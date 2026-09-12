# tests/test_menu_actions_navidrome.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/navidrome.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_navidrome_*/_handle_navidrome_callback.

Deckt die Wrapper-Funktionen (Handler vorhanden/fehlt) und eine
Stichprobe der _handle_navidrome_callback-Routingtabelle ab (jeder
Zweig war vorher ebenfalls ungetestet - reine Neu-Charakterisierung des
unveränderten Ist-Verhaltens, keine vollständige Abdeckung jeder
einzelnen Callback-ID nötig, da die Routing-Logik 1:1 verschoben wurde).
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import navidrome as nav_actions


def _make_update():
    update = Mock()
    update.callback_query = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_browse_artists_delegates_when_present():
    update = _make_update()
    handler = Mock()
    handler.handle_browse_artists = AsyncMock()
    await nav_actions.handle_browse_artists(update, Mock(), handler)
    handler.handle_browse_artists.assert_awaited_once()


@pytest.mark.asyncio
async def test_browse_artists_shows_unavailable_when_missing():
    update = _make_update()
    await nav_actions.handle_browse_artists(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Navidrome-Handler" in update.callback_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_browse_playlists_shows_placeholder_when_present():
    update = _make_update()
    handler = Mock()
    await nav_actions.handle_browse_playlists(update, Mock(), handler)
    update.callback_query.edit_message_text.assert_awaited_once_with(
        "📋 Playlist-Browser wird gerade entwickelt..."
    )


@pytest.mark.asyncio
async def test_recent_uses_stats_handler_when_hasattr():
    update = _make_update()
    stats_handler = Mock()
    stats_handler.handle_last_played = AsyncMock()
    await nav_actions.handle_recent(update, Mock(), stats_handler)
    stats_handler.handle_last_played.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_shows_unavailable_without_attr():
    update = _make_update()
    stats_handler = object()  # kein handle_last_played
    await nav_actions.handle_recent(update, Mock(), stats_handler)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Statistik-Handler" in update.callback_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_callback_no_handler_shows_unavailable():
    update = _make_update()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_browse_artists", None, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Navidrome-Handler nicht verfügbar"
    )


@pytest.mark.asyncio
async def test_callback_browse_artists_with_page():
    update = _make_update()
    handler = Mock()
    handler.handle_browse_artists = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_browse_artists_2", handler, Mock()
    )
    # Positionsargumente prüfen: (update, context, page=2)
    args, kwargs = handler.handle_browse_artists.call_args
    assert args[0] is update
    assert args[2] == 2


@pytest.mark.asyncio
async def test_callback_search_all_routes_to_handle_search():
    update = _make_update()
    handler = Mock()
    handler.handle_search = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_search", handler, Mock()
    )
    handler.handle_search.assert_awaited_once()
    args, _ = handler.handle_search.call_args
    assert args[2] == "all"


@pytest.mark.asyncio
async def test_callback_unknown_shows_not_implemented():
    update = _make_update()
    handler = Mock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_totally_unknown", handler, Mock()
    )
    update.callback_query.answer.assert_awaited_with("⚠️ Funktion nicht implementiert")
