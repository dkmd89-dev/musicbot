# tests/test_enhanced_logger_menu_handler_module_toggle.py
# -*- coding: utf-8 -*-
"""
Regressionstest für den Toggle-Bug in
handlers/enhanced_logger_menu_handler.py::ModuleLoggerManager/toggle_module().

Live-Fund (Nutzer-Report): das Aktivieren eines Moduls im Inline-Button-Menü
("🔄 Toggle Debug") fuehrte NICHT dazu, dass eine dedizierte Log-Datei
geschrieben wurde. Root Cause: toggle_module() togglete bisher
config["enabled"] statt config["file_handler"]. Fuer jedes real aktive,
aber noch nie konfigurierte Modul (get_module_config() liefert per Default
enabled=True) fuehrte der allererste Klick zu enabled=False -
_apply_module_config() behandelt enabled=False als kompletten
Logger-Stopp (logger.disabled = True; return) und erreicht die
FileHandler-Logik gar nicht erst - das Modul wurde dadurch stummgeschaltet
statt eine Log-Datei zu bekommen. Reproduziert per Skript vor diesem Fix
(logger.disabled=True, logger.handlers=[] nach dem "Aktivieren").

Isolation: ModuleLoggerManager haelt data/module_logger_config.json als
hartcodierten, relativen Pfad (kein Config-Attribut) - wie beim etablierten
Muster in tests/test_rich_menu_handler*.py wird dafuer Path innerhalb des
Zielmoduls per side_effect umgeleitet, damit kein Test die echte Datei im
Repo beschreibt.
"""

import asyncio
import logging
from pathlib import Path as RealPath
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.enhanced_logger_menu_handler import (
    EnhancedLoggerMenuHandler,
    ModuleLoggerManager,
    _module_loggers,
)
from logger import get_module_logger


class FakeConfig:
    def __init__(self, log_dir):
        self.LOG_DIR = str(log_dir)


def _make_fake_path(tmp_path):
    def _fake_path(arg=None, *args, **kwargs):
        if arg == "data/module_logger_config.json":
            return tmp_path / "module_logger_config.json"
        if arg is None:
            return RealPath(*args, **kwargs)
        return RealPath(arg, *args, **kwargs)

    return _fake_path


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def handler(tmp_path, log_dir):
    with patch(
        "handlers.enhanced_logger_menu_handler.Path",
        side_effect=_make_fake_path(tmp_path),
    ):
        h = EnhancedLoggerMenuHandler(FakeConfig(log_dir))
    return h


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.answer = AsyncMock()
    return update


def make_context():
    return Mock()


@pytest.fixture(autouse=True)
def _cleanup_real_logger():
    """Stellt sicher, dass Handler eines Test-Modul-Loggers nach jedem Test
    entfernt werden - sonst leaken sie über Testfälle hinweg (logging.Logger
    ist ein globales Singleton pro Name)."""
    yield
    for name in ("RealTestModuleXYZ", "AlreadyConfiguredModule"):
        logger = logging.getLogger(name)
        for h in logger.handlers[:]:
            logger.removeHandler(h)
        logger.disabled = False
        _module_loggers.pop(name, None)


class TestToggleModuleActivatesFileLoggingForNeverConfiguredModule:
    """Kernszenario: ein real aktives Modul, das noch nie über das Menü
    konfiguriert wurde (typischer Fall - alle echten Handler/Services)."""

    def test_first_toggle_attaches_a_file_handler(self, handler, log_dir):
        # Simuliert einen echten, bereits aktiven Produktions-Logger (wie
        # ihn jeder Handler ueber get_module_logger() erzeugt) - noch nie
        # im Menü konfiguriert.
        get_module_logger("RealTestModuleXYZ")
        real_logger = logging.getLogger("RealTestModuleXYZ")
        assert real_logger.disabled is False
        assert real_logger.handlers == []

        update = make_update()
        asyncio.run(handler.toggle_module(update, make_context(), "RealTestModuleXYZ"))

        # Der Logger darf NICHT stummgeschaltet werden ...
        assert real_logger.disabled is False
        # ... und muss jetzt tatsächlich einen FileHandler haben.
        file_handlers = [
            h for h in real_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1

    def test_second_toggle_removes_the_file_handler_again(self, handler, log_dir):
        get_module_logger("RealTestModuleXYZ")
        real_logger = logging.getLogger("RealTestModuleXYZ")

        update = make_update()
        asyncio.run(handler.toggle_module(update, make_context(), "RealTestModuleXYZ"))
        asyncio.run(handler.toggle_module(update, make_context(), "RealTestModuleXYZ"))

        assert real_logger.disabled is False
        file_handlers = [
            h for h in real_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert file_handlers == []

    def test_toggle_never_disables_the_underlying_logger(self, handler, log_dir):
        """Kern-Regression: enabled darf durch toggle_module() nicht mehr
        angefasst werden - das Modul soll unabhaengig vom Datei-Logging
        immer weiter (z. B. an logs/bot.log) loggen koennen."""
        get_module_logger("RealTestModuleXYZ")
        real_logger = logging.getLogger("RealTestModuleXYZ")

        update = make_update()
        for _ in range(3):
            asyncio.run(
                handler.toggle_module(update, make_context(), "RealTestModuleXYZ")
            )
            assert real_logger.disabled is False


class TestToggleModuleHealsAlreadyBrokenConfig:
    """Ein Modul, dessen gespeicherte Konfiguration von einem frueheren
    Klick unter dem alten, fehlerhaften Verhalten bereits enabled=False
    trägt (persistiert in data/module_logger_config.json) - der naechste
    Klick muss den Logger wieder aktivieren statt ihn stumm zu lassen."""

    def test_toggle_reenables_a_previously_disabled_module(self, handler, log_dir):
        get_module_logger("AlreadyConfiguredModule")
        real_logger = logging.getLogger("AlreadyConfiguredModule")

        # Zustand, wie ihn das alte, fehlerhafte toggle_module() hinterlassen
        # haben koennte.
        broken_config = {
            "enabled": False,
            "level": "INFO",
            "file_handler": True,
            "console_handler": True,
            "custom_format": None,
        }
        handler.module_manager.set_module_config(
            "AlreadyConfiguredModule", broken_config
        )
        assert real_logger.disabled is True

        update = make_update()
        asyncio.run(
            handler.toggle_module(update, make_context(), "AlreadyConfiguredModule")
        )

        assert real_logger.disabled is False


class TestModuleLoggerManagerFileHandlerHelper:
    """Isolierter Test der reinen Config-Ebene (ohne Telegram-Update)."""

    def test_get_module_config_default_file_handler_is_true_but_not_yet_applied(
        self, tmp_path
    ):
        with patch(
            "handlers.enhanced_logger_menu_handler.Path",
            side_effect=_make_fake_path(tmp_path),
        ):
            manager = ModuleLoggerManager(FakeConfig(tmp_path))
        config = manager.get_module_config("NeverSeenModule")
        assert config["file_handler"] is True
        # Der Default ist rein notionell - der echte Logger hat noch
        # keinerlei Handler, bis set_module_config() ihn tatsaechlich anwendet.
        assert logging.getLogger("NeverSeenModule").handlers == []
