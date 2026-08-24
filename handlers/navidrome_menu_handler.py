# handlers/navidrome_menu_handler.py
# -*- coding: utf-8 -*-
"""
🎵 NAVIDROME MENÜ-HANDLER
Integrierte Mediensuche und -verwaltung über Navidrome API
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from logger import get_module_logger, EnhancedLogger
from helfer.markdown_helfer import escape_md_v2, md_bold, md_code
from services.clients.navidrome_api import NavidromeAPI


@dataclass
class MediaItem:
    """Represents a media item from Navidrome"""

    id: str
    name: str
    type: str  # "artist", "album", "song", "playlist"
    extra_info: Dict[str, Any] = None

    def get_display_text(self, max_length: int = 30) -> str:
        """Formatiert für Anzeige"""
        display_name = (
            self.name[:max_length] + "..." if len(self.name) > max_length else self.name
        )

        type_emojis = {
            "artist": "🎤",
            "album": "💿",
            "song": "🎵",
            "playlist": "📋",
            "genre": "🎭",
        }

        emoji = type_emojis.get(self.type, "📁")
        return f"{emoji} {display_name}"


class NavidromeMenuHandler:
    """Handler für Navidrome-Integration im Menü-System"""

    def __init__(self, config: Config, logger_factory=None, navidrome_api=None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("NavidromeMenuHandler")

        self.connection_status = False

        # ARCH-009 Phase 7: navidrome_api optional injizierbar (DI) - ohne
        # Angabe wird wie bisher eine echte NavidromeAPI()-Instanz
        # konstruiert (analog zum P-8-Muster in StatistikService).
        # Bewusst NavidromeAPI() statt NavidromeAPI(config): _auth_params
        # kam schon vor dieser Migration immer aus der globalen
        # Config-Singleton-Instanz, unabhaengig vom hier uebergebenen
        # config-Objekt (z.B. einem Test-Double ohne NAVIDROME_PASS) -
        # NavidromeAPI(config) wuerde diese Entkopplung aufheben und ist
        # daher eine Verhaltensaenderung, die hier vermieden wird.
        self.navidrome_api = (
            navidrome_api if navidrome_api is not None else NavidromeAPI()
        )

        # Browse-State für jeden User
        self.browse_states: Dict[int, Dict] = {}
        self.search_cache: Dict[str, List[MediaItem]] = {}

        self._initialize_api()

    def _initialize_api(self):
        """Initialisiert die Navidrome API-Verbindung (SYNCHRON)"""
        try:
            # BUG-007-Fix: NAVIDROME_URL/NAVIDROME_USER sind @property auf
            # Config und liefern bei fehlender .env-Variable "" statt eine
            # Exception - hasattr() prueft nur, ob die Property EXISTIERT
            # (immer der Fall), nicht ob sie einen echten Wert hat. War
            # daher unabhaengig von der tatsaechlichen Konfiguration immer
            # True. Der im Kommentar versprochene spaetere asynchrone Check
            # existiert nirgends im Code - connection_status wurde nie
            # korrigiert. Ein voller Verbindungstest (NavidromeAPI.
            # check_connection()) waere ein groesserer, async-basierter
            # Umbau - hier zunaechst der kleinere, eindeutig richtige Fix:
            # tatsaechlich konfigurierte (nicht-leere) Werte pruefen.
            if self.config.NAVIDROME_URL and self.config.NAVIDROME_USER:
                # Setze zunächst auf True (wird später asynchron getestet)
                self.connection_status = True
                self.logger.info(
                    "✅ Navidrome Konfiguration gefunden - Verbindung wird asynchron geprüft"
                )
            else:
                self.connection_status = False
                self.logger.warning("⚠️ Navidrome-Konfiguration unvollständig")

        except Exception as e:
            self.logger.error(f"❌ Fehler bei Navidrome-Initialisierung: {e}")
            self.connection_status = False

    async def handle_browse_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
    ):
        """Zeigt Künstler-Liste an (paginierte Sicht auf get_artists)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            # Gesamtliste der Künstler abrufen und lokal paginieren
            all_artists = await self.navidrome_api.get_artists()
            if not all_artists:
                await update.callback_query.edit_message_text(
                    "❌ Keine Künstler gefunden."
                )
                return

            page_size = 20
            start = page * page_size
            end = start + page_size
            artists = all_artists[start:end]

            # Keyboard erstellen (2 Spalten)
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

            # Navigation
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
                    InlineKeyboardButton(
                        "🔍 Suchen", callback_data="nav_search_artists"
                    ),
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome"),
                ]
            )

            reply_markup = InlineKeyboardMarkup(keyboard)

            message_text = f"""
🎤 **Künstler durchsuchen**

Seite {page + 1} \\- {len(artists)} Künstler auf dieser Seite

Wähle einen Künstler aus oder verwende die Navigation\\:
"""

            await update.callback_query.edit_message_text(
                text=message_text.strip(),
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Künstler: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Künstler. Bitte versuche es später erneut."
            )

    async def handle_browse_albums(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        page: int = 0,
        artist_id: str = None,
    ):
        """Zeigt Album-Liste an (Artist-spezifisch via getArtist, sonst getAlbumList2)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            page_size = 15
            if artist_id:
                # getArtist liefert Albumliste des Künstlers
                data = await asyncio.to_thread(
                    self.navidrome_api.make_request, "getArtist", {"id": artist_id}
                )
                artist = data.get("subsonic-response", {}).get("artist", {})
                albums = artist.get("album", [])
                title_prefix = "🎤 Alben des Künstlers"
                # Lokal paginieren
                start = page * page_size
                end = start + page_size
                albums = albums[start:end]
            else:
                # Alphabetisch nach Künstler mit Offset/Size
                params = {
                    "type": "alphabeticalByArtist",
                    "size": page_size,
                    "offset": page * page_size,
                }
                data = await asyncio.to_thread(
                    self.navidrome_api.make_request, "getAlbumList2", params
                )
                albums = (
                    data.get("subsonic-response", {})
                    .get("albumList2", {})
                    .get("album", [])
                )
                title_prefix = "💿 Alle Alben"

            if not albums:
                await update.callback_query.edit_message_text(
                    "❌ Keine Alben gefunden."
                )
                return

            # Keyboard erstellen
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

            # Navigation
            nav_row = []
            if page > 0:
                callback_data = f"nav_browse_albums_{page-1}"
                if artist_id:
                    callback_data += f"_{artist_id}"
                nav_row.append(
                    InlineKeyboardButton("⬅️ Vorherige", callback_data=callback_data)
                )

            # Bei artist_id lokal prüfen, ob es weitere Seiten gibt
            has_next = False
            if artist_id:
                # Wenn wir genau page_size Elemente zeigen, könnte es noch mehr geben
                has_next = len(albums) == page_size
            else:
                # AlbumList2 liefert genau size Einträge, solange verfügbar
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

            # Zurück-Buttons
            back_row = [
                InlineKeyboardButton("🔍 Suchen", callback_data="nav_search_albums")
            ]
            if artist_id:
                back_row.append(
                    InlineKeyboardButton(
                        "🎤 Künstler", callback_data="nav_browse_artists"
                    )
                )
            back_row.append(
                InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")
            )
            keyboard.append(back_row)

            reply_markup = InlineKeyboardMarkup(keyboard)

            message_text = f"""
{title_prefix}

