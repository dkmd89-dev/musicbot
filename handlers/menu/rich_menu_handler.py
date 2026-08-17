# handlers/menu/rich_menu_handler.py
# -*- coding: utf-8 -*-
"""
🎯 RichMenuHandler - ERWEITERT MIT NAVIDROME, LOGGER, START, HELP, BOT-NEUSTART
                     UND SPOTIFY-INTEGRATION

CHANGELOG:
  - v2.2  Spotify-Integration:
          • Import SpotifyDownloader
          • self.spotify_downloader Attribut (__init__)
          • SpotifyDownloader-Initialisierung (initialize)
          • Injektion in DownloadHandler (_initiate_download + _handle_regular_url)
          • Unified handle_url() statt handle_youtube_links() (erkennt automatisch YT vs Spotify)
  - v2.1  Bot-Neustart-Feature:
          • Import BotRestartHandler
          • BotRestartHandler-Instanziierung (initialize)
          • restart:-Pattern in get_telegram_handlers()
"""

import json
from datetime import datetime
from typing import Dict, Callable, Optional, Any
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from logger import get_module_logger
from handlers.menu.rich_menu_system import (
    RichMenuSystem,
    MenuItem,
    AccessLevel,
    MenuState,
)
from klassen.download_handler import DownloadHandler
from handlers.test_menu_handler import TestMenuHandler
from handlers.enhanced_logger_menu_handler import EnhancedLoggerMenuHandler
from handlers.navidrome_menu_handler import NavidromeMenuHandler
from handlers.mugge_statistik_handler import StatistikHandler
from handlers.admin.user_management_handler import UserManagementHandler
from handlers.admin.backup_handler import BackupHandler
from handlers.admin.bot_restart_handler import BotRestartHandler
from handlers.duplicate_handler import EnhancedDuplicateHandler
from handlers.enhanced_status_handler import (
    EnhancedStatusHandler,
    create_enhanced_status_handler,
)
from handlers.enhanced_error_handler import (
    EnhancedErrorHandler,
    create_enhanced_error_handler,
    ErrorHandlerAdminInterface,
)
from config import Config
from services.downloader.utils.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)

# ── NEU: Spotify-Integration ──────────────────────────────────────────────────
from services.downloader.spotify_downloader import SpotifyDownloader, _is_spotify_url

# ─────────────────────────────────────────────────────────────────────────────


