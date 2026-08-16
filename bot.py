# bot.py - ANGEPASST FÜR RICHMENUSYSTEM MIT GET_MODULE_LOGGER
# -*- coding: utf-8 -*-
"""
🎵 TELEGRAM MUSIK-BOT mit RichMenuSystem & Error Handler
Direkte Integration mit RichMenuSystem
"""

import sys
import gc
from typing import Optional
from pathlib import Path
import asyncio
import signal

# aiohttp wird für den Session-Cleanup benötigt
try:
    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

from telegram import BotCommand, Update
from telegram.ext import Application
from telegram.request import HTTPXRequest

from config import Config, get_config
from logger import setup_enhanced_logging, get_module_logger, EnhancedLogger

# Import der RichMenuSystem Komponenten
from handlers.menu.rich_menu_handler import RichMenuHandler

# ====== ERROR HANDLER IMPORT ======
from handlers.enhanced_error_handler import (
    EnhancedErrorHandler,
    create_enhanced_error_handler,
    ErrorHandlerAdminInterface,
)


class ExtendedBot:
    """Erweiterte Bot-Klasse mit RichMenuSystem und Error Handler"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = self._setup_logger()
        self.application: Optional[Application] = None
        self.rich_menu_handler: Optional[RichMenuHandler] = None

        # ====== ERROR HANDLER ======
        self.error_handler: Optional[EnhancedErrorHandler] = None
        self.error_admin_interface: Optional[ErrorHandlerAdminInterface] = None

        self._cleanup_task = None
        self._shutdown_event = asyncio.Event()

    def _setup_logger(self) -> EnhancedLogger:
        """Konfiguriert den erweiterten Logger"""
        log_file = getattr(self.config, "LOG_FILE", "logs/bot.log")
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        setup_enhanced_logging(
            log_file=str(log_file),
            level=getattr(self.config, "LOG_LEVEL", "INFO"),
            use_colors=True,
            use_emojis=True,
        )
        return get_module_logger("telegram_bot")

    def initialize(self) -> None:
        """Initialisiert alle Handler und Systeme (synchron)"""
        self.logger.info("🎛️ Initialisiere Bot mit RichMenuSystem & Error Handler...")

        # ====== 1. TELEGRAM APPLICATION ERSTELLEN ======
        request = HTTPXRequest(
            connection_pool_size=8,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=10,
        )
        self.application = (
            Application.builder().token(self.config.BOT_TOKEN).request(request).build()
        )
        self.logger.info("✅ Telegram Application erstellt")

        # ====== 2. ERROR HANDLER ZUERST ERSTELLEN ======
        try:
            # WICHTIG: create_enhanced_error_handler erwartet KEINE logger_factory!
            # Es verwendet intern get_module_logger
            self.error_handler = create_enhanced_error_handler(self.config)
            self.logger.info("✅ Enhanced Error Handler erstellt")
        except Exception as e:
            self.logger.critical(
                f"❌ FATAL: Error Handler konnte nicht erstellt werden: {e}",
                exc_info=True,
            )
            raise

        # ====== 3. ERROR HANDLER BEI TELEGRAM REGISTRIEREN ======
        self.application.add_error_handler(self.error_handler.handle_telegram_error)
        self.logger.info("✅ Telegram Error Handler registriert")

        # ====== 4. RICH MENU HANDLER ERSTELLEN ======
        try:
            # RichMenuHandler erwartet KEINE logger_factory!
            # Es verwendet intern get_module_logger
            self.rich_menu_handler = RichMenuHandler(self.config)
            self.logger.info("✅ RichMenuHandler erstellt")
        except Exception as e:
            self.logger.critical(
                f"❌ FATALER FEHLER: RichMenuHandler konnte nicht erstellt werden: {e}",
                exc_info=True,
            )
            raise

        # ====== 5. RICH MENU HANDLER INITIALISIEREN ======
        try:
            self.rich_menu_handler.initialize()
            self.logger.info("✅ RichMenuHandler initialisiert")
        except Exception as e:
            self.logger.critical(
                f"❌ FATAL: RichMenuHandler Initialisierung fehlgeschlagen: {e}",
                exc_info=True,
            )
            raise

        # ====== 6. ALLE HANDLER BEI TELEGRAM REGISTRIEREN ======
        try:
            telegram_handlers = self.rich_menu_handler.get_telegram_handlers()
            for handler in telegram_handlers:
                self.application.add_handler(handler)

            self.logger.info(f"✅ {len(telegram_handlers)} Handler registriert")
        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Registrieren der Handler: {e}", exc_info=True
            )
            raise

        # ====== 7. ADMIN COMMANDS FÜR ERROR MONITORING ======
        if hasattr(self.config, "ADMIN_USER_IDS") and self.config.ADMIN_USER_IDS:
            try:
                self.error_admin_interface = ErrorHandlerAdminInterface(
                    self.error_handler, self.config.ADMIN_USER_IDS
                )
                self.error_admin_interface.register_admin_commands(self.application)
                self.logger.info("✅ Error Handler Admin Commands registriert")

                if self.rich_menu_handler:
                    self.rich_menu_handler.set_error_admin_interface(
                        self.error_admin_interface
                    )
                    self.logger.info(
                        "✅ Error Admin Interface an RichMenuHandler übergeben"
                    )

            except Exception as e:
                self.logger.warning(
                    f"⚠️ Admin Commands konnten nicht registriert werden: {e}"
                )

        self.logger.info("✅ Bot-Komponenten vollständig initialisiert")

    async def _setup_bot_commands(self):
        """Setzt Bot-Commands im Telegram-Menü"""
        commands = [
            BotCommand("start", "🤖 Bot starten"),
            BotCommand("menu", "📱 Hauptmenü öffnen"),
            BotCommand("help", "ℹ️ Hilfe anzeigen"),
            BotCommand("status", "📊 Bot-Status"),
        ]

        # ====== ADMIN COMMANDS HINZUFÜGEN ======
        if hasattr(self.config, "ADMIN_USER_IDS"):
            commands.extend(
                [
                    BotCommand("error_stats", "📊 Error-Statistiken (Admin)"),
                    BotCommand("error_report", "📋 Error-Bericht (Admin)"),
                ]
            )

        if self.application and self.application.bot:
            await self.application.bot.set_my_commands(commands)
            self.logger.info("✅ Bot-Befehle im Menü gesetzt")

    async def _periodic_cleanup(self):
        """Führt periodische Cleanup-Aufgaben aus"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(300)  # Alle 5 Minuten

                if self._shutdown_event.is_set():
                    break

                # RichMenuHandler Cleanup
                if self.rich_menu_handler:
                    try:
                        self.rich_menu_handler.cleanup()
                        self.logger.debug("🧹 RichMenuHandler cleanup durchgeführt")
                    except Exception as e:
                        self.logger.error(f"❌ Cleanup-Fehler: {e}")

                # ====== ERROR HANDLER CLEANUP ======
                if self.error_handler:
                    try:
                        self.error_handler.cleanup_old_data(max_age_hours=24)
                        self.logger.debug("🧹 Error Handler cleanup durchgeführt")
                    except Exception as e:
                        self.logger.error(f"❌ Error Handler Cleanup-Fehler: {e}")

        except asyncio.CancelledError:
            self.logger.debug("Cleanup-Task wurde beendet")
            raise

    async def start_polling(self):
        """
        Startet den Bot im Polling-Modus mit korrekter Event-Loop-Verwaltung.
        """
        if not self.application:
            self.logger.error("❌ Application nicht initialisiert")
            raise RuntimeError("Application nicht initialisiert")

        self.logger.info("🚀 Starte Telegram Bot Polling (Ctrl+C zum Beenden)...")

        try:
            # 1. Application initialisieren
            await self.application.initialize()
            await self.application.start()
            self.logger.debug("✅ Application initialisiert und gestartet")

            # 2. Bot-Commands setzen
            await self._setup_bot_commands()

            # 3. Periodic Cleanup Task starten
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self.logger.debug("✅ Cleanup-Task gestartet")

            # 4. Statistik-Hintergrund-Polling starten (falls verfügbar)
            if (
                self.rich_menu_handler
                and self.rich_menu_handler.stats_handler
                and hasattr(self.rich_menu_handler.stats_handler, "statistik_service")
            ):

                try:
                    self.rich_menu_handler.stats_handler.statistik_service.start_polling()
                    self.logger.info(
                        "📊✅ Statistik-History-Polling erfolgreich gestartet"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Fehler beim Starten des Statistik-Pollings: {e}"
                    )
            else:
                self.logger.warning(
                    "⚠️ Statistik-Handler nicht verfügbar. History-Polling ist DEAKTIVIERT."
                )

            # 5. Updater starten (falls vorhanden)
            if self.application.updater:
                await self.application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                self.logger.info("✅ Bot läuft und lauscht auf Nachrichten...")
            else:
                self.logger.error("❌ Kein Updater verfügbar")
                raise RuntimeError("Application.updater nicht verfügbar")

            # 6. Warten auf Shutdown-Signal
            await self._shutdown_event.wait()

        except asyncio.CancelledError:
            self.logger.info("🛑 Bot-Polling durch CancelledError gestoppt")
        except Exception as e:
            self.logger.error(f"❌ Fehler während Bot-Polling: {e}", exc_info=True)
            raise
        finally:
            # Cleanup durchführen
            await self._cleanup()

    async def _async_cleanup_components(self):
        """
        Schließt alle Komponenten, die asynchrone Ressourcen halten (z.B. aiohttp-Sessions).
        """
        # ── EnhancedMetadataProcessor: async-fähiger Cleanup ────────────────
        if self.rich_menu_handler:
            try:
                proc = getattr(self.rich_menu_handler, "metadata_processor", None)
                if proc:
                    genius = getattr(proc, "genius_client", None)
                    if genius:
                        if hasattr(
                            genius, "async_close"
                        ) and asyncio.iscoroutinefunction(genius.async_close):
                            await genius.async_close()
                            self.logger.debug(
                                "✅ GeniusClient async_close() aufgerufen"
                            )
                        elif hasattr(genius, "_session"):
                            session = genius._session
                            if session and not session.closed:
                                await session.close()
                                self.logger.debug(
                                    "✅ GeniusClient._session direkt geschlossen"
                                )
                        if hasattr(genius, "close"):
                            genius.close()
            except Exception as e:
                self.logger.debug(f"ℹ️ Async-Cleanup der Komponenten: {e}")

        # ── Sicherheitsnetz: Alle verbleibenden aiohttp-Sessions via gc schließen ──
        if _AIOHTTP_AVAILABLE:
            try:
                geschlossen = 0
                for obj in gc.get_objects():
                    if isinstance(obj, aiohttp.ClientSession) and not obj.closed:
                        await obj.close()
                        geschlossen += 1
                if geschlossen:
                    self.logger.debug(
                        f"✅ {geschlossen} verbleibende aiohttp-Session(s) via gc geschlossen"
                    )
            except Exception as e:
                self.logger.debug(f"ℹ️ aiohttp gc-Cleanup: {e}")

            await asyncio.sleep(0.25)

    async def _cleanup(self):
        """Führt vollständiges Cleanup durch"""
        self.logger.info("🧹 Starte Cleanup-Prozess...")

        self._shutdown_event.set()

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self.logger.debug("✅ Cleanup-Task gestoppt")

        # Statistik-Polling stoppen
        if (
            self.rich_menu_handler
            and self.rich_menu_handler.stats_handler
            and hasattr(self.rich_menu_handler.stats_handler, "statistik_service")
        ):

            try:
                await self.rich_menu_handler.stats_handler.statistik_service.stop_polling()
                self.logger.info("📊✅ Statistik-History-Polling gestoppt")
            except Exception as e:
                self.logger.error(f"❌ Fehler beim Stoppen des Statistik-Pollings: {e}")

        # ====== ERROR HANDLER CLEANUP ======
        if self.error_handler:
            try:
                stats = self.error_handler.get_comprehensive_statistics()
                self.logger.info(
                    f"📊 Error Handler Stats: "
                    f"{stats['exception_monitor']['total_exceptions']} Exceptions, "
                    f"Recovery Rate: {stats['performance']['recovery_success_rate']:.1%}"
                )

                self.error_handler.cleanup_old_data(max_age_hours=0)
                self.logger.info("✅ Error Handler cleanup abgeschlossen")
            except Exception as e:
                self.logger.error(f"❌ Error Handler cleanup Fehler: {e}")

        # RichMenuHandler cleanup
        if self.rich_menu_handler:
            try:
                self.rich_menu_handler.cleanup()
                self.logger.info("✅ RichMenuHandler cleanup abgeschlossen")
            except Exception as e:
                self.logger.error(
                    f"❌ Fehler bei RichMenuHandler cleanup: {e}", exc_info=True
                )

        # Application stoppen
        if self.application:
            try:
                if self.application.updater:
                    await self.application.updater.stop()
                    self.logger.debug("✅ Updater gestoppt")

                await self.application.stop()
                self.logger.debug("✅ Application gestoppt")

                await self.application.shutdown()
                self.logger.debug("✅ Application heruntergefahren")

            except Exception as e:
                self.logger.warning(f"⚠️ Fehler beim Application-Cleanup: {e}")

        await self._async_cleanup_components()

        self.logger.info("✅ Cleanup abgeschlossen")

    async def stop(self):
        """Stoppt den Bot ordnungsgemäß"""
        self.logger.info("🛑 Stop-Signal empfangen")
        self._shutdown_event.set()


