# handlers/menu/rich_menu_handler.py
# -*- coding: utf-8 -*-
"""
🎯 RichMenuHandler - ERWEITERT MIT NAVIDROME, LOGGER, START, HELP, BOT-NEUSTART

CHANGELOG:
  - v2.1  Bot-Neustart-Feature:
          • Import BotRestartHandler
          • BotRestartHandler-Instanziierung (initialize)
          • restart:-Pattern in get_telegram_handlers()

Spotify-Unterstützung (v2.2) wurde entfernt (siehe
docs/archive/arch/MusicBot_ARCH-020_Download_Pipeline_Characterization.md, Abschnitt
"Spotify-Entfernung") - Spotify wurde im produktiven Betrieb nicht genutzt.
"""

import asyncio
from typing import Dict, Callable, Optional, Any
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from logger import get_module_logger
from handlers.menu.text_workflow_dispatcher import TextWorkflowDispatcher
from handlers.menu.rich_menu_system import RichMenuSystem
from handlers.menu.models import (
    MenuItem,
    AccessLevel,
    MenuState,
)
from handlers.menu.permissions import is_admin_or_owner
from handlers.menu.content import user_context
from handlers.menu.content import greeting
from handlers.menu.content import help as help_content
from handlers.menu.actions import stats as stats_actions
from handlers.menu.actions import admin_diagnostics as admin_diagnostics_actions
from handlers.menu.actions import usermgmt as usermgmt_actions
from handlers.menu.actions import admin_operations as admin_operations_actions
from handlers.menu.actions import download as download_actions
from klassen.download_handler import DownloadHandler
from services.downloader.active_downloads import ActiveDownloadRegistry
from services.downloader.download_history import DownloadHistoryStore
from services.bot_maintenance import MaintenanceModeStore
from handlers.menu.maintenance_gate import is_blocked_by_maintenance
from handlers.menu.activity_tracking import record_activity
from handlers.test_menu_handler import TestMenuHandler
from handlers.enhanced_logger_menu_handler import EnhancedLoggerMenuHandler
from handlers.navidrome_menu_handler import NavidromeMenuHandler
from handlers.menu.reprocessing_menu_handler import ReprocessingMenuHandler
from handlers.library_doctor_handler import LibraryDoctorHandler
from handlers.library_health_review_handler import LibraryHealthReviewHandler
from handlers.repair_musicbot_handler import RepairMusicBotHandler
from handlers.mugge_statistik_handler import StatistikHandler
from handlers.family_stats_handler import FamilyStatsHandler
from handlers.family_chat_handler import FamilyChatHandler
from handlers.family_challenge_handler import FamilyChallengeHandler
from handlers.admin.user_management_handler import UserManagementHandler
from handlers.admin.backup_handler import BackupHandler
from handlers.admin.bot_restart_handler import BotRestartHandler
from handlers.duplicate_handler import EnhancedDuplicateHandler
from services.duplicate.detector import DuplicateDetector
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
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)

# ─────────────────────────────────────────────────────────────────────────────


