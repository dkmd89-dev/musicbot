# tests/test_menu_actions_stats.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/stats.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_stats_*/RichMenuHandler._handle_*_stats_wrapper.

ARCH-025: die vormals hier mitgetesteten toten "_system"-Funktionen
(handle_stats_monthly_system/_timeline_system u. a.) wurden nach
Verifikation entfernt (siehe handlers/menu/actions/stats.py-Docstring) -
ihre Tests (test_stats_monthly_system_delegates/
test_stats_monthly_system_fallback_without_handler/
test_stats_timeline_system_requires_hasattr) sind mit ihnen entfallen.
test_stats_library_overview_delegates bleibt (einzige weiterhin live
genutzte "_system"-artige Funktion).
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import stats as stats_actions


def _make_update():
    update = Mock()
    update.callback_query = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_stats_library_overview_delegates():
    update = _make_update()
    handler = Mock()
    handler.handle_library_overview = AsyncMock()
    await stats_actions.handle_stats_library_overview(update, Mock(), handler)
    handler.handle_library_overview.assert_awaited_once()


@pytest.mark.asyncio
async def test_stats_library_overview_fallback_without_handler():
    update = _make_update()
    await stats_actions.handle_stats_library_overview(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once_with(
        "📚 Lade Library-Übersicht..."
    )


# ---- RichMenuHandler-Seite (live, mit try/except) ----


@pytest.mark.asyncio
async def test_monthly_wrapper_delegates_when_hasattr():
    update = _make_update()
    handler = Mock()
    handler.handle_month_review = AsyncMock()
    await stats_actions.handle_monthly_stats_wrapper(update, Mock(), handler, Mock())
    handler.handle_month_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_monthly_wrapper_placeholder_without_hasattr():
    update = _make_update()
    handler = object()
    await stats_actions.handle_monthly_stats_wrapper(update, Mock(), handler, Mock())
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Monatsrückblick" in text
    assert "gerade entwickelt" in text


@pytest.mark.asyncio
async def test_monthly_wrapper_catches_exception_and_logs():
    update = _make_update()
    handler = Mock()
    handler.handle_month_review = AsyncMock(side_effect=RuntimeError("boom"))
    logger = Mock()
    await stats_actions.handle_monthly_stats_wrapper(update, Mock(), handler, logger)
    logger.error.assert_called_once()
    update.callback_query.edit_message_text.assert_awaited_once_with(
        "❌ Fehler beim Laden der Statistiken"
    )


@pytest.mark.asyncio
async def test_top_songs_wrapper_answers_with_loading_text():
    update = _make_update()
    handler = Mock()
    handler.handle_top_songs = AsyncMock()
    await stats_actions.handle_top_songs_wrapper(update, Mock(), handler, Mock())
    update.callback_query.answer.assert_awaited_once_with("Lade Top Songs ...")
    args, kwargs = handler.handle_top_songs.call_args
    assert kwargs.get("period") == "month"