Seite {page + 1} \\- {len(albums)} Alben auf dieser Seite

Wähle ein Album aus oder verwende die Navigation\\:
"""

            await update.callback_query.edit_message_text(
                text=message_text.strip(),
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Alben: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Alben. Bitte versuche es später erneut."
            )

    async def handle_browse_genres(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Genre-Liste an - KORRIGIERT für richtige API-Response-Verarbeitung"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("🎭 Lade Genres von Navidrome API...")

            # KORRIGIERT: Direkte API-Anfrage statt get_genres()
            data = await asyncio.to_thread(self.navidrome_api.make_request, "getGenres", {})

            self.logger.debug(f"🔍 Genre API Response: {data}")

            # Extrahiere Genres aus Response
            subsonic_response = data.get("subsonic-response", {})
            genres_data = subsonic_response.get("genres", {})
            genres = genres_data.get("genre", [])

            self.logger.info(f"🎭 Verarbeite {len(genres)} Genres")

            if not genres:
                self.logger.warning("⚠️ Keine Genres in API-Response gefunden")
                await update.callback_query.edit_message_text(
                    "❌ Keine Genres gefunden."
                )
                return

            # Sortiere nach Song-Anzahl (falls verfügbar)
            try:
                genres.sort(key=lambda x: int(x.get("songCount", 0)), reverse=True)
            except (ValueError, TypeError) as e:
                self.logger.warning(
                    f"⚠️ Konnte Genres nicht nach songCount sortieren: {e}"
                )
                # Fallback: alphabetisch sortieren
                genres.sort(key=lambda x: x.get("name", "").lower())

            # Keyboard erstellen - 2 Spalten Layout
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

                        # Formatiere Genre-Button
                        if song_count > 0:
                            genre_text = f"🎭 {genre_name} ({song_count})"
                        else:
                            genre_text = f"🎭 {genre_name}"

                        # Kürze Text falls zu lang
                        if len(genre_text) > 35:
                            genre_text = genre_text[:32] + "..."

                        row.append(
                            InlineKeyboardButton(
                                genre_text, callback_data=f"nav_genre_{genre_name}"
                            )
                        )

                if row:  # Nur hinzufügen wenn Row nicht leer
                    keyboard.append(row)

            # Control-Buttons hinzufügen
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔍 Genre suchen", callback_data="nav_search_genres"
                    ),
                    InlineKeyboardButton(
                        "📊 Genre-Stats", callback_data="nav_genre_stats"
                    ),
                ]
            )

            keyboard.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Statistiken berechnen
            total_songs = sum(int(g.get("songCount", 0)) for g in genres)
            avg_songs = total_songs // max(len(genres), 1)

            message_text = f"""🎭 **Genres durchsuchen**

