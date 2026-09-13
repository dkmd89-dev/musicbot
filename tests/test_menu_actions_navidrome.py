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
async def test_recent_uses_stats_handler_when_hasattr():
    update = _make_update()
    stats_handler = Mock()
    stats_handler.handle_last_played = AsyncMock()
    await nav_actions.handle_recent(update, Mock(), stats_handler)
    stats_handler.handle_last_played.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_nav_markup_defaults_to_none():
    """NAV-F10: reply_markup ohne übergebenes nav_markup bleibt None
    (additiv, Rückwärtskompatibilität)."""
    update = _make_update()
    stats_handler = Mock()
    stats_handler.handle_last_played = AsyncMock()
    await nav_actions.handle_recent(update, Mock(), stats_handler)
    _, kwargs = stats_handler.handle_last_played.call_args
    assert kwargs.get("reply_markup") is None


@pytest.mark.asyncio
async def test_recent_nav_markup_is_passed_through_as_reply_markup():
    """NAV-F10 (Navidrome Menu System Audit): ein von RichMenuSystem
    berechnetes nav_markup wird 1:1 als reply_markup durchgereicht -
    schließt den in ARCH-029 übersehenen Dead-End für 'Zuletzt gespielt'."""
    update = _make_update()
    stats_handler = Mock()
    stats_handler.handle_last_played = AsyncMock()
    sentinel_markup = Mock(name="nav_markup")

    await nav_actions.handle_recent(
        update, Mock(), stats_handler, nav_markup=sentinel_markup
    )

    _, kwargs = stats_handler.handle_last_played.call_args
    assert kwargs.get("reply_markup") is sentinel_markup


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


@pytest.mark.asyncio
async def test_callback_album_detail_delegates_with_correct_id_nav_f9():
    """NAV-F9: nav_album_<id> ist kein STUB mehr, sondern delegiert an
    handle_album_detail() mit dem korrekten Album-Parameter."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_album_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_album_abc123", handler, Mock()
    )
    handler.handle_album_detail.assert_awaited_once_with(update, context, "abc123")


@pytest.mark.asyncio
async def test_callback_song_detail_delegates_with_correct_id_nav_f9():
    """NAV-F9: nav_song_<id> ist kein STUB mehr, sondern delegiert an
    handle_song_detail() mit dem korrekten Song-Parameter."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_song_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_song_xyz789", handler, Mock()
    )
    handler.handle_song_detail.assert_awaited_once_with(update, context, "xyz789")


@pytest.mark.asyncio
async def test_callback_artist_topsongs_delegates_with_correct_id_nav_f17():
    """NAV-F17: 'nav_artist_topsongs_<id>' MUSS vor dem generischen
    'nav_artist_'-Präfix-Zweig geroutet werden - derselbe Bug-Typ wie
    NAV-F2/NAV-F11 (Präfix-Kollision)."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_top_songs = AsyncMock()
    handler.handle_artist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_artist_topsongs_real-artist-id", handler, Mock()
    )
    handler.handle_top_songs.assert_awaited_once_with(
        update, context, "real-artist-id"
    )
    handler.handle_artist_detail.assert_not_called()


@pytest.mark.asyncio
async def test_callback_artist_detail_still_works_after_topsongs_fix_nav_f17():
    """Regressionsschutz: der neue 'nav_artist_topsongs_'-Zweig darf den
    normalen 'nav_artist_<id>'-Pfad nicht brechen."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_artist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_artist_real-artist-id", handler, Mock()
    )
    handler.handle_artist_detail.assert_awaited_once_with(
        update, context, "real-artist-id"
    )


@pytest.mark.asyncio
async def test_callback_discover_menu_delegates_nav_f17():
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_discover_menu = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_discover", handler, Mock()
    )
    handler.handle_discover_menu.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
async def test_callback_discover_random_delegates_nav_f17():
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_random_songs = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_discover_random", handler, Mock()
    )
    handler.handle_random_songs.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
async def test_callback_discover_newest_albums_first_page_defaults_to_zero_nav_f17():
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_newest_albums = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_discover_newest_albums", handler, Mock()
    )
    handler.handle_newest_albums.assert_awaited_once_with(update, context, 0)


@pytest.mark.asyncio
async def test_callback_discover_newest_albums_parses_page_number_nav_f17():
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_newest_albums = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_discover_newest_albums_2", handler, Mock()
    )
    handler.handle_newest_albums.assert_awaited_once_with(update, context, 2)


