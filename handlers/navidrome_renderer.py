# handlers/navidrome_renderer.py
# -*- coding: utf-8 -*-
"""
Reines MarkdownV2-Text-/Keyboard-Rendering für die Navidrome-
Detail- und Browse-Ansichten.

Architecture Refactoring Audit (siehe
docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md,
Abschnitt 5), Migrationsstufe 1: 1:1 aus `handlers/navidrome_menu_handler.py`
extrahiert (`handle_album_detail()`/`handle_song_detail()`/
`handle_playlist_detail()`), keine Verhaltensänderung.

Migrationsstufe 3: ergänzt um die Browse-Render-Funktionen
(`handle_browse_artists()`/`handle_browse_albums()`/`handle_browse_genres()`),
ebenfalls 1:1 extrahiert - inkl. des zuvor separat gefixten NAV-F14
(`songCount`-Normalisierung VOR Sortierung/Anzeige in
`render_browse_genres()`, siehe dessen Docstring).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Aufbau von (Text, InlineKeyboardMarkup) aus bereits
    von Navidrome geladenen Daten (Dicts/Listen).
  - KEIN API-Aufruf, KEIN `_check_connection()`, KEIN Error-Handling,
    KEIN Telegram-`Update`/`edit_message_text()`-Zugriff - das bleibt
    vollständig in `NavidromeMenuHandler` (Orchestrierung).

Reine, zustandslose Funktionen - direkt unit-testbar ohne Mocks (siehe
tests/test_navidrome_renderer.py). Eigener Modul-Logger (nicht
`self.logger` von `NavidromeMenuHandler`, da diese Funktionen keine
Instanzmethoden sind) - einziger, bewusst begrenzter Seiteneffekt
neben dem reinen Rückgabewert (Diagnose-Warnung bei NAV-F14-Fallback
in `render_browse_genres()`).
"""

from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from logger import get_module_logger

logger = get_module_logger("NavidromeRenderer")

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
    NavidromeMenuHandler.handle_album_detail() verschoben.

    NAV-F16 (derselbe Bug wie NAV-F15, siehe render_playlist_detail()):
    das Literal "_+N weitere Songs nicht angezeigt_" enthielt ein '+'
    im MarkdownV2-Text - '+' ist ein reserviertes Zeichen, Telegram
    lehnt die Nachricht mit BadRequest ab. Da das '+' hier nur ein
    Stilmittel ohne inhaltliche Bedeutung war, wird es weggelassen."""
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
        more_songs_note = f"\n_{len(songs) - 25} weitere Songs nicht angezeigt_"

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
    verschoben.

    NAV-F15: Das Literal "_+N weitere Songs nicht angezeigt_" enthielt
    ein '+' im MarkdownV2-Text. '+' ist ein reserviertes Zeichen und
    muss entweder escaped oder durch ein nicht-reserviertes Zeichen
    ersetzt werden. Da das '+' hier nur ein Stilmittel ohne inhaltliche
    Bedeutung war, wird es weggelassen - die Zeile bleibt verständlich.
    Derselbe Bug existierte auch in render_album_detail() - dort
    bewusst nicht im selben Schritt mitgefixt (separat als NAV-F16
    dokumentiert), inzwischen in einem eigenen PR ebenfalls behoben."""
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
        more_songs_note = f"\n_{len(songs) - 25} weitere Songs nicht angezeigt_"

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


