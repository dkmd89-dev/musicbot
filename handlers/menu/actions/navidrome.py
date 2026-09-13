# handlers/menu/actions/navidrome.py
# -*- coding: utf-8 -*-
"""
Navidrome-Browse/-Suche-Actions ("nav_*"-Callbacks, User-Facing).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py verschoben (reine Move-Operation).
"""

from typing import Optional

from telegram import InlineKeyboardMarkup, Update
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


async def handle_discover_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, navidrome_handler):
    """NAV-F17: Einstieg "🎵 Entdecken" - einziges MenuItem dieser
    Erweiterung. "🎲 Zufällige Songs"/"🆕 Neue Alben" sind bewusst KEINE
    eigenen MenuItems (analog zu Genre-Suche/-Stats, NAV-F7/F8, "kein
    eigener Menüpunkt nötig") - reine Inline-Buttons innerhalb der hier
    gerenderten Nachricht, dispatcht über handle_navidrome_callback()."""
    if navidrome_handler:
        await navidrome_handler.handle_discover_menu(update, context)
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


async def handle_recent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    stats_handler,
    nav_markup: Optional[InlineKeyboardMarkup] = None,
):
    """Wrapper für Zuletzt gespielt (ruft StatistikHandler auf).

    NAV-F10: `nav_markup` additiv/optional (Default `None`), von
    RichMenuSystem._handle_navidrome_recent() per
    RichMenuSystem.get_result_navigation("nav_recent") berechnet - siehe
    handlers/menu/rendering.py::render_result_navigation()-Docstring
    (ARCH-029-Muster). Dieses Modul kennt selbst weder MenuItem noch die
    Menü-Registry, reiner Passthrough."""
    if stats_handler and hasattr(stats_handler, "handle_last_played"):
        await stats_handler.handle_last_played(
            update, context, reply_markup=nav_markup
        )
    else:
        await show_handler_not_available(update, "Statistik-Handler")