📊 **Übersicht:**
• {len(genres)} Genres verfügbar
• {total_songs:,} Songs gesamt  
• ∅ {avg_songs} Songs pro Genre

Die Zahlen in Klammern zeigen die Anzahl der Songs pro Genre\\."""

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

            self.logger.info(
                f"✅ Genre-Liste erfolgreich angezeigt: {len(genres)} Genres"
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Genres: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Genres. Bitte versuche es später erneut."
            )

    # NEU: Genre-Details anzeigen
    async def handle_genre_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, genre_name: str
    ):
        """Zeigt Details und Songs eines spezifischen Genres"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"🎭 Lade Songs für Genre: {genre_name}")

            # Songs des Genres abrufen
            params = {"genre": genre_name, "size": 50, "offset": 0}  # Erste 50 Songs

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getSongsByGenre", params
            )

            subsonic_response = data.get("subsonic-response", {})
            songs_data = subsonic_response.get("songsByGenre", {})
            songs = songs_data.get("song", [])

            if not songs:
                await update.callback_query.edit_message_text(
                    f"❌ Keine Songs für Genre '{genre_name}' gefunden."
                )
                return

            # Song-Liste erstellen (erste 10 anzeigen)
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

            # Weitere Aktionen
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
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            # Statistiken aus Songs berechnen
            artists = set(song.get("artist", "Unbekannt") for song in songs)
            albums = set(song.get("album", "Unbekannt") for song in songs)

            # BUG-007-Fix: siehe analoge Begruendung in handle_artist_detail()
            # - genre_name ungeschuetzt in MarkdownV2-Body eingefuegt (z.B.
            # "Lo-Fi" oder "R&B/Soul" enthalten MarkdownV2-Sonderzeichen).
            message_text = f"""🎭 **Genre: {escape_md_v2(genre_name)}**

📊 **Statistiken:**
• {len(songs)} Songs total
• {len(artists)} verschiedene Künstler
• {len(albums)} verschiedene Alben

**🎵 Top Songs:** (erste 10 angezeigt)"""

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Genre-Details: {e}")
            await update.callback_query.edit_message_text(
                f"❌ Fehler beim Laden der Details für Genre '{genre_name}'."
            )

    # NEU: Artist-Details anzeigen
    async def handle_artist_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, artist_id: str
    ):
        """Zeigt Details eines Künstlers mit Alben"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"🎤 Lade Künstler-Details für ID: {artist_id}")

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getArtist", {"id": artist_id}
            )

            subsonic_response = data.get("subsonic-response", {})
            artist = subsonic_response.get("artist", {})

            if not artist:
                await update.callback_query.edit_message_text(
                    "❌ Künstler nicht gefunden."
                )
                return

            artist_name = artist.get("name", "Unbekannt")
            albums = artist.get("album", [])

            # Album-Buttons erstellen
            keyboard = []
            for album in albums[:15]:  # Erste 15 Alben
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

            # Weitere Aktionen
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
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            # Zusätzliche Info falls verfügbar
            star_rating = artist.get("starred", "")
            play_count = artist.get("playCount", 0)

            stats_text = ""
            if play_count > 0:
                stats_text += f"• {play_count} mal abgespielt\n"
            if star_rating:
                stats_text += f"• ⭐ Favorit\n"

            # BUG-007-Fix: artist_name kommt unveraendert aus der Navidrome-
            # Bibliothek (Nutzer-/Library-Daten) und wird hier in einen
            # MarkdownV2-Nachrichtentext eingefuegt. Ohne escape_md_v2()
            # fuehrt jeder MarkdownV2-Sonderzeichen im Namen (Punkt,
            # Bindestrich, Klammern, Ausrufezeichen - in echten Kuenstler-
            # namen keine Seltenheit) zu einem "can't parse entities"-Fehler
            # von Telegram, der hier als generische Fehlermeldung endet statt
            # die Kuenstlerdetails anzuzeigen. process_search_query()/
            # handle_stats() escapen bereits korrekt, diese Methode nicht.
            message_text = f"""🎤 **Künstler: {escape_md_v2(artist_name)}**

