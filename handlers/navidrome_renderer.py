# handlers/navidrome_renderer.py
# -*- coding: utf-8 -*-
"""
Reines MarkdownV2-Text-/Keyboard-Rendering für die Navidrome-
Detailansichten (Album/Song/Playlist).

Architecture Refactoring Audit, Migrationsstufe 1 (siehe
docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md,
Abschnitt 5): 1:1 aus `handlers/navidrome_menu_handler.py` extrahiert
(`handle_album_detail()`/`handle_song_detail()`/`handle_playlist_detail()`),
keine Verhaltensänderung. Enthält bewusst NUR die drei Detail-Render-
Funktionen dieser Migrationsstufe - keine Browse-Rendering-Funktionen
(kein Scope-Creep in Richtung einer künftigen Stufe, CLAUDE.md
Abschnitt 3.A: keine Vorwegnahme mehrerer ARCH-Phasen).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Aufbau von (Text, InlineKeyboardMarkup) aus bereits
    von Navidrome geladenen Dicts (Album/Song/Playlist).
  - KEIN API-Aufruf, KEIN `_check_connection()`, KEIN Error-Handling,
    KEIN Telegram-`Update`/`edit_message_text()`-Zugriff - das bleibt
    vollständig in `NavidromeMenuHandler` (Orchestrierung).

Reine, zustandslose Funktionen - direkt unit-testbar ohne Mocks (siehe
tests/test_navidrome_renderer.py).
"""

from typing import Any, Dict, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from helfer.markdown_helfer import escape_md_v2


def format_track_duration(seconds: Any) -> str:
    """Formatiert Sekunden als 'M:SS' (Einzeltrack-/Album-Gesamtdauer,
    NAV-F9) - bewusst ein eigener, kleiner Formatter statt
    StatistikHandler._format_duration() ('Xh Ym', für aufsummierte
    Hörzeit über viele Songs gedacht, ungeeignet für eine einzelne
    Track-/Album-Laufzeit). 1:1 aus
    NavidromeMenuHandler._format_track_duration() verschoben."""
    try:
        total_seconds = int(float(seconds or 0))
    except (TypeError, ValueError):
        total_seconds = 0
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}:{secs:02d}"


