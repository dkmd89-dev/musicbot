# tests/test_enhanced_logger_menu_handler_error_handler.py
# -*- coding: utf-8 -*-
"""
Tests für die EnhancedErrorHandler-Integration in
handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler.

Analog zum bereits etablierten Muster in handlers/enhanced_status_handler.py/
handlers/menu/rich_menu_system.py sowie den neueren Integrationen in
handlers/navidrome_menu_handler.py und handlers/duplicate_handler.py: ist
error_handler gesetzt (wird von handlers/menu/rich_menu_handler.py nach der
Konstruktion zugewiesen - self.logger_handler.error_handler =
self.error_handler), wird er STATT der bisherigen lokalen Fehlerbehandlung
aufgerufen (kein doppeltes Benachrichtigen); ohne error_handler bleibt das
bisherige Verhalten unveraendert (Nichtregression).

Die Datei deckt die drei in enhanced_logger_menu_handler.py vorkommenden
except-Varianten ab:
- kein bisheriger Nutzer-Fallback, nur Logging (show_main_menu)
- Fallback ueber die gemeinsame _show_error_message()-Hilfsmethode
  (show_comprehensive_statistics, toggle_module)
- Fallback ueber ein direktes callback_query.answer(...) (set_global_log_level)
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import TelegramError

from handlers.enhanced_logger_menu_handler import EnhancedLoggerMenuHandler


class FakeConfig:
    def __init__(self, log_dir):
        self.LOG_DIR = str(log_dir)


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def handler(log_dir):
    return EnhancedLoggerMenuHandler(FakeConfig(log_dir))


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.answer = AsyncMock()
    return update


def make_context():
    return Mock()


def _sent_text(mock_edit_message_text: AsyncMock) -> str:
    args, kwargs = mock_edit_message_text.call_args
    return args[0] if args else kwargs.get("text", "")


class TestShowMainMenuErrorHandling:
    """show_main_menu: kein bisheriger Nutzer-Fallback, nur Logging.

    show_main_menu faengt gezielt nur TelegramError (nicht die breitere
    Exception) - der Ausloeser muss daher eine TelegramError sein, damit
    ueberhaupt der bestehende except-Zweig greift (unveraendertes,
    vorbestehendes Verhalten, nicht Teil dieser Aenderung).
    """

    def test_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=TelegramError("boom")
        )
        context = make_context()

        asyncio.run(handler.show_main_menu(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "logger_main_menu"
        assert isinstance(call_args[3], TelegramError)

    def test_without_error_handler_only_logs_unchanged(self, handler):
        assert handler.error_handler is None
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=TelegramError("boom")
        )
        context = make_context()

        # Vor dieser Aenderung wurde der Fehler nur geloggt, keine weitere
        # Telegram-Nachricht gesendet - dieses Verhalten bleibt erhalten
        # (kein zweiter edit_message_text-Aufruf ueber diesen einen
        # fehlschlagenden hinaus).
        asyncio.run(handler.show_main_menu(update, context))

        assert update.callback_query.edit_message_text.await_count == 1


class TestShowComprehensiveStatisticsErrorHandling:
    """show_comprehensive_statistics: Fallback ueber _show_error_message()."""

    def test_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._collect_comprehensive_stats = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_comprehensive_statistics(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "logger_global_stats"
        assert isinstance(call_args[3], RuntimeError)
        update.callback_query.edit_message_text.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, handler):
        assert handler.error_handler is None
        handler._collect_comprehensive_stats = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_comprehensive_statistics(update, context))

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler beim Laden der Statistiken" in text


class TestToggleModuleErrorHandling:
    """toggle_module: ebenfalls Fallback ueber _show_error_message()."""

    def test_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.module_manager.get_module_config = Mock(
            side_effect=RuntimeError("boom")
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.toggle_module(update, context, "TestModule"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "logger_toggle_module"
        assert isinstance(call_args[3], RuntimeError)
        update.callback_query.edit_message_text.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, handler):
        assert handler.error_handler is None
        handler.module_manager.get_module_config = Mock(
            side_effect=RuntimeError("boom")
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.toggle_module(update, context, "TestModule"))

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler beim Umschalten" in text


class TestSetGlobalLogLevelErrorHandling:
    """set_global_log_level: Fallback ueber ein direktes callback_query.answer()."""

    def test_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.logger.info = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        asyncio.run(handler.set_global_log_level(update, context, "DEBUG"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "logger_set_global_level"
        assert isinstance(call_args[3], RuntimeError)
        update.callback_query.answer.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, handler):
        assert handler.error_handler is None
        handler.logger.info = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        asyncio.run(handler.set_global_log_level(update, context, "DEBUG"))

        update.callback_query.answer.assert_awaited_once_with(
            "❌ Fehler beim Setzen des Log-Levels"
        )