📊 **Alben:** {len(albums)}
{stats_text}
**💿 Verfügbare Alben:**"""

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Künstler-Details: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Künstler-Details."
            )

    async def handle_my_playlists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
    ):
        """Zeigt die Playlists des Benutzers an"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("📋 Lade Playlists...")
            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getPlaylists", {}
            )
            subsonic_response = data.get("subsonic-response", {})
            playlists_data = subsonic_response.get("playlists", {})
            playlists = playlists_data.get("playlist", [])

            if not playlists:
                await update.callback_query.edit_message_text(
                    "❌ Keine Playlists gefunden."
                )
                return

            keyboard = []
            # Paginierung (falls gewünscht, hier vereinfacht: erste 20)
            for playlist in playlists[:20]:
                name = playlist.get("name", "Unbekannte Playlist")
                song_count = playlist.get("songCount", 0)
                playlist_text = f"📋 {name} ({song_count} Songs)"

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            playlist_text[:40],
                            callback_data=f"nav_playlist_{playlist['id']}",
                        )
                    ]
                )

            keyboard.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            message_text = f"""
📋 **Meine Playlists**

Du hast {len(playlists)} Playlist(s) verfügbar:
"""
            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Playlists: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Playlists."
            )

    async def handle_favorites(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Favoriten (Songs, Alben, Künstler)"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("⭐ Lade Favoriten (getStarred2)...")
            data = await asyncio.to_thread(self.navidrome_api.make_request, "getStarred2", {})
            subsonic_response = data.get("subsonic-response", {})
            starred_data = subsonic_response.get("starred2", {})

            artists = starred_data.get("artist", [])
            albums = starred_data.get("album", [])
            songs = starred_data.get("song", [])

            if not artists and not albums and not songs:
                await update.callback_query.edit_message_text(
                    "❌ Du hast noch keine Favoriten markiert."
                )
                return

            keyboard = []
            message_parts = ["⭐ **Deine Favoriten**\n"]

            # Künstler
            if artists:
                message_parts.append("\n🎤 **Künstler:**")
                for artist in artists[:5]:  # Zeige die ersten 5
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"🎤 {artist['name']}",
                                callback_data=f"nav_artist_{artist['id']}",
                            )
                        ]
                    )

            # Alben
            if albums:
                message_parts.append("\n💿 **Alben:**")
                for album in albums[:5]:  # Zeige die ersten 5
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"💿 {album['name']}",
                                callback_data=f"nav_album_{album['id']}",
                            )
                        ]
                    )

            # Songs
            if songs:
                message_parts.append("\n🎵 **Songs:**")
                for song in songs[:5]:  # Zeige die ersten 5
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"🎵 {song['title']}",
                                callback_data=f"nav_song_{song['id']}",
                            )
                        ]
                    )

            keyboard.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            await update.callback_query.edit_message_text(
                text="\n".join(message_parts),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Favoriten: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Favoriten."
            )

    async def handle_recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Zeigt zuletzt gespielte Alben"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("🕐 Lade zuletzt gespielte Alben...")
            # 'getAlbumList' mit type 'recentlyPlayed'
            params = {"type": "recentlyPlayed", "size": 10}
            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getAlbumList", params
            )

            subsonic_response = data.get("subsonic-response", {})
            album_list = subsonic_response.get("albumList", {})
            albums = album_list.get("album", [])

            if not albums:
                await update.callback_query.edit_message_text(
                    "❌ Keine kürzlich gespielten Alben gefunden."
                )
                return

            keyboard = []
            for album in albums:
                album_text = f"💿 {album['name']} - {album['artist']}"
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            album_text[:40],
                            callback_data=f"nav_album_{album['id']}",
                        )
                    ]
                )

            keyboard.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            )

            message_text = "🕐 **Zuletzt gespielte Alben**"

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der 'Zuletzt gespielt'-Liste: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der 'Zuletzt gespielt'-Liste."
            )

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Zeigt allgemeine Bibliotheksstatistiken"""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("📊 Lade Bibliotheksstatistiken...")
            # getIndexes liefert oft Künstler- und Album-Zahlen
            data = await asyncio.to_thread(self.navidrome_api.make_request, "getIndexes", {})
            subsonic_response = data.get("subsonic-response", {})
            indexes = subsonic_response.get("indexes", {})

            # Versuche, Statistiken aus 'getIndexes' zu extrahieren
            # Navidrome-spezifisch: 'index' ist eine Liste von Dictionaries
            stats = {}
            if "index" in indexes:
                for index in indexes.get("index", []):
                    name = index.get("name", "Unbekannt")
                    artist_count = len(index.get("artist", []))
                    if artist_count > 0:
                        stats[name] = artist_count

            # Fallback oder zusätzliche Infos
            if not stats:
                # Alternative: 'getArtistCount', 'getAlbumCount', 'getSongCount'
                # (Diese sind nicht Standard-Subsonic, aber Navidrome unterstützt sie vllt?)
                # Hier als Platzhalter:
                stats["Künstler (geschätzt)"] = indexes.get("artistCount", "N/A")
                stats["Alben (geschätzt)"] = indexes.get("albumCount", "N/A")
                stats["Songs (geschätzt)"] = indexes.get("songCount", "N/A")

            message_parts = ["📊 **Bibliotheksstatistiken**\n"]
            for key, value in stats.items():
                message_parts.append(f"• {escape_md_v2(key)}: {md_bold(str(value))}")

            keyboard = [
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome")]
            ]

            await update.callback_query.edit_message_text(
                text="\n".join(message_parts),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Statistiken: {e}")
            await update.callback_query.edit_message_text(
                "❌ Fehler beim Laden der Statistiken."
            )

    async def handle_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        search_type: str = "all",
    ):
        """Startet eine Suche"""
        user_id = update.effective_user.id

        # Setze den Suchzustand für den Benutzer
        if user_id not in self.browse_states:
            self.browse_states[user_id] = {}

        self.browse_states[user_id]["search_type"] = search_type
        self.browse_states[user_id]["waiting_for_search"] = True

        search_type_names = {
            "all": "allen Medien",
            "artists": "Künstlern",
            "albums": "Alben",
            "songs": "Songs",
            "playlists": "Playlists",
        }

        type_name = search_type_names.get(search_type, "allen Medien")

        message_text = f"""
