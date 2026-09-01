# tests/test_duplicate_handler_telegram.py
# -*- coding: utf-8 -*-
"""
Tests für handlers/duplicate_handler.py::EnhancedDuplicateHandler
(Telegram-Präsentationsschicht) - bislang ohne eigene Testabdeckung
(tests/test_duplicate_handler.py deckt ausschließlich den fachlichen
Kern services/duplicate/detector.py::DuplicateDetector ab, nicht diese
Klasse).

Fokus dieser Datei: die neu verdrahtete error_handler-Integration in
show_statistics_menu()/execute_clear_cache() (error_handler wird von
handlers/menu/rich_menu_handler.py nach der Konstruktion zugewiesen -
self.duplicate_handler.error_handler = self.error_handler). Analog zum
bereits etablierten Muster in handlers/enhanced_status_handler.py/
handlers/menu/rich_menu_system.py: ist error_handler gesetzt, wird er
STATT der bisherigen lokalen Fehlermeldung aufgerufen (kein doppeltes
Benachrichtigen); ohne error_handler bleibt das bisherige Verhalten
unverändert (Nichtregression).
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.duplicate_handler import EnhancedDuplicateHandler
from services.duplicate.detector import DuplicateDetector


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


@pytest.fixture
def handler(tmp_path):
    config = FakeConfig(tmp_path)
    detector = DuplicateDetector(config)
    return EnhancedDuplicateHandler(config, detector)


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestShowStatisticsMenu:
    @pytest.mark.asyncio
    async def test_happy_path_shows_statistics(self, handler):
        update = make_update()
        context = make_context()

        await handler.show_statistics_menu(update, context)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Duplikat-Statistiken" in text

    @pytest.mark.asyncio
    async def test_error_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.detector.get_statistics = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        await handler.show_statistics_menu(update, context)

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "duplicate_statistics_menu"
        assert isinstance(call_args[3], RuntimeError)
        # kein doppeltes Benachrichtigen: die alte lokale Fehlermeldung
        # darf NICHT zusaetzlich gesendet werden.
        update.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_falls_back_to_local_message_without_error_handler(self, handler):
        assert handler.error_handler is None
        handler.detector.get_statistics = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        await handler.show_statistics_menu(update, context)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Fehler beim Laden der Duplikat-Statistiken" in text


class TestExecuteClearCache:
    @pytest.mark.asyncio
    async def test_happy_path_clears_cache(self, handler):
        update = make_update()
        context = make_context()

        await handler.execute_clear_cache(update, context)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Cache geleert" in text

    @pytest.mark.asyncio
    async def test_error_routes_through_error_handler_when_set(self, handler):
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.detector.get_statistics = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        await handler.execute_clear_cache(update, context)

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "duplicate_clear_cache"
        assert isinstance(call_args[3], RuntimeError)
        update.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_falls_back_to_local_message_without_error_handler(self, handler):
        assert handler.error_handler is None
        handler.detector.get_statistics = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        await handler.execute_clear_cache(update, context)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Fehler beim Löschen des Duplikat-Cache" in text