def render_browse_artists(
    all_artists: List[Dict[str, Any]], page: int
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die paginierte Künstlerliste. `all_artists`
    ist die VOLLSTÄNDIGE (bereits vom Aufrufer als nicht-leer geprüfte)
    Liste - Pagination erfolgt hier lokal. 1:1 aus
    NavidromeMenuHandler.handle_browse_artists() verschoben."""
    page_size = 20
    start = page * page_size
    end = start + page_size
    artists = all_artists[start:end]

    keyboard = []
    for i in range(0, len(artists), 2):
        row = []
        for j in range(2):
            if i + j < len(artists):
                artist = artists[i + j]
                name = artist.get("name") or artist.get("title") or "Unbekannt"
                artist_id = artist.get("id") or artist.get("artistId") or ""
                row.append(
                    InlineKeyboardButton(
                        f"🎤 {name[:25]}",
                        callback_data=f"nav_artist_{artist_id}",
                    )
                )
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                "⬅️ Vorherige", callback_data=f"nav_browse_artists_{page-1}"
            )
        )
    if end < len(all_artists):
        nav_row.append(
            InlineKeyboardButton(
                "Nächste ➡️", callback_data=f"nav_browse_artists_{page+1}"
            )
        )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append(
        [
            InlineKeyboardButton("🔍 Suchen", callback_data="nav_search_artists"),
            InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome"),
        ]
    )

    text = f"""
🎤 **Künstler durchsuchen**

Seite {page + 1} \\- {len(artists)} Künstler auf dieser Seite

Wähle einen Künstler aus oder verwende die Navigation\\:
""".strip()

    return text, InlineKeyboardMarkup(keyboard)


def render_browse_albums(
    albums: List[Dict[str, Any]],
    title_prefix: str,
    page: int,
    artist_id: Optional[str],
    page_size: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Album-Liste (bereits vom Aufrufer
    geladen/lokal paginiert - beide API-Pfade von
    `handle_browse_albums()` [getArtist vs. getAlbumList2] bleiben in
    `NavidromeMenuHandler`, da sie einen echten API-Aufruf enthalten).
    `page_size` wird durchgereicht statt hier erneut hartkodiert, um
    eine einzige Quelle für die "hat es eine nächste Seite"-Heuristik
    (`len(albums) == page_size`) zu behalten. 1:1 aus
    NavidromeMenuHandler.handle_browse_albums() verschoben - inkl. der
    bereits im Original identischen if/else-Berechnung von `has_next`
    (beide Zweige lieferten denselben Ausdruck), hier auf eine Zeile
    vereinfacht, ohne Verhaltensänderung."""
    keyboard = []
    for album in albums:
        album_text = f"💿 {album['name'][:30]}"
        if "artist" in album:
            album_text += f" - {album['artist'][:20]}"

        keyboard.append(
            [
                InlineKeyboardButton(
                    album_text, callback_data=f"nav_album_{album['id']}"
                )
            ]
        )

    nav_row = []
    if page > 0:
        callback_data = f"nav_browse_albums_{page-1}"
        if artist_id:
            callback_data += f"_{artist_id}"
        nav_row.append(
            InlineKeyboardButton("⬅️ Vorherige", callback_data=callback_data)
        )

    has_next = len(albums) == page_size
    if has_next:
        callback_data = f"nav_browse_albums_{page+1}"
        if artist_id:
            callback_data += f"_{artist_id}"
        nav_row.append(
            InlineKeyboardButton("Nächste ➡️", callback_data=callback_data)
        )

    if nav_row:
        keyboard.append(nav_row)

    back_row = [
        InlineKeyboardButton("🔍 Suchen", callback_data="nav_search_albums")
    ]
    if artist_id:
        back_row.append(
            InlineKeyboardButton("🎤 Künstler", callback_data="nav_browse_artists")
        )
    back_row.append(
        InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")
    )
    keyboard.append(back_row)

    text = f"""
{title_prefix}

Seite {page + 1} \\- {len(albums)} Alben auf dieser Seite

Wähle ein Album aus oder verwende die Navigation\\:
""".strip()

    return text, InlineKeyboardMarkup(keyboard)


def render_browse_genres(
    genres: List[Dict[str, Any]]
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Genre-Liste (Top 20, sortiert nach
    Song-Anzahl). `genres` wird IN PLACE normalisiert+sortiert (wie im
    Original). 1:1 aus NavidromeMenuHandler.handle_browse_genres()
    verschoben, inkl. NAV-F14-Fix: `songCount` wird hier einmalig vor
    Sortierung UND Anzeige sicher zu `int` normalisiert (fehlerhafte
    Werte -> 0) - vorher fing nur der Sortier-Schritt eine
    nicht-numerische `songCount` ab (mit Fallback auf einen alphabetischen
    Sort nach dem falschen Feld), während die Anzeige-Schleife danach mit
    dem unkonvertierten Rohwert crashte. Sortierung erfolgt über
    `(-songCount, name.lower())` mit demselben `value`-bevorzugenden
    Namensfeld wie die Anzeige."""
    genre_songcount_fallback_used = False
    for genre in genres:
        try:
            genre["songCount"] = int(genre.get("songCount") or 0)
        except (TypeError, ValueError):
            genre["songCount"] = 0
            genre_songcount_fallback_used = True

    if genre_songcount_fallback_used:
        logger.warning(
            "⚠️ Mindestens ein Genre hatte einen nicht-numerischen "
            "songCount-Wert - auf 0 normalisiert."
        )

    genres.sort(
        key=lambda g: (
            -g["songCount"],
            (g.get("value") or g.get("name") or "").lower(),
        )
    )

    keyboard = []
    max_genres = min(len(genres), 20)  # Maximal 20 Genres

    for i in range(0, max_genres, 2):
        row = []
        for j in range(2):
            if i + j < max_genres:
                genre = genres[i + j]
                genre_name = (
                    genre.get("value") or genre.get("name") or "Unbekannt"
                )
                song_count = genre.get("songCount", 0)

                if song_count > 0:
                    genre_text = f"🎭 {genre_name} ({song_count})"
                else:
                    genre_text = f"🎭 {genre_name}"

                if len(genre_text) > 35:
                    genre_text = genre_text[:32] + "..."

                row.append(
                    InlineKeyboardButton(
                        genre_text, callback_data=f"nav_genre_{genre_name}"
                    )
                )

        if row:
            keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔍 Genre suchen", callback_data="nav_search_genres"
            ),
            InlineKeyboardButton("📊 Genre-Stats", callback_data="nav_genre_stats"),
        ]
    )

    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    total_songs = sum(int(g.get("songCount", 0)) for g in genres)
    avg_songs = total_songs // max(len(genres), 1)

    text = f"""🎭 **Genres durchsuchen**

📊 **Übersicht:**
• {len(genres)} Genres verfügbar
• {total_songs:,} Songs gesamt  
• ∅ {avg_songs} Songs pro Genre

Die Zahlen in Klammern zeigen die Anzahl der Songs pro Genre\\."""

    return text, InlineKeyboardMarkup(keyboard)


def render_genre_detail(
    genre_name: str, songs: List[Dict[str, Any]]
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Genre-Detailansicht (Top 10 Songs +
    Statistiken). `songs` ist die VOLLSTÄNDIGE (bereits vom Aufrufer als
    nicht-leer geprüfte) Songliste des Genres. 1:1 aus
    NavidromeMenuHandler.handle_genre_detail() verschoben."""
    keyboard = []
    display_songs = songs[:10]

    for song in display_songs:
        song_title = song.get("title", "Unbekannt")
        artist_name = song.get("artist", "Unbekannt")
        song_text = f"🎵 {song_title} - {artist_name}"

        if len(song_text) > 40:
            song_text = song_text[:37] + "..."

        keyboard.append(
            [
                InlineKeyboardButton(
                    song_text, callback_data=f"nav_song_{song['id']}"
                )
            ]
        )

    if len(songs) > 10:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"➕ {len(songs) - 10} weitere anzeigen",
                    callback_data=f"nav_genre_songs_all_{genre_name}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🎭 Andere Genres", callback_data="nav_browse_genres"
            ),
            InlineKeyboardButton(
                "🔍 In Genre suchen",
                callback_data=f"nav_search_in_genre_{genre_name}",
            ),
        ]
    )

    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    artists = set(song.get("artist", "Unbekannt") for song in songs)
    albums = set(song.get("album", "Unbekannt") for song in songs)

    # BUG-007-Fix: siehe analoge Begruendung in render_artist_detail() -
    # genre_name ungeschuetzt in MarkdownV2-Body eingefuegt (z.B. "Lo-Fi"
    # oder "R&B/Soul" enthalten MarkdownV2-Sonderzeichen).
    text = f"""🎭 **Genre: {escape_md_v2(genre_name)}**

📊 **Statistiken:**
• {len(songs)} Songs total
• {len(artists)} verschiedene Künstler
• {len(albums)} verschiedene Alben

**🎵 Top Songs:** \\(erste 10 angezeigt\\)"""

    return text, InlineKeyboardMarkup(keyboard)


