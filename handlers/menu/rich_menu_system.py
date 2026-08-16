# handlers/menu/rich_menu_system.py
# -*- coding: utf-8 -*-
"""
🎯 RichMenuSystem - Hierarchisches Menüsystem mit State Machine
ERWEITERT MIT LOGGER-MANAGEMENT INTEGRATION

CHANGELOG:
  - v2.1  Bot-Neustart-Feature:
          • self.restart_handler = None  (__init__)
          • set_restart_handler()        (neuer Setter)
          • admin_restart MenuItem       (initialize_menu_structure)
          • restart:-Routing             (handle_callback)
          • _handle_restart_show()       (neuer Wrapper)
          • _handle_restart_callback()   (neuer Dispatcher)
          • _is_admin_check()            (interne Hilfsmethode)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Set
from enum import Enum
from datetime import datetime, timedelta
import json
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from logger import get_module_logger


class MenuState(Enum):
    """Menü-Zustände für State Machine"""

    IDLE = "idle"
    MAIN_MENU = "main_menu"
    DOWNLOAD_MENU = "download_menu"
    STATS_MENU = "stats_menu"
    ADMIN_MENU = "admin_menu"
    SETTINGS_MENU = "settings_menu"
    LOGGER_MENU = "logger_menu"
    PROCESSING = "processing"
    WAITING_INPUT = "waiting_input"
    ERROR = "error"


class AccessLevel(Enum):
    """Zugriffsebenen für Menüpunkte"""

    PUBLIC = 0
    USER = 1
    MODERATOR = 2
    ADMIN = 3
    OWNER = 4


@dataclass
class MenuItem:
    """Einzelner Menüpunkt mit allen Eigenschaften"""

    id: str
    title: str
    emoji: str = "📋"
    callback_data: Optional[str] = None
    handler: Optional[Callable] = None
    children: List["MenuItem"] = field(default_factory=list)
    parent: Optional["MenuItem"] = None
    access_level: AccessLevel = AccessLevel.USER
    description: Optional[str] = None
    is_active: bool = True
    is_action: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Automatische Callback-Data Generierung"""
        if not self.callback_data:
            self.callback_data = f"menu:{self.id}"

    def has_children(self) -> bool:
        """Prüft ob Menüpunkt Untermenüs hat"""
        return len(self.children) > 0

    def is_accessible(self, user_level: AccessLevel) -> bool:
        """Prüft Zugriffsberechtigung"""
        return user_level.value >= self.access_level.value

    def add_child(self, child: "MenuItem") -> None:
        """Fügt Untermenü hinzu"""
        child.parent = self
        self.children.append(child)

    def get_breadcrumb(self) -> List[str]:
        """Erstellt Brotkrumen-Navigation"""
        path = []
        current = self
        while current:
            path.insert(0, current.title)
            current = current.parent
        return path


@dataclass
class MenuSession:
    """Benutzer-Session für Menü-Interaktionen"""

    user_id: int
    current_menu: Optional[MenuItem] = None
    state: MenuState = MenuState.IDLE
    history: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    message_id: Optional[int] = None

    def is_expired(self, timeout: int = 300) -> bool:
        """Prüft ob Session abgelaufen ist"""
        return (datetime.now() - self.last_activity).seconds > timeout

    def update_activity(self) -> None:
        """Aktualisiert letzte Aktivität"""
        self.last_activity = datetime.now()

    def navigate_to(self, menu_item: MenuItem) -> None:
        """Navigiert zu neuem Menüpunkt"""
        if self.current_menu:
            self.history.append(self.current_menu.id)
        self.current_menu = menu_item
        self.update_activity()

    def go_back(self) -> Optional[str]:
        """Navigiert zurück"""
        if self.history:
            return self.history.pop()
        return None


