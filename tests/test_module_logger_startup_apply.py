# -*- coding: utf-8 -*-
"""
CC-LOGGER-L4, Stufe 0 — Tests für den Startup-Apply-Fix in
`ModuleLoggerManager._load_module_configs()`.

**Vor L4:** die JSON wurde geladen, aber NICHT angewendet — persistierte
Level/Handler waren für den laufenden Prozess wirkungslos.

**Nach L4:** `_load_module_configs()` ruft für jedes geladene Modul
`_apply_module_config()` auf. Der Runtime-Zustand entspricht nach dem
Bot-Start der persistierten Konfiguration.

**Isolation:** ModuleLoggerManager hält `data/module_logger_config.json`
als hartcodierten relativen Pfad (kein Config-Attribut). Wir leiten ihn
per Path-Side-Effect um — identisches Muster wie in
`tests/test_enhanced_logger_menu_handler_module_toggle.py`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path as RealPath
from unittest.mock import patch

import pytest

from handlers.enhanced_logger_menu_handler import ModuleLoggerManager


class FakeConfig:
    def __init__(self, log_dir: Path):
        self.LOG_DIR = str(log_dir)


def _make_fake_path(config_file: Path):
    def _fake_path(arg=None, *args, **kwargs):
        if arg == "data/module_logger_config.json":
            return config_file
        if arg is None:
            return RealPath(*args, **kwargs)
        return RealPath(arg, *args, **kwargs)
    return _fake_path


_TEST_MODULES = [
    "StartupApplyTest_ModA",
    "StartupApplyTest_ModB",
    "StartupApplyTest_ModDisabled",
    "StartupApplyTest_ModConsoleOnly",
    "StartupApplyTest_ModNoHandlers",
]


@pytest.fixture
def isolated_config(tmp_path: Path) -> Path:
    return tmp_path / "module_logger_config.json"


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _cleanup_real_loggers():
    """Entfernt Handler + setzt Level/disabled aller in den Tests
    verwendeten Logger zurück — sonst leaken sie über Testfälle hinweg
    (logging.Logger ist ein globales Singleton pro Name)."""
    yield
    for n in _TEST_MODULES:
        logger = logging.getLogger(n)
        for h in logger.handlers[:]:
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        logger.disabled = False
        logger.setLevel(logging.NOTSET)


def _manager(isolated_config: Path, log_dir: Path) -> ModuleLoggerManager:
    with patch(
        "handlers.enhanced_logger_menu_handler.Path",
        side_effect=_make_fake_path(isolated_config),
    ):
        return ModuleLoggerManager(FakeConfig(log_dir))


def _write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _cfg(**overrides) -> dict:
    base = {
        "enabled": True,
        "level": "INFO",
        "file_handler": True,
        "console_handler": True,
        "custom_format": None,
    }
    base.update(overrides)
    return base


# =====================================================================
# Startup-Apply — der eigentliche Fix
# =====================================================================

class TestStartupApplyLevel:
    def test_module_level_is_applied(self, isolated_config: Path, log_dir: Path) -> None:
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModA": _cfg(level="DEBUG")},
        )
        _manager(isolated_config, log_dir)
        assert logging.getLogger("StartupApplyTest_ModA").level == logging.DEBUG

    def test_unknown_level_falls_back_to_info(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        """Ungültiger Level-String → getattr(logging, level, INFO)-Fallback
        im bestehenden _apply_module_config(). Kein Crash."""
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModA": _cfg(level="NOT_A_REAL_LEVEL")},
        )
        _manager(isolated_config, log_dir)
        assert logging.getLogger("StartupApplyTest_ModA").level == logging.INFO


class TestStartupApplyHandlers:
    def test_file_handler_is_attached_when_enabled(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModA": _cfg(file_handler=True, console_handler=False)},
        )
        _manager(isolated_config, log_dir)
        handlers = [
            h
            for h in logging.getLogger("StartupApplyTest_ModA").handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(handlers) == 1

    def test_file_handler_is_not_attached_when_disabled_in_config(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModNoHandlers": _cfg(file_handler=False)},
        )
        _manager(isolated_config, log_dir)
        handlers = [
            h
            for h in logging.getLogger("StartupApplyTest_ModNoHandlers").handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert handlers == []

    def test_console_handler_is_attached_when_enabled(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModConsoleOnly": _cfg(console_handler=True, file_handler=False)},
        )
        _manager(isolated_config, log_dir)
        handlers = [
            h
            for h in logging.getLogger("StartupApplyTest_ModConsoleOnly").handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(handlers) == 1


class TestStartupApplyDisabledModule:
    def test_disabled_module_sets_logger_disabled(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModDisabled": _cfg(enabled=False)},
        )
        _manager(isolated_config, log_dir)
        assert logging.getLogger("StartupApplyTest_ModDisabled").disabled is True


class TestStartupApplyMultipleModules:
    def test_all_modules_are_applied(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        _write_config(
            isolated_config,
            {
                "StartupApplyTest_ModA": _cfg(level="DEBUG", file_handler=False, console_handler=False),
                "StartupApplyTest_ModB": _cfg(level="WARNING", file_handler=False, console_handler=False),
            },
        )
        _manager(isolated_config, log_dir)
        assert logging.getLogger("StartupApplyTest_ModA").level == logging.DEBUG
        assert logging.getLogger("StartupApplyTest_ModB").level == logging.WARNING

    def test_one_bad_module_does_not_block_others(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        """Defensiv: ein Modul mit unvollständigem/fehlerhaftem Config-
        Dict darf die anderen Module nicht mitreißen. Der bestehende
        _apply_module_config()-Body fängt Modul-Fehler intern ab."""
        _write_config(
            isolated_config,
            {
                "StartupApplyTest_ModA": _cfg(level="DEBUG", file_handler=False, console_handler=False),
                # Fehlende Keys — _apply_module_config nutzt get()-Defaults
                "StartupApplyTest_ModB": {"enabled": True},
            },
        )
        _manager(isolated_config, log_dir)
        assert logging.getLogger("StartupApplyTest_ModA").level == logging.DEBUG


# =====================================================================
# Idempotenz / wiederholtes Laden
# =====================================================================

class TestStartupApplyIdempotent:
    def test_repeated_load_does_not_double_handlers(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        """Zweiter Manager-Init auf derselben Config darf FileHandler
        nicht doppelt anhängen (has_file_handler-Check greift)."""
        _write_config(
            isolated_config,
            {"StartupApplyTest_ModA": _cfg(file_handler=True, console_handler=False)},
        )
        _manager(isolated_config, log_dir)
        _manager(isolated_config, log_dir)
        handlers = [
            h
            for h in logging.getLogger("StartupApplyTest_ModA").handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(handlers) == 1


# =====================================================================
# Edge Cases — Verhalten unverändert gegenüber vor-L4
# =====================================================================

class TestEdgeCasesUnchanged:
    def test_missing_file_writes_default_config_and_applies_it(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        """Fehlende Datei → Defaults werden geschrieben UND (neu in L4)
        direkt angewendet. Die Default-Config enthält u. a. NavidromeHandler
        mit level=DEBUG."""
        assert not isolated_config.exists()
        _manager(isolated_config, log_dir)
        assert isolated_config.exists()
        # Debug aus Default-Config ist auf den realen Logger angewendet.
        assert logging.getLogger("NavidromeHandler").level == logging.DEBUG
        # Cleanup für diesen Test (nicht in _TEST_MODULES enthalten)
        lgr = logging.getLogger("NavidromeHandler")
        for h in lgr.handlers[:]:
            lgr.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        lgr.setLevel(logging.NOTSET)

    def test_empty_json_object_is_loaded_and_no_module_applied(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        isolated_config.write_text("{}", encoding="utf-8")
        mgr = _manager(isolated_config, log_dir)
        assert mgr.module_configs == {}

    def test_corrupt_json_does_not_crash(
        self, isolated_config: Path, log_dir: Path
    ) -> None:
        """Korrupte JSON → Exception wird gefangen (bestehender outer try),
        Manager bleibt konstruierbar, module_configs ist leer."""
        isolated_config.write_text("{ this is not valid JSON", encoding="utf-8")
        mgr = _manager(isolated_config, log_dir)
        assert isinstance(mgr, ModuleLoggerManager)
        assert mgr.module_configs == {}