🔍 **Suche in {type_name}**

Sende mir jetzt deinen Suchbegriff\\!

Beispiele:
• Künstlername
• Albumtitel
• Songtitel
• Genre

Die Suche ist nicht case\\-sensitiv\\!
"""

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Abbrechen", callback_data="menu_navidrome")]]
        )

        await update.callback_query.edit_message_text(
            text=message_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def process_search_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str
    ):
        """Verarbeitet eine Suchanfrage"""
        user_id = update.effective_user.id

        if user_id not in self.browse_states or not self.browse_states[user_id].get(
            "waiting_for_search"
        ):
            return False

        search_type = self.browse_states[user_id].get("search_type", "all")
        self.browse_states[user_id]["waiting_for_search"] = False

        if not self._check_connection():
            await update.message.reply_text("❌ Keine Verbindung zu Navidrome.")
            return True

        try:
            # Sende "Sucht..." Nachricht
            search_msg = await update.message.reply_text(f"🔍 Suche nach '{query}'...")

            # Führe Suche durch
            search_results = await self.navidrome_api.search(query)

            if not search_results:
                await search_msg.edit_text("❌ Keine Ergebnisse gefunden.")
                return True

            # Verarbeite Ergebnisse
            results_text = []
            keyboard = []

            # Künstler
            if "artist" in search_results and search_results["artist"]:
                results_text.append("🎤 **Künstler:**")
                for artist in search_results["artist"][:5]:
                    results_text.append(f"  • {escape_md_v2(artist['name'])}")
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"🎤 {artist['name'][:30]}",
                                callback_data=f"nav_artist_{artist['id']}",
                            )
                        ]
                    )

            # Alben
            if "album" in search_results and search_results["album"]:
                if results_text:
                    results_text.append("")
                results_text.append("💿 **Alben:**")
                for album in search_results["album"][:5]:
                    album_info = f"{album['name']}"
                    if "artist" in album:
                        album_info += f" - {album['artist']}"
                    results_text.append(f"  • {escape_md_v2(album_info)}")
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"💿 {album_info[:30]}",
                                callback_data=f"nav_album_{album['id']}",
                            )
                        ]
                    )

            # Songs
            if "song" in search_results and search_results["song"]:
                if results_text:
                    results_text.append("")
                results_text.append("🎵 **Songs:**")
                for song in search_results["song"][:5]:
                    song_info = f"{song['title']}"
                    if "artist" in song:
                        song_info += f" - {song['artist']}"
                    results_text.append(f"  • {escape_md_v2(song_info)}")
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"🎵 {song_info[:30]}",
                                callback_data=f"nav_song_{song['id']}",
                            )
                        ]
                    )

            if not results_text:
                await search_msg.edit_text("❌ Keine passenden Ergebnisse gefunden.")
                return True

            # Footer mit Statistiken
            total_results = (
                len(search_results.get("artist", []))
                + len(search_results.get("album", []))
                + len(search_results.get("song", []))
            )

            results_text.append("")
            results_text.append(f"Gesamt: {total_results} Ergebnisse")

            keyboard.append(
                [
                    InlineKeyboardButton("🔍 Neue Suche", callback_data="nav_search"),
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu_navidrome"),
                ]
            )

            final_text = (
                f"🔍 **Suchergebnisse für '{escape_md_v2(query)}'**\n\n"
                + "\n".join(results_text)
            )

            await search_msg.edit_text(
                text=final_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

            return True

        except Exception as e:
            self.logger.error(f"❌ Fehler bei der Suche: {e}")
            await update.message.reply_text(
                "❌ Fehler bei der Suche. Bitte versuche es später erneut."
            )
            return True

    def _check_connection(self) -> bool:
        """Prüft die Navidrome-Verbindung"""
        return self.connection_status and NavidromeAPI is not None

    async def _show_connection_error(self, update: Update):
        """Zeigt Verbindungsfehler an"""
        error_text = """