def render_artist_detail(
    artist: Dict[str, Any], artist_id: str
) -> Tuple[str, InlineKeyboardMarkup]:
    """Baut Text+Keyboard für die Artist-Detailansicht (Top 15 Alben +
    Statistiken). `artist_id` wird separat übergeben (nicht zwangsläufig
    im `artist`-Dict selbst enthalten) - identisch zum Original-Parameter
    von NavidromeMenuHandler.handle_artist_detail(), 1:1 verschoben."""
    artist_name = artist.get("name", "Unbekannt")
    albums = artist.get("album", [])

    keyboard = []
    for album in albums[:15]:
        album_name = album.get("name", "Unbekannt")
        year = album.get("year", "")
        year_text = f" ({year})" if year else ""

        album_text = f"💿 {album_name}{year_text}"
        if len(album_text) > 40:
            album_text = album_text[:37] + "..."

        keyboard.append(
            [
                InlineKeyboardButton(
                    album_text, callback_data=f"nav_album_{album['id']}"
                )
            ]
        )

    if len(albums) > 15:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"➕ {len(albums) - 15} weitere Alben",
                    callback_data=f"nav_artist_albums_all_{artist_id}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🎤 Andere Künstler", callback_data="nav_browse_artists"
            ),
            InlineKeyboardButton(
                "🔍 Künstler suchen", callback_data="nav_search_artists"
            ),
        ]
    )

    keyboard.append(
        [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
    )

    star_rating = artist.get("starred", "")
    play_count = artist.get("playCount", 0)

    stats_text = ""
    if play_count > 0:
        stats_text += f"• {play_count} mal abgespielt\n"
    if star_rating:
        stats_text += f"• ⭐ Favorit\n"

    # BUG-007-Fix: artist_name kommt unveraendert aus der Navidrome-
    # Bibliothek (Nutzer-/Library-Daten) und wird hier in einen
    # MarkdownV2-Nachrichtentext eingefuegt. Ohne escape_md_v2() fuehrt
    # jeder MarkdownV2-Sonderzeichen im Namen (Punkt, Bindestrich,
    # Klammern, Ausrufezeichen - in echten Kuenstlernamen keine
    # Seltenheit) zu einem "can't parse entities"-Fehler von Telegram.
    text = f"""🎤 **Künstler: {escape_md_v2(artist_name)}**

📊 **Alben:** {len(albums)}
{stats_text}
**💿 Verfügbare Alben:**"""

    return text, InlineKeyboardMarkup(keyboard)
