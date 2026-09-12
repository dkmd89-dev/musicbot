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

from typing import Dict, List, Optional, Callable, Any, Set
from datetime import datetime, timedelta
import json
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from logger import get_module_logger
from handlers.menu.maintenance_gate import is_blocked_by_maintenance
from handlers.menu.activity_tracking import record_activity
from handlers.menu.models import (
    AccessLevel,
    MenuItem,
    MenuSession,
    MenuState,
)
from handlers.menu.permissions import is_admin_or_owner, get_user_access_level
from handlers.menu.session import SessionManager


def _dl_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Track-Fortschrittsbalken für "🔄 Aktive Downloads" (Download-
    Control-Center 2026-09-02) - eigener, kleiner Helfer für die
    Track-Anzahl innerhalb EINES Downloads, nicht zu verwechseln mit dem
    6-Schritte-Pipelinebalken in klassen/download_handler.py."""
    filled = round(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {current}/{total}"


class _RetryMessageAdapter:
    """Duck-Typing-Stellvertreter für update.message, beschränkt auf genau
    die zwei Attribute, die klassen/download_handler.py entlang des
    handle_url()/handle_youtube_links()-Pfads tatsächlich liest (verifiziert
    per grep: nur .text und .reply_text(...))."""

    def __init__(self, text: str, reply_text: Callable):
        self.text = text
        self.reply_text = reply_text


class _RetryUpdateAdapter:
    """Duck-Typing-Stellvertreter für ein Update-Objekt, siehe
    RichMenuSystem._handle_download_retry()-Docstring für die Begründung
    (PTB-Update-/Message-Objekte sind eingefroren, dürfen nicht mutiert
    werden). effective_user/effective_chat/update_id werden 1:1 vom echten,
    auslösenden Callback-Query-Update übernommen (die sind bereits real und
    gültig) - nur .message wird durch einen Stellvertreter mit der
    gespeicherten Verlaufs-URL ersetzt, .reply_text sendet über die echte
    Bot-Message des Callback-Queries (callback_query.message.reply_text)."""

    def __init__(self, source_update: Update, url: str):
        self.effective_user = source_update.effective_user
        self.effective_chat = source_update.effective_chat
        self.update_id = source_update.update_id
        self.message = _RetryMessageAdapter(
            text=url,
            reply_text=source_update.callback_query.message.reply_text,
        )


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
        self.handlers: Dict[str, Callable] = {}

        # Handler-Referenzen
        self.logger_handler = None
        self.navidrome_handler = None
        self.stats_handler = None
        # Familien-Statistik (Phase F2, Family Hub): von RichMenuHandler
        # injiziert - siehe set_family_stats_handler(). Eigenständig von
        # stats_handler, da FamilyStatsHandler zusätzlich eine
        # Family-Membership-Prüfung durchführt, bevor irgendein
        # Family-Datum gesendet wird.
        self.family_stats_handler = None
        # Familien-Chat (Phase F3, Family Hub): von RichMenuHandler
        # injiziert - siehe set_family_chat_handler().
        self.family_chat_handler = None
        # Familien-Challenge (Phase F4, Family Hub): von RichMenuHandler
        # injiziert - siehe set_family_challenge_handler().
        self.family_challenge_handler = None
        self.error_handler = None
        self.user_mgmt_handler = None
        self.duplicate_handler = None
        self.error_admin_interface = None
        self.status_handler = None
        self.backup_handler = None
        self.restart_handler = None  # NEU: Bot-Neustart-Handler
        # Download-Control-Center 2026-09-02: geteilte, prozessweite
        # ActiveDownloadRegistry (services/downloader/active_downloads.py),
        # von RichMenuHandler injiziert - siehe set_active_downloads().
        self.active_downloads = None
        # Download-Verlauf-Feature: geteilte, prozessweite
        # DownloadHistoryStore (services/downloader/download_history.py),
        # von RichMenuHandler injiziert - siehe set_download_history().
        self.download_history = None
        # "🔁 Erneut versuchen": RichMenuSystem kann selbst keinen
        # DownloadHandler bauen (das kann nur RichMenuHandler, siehe dessen
        # _create_download_handler()/_process_url()) - dieser Callback wird
        # von RichMenuHandler.initialize() injiziert (set_url_retry_callback())
        # und ruft dort _process_url(update, context, url) auf, exakt derselbe
        # Pfad wie ein normaler Text-Download.
        self._retry_url_callback: Optional[Callable] = None
        # Wartungsmodus ("🛠️ Ein-/Ausschalten"): geteilte, prozessweite
        # MaintenanceModeStore-Instanz (services/bot_maintenance.py), von
        # RichMenuHandler injiziert - siehe set_maintenance_store().
        self.maintenance_store = None
        # Metadata-Reprocessing ("🔧 Reprocessing"): von RichMenuHandler
        # injiziert - siehe set_reprocessing_handler().
        self.reprocessing_handler = None
        # MusicBot Doctor ("🩺 Doctor", Phase 3 P1.3): von RichMenuHandler
        # injiziert - siehe set_doctor_handler().
        self.doctor_handler = None
        # Library Health Review ("🔎 Library Health Review"): von
        # RichMenuHandler injiziert - siehe set_review_handler().
        self.review_handler = None
        # Repair MusicBot ("🛠️ Repair MusicBot"): von RichMenuHandler
        # injiziert - siehe set_repair_handler().
        self.repair_handler = None

        # Konfiguration / Session-Verwaltung (ARCH-021/P-4: ausgelagert nach
        # handlers/menu/session.py::SessionManager)
        self.session_manager = SessionManager(
            session_timeout=getattr(config, "SESSION_TIMEOUT", 300),
            max_sessions=getattr(config, "MAX_CONCURRENT_SESSIONS", 100),
            logger=self.logger,
        )

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

    def set_family_stats_handler(self, handler) -> None:
        """Setzt den Familien-Statistik-Handler (Phase F2, Family Hub)"""
        self.family_stats_handler = handler
        self.logger.info("✅ Family-Stats-Handler verknüpft")

    def set_family_chat_handler(self, handler) -> None:
        """Setzt den Familien-Chat-Handler (Phase F3, Family Hub)"""
        self.family_chat_handler = handler
        self.logger.info("✅ Family-Chat-Handler verknüpft")

    def set_family_challenge_handler(self, handler) -> None:
        """Setzt den Familien-Challenge-Handler (Phase F4, Family Hub)"""
        self.family_challenge_handler = handler
        self.logger.info("✅ Family-Challenge-Handler verknüpft")

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

    def set_active_downloads(self, registry) -> None:
        """Setzt die geteilte ActiveDownloadRegistry (Download-Control-Center)."""
        self.active_downloads = registry
        self.logger.info("✅ ActiveDownloadRegistry verknüpft")

    def set_download_history(self, store) -> None:
        """Setzt den geteilten DownloadHistoryStore (Download-Verlauf-Feature)."""
        self.download_history = store
        self.logger.info("✅ DownloadHistoryStore verknüpft")

    def set_url_retry_callback(self, callback: Callable) -> None:
        """Setzt den Callback für "🔁 Erneut versuchen" (siehe __init__)."""
        self._retry_url_callback = callback
        self.logger.info("✅ URL-Retry-Callback verknüpft")

    def set_maintenance_store(self, store) -> None:
        """Setzt den geteilten MaintenanceModeStore (Wartungsmodus-Feature)."""
        self.maintenance_store = store
        self.logger.info("✅ MaintenanceModeStore verknüpft")

    def set_reprocessing_handler(self, handler) -> None:
        """Setzt den ReprocessingMenuHandler (Metadata-Reprocessing-Feature)."""
        self.reprocessing_handler = handler
        self.logger.info("✅ Reprocessing-Handler verknüpft")

    def set_doctor_handler(self, handler) -> None:
        """Setzt den LibraryDoctorHandler (MusicBot-Doctor-Feature, Phase 3 P1.3)."""
        self.doctor_handler = handler
        self.logger.info("✅ Doctor-Handler verknüpft")

    def set_review_handler(self, handler) -> None:
        """Setzt den LibraryHealthReviewHandler ("Library Health Review")."""
        self.review_handler = handler
        self.logger.info("✅ Review-Handler verknüpft")

    def set_repair_handler(self, handler) -> None:
        """Setzt den RepairMusicBotHandler ("Repair MusicBot")."""
        self.repair_handler = handler
        self.logger.info("✅ Repair-Handler verknüpft")

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
        # Download-Control-Center 2026-09-02 (Nutzer-Vorgabe): handler=
        # macht "download" zu einem eigenen Aktions-Menüpunkt statt der
        # generischen render_menu()-Darstellung seiner Kinder (analog zu
        # dup:/status_/backup_/restart: - siehe _handle_download_menu()
        # weiter unten). Die beiden statischen Kinder darunter bleiben in
        # der Registry bestehen (harmlos, ungenutzt) - _handle_download_menu()
        # baut die Tastatur komplett selbst.
        download_menu = MenuItem(
            id="download",
            title="Downloads",
            emoji="📥",
            description="Musik herunterladen",
            handler=self._handle_download_menu,
            is_action=True,
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
        stats_menu.add_child(
            MenuItem(
                id="stats_timeline",
                title="Music Timeline",
                emoji="📅",
                handler=self._handle_stats_timeline,
                is_action=True,
            )
        )
        stats_menu.add_child(
            MenuItem(
                id="stats_library_overview",
                title="Library Übersicht",
                emoji="📚",
                handler=self._handle_stats_library_overview,
                is_action=True,
            )
        )

        # Familien-Statistik (Phase F2, Family Hub) - neuer Zweig NEBEN den
        # bestehenden persönlichen Statistik-Punkten (stats_monthly/...),
        # die unverändert bleiben (Master-Prompt: "Bestehende Callback-Namen
        # und Navigation nicht unnötig brechen"). Zugriff wird serverseitig
        # in FamilyStatsHandler geprüft (Family-Membership), nicht hier.
        family_stats_menu = MenuItem(
            id="family_stats",
            title="Familien-Statistik",
            emoji="👨‍👩‍👧‍👦",
            description="Statistiken für alle Familienmitglieder",
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_top_songs",
                title="Top Songs Familie",
                emoji="🎵",
                handler=self._handle_family_stats_top_songs,
                is_action=True,
            )
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_top_artists",
                title="Top Künstler Familie",
                emoji="🎤",
                handler=self._handle_family_stats_top_artists,
                is_action=True,
            )
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_member",
                title="Statistik pro Person",
                emoji="👥",
                handler=self._handle_family_stats_member,
                is_action=True,
            )
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_champion",
                title="Musik-Champion",
                emoji="🏆",
                handler=self._handle_family_stats_champion,
                is_action=True,
            )
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_listening_times",
                title="Hörzeiten",
                emoji="⏰",
                handler=self._handle_family_stats_listening_times,
                is_action=True,
            )
        )
        family_stats_menu.add_child(
            MenuItem(
                id="family_stats_monthly_trend",
                title="Monatsentwicklung",
                emoji="📈",
                handler=self._handle_family_stats_monthly_trend,
                is_action=True,
            )
        )
        stats_menu.add_child(family_stats_menu)

        # Familien-Chat (Phase F3, Family Hub) - eigenes Top-Level-Menü
        # (Geschwister von "stats", nicht darunter verschachtelt), analog
        # zur Master-Prompt-Zielstruktur. Zugriff wird serverseitig in
        # FamilyChatHandler geprüft (Family-Membership), nicht hier.
        family_chat_menu = MenuItem(
            id="family_chat",
            title="Familien-Chat",
            emoji="💬",
            description="Privater Chat für Familienmitglieder",
        )
        family_chat_menu.add_child(
            MenuItem(
                id="family_chat_send",
                title="Nachricht senden",
                emoji="📝",
                handler=self._handle_family_chat_send,
                is_action=True,
            )
        )
        family_chat_menu.add_child(
            MenuItem(
                id="family_chat_recent",
                title="Letzte Nachrichten",
                emoji="📋",
                handler=self._handle_family_chat_recent,
                is_action=True,
            )
        )
        family_chat_menu.add_child(
            MenuItem(
                id="family_chat_notifications",
                title="Benachrichtigungen",
                emoji="🔔",
                handler=self._handle_family_chat_notifications,
                is_action=True,
            )
        )

        # Familien-Challenge (Phase F4, Family Hub) - eigenes Top-Level-
        # Menü, analog zu family_chat. Zugriff wird serverseitig in
        # FamilyChallengeHandler geprüft (Family-Membership), nicht hier.
        family_challenge_menu = MenuItem(
            id="family_challenge",
            title="Familien-Challenge",
            emoji="🎯",
            description="Tägliche Musik-Challenge für die Familie",
        )
        family_challenge_menu.add_child(
            MenuItem(
                id="family_challenge_today",
                title="Heutige Challenge",
                emoji="❓",
                handler=self._handle_family_challenge_today,
                is_action=True,
            )
        )
        family_challenge_menu.add_child(
            MenuItem(
                id="family_challenge_answer",
                title="Antworten",
                emoji="✅",
                handler=self._handle_family_challenge_answer,
                is_action=True,
            )
        )
        family_challenge_menu.add_child(
            MenuItem(
                id="family_challenge_leaderboard",
                title="Punktestand",
                emoji="🏆",
                handler=self._handle_family_challenge_leaderboard,
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

        # Admin-Menü-Reorg (UX/Navigation, siehe Analyse-Bericht): drei
        # thematische Gruppen-Container - reine Navigationsknoten (kein
        # handler=, kein eigenes callback_data noetig, automatisch
        # "menu:<id>", bereits durch das generische "^menu:"-Pattern in
        # RichMenuHandler.get_telegram_handlers() abgedeckt, siehe
        # docs/MusicBot_TELEGRAM_MENU_SYSTEM.md Abschnitt 6 - kein neuer
        # CallbackQueryHandler noetig). Duplikat-Verwaltung und
        # Benutzerverwaltung bleiben bewusst direkte Administration-Kinder
        # (CLAUDE.md Abschnitt 5/15: Duplicate Detection ist eine eigene
        # P0-Domaene, nicht Teil von "Bibliothek").
        admin_group_library = MenuItem(
            id="admin_group_library",
            title="Bibliothek & Navidrome",
            emoji="🎵",
            access_level=AccessLevel.ADMIN,
            description="Library-Diagnose, Reprocessing und Navidrome-Scan",
        )
        admin_group_operations = MenuItem(
            id="admin_group_operations",
            title="Bot & Betrieb",
            emoji="🤖",
            access_level=AccessLevel.ADMIN,
            description="Bot-Neustart, Wartungsmodus und Backups",
        )
        admin_group_diagnostics = MenuItem(
            id="admin_group_diagnostics",
            title="Diagnose & Monitoring",
            emoji="🩺",
            access_level=AccessLevel.ADMIN,
            description="System-Status, Logs, Fehler und Logger-Steuerung",
        )

        # System-Status
        admin_group_diagnostics.add_child(
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
        admin_users_item = MenuItem(
            id="admin_users",
            title="Benutzerverwaltung",
            emoji="👥",
            access_level=AccessLevel.ADMIN,
            is_action=True,
        )

        # System-Logs
        admin_group_diagnostics.add_child(
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
        admin_group_diagnostics.add_child(error_menu)

        # Logger-Management
        logger_menu = MenuItem(
            id="logger",
            title="Logger-Verwaltung",
            emoji="📈",
            access_level=AccessLevel.ADMIN,
            description="Erweiterte Logger-Steuerung und -Überwachung",
        )
        # TGPERM-001-Fix (siehe docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_
        # 2026-09-12.md): callback_data wird hier bewusst explizit auf die
        # ID gesetzt statt der automatischen "menu:<id>"-Generierung
        # (MenuItem.__post_init__) zu ueberlassen. Ohne dieses Override
        # dispatchte handle_callback() diese ADMIN-Items ueber den
        # generischen "menu:"-Fallback (Ende von handle_callback(), ruft
        # menu_item.handler() OHNE jede Berechtigungspruefung auf) statt
        # ueber den bereits vorhandenen, in _ADMIN_ONLY_PREFIXES gegateten
        # "logger_"-Praefixpfad (_handle_logger_callback()'s routing_map,
        # die exakt dieselben IDs bereits kennt). Die vormaligen
        # `handler=self._handle_logger_*`-Wrapper sind dadurch obsolet und
        # wurden entfernt (siehe frueher "LOGGER-HANDLER WRAPPER").
        logger_menu.add_child(
            MenuItem(
                id="logger_main_menu",
                title="Logger-Übersicht",
                emoji="🏠",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_main_menu",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_modules_list",
                title="Module verwalten",
                emoji="📦",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_modules_list",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_global_level",
                title="Globales Level",
                emoji="🌍",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_global_level",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_files_list",
                title="Log-Dateien",
                emoji="📁",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_files_list",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_global_stats",
                title="Statistiken",
                emoji="📈",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_global_stats",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_handlers_list",
                title="Handler-Verwaltung",
                emoji="⚡",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_handlers_list",
                is_action=True,
            )
        )
        logger_menu.add_child(
            MenuItem(
                id="logger_cleanup_menu",
                title="Bereinigung",
                emoji="🧹",
                access_level=AccessLevel.ADMIN,
                callback_data="logger_cleanup_menu",
                is_action=True,
            )
        )
        admin_group_diagnostics.add_child(logger_menu)

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
        admin_group_operations.add_child(backup_menu)

        # ====== NEU: BOT-NEUSTART ======
        admin_group_operations.add_child(
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

        # ====== NEU: WARTUNGSMODUS ======
        admin_group_operations.add_child(
            MenuItem(
                id="admin_maintenance",
                title="Wartungsmodus",
                emoji="🛠️",
                access_level=AccessLevel.ADMIN,
                callback_data="maint:show",
                handler=self._handle_maintenance_show,
                is_action=True,
                description="Bot für alle außer Admins pausieren/fortsetzen",
            )
        )
        # ====== ENDE WARTUNGSMODUS ======

        # ====== NEU: METADATA-REPROCESSING ======
        # Nutzer-Entscheidung: nur Owner (nicht Admin) - greift auf
        # Metadata-/Auto-Learn-Dateien zu, siehe docs/FINDINGS_INDEX.md.
        admin_group_library.add_child(
            MenuItem(
                id="admin_reprocessing",
                title="Reprocessing",
                emoji="🔧",
                access_level=AccessLevel.OWNER,
                callback_data="reprocess:show",
                handler=self._handle_reprocessing_show,
                is_action=True,
                description="Metadata eines Test-Artists erneut verarbeiten",
            )
        )
        # ====== ENDE METADATA-REPROCESSING ======

        # ====== NEU: MUSICBOT DOCTOR (Phase 3, P1.3) ======
        admin_group_library.add_child(
            MenuItem(
                id="admin_library_doctor",
                title="MusicBot Doctor",
                emoji="🩺",
                access_level=AccessLevel.ADMIN,
                callback_data="doctor:scan",
                handler=self._handle_doctor_scan,
                is_action=True,
                description="Library Health-Scan + sichere Tag-/Namens-Reparaturen",
            )
        )
        # ====== ENDE MUSICBOT DOCTOR ======

        # ====== NEU: LIBRARY HEALTH REVIEW ======
        admin_group_library.add_child(
            MenuItem(
                id="admin_library_health_review",
                title="Library Health Review",
                emoji="🔎",
                access_level=AccessLevel.ADMIN,
                callback_data="review:start",
                handler=self._handle_review_start,
                is_action=True,
                description="Offene Health-Findings nach Kategorie prüfen "
                            "(Resolve/False Positive)",
            )
        )
        # ====== ENDE LIBRARY HEALTH REVIEW ======

        # ====== NEU: REPAIR MUSICBOT ======
        admin_group_library.add_child(
            MenuItem(
                id="admin_repair_musicbot",
                title="Repair MusicBot",
                emoji="🛠️",
                access_level=AccessLevel.ADMIN,
                callback_data="repair:start",
                handler=self._handle_repair_start,
                is_action=True,
                description="Reparaturplan/-vorschläge, SAFE_AUTOMATIC-Ausführung, "
                            "Historie & Statistik",
            )
        )
        # ====== ENDE REPAIR MUSICBOT ======

        # Admin-Menü-Reorg: Gruppen-Container an Administration haengen -
        # Reihenfolge hier = Anzeige-Reihenfolge im Menü (siehe
        # Analyse-Bericht, Abschnitt F/H).
        admin_menu.add_child(admin_group_library)
        admin_menu.add_child(admin_group_operations)
        admin_menu.add_child(admin_group_diagnostics)
        admin_menu.add_child(duplicate_menu)
        admin_menu.add_child(admin_users_item)

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
        self.root_menu.add_child(family_chat_menu)
        self.root_menu.add_child(family_challenge_menu)
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

    # Die vormaligen LOGGER-HANDLER WRAPPER (_handle_logger_main_menu,
    # _handle_logger_modules, _handle_logger_global_level,
    # _handle_logger_files, _handle_logger_stats, _handle_logger_handlers,
    # _handle_logger_cleanup) wurden im Rahmen des TGPERM-001-Fixes entfernt
    # (siehe docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md):
    # die zugehoerigen MenuItems routen jetzt ueber explizites
    # callback_data direkt in den bereits gegateten "logger_"-Praefixpfad
    # (_handle_logger_callback()'s routing_map), diese Wrapper wurden dadurch
    # unerreichbar.

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

    # ====== NEU: WARTUNGSMODUS ======
    #
    # Anders als der Bot-Neustart bewusst OHNE eigene Handler-Klasse: die
    # Logik beschraenkt sich auf Lesen/Schreiben des einen booleschen
    # Zustands im geteilten MaintenanceModeStore (services/bot_maintenance.py)
    # - kein Bestaetigungsdialog (anders als beim Neustart), da instant
    # reversibel und ohne Datenverlust/Verbindungsabbruch.

    async def _handle_maintenance_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Einstiegspunkt aus dem Menü-System - zeigt den aktuellen
        Wartungsmodus-Status mit Toggle-Button.
        """
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin_check(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if not self.maintenance_store:
            await query.edit_message_text("⚠️ Wartungsmodus-Speicher nicht verfügbar")
            return

        active = self.maintenance_store.is_active()
        status_text = "🔴 AKTIV" if active else "🟢 Inaktiv"
        toggle_label = (
            "🟢 Wartungsmodus beenden" if active else "🔴 Wartungsmodus aktivieren"
        )

        text = (
            "🛠️ <b>Wartungsmodus</b>\n\n"
            f"Status: {status_text}\n\n"
            "Im aktiven Wartungsmodus können nur Admins/Owner den Bot "
            "normal nutzen - alle anderen Nutzer erhalten an jedem "
            "Einstiegspunkt eine Wartungsmeldung statt der eigentlichen "
            "Funktion."
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(toggle_label, callback_data="maint:toggle")],
                [
                    InlineKeyboardButton(
                        "◀️ Zurück", callback_data="menu:admin_group_operations"
                    )
                ],
            ]
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def _handle_maintenance_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle maint:* Callbacks.

        Routing:
          maint:show   → Status anzeigen
          maint:toggle → Zustand umschalten, danach Status erneut anzeigen
        """
        query = update.callback_query
        user_id = update.effective_user.id

        # Admin-Check (Defense-in-Depth, analog zu restart:/erradmin: -
        # maint: ist bewusst NICHT in _ADMIN_ONLY_PREFIXES aufgenommen,
        # da dieser Dispatcher seinen eigenen Check macht).
        if not self._is_admin_check(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        if not self.maintenance_store:
            await query.answer(
                "⚠️ Wartungsmodus-Speicher nicht verfügbar", show_alert=True
            )
            return

        if callback_data == "maint:show":
            await self._handle_maintenance_show(update, context)
            return

        if callback_data == "maint:toggle":
            new_state = not self.maintenance_store.is_active()
            self.maintenance_store.set_active(new_state, changed_by_user_id=user_id)
            self.logger.warning(
                f"🛠️ Wartungsmodus {'aktiviert' if new_state else 'deaktiviert'} "
                f"von Admin {user_id}"
            )
            await self._handle_maintenance_show(update, context)
            return

        await query.answer("⚠️ Unbekannter Wartungsmodus-Callback")

    # ====== ENDE WARTUNGSMODUS ======

    # ====== METADATA-REPROCESSING ======

    async def _handle_reprocessing_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu den
        _handle_navidrome_*-Methoden."""
        if self.reprocessing_handler:
            await self.reprocessing_handler.show_artist_list(update, context)
        else:
            await self._show_handler_not_available(update, "Reprocessing-Handler")

    async def _handle_reprocessing_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle reprocess:* Callbacks.

        Routing:
          reprocess:show        → Artist-Liste anzeigen
          reprocess:pick:<idx>  → Dry-Run für Artist <idx> starten
          reprocess:live:<idx>  → LIVE-Lauf für Artist <idx> starten

        Eigener Owner-Check hier (Defense-in-Depth, analog zu maint: -
        bewusst NICHT in _ADMIN_ONLY_PREFIXES aufgenommen, da OWNER
        strenger als ADMIN ist und dieser Dispatcher seinen eigenen,
        passenden Check macht statt sich auf den ADMIN-Check zu verlassen).
        """
        query = update.callback_query
        user_id = update.effective_user.id

        if user_id != getattr(self.config, "OWNER_USER_ID", None):
            self.logger.warning(
                f"🚨 [SECURITY] Nicht-Owner {user_id} versuchte "
                f"Reprocessing-Callback: {callback_data}"
            )
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        if not self.reprocessing_handler:
            await query.answer(
                "⚠️ Reprocessing-Handler nicht verfügbar", show_alert=True
            )
            return

        if callback_data == "reprocess:show":
            await self.reprocessing_handler.show_artist_list(update, context)
            return

        if callback_data.startswith("reprocess:pick:"):
            idx_str = callback_data[len("reprocess:pick:") :]
            try:
                idx = int(idx_str)
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await self.reprocessing_handler.handle_pick(update, context, idx)
            return

        if callback_data.startswith("reprocess:live:"):
            idx_str = callback_data[len("reprocess:live:") :]
            try:
                idx = int(idx_str)
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await self.reprocessing_handler.handle_live(update, context, idx)
            return

        await query.answer("⚠️ Unbekannter Reprocessing-Callback")

    # ====== ENDE METADATA-REPROCESSING ======

    # ====== MUSICBOT DOCTOR (Phase 3, P1.3) ======

    async def _handle_doctor_scan(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_reprocessing_show()."""
        if self.doctor_handler:
            await self.doctor_handler.handle_scan(update, context)
        else:
            await self._show_handler_not_available(update, "Doctor-Handler")

    async def _handle_doctor_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle doctor:* Callbacks.

        Routing:
          doctor:scan                 → Health-Scan starten (auch über
                                         den Menüpunkt direkt erreichbar)
          doctor:apply_safe           → Bestätigung vor SAFE_AUTOMATIC-Apply
          doctor:apply_safe_confirm   → SAFE_AUTOMATIC-Apply tatsächlich starten

        Eigener Admin-Check hier (Defense-in-Depth, analog zu maint:/
        reprocess: - callback_data ist frei sendbar, siehe SEC-003).
        """
        query = update.callback_query
        user_id = update.effective_user.id

        is_admin = user_id == getattr(self.config, "OWNER_USER_ID", None) or \
            user_id in getattr(self.config, "ADMIN_USER_IDS", [])
        if not is_admin:
            self.logger.warning(
                f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
                f"Doctor-Callback: {callback_data}"
            )
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        if not self.doctor_handler:
            await query.answer("⚠️ Doctor-Handler nicht verfügbar", show_alert=True)
            return

        if callback_data == "doctor:scan":
            await self.doctor_handler.handle_scan(update, context)
            return

        if callback_data == "doctor:apply_safe":
            await self.doctor_handler.handle_apply_safe_confirm_prompt(update, context)
            return

        if callback_data == "doctor:apply_safe_confirm":
            await self.doctor_handler.handle_apply_safe_confirmed(update, context)
            return

        await query.answer("⚠️ Unbekannter Doctor-Callback")

    # ====== ENDE MUSICBOT DOCTOR ======

    # ====== LIBRARY HEALTH REVIEW ======

    async def _handle_review_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_doctor_scan()."""
        if self.review_handler:
            await self.review_handler.handle_start(update, context)
        else:
            await self._show_handler_not_available(update, "Review-Handler")

    async def _handle_review_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle review:* Callbacks.

        Routing (siehe handlers/library_health_review_handler.py):
          review:start                    → Übersicht (Severity-Verteilung)
          review:severity:<TIER>          → Kategorien dieser Severity-Stufe
          review:category:<CODE>          → Kategorie-Aktionen
          review:edit:<CODE>              → Einzelreview starten
          review:resolve:<finding_id>     → Resolve im Einzelreview
          review:fp:<finding_id>          → False Positive im Einzelreview
          review:skip:<finding_id>        → Skip im Einzelreview
          review:quit:<finding_id>        → Review beenden
          review:batchconfirm:<CODE>      → Bestätigung vor Batch-False-Positive
          review:batchyes:<CODE>          → Batch-False-Positive ausführen
          review:accepted                 → Liste der akzeptierten Findings (nach Code)
          review:acccode:<CODE>           → akzeptierte Findings dieser Kategorie
          review:accshow:<finding_id>     → ein akzeptiertes Finding (Detail)
          review:unaccept:<finding_id>    → Acceptance zurücknehmen (→ OPEN)

        Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
        maint:/reprocess: - callback_data ist frei sendbar, siehe SEC-003).
        """
        query = update.callback_query
        user_id = update.effective_user.id

        is_admin = user_id == getattr(self.config, "OWNER_USER_ID", None) or \
            user_id in getattr(self.config, "ADMIN_USER_IDS", [])
        if not is_admin:
            self.logger.warning(
                f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
                f"Review-Callback: {callback_data}"
            )
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        if not self.review_handler:
            await query.answer("⚠️ Review-Handler nicht verfügbar", show_alert=True)
            return

        if callback_data == "review:start":
            await self.review_handler.handle_start(update, context)
            return
        if callback_data == "review:accepted":
            await self.review_handler.handle_accepted_list(update, context)
            return

        parts = callback_data.split(":", 2)
        if len(parts) < 3:
            await query.answer("⚠️ Unbekannter Review-Callback")
            return
        action, payload = parts[1], parts[2]

        if action == "severity":
            await self.review_handler.handle_severity(update, context, payload)
        elif action == "category":
            await self.review_handler.handle_category(update, context, payload)
        elif action == "edit":
            await self.review_handler.handle_edit_start(update, context, payload)
        elif action == "batchconfirm":
            await self.review_handler.handle_batch_confirm_prompt(update, context, payload)
        elif action == "batchyes":
            await self.review_handler.handle_batch_confirmed(update, context, payload)
        elif action in ("resolve", "fp", "skip", "quit"):
            await self.review_handler.handle_single_action(update, context, action, payload)
        elif action == "acccode":
            await self.review_handler.handle_accepted_category(update, context, payload)
        elif action == "accshow":
            await self.review_handler.handle_accepted_show(update, context, payload)
        elif action == "unaccept":
            await self.review_handler.handle_unaccept(update, context, payload)
        else:
            await query.answer("⚠️ Unbekannter Review-Callback")

    # ====== ENDE LIBRARY HEALTH REVIEW ======

    # ====== REPAIR MUSICBOT ======

    async def _handle_repair_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_doctor_scan()/_handle_review_start()."""
        if self.repair_handler:
            await self.repair_handler.handle_start(update, context)
        else:
            await self._show_handler_not_available(update, "Repair-Handler")

    async def _handle_repair_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle repair:* Callbacks.

        Routing (siehe handlers/repair_musicbot_handler.py):
          repair:start      → Startseite
          repair:analyze    → Reparaturen analysieren / Offene Reparaturen
          repair:proposals  → Reparaturvorschläge (SAFE_AUTOMATIC)
          repair:preview    → Read-only Vorschau
          repair:confirm    → explizite Bestätigung vor Ausführung
          repair:execute    → tatsächliche Ausführung (Berechtigung erneut geprüft)
          repair:history    → Reparaturhistorie
          repair:stats      → Repair-Statistik

        Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
        review:/maint:/reprocess: - callback_data ist frei sendbar, siehe
        SEC-003).
        """
        query = update.callback_query
        user_id = update.effective_user.id

        is_admin = user_id == getattr(self.config, "OWNER_USER_ID", None) or \
            user_id in getattr(self.config, "ADMIN_USER_IDS", [])
        if not is_admin:
            self.logger.warning(
                f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
                f"Repair-Callback: {callback_data}"
            )
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        if not self.repair_handler:
            await query.answer("⚠️ Repair-Handler nicht verfügbar", show_alert=True)
            return

        routing = {
            "repair:start": self.repair_handler.handle_start,
            "repair:analyze": self.repair_handler.handle_analyze,
            "repair:proposals": self.repair_handler.handle_proposals,
            "repair:preview": self.repair_handler.handle_preview,
            "repair:confirm": self.repair_handler.handle_confirm_prompt,
            "repair:execute": self.repair_handler.handle_execute,
            "repair:history": self.repair_handler.handle_history,
            "repair:stats": self.repair_handler.handle_statistics,
        }
        handler_fn = routing.get(callback_data)
        if handler_fn is None:
            await query.answer("⚠️ Unbekannter Repair-Callback")
            return
        await handler_fn(update, context)

    # ====== ENDE REPAIR MUSICBOT ======

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

    @property
    def sessions(self) -> Dict[int, MenuSession]:
        """Kompatibilitäts-Property (ARCH-021/P-4): gibt das Live-Dict des
        SessionManager zurück (keine Kopie) - bestehende direkte Zugriffe
        wie menu_system.sessions[user_id]/user_id in menu_system.sessions/
        del self.sessions[user_id] funktionieren dadurch unverändert."""
        return self.session_manager.sessions

    def get_session(self, user_id: int) -> MenuSession:
        """Holt oder erstellt User-Session (ARCH-021/P-4: delegiert an
        session.SessionManager.get_session())."""
        return self.session_manager.get_session(user_id)

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

        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return

        record_activity(update, getattr(self, "status_handler", None), f"callback:{callback_data}")

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
            # status_ wurde nachtraeglich ergaenzt (Folgeaspekt aus dem
            # urspruenglichen SEC-003-Fund): show_storage_status() etc.
            # geben echte Server-Dateisystempfade preis (LIBRARY_DIR,
            # DOWNLOAD_DIR, ...) und bieten eine destruktive
            # "status_storage_cleanup"-Aktion an. nav_ bleibt bewusst
            # ungegated - reines Bibliotheks-Browsing/Suche ohne
            # destruktive Aktionen oder Pfad-Offenlegung.
            _ADMIN_ONLY_PREFIXES = ("logger_", "usermgmt_", "dup:", "backup_", "status_")
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

            if callback_data.startswith("dl:"):
                await self._handle_download_control_callback(update, context, callback_data)
                return

            # ── NEU: Bot-Neustart ─────────────────────────────────────
            if callback_data.startswith("restart:"):
                await self._handle_restart_callback(update, context, callback_data)
                return

            # ── NEU: Wartungsmodus ────────────────────────────────────
            if callback_data.startswith("maint:"):
                await self._handle_maintenance_callback(update, context, callback_data)
                return

            # ── NEU: Metadata-Reprocessing ────────────────────────────
            if callback_data.startswith("reprocess:"):
                await self._handle_reprocessing_callback(update, context, callback_data)
                return

            # ── NEU: MusicBot Doctor (Phase 3, P1.3) ──────────────────
            if callback_data.startswith("doctor:"):
                await self._handle_doctor_callback(update, context, callback_data)
                return

            # ── NEU: Library Health Review ────────────────────────────
            if callback_data.startswith("review:"):
                await self._handle_review_callback(update, context, callback_data)
                return

            # ── NEU: Repair MusicBot ───────────────────────────────────
            if callback_data.startswith("repair:"):
                await self._handle_repair_callback(update, context, callback_data)
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

    def _get_user_access_level(self, user_id: int) -> AccessLevel:
        """Ermittelt Zugriffsebene des Users (ARCH-021/P-3: delegiert an
        permissions.get_user_access_level())."""
        return get_user_access_level(user_id, self.config, self.user_mgmt_handler)

    def _is_admin_check(self, user_id: int) -> bool:
        """
        Interne Admin-Prüfung (wiederverwendbar). Gibt True zurück für
        Owner und alle konfigurierten Admins.
        ARCH-021/P-3: delegiert an permissions.is_admin_or_owner(),
        gemeinsam mit RichMenuHandler._is_admin()).
        """
        return is_admin_or_owner(user_id, self.config)

    def register_handler(self, menu_id: str, handler: Callable) -> None:
        """Registriert Handler für Menüpunkt"""
        if menu_id in self.menu_registry:
            self.menu_registry[menu_id].handler = handler
            self.logger.info(f"✅ Handler registriert für '{menu_id}'")
        else:
            self.logger.warning(f"⚠️ Menü-ID '{menu_id}' nicht gefunden")

    def add_child_menu_item(self, parent_id: str, item: "MenuItem") -> bool:
        """
        Fügt ein MenuItem nachträglich als Kind eines bestehenden Menüs hinzu
        und trägt es zusätzlich in die Registry ein (z.B. für Menüpunkte, die
        erst nach initialize_menu_structure() dynamisch entstehen). Gibt
        False zurück und tut nichts, wenn parent_id nicht existiert.
        """
        parent = self.menu_registry.get(parent_id)
        if not parent:
            self.logger.warning(f"⚠️ Eltern-Menü-ID '{parent_id}' nicht gefunden")
            return False
        parent.add_child(item)
        self.menu_registry[item.id] = item
        return True

    def cleanup_expired_sessions(self) -> int:
        """Entfernt abgelaufene Sessions (ARCH-021/P-4: delegiert an
        session.SessionManager.cleanup_expired_sessions())."""
        return self.session_manager.cleanup_expired_sessions()

    # ====== DOWNLOAD-CONTROL-CENTER (2026-09-02, Nutzer-Vorgabe) ======
    #
    # "📥 Downloads" wird zu einem echten Steuerzentrum statt der
    # bisherigen statischen 2-Optionen-Liste (Einzelner Track/Playlist -
    # ohnehin redundant, da download_utils.py Single/Playlist automatisch
    # anhand der URL erkennt, siehe _handle_download_new()). "❌
    # Abbrechen" erscheint NUR, wenn tatsächlich ein Download für diesen
    # Chat aktiv ist (self.active_downloads, siehe
    # services/downloader/active_downloads.py) - "keine toten Buttons".
    #
    # 📋 Download-Verlauf / 🔁 Erneut versuchen (Nutzer-Prioritäten 3/4)
    # sind bewusst NOCH NICHT Teil dieser ersten Ausbaustufe - sie
    # brauchen einen persistenten Verlaufsspeicher, der als eigener
    # Folgeschritt kommt (siehe _handle_download_history()-Platzhalter).
    # 🔄 Reprocessing (Priorität 5) ist laut Nutzer-Entscheidung ein
    # eigener Bereich, absichtlich NICHT Teil dieses Menüs.

    async def _handle_download_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Wird über den regulären menu:download-Callback aufgerufen
        (query.answer() bereits vom generischen Dispatcher erledigt, siehe
        handle_callback())."""
        query = update.callback_query
        chat_id = update.effective_chat.id
        active = self.active_downloads.get(chat_id) if self.active_downloads else None
        await self._render_download_menu(query, active)

    async def _render_download_menu(self, query, active) -> None:
        # Live-Fund 2026-09-02: active.title/tracker-Inhalte stammen aus
        # echten YouTube-Titeln/Artist-/Albumnamen - koennen "_"/"*"
        # enthalten, die Telegrams (Legacy-)Markdown-Parser als
        # unvollstaendige Formatierung interpretiert
        # ("Can't parse entities: can't find end of the entity", live
        # reproduziert für eine URL mit "_"). Bewusst KEIN parse_mode in
        # dieser gesamten dl:-Sektion, sobald dynamische/externe Inhalte
        # vorkommen koennen - robuster als selektives Escapen einzelner
        # Felder (das genau diesen Fund erst verursacht hat).
        lines = ["📥 Downloads", ""]
        if active is not None:
            lines.append(f"🔄 Läuft gerade: {active.title or 'wird vorbereitet …'}")
        else:
            lines.append("Lade Musik von YouTube herunter oder verwalte Downloads.")

        keyboard = [
            [InlineKeyboardButton("➕ Neuer Download", callback_data="dl:new")],
            [InlineKeyboardButton("🔄 Aktive Downloads", callback_data="dl:active")],
            [InlineKeyboardButton("📋 Download-Verlauf", callback_data="dl:history")],
        ]
        if active is not None:
            keyboard.append(
                [InlineKeyboardButton("❌ Abbrechen", callback_data="dl:cancel")]
            )
        keyboard.append(
            [InlineKeyboardButton("◀️ Hauptmenü", callback_data="menu:main")]
        )

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_download_control_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ) -> None:
        """Spezial-Handler für alle dl:*-Callbacks (Download-Control-Center),
        analog zu _handle_backup_callback() etc."""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if callback_data == "dl:new":
            await self._handle_download_new(query)
            return
        if callback_data == "dl:active":
            await self._handle_download_active(query, chat_id)
            return
        if callback_data == "dl:cancel":
            await self._handle_download_cancel_request(query, chat_id)
            return
        if callback_data == "dl:details":
            await self._handle_download_details(query, chat_id)
            return
        if callback_data == "dl:history":
            await self._handle_download_history(query, chat_id)
            return
        if callback_data.startswith("dl:retry:"):
            await self._handle_download_retry(update, context, query, chat_id, callback_data)
            return
        if callback_data == "dl:menu":
            active = (
                self.active_downloads.get(chat_id) if self.active_downloads else None
            )
            await self._render_download_menu(query, active)
            return

        self.logger.warning(f"⚠️ Unbekannter dl:-Callback: {callback_data}")
        await query.edit_message_text("⚠️ Unbekannte Aktion.")

    async def _handle_download_new(self, query) -> None:
        await query.edit_message_text(
            "🎵 Neuer Download\n\n"
            "Sende mir einfach einen YouTube-Link (Song oder Playlist) - "
            "ich erkenne automatisch, um welchen Typ es sich handelt."
        )

    async def _handle_download_active(self, query, chat_id: int) -> None:
        """
        "📥 Download läuft" (Nutzer-Vorgabe, P1): zeigt aktuellen Track,
        bereits abgeschlossene Tracks und die verbleibende Anzahl anhand
        des GETEILTEN ProgressTrackers (ActiveDownload.tracker) - derselbe
        Zustand, den auch die automatischen Zwischen-Updates während des
        Downloads nutzen (klassen/download_handler.py::
        _on_playlist_progress()) - hier nur zusätzlich manuell abrufbar,
        statt nur passiv gepusht.
        """
        active = self.active_downloads.get(chat_id) if self.active_downloads else None
        if active is None:
            await query.edit_message_text(
                "🔄 Aktive Downloads\n\nAktuell läuft kein Download.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
                ),
            )
            return

        tracker = active.tracker
        bar = _dl_progress_bar(tracker.processed_items, tracker.total_items)
        remaining = max(tracker.total_items - tracker.processed_items, 0)

        # Live-Fund 2026-09-02: siehe _render_download_menu() - kein
        # parse_mode, tracker.current_item/completed_items sind echte
        # YouTube-Tracktitel (koennen "_"/"*" enthalten).
        lines = [
            "📥 Download läuft",
            "",
            f"🎵 {active.title or 'wird vorbereitet …'}",
            "",
            bar,
        ]
        if tracker.current_item:
            lines += ["", "⬇️ Aktuell", tracker.current_item]
        if tracker.completed_items:
            lines += ["", "✅ Abgeschlossen"] + tracker.completed_items[-5:]
        if remaining > 0:
            lines += ["", f"⏳ Noch {remaining} Tracks"]

        keyboard = [
            [InlineKeyboardButton("❌ Download abbrechen", callback_data="dl:cancel")],
            [InlineKeyboardButton("ℹ️ Details", callback_data="dl:details")],
            [InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")],
        ]

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_download_cancel_request(self, query, chat_id: int) -> None:
        active = self.active_downloads.get(chat_id) if self.active_downloads else None
        if active is None:
            await query.edit_message_text(
                "ℹ️ Kein aktiver Download zum Abbrechen.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
                ),
            )
            return

        active.request_cancel()
        self.logger.info(f"🛑 [DL-CONTROL] Abbruch angefordert für Chat {chat_id}")
        await query.edit_message_text(
            "🛑 Abbruch angefordert - der Download wird in Kürze gestoppt.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
            ),
        )

    async def _handle_download_details(self, query, chat_id: int) -> None:
        active = self.active_downloads.get(chat_id) if self.active_downloads else None
        if active is None:
            await query.edit_message_text(
                "ℹ️ Kein aktiver Download.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
                ),
            )
            return

        tracker = active.tracker
        elapsed = int(active.elapsed_seconds())
        minutes, seconds = divmod(elapsed, 60)

        # Live-Fund 2026-09-02: siehe _render_download_menu() - kein
        # parse_mode. Genau active.url hat den urspruenglichen Fehler
        # ausgeloest ("Can't parse entities", "_" in der YouTube-URL von
        # Telegrams Legacy-Markdown-Parser als unvollstaendige Kursiv-
        # Formatierung interpretiert).
        lines = [
            "ℹ️ Download-Details",
            "",
            f"🎵 Titel      : {active.title or '?'}",
            f"🔗 URL        : {active.url}",
            f"📦 Typ        : {active.download_type}",
            f"⏱️ Laufzeit   : {minutes}:{seconds:02d} min",
            f"📊 Fortschritt: {tracker.processed_items}/{tracker.total_items}",
        ]
        if tracker.current_item:
            lines.append(f"⬇️ Aktuell    : {tracker.current_item}")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:active")]]
            ),
        )

    _HISTORY_STATUS_ICONS = {"success": "✅", "failed": "❌", "cancelled": "🛑"}

    async def _handle_download_history(self, query, chat_id: int) -> None:
        """
        Download-Verlauf (Nutzer-Priorität 3) + "🔁 Erneut versuchen"
        (Priorität 4) - Folgeschritt des Download-Control-Centers, siehe
        docs/FINDINGS_INDEX.md ("Download-Verlauf/Erneut-versuchen").
        Zeigt die letzten Einträge des Chats aus dem geteilten
        DownloadHistoryStore (services/downloader/download_history.py),
        neueste zuerst - jeweils mit einem eigenen "🔁"-Button
        (callback_data=f"dl:retry:{position}", position bezieht sich auf
        DownloadHistoryStore.get_recent()/get_entry_by_position(), damit
        Index und Anzeige immer übereinstimmen).
        """
        entries = self.download_history.get_recent(chat_id) if self.download_history else []
        if not entries:
            await query.edit_message_text(
                "📋 Download-Verlauf\n\nNoch keine Downloads in dieser Chat-Historie.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
                ),
            )
            return

        lines = ["📋 Download-Verlauf", ""]
        keyboard = []
        for position, entry in enumerate(entries):
            icon = self._HISTORY_STATUS_ICONS.get(entry.status, "•")
            # Nur Datum/Uhrzeit, kein Sekunden-Praezisions-Rauschen - die
            # Reihenfolge (neueste zuerst) macht die genaue Sekunde ohnehin
            # nicht aussagekraeftig.
            try:
                when = datetime.fromisoformat(entry.timestamp).strftime("%d.%m. %H:%M")
            except ValueError:
                when = "?"
            lines.append(f"{icon} {entry.artist} - {entry.title}  ({when})")
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🔁 {entry.title[:40]}",
                        callback_data=f"dl:retry:{position}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_download_retry(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, chat_id: int, callback_data: str
    ) -> None:
        """Handler für "🔁 Erneut versuchen" (callback_data=f"dl:retry:{position}").

        RichMenuSystem kann selbst keinen DownloadHandler bauen (siehe
        __init__-Kommentar zu _retry_url_callback) - baut stattdessen ein
        minimales, schreibgeschütztes Duck-Typing-Objekt anstelle von
        update.message (PTB-Update-/Message-Objekte sind nach Auslieferung
        eingefroren, ein echtes Update darf nicht nachtraeglich mutiert
        werden) und reicht es an genau denselben, bereits produktiv
        genutzten Pfad weiter (_process_url() -> handler.handle_url() ->
        handle_youtube_links()) wie ein normaler Text-Download - keine
        Parallel-Implementierung der Download-Pipeline."""
        try:
            position = int(callback_data.split(":", 2)[2])
        except (IndexError, ValueError):
            await query.edit_message_text("⚠️ Ungültiger Verlaufseintrag.")
            return

        if not self.download_history:
            await query.edit_message_text("⚠️ Download-Verlauf nicht verfügbar.")
            return
        entry = self.download_history.get_entry_by_position(chat_id, position)
        if entry is None or not entry.url:
            await query.edit_message_text("⚠️ Dieser Eintrag ist nicht mehr verfügbar.")
            return
        if not self._retry_url_callback:
            await query.edit_message_text("⚠️ Erneuter Download aktuell nicht möglich.")
            return

        await query.edit_message_text(f"🔁 Starte erneuten Download:\n{entry.title}")
        retry_update = _RetryUpdateAdapter(update, entry.url)
        await self._retry_url_callback(retry_update, context, entry.url)

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

    async def _handle_stats_library_overview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Phase 3, P1.1 — Library-Zusammensetzung aus dem Health-Report,
        anders als die übrigen stats_*-Handler keine Play-History."""
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_library_overview(update, context)
        else:
            await query.edit_message_text("📚 Lade Library-Übersicht...")

    async def _handle_stats_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler:
            await self.stats_handler.handle_top_artists(update, context, period="month")
        else:
            await query.edit_message_text("🎤 Lade Top Künstler...")

    async def _handle_stats_timeline(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.stats_handler and hasattr(self.stats_handler, "handle_music_timeline"):
            await self.stats_handler.handle_music_timeline(update, context)
        else:
            await query.edit_message_text("📅 Lade Music Timeline...")

    # ====== FAMILIEN-STATISTIK (Phase F2, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyStatsHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei allen übrigen
    # _handle_stats_*-Methoden dieser Klasse (dünner Wrapper -> Handler).

    async def _handle_family_stats_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_top_songs(update, context)
        else:
            await query.edit_message_text("🎵 Lade Top Songs Familie...")

    async def _handle_family_stats_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_top_artists(update, context)
        else:
            await query.edit_message_text("🎤 Lade Top Künstler Familie...")

    async def _handle_family_stats_member(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_member_stats(update, context)
        else:
            await query.edit_message_text("👥 Lade Statistik pro Person...")

    async def _handle_family_stats_champion(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_champion(update, context)
        else:
            await query.edit_message_text("🏆 Ermittle Musik-Champion...")

    async def _handle_family_stats_listening_times(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_listening_times(
                update, context
            )
        else:
            await query.edit_message_text("⏰ Lade Hörzeiten...")

    async def _handle_family_stats_monthly_trend(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_stats_handler:
            await self.family_stats_handler.handle_family_monthly_trend(
                update, context
            )
        else:
            await query.edit_message_text("📈 Lade Monatsentwicklung...")

    # ====== FAMILIEN-CHAT (Phase F3, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyChatHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei den übrigen
    # _handle_*-Methoden dieser Klasse (dünner Wrapper -> Handler).

    async def _handle_family_chat_send(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_chat_handler:
            await self.family_chat_handler.handle_send_message_prompt(update, context)
        else:
            await query.edit_message_text("📝 Familien-Chat nicht verfügbar...")

    async def _handle_family_chat_recent(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_chat_handler:
            await self.family_chat_handler.handle_recent_messages(update, context)
        else:
            await query.edit_message_text("📋 Familien-Chat nicht verfügbar...")

    async def _handle_family_chat_notifications(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_chat_handler:
            await self.family_chat_handler.handle_toggle_notifications(update, context)
        else:
            await query.edit_message_text("🔔 Familien-Chat nicht verfügbar...")

    # ====== FAMILIEN-CHALLENGE (Phase F4, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyChallengeHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei den übrigen
    # _handle_*-Methoden dieser Klasse (dünner Wrapper -> Handler).

    async def _handle_family_challenge_today(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_challenge_handler:
            await self.family_challenge_handler.handle_todays_challenge(update, context)
        else:
            await query.edit_message_text("❓ Familien-Challenge nicht verfügbar...")

    async def _handle_family_challenge_answer(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_challenge_handler:
            await self.family_challenge_handler.handle_answer_prompt(update, context)
        else:
            await query.edit_message_text("✅ Familien-Challenge nicht verfügbar...")

    async def _handle_family_challenge_leaderboard(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        if self.family_challenge_handler:
            await self.family_challenge_handler.handle_leaderboard(update, context)
        else:
            await query.edit_message_text("🏆 Familien-Challenge nicht verfügbar...")
