# handlers/menu/actions/navidrome.py
# -*- coding: utf-8 -*-
"""
Navidrome-Browse/-Suche-Actions ("nav_*"-Callbacks, User-Facing).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py verschoben (reine Move-Operation).
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.actions._common import show_handler_not_available


async def handle_browse_artists(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_browse_artists(update, context)
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_browse_albums(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_browse_albums(update, context)
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_browse_genres(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_browse_genres(update, context)
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_browse_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📋 Playlist-Browser wird gerade entwickelt..."
        )
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_search_all(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_search(update, context, "all")
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_search_artists(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_search(update, context, "artists")
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_search_albums(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_search(update, context, "albums")
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_search_songs(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_search(update, context, "songs")
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_my_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_my_playlists(update, context)
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    if navidrome_handler:
        await navidrome_handler.handle_favorites(update, context)
    else:
        await show_handler_not_available(update, "Navidrome-Handler")


async def handle_recent(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    """Wrapper für Zuletzt gespielt (ruft StatistikHandler auf)"""
    if stats_handler and hasattr(stats_handler, "handle_last_played"):
        await stats_handler.handle_last_played(update, context)
    else:
        await show_handler_not_available(update, "Statistik-Handler")


async def handle_navidrome_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    navidrome_handler,
    logger,
) -> None:
    """Spezial-Handler für alle nav_* Callbacks"""
    if not navidrome_handler:
        await update.callback_query.answer("⚠️ Navidrome-Handler nicht verfügbar")
        return

    query = update.callback_query
    await query.answer()

    logger.debug(f"🎵 Navidrome-Callback: {callback_data}")

    if callback_data.startswith("nav_browse_artists"):
        parts = callback_data.split("_")
        page = int(parts[3]) if len(parts) > 3 else 0
        await navidrome_handler.handle_browse_artists(update, context, page)
        return

    if callback_data.startswith("nav_browse_albums"):
        parts = callback_data.split("_")
        page = int(parts[3]) if len(parts) > 3 else 0
        artist_id = parts[4] if len(parts) > 4 else None
        await navidrome_handler.handle_browse_albums(update, context, page, artist_id)
        return

    if callback_data == "nav_browse_genres":
        await navidrome_handler.handle_browse_genres(update, context)
        return

    if callback_data.startswith("nav_artist_"):
        artist_id = callback_data.replace("nav_artist_", "")
        await navidrome_handler.handle_artist_detail(update, context, artist_id)
        return

    if callback_data.startswith("nav_album_"):
        album_id = callback_data.replace("nav_album_", "")
        await query.edit_message_text(
            f"💿 Album-Details (ID: {album_id})\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    if callback_data.startswith("nav_song_"):
        song_id = callback_data.replace("nav_song_", "")
        await query.edit_message_text(
            f"🎵 Song-Details (ID: {song_id})\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    if callback_data.startswith("nav_genre_"):
        genre_name = callback_data.replace("nav_genre_", "")
        await navidrome_handler.handle_genre_detail(update, context, genre_name)
        return

    if callback_data == "nav_search":
        await navidrome_handler.handle_search(update, context, "all")
        return

    if callback_data == "nav_search_artists":
        await navidrome_handler.handle_search(update, context, "artists")
        return

    if callback_data == "nav_search_albums":
        await navidrome_handler.handle_search(update, context, "albums")
        return

    if callback_data == "nav_search_songs":
        await navidrome_handler.handle_search(update, context, "songs")
        return

    if callback_data == "nav_search_genres":
        await query.edit_message_text(
            "🔎 Genre-Suche\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    if callback_data == "nav_reconnect":
        await navidrome_handler.handle_reconnect(update, context)
        return

    if callback_data == "nav_genre_stats":
        await query.edit_message_text(
            "📊 Genre-Statistiken\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    logger.warning(f"⚠️ Unbekannter Navidrome-Callback: {callback_data}")
    await query.answer("⚠️ Funktion nicht implementiert")