❌ **Navidrome nicht verfügbar**

Die Verbindung zu Navidrome konnte nicht hergestellt werden\\.

**Mögliche Ursachen:**
• Server ist offline
• Falsche Konfiguration
• Netzwerkprobleme

Kontaktiere den Administrator\\!
"""

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔄 Erneut versuchen", callback_data="nav_reconnect"
                    ),
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu_main"),
                ]
            ]
        )

        await update.callback_query.edit_message_text(
            text=error_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def handle_reconnect(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Versucht die Verbindung wiederherzustellen"""
        await update.callback_query.edit_message_text(
            "🔄 Verbindung wird wiederhergestellt..."
        )

        try:
            self._initialize_api()
            if self._check_connection():
                await update.callback_query.edit_message_text(
                    "✅ Verbindung wiederhergestellt!",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🎵 Zu Navidrome", callback_data="menu_navidrome"
                                )
                            ]
                        ]
                    ),
                )
            else:
                await self._show_connection_error(update)
        except Exception as e:
            self.logger.error(f"❌ Reconnect fehlgeschlagen: {e}")
            await self._show_connection_error(update)


def create_navidrome_handler(
    config: Config, logger_factory=None
) -> NavidromeMenuHandler:
    """Factory-Funktion für den Navidrome-Handler"""
    return NavidromeMenuHandler(config, logger_factory)
