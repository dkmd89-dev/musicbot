# tests/test_menu_actions_duplicates.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/duplicates.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_duplicate_callback.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions.duplicates import handle_duplicate_callback


def _make_update():
    update = Mock()
    update.callback_query = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_no_handler_shows_unavailable():
    update = _make_update()
    await handle_duplicate_callback(update, Mock(), "dup:show_stats", None, Mock())
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Duplicate-Handler nicht verfügbar"
    )


@pytest.mark.asyncio
async def test_show_stats_delegates():
    update = _make_update()
    handler = Mock()
    handler.show_statistics_menu = AsyncMock()
    await handle_duplicate_callback(update, Mock(), "dup:show_stats", handler, Mock())
    update.callback_query.answer.assert_awaited_once_with("Lade Statistiken...")
    handler.show_statistics_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_cache_confirm_delegates():
    update = _make_update()
    handler = Mock()
    handler.show_clear_cache_confirm = AsyncMock()
    await handle_duplicate_callback(
        update, Mock(), "dup:clear_cache_confirm", handler, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with()
    handler.show_clear_cache_confirm.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_cache_execute_delegates():
    update = _make_update()
    handler = Mock()
    handler.execute_clear_cache = AsyncMock()
    await handle_duplicate_callback(
        update, Mock(), "dup:clear_cache_execute", handler, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("Cache wird geleert...")
    handler.execute_clear_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_callback_shows_not_implemented():
    update = _make_update()
    handler = Mock()
    await handle_duplicate_callback(update, Mock(), "dup:unknown", handler, Mock())
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Funktion nicht implementiert"
    )