class RichMenuSystem:
    """
    Haupt-Menüsystem mit vollständiger Funktionalität
    """

    def __init__(self, config, logger_factory=None):
        self.config = config
        self.logger = (logger_factory or get_module_logger)("RichMenuSystem")

        # Core Komponenten
        self.root_menu: Optional[MenuItem] = None
        self.menu_registry: Dict[str, MenuItem] = {}
        self.sessions: Dict[int, MenuSession] = {}
        self.handlers: Dict[str, Callable] = {}

        # Handler-Referenzen
        self.logger_handler = None
        self.navidrome_handler = None
        self.stats_handler = None
        self.error_handler = None
        self.user_mgmt_handler = None
        self.duplicate_handler = None
        self.error_admin_interface = None
        self.status_handler = None
        self.backup_handler = None
        self.restart_handler = None  # NEU: Bot-Neustart-Handler

        # Konfiguration
        self.session_timeout = getattr(config, "SESSION_TIMEOUT", 300)
        self.max_sessions = getattr(config, "MAX_CONCURRENT_SESSIONS", 100)

        self.logger.info("🎯 RichMenuSystem initialisiert")

    # ====== SETTER ======

    def set_error_handler(self, handler) -> None:
        """Setzt den Error Handler"""
        self.error_handler = handler
        self.logger.info("✅ Error-Handler verknüpft")

    def set_logger_handler(self, handler) -> None:
        """Setzt den Logger-Handler"""
        self.logger_handler = handler
        self.logger.info("✅ Logger-Handler verknüpft")

    def set_stats_handler(self, handler) -> None:
        """Setzt den Statistik-Handler"""
        self.stats_handler = handler
        self.logger.info("✅ Statistik-Handler verknüpft")

    def set_navidrome_handler(self, handler) -> None:
        """Setzt den Navidrome-Handler"""
        self.navidrome_handler = handler
        self.logger.info("✅ Navidrome-Handler verknüpft")

    def set_user_mgmt_handler(self, handler) -> None:
        """Setzt den User-Management-Handler"""
        self.user_mgmt_handler = handler
        self.logger.info("✅ UserManagement-Handler verknüpft")

    def set_duplicate_handler(self, handler) -> None:
        """Setzt den Duplicate-Handler"""
        self.duplicate_handler = handler
        self.logger.info("✅ Duplicate-Handler verknüpft")

    def set_error_admin_interface(self, handler) -> None:
        """Setzt das Error Handler Admin Interface"""
        self.error_admin_interface = handler
        self.logger.info("✅ Error-Admin-Interface verknüpft")

    def set_status_handler(self, handler) -> None:
        """Setzt den Status-Handler"""
        self.status_handler = handler
        self.logger.info("✅ Status-Handler verknüpft")

    def set_backup_handler(self, handler) -> None:
        """Setzt den Backup-Handler"""
        self.backup_handler = handler
        self.logger.info("✅ Backup-Handler verknüpft")

    def set_restart_handler(self, handler) -> None:
        """
        Setzt den BotRestartHandler.
        Wird von RichMenuHandler.initialize() aufgerufen.
        """
        self.restart_handler = handler
        self.logger.info("✅ Restart-Handler verknüpft")

    # ====== MENÜ-STRUKTUR ======

    def initialize_menu_structure(self) -> None:
        """Erstellt die Menü-Hierarchie"""
        self.logger.info("🗂️ Erstelle Menü-Struktur...")

        # Hauptmenü
        self.root_menu = MenuItem(
            id="main",
            title="Hauptmenü",
            emoji="🏠",
            description="Willkommen beim Musik-Bot",
        )

        # Download-Menü
        download_menu = MenuItem(
            id="download",
            title="Downloads",
            emoji="📥",
            description="Musik herunterladen",
        )
        download_menu.add_child(
            MenuItem(
                id="download_single",
                title="Einzelner Track",
                emoji="🎵",
                handler=self._handle_download_single,
                is_action=True,
            )
        )
        download_menu.add_child(
            MenuItem(
                id="download_playlist",
                title="Playlist",
                emoji="📋",
                handler=self._handle_download_playlist,
                is_action=True,
            )
        )

        # Statistik-Menü
        stats_menu = MenuItem(
            id="stats",
            title="Statistiken",
            emoji="📊",
            description="Übersichten und Analysen",
        )
        stats_menu.add_child(
            MenuItem(
                id="stats_monthly",
                title="Monatsrückblick",
                emoji="📅",
                handler=self._handle_stats_monthly,
                is_action=True,
            )
        )
        stats_menu.add_child(
            MenuItem(
                id="stats_yearly",
                title="Jahresrückblick",
                emoji="🎆",
                handler=self._handle_stats_yearly,
                is_action=True,
            )
        )
        stats_menu.add_child(
            MenuItem(
                id="stats_top_songs",
                title="Top Songs",
                emoji="🎵",
                handler=self._handle_stats_top_songs,
                is_action=True,
            )
        )
        stats_menu.add_child(
            MenuItem(
                id="stats_top_artists",
                title="Top Künstler",
                emoji="🎤",
                handler=self._handle_stats_top_artists,
                is_action=True,
            )
        )

        # Admin-Menü
        admin_menu = MenuItem(
            id="admin",
            title="Administration",
            emoji="⚙️",
            access_level=AccessLevel.ADMIN,
            description="System-Verwaltung",
        )

        # System-Status
        admin_menu.add_child(
            MenuItem(
                id="admin_status",
                title="System-Status",
                emoji="📊",
                access_level=AccessLevel.ADMIN,
                callback_data="status_menu",
                handler=self._handle_status_menu,
                is_action=True,
            )
        )

        # Benutzerverwaltung
        admin_menu.add_child(
            MenuItem(
                id="admin_users",
                title="Benutzerverwaltung",
                emoji="👥",
                access_level=AccessLevel.ADMIN,
                is_action=True,
            )
        )

        # System-Logs
        admin_menu.add_child(
            MenuItem(
                id="admin_logs",
                title="System-Logs",
                emoji="📄",
                access_level=AccessLevel.ADMIN,
                is_action=True,
            )
        )

        # Duplikat-Verwaltung
        duplicate_menu = MenuItem(
            id="admin_duplicates",
            title="Duplikat-Verwaltung",
            emoji="♻️",
            access_level=AccessLevel.ADMIN,
            description="Verwaltung des Download-Duplikat-Cache",
        )
        duplicate_menu.add_child(
            MenuItem(
                id="dup_show_stats",
                title="Statistiken anzeigen",
                emoji="📊",
                callback_data="dup:show_stats",
                is_action=True,
                handler=None,
            )
        )
        duplicate_menu.add_child(
            MenuItem(
                id="dup_clear_cache_confirm",
                title="Cache leeren",
                emoji="🗑️",
                callback_data="dup:clear_cache_confirm",
                is_action=True,
                handler=None,
            )
        )
        admin_menu.add_child(duplicate_menu)

        # Error-Verwaltung
        error_menu = MenuItem(
            id="admin_errors",
            title="Error-Verwaltung",
            emoji="🚨",
            access_level=AccessLevel.ADMIN,
            description="Überwachung und Verwaltung des Error Handlers",
        )
        error_menu.add_child(
            MenuItem(
                id="erradmin_stats",
                title="Statistiken",
                emoji="📊",
                callback_data="erradmin:show_stats",
                is_action=True,
            )
        )
        error_menu.add_child(
            MenuItem(
                id="erradmin_report",
                title="Gesundheitsbericht",
                emoji="🏥",
                callback_data="erradmin:show_report",
                is_action=True,
            )
        )
        error_menu.add_child(
            MenuItem(
                id="erradmin_recent",
                title="Letzte Fehler",
                emoji="🕐",
                callback_data="erradmin:show_recent",
                is_action=True,
            )
        )
        error_menu.add_child(
            MenuItem(
                id="erradmin_reset_confirm",
                title="Statistiken zurücksetzen",
                emoji="🔄",
                callback_data="erradmin:reset_confirm",
                is_action=True,
            )
        )
        admin_menu.add_child(error_menu)

        # Logger-Management
        logger_menu = MenuItem(
            id="logger",
            title="Logger-Verwaltung",
            emoji="📊",
            access_level=AccessLevel.ADMIN,
            description="Erweiterte Logger-Steuerung und -Überwachung",
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_main_menu",
                title="Logger-Übersicht",
                emoji="🏠",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_main_menu,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_modules_list",
                title="Module verwalten",
                emoji="📦",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_modules,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_global_level",
                title="Globales Level",
                emoji="🌍",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_global_level,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_files_list",
                title="Log-Dateien",
                emoji="📁",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_files,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_global_stats",
                title="Statistiken",
                emoji="📈",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_stats,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_handlers_list",
                title="Handler-Verwaltung",
                emoji="⚡",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_handlers,
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_cleanup_menu",
                title="Bereinigung",
                emoji="🧹",
                access_level=AccessLevel.ADMIN,
                handler=self._handle_logger_cleanup,
                is_action=True,
            )
        )
        admin_menu.add_child(logger_menu)

        # Backup-Verwaltung
        backup_menu = MenuItem(
            id="admin_backup",
            title="Backup-Verwaltung",
            emoji="💾",
            access_level=AccessLevel.ADMIN,
            description="Sicherung von Bot-Verzeichnis und Musikbibliothek",
        )
        backup_menu.add_child(
            MenuItem(
                id="backup_main",
                title="Backup-Übersicht",
                emoji="🏠",
                access_level=AccessLevel.ADMIN,
                callback_data="backup_main",
                handler=self._handle_backup_main,
                is_action=True,
            )
        )
        backup_menu.add_child(
            MenuItem(
                id="backup_bot_confirm",
                title="Bot sichern",
                emoji="🤖",
                access_level=AccessLevel.ADMIN,
                callback_data="backup_bot_confirm",
                handler=self._handle_backup_bot_confirm,
                is_action=True,
            )
        )
        backup_menu.add_child(
            MenuItem(
                id="backup_lib_confirm",
                title="Library sichern",
                emoji="🎵",
                access_level=AccessLevel.ADMIN,
                callback_data="backup_lib_confirm",
                handler=self._handle_backup_lib_confirm,
                is_action=True,
            )
        )
        backup_menu.add_child(
            MenuItem(
                id="backup_list_bot",
                title="Bot-Backups",
                emoji="📋",
                access_level=AccessLevel.ADMIN,
                callback_data="backup_list_bot",
                handler=self._handle_backup_list_bot,
                is_action=True,
            )
        )
        backup_menu.add_child(
            MenuItem(
                id="backup_list_lib",
                title="Library-Backups",
                emoji="📋",
                access_level=AccessLevel.ADMIN,
                callback_data="backup_list_lib",
                handler=self._handle_backup_list_lib,
                is_action=True,
            )
        )
        admin_menu.add_child(backup_menu)

        # ====== NEU: BOT-NEUSTART ======
        admin_menu.add_child(
            MenuItem(
                id="admin_restart",
                title="Bot neu starten",
                emoji="🔄",
                access_level=AccessLevel.ADMIN,
                callback_data="restart:show",
                handler=self._handle_restart_show,
                is_action=True,
                description="Bot-Service via systemctl neu starten",
            )
        )
        # ====== ENDE BOT-NEUSTART ======

        # Test-Menü
        test_menu = MenuItem(
            id="tests",
            title="Test-System",
            emoji="🧪",
            access_level=AccessLevel.ADMIN,
            description="Unit-, Integrations- und Performance-Tests ausführen",
        )
        test_menu.add_child(
            MenuItem(
                id="test_unit",
                title="Unit Tests ausführen",
                emoji="🔬",
                access_level=AccessLevel.ADMIN,
                is_action=True,
            )
        )
        test_menu.add_child(
            MenuItem(
                id="test_integration",
                title="Integration Tests ausführen",
                emoji="🔗",
                access_level=AccessLevel.ADMIN,
                is_action=True,
            )
        )
        test_menu.add_child(
            MenuItem(
                id="test_performance",
                title="Performance Tests ausführen",
                emoji="⚡",
                access_level=AccessLevel.ADMIN,
                is_action=True,
            )
        )

        # Navidrome-Menü
        navidrome_menu = MenuItem(
            id="navidrome",
            title="Navidrome Mediathek",
            emoji="🎵",
            access_level=AccessLevel.USER,
            description="Durchsuche und verwalte deine Musikbibliothek",
        )

        # Browse-Untermenüs
        browse_menu = MenuItem(
            id="navidrome_browse",
            title="Durchsuchen",
            emoji="🔍",
            description="Musikbibliothek nach Kategorien durchsuchen",
        )
        browse_menu.add_child(
            MenuItem(
                id="nav_browse_artists",
                title="Künstler",
                emoji="🎤",
                handler=self._handle_navidrome_browse_artists,
                is_action=True,
            )
        )
        browse_menu.add_child(
            MenuItem(
                id="nav_browse_albums",
                title="Alben",
                emoji="💿",
                handler=self._handle_navidrome_browse_albums,
                is_action=True,
            )
        )
        browse_menu.add_child(
            MenuItem(
                id="nav_browse_genres",
                title="Genres",
                emoji="🎭",
                handler=self._handle_navidrome_browse_genres,
                is_action=True,
            )
        )
        browse_menu.add_child(
            MenuItem(
                id="nav_browse_playlists",
                title="Playlists",
                emoji="📋",
                handler=self._handle_navidrome_browse_playlists,
                is_action=True,
            )
        )

        # Suche-Menü
        search_menu = MenuItem(
            id="navidrome_search",
            title="Suchen",
            emoji="🔎",
            description="Musikbibliothek durchsuchen",
        )
        search_menu.add_child(
            MenuItem(
                id="nav_search",
                title="Überall suchen",
                emoji="🔍",
                handler=self._handle_navidrome_search_all,
                is_action=True,
            )
        )
        search_menu.add_child(
            MenuItem(
                id="nav_search_artists",
                title="Künstler suchen",
                emoji="🎤",
                handler=self._handle_navidrome_search_artists,
                is_action=True,
            )
        )
        search_menu.add_child(
            MenuItem(
                id="nav_search_albums",
                title="Alben suchen",
                emoji="💿",
                handler=self._handle_navidrome_search_albums,
                is_action=True,
            )
        )
        search_menu.add_child(
            MenuItem(
                id="nav_search_songs",
                title="Songs suchen",
                emoji="🎵",
                handler=self._handle_navidrome_search_songs,
                is_action=True,
            )
        )

        navidrome_menu.add_child(browse_menu)
        navidrome_menu.add_child(search_menu)
        navidrome_menu.add_child(
            MenuItem(
                id="nav_playlists",
                title="Meine Playlists",
                emoji="📋",
                handler=self._handle_navidrome_my_playlists,
                is_action=True,
            )
        )
        navidrome_menu.add_child(
            MenuItem(
                id="nav_favorites",
                title="Favoriten",
                emoji="⭐",
                handler=self._handle_navidrome_favorites,
                is_action=True,
            )
        )
        navidrome_menu.add_child(
            MenuItem(
                id="nav_recent",
                title="Zuletzt gespielt",
                emoji="🕐",
                handler=self._handle_navidrome_recent,
                is_action=True,
            )
        )
        navidrome_menu.add_child(
            MenuItem(
                id="nav_link_stats",
                title="Statistiken",
                emoji="📊",
                callback_data="menu:stats",
                handler=None,
                is_action=False,
            )
        )

        # Menüs zum Root hinzufügen
        self.root_menu.add_child(download_menu)
        self.root_menu.add_child(stats_menu)
        self.root_menu.add_child(admin_menu)
        self.root_menu.add_child(test_menu)
        self.root_menu.add_child(navidrome_menu)

        # Registry aufbauen
        self._build_registry(self.root_menu)

        self.logger.info(f"✅ Menü-Struktur erstellt: {len(self.menu_registry)} Items")

    def _build_registry(self, menu: MenuItem) -> None:
        """Baut flache Registry für schnellen Zugriff"""
        self.menu_registry[menu.id] = menu
        for child in menu.children:
            self._build_registry(child)

    # ====== LOGGER-HANDLER WRAPPER ======

    async def _handle_logger_main_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Logger-Hauptmenü"""
        if self.logger_handler:
            await self.logger_handler.show_main_menu(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_modules(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Logger-Module"""
        if self.logger_handler:
            await self.logger_handler.show_modules_list(update, context, page=0)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_global_level(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für globales Log-Level"""
        if self.logger_handler:
            await self.logger_handler.show_global_level_menu(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_files(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Log-Dateien"""
        if self.logger_handler:
            await self.logger_handler.show_log_files_list(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Logger-Statistiken"""
        if self.logger_handler:
            await self.logger_handler.show_comprehensive_statistics(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_handlers(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Handler-Verwaltung"""
        if self.logger_handler:
            await self.logger_handler.manage_handlers_advanced(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    async def _handle_logger_cleanup(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Logger-Bereinigung"""
        if self.logger_handler:
            await self.logger_handler.show_cleanup_menu(update, context)
        else:
            await self._show_handler_not_available(update, "Logger-Handler")

    # ====== BACKUP-HANDLER WRAPPER ======

    async def _handle_backup_main(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Backup-Hauptmenü"""
        if self.backup_handler:
            await self.backup_handler.show_main_menu(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_bot_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Bot-Backup Bestätigung"""
        if self.backup_handler:
            await self.backup_handler.confirm_bot_backup(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_lib_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Library-Backup Bestätigung"""
        if self.backup_handler:
            await self.backup_handler.confirm_lib_backup(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_bot_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Bot-Backup starten"""
        if self.backup_handler:
            await self.backup_handler.start_bot_backup(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_lib_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Library-Backup starten"""
        if self.backup_handler:
            await self.backup_handler.start_lib_backup(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_list_bot(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Bot-Backup-Liste anzeigen"""
        if self.backup_handler:
            await self.backup_handler.show_list_bot(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    async def _handle_backup_list_lib(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Library-Backup-Liste anzeigen"""
        if self.backup_handler:
            await self.backup_handler.show_list_lib(update, context)
        else:
            await self._show_handler_not_available(update, "Backup-Handler")

    # ====== NEU: BOT-NEUSTART WRAPPER ======

    async def _handle_restart_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Einstiegspunkt aus dem Menü-System für den Bot-Neustart.
        Leitet an BotRestartHandler.show_restart_confirm() weiter.
        """
        if not self.restart_handler:
            query = update.callback_query
            await query.answer("⚠️ Restart-Handler nicht verfügbar", show_alert=True)
            return
        await self.restart_handler.show_restart_confirm(update, context)

    # ====== ENDE BOT-NEUSTART WRAPPER ======

    async def _show_handler_not_available(self, update: Update, handler_name: str):
        """Zeigt Fehlermeldung wenn Handler nicht verfügbar"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            f"⚠️ {handler_name} nicht verfügbar\n\n"
            f"Bitte warte bis das System vollständig geladen ist."
        )

    # ====== NAVIDROME WRAPPER ======

    async def _handle_navidrome_browse_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Künstler-Browse"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_browse_artists(update, context)
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_browse_albums(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Album-Browse"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_browse_albums(update, context)
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_browse_genres(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Genre-Browse"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_browse_genres(update, context)
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_browse_playlists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Playlist-Browse"""
        if self.navidrome_handler:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "📋 Playlist-Browser wird gerade entwickelt..."
            )
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_search_all(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für universelle Suche"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_search(update, context, "all")
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_search_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Künstler-Suche"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_search(update, context, "artists")
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_search_albums(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Album-Suche"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_search(update, context, "albums")
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_search_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Song-Suche"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_search(update, context, "songs")
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_my_playlists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Meine Playlists"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_my_playlists(update, context)
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_favorites(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Favoriten"""
        if self.navidrome_handler:
            await self.navidrome_handler.handle_favorites(update, context)
        else:
            await self._show_handler_not_available(update, "Navidrome-Handler")

    async def _handle_navidrome_recent(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Zuletzt gespielt (ruft StatistikHandler auf)"""
        if self.stats_handler and hasattr(self.stats_handler, "handle_last_played"):
            await self.stats_handler.handle_last_played(update, context)
        else:
            await self._show_handler_not_available(update, "Statistik-Handler")

    # ====== SESSION MANAGEMENT ======

    def get_session(self, user_id: int) -> MenuSession:
        """Holt oder erstellt User-Session"""
        if user_id not in self.sessions:
            self.sessions[user_id] = MenuSession(user_id=user_id)
            self.logger.debug(f"📝 Neue Session für User {user_id}")

        session = self.sessions[user_id]

        if session.is_expired(self.session_timeout):
            self.logger.info(f"⏰ Session für User {user_id} abgelaufen, erneuere...")
            self.sessions[user_id] = MenuSession(user_id=user_id)
            session = self.sessions[user_id]

        session.update_activity()
        return session

    def render_menu(
        self, menu_item: MenuItem, user_level: AccessLevel = AccessLevel.USER
    ) -> InlineKeyboardMarkup:
        """Erstellt Telegram InlineKeyboard für Menü"""
        keyboard = []

        accessible_items = [
            item
            for item in menu_item.children
            if item.is_active and item.is_accessible(user_level)
        ]

        for i in range(0, len(accessible_items), 2):
            row = []
            for item in accessible_items[i : i + 2]:
                button_text = f"{item.emoji} {item.title}"
                row.append(
                    InlineKeyboardButton(button_text, callback_data=item.callback_data)
                )
            keyboard.append(row)

        if menu_item.parent:
            keyboard.append(
                [InlineKeyboardButton("⬅️ Zurück", callback_data="menu:back")]
            )

        if not menu_item.parent or menu_item.id == "main":
            keyboard.append(
                [InlineKeyboardButton("❌ Schließen", callback_data="menu:close")]
            )
        elif menu_item.parent and menu_item.id != "main":
            keyboard.append(
                [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")]
            )

        return InlineKeyboardMarkup(keyboard)

    def get_menu_text(self, menu_item: MenuItem) -> str:
        """Erstellt Menü-Text mit Breadcrumb"""
        breadcrumb = " > ".join(menu_item.get_breadcrumb())

        text_parts = [
            f"📍 **Navigation:** {breadcrumb}",
            "",
        ]

        if menu_item.description:
            text_parts.extend(
                [
                    menu_item.description,
                    "",
                ]
            )

        if menu_item.has_children():
            text_parts.append("Wähle eine Option:")

        return "\n".join(text_parts)

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        menu_id: Optional[str] = None,
    ) -> None:
        """Zeigt Menü an oder aktualisiert es"""
        query = update.callback_query
        user_id = update.effective_user.id

        session = self.get_session(user_id)

        if menu_id:
            menu_item = self.menu_registry.get(menu_id, self.root_menu)
        elif session.current_menu:
            menu_item = session.current_menu
        else:
            menu_item = self.root_menu

        session.navigate_to(menu_item)

        user_level = self._get_user_access_level(user_id)

        text = self.get_menu_text(menu_item)
        keyboard = self.render_menu(menu_item, user_level)

        try:
            if query:
                if (
                    query.message.text == text
                    and query.message.reply_markup == keyboard
                ):
                    await query.answer("ℹ️ Ansicht bereits aktuell.")
                    return

                await query.answer()
                await query.edit_message_text(
                    text, reply_markup=keyboard, parse_mode="Markdown"
                )
                session.message_id = query.message.message_id
            else:
                message = await update.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="Markdown"
                )
                session.message_id = message.message_id

            self.logger.info(f"📱 Menü '{menu_item.id}' angezeigt für User {user_id}")

        except Exception as e:
            if "Message is not modified" in str(e):
                self.logger.debug("Menü-Update übersprungen (keine Änderung).")
            else:
                self.logger.error(
                    f"❌ Fehler beim Anzeigen des Menüs: {e}", exc_info=True
                )

    # ====== HAUPT-CALLBACK-HANDLER ======

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Haupt-Callback-Handler mit vollständigem Präfix-Routing.
        Alle Präfixe werden hier zentral dispatcht.
        """
        query = update.callback_query
        user_id = update.effective_user.id
        callback_data = query.data

        try:
            self.logger.debug(f"📞 Callback: {callback_data} von User {user_id}")

            # ── Spezial-Aktionen ──────────────────────────────────────
            if callback_data == "menu:close":
                await self._handle_close(update, context)
                return

            if callback_data == "menu:back":
                await self._handle_back(update, context)
                return

            # ── Zentrale Admin-Prüfung für sicherheitsrelevante Präfixe ──
            # handle_callback dispatchte diese Callbacks bisher ohne jede
            # Berechtigungsprüfung. callback_data ist ein von jedem Telegram-
            # Client frei sendbarer String, nicht an tatsächlich gerenderte
            # Buttons gebunden - jeder Nutzer konnte z.B. per
            # "usermgmt_set_role_<eigene_id>_owner" sich selbst zum Owner
            # machen. is_accessible() in render_menu() blendet Buttons nur
            # aus, prüft aber nichts beim tatsächlichen Callback-Empfang.
            # (erradmin: und restart: haben bereits eigene Admin-Checks in
            # ihren jeweiligen Dispatchern.)
            _ADMIN_ONLY_PREFIXES = ("logger_", "usermgmt_", "dup:", "backup_")
            if callback_data.startswith(_ADMIN_ONLY_PREFIXES) and not self._is_admin_check(
                user_id
            ):
                self.logger.warning(
                    f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte Admin-Callback: "
                    f"{callback_data}"
                )
                await query.answer("⛔ Keine Berechtigung", show_alert=True)
                return

            # ── Logger (hohe Priorität wegen Paginierung) ─────────────
            if callback_data.startswith("logger_modules_page_"):
                page = int(callback_data.replace("logger_modules_page_", ""))
                await self.logger_handler.show_modules_list(update, context, page)
                return

            if callback_data == "logger_modules_info":
                await query.answer("ℹ️ Verwende ⬅️➡️ zum Navigieren")
                return

            if callback_data == "logger_search_module":
                await self.logger_handler.search_module(update, context)
                return

            # ── Präfix-basiertes Routing ──────────────────────────────
            if callback_data.startswith("logger_"):
                await self._handle_logger_callback(update, context, callback_data)
                return

            if callback_data.startswith("nav_"):
                await self._handle_navidrome_callback(update, context, callback_data)
                return

            if callback_data.startswith("usermgmt_"):
                await self._handle_usermgmt_callback(update, context, callback_data)
                return

            if callback_data.startswith("dup:"):
                await self._handle_duplicate_callback(update, context, callback_data)
                return

            if callback_data.startswith("erradmin:"):
                await self._handle_error_admin_callback(update, context, callback_data)
                return

            if callback_data.startswith("status_"):
                await self._handle_status_callback(update, context, callback_data)
                return

            if callback_data.startswith("backup_"):
                await self._handle_backup_callback(update, context, callback_data)
                return

            # ── NEU: Bot-Neustart ─────────────────────────────────────
            if callback_data.startswith("restart:"):
                await self._handle_restart_callback(update, context, callback_data)
                return

            # ── Standard Menü-Callback (menu:...) ────────────────────
            if callback_data.startswith("menu:"):
                menu_id = callback_data.split(":", 1)[1]
            else:
                await query.answer("⚠️ Unbekannter Menü-Präfix")
                return

            menu_item = self._find_menu_item_by_id(menu_id)

            if not menu_item:
                await query.answer("⚠️ Menüpunkt nicht gefunden")
                return

            if menu_item.handler:
                self.logger.info(f"⚡ Aktion '{menu_item.id}' wird ausgeführt.")
                await query.answer()
                await menu_item.handler(update, context)
                return
            else:
                self.logger.info(
                    f"📱 Menü '{menu_item.id}' angezeigt für User {user_id}"
                )
                await query.answer()
                await self.show_menu(update, context, menu_id)
                return

        except Exception as e:
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, callback_data, e
                )
            else:
                self.logger.error(f"❌ Callback Error: {e}", exc_info=True)
                try:
                    await query.answer("❌ Ein Fehler ist aufgetreten")
                except Exception:
                    pass

    # ====== CALLBACK-DISPATCHER ======

    async def _handle_logger_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle logger_* Callbacks"""
        if not self.logger_handler:
            await update.callback_query.answer("⚠️ Logger-Handler nicht verfügbar")
            return

        query = update.callback_query
        await query.answer()

        routing_map = {
            "logger_main_menu": self.logger_handler.show_main_menu,
            "logger_modules_list": self.logger_handler.show_modules_list,
            "logger_global_level": self.logger_handler.show_global_level_menu,
            "logger_files_list": self.logger_handler.show_log_files_list,
            "logger_global_stats": self.logger_handler.show_comprehensive_statistics,
            "logger_handlers_list": self.logger_handler.manage_handlers_advanced,
            "logger_cleanup_menu": self.logger_handler.show_cleanup_menu,
            "logger_enable_all": self.logger_handler.enable_all_modules,
            "logger_disable_all": self.logger_handler.disable_all_modules,
            "logger_add_module": self.logger_handler.add_module,
            "logger_files_stats": self.logger_handler.show_log_files_stats,
            "logger_configure_handlers": self.logger_handler.configure_handlers,
            "logger_handler_details": self.logger_handler.handler_details,
            "logger_add_handler": self.logger_handler.add_handler,
            "logger_remove_handler": self.logger_handler.remove_handler,
            "logger_reload_handlers": self.logger_handler.reload_handlers,
        }

        if callback_data.startswith("logger_module_detail_"):
            module_name = callback_data.replace("logger_module_detail_", "")
            await self.logger_handler.show_module_detail(update, context, module_name)
            return

        if callback_data.startswith("logger_module_toggle_"):
            module_name = callback_data.replace("logger_module_toggle_", "")
            await self.logger_handler.toggle_module(update, context, module_name)
            return

        if callback_data.startswith("logger_module_level_"):
            module_name = callback_data.replace("logger_module_level_", "")
            await self.logger_handler.show_module_level_menu(
                update, context, module_name
            )
            return

        if callback_data.startswith("logger_set_module_level_"):
            parts = callback_data.replace("logger_set_module_level_", "").split("_", 1)
            if len(parts) == 2:
                module_name, level = parts
                await self.logger_handler.set_module_level(
                    update, context, module_name, level
                )
            return

        if callback_data.startswith("logger_set_global_level_"):
            level = callback_data.replace("logger_set_global_level_", "")
            await self.logger_handler.set_global_log_level(update, context, level)
            return

        if callback_data.startswith("logger_file_detail_"):
            filename = callback_data.replace("logger_file_detail_", "")
            await self.logger_handler.show_log_file_detail(update, context, filename)
            return

        if callback_data.startswith("logger_file_download_"):
            filename = callback_data.replace("logger_file_download_", "")
            await self.logger_handler.download_log_file(update, context, filename)
            return

        handler_method = routing_map.get(callback_data)
        if handler_method:
            await handler_method(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter Logger-Callback: {callback_data}")
            await query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_navidrome_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle nav_* Callbacks"""
        if not self.navidrome_handler:
            await update.callback_query.answer("⚠️ Navidrome-Handler nicht verfügbar")
            return

        query = update.callback_query
        await query.answer()

        self.logger.debug(f"🎵 Navidrome-Callback: {callback_data}")

        if callback_data.startswith("nav_browse_artists"):
            parts = callback_data.split("_")
            page = int(parts[3]) if len(parts) > 3 else 0
            await self.navidrome_handler.handle_browse_artists(update, context, page)
            return

        if callback_data.startswith("nav_browse_albums"):
            parts = callback_data.split("_")
            page = int(parts[3]) if len(parts) > 3 else 0
            artist_id = parts[4] if len(parts) > 4 else None
            await self.navidrome_handler.handle_browse_albums(
                update, context, page, artist_id
            )
            return

        if callback_data == "nav_browse_genres":
            await self.navidrome_handler.handle_browse_genres(update, context)
            return

        if callback_data.startswith("nav_artist_"):
            artist_id = callback_data.replace("nav_artist_", "")
            await self.navidrome_handler.handle_artist_detail(
                update, context, artist_id
            )
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
            await self.navidrome_handler.handle_genre_detail(
                update, context, genre_name
            )
            return

        if callback_data == "nav_search":
            await self.navidrome_handler.handle_search(update, context, "all")
            return

        if callback_data == "nav_search_artists":
            await self.navidrome_handler.handle_search(update, context, "artists")
            return

        if callback_data == "nav_search_albums":
            await self.navidrome_handler.handle_search(update, context, "albums")
            return

        if callback_data == "nav_search_songs":
            await self.navidrome_handler.handle_search(update, context, "songs")
            return

        if callback_data == "nav_search_genres":
            await query.edit_message_text(
                "🔎 Genre-Suche\n\nDiese Funktion wird gerade entwickelt..."
            )
            return

        if callback_data == "nav_reconnect":
            await self.navidrome_handler.handle_reconnect(update, context)
            return

        if callback_data == "nav_genre_stats":
            await query.edit_message_text(
                "📊 Genre-Statistiken\n\nDiese Funktion wird gerade entwickelt..."
            )
            return

        self.logger.warning(f"⚠️ Unbekannter Navidrome-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_usermgmt_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """
        Spezial-Handler für alle usermgmt_* Callbacks
        Unterstützt Navidrome-User-Workflows
        """
        if not self.user_mgmt_handler:
            await update.callback_query.answer(
                "⚠️ UserManagement-Handler nicht verfügbar"
            )
            return

        query = update.callback_query
        admin_user_id = update.effective_user.id
        await query.answer()

        self.logger.debug(f"👥 UserMgmt-Callback: {callback_data}")

        if callback_data == "usermgmt_add_user":
            context.user_data["workflow"] = "add_user_id"
            context.user_data.pop("pending_user_id", None)
            context.user_data.pop("target_user_id", None)
            await query.edit_message_text(
                "➕ **Neuen Benutzer hinzufügen (Schritt 1/2)**\n\n"
                "Bitte sende mir jetzt die **Telegram User-ID** des neuen Benutzers als Nachricht.\n\n"
                "*(Du kannst /cancel eingeben, um abzubrechen)*",
                parse_mode="Markdown",
            )
            return

        if callback_data.startswith("usermgmt_set_navidrome_"):
            target_user_id = callback_data.replace("usermgmt_set_navidrome_", "")
            context.user_data["workflow"] = "edit_navidrome_user"
            context.user_data["target_user_id"] = target_user_id
            await query.edit_message_text(
                f"👤 **Navidrome-Benutzer festlegen**\n\n"
                f"Betroffene User-ID: `{target_user_id}`\n\n"
                "Bitte sende mir jetzt den **Navidrome-Benutzernamen** für diesen Benutzer.\n\n"
                "*(Du kannst /cancel eingeben, um abzubrechen)*",
                parse_mode="Markdown",
            )
            return

        if callback_data.startswith("usermgmt_list_"):
            page = int(callback_data.replace("usermgmt_list_", ""))
            await self.user_mgmt_handler.show_user_management_menu(
                update, context, page
            )
            return

        if callback_data.startswith("usermgmt_detail_"):
            user_id = callback_data.replace("usermgmt_detail_", "")
            await self.user_mgmt_handler.show_user_detail(update, context, user_id)
            return

        if callback_data.startswith("usermgmt_change_role_"):
            user_id = callback_data.replace("usermgmt_change_role_", "")
            await self.user_mgmt_handler.show_role_change_menu(update, context, user_id)
            return

        if callback_data.startswith("usermgmt_set_role_"):
            parts = callback_data.replace("usermgmt_set_role_", "").split("_", 1)
            if len(parts) == 2:
                user_id, new_role = parts
                await self.user_mgmt_handler.set_user_role(
                    update, context, user_id, new_role
                )
            return

        if callback_data.startswith("usermgmt_delete_confirm_"):
            user_id = callback_data.replace("usermgmt_delete_confirm_", "")
            await self.user_mgmt_handler.delete_user_confirm(update, context, user_id)
            return

        if callback_data.startswith("usermgmt_delete_confirmed_"):
            user_id = callback_data.replace("usermgmt_delete_confirmed_", "")
            await self.user_mgmt_handler.delete_user(update, context, user_id)
            return

        routing_map = {
            "usermgmt_stats": self.user_mgmt_handler.show_statistics,
            "usermgmt_search": lambda u, c: query.edit_message_text(
                "🔍 **Benutzer suchen**\n\nDiese Funktion wird gerade entwickelt..."
            ),
            "usermgmt_cleanup": lambda u, c: query.edit_message_text(
                "🗑️ **Aufräumen**\n\nDiese Funktion wird gerade entwickelt..."
            ),
            "usermgmt_pending": lambda u, c: query.edit_message_text(
                "📋 **Pending Users**\n\nKeine wartenden Benutzer."
            ),
        }

        if callback_data.startswith("usermgmt_permissions_"):
            user_id = callback_data.replace("usermgmt_permissions_", "")
            await self.user_mgmt_handler.show_permission_menu(update, context, user_id)
            return

        if callback_data.startswith("usermgmt_toggle_perm_"):
            parts = callback_data.replace("usermgmt_toggle_perm_", "").split("_", 1)
            if len(parts) == 2:
                user_id, permission = parts
                await self.user_mgmt_handler.toggle_user_permission(
                    update, context, user_id, permission
                )
            return

        if callback_data.startswith("usermgmt_ban_"):
            user_id = callback_data.replace("usermgmt_ban_", "")
            await query.edit_message_text(
                f"🚫 **Benutzer sperren**\n\nUser: {user_id}\n\n"
                "Diese Funktion wird gerade entwickelt..."
            )
            return

        handler_method = routing_map.get(callback_data)
        if handler_method:
            await handler_method(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter UserMgmt-Callback: {callback_data}")
            await query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_duplicate_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle dup:* Callbacks"""
        if not self.duplicate_handler:
            await update.callback_query.answer("⚠️ Duplicate-Handler nicht verfügbar")
            return

        query = update.callback_query

        self.logger.debug(f"♻️ Duplicate-Callback: {callback_data}")

        if callback_data == "dup:show_stats":
            await query.answer("Lade Statistiken...")
            await self.duplicate_handler.show_statistics_menu(update, context)
            return

        if callback_data == "dup:clear_cache_confirm":
            await query.answer()
            await self.duplicate_handler.show_clear_cache_confirm(update, context)
            return

        if callback_data == "dup:clear_cache_execute":
            await query.answer("Cache wird geleert...")
            await self.duplicate_handler.execute_clear_cache(update, context)
            return

        self.logger.warning(f"⚠️ Unbekannter Duplicate-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_error_admin_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle erradmin:* Callbacks"""
        if not self.error_admin_interface:
            await update.callback_query.answer(
                "⚠️ Error Admin Interface nicht verfügbar"
            )
            return

        user_id = update.effective_user.id
        if not self.error_admin_interface.is_admin(user_id):
            await update.callback_query.answer("⛔ Keine Berechtigung")
            return

        self.logger.debug(f"🚨 ErrorAdmin-Callback: {callback_data}")

        routing_map = {
            "erradmin:show_stats": self.error_admin_interface.handle_error_stats_command,
            "erradmin:show_report": self.error_admin_interface.handle_error_report_command,
            "erradmin:show_recent": self.error_admin_interface.handle_recent_errors_command,
            "erradmin:reset_confirm": self.error_admin_interface.show_reset_stats_confirm,
            "erradmin:reset_execute": self.error_admin_interface.execute_reset_stats,
        }

        handler_method = routing_map.get(callback_data)
        if handler_method:
            await handler_method(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter ErrorAdmin-Callback: {callback_data}")
            await update.callback_query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_status_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle status_* Callbacks"""
        if not self.status_handler:
            await update.callback_query.answer("⚠️ Status-Handler nicht verfügbar")
            return

        query = update.callback_query
        await query.answer()

        self.logger.debug(f"📊 Status-Callback: {callback_data}")

        routing_map = {
            "status_menu": self.status_handler.show_status_menu,
            "status_system": self.status_handler.show_system_status,
            "status_bot": self.status_handler.show_bot_status,
            "status_services": self.status_handler.show_services_status,
            "status_performance": self.status_handler.show_performance_status,
            "status_storage": self.status_handler.show_storage_status,
            "status_refresh": self.status_handler.show_status_menu,
        }

        handler_method = routing_map.get(callback_data)
        if handler_method:
            await handler_method(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter Status-Callback: {callback_data}")
            await query.answer("⚠️ Funktion nicht implementiert")

    async def _handle_backup_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle backup_* Callbacks"""
        if not self.backup_handler:
            await update.callback_query.answer("⚠️ Backup-Handler nicht verfügbar")
            return

        query = update.callback_query
        await query.answer()

        self.logger.debug(f"💾 Backup-Callback: {callback_data}")

        if callback_data.startswith("backup_delete_confirm_"):
            filename = callback_data.replace("backup_delete_confirm_", "")
            await self.backup_handler.confirm_delete(update, context, filename)
            return

        if callback_data.startswith("backup_delete_"):
            filename = callback_data.replace("backup_delete_", "")
            await self.backup_handler.delete_backup(update, context, filename)
            return

        routing_map = {
            "backup_main": self.backup_handler.show_main_menu,
            "backup_bot_confirm": self.backup_handler.confirm_bot_backup,
            "backup_lib_confirm": self.backup_handler.confirm_lib_backup,
            "backup_bot_start": self.backup_handler.start_bot_backup,
            "backup_lib_start": self.backup_handler.start_lib_backup,
            "backup_list_bot": self.backup_handler.show_list_bot,
            "backup_list_lib": self.backup_handler.show_list_lib,
        }

        handler_method = routing_map.get(callback_data)
        if handler_method:
            await handler_method(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter Backup-Callback: {callback_data}")
            await query.answer("⚠️ Funktion nicht implementiert")

    # ====== NEU: BOT-NEUSTART CALLBACK-DISPATCHER ======

    async def _handle_restart_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle restart:* Callbacks.

        Routing:
          restart:show    → Bestätigungs-Dialog anzeigen
          restart:confirm → Neustart ausführen
          restart:cancel  → Neustart abbrechen
        """
        if not self.restart_handler:
            await update.callback_query.answer(
                "⚠️ Restart-Handler nicht verfügbar", show_alert=True
            )
            return

        # Admin-Check
        user_id = update.effective_user.id
        if not self._is_admin_check(user_id):
            await update.callback_query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        self.logger.debug(f"🔄 Restart-Callback: {callback_data} von User {user_id}")

        routing: dict = {
            "restart:show": self.restart_handler.show_restart_confirm,
            "restart:confirm": self.restart_handler.execute_restart,
            "restart:cancel": self.restart_handler.cancel_restart,
        }

        handler_fn = routing.get(callback_data)
        if handler_fn:
            await handler_fn(update, context)
        else:
            self.logger.warning(f"⚠️ Unbekannter Restart-Callback: {callback_data}")
            await update.callback_query.answer("⚠️ Unbekannte Aktion")

    # ====== ENDE BOT-NEUSTART CALLBACK-DISPATCHER ======

    async def _handle_status_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Status-Menü"""
        if self.status_handler:
            await self.status_handler.show_status_menu(update, context)
        else:
            await self._show_handler_not_available(update, "Status-Handler")

    async def _handle_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Navigiert zurück"""
        user_id = update.effective_user.id
        session = self.get_session(user_id)

        previous_id = session.go_back()
        if previous_id:
            await self.show_menu(update, context, previous_id)
        else:
            await self.show_menu(update, context, "main")

    async def _handle_close(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Schließt Menü"""
        query = update.callback_query
        user_id = update.effective_user.id

        if user_id in self.sessions:
            del self.sessions[user_id]

        await query.answer("👋 Menü geschlossen")
        try:
            await query.message.delete()
        except Exception as e:
            self.logger.warning(f"Konnte Menü-Nachricht nicht löschen: {e}")

    def _find_menu_item_by_id(self, menu_id: str) -> Optional[MenuItem]:
        """Findet MenuItem anhand seiner ID"""
        return self.menu_registry.get(menu_id)

    def _find_menu_by_callback(self, callback_data: str) -> Optional[MenuItem]:
        """Findet MenuItem anhand Callback-Data"""
        for item in self.menu_registry.values():
            if item.callback_data == callback_data:
                return item
        return None

    def _get_user_access_level(self, user_id: int) -> AccessLevel:
        """Ermittelt Zugriffsebene des Users"""
        if user_id == self.config.OWNER_USER_ID:
            return AccessLevel.OWNER

        if self.user_mgmt_handler and hasattr(
            self.user_mgmt_handler, "user_data_cache"
        ):
            user_data = self.user_mgmt_handler.user_data_cache.get(str(user_id))
            if user_data:
                role_str = user_data.get("role", "user").upper()
                if role_str == "ADMIN":
                    return AccessLevel.ADMIN
                if role_str == "MODERATOR":
                    return AccessLevel.MODERATOR
                if role_str == "USER":
                    return AccessLevel.USER

        if user_id in getattr(self.config, "ADMIN_USER_IDS", []):
            return AccessLevel.ADMIN

        return AccessLevel.USER

    def _is_admin_check(self, user_id: int) -> bool:
        """
        Interne Admin-Prüfung (wiederverwendbar).
        Gibt True zurück für Owner und alle konfigurierten Admins.
        """
        if user_id == getattr(self.config, "OWNER_USER_ID", None):
            return True
        return user_id in getattr(self.config, "ADMIN_USER_IDS", [])

    def register_handler(self, menu_id: str, handler: Callable) -> None:
        """Registriert Handler für Menüpunkt"""
        if menu_id in self.menu_registry:
            self.menu_registry[menu_id].handler = handler
            self.logger.info(f"✅ Handler registriert für '{menu_id}'")
        else:
            self.logger.warning(f"⚠️ Menü-ID '{menu_id}' nicht gefunden")

    def cleanup_expired_sessions(self) -> int:
        """Entfernt abgelaufene Sessions"""
        expired = [
            uid
            for uid, session in self.sessions.items()
            if session.is_expired(self.session_timeout)
        ]

        for uid in expired:
            del self.sessions[uid]

        if expired:
            self.logger.info(f"🧹 {len(expired)} abgelaufene Sessions bereinigt")

        return len(expired)

    # ====== PLATZHALTER-HANDLER ======

    async def _handle_download_single(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🎵 Einzelner Track - Sende mir einen YouTube-Link!"
        )

    async def _handle_download_playlist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("📋 Playlist - Sende mir einen Playlist-Link!")

    async def _handle_stats_monthly(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_month_review(update, context)
        else:
            await query.edit_message_text("📅 Lade Monatsstatistiken...")

    async def _handle_stats_yearly(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_year_review(update, context)
        else:
            await query.edit_message_text("🎆 Lade Jahresstatistiken...")

    async def _handle_stats_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_top_songs(update, context, period="month")
        else:
            await query.edit_message_text("🎵 Lade Top Songs...")

    async def _handle_stats_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_top_artists(update, context, period="month")
        else:
            await query.edit_message_text("🎤 Lade Top Künstler...")