@pytest.mark.asyncio
async def test_callback_artist_albums_all_does_not_call_artist_detail_with_corrupted_id_nav_f11():
    """NAV-F11 (entdeckt bei NAV-F9): 'nav_artist_albums_all_<id>' wurde
    bisher vom generischen 'nav_artist_'-Präfix-Zweig abgefangen und
    lieferte einen korrupten Parameter ('albums_all_<id>' statt '<id>')
    an handle_artist_detail() - derselbe Bug-Typ wie NAV-F2."""
    update = _make_update()
    handler = Mock()
    handler.handle_artist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_artist_albums_all_real-artist-id", handler, Mock()
    )
    handler.handle_artist_detail.assert_not_called()
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "albums_all" not in text


@pytest.mark.asyncio
async def test_callback_playlist_detail_delegates_with_correct_id_nav_f5():
    """NAV-F5: nav_playlist_<id> war eine Dead Route (Buttons in
    handle_my_playlists() erzeugten den Callback, kein Dispatcher-Zweig
    existierte) - delegiert jetzt an handle_playlist_detail()."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_playlist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_playlist_pl123", handler, Mock()
    )
    handler.handle_playlist_detail.assert_awaited_once_with(update, context, "pl123")


@pytest.mark.asyncio
async def test_callback_nav_playlists_menu_id_does_not_collide_with_playlist_detail_nav_f5():
    """Regressionsschutz: 'nav_playlists' (Top-Level-Menuepunkt 'Meine
    Playlists') darf nicht vom neuen 'nav_playlist_'-Praefix-Zweig
    abgefangen werden. Erreicht diesen Dispatcher in der Praxis nie
    (laeuft ueber 'menu:nav_playlists'), aber falls doch: darf nicht auf
    handle_playlist_detail() mit korruptem Parameter '"s"' landen."""
    update = _make_update()
    handler = Mock()
    handler.handle_playlist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_playlists", handler, Mock()
    )
    handler.handle_playlist_detail.assert_not_called()


@pytest.mark.asyncio
async def test_callback_search_genres_delegates_to_handle_search_nav_f7():
    """NAV-F7: nav_search_genres war ein STUB - delegiert jetzt an
    handle_search(update, context, "genres") (eigener search_type, siehe
    NavidromeMenuHandler._process_genre_search_query()-Docstring)."""
    update = _make_update()
    handler = Mock()
    handler.handle_search = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_search_genres", handler, Mock()
    )
    handler.handle_search.assert_awaited_once()
    args, _ = handler.handle_search.call_args
    assert args[2] == "genres"


@pytest.mark.asyncio
async def test_callback_genre_stats_delegates_to_stats_handler_nav_f8():
    """NAV-F8: nav_genre_stats war ein STUB - delegiert jetzt an
    StatistikHandler.handle_genre_stats() (bestehendes Statistics-System,
    analog zu nav_recent/handle_recent())."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    stats_handler = Mock()
    stats_handler.handle_genre_stats = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_genre_stats", handler, Mock(), stats_handler=stats_handler
    )
    stats_handler.handle_genre_stats.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
async def test_callback_genre_stats_does_not_collide_with_generic_genre_detail_nav_f8():
    """Regressionsschutz (entdeckt beim Implementieren von NAV-F8):
    'nav_genre_stats' startet ebenfalls mit dem generischen
    'nav_genre_'-Praefix und wurde deshalb bisher faelschlich als
    handle_genre_detail(..., 'stats') geroutet - derselbe Bug-Typ wie
    NAV-F2/NAV-F11. Muss stattdessen an handle_genre_stats() gehen."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_genre_detail = AsyncMock()
    stats_handler = Mock()
    stats_handler.handle_genre_stats = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_genre_stats", handler, Mock(), stats_handler=stats_handler
    )
    handler.handle_genre_detail.assert_not_called()
    stats_handler.handle_genre_stats.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
async def test_callback_genre_stats_shows_unavailable_without_stats_handler_nav_f8():
    update = _make_update()
    handler = Mock()
    await nav_actions.handle_navidrome_callback(
        update, Mock(), "nav_genre_stats", handler, Mock(), stats_handler=None
    )
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Statistik-Handler" in text


@pytest.mark.asyncio
async def test_callback_normal_artist_still_extracts_correct_id_nav_f11():
    """Regressionsschutz: der NAV-F11-Fix darf den normalen
    'nav_artist_<id>'-Pfad nicht brechen."""
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_artist_detail = AsyncMock()
    await nav_actions.handle_navidrome_callback(
        update, context, "nav_artist_real-artist-id", handler, Mock()
    )
    handler.handle_artist_detail.assert_awaited_once_with(
        update, context, "real-artist-id"
    )
