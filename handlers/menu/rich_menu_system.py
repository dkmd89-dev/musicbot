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

from telegram import Update, InlineKeyboardMarkup
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
from handlers.menu import definitions
from handlers.menu import rendering
from handlers.menu.actions import family as family_actions
from handlers.menu.actions import duplicates as duplicates_actions
from handlers.menu.actions import _common as actions_common
from handlers.menu.actions import navidrome as navidrome_actions
from handlers.menu.actions import stats as stats_actions
from handlers.menu.actions import admin_diagnostics as admin_diagnostics_actions
from handlers.menu.actions import usermgmt as usermgmt_actions
from handlers.menu.actions import library as library_actions
from handlers.menu.actions import admin_operations as admin_operations_actions
from handlers.menu.actions import download as download_actions


# ARCH-024/P-2: _dl_progress_bar/_RetryMessageAdapter/_RetryUpdateAdapter
# leben jetzt in handlers/menu/actions/download.py (siehe dort).


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
        """Erstellt die Menü-Hierarchie (ARCH-024/P-3: delegiert an
        definitions.build_menu_tree()/definitions.populate_registry())."""
        self.logger.info("🗂️ Erstelle Menü-Struktur...")
        self.root_menu = definitions.build_menu_tree(self)
        self._build_registry(self.root_menu)
        self.logger.info(f"✅ Menü-Struktur erstellt: {len(self.menu_registry)} Items")

    def _build_registry(self, menu: MenuItem) -> None:
        """Baut flache Registry für schnellen Zugriff (ARCH-024/P-3:
        delegiert an definitions.populate_registry())."""
        definitions.populate_registry(self.menu_registry, menu)

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
        await admin_operations_actions.handle_backup_main(update, context, self.backup_handler)

    async def _handle_backup_bot_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Bot-Backup Bestätigung"""
        await admin_operations_actions.handle_backup_bot_confirm(update, context, self.backup_handler)

    async def _handle_backup_lib_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Library-Backup Bestätigung"""
        await admin_operations_actions.handle_backup_lib_confirm(update, context, self.backup_handler)

    async def _handle_backup_list_bot(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Bot-Backup-Liste anzeigen"""
        await admin_operations_actions.handle_backup_list_bot(update, context, self.backup_handler)

    async def _handle_backup_list_lib(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper: Library-Backup-Liste anzeigen"""
        await admin_operations_actions.handle_backup_list_lib(update, context, self.backup_handler)

    # ====== NEU: BOT-NEUSTART WRAPPER ======

    async def _handle_restart_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Einstiegspunkt aus dem Menü-System für den Bot-Neustart.
        Leitet an BotRestartHandler.show_restart_confirm() weiter.
        """
        await admin_operations_actions.handle_restart_show(update, context, self.restart_handler)

    # ====== ENDE BOT-NEUSTART WRAPPER ======

    # ====== NEU: WARTUNGSMODUS ======
    #
    # Anders als der Bot-Neustart bewusst OHNE eigene Handler-Klasse -
    # siehe handlers/menu/actions/admin_operations.py.

    async def _handle_maintenance_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Einstiegspunkt aus dem Menü-System - zeigt den aktuellen
        Wartungsmodus-Status mit Toggle-Button.
        """
        await admin_operations_actions.handle_maintenance_show(
            update, context, self._is_admin_check, self.maintenance_store
        )

    async def _handle_maintenance_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """
        Dispatcher für alle maint:* Callbacks - siehe
        handlers/menu/actions/admin_operations.py::handle_maintenance_callback().
        """
        await admin_operations_actions.handle_maintenance_callback(
            update, context, callback_data, self._is_admin_check, self.maintenance_store, self.logger
        )

    # ====== ENDE WARTUNGSMODUS ======

    # ====== METADATA-REPROCESSING ======

    async def _handle_reprocessing_show(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu den
        _handle_navidrome_*-Methoden."""
        await library_actions.handle_reprocessing_show(
            update, context, self.reprocessing_handler
        )

    async def _handle_reprocessing_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Dispatcher für alle reprocess:* Callbacks - siehe
        handlers/menu/actions/library.py::handle_reprocessing_callback()."""
        await library_actions.handle_reprocessing_callback(
            update, context, callback_data, self.reprocessing_handler, self.config, self.logger
        )

    # ====== ENDE METADATA-REPROCESSING ======

    # ====== MUSICBOT DOCTOR (Phase 3, P1.3) ======

    async def _handle_doctor_scan(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_reprocessing_show()."""
        await library_actions.handle_doctor_scan(update, context, self.doctor_handler)

    async def _handle_doctor_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Dispatcher für alle doctor:* Callbacks - siehe
        handlers/menu/actions/library.py::handle_doctor_callback()."""
        await library_actions.handle_doctor_callback(
            update, context, callback_data, self.doctor_handler, self._is_admin_check, self.logger
        )

    # ====== ENDE MUSICBOT DOCTOR ======

    # ====== LIBRARY HEALTH REVIEW ======

    async def _handle_review_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_doctor_scan()."""
        await library_actions.handle_review_start(update, context, self.review_handler)

    async def _handle_review_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Dispatcher für alle review:* Callbacks - siehe
        handlers/menu/actions/library.py::handle_review_callback()."""
        await library_actions.handle_review_callback(
            update, context, callback_data, self.review_handler, self._is_admin_check, self.logger
        )

    # ====== ENDE LIBRARY HEALTH REVIEW ======

    # ====== REPAIR MUSICBOT ======

    async def _handle_repair_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
        _handle_doctor_scan()/_handle_review_start()."""
        await library_actions.handle_repair_start(update, context, self.repair_handler)

    async def _handle_repair_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Dispatcher für alle repair:* Callbacks - siehe
        handlers/menu/actions/library.py::handle_repair_callback()."""
        await library_actions.handle_repair_callback(
            update, context, callback_data, self.repair_handler, self._is_admin_check, self.logger
        )

    # ====== ENDE REPAIR MUSICBOT ======

    async def _show_handler_not_available(self, update: Update, handler_name: str):
        """Zeigt Fehlermeldung wenn Handler nicht verfügbar"""
        await actions_common.show_handler_not_available(update, handler_name)

    # ====== NAVIDROME WRAPPER ======

    async def _handle_navidrome_browse_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Künstler-Browse"""
        await navidrome_actions.handle_browse_artists(update, context, self.navidrome_handler)

    async def _handle_navidrome_browse_albums(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Album-Browse"""
        await navidrome_actions.handle_browse_albums(update, context, self.navidrome_handler)

    async def _handle_navidrome_browse_genres(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Genre-Browse"""
        await navidrome_actions.handle_browse_genres(update, context, self.navidrome_handler)

    async def _handle_navidrome_browse_playlists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Playlist-Browse"""
        await navidrome_actions.handle_browse_playlists(update, context, self.navidrome_handler)

    async def _handle_navidrome_search_all(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für universelle Suche"""
        await navidrome_actions.handle_search_all(update, context, self.navidrome_handler)

    async def _handle_navidrome_search_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Künstler-Suche"""
        await navidrome_actions.handle_search_artists(update, context, self.navidrome_handler)

    async def _handle_navidrome_search_albums(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Album-Suche"""
        await navidrome_actions.handle_search_albums(update, context, self.navidrome_handler)

    async def _handle_navidrome_search_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Song-Suche"""
        await navidrome_actions.handle_search_songs(update, context, self.navidrome_handler)

    async def _handle_navidrome_my_playlists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Meine Playlists"""
        await navidrome_actions.handle_my_playlists(update, context, self.navidrome_handler)

    async def _handle_navidrome_favorites(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Favoriten"""
        await navidrome_actions.handle_favorites(update, context, self.navidrome_handler)

    async def _handle_navidrome_recent(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Zuletzt gespielt (ruft StatistikHandler auf)"""
        await navidrome_actions.handle_recent(update, context, self.stats_handler)

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
        """Erstellt Telegram InlineKeyboard für Menü (ARCH-024/P-4:
        delegiert an rendering.render_menu())."""
        return rendering.render_menu(menu_item, user_level)

    def get_menu_text(self, menu_item: MenuItem) -> str:
        """Erstellt Menü-Text mit Breadcrumb (ARCH-024/P-4: delegiert an
        rendering.get_menu_text())."""
        return rendering.get_menu_text(menu_item)

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        menu_id: Optional[str] = None,
    ) -> None:
        """Zeigt Menü an oder aktualisiert es (ARCH-024/P-4: delegiert an
        rendering.show_menu())."""
        await rendering.show_menu(
            update,
            context,
            menu_id,
            self.menu_registry,
            self.root_menu,
            self.get_session,
            self._get_user_access_level,
            self.logger,
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
                # ARCH-023/P-3 Menu-Fallback-Gate: menu_item.access_level
                # wurde bisher ausschliesslich in render_menu() fuer die
                # Button-Sichtbarkeit ausgewertet, nie beim tatsaechlichen
                # Dispatch hier (TGPERM-001-Fehlerklasse - ein privilegiertes
                # Item war nur geschuetzt, wenn sein individueller Handler
                # zufaellig selbst einen Check besass). Zentrale Durchsetzung
                # jetzt hier, vor jedem Handler-Aufruf, unabhaengig davon, ob
                # der Ziel-Handler zusaetzlich eine eigene Pruefung hat.
                user_level = self._get_user_access_level(user_id)
                if not menu_item.is_accessible(user_level):
                    self.logger.warning(
                        f"🚨 [SECURITY] User {user_id} ohne ausreichende Berechtigung "
                        f"versuchte privilegiertes Menu-Item '{menu_item.id}' "
                        f"(benoetigt: {menu_item.access_level.name}, hat: {user_level.name}): "
                        f"{callback_data}"
                    )
                    await query.answer("⛔ Keine Berechtigung", show_alert=True)
                    return
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
        await admin_diagnostics_actions.handle_logger_callback(
            update, context, callback_data, self.logger_handler, self.logger
        )

    async def _handle_navidrome_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle nav_* Callbacks"""
        await navidrome_actions.handle_navidrome_callback(
            update, context, callback_data, self.navidrome_handler, self.logger
        )

    async def _handle_usermgmt_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """
        Spezial-Handler für alle usermgmt_* Callbacks
        Unterstützt Navidrome-User-Workflows
        """
        await usermgmt_actions.handle_usermgmt_callback(
            update, context, callback_data, self.user_mgmt_handler, self.logger
        )

    async def _handle_duplicate_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle dup:* Callbacks"""
        await duplicates_actions.handle_duplicate_callback(
            update, context, callback_data, self.duplicate_handler, self.logger
        )

    async def _handle_error_admin_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle erradmin:* Callbacks"""
        await admin_diagnostics_actions.handle_error_admin_callback(
            update, context, callback_data, self.error_admin_interface, self.logger
        )

    async def _handle_status_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle status_* Callbacks"""
        await admin_diagnostics_actions.handle_status_callback(
            update, context, callback_data, self.status_handler, self.logger
        )

    async def _handle_backup_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ):
        """Spezial-Handler für alle backup_* Callbacks"""
        await admin_operations_actions.handle_backup_callback(
            update, context, callback_data, self.backup_handler, self.logger
        )

    # ====== NEU: BOT-NEUSTART CALLBACK-DISPATCHER ======

    async def _handle_restart_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Dispatcher für alle restart:* Callbacks - siehe
        handlers/menu/actions/admin_operations.py::handle_restart_callback()."""
        await admin_operations_actions.handle_restart_callback(
            update, context, callback_data, self.restart_handler, self._is_admin_check, self.logger
        )

    # ====== ENDE BOT-NEUSTART CALLBACK-DISPATCHER ======

    async def _handle_status_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Wrapper für Status-Menü"""
        await admin_diagnostics_actions.handle_status_menu(
            update, context, self.status_handler, self._show_handler_not_available
        )

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
        await download_actions.handle_download_menu(update, context, self.active_downloads)

    async def _render_download_menu(self, query, active) -> None:
        await download_actions.render_download_menu(query, active)

    async def _handle_download_control_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str
    ) -> None:
        """Spezial-Handler für alle dl:*-Callbacks (Download-Control-Center),
        analog zu _handle_backup_callback() etc."""
        await download_actions.handle_download_control_callback(
            update,
            context,
            callback_data,
            self.active_downloads,
            self.download_history,
            self._retry_url_callback,
            self.logger,
        )

    # ====== PLATZHALTER-HANDLER ======

    async def _handle_download_single(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await download_actions.handle_download_single_placeholder(update, context)

    async def _handle_download_playlist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await download_actions.handle_download_playlist_placeholder(update, context)

    async def _handle_stats_monthly(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await stats_actions.handle_stats_monthly_system(update, context, self.stats_handler)

    async def _handle_stats_yearly(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await stats_actions.handle_stats_yearly_system(update, context, self.stats_handler)

    async def _handle_stats_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await stats_actions.handle_stats_top_songs_system(update, context, self.stats_handler)

    async def _handle_stats_library_overview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Phase 3, P1.1 — Library-Zusammensetzung aus dem Health-Report,
        anders als die übrigen stats_*-Handler keine Play-History."""
        await stats_actions.handle_stats_library_overview(update, context, self.stats_handler)

    async def _handle_stats_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await stats_actions.handle_stats_top_artists_system(update, context, self.stats_handler)

    async def _handle_stats_timeline(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await stats_actions.handle_stats_timeline_system(update, context, self.stats_handler)

    # ====== FAMILIEN-STATISTIK (Phase F2, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyStatsHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei allen übrigen
    # _handle_stats_*-Methoden dieser Klasse (dünner Wrapper -> Handler).

    async def _handle_family_stats_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_top_songs(
            update, context, self.family_stats_handler
        )

    async def _handle_family_stats_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_top_artists(
            update, context, self.family_stats_handler
        )

    async def _handle_family_stats_member(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_member(
            update, context, self.family_stats_handler
        )

    async def _handle_family_stats_champion(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_champion(
            update, context, self.family_stats_handler
        )

    async def _handle_family_stats_listening_times(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_listening_times(
            update, context, self.family_stats_handler
        )

    async def _handle_family_stats_monthly_trend(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_stats_monthly_trend(
            update, context, self.family_stats_handler
        )

    # ====== FAMILIEN-CHAT (Phase F3, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyChatHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei den übrigen
    # Actions in handlers/menu/actions/family.py (dünner Wrapper -> Handler).

    async def _handle_family_chat_send(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_chat_send(
            update, context, self.family_chat_handler
        )

    async def _handle_family_chat_recent(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_chat_recent(
            update, context, self.family_chat_handler
        )

    async def _handle_family_chat_notifications(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_chat_notifications(
            update, context, self.family_chat_handler
        )

    # ====== FAMILIEN-CHALLENGE (Phase F4, Family Hub) ======
    # Zugriffsprüfung (Family-Membership) erfolgt in FamilyChallengeHandler
    # selbst, nicht hier - dieselbe Aufgabenteilung wie bei den übrigen
    # Actions in handlers/menu/actions/family.py (dünner Wrapper -> Handler).

    async def _handle_family_challenge_today(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_challenge_today(
            update, context, self.family_challenge_handler
        )

    async def _handle_family_challenge_answer(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_challenge_answer(
            update, context, self.family_challenge_handler
        )

    async def _handle_family_challenge_leaderboard(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await family_actions.handle_family_challenge_leaderboard(
            update, context, self.family_challenge_handler
        )
