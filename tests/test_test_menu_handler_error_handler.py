# tests/test_test_menu_handler_error_handler.py
# -*- coding: utf-8 -*-
"""
Tests für die EnhancedErrorHandler-Integration in
handlers/test_menu_handler.py::TestMenuHandler.

Analog zum bereits etablierten Muster (siehe navidrome_menu_handler.py,
duplicate_handler.py, enhanced_logger_menu_handler.py): ist error_handler
gesetzt (wird von handlers/menu/rich_menu_handler.py nach der Konstruktion
zugewiesen - self.test_handler.error_handler = self.error_handler), wird er
STATT der bisherigen lokalen Fehlermeldung aufgerufen; ohne error_handler
bleibt das bisherige Verhalten unveraendert (Nichtregression).

Besonderheit dieses Handlers: _execute_test_run() und _show_test_results()
hatten urspruenglich KEINEN context-Parameter (nur die drei oeffentlichen
Einstiegspunkte run_unit_tests/run_integration_tests/run_performance_tests
erhalten context von RichMenuHandler). Fuer die Integration wurde context
als optionaler Parameter (Default None) ergaenzt und von den drei
Einstiegspunkten durchgereicht - ohne context (z.B. bei bestehenden direkten
Aufrufen dieser internen Methoden ohne Context-Objekt) greift immer der
lokale Fallback, da EnhancedErrorHandler.handle_exception ohne
telegram_context keine Nutzerbenachrichtigung verschickt.
"""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from handlers.test_menu_handler import TestMenuHandler


def run_async(coro):
    return asyncio.run(coro)


class FakeConfig:
    def __init__(self, base_dir):
        self.BASE_DIR = str(base_dir)


def make_handler(tmp_path, create_dirs=None):
    config = FakeConfig(tmp_path)
    handler = TestMenuHandler(config, logger_factory=lambda name: Mock())

    if create_dirs:
        for subdir, filenames in create_dirs:
            d = tmp_path / "tests" / subdir
            d.mkdir(parents=True, exist_ok=True)
            for fn in filenames:
                (d / fn).write_text("def test_x(): pass\n")

    return handler


def make_update(user_id=123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _sent_text(mock_edit_message_text: AsyncMock) -> str:
    args, kwargs = mock_edit_message_text.call_args
    return args[0] if args else kwargs.get("text", "")


class TestExecuteTestRunErrorHandling:
    """_execute_test_run: context wird von den drei public Einstiegspunkten
    durchgereicht."""

    def test_routes_through_error_handler_when_context_present(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=RuntimeError("boom"))
        )
        update = make_update()
        context = Mock()

        run_async(handler.run_unit_tests(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "test_run_unit"
        assert isinstance(call_args[3], RuntimeError)
        # kein doppeltes Benachrichtigen ueber die urspruengliche lokale
        # Fehlermeldung hinaus (der einzige edit_message_text-Aufruf ist der
        # "Starte..."-Zwischenstand, keine weitere Fehlermeldung danach)
        last_text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler bei der Ausführung" not in last_text

    def test_falls_back_to_local_message_without_error_handler(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        assert handler.error_handler is None
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=RuntimeError("boom"))
        )
        update = make_update()
        context = Mock()

        run_async(handler.run_unit_tests(update, context))

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler bei der Ausführung" in text

    def test_falls_back_to_local_message_without_context(self, tmp_path, monkeypatch):
        """Direkter Aufruf ohne context (bestehendes Testmuster) - auch mit
        gesetztem error_handler muss der lokale Fallback greifen, da ohne
        telegram_context keine Benachrichtigung moeglich ist."""
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=RuntimeError("boom"))
        )
        update = make_update()

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        handler.error_handler.handle_callback_error.assert_not_awaited()
        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler bei der Ausführung" in text


class TestShowAllTestResultsErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler = make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.test_results_cache = {"unit": Mock(get=Mock(side_effect=RuntimeError("boom")))}
        update = make_update()
        context = Mock()

        run_async(handler.show_all_test_results(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "test_all_results"
        assert isinstance(call_args[3], RuntimeError)

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler = make_handler(tmp_path)
        assert handler.error_handler is None
        handler.test_results_cache = {"unit": Mock(get=Mock(side_effect=RuntimeError("boom")))}
        update = make_update()
        context = Mock()

        run_async(handler.show_all_test_results(update, context))

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler beim Laden der Übersicht" in text


class TestRunAllTestsErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler = make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._run_test_type = AsyncMock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = Mock()

        run_async(handler.run_all_tests(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "test_run_all"
        assert isinstance(call_args[3], RuntimeError)

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler = make_handler(tmp_path)
        assert handler.error_handler is None
        handler._run_test_type = AsyncMock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = Mock()

        run_async(handler.run_all_tests(update, context))

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Fehler bei der Ausführung der Test-Suite" in text
