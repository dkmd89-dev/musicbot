# -*- coding: utf-8 -*-
"""
CC-LOGGER-L7.1 — Tests fuer `logger.py::setup_module_logging()` und
die zwei Aufrufer, die seit L7.1 die persistierte Logger-Config
respektieren.

Hintergrund (Finding): `setup_module_logging()` hat vor L7.1 `level`
hart gesetzt und IMMER einen FileHandler + ConsoleHandler angehaengt -
egal was in `data/module_logger_config.json` stand. Zwei Aufrufer
(`EnhancedMetadataProcessor`, `EnhancedLoggerMenuHandler`) haben damit
die Config-Werte ueberschrieben, sobald sie nach dem
`_load_module_configs()`-Lauf konstruiert wurden.

Fix: `setup_module_logging()` hat zwei additive Parameter
(`enable_file_handler`, `enable_console_handler`) mit Default `True`;
die zwei Aufrufer lesen `read_logger_config()` und uebergeben die
konkreten Werte. Fallback-Werte bleiben identisch zum bisherigen
Verhalten.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import logger as logger_module
from logger import setup_module_logging


# =====================================================================
# Basis-Tests: setup_module_logging() respektiert die neuen Flags
# =====================================================================


_TEST_NAMES = (
    "SetupTest_Default",
    "SetupTest_FileOff",
    "SetupTest_ConsoleOff",
    "SetupTest_BothOff",
    "SetupTest_Rotation",
    "SetupTest_Reinit",
)


@pytest.fixture(autouse=True)
def _cleanup_test_loggers():
    yield
    for name in _TEST_NAMES:
        lgr = logging.getLogger(name)
        for h in lgr.handlers[:]:
            lgr.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        logger_module._module_loggers.pop(name, None)


def _handler_kinds(name: str) -> list[str]:
    return sorted(type(h).__name__ for h in logging.getLogger(name).handlers)


def _mk(log_file: Path):
    return str(log_file)


class TestSetupModuleLoggingFlags:
    def test_default_unchanged(self, tmp_path: Path) -> None:
        """Ohne neue Parameter: Verhalten wie bisher - beide Handler."""
        setup_module_logging("SetupTest_Default", _mk(tmp_path / "a.log"), level="INFO")
        kinds = _handler_kinds("SetupTest_Default")
        assert "EnhancedRotatingFileHandler" in kinds
        assert "StreamHandler" in kinds

    def test_file_handler_off(self, tmp_path: Path) -> None:
        setup_module_logging(
            "SetupTest_FileOff", _mk(tmp_path / "b.log"),
            level="INFO", enable_file_handler=False,
        )
        kinds = _handler_kinds("SetupTest_FileOff")
        assert "EnhancedRotatingFileHandler" not in kinds
        assert "StreamHandler" in kinds

    def test_console_handler_off(self, tmp_path: Path) -> None:
        setup_module_logging(
            "SetupTest_ConsoleOff", _mk(tmp_path / "c.log"),
            level="INFO", enable_console_handler=False,
        )
        kinds = _handler_kinds("SetupTest_ConsoleOff")
        assert "EnhancedRotatingFileHandler" in kinds
        assert "StreamHandler" not in kinds

    def test_both_off(self, tmp_path: Path) -> None:
        setup_module_logging(
            "SetupTest_BothOff", _mk(tmp_path / "d.log"),
            level="INFO",
            enable_file_handler=False, enable_console_handler=False,
        )
        assert _handler_kinds("SetupTest_BothOff") == []

    def test_rotation_class_preserved(self, tmp_path: Path) -> None:
        """Kernvertrag: die Rotation darf nicht auf einen plain
        logging.FileHandler zurueckfallen."""
        setup_module_logging("SetupTest_Rotation", _mk(tmp_path / "e.log"), level="INFO")
        kinds = _handler_kinds("SetupTest_Rotation")
        assert "EnhancedRotatingFileHandler" in kinds
        assert "FileHandler" not in kinds  # Kein plain FileHandler


# =====================================================================
# Reihenfolge-Unabhaengigkeit: setup_module_logging() nach Config-Apply
# =====================================================================


class TestOrderIndependence:
    """Kernanforderung aus dem L7.1-Analyse-Prompt (Abschnitt 5):
    egal in welcher Reihenfolge - die persistierte Config muss gewinnen."""

    def test_config_apply_after_setup(self, tmp_path: Path) -> None:
        """Simuliert Szenario A: setup_module_logging() zuerst, dann
        _apply_module_config(). Letzteres entfernt den FileHandler,
        weil die Config file_handler=false sagt."""
        # setup mit aktiviertem FileHandler (Config sagt spaeter: false)
        setup_module_logging(
            "SetupTest_Reinit", _mk(tmp_path / "f.log"),
            level="DEBUG", enable_file_handler=True,
        )
        assert "EnhancedRotatingFileHandler" in _handler_kinds("SetupTest_Reinit")

        # Config-Apply simulieren: entfernt den FileHandler (analog
        # _apply_module_config() mit config["file_handler"]=False)
        lgr = logging.getLogger("SetupTest_Reinit")
        for h in lgr.handlers[:]:
            if isinstance(h, logging.FileHandler):
                lgr.removeHandler(h)

        assert "EnhancedRotatingFileHandler" not in _handler_kinds("SetupTest_Reinit")

    def test_config_before_setup(self, tmp_path: Path) -> None:
        """Szenario B: Config-Apply zuerst (siehe oben), dann setup mit
        enable_file_handler=False - FileHandler darf nicht wiederkehren."""
        setup_module_logging(
            "SetupTest_Reinit", _mk(tmp_path / "g.log"),
            level="DEBUG", enable_file_handler=False, enable_console_handler=False,
        )
        assert _handler_kinds("SetupTest_Reinit") == []


# =====================================================================
# Sonderfaelle: die zwei Aufrufer lesen read_logger_config()
# =====================================================================


class TestCallersReadConfig:
    """Prufft, dass beide Aufrufer die persistierte Config lesen und
    die Werte an setup_module_logging() weiterreichen."""

    def _write_config(self, data_dir: Path, module_name: str, cfg: dict) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "module_logger_config.json").write_text(
            json.dumps({module_name: cfg}), encoding="utf-8"
        )

    def test_handler_reads_config(self, tmp_path: Path) -> None:
        """EnhancedLoggerMenuHandler mit file_handler=false, level=INFO."""
        from services.logger_admin import read_logger_config

        data_dir = tmp_path / "data_handler"

        class FakeConfig:
            DATA_DIR = str(data_dir)
            LOG_DIR = str(tmp_path / "logs")

        self._write_config(
            data_dir, "EnhancedLoggerHandler",
            {"enabled": True, "level": "INFO", "file_handler": False,
             "console_handler": True, "custom_format": None},
        )

        _cfg = read_logger_config(FakeConfig()).get("EnhancedLoggerHandler", {})
        setup_module_logging(
            "SetupTest_Reinit",
            _mk(tmp_path / "h.log"),
            level=_cfg.get("level", "DEBUG"),
            enable_file_handler=_cfg.get("file_handler", True),
            enable_console_handler=_cfg.get("console_handler", True),
        )

        lgr = logging.getLogger("SetupTest_Reinit")
        assert logging.getLevelName(lgr.level) == "INFO"
        assert "EnhancedRotatingFileHandler" not in _handler_kinds("SetupTest_Reinit")

    def test_metadata_processor_reads_config(self, tmp_path: Path) -> None:
        """EnhancedMetadataProcessor mit file_handler=false,
        console_handler=false, level=WARNING."""
        from services.logger_admin import read_logger_config

        data_dir = tmp_path / "data_meta"

        class FakeConfig:
            DATA_DIR = str(data_dir)
            LOG_DIR = str(tmp_path / "logs")

        self._write_config(
            data_dir, "EnhancedMetadataProcessor",
            {"enabled": True, "level": "WARNING", "file_handler": False,
             "console_handler": False, "custom_format": None},
        )

        _cfg = read_logger_config(FakeConfig()).get("EnhancedMetadataProcessor", {})
        setup_module_logging(
            "SetupTest_Reinit",
            _mk(tmp_path / "i.log"),
            level=_cfg.get("level", "DEBUG"),
            enable_file_handler=_cfg.get("file_handler", True),
            enable_console_handler=_cfg.get("console_handler", True),
        )

        lgr = logging.getLogger("SetupTest_Reinit")
        assert logging.getLevelName(lgr.level) == "WARNING"
        assert _handler_kinds("SetupTest_Reinit") == []

    def test_fallback_when_config_missing(self, tmp_path: Path) -> None:
        """Modul nicht in Config -> Fallback-Werte = bisheriges Verhalten."""
        from services.logger_admin import read_logger_config

        class FakeConfig:
            DATA_DIR = str(tmp_path / "data_empty")
            LOG_DIR = str(tmp_path / "logs")

        _cfg = read_logger_config(FakeConfig()).get("NotInConfig", {})
        setup_module_logging(
            "SetupTest_Reinit",
            _mk(tmp_path / "j.log"),
            level=_cfg.get("level", "DEBUG"),
            enable_file_handler=_cfg.get("file_handler", True),
            enable_console_handler=_cfg.get("console_handler", True),
        )

        lgr = logging.getLogger("SetupTest_Reinit")
        assert logging.getLevelName(lgr.level) == "DEBUG"
        kinds = _handler_kinds("SetupTest_Reinit")
        assert "EnhancedRotatingFileHandler" in kinds
        assert "StreamHandler" in kinds