def render_album_detail(album: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Album-Detailansicht (NAV-F9). Tracklist
    bewusst auf 25 Songs gedeckelt (keine neue Pagination-Button-
    Fehlerquelle, siehe NAV-F2/NAV-F11). 1:1 aus
    NavidromeMenuHandler.handle_album_detail() verschoben."""
    album_name = album.get("name", "Unbekannt")
    artist_name = album.get("artist", "Unbekannt")
    artist_id = album.get("artistId", "")
    songs = album.get("song", [])

    keyboard = []
    for song in songs[:25]:
        track_num = song.get("track")
        track_prefix = f"{track_num}. " if track_num else ""
        song_text = f"🎵 {track_prefix}{song.get('title', 'Unbekannt')}"
        if len(song_text) > 40:
            song_text = song_text[:37] + "..."

        keyboard.append(
            [
                InlineKeyboardButton(
                    song_text, callback_data=f"nav_song_{song['id']}"
                )
            ]
        )

    action_row = []
    if artist_id:
        action_row.append(
            InlineKeyboardButton(
                "🎤 Zum Künstler", callback_data=f"nav_artist_{artist_id}"
            )
        )
    if action_row:
        keyboard.append(action_row)
    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    song_count = album.get("songCount", len(songs))
    duration_text = format_track_duration(album.get("duration", 0))
    year = album.get("year")
    year_suffix = f" ({year})" if year else ""

    more_songs_note = ""
    if len(songs) > 25:
        more_songs_note = f"\n_+{len(songs) - 25} weitere Songs nicht angezeigt_"

    # BUG-007-Fix-Analogon (siehe handle_artist_detail()/
    # handle_genre_detail()): album_name/artist_name/year_suffix
    # kommen unveraendert aus der Navidrome-Bibliothek und werden
    # hier in einen MarkdownV2-Nachrichtentext eingefuegt - mit
    # escape_md_v2() statt roh eingesetzt.
    text = (
        f"💿 **Album: {escape_md_v2(album_name)}{escape_md_v2(year_suffix)}**\n\n"
        f"🎤 Künstler: {escape_md_v2(artist_name)}\n"
        f"🎵 {escape_md_v2(str(song_count))} Songs · "
        f"⏱️ {escape_md_v2(duration_text)}\n"
        f"{more_songs_note}\n\n"
        f"**Tracklist:**"
    )

    return text, InlineKeyboardMarkup(keyboard)


def render_song_detail(song: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Song-Detailansicht (NAV-F9). 1:1 aus
    NavidromeMenuHandler.handle_song_detail() verschoben."""
    title = song.get("title", "Unbekannt")
    artist_name = song.get("artist", "Unbekannt")
    album_name = song.get("album", "")
    genre = song.get("genre", "")
    year = song.get("year")
    track_num = song.get("track")
    duration_text = format_track_duration(song.get("duration", 0))

    keyboard = []
    action_row = []
    if song.get("artistId"):
        action_row.append(
            InlineKeyboardButton(
                "🎤 Zum Künstler",
                callback_data=f"nav_artist_{song['artistId']}",
            )
        )
    if song.get("albumId"):
        action_row.append(
            InlineKeyboardButton(
                "💿 Zum Album", callback_data=f"nav_album_{song['albumId']}"
            )
        )
    if action_row:
        keyboard.append(action_row)
    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    lines = [f"🎵 **{escape_md_v2(title)}**", ""]
    lines.append(f"🎤 Künstler: {escape_md_v2(artist_name)}")
    if album_name:
        lines.append(f"💿 Album: {escape_md_v2(album_name)}")
    if track_num:
        lines.append(f"🔢 Track: {escape_md_v2(str(track_num))}")
    if year:
        lines.append(f"📅 Jahr: {escape_md_v2(str(year))}")
    if genre:
        lines.append(f"🎭 Genre: {escape_md_v2(genre)}")
    lines.append(f"⏱️ Dauer: {escape_md_v2(duration_text)}")

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def render_playlist_detail(
    playlist: Dict[str, Any]
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Playlist-Detailansicht (NAV-F5).
    Tracklist analog zu render_album_detail() bewusst auf 25 Songs
    gedeckelt. 1:1 aus NavidromeMenuHandler.handle_playlist_detail()
    verschoben."""
    playlist_name = playlist.get("name", "Unbekannt")
    owner = playlist.get("owner", "")
    songs = playlist.get("entry", [])

    keyboard = []
    for song in songs[:25]:
        track_num = song.get("track")
        track_prefix = f"{track_num}. " if track_num else ""
        song_text = f"🎵 {track_prefix}{song.get('title', 'Unbekannt')}"
        if len(song_text) > 40:
            song_text = song_text[:37] + "..."

        keyboard.append(
            [
                InlineKeyboardButton(
                    song_text, callback_data=f"nav_song_{song['id']}"
                )
            ]
        )

    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    song_count = playlist.get("songCount", len(songs))
    duration_text = format_track_duration(playlist.get("duration", 0))

    more_songs_note = ""
    if len(songs) > 25:
        more_songs_note = f"\n_+{len(songs) - 25} weitere Songs nicht angezeigt_"

    # BUG-007-Fix-Analogon (siehe render_album_detail()): playlist_name/
    # owner kommen unveraendert aus der Navidrome-Bibliothek und werden
    # hier in einen MarkdownV2-Nachrichtentext eingefuegt - mit
    # escape_md_v2() statt roh eingesetzt.
    lines = [f"📋 **{escape_md_v2(playlist_name)}**\n"]
    if owner:
        lines.append(f"👤 Ersteller: {escape_md_v2(owner)}")
    lines.append(
        f"🎵 {escape_md_v2(str(song_count))} Songs · "
        f"⏱️ {escape_md_v2(duration_text)}"
    )
    if more_songs_note:
        lines.append(more_songs_note)
    lines.append("\n**Tracklist:**")

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)
