# handlers/navidrome_menu_handler.py
# -*- coding: utf-8 -*-
"""
🎵 NAVIDROME MENÜ-HANDLER
Integrierte Mediensuche und -verwaltung über Navidrome API

NAV-F1-Fix (Navidrome Menu System Audit, 2026-09-13): alle "🔙 Zurück"/
"❌ Abbrechen"-Buttons dieser Klasse nutzten bisher callback_data
"menu_navidrome"/"menu_main" (Unterstrich) - weder als PTB-
CallbackQueryHandler-Pattern registriert noch von
RichMenuSystem.handle_callback() geroutet (dort ausschließlich
"menu:<id>" mit Doppelpunkt, siehe MenuItem.__post_init__ in
handlers/menu/models.py). Jeder Klick verpuffte dadurch stillschweigend
(PTB liefert für nicht gematchte Callback-Daten keinen Fehler/kein Log).
Auf "menu:navidrome"/"menu:main" umgestellt - beides bereits bestehende,
unveränderte Menu-IDs (definitions.py), kein neuer Callback-Präfix.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from typing import TYPE_CHECKING
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from logger import get_module_logger, EnhancedLogger
from helfer.markdown_helfer import escape_md_v2, md_bold, md_code
from handlers import navidrome_renderer
from services.clients.navidrome_api import NavidromeAPI
from services.navidrome import browser_service

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


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

        # Wird von rich_menu_handler.py nach der Konstruktion zugewiesen
        # (self.navidrome_handler.error_handler = self.error_handler) -
        # Default None, damit sowohl direkte Konstruktion (Tests) als auch
        # der Zeitraum vor dieser Zuweisung sicher funktionieren.
        self.error_handler: "Optional[EnhancedErrorHandler]" = None

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
        """Zeigt Künstler-Liste an (paginierte Sicht auf get_artists).

        Architecture Refactoring Audit, Migrationsstufe 3: Text-/
        Keyboard-Bau wurde nach navidrome_renderer.render_browse_artists()
        ausgelagert - diese Methode bleibt reine Orchestrierung
        (Connection-Check, API-Aufruf, Error-Handling)."""
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

            message_text, reply_markup = navidrome_renderer.render_browse_artists(
                all_artists, page
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Künstler: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_browse_artists", e
                )
            else:
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
        """Zeigt Album-Liste an (Artist-spezifisch via getArtist, sonst getAlbumList2).

        Architecture Refactoring Audit, Migrationsstufe 3: Text-/
        Keyboard-Bau wurde nach navidrome_renderer.render_browse_albums()
        ausgelagert. Migrationsstufe 4: der API-Pfad (getArtist vs.
        getAlbumList2) wurde zusätzlich nach
        services/navidrome/browser_service.py::get_albums_page()
        ausgelagert - diese Methode bleibt reine Orchestrierung
        (Connection-Check, Service-Aufruf, Error-Handling)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            page_size = 15
            albums, title_prefix = await browser_service.get_albums_page(
                self.navidrome_api, page, artist_id, page_size
            )

            if not albums:
                await update.callback_query.edit_message_text(
                    "❌ Keine Alben gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_browse_albums(
                albums, title_prefix, page, artist_id, page_size
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Alben: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_browse_albums", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Alben. Bitte versuche es später erneut."
                )

    async def handle_browse_genres(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Genre-Liste an - KORRIGIERT für richtige API-Response-Verarbeitung

        Architecture Refactoring Audit, Migrationsstufe 3: Text-/
        Keyboard-Bau (inkl. der NAV-F14-Sortier-/Normalisierungslogik)
        wurde nach navidrome_renderer.render_browse_genres() ausgelagert."""
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

            message_text, reply_markup = navidrome_renderer.render_browse_genres(
                genres
            )

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
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_browse_genres", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Genres. Bitte versuche es später erneut."
                )

    # NEU: Genre-Details anzeigen
    async def handle_genre_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, genre_name: str
    ):
        """Zeigt Details und Songs eines spezifischen Genres

        Architecture Refactoring Audit, Detail-View-Familie: Text-/
        Keyboard-Bau wurde nach navidrome_renderer.render_genre_detail()
        ausgelagert."""
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

            message_text, reply_markup = navidrome_renderer.render_genre_detail(
                genre_name, songs
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Genre-Details: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_genre_detail", e
                )
            else:
                await update.callback_query.edit_message_text(
                    f"❌ Fehler beim Laden der Details für Genre '{genre_name}'."
                )

    # NEU: Artist-Details anzeigen
    async def handle_artist_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, artist_id: str
    ):
        """Zeigt Details eines Künstlers mit Alben

        Architecture Refactoring Audit, Detail-View-Familie: Text-/
        Keyboard-Bau wurde nach navidrome_renderer.render_artist_detail()
        ausgelagert."""
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

            message_text, reply_markup = navidrome_renderer.render_artist_detail(
                artist, artist_id
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Künstler-Details: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_artist_detail", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Künstler-Details."
                )

    # NEU (NAV-F17): "🎵 Entdecken"-Menü
    async def handle_discover_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt das "🎵 Entdecken"-Menü (NAV-F17) - reine statische
        Auswahl, kein API-Aufruf/Connection-Check nötig (analog zu
        anderen reinen Menü-Übersichten)."""
        message_text, reply_markup = navidrome_renderer.render_discover_menu()
        await update.callback_query.edit_message_text(
            text=message_text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )

    async def handle_random_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt "🎲 Zufällige Songs" (NAV-F17, getRandomSongs)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info("🎲 Lade zufällige Songs")

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getRandomSongs", {"size": 25}
            )

            subsonic_response = data.get("subsonic-response", {})
            songs = subsonic_response.get("randomSongs", {}).get("song", [])

            if not songs:
                await update.callback_query.edit_message_text(
                    "❌ Keine Songs gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_random_songs(songs)

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden zufälliger Songs: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_random_songs", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden zufälliger Songs."
                )

    async def handle_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, artist_id: str
    ):
        """Zeigt "🔥 Top Songs" eines Künstlers (NAV-F17, getTopSongs) -
        aufgerufen über den in render_artist_detail() ergänzten Button,
        nicht über einen eigenen Freitext-Prompt (siehe dessen
        Docstring). getTopSongs braucht den Artist-NAMEN (nicht die ID),
        daher zuerst getArtist zur Namensauflösung - identisches Muster
        zu handle_artist_detail()."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"🔥 Lade Top Songs für Künstler-ID: {artist_id}")

            artist_data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getArtist", {"id": artist_id}
            )
            artist = artist_data.get("subsonic-response", {}).get("artist", {})
            artist_name = artist.get("name")

            if not artist_name:
                await update.callback_query.edit_message_text(
                    "❌ Künstler nicht gefunden."
                )
                return

            data = await asyncio.to_thread(
                self.navidrome_api.make_request,
                "getTopSongs",
                {"artist": artist_name, "count": 25},
            )
            songs = data.get("subsonic-response", {}).get("topSongs", {}).get(
                "song", []
            )

            message_text, reply_markup = navidrome_renderer.render_top_songs(
                artist_name, artist_id, songs
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Top Songs: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_top_songs", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Top Songs."
                )

    async def handle_newest_albums(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
    ):
        """Zeigt "🆕 Neue Alben" (NAV-F17, getAlbumList2 type=newest) -
        Pagination analog zu handle_browse_albums(), aber fachlich
        unabhängig (neueste zuerst statt alphabetisch), daher eigener
        Callback-Namensraum (siehe render_newest_albums()-Docstring)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            page_size = 15
            data = await asyncio.to_thread(
                self.navidrome_api.make_request,
                "getAlbumList2",
                {"type": "newest", "size": page_size, "offset": page * page_size},
            )
            albums = (
                data.get("subsonic-response", {})
                .get("albumList2", {})
                .get("album", [])
            )

            if not albums:
                await update.callback_query.edit_message_text(
                    "❌ Keine Alben gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_newest_albums(
                albums, page, page_size
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden neuer Alben: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_newest_albums", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden neuer Alben."
                )

    # NEU (NAV-F9): Album-Details anzeigen
    async def handle_album_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, album_id: str
    ):
        """Zeigt Details eines Albums mit Tracklist (schließt den bisherigen
        `nav_album_<id>`-STUB, siehe docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md
        NAV-F9). Bewusst OHNE „weitere Songs anzeigen"-Pagination (Tracklist
        auf 25 Songs gedeckelt, für praktisch jedes reale Album ausreichend)
        - vermeidet eine weitere STUB-/Prefix-Kollisions-Fehlerquelle wie
        bei NAV-F2/NAV-F11, siehe deren Docstrings.

        Architecture Refactoring Audit, Migrationsstufe 1: Text-/Keyboard-Bau
        wurde nach navidrome_renderer.render_album_detail() ausgelagert -
        diese Methode bleibt reine Orchestrierung (Connection-Check,
        API-Aufruf, Error-Handling)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"💿 Lade Album-Details für ID: {album_id}")

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getAlbum", {"id": album_id}
            )

            subsonic_response = data.get("subsonic-response", {})
            album = subsonic_response.get("album", {})

            if not album:
                await update.callback_query.edit_message_text(
                    "❌ Album nicht gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_album_detail(album)

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Album-Details: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_album_detail", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Album-Details."
                )

    # NEU (NAV-F9): Song-Details anzeigen
    async def handle_song_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, song_id: str
    ):
        """Zeigt Details eines einzelnen Songs (schließt den bisherigen
        `nav_song_<id>`-STUB, siehe NAV-F9).

        Architecture Refactoring Audit, Migrationsstufe 1: Text-/Keyboard-Bau
        wurde nach navidrome_renderer.render_song_detail() ausgelagert."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"🎵 Lade Song-Details für ID: {song_id}")

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getSong", {"id": song_id}
            )

            subsonic_response = data.get("subsonic-response", {})
            song = subsonic_response.get("song", {})

            if not song:
                await update.callback_query.edit_message_text(
                    "❌ Song nicht gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_song_detail(song)

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Song-Details: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_song_detail", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Song-Details."
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

            # NAV-F18 (Playlist-CRUD): "➕ Neue Playlist" bleibt auch bei
            # leerer Liste sichtbar (bootstrapt die allererste Playlist),
            # anders als der bisherige fruehe Return bei "not playlists".
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "➕ Neue Playlist", callback_data="nav_playlist_create_prompt"
                    )
                ]
            )
            keyboard.append(
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
            )

            if playlists:
                message_text = f"""
📋 **Meine Playlists**

Du hast {len(playlists)} Playlist\\(s\\) verfügbar:
"""
            else:
                message_text = """
📋 **Meine Playlists**

❌ Keine Playlists gefunden\\.
"""
            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Playlists: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_my_playlists", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Playlists."
                )

    # NEU (NAV-F5): Playlist-Details anzeigen
    async def handle_playlist_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, playlist_id: str
    ):
        """Zeigt Details einer Playlist mit Tracklist (schließt die bisherige
        `nav_playlist_<id>`-Dead-Route - die Buttons in `handle_my_playlists()`
        erzeugten diesen Callback bereits, es existierte aber kein
        Dispatcher-Zweig dafür, siehe
        docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md NAV-F5). Tracklist
        analog zu `handle_album_detail()` bewusst auf 25 Songs gedeckelt
        (keine neue Pagination-Button-Fehlerquelle, siehe NAV-F2/NAV-F11).

        Architecture Refactoring Audit, Migrationsstufe 1: Text-/Keyboard-Bau
        wurde nach navidrome_renderer.render_playlist_detail() ausgelagert."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"📋 Lade Playlist-Details für ID: {playlist_id}")

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getPlaylist", {"id": playlist_id}
            )

            subsonic_response = data.get("subsonic-response", {})
            playlist = subsonic_response.get("playlist", {})

            if not playlist:
                await update.callback_query.edit_message_text(
                    "❌ Playlist nicht gefunden."
                )
                return

            message_text, reply_markup = navidrome_renderer.render_playlist_detail(
                playlist
            )

            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Playlist-Details: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_playlist_detail", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Playlist-Details."
                )

    # NEU (NAV-F18): Playlist-CRUD - bewusst reduzierter Zuschnitt
    # (Nutzerentscheidung): nur Name-Erstellung (leere Playlist), kein
    # Song-Auswahl-Schritt im selben Zug (bräuchte einen im Bot aktuell
    # nirgends vorhandenen Mehrfachauswahl-Song-Picker - "Songs zu
    # Playlist hinzufügen" bleibt ein eigener, separater Folge-Scope).
    async def handle_playlist_create_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Fragt nach dem Namen der neuen Playlist (Freitext-Workflow,
        identisches Muster zu handle_search()/browse_states)."""
        user_id = update.effective_user.id
        if user_id not in self.browse_states:
            self.browse_states[user_id] = {}
        self.browse_states[user_id]["waiting_for_playlist_name"] = True

        message_text = """
📋 **Neue Playlist erstellen**

Sende mir jetzt den Namen für die neue Playlist\\!
"""
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Abbrechen", callback_data="menu:navidrome")]]
        )
        await update.callback_query.edit_message_text(
            text=message_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def process_playlist_name(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, name: str
    ) -> bool:
        """Verarbeitet den eingegebenen Playlist-Namen (createPlaylist,
        leere Playlist). Rückgabewert analog zu process_search_query():
        `True` = Text wurde konsumiert, `False` = kein aktiver Workflow
        (Aufrufer soll die Nachricht anderweitig behandeln)."""
        user_id = update.effective_user.id

        if user_id not in self.browse_states or not self.browse_states[user_id].get(
            "waiting_for_playlist_name"
        ):
            return False

        self.browse_states[user_id]["waiting_for_playlist_name"] = False

        name = (name or "").strip()
        if not name:
            await update.message.reply_text(
                "❌ Der Playlist-Name darf nicht leer sein."
            )
            return True

        if not self._check_connection():
            await update.message.reply_text("❌ Keine Verbindung zu Navidrome.")
            return True

        try:
            self.logger.info(f"📋 Erstelle neue Playlist: {name}")
            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "createPlaylist", {"name": name}
            )
            playlist = data.get("subsonic-response", {}).get("playlist", {})

            await update.message.reply_text(
                f"✅ Playlist '{name}' wurde erstellt."
                if not playlist
                else f"✅ Playlist '{playlist.get('name', name)}' wurde erstellt."
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Erstellen der Playlist: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_playlist_create", e
                )
            else:
                await update.message.reply_text(
                    "❌ Fehler beim Erstellen der Playlist."
                )

        return True

    async def handle_playlist_rename_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, playlist_id: str
    ):
        """Fragt nach dem neuen Namen einer bestehenden Playlist."""
        user_id = update.effective_user.id
        if user_id not in self.browse_states:
            self.browse_states[user_id] = {}
        self.browse_states[user_id]["waiting_for_playlist_rename"] = True
        self.browse_states[user_id]["rename_playlist_id"] = playlist_id

        message_text = """
✏️ **Playlist umbenennen**

Sende mir jetzt den neuen Namen für diese Playlist\\!
"""
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Abbrechen", callback_data=f"nav_playlist_{playlist_id}"
                    )
                ]
            ]
        )
        await update.callback_query.edit_message_text(
            text=message_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def process_playlist_rename(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, name: str
    ) -> bool:
        """Verarbeitet den eingegebenen neuen Playlist-Namen
        (updatePlaylist). Rückgabewert analog zu process_playlist_name()."""
        user_id = update.effective_user.id

        if user_id not in self.browse_states or not self.browse_states[user_id].get(
            "waiting_for_playlist_rename"
        ):
            return False

        self.browse_states[user_id]["waiting_for_playlist_rename"] = False
        playlist_id = self.browse_states[user_id].pop("rename_playlist_id", None)

        name = (name or "").strip()
        if not name:
            await update.message.reply_text(
                "❌ Der Playlist-Name darf nicht leer sein."
            )
            return True

        if not playlist_id:
            await update.message.reply_text(
                "❌ Fehler: keine Playlist-ID gefunden."
            )
            return True

        if not self._check_connection():
            await update.message.reply_text("❌ Keine Verbindung zu Navidrome.")
            return True

        try:
            self.logger.info(f"✏️ Benenne Playlist {playlist_id} um zu: {name}")
            await asyncio.to_thread(
                self.navidrome_api.make_request,
                "updatePlaylist",
                {"playlistId": playlist_id, "name": name},
            )
            await update.message.reply_text(f"✅ Playlist wurde in '{name}' umbenannt.")

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Umbenennen der Playlist: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_playlist_rename", e
                )
            else:
                await update.message.reply_text(
                    "❌ Fehler beim Umbenennen der Playlist."
                )

        return True

    async def handle_playlist_delete_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, playlist_id: str
    ):
        """Zeigt Bestätigungs-Dialog vor dem Löschen (irreversible
        Aktion, analog zu UserManagementHandler.delete_user_confirm())."""
        message_text = """
⚠️ **Playlist löschen**

Bist du sicher, dass du diese Playlist löschen möchtest\\?

Diese Aktion kann nicht rückgängig gemacht werden\\!
"""
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, löschen",
                        callback_data=f"nav_playlist_delete_execute_{playlist_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Abbrechen", callback_data=f"nav_playlist_{playlist_id}"
                    ),
                ]
            ]
        )
        await update.callback_query.edit_message_text(
            text=message_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def handle_playlist_delete_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, playlist_id: str
    ):
        """Führt die Löschung aus (nach Bestätigung)."""
        if not self._check_connection():
            await self._show_connection_error(update)
            return

        try:
            self.logger.info(f"🗑️ Lösche Playlist: {playlist_id}")
            await asyncio.to_thread(
                self.navidrome_api.make_request, "deletePlaylist", {"id": playlist_id}
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📋 Meine Playlists", callback_data="menu:nav_playlists"
                        )
                    ]
                ]
            )
            await update.callback_query.edit_message_text(
                text="✅ Playlist wurde gelöscht\\.",
                reply_markup=keyboard,
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Löschen der Playlist: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_playlist_delete", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Löschen der Playlist."
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
                [InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome")]
            )

            await update.callback_query.edit_message_text(
                text="\n".join(message_parts),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Favoriten: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_favorites", e
                )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Fehler beim Laden der Favoriten."
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
            "genres": "Genres",
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
            [[InlineKeyboardButton("❌ Abbrechen", callback_data="menu:navidrome")]]
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

        # NAV-F7-Fix (Navidrome Menu System Audit): "genres" ist ein
        # eigener Suchpfad - Subsonic hat keine dedizierte Genre-Such-API,
        # daher Teilstring-Filter über die bereits von
        # handle_browse_genres() genutzte getGenres()-Liste statt der
        # generischen search3()-Ergebnisverarbeitung unten (die kennt
        # ohnehin keine Genres, nur artist/album/song).
        if search_type == "genres":
            return await self._process_genre_search_query(update, context, query)

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
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome"),
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
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_search_query", e
                )
            else:
                await update.message.reply_text(
                    "❌ Fehler bei der Suche. Bitte versuche es später erneut."
                )
            return True

    # NEU (NAV-F7): Genre-Suche
    async def _process_genre_search_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str
    ) -> bool:
        """Verarbeitet eine Genre-Suchanfrage (schließt den bisherigen
        `nav_search_genres`-STUB, siehe
        docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md NAV-F7). Subsonic hat
        keine dedizierte Genre-Such-API - filtert stattdessen die bereits
        in `handle_browse_genres()` verwendete `getGenres()`-Liste per
        case-insensitive Teilstring-Match. Zeigt Treffer als
        `nav_genre_<name>`-Buttons (identisch zu `handle_browse_genres()`),
        auch bei genau einem Treffer - vermeidet einen zweiten,
        message-context-Aufruf von `handle_genre_detail()` (das erwartet
        `update.callback_query`, hier liegt nur `update.message` vor)."""
        if not self._check_connection():
            await update.message.reply_text("❌ Keine Verbindung zu Navidrome.")
            return True

        try:
            search_msg = await update.message.reply_text(
                f"🔍 Suche Genre '{query}'..."
            )

            data = await asyncio.to_thread(
                self.navidrome_api.make_request, "getGenres", {}
            )
            subsonic_response = data.get("subsonic-response", {})
            genres_data = subsonic_response.get("genres", {})
            genres = genres_data.get("genre", [])

            query_lower = query.strip().lower()
            matches = [
                g
                for g in genres
                if query_lower
                and query_lower in (g.get("value") or g.get("name") or "").lower()
            ]

            if not matches:
                await search_msg.edit_text(
                    f"❌ Kein Genre gefunden, das '{escape_md_v2(query)}' enthält\\.",
                    parse_mode="MarkdownV2",
                )
                return True

            keyboard = []
            for genre in matches[:15]:
                genre_name = genre.get("value") or genre.get("name") or "Unbekannt"
                song_count = genre.get("songCount", 0)
                label = (
                    f"🎭 {genre_name} ({song_count})"
                    if song_count
                    else f"🎭 {genre_name}"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            label[:40], callback_data=f"nav_genre_{genre_name}"
                        )
                    ]
                )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔍 Neue Genre-Suche", callback_data="nav_search_genres"
                    ),
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu:navidrome"),
                ]
            )

            await search_msg.edit_text(
                text=(
                    f"🎭 **Genres, die '{escape_md_v2(query)}' enthalten** "
                    f"\\({len(matches)}\\)"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Fehler bei der Genre-Suche: {e}")
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "navidrome_genre_search_query", e
                )
            else:
                await update.message.reply_text(
                    "❌ Fehler bei der Genre-Suche. Bitte versuche es später erneut."
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
                    InlineKeyboardButton("🔙 Zurück", callback_data="menu:main"),
                ]
            ]
        )

        await update.callback_query.edit_message_text(
            text=error_text.strip(), reply_markup=keyboard, parse_mode="MarkdownV2"
        )

    async def handle_reconnect(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Versucht die Verbindung wiederherzustellen.

        NAV-F6-Fix (Navidrome Menu System Audit, 2026-09-13): führt jetzt
        tatsächlich einen echten Subsonic-`ping`-Request aus
        (NavidromeAPI.check_connection()), bevor „✅ Verbindung
        wiederhergestellt!" angezeigt wird. Vorher rief diese Methode nur
        _initialize_api() (reine Config-Präsenzprüfung, KEIN
        Netzwerkaufruf) erneut auf - bei nicht-leerer Config wurde immer
        Erfolg gemeldet, selbst wenn der Server tatsächlich nicht
        erreichbar war ("🔄 Erneut versuchen" testete keine echte
        Konnektivität).

        Der schnelle, rein lokale `_check_connection()`-Vorab-Check vor
        den übrigen 8 Browse-/Such-Methoden bleibt BEWUSST unverändert -
        kein `ping` vor jedem einzelnen Klick (Latenz-Trade-off, siehe
        docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md, NAV-F6). Nur der
        explizit vom Nutzer ausgelöste "🔄 Erneut versuchen"-Klick
        rechtfertigt einen echten Netzwerk-Request. `connection_status`
        wird bei fehlgeschlagenem Ping auf False gesetzt, damit der
        nächste Klick auf eine andere Navidrome-Funktion wieder korrekt
        den Verbindungsfehler zeigt, statt mit einer veralteten
        `True`-Config-Präsenz eine echte API-Exception zu riskieren."""
        await update.callback_query.edit_message_text(
            "🔄 Verbindung wird wiederhergestellt..."
        )

        try:
            self._initialize_api()
            if not self._check_connection():
                await self._show_connection_error(update)
                return

            connection_ok = await self.navidrome_api.check_connection()
            if connection_ok:
                await update.callback_query.edit_message_text(
                    "✅ Verbindung wiederhergestellt!",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🎵 Zu Navidrome", callback_data="menu:navidrome"
                                )
                            ]
                        ]
                    ),
                )
            else:
                self.connection_status = False
                await self._show_connection_error(update)
        except Exception as e:
            self.logger.error(f"❌ Reconnect fehlgeschlagen: {e}")
            await self._show_connection_error(update)