class RichMenuHandler:
    """
    Integration Layer zwischen RichMenuSystem und bestehenden Handlern.

    Verwaltet alle Handler-Instanzen, initialisiert sie in der richtigen
    Reihenfolge und verknüpft sie mit dem Menüsystem.
    """

    def __init__(
        self,
        config: Config,
        logger_factory=None,
        error_handler: Optional[EnhancedErrorHandler] = None,
    ):
        self.config = config
        self.logger_factory = logger_factory
        self.logger = (self.logger_factory or get_module_logger)("RichMenuHandler")

        # Error Handler (muss zuerst initialisiert werden).
        # ARCH-027: optionale Constructor-Injection einer bereits von
        # bot.py erzeugten und als PTB-Application-Error-Handler
        # registrierten EnhancedErrorHandler-Instanz - siehe initialize()
        # weiter unten, das bei bereits injizierter Instanz KEINE eigene
        # zweite Instanz mehr erzeugt (vorher: RichMenuHandler erzeugte in
        # initialize() immer eine eigene, von bot.py unabhaengige Instanz -
        # siehe docs/MusicBot_ARCH-026_Error_Handler_Integration_Audit.md,
        # docs/MusicBot_ARCH-027_Error_Handler_Consolidation.md). Bleibt
        # None fuer eigenstaendige Konstruktion ohne bot.py (Tests,
        # Standalone-Nutzung) - initialize() erzeugt dann wie bisher einen
        # kontrollierten Fallback.
        self.error_handler: Optional[EnhancedErrorHandler] = error_handler

        # Core System
        self.menu_system = RichMenuSystem(config, self.logger_factory)

        # Handler-Referenzen
        self.stats_handler: Optional[StatistikHandler] = None
        self.family_stats_handler: Optional[FamilyStatsHandler] = None
        self.family_chat_handler: Optional[FamilyChatHandler] = None
        self.family_challenge_handler: Optional[FamilyChallengeHandler] = None
        self.test_handler: Optional[TestMenuHandler] = None
        self.logger_handler: Optional[EnhancedLoggerMenuHandler] = None
        self.navidrome_handler: Optional[NavidromeMenuHandler] = None
        self.user_mgmt_handler: Optional[Any] = None
        self.duplicate_handler: Optional[EnhancedDuplicateHandler] = None
        self.duplicate_detector: Optional[DuplicateDetector] = None
        self.error_admin_interface: Optional[ErrorHandlerAdminInterface] = None
        self.metadata_processor: Optional[EnhancedMetadataProcessor] = None
        self.status_handler: Optional[EnhancedStatusHandler] = None
        self.backup_handler: Optional[BackupHandler] = None
        self.restart_handler: Optional[BotRestartHandler] = None
        self.reprocessing_handler: Optional[ReprocessingMenuHandler] = None
        self.doctor_handler: Optional[LibraryDoctorHandler] = None
        self.review_handler: Optional[LibraryHealthReviewHandler] = None
        self.repair_handler: Optional[RepairMusicBotHandler] = None

        # Download-Control-Center 2026-09-02: EINE prozessweite Registry,
        # ueber die gesamte Bot-Laufzeit auf diesem (im Gegensatz zu
        # DownloadHandler pro Update neu erzeugten) Objekt gehalten - siehe
        # services/downloader/active_downloads.py-Docstring.
        self.active_downloads = ActiveDownloadRegistry(
            logger_factory=self.logger_factory
        )

        # Download-Verlauf ("📋 Download-Verlauf"/"🔁 Erneut versuchen",
        # Folgeschritt des Download-Control-Centers): ebenfalls EINE
        # prozessweite, langlebige Instanz (JSON-persistiert, siehe
        # services/downloader/download_history.py-Docstring) - analog zu
        # active_downloads oben, aus demselben Grund (DownloadHandler wird
        # pro Update neu erzeugt, der Verlauf muss das überstehen).
        self.download_history = DownloadHistoryStore(
            cache_dir=str(
                getattr(self.config, "DOWNLOAD_HISTORY_DIR", "cache/download_history")
            ),
            logger=(self.logger_factory or get_module_logger)("DownloadHistoryStore"),
        )

        # Wartungsmodus ("🛠️ Ein-/Ausschalten" ueber Telegram-Inline-
        # Buttons, Folgeschritt zu BotRestartHandler): ebenfalls EINE
        # prozessweite, langlebige, JSON-persistierte Instanz - siehe
        # services/bot_maintenance.py-Docstring fuer die Begruendung,
        # warum das bewusst kein echtes Prozess-An/Aus ist. state_file
        # bewusst explizit ueber das (in Tests via _make_handler()
        # gepatchte) Path() DIESES Moduls aufgeloest, statt den Default-
        # String an MaintenanceModeStore durchzureichen - identisches
        # Test-Isolationsmuster wie bei user_data_file oben.
        self.maintenance_store = MaintenanceModeStore(
            state_file=str(Path("data/maintenance_mode.json")),
            logger=(self.logger_factory or get_module_logger)("MaintenanceModeStore"),
        )

        # State Management
        self.user_states: Dict[int, str] = {}
        self.workflow_dispatcher = TextWorkflowDispatcher(
            logger=(self.logger_factory or get_module_logger)("TextWorkflowDispatcher")
        )

        # User-Data für Start/Help
        self.user_data_file = Path("data/user_data.json")

        # Feature-Katalog (ARCH-025: verschoben nach
        # handlers/menu/content/user_context.py::FEATURES - Attribut hier
        # bewusst als Alias erhalten, falls extern gelesen).
        self.features = user_context.FEATURES

        self.logger.info("🎯 RichMenuHandler initialisiert")

    # ====== INITIALISIERUNG ======

    def initialize(self) -> None:
        """
        Initialisiert alle Handler in der richtigen Reihenfolge.

        Reihenfolge ist bewusst gewählt:
        1. Error Handler (Basis für alle anderen)
        2. Fachliche Handler (Test, Logger, Stats, Navidrome, ...)
        3. MetadataProcessor (wird von DownloadHandler benötigt)
        4. Menüsystem-Verknüpfung
        """
        self.logger.info("🚀 Starte Handler-Integration ...")

        # 1. Error Handler (höchste Priorität – alle anderen hängen davon ab)
        #
        # ARCH-027: kein stilles Überschreiben einer bereits per Constructor
        # injizierten, gemeinsamen Instanz (siehe __init__ oben) - nur wenn
        # RichMenuHandler eigenständig ohne bot.py konstruiert wurde (Tests,
        # Standalone-Nutzung), wird hier ein kontrollierter Fallback
        # erzeugt. Production (bot.py) injiziert immer bereits eine
        # Instanz, die zugleich als PTB-Application-Error-Handler
        # registriert ist - dadurch teilen sich PTB, RichMenuSystem, alle
        # Sub-Handler und ErrorHandlerAdminInterface exakt denselben
        # Monitoring-/Statistik-Zustand (siehe
        # docs/MusicBot_ARCH-027_Error_Handler_Consolidation.md).
        if self.error_handler is not None:
            self.logger.info(
                "✅ Enhanced Error Handler übernommen (gemeinsame Instanz von bot.py)"
            )
        else:
            try:
                self.error_handler = create_enhanced_error_handler(
                    self.config, self.logger_factory
                )
                self.logger.info(
                    "✅ Enhanced Error Handler initialisiert (Standalone-Fallback, "
                    "keine Instanz injiziert)"
                )
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

        # 4b. Family-Stats-Handler (Phase F2, Family Hub) - eigenständig von
        # StatistikHandler, da FamilyStatsService die Play-History mehrerer
        # Navidrome-User aggregiert statt eines einzelnen (siehe
        # services/family/family_stats_service.py).
        try:
            self.family_stats_handler = FamilyStatsHandler()
            self.logger.info("✅ FamilyStatsHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Family-Stats-Handler Fehler: {e}", exc_info=True)
            self.family_stats_handler = None

        # 4c. Family-Chat-Handler (Phase F3, Family Hub)
        try:
            self.family_chat_handler = FamilyChatHandler()
            self.logger.info("✅ FamilyChatHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Family-Chat-Handler Fehler: {e}", exc_info=True)
            self.family_chat_handler = None

        # 4d. Family-Challenge-Handler (Phase F4, Family Hub) - die
        # tägliche Auslösung/Verteilung übernimmt FamilyChallengeScheduler
        # (handlers/family_challenge_scheduler.py), von bot.py konstruiert
        # (braucht die echte Bot-Instanz, die RichMenuHandler nicht hält).
        try:
            self.family_challenge_handler = FamilyChallengeHandler()
            self.logger.info("✅ FamilyChallengeHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Family-Challenge-Handler Fehler: {e}", exc_info=True)
            self.family_challenge_handler = None

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
            self.duplicate_detector = DuplicateDetector(
                self.config, self.logger_factory
            )
            self.duplicate_handler = EnhancedDuplicateHandler(
                self.config, self.duplicate_detector, self.logger_factory
            )
            self.duplicate_handler.error_handler = self.error_handler
            self.logger.info("✅ EnhancedDuplicateHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Duplicate-Handler Fehler: {e}", exc_info=True)
            self.duplicate_handler = None
            self.duplicate_detector = None

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
            self.backup_handler.error_handler = self.error_handler
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

        # 11. Metadata Processor
        try:
            self.metadata_processor = EnhancedMetadataProcessor(
                self.config, self.logger_factory
            )
            self.logger.info("✅ EnhancedMetadataProcessor initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Metadata-Processor Fehler: {e}", exc_info=True)
            self.metadata_processor = None

        # 12. Reprocessing-Handler (ruft scripts/reprocess_artist_metadata.py
        # ausschliesslich als eigenstaendigen Subprozess auf, siehe
        # docs/METADATA_REPROCESSING.md Abschnitt 2a - genau deshalb
        # unproblematisch, obwohl Schritt 11 oben bereits real beweist,
        # dass EnhancedMetadataProcessor in diesem Bot-Prozess laengst mit
        # der echten config.Config konstruiert ist)
        try:
            self.reprocessing_handler = ReprocessingMenuHandler(
                self.config, self.logger_factory
            )
            self.reprocessing_handler.error_handler = self.error_handler
            self.logger.info("✅ ReprocessingMenuHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Reprocessing-Handler Fehler: {e}", exc_info=True)
            self.reprocessing_handler = None

        # 13. MusicBot-Doctor-Handler (Phase 3, P1.3) - ruft
        # scripts/library_health_check.py und scripts/library_repair.py
        # ausschliesslich als eigenstaendige Subprozesse auf (services/
        # library_repair/doctor_runner.py), analog zum Reprocessing-Handler
        # oben.
        try:
            self.doctor_handler = LibraryDoctorHandler(
                self.config, self.logger_factory
            )
            self.doctor_handler.error_handler = self.error_handler
            self.logger.info("✅ LibraryDoctorHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Doctor-Handler Fehler: {e}", exc_info=True)
            self.doctor_handler = None

        # 14. Library-Health-Review-Handler ("Library Health Review",
        # Teil B) - Telegram-Oberflaeche fuer die persistente Findings-
        # Registry (services/library_health/findings.py), verwendet
        # dieselbe zentrale Review-Service-Logik wie
        # scripts/library_health_review.py. Reine Registry-Persistenz,
        # keine Subprozesse, kein Library-Zugriff.
        try:
            self.review_handler = LibraryHealthReviewHandler(
                self.config, self.logger_factory
            )
            self.review_handler.error_handler = self.error_handler
            self.logger.info("✅ LibraryHealthReviewHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Review-Handler Fehler: {e}", exc_info=True)
            self.review_handler = None

        # 15. Repair-MusicBot-Handler ("Repair MusicBot", Teil C) -
        # Telegram-Oberflaeche fuer services/library_repair/repair_service.py,
        # verwendet ausschliesslich bereits bestehende Repair-Infrastruktur
        # (Doctor-Subprozess-Pfad, Planner, Journal, Findings-Registry).
        try:
            self.repair_handler = RepairMusicBotHandler(
                self.config, self.logger_factory
            )
            self.repair_handler.error_handler = self.error_handler
            self.logger.info("✅ RepairMusicBotHandler initialisiert")
        except Exception as e:
            self.logger.error(f"❌ Repair-Handler Fehler: {e}", exc_info=True)
            self.repair_handler = None

        self._record_initial_handler_statuses()

        # ── Menüsystem initialisieren und Handler verknüpfen ──────────────────
        self.menu_system.initialize_menu_structure()
        self.menu_system.error_handler = self.error_handler
        self.menu_system.set_error_handler(self.error_handler)

        if self.logger_handler:
            self.menu_system.set_logger_handler(self.logger_handler)
        if self.stats_handler:
            self.menu_system.set_stats_handler(self.stats_handler)
        if self.family_stats_handler:
            self.menu_system.set_family_stats_handler(self.family_stats_handler)
        if self.family_chat_handler:
            self.menu_system.set_family_chat_handler(self.family_chat_handler)
        if self.family_challenge_handler:
            self.menu_system.set_family_challenge_handler(self.family_challenge_handler)
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
        self.menu_system.set_active_downloads(self.active_downloads)
        self.menu_system.set_download_history(self.download_history)
        self.menu_system.set_url_retry_callback(self._process_url)
        self.menu_system.set_maintenance_store(self.maintenance_store)
        if self.reprocessing_handler:
            self.menu_system.set_reprocessing_handler(self.reprocessing_handler)
        if self.doctor_handler:
            self.menu_system.set_doctor_handler(self.doctor_handler)
        if self.review_handler:
            self.menu_system.set_review_handler(self.review_handler)
        if self.repair_handler:
            self.menu_system.set_repair_handler(self.repair_handler)

        # Handler registrieren
        self._register_download_handlers()
        self._register_stats_handlers()
        self._register_admin_handlers()
        self._register_system_handlers()
        self._register_test_handlers()

        self.logger.info("✅ Handler-Integration abgeschlossen")

    def _record_initial_handler_statuses(self) -> None:
        """
        Funktions-Fund (docs/audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md):
        der "🤖 Bot-Status"-Screen zeigt "Handler: Gesamt/Aktiv" aus
        BotStatusTracker.get_handler_overview() an - aber
        update_handler_status() wurde nirgends aufgerufen, die Anzeige
        war dadurch dauerhaft 0/0. Zeichnet hier, an der einzigen Stelle
        mit Kenntnis ALLER Konstruktionsergebnisse aus initialize(), den
        tatsächlichen Erfolg/Fehlschlag jedes dort initialisierten
        Handlers auf - "active" bei erfolgreicher Konstruktion, "error"
        wenn der jeweilige try/except-Block dort fehlschlug (Instanz
        blieb None). Eigene Methode statt Inline-Block in initialize()
        (das selbst viele echte Handler konstruiert und daher nicht
        end-to-end unit-testbar ist) - macht NUR diese neue Logik isoliert
        testbar, ohne initialize() selbst zu verändern.
        """
        if not self.status_handler:
            return
        for handler_name, handler_instance in [
            ("error_handler", self.error_handler),
            ("test_handler", self.test_handler),
            ("logger_handler", self.logger_handler),
            ("stats_handler", self.stats_handler),
            ("family_stats_handler", self.family_stats_handler),
            ("family_chat_handler", self.family_chat_handler),
            ("family_challenge_handler", self.family_challenge_handler),
            ("navidrome_handler", self.navidrome_handler),
            ("user_mgmt_handler", self.user_mgmt_handler),
            ("duplicate_handler", self.duplicate_handler),
            ("backup_handler", self.backup_handler),
            ("restart_handler", self.restart_handler),
            ("metadata_processor", self.metadata_processor),
            ("reprocessing_handler", self.reprocessing_handler),
            ("doctor_handler", self.doctor_handler),
            ("review_handler", self.review_handler),
            ("repair_handler", self.repair_handler),
        ]:
            self.status_handler.bot_tracker.update_handler_status(
                handler_name, "active" if handler_instance else "error"
            )

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
        self.menu_system.register_handler(
            "stats_timeline", self._handle_timeline_stats_wrapper
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
            # ARCH-023/P-4: is_action war zuvor False (Default) trotz bei
            # Konstruktion gesetztem handler= - semantisch inkonsistent mit
            # jedem anderen echten Aktions-Item im Menuebaum (siehe
            # initialize_menu_structure(), wo jede echte Aktion explizit
            # is_action=True traegt; nur reine Navigations-Links wie
            # "nav_link_stats" bleiben bewusst False). is_action wird von
            # keiner Produktionslogik gelesen (nur von Test-Tooling, siehe
            # tests/test_rich_menu_access_control.py/test_suite.py) -
            # reine Korrektur der Modellierung, kein Verhaltensrisiko.
            is_action=True,
        )
        # Admin-Menü-Reorg: Navidrome Scan gehört fachlich zur Gruppe
        # "Bibliothek & Navidrome" (admin_group_library), nicht mehr direkt
        # unter "admin" (siehe Analyse-Bericht, Abschnitt F/H).
        self.menu_system.add_child_menu_item("admin_group_library", navidrome_menu)
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

    def set_stats_handler(self, handler: StatistikHandler) -> None:
        self.stats_handler = handler
        self.logger.info("✅ StatsHandler verbunden")

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
            # Wartungsmodus 2026-09-03: derselbe "Bug B"-Fall wie beim
            # dl:-Präfix unten (Live-Fund direkt beim ersten Live-Test
            # dieses Features, siehe docs/MusicBot_TELEGRAM_MENU_SYSTEM.md
            # Abschnitt 5, Schritt 3) - ohne diesen Handler verpuffte
            # jeder maint:-Callback (Menüpunkt UND Toggle-Button)
            # stillschweigend, obwohl das interne maint:-Routing in
            # RichMenuSystem.handle_callback() bereits korrekt war.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^maint:"),
            # Download-Control-Center 2026-09-02 (Live-Fund: "restliche
            # Buttons sind tot außer Hauptmenü"): CallbackQueryHandler
            # werden PTB-seitig über feste pattern=-Allowlists geroutet -
            # das interne dl:-Präfix-Routing in
            # RichMenuSystem.handle_callback() (siehe dort) wird nie
            # erreicht, wenn hier kein eigener Handler für "^dl:"
            # registriert ist. menu:download selbst funktionierte bereits
            # (passt auf "^menu:" unten), nur die dl:*-Folge-Callbacks
            # (Neuer Download/Aktive Downloads/Verlauf/Abbrechen/Details/
            # Zurück) liefen dadurch ins Leere - PTB ignorierte sie
            # komplett (kein Handler-Match), daher weder Log-Eintrag noch
            # Exception.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^dl:"),
            # Metadata-Reprocessing 2026-09-03: derselbe "Bug B"-Fall wie
            # bei maint:/dl: oben - ohne diesen Handler verpuffte jeder
            # reprocess:-Callback stillschweigend, obwohl das interne
            # reprocess:-Routing in RichMenuSystem.handle_callback()
            # bereits korrekt ist.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^reprocess:"),
            # MusicBot Doctor (Phase 3, P1.3): derselbe "Bug B"-Fall wie bei
            # maint:/dl:/reprocess: oben - ohne diesen Handler verpuffte
            # jeder doctor:-Callback stillschweigend, obwohl das interne
            # doctor:-Routing in RichMenuSystem.handle_callback() bereits
            # korrekt ist.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^doctor:"),
            # Library Health Review: derselbe "Bug B"-Fall wie bei
            # maint:/dl:/reprocess:/doctor: oben - ohne diesen Handler
            # verpuffte jeder review:-Callback stillschweigend.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^review:"),
            # Repair MusicBot: derselbe "Bug B"-Fall wie bei maint:/dl:/
            # reprocess:/doctor:/review: oben - ohne diesen Handler
            # verpuffte jeder repair:-Callback stillschweigend.
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^repair:"),
            # Allgemeines Menü zuletzt
            CallbackQueryHandler(self.menu_system.handle_callback, pattern="^menu:"),
            # URL Handler (YouTube-URLs)
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
        """Wrapper für Single-Download (YouTube)."""
        await download_actions.handle_download_single_wrapper(
            update, context, self.user_states, self.logger
        )

    async def _handle_download_playlist_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Wrapper für Playlist-Download (YouTube)."""
        await download_actions.handle_download_playlist_wrapper(
            update, context, self.user_states, self.logger
        )

    # ====== STATISTIK WRAPPER ======

    async def _handle_monthly_stats_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await stats_actions.handle_monthly_stats_wrapper(
            update, context, self.stats_handler, self.logger
        )

    async def _handle_yearly_stats_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await stats_actions.handle_yearly_stats_wrapper(
            update, context, self.stats_handler, self.logger
        )

    async def _handle_top_songs_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await stats_actions.handle_top_songs_wrapper(
            update, context, self.stats_handler, self.logger
        )

    async def _handle_top_artists_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await stats_actions.handle_top_artists_wrapper(
            update, context, self.stats_handler, self.logger
        )

    async def _handle_timeline_stats_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await stats_actions.handle_timeline_stats_wrapper(
            update, context, self.stats_handler, self.logger
        )

    # ====== ADMIN WRAPPER ======

    async def _handle_user_management_wrapper(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await usermgmt_actions.handle_user_management_wrapper(
            update,
            context,
            self.config,
            getattr(self, "user_mgmt_handler", None),
            getattr(self, "error_handler", None),
            self.logger,
        )

    async def _handle_view_logs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await admin_diagnostics_actions.handle_view_logs(
            update, context, self.config, self.logger
        )

    async def _handle_navidrome_scan(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        ARCH-009 Phase 9 (Umsetzung A) - siehe
        handlers/menu/actions/admin_operations.py::handle_navidrome_scan()
        für den vollständigen Docstring/die Begründung.
        """
        await admin_operations_actions.handle_navidrome_scan(
            update, context, self.config, self.logger
        )

    # ====== HILFS-METHODEN ======

    def _is_admin(self, user_id: int) -> bool:
        """Prüft Admin- oder Owner-Rechte (ARCH-021/P-3: delegiert an
        permissions.is_admin_or_owner(), gemeinsam mit
        RichMenuSystem._is_admin_check())."""
        return is_admin_or_owner(user_id, self.config)

    def _load_user_data(self) -> Dict[str, Any]:
        """Lädt User-Daten aus JSON (ARCH-025: delegiert an
        content.user_context.load_user_data())."""
        return user_context.load_user_data(
            self.user_data_file, self.logger, self.user_mgmt_handler
        )

    def _get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Holt User-Informationen (ARCH-025: delegiert an
        content.user_context.get_user_info())."""
        return user_context.get_user_info(
            user_id, self.user_data_file, self.logger, self.user_mgmt_handler
        )

    def _is_new_user(self, user_id: int) -> bool:
        """Prüft ob User neu ist (< 24h registriert) (ARCH-025: delegiert
        an content.user_context.is_new_user())."""
        return user_context.is_new_user(
            user_id, self.user_data_file, self.logger, self.user_mgmt_handler
        )

    def _get_user_role(self, user_id: int) -> str:
        """Ermittelt User-Rolle (owner > admin > moderator > user)
        (ARCH-025: delegiert an content.user_context.get_user_role())."""
        return user_context.get_user_role(
            user_id, self.config, self.user_data_file, self.logger, self.user_mgmt_handler
        )

    def _get_available_features(self, user_role: str) -> Dict[str, Dict]:
        """Gibt verfügbare Features basierend auf Rolle zurück (ARCH-025:
        delegiert an content.user_context.get_available_features())."""
        return user_context.get_available_features(user_role)

    def _create_download_handler(self, update: Update) -> Optional[DownloadHandler]:
        """
        Erstellt eine neue DownloadHandler-Instanz mit allen injizierten
        Abhängigkeiten.

        Der MetadataProcessor und DuplicateHandler werden geteilt.

        Args:
            update: Telegram-Update-Objekt

        Returns:
            Fertig konfigurierter DownloadHandler oder None bei fehlenden
            Abhängigkeiten.
        """
        return download_actions.create_download_handler(
            update,
            self.config,
            self.duplicate_detector,
            self.metadata_processor,
            self.logger_factory,
            self.active_downloads,
            self.download_history,
            self.logger,
        )

    # ====== COMMAND HANDLER ======

    async def handle_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Erweiterter /start Command Handler mit personalisierter Begrüßung
        (ARCH-025: delegiert an content.greeting.send_start_message())."""
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "command:start")
        await greeting.send_start_message(
            update,
            context,
            self.config,
            self.user_mgmt_handler,
            self.user_data_file,
            self.error_handler,
            self.logger,
        )

    async def handle_menu_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt Hauptmenü bei /menu."""
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "command:menu")
        self.logger.info(f"📱 /menu von User {update.effective_user.id}")
        await self.menu_system.show_menu(update, context, "main")

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Erweiterter /help Command Handler (ARCH-025: delegiert an
        content.help.send_help_message())."""
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "command:help")
        await help_content.send_help_message(
            update,
            context,
            self.config,
            self.user_mgmt_handler,
            self.user_data_file,
            self.error_handler,
            self.logger,
        )

    async def handle_help_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Callback-Handler für spezifische Hilfe-Themen (pattern='^help:')
        (ARCH-025: delegiert an content.help.send_help_callback_response())."""
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "callback:help")
        await help_content.send_help_callback_response(
            update,
            context,
            self.config,
            self.user_mgmt_handler,
            self.user_data_file,
            self.logger,
        )

    # ====== MESSAGE HANDLER ======

    async def handle_url_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Verarbeitet URL-Nachrichten basierend auf dem User-State.

        Die URL-Validierung erfolgt in DownloadHandler.handle_url().
        """
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "message:url")
        await download_actions.handle_url_message(
            update, context, self.user_states, self._process_url
        )

    async def _process_url(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str,
    ) -> None:
        """
        Erstellt einen DownloadHandler und startet den Download-Prozess -
        siehe handlers/menu/actions/download.py::process_url() für den
        vollständigen Docstring/die Begründung (Hintergrund-Task wegen
        fehlendem concurrent_updates=True, siehe dort).
        """
        await download_actions.process_url(
            update, context, url, self._create_download_handler, self.logger
        )

    def _log_background_download_task_exception(self, task: "asyncio.Task") -> None:
        """add_done_callback()-Sicherheitsnetz für _process_url()'s
        Hintergrund-Download-Task - siehe
        handlers/menu/actions/download.py::_log_background_download_task_exception()."""
        download_actions._log_background_download_task_exception(task, self.logger)

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
        if await is_blocked_by_maintenance(
            update,
            context,
            maintenance_store=getattr(self, "maintenance_store", None),
            config=self.config,
            logger=self.logger,
        ):
            return
        record_activity(update, getattr(self, "status_handler", None), "message:text")
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
        if self.workflow_dispatcher.is_cancel_command(text):
            context.user_data.clear()
            if user_id in self.user_states:
                del self.user_states[user_id]
            family_chat_handler = getattr(self, "family_chat_handler", None)
            if family_chat_handler:
                family_chat_handler.pending_message_senders.discard(user_id)
            family_challenge_handler = getattr(self, "family_challenge_handler", None)
            if family_challenge_handler:
                family_challenge_handler.pending_answers.pop(user_id, None)
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

        # Familien-Chat: wartet dieser User gerade auf seine Chat-Nachricht?
        # (Phase F3, Family Hub - siehe FamilyChatHandler-Docstring zur
        # bewussten Entscheidung gegen den generischen TextWorkflowDispatcher.)
        family_chat_handler = getattr(self, "family_chat_handler", None)
        if family_chat_handler and user_id in family_chat_handler.pending_message_senders:
            await family_chat_handler.process_pending_message(update, context, text)
            return

        # Familien-Challenge: wartet dieser User gerade auf seine Antwort?
        # (Phase F4, Family Hub - dasselbe Muster wie beim Familien-Chat
        # oben, siehe FamilyChallengeHandler-Docstring.)
        family_challenge_handler = getattr(self, "family_challenge_handler", None)
        if family_challenge_handler and user_id in family_challenge_handler.pending_answers:
            await family_challenge_handler.process_pending_answer(update, context, text)
            return

        # Aktive Workflows prüfen
        handled = await self.workflow_dispatcher.try_dispatch(
            update, context, text, self.user_mgmt_handler
        )
        if handled:
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