async def handle_navidrome_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    navidrome_handler,
    logger,
    stats_handler=None,
) -> None:
    """Spezial-Handler für alle nav_* Callbacks.

    `stats_handler` (NAV-F8, additiv/optional, Default `None`): nur für
    den `nav_genre_stats`-Zweig benötigt (delegiert an
    `StatistikHandler.handle_genre_stats()`, analog zu `handle_recent()`/
    `nav_recent`). Alle übrigen Zweige bleiben unverändert rein
    `navidrome_handler`-basiert."""
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

    # NAV-F11-Fix (entdeckt bei der NAV-F9-Umsetzung, 2026-09-13): dieser
    # Zweig MUSS vor dem generischen "nav_artist_"-Prefix-Check unten
    # stehen - "nav_artist_albums_all_<id>" (Button "➕ N weitere Alben"
    # in handle_artist_detail(), nur bei >15 Alben sichtbar) startet
    # ebenfalls mit "nav_artist_" und wurde deshalb bisher fälschlich dort
    # abgefangen; .replace("nav_artist_", "") lieferte einen korrupten
    # Parameter ("albums_all_<id>" statt "<id>") an handle_artist_detail(),
    # das dann einen nicht existierenden Künstler suchte. Derselbe
    # Bug-Typ wie NAV-F2 (dort für "nav_genre_songs_all_"). Der zugrunde-
    # liegende Button hat noch keine eigene "weitere Alben"-Implementierung
    # - Platzhaltertext analog zum NAV-F2-Fix statt der korrupten
    # Weiterleitung.
    if callback_data.startswith("nav_artist_albums_all_"):
        await query.edit_message_text(
            "💿 Weitere Alben anzeigen\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    # NAV-F17 (Discovery-Erweiterung): derselbe Bug-Typ wie NAV-F2/NAV-F11
    # ("nav_artist_topsongs_<id>" startet ebenfalls mit "nav_artist_") -
    # MUSS deshalb vor dem generischen "nav_artist_"-Prefix-Check unten
    # stehen, sonst wuerde ".replace('nav_artist_', '')" den korrupten
    # Parameter "topsongs_<id>" statt "<id>" an handle_artist_detail()
    # liefern.
    if callback_data.startswith("nav_artist_topsongs_"):
        artist_id = callback_data.replace("nav_artist_topsongs_", "")
        await navidrome_handler.handle_top_songs(update, context, artist_id)
        return

    if callback_data.startswith("nav_artist_"):
        artist_id = callback_data.replace("nav_artist_", "")
        await navidrome_handler.handle_artist_detail(update, context, artist_id)
        return

    if callback_data.startswith("nav_album_"):
        album_id = callback_data.replace("nav_album_", "")
        await navidrome_handler.handle_album_detail(update, context, album_id)
        return

    if callback_data.startswith("nav_song_"):
        song_id = callback_data.replace("nav_song_", "")
        await navidrome_handler.handle_song_detail(update, context, song_id)
        return

    # NAV-F18 (Playlist-CRUD): alle vier Zweige MUESSEN vor dem
    # generischen "nav_playlist_"-Praefix-Check unten stehen - derselbe
    # Bug-Typ wie NAV-F2/NAV-F11/NAV-F17 ("nav_playlist_create_prompt"/
    # "nav_playlist_rename_<id>"/"nav_playlist_delete_confirm_<id>"/
    # "nav_playlist_delete_execute_<id>" starten ebenfalls alle mit
    # "nav_playlist_"). Reihenfolge untereinander ist irrelevant
    # (vollstaendig disjunkte, spezifischere Praefixe).
    if callback_data == "nav_playlist_create_prompt":
        await navidrome_handler.handle_playlist_create_prompt(update, context)
        return

    if callback_data.startswith("nav_playlist_rename_"):
        playlist_id = callback_data.replace("nav_playlist_rename_", "")
        await navidrome_handler.handle_playlist_rename_prompt(
            update, context, playlist_id
        )
        return

    if callback_data.startswith("nav_playlist_delete_confirm_"):
        playlist_id = callback_data.replace("nav_playlist_delete_confirm_", "")
        await navidrome_handler.handle_playlist_delete_confirm(
            update, context, playlist_id
        )
        return

    if callback_data.startswith("nav_playlist_delete_execute_"):
        playlist_id = callback_data.replace("nav_playlist_delete_execute_", "")
        await navidrome_handler.handle_playlist_delete_execute(
            update, context, playlist_id
        )
        return

    # NAV-F5-Fix: "nav_playlist_<id>"-Buttons wurden bereits in
    # handle_my_playlists() erzeugt, es existierte aber kein
    # Dispatcher-Zweig dafuer (fiel auf "Funktion nicht implementiert"
    # unten durch). "nav_playlists" (Top-Level-Menuepunkt "Meine
    # Playlists") kollidiert hier nicht - der laeuft ueber das separate
    # "menu:nav_playlists"-Format und erreicht diesen Praefix-Dispatcher
    # nie.
    if callback_data.startswith("nav_playlist_"):
        playlist_id = callback_data.replace("nav_playlist_", "")
        await navidrome_handler.handle_playlist_detail(update, context, playlist_id)
        return

    # NAV-F2-Fix (Navidrome Menu System Audit, 2026-09-13): dieser Zweig
    # MUSS vor dem generischen "nav_genre_"-Prefix-Check unten stehen -
    # "nav_genre_songs_all_<name>" startet ebenfalls mit "nav_genre_" und
    # wurde deshalb bisher fälschlich dort abgefangen; das anschließende
    # .replace("nav_genre_", "") lieferte einen korrupten Parameter
    # ("songs_all_<name>" statt "<name>") an handle_genre_detail(), das
    # dann Songs für einen nicht existierenden Genre-Namen suchte. Der
    # zugrundeliegende Button ("➕ N weitere anzeigen") hat noch keine
    # eigene Implementierung (zeigt bisher nur die ersten 10 Songs eines
    # Genres) - Platzhaltertext analog zu den bestehenden STUB-Zweigen
    # ("nav_search_genres"/"nav_genre_stats") statt der korrupten
    # Weiterleitung.
    if callback_data.startswith("nav_genre_songs_all_"):
        await query.edit_message_text(
            "🎵 Weitere Songs anzeigen\n\nDiese Funktion wird gerade entwickelt..."
        )
        return

    # NAV-F8-Fix (entdeckt beim Implementieren von NAV-F8, 2026-09-13):
    # dieser Zweig MUSS vor dem generischen "nav_genre_"-Prefix-Check
    # unten stehen - "nav_genre_stats" startet ebenfalls mit "nav_genre_"
    # und wurde deshalb bisher (als der noch nur reine STUB-Text zeigte)
    # nie erreicht, sondern fälschlich als handle_genre_detail(update,
    # context, "stats") geroutet (Suche nach einem Genre namens "stats").
    # Derselbe Bug-Typ wie NAV-F2/NAV-F11, hier bisher unbemerkt, weil der
    # STUB-Platzhaltertext dieselbe Bedeutungslosigkeit hatte wie ein
    # (fälschlich) gesuchtes, nicht existierendes Genre "stats". Jetzt wo
    # nav_genre_stats echte Funktionalität bekommt (StatistikHandler.
    # handle_genre_stats()), muss der Zweig tatsächlich erreichbar sein.
    if callback_data == "nav_genre_stats":
        if stats_handler and hasattr(stats_handler, "handle_genre_stats"):
            await stats_handler.handle_genre_stats(update, context)
        else:
            await show_handler_not_available(update, "Statistik-Handler")
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

    # NAV-F7-Fix: "genres" ist ein eigener search_type ohne generische
    # search3()-Weiterverarbeitung, siehe
    # NavidromeMenuHandler._process_genre_search_query()-Docstring.
    if callback_data == "nav_search_genres":
        await navidrome_handler.handle_search(update, context, "genres")
        return

    if callback_data == "nav_reconnect":
        await navidrome_handler.handle_reconnect(update, context)
        return

    # NAV-F17 (Discovery-Erweiterung): "nav_discover" ist der Rueck-Button
    # aus den beiden Unteransichten (siehe render_random_songs()/
    # render_newest_albums()) - fuehrt zurueck zum "Entdecken"-Menue.
    # Reiner exakter Match, kein Prefix-Konflikt mit den beiden
    # spezifischeren Zweigen unten (unterschiedliche, vollstaendig
    # verschiedene Strings, keine Ueberschneidungsgefahr wie bei
    # nav_artist_*/nav_genre_*).
    if callback_data == "nav_discover":
        await navidrome_handler.handle_discover_menu(update, context)
        return

    if callback_data == "nav_discover_random":
        await navidrome_handler.handle_random_songs(update, context)
        return

    if callback_data.startswith("nav_discover_newest_albums"):
        parts = callback_data.split("_")
        page = int(parts[-1]) if callback_data != "nav_discover_newest_albums" else 0
        await navidrome_handler.handle_newest_albums(update, context, page)
        return

    logger.warning(f"⚠️ Unbekannter Navidrome-Callback: {callback_data}")
    await query.answer("⚠️ Funktion nicht implementiert")