class RichMenuHandler:
    """
    Integration Layer zwischen RichMenuSystem und bestehenden Handlern.

    Verwaltet alle Handler-Instanzen, initialisiert sie in der richtigen
    Reihenfolge und verknüpft sie mit dem Menüsystem.

    Neu in v2.2: Geteilte SpotifyDownloader-Instanz wird einmalig initialisiert
    und bei jedem DownloadHandler-Aufruf injiziert (statt pro Request neu zu erstellen).
    """

    def __init__(self, config: Config, logger_factory=None):
        self.config = config
        self.logger_factory = logger_factory
        self.logger = (self.logger_factory or get_module_logger)("RichMenuHandler")

        # Error Handler (muss zuerst initialisiert werden)
        self.error_handler: Optional[EnhancedErrorHandler] = None

        # Core System
        self.menu_system = RichMenuSystem(config, self.logger_factory)

        # Handler-Referenzen
        self.download_handler: Optional[DownloadHandler] = None
        self.stats_handler: Optional[StatistikHandler] = None
        self.admin_handler: Optional[Any] = None
        self.navidrome_adapter: Optional[Any] = None
        self.test_handler: Optional[TestMenuHandler] = None
        self.logger_handler: Optional[EnhancedLoggerMenuHandler] = None
        self.navidrome_handler: Optional[NavidromeMenuHandler] = None
        self.user_mgmt_handler: Optional[Any] = None
        self.duplicate_handler: Optional[EnhancedDuplicateHandler] = None
        self.error_admin_interface: Optional[ErrorHandlerAdminInterface] = None
        self.metadata_processor: Optional[EnhancedMetadataProcessor] = None
        self.status_handler: Optional[EnhancedStatusHandler] = None
        self.backup_handler: Optional[BackupHandler] = None
        self.restart_handler: Optional[BotRestartHandler] = None

        # ── NEU: Geteilte SpotifyDownloader-Instanz ───────────────────────────
        # Wird einmalig in initialize() erstellt und bei jedem DownloadHandler-
        # Aufruf injiziert, um Ressourcen (spotdl-Check, Credentials) zu sparen.
        self.spotify_downloader: Optional[SpotifyDownloader] = None
        # ─────────────────────────────────────────────────────────────────────

        # State Management
        self.user_states: Dict[int, str] = {}

        # User-Data für Start/Help
        self.user_data_file = Path("data/user_data.json")

        # Feature-Katalog
        self.features = {
            "download": {
                "emoji": "📥",
                "title": "Downloads",
                "description": "Lade Musik von YouTube oder Spotify herunter",
                "commands": ["/download"],
                "min_role": "user",
                "menu_id": "download",
            },
            "stats": {
                "emoji": "📊",
                "title": "Statistiken",
                "description": "Zeige deine Hörstatistiken",
                "commands": ["/stats", "/month", "/year"],
                "min_role": "user",
                "menu_id": "stats",
            },
            "navidrome": {
                "emoji": "🎵",
                "title": "Navidrome",
                "description": "Durchsuche deine Musikbibliothek",
                "commands": ["/navidrome", "/search"],
                "min_role": "user",
                "menu_id": "navidrome",
            },
            "admin": {
                "emoji": "⚙️",
                "title": "Administration",
                "description": "Systemverwaltung und User-Management",
                "commands": ["/admin", "/users"],
                "min_role": "admin",
                "menu_id": "admin",
            },
            "tests": {
                "emoji": "🧪",
                "title": "Test-System",
                "description": "Unit-, Integrations- und Performance-Tests",
                "commands": ["/tests"],
                "min_role": "admin",
                "menu_id": "tests",
            },
        }

        self.logger.info("🎯 RichMenuHandler initialisiert")

    # ====== INITIALISIERUNG ======

    def initialize(self) -> None:
        """
        Initialisiert alle Handler in der richtigen Reihenfolge.

        Reihenfolge ist bewusst gewählt:
        1. Error Handler (Basis für alle anderen)
        2. Fachliche Handler (Test, Logger, Stats, Navidrome, ...)
        3. SpotifyDownloader (eigene Ressource, muss vor DownloadHandler kommen)
        4. MetadataProcessor (wird von DownloadHandler benötigt)
        5. Menüsystem-Verknüpfung
        """
        self.logger.info("🚀 Starte Handler-Integration ...")

        # 1. Error Handler (höchste Priorität – alle anderen hängen davon ab)
        try:
            self.error_handler = create_enhanced_error_handler(
                self.config, self.logger_factory
            )
            self.logger.info("✅ Enhanced Error Handler initialisiert")
        except Exception as e:
            self.logger.critical(
                f"❌ FATAL: Error Handler konnte nicht initialisiert werden: {e}"
            )
            raise

        # 2. Test-Handler
        self.test_handler = TestMenuHandler(self.config, self.logger_factory)
        if self.test_handler:
            self.test_handler.error_handler = self.error_handler

        # 3. Logger-Handler
        try:
            self.logger_handler = EnhancedLoggerMenuHandler(
                self.config, self.logger_factory
            )
            self.logger_handler.error_handler = self.error_handler
            self.logger.info("✅ EnhancedLoggerMenuHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Logger-Handler Fehler: {e}", exc_info=True)
            self.logger_handler = None

        # 4. Statistik-Handler
        try:
            self.stats_handler = StatistikHandler()
            self.logger.info("✅ StatistikHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Statistik-Handler Fehler: {e}", exc_info=True)
            self.stats_handler = None

        # 5. Navidrome-Handler
        try:
            self.navidrome_handler = NavidromeMenuHandler(
                self.config, self.logger_factory
            )
            self.navidrome_handler.error_handler = self.error_handler
            self.logger.info("✅ NavidromeMenuHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Navidrome-Handler Fehler: {e}", exc_info=True)
            self.navidrome_handler = None

        # 6. User Management Handler
        try:
            self.user_mgmt_handler = UserManagementHandler(
                self.config, self.logger_factory
            )
            self.user_mgmt_handler.error_handler = self.error_handler
            self.logger.info("✅ UserManagementHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ UserManagement-Handler Fehler: {e}", exc_info=True)
            self.user_mgmt_handler = None

        # 7. Duplicate Handler
        try:
            self.duplicate_handler = EnhancedDuplicateHandler(
                self.config, self.logger_factory
            )
            self.duplicate_handler.error_handler = self.error_handler
            self.logger.info("✅ EnhancedDuplicateHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Duplicate-Handler Fehler: {e}", exc_info=True)
            self.duplicate_handler = None

        # 8. Status Handler
        try:
            self.status_handler = create_enhanced_status_handler(
                self.config, self.logger_factory
            )
            self.status_handler.error_handler = self.error_handler
            self.logger.info("✅ EnhancedStatusHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Status-Handler Fehler: {e}", exc_info=True)
            self.status_handler = None

        # 9. Backup Handler
        try:
            self.backup_handler = BackupHandler(self.config, self.logger_factory)
            self.logger.info("✅ BackupHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Backup-Handler Fehler: {e}", exc_info=True)
            self.backup_handler = None

        # 10. Bot-Neustart Handler
        try:
            self.restart_handler = BotRestartHandler(self.config, self.logger_factory)
            self.logger.info("✅ BotRestartHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Restart-Handler Fehler: {e}", exc_info=True)
            self.restart_handler = None

        # ── NEU 11. SpotifyDownloader ─────────────────────────────────────────
        # Wird einmalig hier initialisiert und später bei jedem DownloadHandler
        # per Dependency Injection weitergegeben.
        # Aktivierungsbedingungen (erste zutreffende):
        #   a) SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in Config → volles Metadaten-Abruf
        #   b) spotdl installiert ohne eigene Credentials → funktioniert mit spotdl-Auth
        # Wenn keines zutrifft, bleibt self.spotify_downloader = None
        # und handle_spotify_url() gibt eine verständliche Fehlermeldung aus.
        try:
            self.spotify_downloader = SpotifyDownloader(
                self.config,
                logger_factory=self.logger_factory,
            )
            self.logger.info(
                "✅ SpotifyDownloader initialisiert "
                f"(Credentials: {'✅' if getattr(self.config, 'SPOTIFY_CLIENT_ID', '') else '❌ nicht konfiguriert'})"
            )
        except Exception as e:
            self.logger.warning(
                f"⚠️ SpotifyDownloader konnte nicht initialisiert werden: {e}. "
                "Spotify-Downloads sind deaktiviert."
            )
            self.spotify_downloader = None
        # ─────────────────────────────────────────────────────────────────────

        # 12. Metadata Processor
        try:
            self.metadata_processor = EnhancedMetadataProcessor(
                self.config, self.logger_factory
            )
            self.logger.info("✅ EnhancedMetadataProcessor initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Metadata-Processor Fehler: {e}", exc_info=True)
            self.metadata_processor = None

        # ── Menüsystem initialisieren und Handler verknüpfen ──────────────────
        self.menu_system.initialize_menu_structure()
        self.menu_system.error_handler = self.error_handler
        self.menu_system.set_error_handler(self.error_handler)

        if self.logger_handler:
            self.menu_system.set_logger_handler(self.logger_handler)
        if self.stats_handler:
            self.menu_system.set_stats_handler(self.stats_handler)
        if self.navidrome_handler:
            self.menu_system.set_navidrome_handler(self.navidrome_handler)
        if self.user_mgmt_handler:
            self.menu_system.set_user_mgmt_handler(self.user_mgmt_handler)
        if self.duplicate_handler:
            self.menu_system.set_duplicate_handler(self.duplicate_handler)
        if self.status_handler:
            self.menu_system.set_status_handler(self.status_handler)
        if self.backup_handler:
            self.menu_system.set_backup_handler(self.backup_handler)
        if self.restart_handler:
            self.menu_system.set_restart_handler(self.restart_handler)

        # Handler registrieren
        self._register_download_handlers()
        self._register_stats_handlers()
        self._register_admin_handlers()
        self._register_system_handlers()
        self._register_test_handlers()

        self.logger.info("✅ Handler-Integration abgeschlossen")

    # ====== HANDLER-REGISTRIERUNG ======

    def _register_download_handlers(self) -> None:
        """Registriert Download-bezogene Handler."""
        self.menu_system.register_handler(
            "download_single", self._handle_download_single_wrapper
        )
        self.menu_system.register_handler(
            "download_playlist", self._handle_download_playlist_wrapper
        )
        self.logger.debug("📥 Download-Handler registriert")

    def _register_stats_handlers(self) -> None:
        """Registriert Statistik-Handler."""
        self.menu_system.register_handler(
            "stats_monthly", self._handle_monthly_stats_wrapper
        )
        self.menu_system.register_handler(
            "stats_yearly", self._handle_yearly_stats_wrapper
        )
        self.menu_system.register_handler(
            "stats_top_songs", self._handle_top_songs_wrapper
        )
        self.menu_system.register_handler(
            "stats_top_artists", self._handle_top_artists_wrapper
        )
        self.logger.debug("📊 Statistik-Handler registriert")

    def _register_admin_handlers(self) -> None:
        """Registriert Admin-Handler."""
        self.menu_system.register_handler(
            "admin_users", self._handle_user_management_wrapper
        )
        self.menu_system.register_handler("admin_logs", self._handle_view_logs)
        self.logger.debug("⚙️ Admin-Handler registriert")

    def _register_system_handlers(self) -> None:
        """Registriert System-Handler (Navidrome-Scan wird dynamisch hinzugefügt)."""
        navidrome_menu = MenuItem(
            id="admin_navidrome",
            title="Navidrome Scan",
            emoji="🔄",
            access_level=AccessLevel.ADMIN,
            handler=self._handle_navidrome_scan,
        )
        admin_menu = self.menu_system.menu_registry.get("admin")
        if admin_menu:
            admin_menu.add_child(navidrome_menu)
            self.menu_system.menu_registry[navidrome_menu.id] = navidrome_menu
        self.logger.debug("🔧 System-Handler registriert")

    def _register_test_handlers(self) -> None:
        """Registriert Test-bezogene Handler."""
        if self.test_handler:
            self.menu_system.register_handler(
                "test_unit", self.test_handler.run_unit_tests
            )
            self.menu_system.register_handler(
                "test_integration", self.test_handler.run_integration_tests
            )
            self.menu_system.register_handler(
                "test_performance", self.test_handler.run_performance_tests
            )
            self.logger.debug("🧪 Test-Handler registriert")
        else:
            self.logger.warning(
                "⚠️ TestMenuHandler nicht initialisiert – Tests deaktiviert."
            )

    # ====== SETTER ======

    def set_download_handler(self, handler: DownloadHandler) -> None:
        self.download_handler = handler
        self.logger.info("✅ DownloadHandler verbunden")

    def set_stats_handler(self, handler: StatistikHandler) -> None:
        self.stats_handler = handler
        self.logger.info("✅ StatsHandler verbunden")

    def set_admin_handler(self, handler: Any) -> None:
        self.admin_handler = handler
        self.logger.info("✅ AdminHandler verbunden")

    def set_navidrome_adapter(self, adapter: Any) -> None:
        self.navidrome_adapter = adapter
        self.logger.info("✅ NavidromeAdapter verbunden")

    def set_logger_handler(self, handler: EnhancedLoggerMenuHandler) -> None:
        self.logger_handler = handler
        if self.menu_system:
            self.menu_system.set_logger_handler(handler)
        self.logger.info("✅ EnhancedLoggerHandler verbunden")

    def set_error_handler(self, handler: EnhancedErrorHandler) -> None:
        """Setzt Error Handler und propagiert ihn an alle Handler."""
        self.error_handler = handler
        if self.menu_system:
            self.menu_system.error_handler = handler
            self.menu_system.set_error_handler(handler)
        for h in [
            self.logger_handler,
            self.navidrome_handler,
            self.test_handler,
            self.user_mgmt_handler,
        ]:
            if h:
                h.error_handler = handler
        self.logger.info("✅ Error Handler an alle Handler verteilt")

    def set_navidrome_handler(self, handler: NavidromeMenuHandler) -> None:
        self.navidrome_handler = handler
        if self.menu_system:
            self.menu_system.set_navidrome_handler(handler)
        self.logger.info("✅ NavidromeMenuHandler verbunden")

    def set_user_mgmt_handler(self, handler: Any) -> None:
        self.user_mgmt_handler = handler
        if self.menu_system:
            self.menu_system.set_user_mgmt_handler(handler)
        self.logger.info("✅ UserManagementHandler verbunden")

    def set_duplicate_handler(self, handler: EnhancedDuplicateHandler) -> None:
        self.duplicate_handler = handler
        if self.menu_system:
            self.menu_system.set_duplicate_handler(handler)
        self.logger.info("✅ EnhancedDuplicateHandler verbunden")

    def set_error_admin_interface(self, handler: ErrorHandlerAdminInterface) -> None:
        self.error_admin_interface = handler
        if self.menu_system:
            self.menu_system.set_error_admin_interface(handler)
        self.logger.info("✅ ErrorHandlerAdminInterface verbunden")

    def set_status_handler(self, handler: EnhancedStatusHandler) -> None:
        self.status_handler = handler
        if self.menu_system:
            self.menu_system.set_status_handler(handler)
        self.logger.info("✅ Status-Handler verbunden")

    def set_backup_handler(self, handler: BackupHandler) -> None:
        self.backup_handler = handler
        if self.menu_system:
            self.menu_system.set_backup_handler(handler)
        self.logger.info("✅ Backup-Handler verbunden")

    def set_restart_handler(self, handler: BotRestartHandler) -> None:
        self.restart_handler = handler
        if self.menu_system:
            self.menu_system.set_restart_handler(handler)
        self.logger.info("✅ Restart-Handler verbunden")

    # ── NEU: SpotifyDownloader-Setter ─────────────────────────────────────────
    def set_spotify_downloader(self, downloader: SpotifyDownloader) -> None:
        """
        Setzt eine extern erstellte SpotifyDownloader-Instanz.
        Nützlich wenn der SpotifyDownloader außerhalb des RichMenuHandlers
        erstellt wird (z.B. in bot.py).
        """
        self.spotify_downloader = downloader
        self.logger.info("✅ SpotifyDownloader (extern) verbunden")

    # ─────────────────────────────────────────────────────────────────────────

    # ====== TELEGRAM HANDLER LISTE ======

    def get_telegram_handlers(self) -> list:
        """
        Gibt die vollständige Liste der Telegram-Handler zurück.
        Reihenfolge: spezifischere Pattern zuerst, generische zuletzt.
        """
        from telegram.ext import CallbackQueryHandler, MessageHandler, filters

        return [
            # Command Handler
            CommandHandler("start", self.handle_start_command),
            CommandHandler("menu", self.handle_menu_command),
            CommandHandler("help", self.handle_help),
            # Callback Handler (spezifisch → allgemein)
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^logger_"),
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^nav_"),
            CallbackQueryHandler(
                self.menu_system.handle_callback, pattern="^usermgmt_"
            ),
            CallbackQueryHandler(self.handle_help_callback, pattern="^help:"),
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^dup:"),
            CallbackQueryHandler(
                self.menu_system.handle_callback, pattern="^erradmin:"
            ),
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^status_"),
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^backup_"),
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^restart:"),
            # Allgemeines Menü zuletzt
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^menu:"),
            # URL Handler (YouTube UND Spotify werden automatisch erkannt)
            MessageHandler(
                filters.TEXT & filters.Regex(r"https?://"),
                self.handle_url_message,
            ),
            # Text Handler (muss zuletzt stehen)
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"https?://"),
                self.handle_text_message,
            ),
        ]

    # ====== DOWNLOAD WRAPPER ======

    async def _handle_download_single_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Wrapper für Single-Download (YouTube oder Spotify)."""
        query = update.callback_query
        user_id = update.effective_user.id
        await query.answer()

        # Hinweistext angepasst um Spotify anzuzeigen
        spotify_hinweis = (
            "\nSpotify-Tracks werden ebenfalls unterstützt:\n"
            "`https://open.spotify.com/track/...`"
            if self.spotify_downloader
            else ""
        )
        await query.edit_message_text(
            "🎵 **Einzelner Track Download**\n\n"
            "Sende mir einen YouTube- oder Spotify-Link.\n\n"
            "YouTube-Beispiel:\n"
            "`https://youtube.com/watch?v=...`" + spotify_hinweis
        )
        self.user_states[user_id] = "awaiting_single_url"
        self.logger.info(f"📝 User {user_id} wartet auf Single-URL")

    async def _handle_download_playlist_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Wrapper für Playlist-Download (YouTube oder Spotify)."""
        query = update.callback_query
        user_id = update.effective_user.id
        await query.answer()

        spotify_hinweis = (
            "\nSpotify-Playlists werden ebenfalls unterstützt:\n"
            "`https://open.spotify.com/playlist/...`"
            if self.spotify_downloader
            else ""
        )
        await query.edit_message_text(
            "📋 **Playlist Download**\n\n"
            "Sende mir einen YouTube-Playlist-Link." + spotify_hinweis
        )
        self.user_states[user_id] = "awaiting_playlist_url"
        self.logger.info(f"📝 User {user_id} wartet auf Playlist-URL")

    # ====== STATISTIK WRAPPER ======

    async def _handle_monthly_stats_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        try:
            if self.stats_handler and hasattr(
                self.stats_handler, "handle_month_review"
            ):
                await self.stats_handler.handle_month_review(update, context)
            else:
                await query.edit_message_text(
                    "📅 **Monatsrückblick**\n\nDiese Funktion wird gerade entwickelt... 🚀"
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Monatsstatistik: {e}")
            await query.edit_message_text("❌ Fehler beim Laden der Statistiken")

    async def _handle_yearly_stats_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        try:
            if self.stats_handler and hasattr(self.stats_handler, "handle_year_review"):
                await self.stats_handler.handle_year_review(update, context)
            else:
                await query.edit_message_text(
                    "🎆 **Jahresrückblick**\n\nDiese Funktion wird gerade entwickelt... 🚀"
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Jahresstatistik: {e}")
            await query.edit_message_text("❌ Fehler beim Laden der Statistiken")

    async def _handle_top_songs_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer(f"Lade Top Songs ...")
        try:
            if self.stats_handler and hasattr(self.stats_handler, "handle_top_songs"):
                await self.stats_handler.handle_top_songs(
                    update, context, period="month"
                )
            else:
                await query.edit_message_text(
                    "🎵 **Top Songs**\n\nStatistik-Handler nicht gefunden."
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Top Songs Statistik: {e}")
            await query.edit_message_text("❌ Fehler beim Laden der Statistiken")

    async def _handle_top_artists_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer("Lade Top Künstler ...")
        try:
            if self.stats_handler and hasattr(self.stats_handler, "handle_top_artists"):
                await self.stats_handler.handle_top_artists(
                    update, context, period="month"
                )
            else:
                await query.edit_message_text(
                    "🎤 **Top Künstler**\n\nStatistik-Handler nicht gefunden."
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Top Künstler Statistik: {e}")
            await query.edit_message_text("❌ Fehler beim Laden der Statistiken")

    # ====== ADMIN WRAPPER ======

    async def _handle_user_management_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung")
            return
        await query.answer()
        try:
            if self.user_mgmt_handler:
                await self.user_mgmt_handler.show_user_management_menu(
                    update, context, page=0
                )
            else:
                await query.edit_message_text(
                    "⚠️ UserManagement-Handler nicht verfügbar."
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler in Benutzerverwaltung: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "user_management", e
                )
            else:
                await query.edit_message_text(
                    "❌ Fehler beim Laden der Benutzerverwaltung"
                )

    async def _handle_view_logs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung")
            return
        await query.answer()
        try:
            log_file = Path(self.config.LOG_FILE)
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    last_lines = lines[-20:]
                log_text = "".join(last_lines)
                await query.edit_message_text(
                    f"📄 **System-Logs** (letzte 20 Zeilen)\n\n```\n{log_text[:3000]}\n```",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    "📄 **System-Logs**\n\nLog-Datei nicht gefunden."
                )
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Logs: {e}")
            await query.edit_message_text("❌ Fehler beim Laden der Logs")

    async def _handle_navidrome_scan(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung")
            return
        await query.answer("🔄 Starte Scan ...")
        try:
            if self.navidrome_adapter:
                result = await self.navidrome_adapter.trigger_scan()
                text = (
                    "✅ **Navidrome Scan gestartet**\n\nDie Library wird aktualisiert..."
                    if result
                    else "⚠️ **Navidrome Scan**\n\nScan konnte nicht gestartet werden."
                )
                await query.edit_message_text(text)
            else:
                await query.edit_message_text(
                    "⚠️ **Navidrome Scan**\n\nNavidrome-Adapter nicht verfügbar."
                )
        except Exception as e:
            self.logger.error(f"❌ Navidrome-Scan-Fehler: {e}")
            await query.edit_message_text(f"❌ **Fehler beim Scan**\n\n{str(e)}")

    # ====== HILFS-METHODEN ======

    def _is_admin(self, user_id: int) -> bool:
        """Prüft Admin- oder Owner-Rechte."""
        if user_id == self.config.OWNER_USER_ID:
            return True
        return user_id in getattr(self.config, "ADMIN_USER_IDS", [])

    def _load_user_data(self) -> Dict[str, Any]:
        """Lädt User-Daten aus JSON."""
        try:
            if self.user_data_file.exists():
                with open(self.user_data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if self.user_mgmt_handler:
                        self.user_mgmt_handler.user_data_cache = data
                    return data
            return {}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der User-Daten: {e}")
            return {}

    def _get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Holt User-Informationen."""
        if self.user_mgmt_handler and self.user_mgmt_handler.user_data_cache:
            return self.user_mgmt_handler.user_data_cache.get(str(user_id))
        users = self._load_user_data()
        return users.get(str(user_id))

    def _is_new_user(self, user_id: int) -> bool:
        """Prüft ob User neu ist (< 24h registriert)."""
        user_info = self._get_user_info(user_id)
        if not user_info:
            return True
        created_at = user_info.get("created_at")
        if created_at:
            try:
                created_time = datetime.fromisoformat(created_at)
                return (datetime.now() - created_time).total_seconds() < 86400
            except Exception:
                pass
        return False

    def _get_user_role(self, user_id: int) -> str:
        """Ermittelt User-Rolle (owner > admin > moderator > user)."""
        if user_id == self.config.OWNER_USER_ID:
            return "owner"
        user_info = self._get_user_info(user_id)
        if user_info:
            return user_info.get("role", "user")
        if user_id in getattr(self.config, "ADMIN_USER_IDS", []):
            return "admin"
        return "user"

    def _get_available_features(self, user_role: str) -> Dict[str, Dict]:
        """Gibt verfügbare Features basierend auf Rolle zurück."""
        role_hierarchy = {"user": 0, "moderator": 1, "admin": 2, "owner": 3}
        user_level = role_hierarchy.get(user_role, 0)
        return {
            fid: fdata
            for fid, fdata in self.features.items()
            if user_level >= role_hierarchy.get(fdata.get("min_role", "user"), 0)
        }

    def _create_download_handler(self, update: Update) -> Optional[DownloadHandler]:
        """
        Erstellt eine neue DownloadHandler-Instanz mit allen injizierten
        Abhängigkeiten.

        Der SpotifyDownloader wird als geteilte Instanz übergeben, um
        wiederholte spotdl-Checks und Credential-Initialisierungen zu vermeiden.
        Der MetadataProcessor und DuplicateHandler werden ebenfalls geteilt.

        Args:
            update: Telegram-Update-Objekt

        Returns:
            Fertig konfigurierter DownloadHandler oder None bei fehlenden
            Abhängigkeiten.
        """
        if not self.duplicate_handler:
            self.logger.error(
                "❌ DuplicateHandler nicht initialisiert – Download nicht möglich."
            )
            return None
        if not self.metadata_processor:
            self.logger.error(
                "❌ MetadataProcessor nicht initialisiert – Download nicht möglich."
            )
            return None

        return DownloadHandler(
            update=update,
            config=self.config,
            duplicate_handler=self.duplicate_handler,
            metadata_processor=self.metadata_processor,
            logger_factory=self.logger_factory,
            # ── NEU: Geteilte SpotifyDownloader-Instanz injizieren ────────────
            # Wenn None: DownloadHandler versucht Auto-Init aus Config-Credentials
            # oder gibt verständliche Fehlermeldung bei Spotify-URLs aus.
            spotify_downloader=self.spotify_downloader,
        )

    # ====== COMMAND HANDLER ======

    async def handle_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Erweiterter /start Command Handler mit personalisierter Begrüßung."""
        try:
            user = update.effective_user
            user_id = user.id
            username = user.username or user.first_name

            self.logger.info(f"🚀 /start von User {user_id} ({username})")

            is_new = self._is_new_user(user_id)
            user_role = self._get_user_role(user_id)
            available_features = self._get_available_features(user_role)

            greeting_parts = []
            if is_new:
                greeting_parts.extend(
                    [
                        f"👋 **Willkommen, {username}!**\n",
                        "🎉 Schön, dass du hier bist!",
                        "Lass mich dir zeigen, was ich kann...\n",
                    ]
                )
            else:
                greeting_parts.extend(
                    [
                        f"👋 **Hallo zurück, {username}!**\n",
                        "Schön, dich wiederzusehen!\n",
                    ]
                )

            if user_role != "user":
                role_emoji = {"moderator": "🛡️", "admin": "⚙️", "owner": "👑"}.get(
                    user_role, "👤"
                )
                greeting_parts.append(
                    f"\n{role_emoji} Deine Rolle: **{user_role.capitalize()}**\n"
                )

            greeting_parts.append("\n📚 **Verfügbare Funktionen:**\n")
            for feature_id, feature in available_features.items():
                greeting_parts.append(f"{feature['emoji']} **{feature['title']}**")
                greeting_parts.append(f"   _{feature['description']}_\n")

            greeting_parts.extend(
                [
                    "\n💡 **Schnellstart:**",
                    "• Nutze /menu für das Hauptmenü",
                    "• Nutze /help für detaillierte Hilfe",
                ]
            )

            if "download" in available_features:
                greeting_parts.append(
                    "• Sende mir einen YouTube- oder Spotify-Link zum Download"
                )
            if "navidrome" in available_features:
                greeting_parts.append("• Nutze /search um Musik zu suchen")

            greeting = "\n".join(greeting_parts)

            keyboard = [
                [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")]
            ]
            feature_buttons = [
                InlineKeyboardButton(
                    f"{fdata['emoji']} {fdata['title']}",
                    callback_data=f"menu:{fdata.get('menu_id', fid)}",
                )
                for fid, fdata in available_features.items()
            ]
            for i in range(0, len(feature_buttons), 2):
                keyboard.append(feature_buttons[i : i + 2])
            keyboard.append(
                [InlineKeyboardButton("❓ Hilfe", callback_data="help:main")]
            )

            await update.message.reply_text(
                greeting,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            self.logger.info(f"✅ Start-Nachricht gesendet an {user_id}")

        except Exception as e:
            self.logger.error(f"❌ Fehler in handle_start_command: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_command_error(
                    update, context, "start", e
                )
            else:
                try:
                    await update.message.reply_text("❌ Ein Fehler ist aufgetreten.")
                except Exception:
                    pass

    async def handle_menu_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt Hauptmenü bei /menu."""
        self.logger.info(f"📱 /menu von User {update.effective_user.id}")
        await self.menu_system.show_menu(update, context, "main")

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Erweiterter /help Command Handler."""
        try:
            user_id = update.effective_user.id
            user_role = self._get_user_role(user_id)
            available_features = self._get_available_features(user_role)

            self.logger.info(f"❓ /help von User {user_id}")

            help_parts = [
                "📚 **Hilfe & Dokumentation**\n",
                "Übersicht aller Funktionen:\n",
            ]
            for feature_id, feature in available_features.items():
                commands = feature.get("commands", [])
                help_parts.append(f"{feature['emoji']} **{feature['title']}**")
                help_parts.append(feature["description"])
                if commands:
                    help_parts.append(f"_Befehle: {', '.join(commands)}_\n")
                else:
                    help_parts.append("")

            help_parts.extend(
                [
                    "\n⚡ **Allgemeine Befehle:**",
                    "• /start - Bot neu starten",
                    "• /menu - Hauptmenü öffnen",
                    "• /help - Diese Hilfe anzeigen",
                    "• /cancel - Aktion abbrechen\n",
                    "💬 **Benötigst du Unterstützung?**",
                    "Nutze /menu und navigiere zu den jeweiligen Funktionen.",
                ]
            )

            keyboard = [
                [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")],
                [
                    InlineKeyboardButton("📥 Downloads", callback_data="help:download"),
                    InlineKeyboardButton("📊 Statistiken", callback_data="help:stats"),
                ],
                [InlineKeyboardButton("🎵 Navidrome", callback_data="help:navidrome")],
            ]
            if user_role in ["admin", "owner"]:
                keyboard.append(
                    [InlineKeyboardButton("⚙️ Admin-Hilfe", callback_data="help:admin")]
                )
            keyboard.append(
                [InlineKeyboardButton("❌ Schließen", callback_data="menu:close")]
            )

            await update.message.reply_text(
                "\n".join(help_parts),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as e:
            self.logger.error(f"❌ Fehler in handle_help: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_command_error(
                    update, context, "help", e
                )

    async def handle_help_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Callback-Handler für spezifische Hilfe-Themen (pattern='^help:')."""
        try:
            query = update.callback_query
            topic = query.data.split(":", 1)[-1]
            await query.answer()

            user_id = update.effective_user.id
            user_role = self._get_user_role(user_id)

            help_texts = {
                "download": self._get_download_help(),
                "stats": self._get_stats_help(),
                "navidrome": self._get_navidrome_help(),
                "admin": (
                    self._get_admin_help() if user_role in ["admin", "owner"] else None
                ),
            }

            help_text = help_texts.get(topic) if topic != "main" else None

            if topic == "main" or not help_text:
                main_text = "📚 **Hilfe & Dokumentation**\n\nWähle ein Thema:"
                keyboard = [
                    [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")],
                    [
                        InlineKeyboardButton(
                            "📥 Downloads", callback_data="help:download"
                        ),
                        InlineKeyboardButton(
                            "📊 Statistiken", callback_data="help:stats"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🎵 Navidrome", callback_data="help:navidrome"
                        )
                    ],
                ]
                if user_role in ["admin", "owner"]:
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "⚙️ Admin-Hilfe", callback_data="help:admin"
                            )
                        ]
                    )
                keyboard.append(
                    [InlineKeyboardButton("❌ Schließen", callback_data="menu:close")]
                )
                await query.edit_message_text(
                    main_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown",
                )
                return

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Zurück zur Hilfe", callback_data="help:main"
                        )
                    ],
                    [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")],
                    [InlineKeyboardButton("❌ Schließen", callback_data="menu:close")],
                ]
            )
            await query.edit_message_text(
                help_text, reply_markup=keyboard, parse_mode="Markdown"
            )

        except Exception as e:
            self.logger.error(f"❌ Fehler in handle_help_callback: {e}", exc_info=True)

    # ====== HILFE-TEXTE ======

    def _get_download_help(self) -> str:
        """Hilfe für Download-Funktionen (YouTube + Spotify)."""
        spotify_section = (
            "\n\n**🎵 Spotify-Downloads:**\n"
            "• Einzelne Tracks: `https://open.spotify.com/track/...`\n"
            "• Alben: `https://open.spotify.com/album/...`\n"
            "• Playlists: `https://open.spotify.com/playlist/...`\n\n"
            "_Benötigt: spotdl (pip install spotdl) oder Spotify-Credentials in config.py_"
            if self.spotify_downloader
            else ""
        )
        return (
            "📥 **Download-Hilfe**\n\n"
            "**YouTube-Downloads:**\n"
            "1. Kopiere einen YouTube-Link\n"
            "2. Sende ihn an den Bot\n"
            "3. Der Bot lädt die Musik herunter\n\n"
            "Beispiel: `https://youtube.com/watch?v=...`\n\n"
            "**Unterstützte Formate:**\n"
            "• Einzelne Videos, Playlists, Mix-Playlists" + spotify_section
        )

    def _get_stats_help(self) -> str:
        return (
            "📊 **Statistik-Hilfe**\n\n"
            "• 📅 Monatsrückblick\n"
            "• 🎆 Jahresrückblick\n"
            "• 🎵 Top Songs\n"
            "• 🎤 Top Künstler\n\n"
            "Alle Statistiken basieren auf deinem Navidrome-Account."
        )

    def _get_navidrome_help(self) -> str:
        return (
            "🎵 **Navidrome-Hilfe**\n\n"
            "• 🔍 Suche nach Songs, Alben, Künstlern\n"
            "• 📂 Durchsuche nach Kategorien\n"
            "• ⭐ Favoriten verwalten\n"
            "• 📋 Playlists verwalten\n\n"
            "Befehle: /search, /menu → Navidrome"
        )

    def _get_admin_help(self) -> str:
        return (
            "⚙️ **Admin-Hilfe**\n\n"
            "• 👥 Benutzerverwaltung\n"
            "• 📊 Logger-Verwaltung\n"
            "• 🔄 Bot neu starten\n"
            "• 💾 Backup-Verwaltung\n"
            "• 🧪 Test-System\n"
            "• 🚨 Error-Verwaltung\n\n"
            "Alle Admin-Aktionen werden geloggt."
        )

    # ====== MESSAGE HANDLER ======

    async def handle_url_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Verarbeitet URL-Nachrichten basierend auf dem User-State.

        Erkennt automatisch ob die URL zu YouTube oder Spotify gehört.
        Die eigentliche URL-Unterscheidung erfolgt in DownloadHandler.handle_url().
        """
        user_id = update.effective_user.id
        text = update.message.text
        state = self.user_states.get(user_id)

        if not state:
            # Keine aktive Menü-Auswahl – URL direkt verarbeiten
            await self._process_url(update, context, text)
            return

        if state in ["awaiting_single_url", "awaiting_playlist_url"]:
            await self._process_url(update, context, text)
            # State nach Verarbeitung aufräumen
            if user_id in self.user_states:
                del self.user_states[user_id]

    async def _process_url(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str,
    ) -> None:
        """
        Erstellt einen DownloadHandler und startet den Download-Prozess.

        Verwendet handle_url() als unified Einstiegspunkt, der intern
        automatisch zwischen YouTube und Spotify unterscheidet.

        Args:
            update: Telegram-Update-Objekt
            context: Telegram-Kontext
            url: Die zu verarbeitende URL
        """
        url_type = "🎵 Spotify" if _is_spotify_url(url) else "📺 YouTube"
        self.logger.info(
            f"🔗 Verarbeite {url_type}-URL von User {update.effective_user.id}: {url}"
        )

        handler = self._create_download_handler(update)
        if not handler:
            await update.message.reply_text(
                "❌ Download-Dienst nicht verfügbar. Bitte versuche es später erneut."
            )
            return

        # ── NEU: handle_url() erkennt automatisch YT vs. Spotify ─────────────
        # Kein manueller _is_spotify_url-Check nötig – DownloadHandler.handle_url()
        # delegiert intern an handle_spotify_url() oder handle_youtube_links().
        await handler.handle_url(update, context)

    # Alias für Rückwärtskompatibilität (wird von älterem Code ggf. noch aufgerufen)
    async def _initiate_download(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, state: str
    ) -> None:
        """
        Legacy-Wrapper – delegiert an _process_url().
        Bleibt für Rückwärtskompatibilität erhalten.
        """
        await self._process_url(update, context, url)

    async def _handle_regular_url(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
    ) -> None:
        """
        Legacy-Wrapper – delegiert an _process_url().
        Bleibt für Rückwärtskompatibilität erhalten.
        """
        await self._process_url(update, context, url)

    async def handle_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Verarbeitet Text-Nachrichten.
        Unterstützt Multi-Step Workflows für User-Management und Navidrome-Suche.
        """
        user_id = update.effective_user.id
        text = update.message.text

        # Abbruch-Befehl
        # BUG-006-Fix: stand vorher NACH dem Workflow-Dispatch-Block, der bei
        # aktivem Workflow immer vorher returnt (siehe unten) - "/cancel"
        # wurde dadurch nie als Abbruch erkannt, solange ein Workflow aktiv
        # war, sondern als wortwoertliche Eingabe an den Workflow-Handler
        # durchgereicht (z.B. process_new_user_id(..., "/cancel") ->
        # "ungueltige Eingabe"), obwohl die Bot-Nachrichten selbst genau
        # dieses /cancel als Ausstieg bewerben ("Du kannst /cancel eingeben,
        # um abzubrechen").
        if text.lower() in ["/cancel", "cancel", "abbrechen"]:
            context.user_data.clear()
            if user_id in self.user_states:
                del self.user_states[user_id]
            await update.message.reply_text(
                "❌ Vorgang abgebrochen.\n\nVerwende /menu, um das Menü zu öffnen."
            )
            return

        # Navidrome-Suche prüfen
        if self.navidrome_handler:
            if user_id in self.navidrome_handler.browse_states:
                user_state = self.navidrome_handler.browse_states[user_id]
                if user_state.get("waiting_for_search", False):
                    handled = await self.navidrome_handler.process_search_query(
                        update, context, text
                    )
                    if handled:
                        return

        # Aktive Workflows prüfen
        workflow = context.user_data.get("workflow")
        if workflow:
            self.logger.debug(f"📝 Aktiver Workflow erkannt: {workflow}")

            workflow_handlers = {
                "add_user_id": (self.user_mgmt_handler, "process_new_user_id"),
                "add_user_navidrome": (
                    self.user_mgmt_handler,
                    "process_new_navidrome_user",
                ),
                "edit_navidrome_user": (
                    self.user_mgmt_handler,
                    "process_edit_navidrome_user",
                ),
            }

            entry = workflow_handlers.get(workflow)
            if entry:
                handler_obj, method_name = entry
                if handler_obj and hasattr(handler_obj, method_name):
                    await getattr(handler_obj, method_name)(update, context, text)
                else:
                    await update.message.reply_text(
                        f"❌ Handler für Workflow '{workflow}' nicht verfügbar."
                    )
                    context.user_data.clear()
                return

        self.logger.debug(
            f"📝 Unbehandelte Text-Nachricht von User {user_id}: {text[:50]}"
        )

    # ====== CLEANUP ======

    def cleanup(self) -> None:
        """Bereinigt abgelaufene Sessions und gibt Ressourcen frei."""
        cleaned = self.menu_system.cleanup_expired_sessions()
        # Nur loggen, wenn tatsächlich etwas bereinigt wurde
        if cleaned > 0:
            self.logger.info(f"🧹 Cleanup: {cleaned} Sessions entfernt")