# ========================================
# SIGNAL HANDLING
# ========================================


def setup_signal_handlers(bot: ExtendedBot):
    """Richtet Signal-Handler für sauberes Shutdown ein"""

    def signal_handler(signum, frame):
        logger = get_module_logger("signal_handler")
        signal_name = signal.Signals(signum).name
        logger.info(f"🛑 Signal {signal_name} empfangen, starte Shutdown...")

        if bot._shutdown_event:
            bot._shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


# ========================================
# ENTRY POINT
# ========================================


async def async_main():
    """Asynchroner Hauptprozess"""
    print("=" * 60)
    print("🎵 Telegram Musik-Bot mit RichMenuSystem & Error Handler wird gestartet...")
    print("=" * 60)

    # Konfiguration laden
    try:
        config = get_config()
        setup_enhanced_logging(
            log_file="logs/bot.log",
            level=getattr(config, "LOG_LEVEL", "INFO"),
            use_colors=True,
            use_emojis=True,
        )
        logger = get_module_logger("main")
        logger.info("✅ Konfiguration erfolgreich geladen")
    except Exception as e:
        print(f"❌ Konfigurationsfehler: {e}")
        sys.exit(1)

    bot_runner = ExtendedBot(config)
    setup_signal_handlers(bot_runner)

    try:
        bot_runner.initialize()
        logger.info("✅ Bot initialisiert")
        await bot_runner.start_polling()

    except KeyboardInterrupt:
        logger.info("🛑 KeyboardInterrupt empfangen")
    except Exception as e:
        logger.error(f"💥 Unerwarteter Fehler: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
    finally:
        logger.info("👋 Bot wird beendet...")

        if _AIOHTTP_AVAILABLE:
            try:
                for obj in gc.get_objects():
                    if isinstance(obj, aiohttp.ClientSession) and not obj.closed:
                        await obj.close()
                await asyncio.sleep(0.1)
            except Exception:
                pass


def main():
    """Synchroner Einstiegspunkt"""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n👋 Bot wurde manuell beendet")
    except Exception as e:
        print(f"💥 Kritischer Fehler: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
