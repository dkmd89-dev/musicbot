# tests/test_menu_actions_family.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/family.py
(ARCH-024/P-2, Actions Extraction).

Diese 12 Funktionen wurden 1:1 aus RichMenuSystem._handle_family_*
verschoben - vorher gab es keine dedizierten Tests dafür (nur indirekt
über tests/test_rich_menu_handler_activity_tracking.py, das nur die
Handler-Status-Aufzeichnung prüft, nicht das tatsächliche Callback-
Verhalten). Diese Datei friert das (unveränderte) Verhalten jetzt ein:
Handler vorhanden -> delegiert; Handler fehlt (None) -> Fallback-Text.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import family as family_actions


def _make_update():
    update = Mock()
    update.callback_query = AsyncMock()
    return update


# (action_func, handler_attr_method, fallback_substring)
FAMILY_STATS_CASES = [
    (family_actions.handle_family_stats_top_songs, "handle_family_top_songs", "Top Songs Familie"),
    (family_actions.handle_family_stats_top_artists, "handle_family_top_artists", "Top Künstler Familie"),
    (family_actions.handle_family_stats_member, "handle_family_member_stats", "Statistik pro Person"),
    (family_actions.handle_family_stats_champion, "handle_family_champion", "Musik-Champion"),
    (family_actions.handle_family_stats_listening_times, "handle_family_listening_times", "Hörzeiten"),
    (family_actions.handle_family_stats_monthly_trend, "handle_family_monthly_trend", "Monatsentwicklung"),
]

FAMILY_CHAT_CASES = [
    (family_actions.handle_family_chat_send, "handle_send_message_prompt", "Familien-Chat nicht verfügbar"),
    (family_actions.handle_family_chat_recent, "handle_recent_messages", "Familien-Chat nicht verfügbar"),
    (family_actions.handle_family_chat_notifications, "handle_toggle_notifications", "Familien-Chat nicht verfügbar"),
]

FAMILY_CHALLENGE_CASES = [
    (family_actions.handle_family_challenge_today, "handle_todays_challenge", "Familien-Challenge nicht verfügbar"),
    (family_actions.handle_family_challenge_answer, "handle_answer_prompt", "Familien-Challenge nicht verfügbar"),
    (family_actions.handle_family_challenge_leaderboard, "handle_leaderboard", "Familien-Challenge nicht verfügbar"),
]

ALL_CASES = FAMILY_STATS_CASES + FAMILY_CHAT_CASES + FAMILY_CHALLENGE_CASES


@pytest.mark.asyncio
@pytest.mark.parametrize("action_func,method_name,fallback_text", ALL_CASES)
async def test_delegates_to_handler_when_present(action_func, method_name, fallback_text):
    update = _make_update()
    context = Mock()
    handler = Mock()
    setattr(handler, method_name, AsyncMock())

    await action_func(update, context, handler)

    update.callback_query.answer.assert_awaited_once()
    getattr(handler, method_name).assert_awaited_once_with(update, context)
    update.callback_query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action_func,method_name,fallback_text", ALL_CASES)
async def test_shows_fallback_when_handler_missing(action_func, method_name, fallback_text):
    update = _make_update()
    context = Mock()

    await action_func(update, context, None)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    (text,), _ = update.callback_query.edit_message_text.call_args
    assert fallback_text in text
