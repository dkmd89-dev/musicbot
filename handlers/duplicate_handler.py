# yt_music_bot/handlers/duplicate_handler.py
# -*- coding: utf-8 -*-
"""
EnhancedDuplicateHandler – Telegram-Präsentationsschicht für die
Duplicate-Detection.

ARCH-018 Phase 2 (docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md):
der fachliche Kern (Duplicate-Detection-Kaskade, Cache, Registrierung,
Statistik-Berechnung) wurde nach services/duplicate/ extrahiert
(DuplicateCache, DuplicateDetector) - Abschnitt 6 der Characterization.
Diese Klasse hält seither eine injizierte DuplicateDetector-Instanz und
enthält ausschließlich noch Telegram-Präsentationslogik (Menüs,
Bestätigungsdialoge, Callback-Handling). Verhalten unverändert
gegenüber dem Ausgangszustand.
"""


from pathlib import Path
from typing import Optional, Callable
from typing import TYPE_CHECKING

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler
from services.duplicate.detector import DuplicateDetector


class EnhancedDuplicateHandler:
    def __init__(
        self,
        config: Config,
        detector: DuplicateDetector,
        logger_factory: Optional[Callable] = None,
    ):
        # Logger mit Dependency Injection
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("EnhancedDuplicateHandler")

        self.config = config
        self.detector = detector

        self.error_handler: "Optional[EnhancedErrorHandler]" = None

        self.logger.info("🔍 EnhancedDuplicateHandler initialisiert")

    def _get_default_config(self):
        class FallbackConfig:
            DUPLICATE_CACHE_DIR = "duplicate_cache"
            LIBRARY_DIR = Path("./music_library")

        return FallbackConfig()

    async def show_statistics_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Zeigt das Duplikat-Statistik-Menü via Callback.
        Ersetzt die Logik von `find_duplicates`.
        """
        query = update.callback_query
        try:
            stats = self.detector.get_statistics()

            # Fallback für total_checks=0, um DivisionByZero zu vermeiden
            total_checks = max(stats.get("total_checks", 0), 1)
            duplicates_found = stats.get("url_duplicates_found", 0) + stats.get(
                "content_duplicates_found", 0
            )
            duplicates_skipped = stats.get("duplicates_skipped", 0)

            # Sicherstellen, dass Raten berechnet werden können
            duplicate_rate = (
                (duplicates_found / total_checks) * 100 if total_checks > 0 else 0
            )
            savings_percentage = (
                (duplicates_skipped / total_checks) * 100 if total_checks > 0 else 0
            )

            response = (
                "♻️ **Duplikat-Statistiken**\n\n"
                f"📊 Gesamte Prüfungen: {stats.get('total_checks', 0)}\n"
                f"🔗 URL-Duplikate: {stats.get('url_duplicates_found', 0)}\n"
                f"🎵 Content-Duplikate: {stats.get('content_duplicates_found', 0)}\n"
                f"📝 Neue Einträge: {stats.get('new_entries_added', 0)}\n"
                f"🚫 Übersprungen: {duplicates_skipped}\n"
                f"💾 URL-Cache: {stats.get('url_cache_size', 0)}\n"
                f"💾 Content-Cache: {stats.get('content_cache_size', 0)}\n"
                f"📈 Duplikat-Rate: {duplicate_rate:.1f}%\n"
                f"💰 Einsparungen: {savings_percentage:.1f}%"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    # Zurück zum Duplikat-Menü, nicht zum Admin-Hauptmenü
                    [
                        InlineKeyboardButton(
                            "⬅️ Zurück", callback_data="menu:admin_duplicates"
                        )
                    ]
                ]
            )

            await query.edit_message_text(
                response, reply_markup=keyboard, parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(f"❌ Fehler bei Duplikat-Statistik: {e}", exc_info=True)
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "duplicate_statistics_menu", e
                )
            else:
                await query.edit_message_text(
                    f"❌ Fehler beim Laden der Duplikat-Statistiken: {e}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Zurück", callback_data="menu:admin_duplicates"
                                )
                            ]
                        ]
                    ),
                )

    async def show_clear_cache_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Zeigt Bestätigungs-Dialog für das Leeren des Duplikat-Cache."""
        query = update.callback_query

        text = """⚠️ **Duplikat-Cache leeren**

Bist du sicher, dass du den gesamten Duplikat-Cache (URLs und Content) löschen möchtest?

Diese Aktion kann nicht rückgängig gemacht werden!"""

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, Cache leeren",
                        callback_data="dup:clear_cache_execute",  # Aktion ausführen
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Abbrechen",
                        callback_data="menu:admin_duplicates",  # Zurück zum Menü
                    ),
                ],
            ]
        )

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def execute_clear_cache(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Führt das Leeren des Cache durch.
        Ersetzt die Logik von `clear_duplicate_cache`.
        """
        query = update.callback_query
        try:
            stats_before = self.detector.get_statistics()

            deleted_files = []
            for file_path in [
                self.detector.duplicate_cache.url_cache_file,
                self.detector.duplicate_cache.content_cache_file,
            ]:
                if file_path.exists():
                    file_path.unlink()
                    deleted_files.append(file_path.name)

            # Caches im Speicher leeren
            self.detector.duplicate_cache.url_cache = {}
            self.detector.duplicate_cache.content_cache = {}

            # Statistiken im Speicher zurücksetzen
            self.detector.stats = {
                "url_duplicates_found": 0,
                "content_duplicates_found": 0,
                "new_entries_added": 0,
                "total_checks": 0,
                "duplicates_skipped": 0,
            }
            # Cache-Objekt neu laden (oder leeren)
            from services.duplicate.cache import DuplicateCache

            self.detector.duplicate_cache = DuplicateCache(
                cache_dir=str(self.detector.duplicate_cache.cache_path),
                logger=self.logger_factory("DuplicateCache"),
            )

            response = (
                "✅ **Cache geleert**\n\n"
                "Der Duplikat-Cache wurde erfolgreich zurückgesetzt.\n\n"
                f"Gelöschte Einträge:\n"
                f"• URL-Cache: {stats_before.get('url_cache_size', 0)}\n"
                f"• Content-Cache: {stats_before.get('content_cache_size', 0)}\n"
                f"• Dateien: {', '.join(deleted_files) if deleted_files else 'Keine'}"
            )
            self.logger.info(f"🧹 Duplikat-Cache durch Admin geleert: {deleted_files}")

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Zurück", callback_data="menu:admin_duplicates"
                        )
                    ]
                ]
            )

            await query.edit_message_text(
                response, reply_markup=keyboard, parse_mode="Markdown"
            )
        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Löschen des Duplikat-Cache: {e}", exc_info=True
            )
            if self.error_handler:
                await self.error_handler.handle_callback_error(
                    update, context, "duplicate_clear_cache", e
                )
            else:
                await query.edit_message_text(
                    f"❌ Fehler beim Löschen des Duplikat-Cache: {e}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Zurück", callback_data="menu:admin_duplicates"
                                )
                            ]
                        ]
                    ),
                )


async def find_duplicates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram-Handler für Duplikat-Suche (Kompatibilität)"""
    logger = get_module_logger("DuplicateHandler_Telegram")
    try:
        # Konfiguration aus dem Context holen oder Standardkonfig verwenden
        config = (
            context.bot_data.get("config")
            or EnhancedDuplicateHandler()._get_default_config()
        )
        detector = DuplicateDetector(config=config, logger_factory=get_module_logger)
        duplicate_handler = EnhancedDuplicateHandler(
            config=config, detector=detector, logger_factory=get_module_logger
        )
        stats = duplicate_handler.detector.get_statistics()
        response = (
            "🔍 **Duplikat-Erkennungsstatistiken:**\n\n"
            f"📊 Gesamte Prüfungen: {stats['total_checks']}\n"
            f"🔗 URL-Duplikate gefunden: {stats['url_duplicates_found']}\n"
            f"🎵 Content-Duplikate gefunden: {stats['content_duplicates_found']}\n"
            f"📝 Neue Einträge hinzugefügt: {stats['new_entries_added']}\n"
            f"🚫 Übersprungene Downloads: {stats['duplicates_skipped']}\n"
            f"💾 URL-Cache-Größe: {stats['url_cache_size']}\n"
            f"💾 Content-Cache-Größe: {stats['content_cache_size']}\n"
            f"📈 Duplikat-Rate: {stats['duplicate_rate']:.1f}%\n"
            f"💰 Einsparungen: {stats['savings_percentage']:.1f}%"
        )
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ Fehler bei Duplikat-Suche: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Fehler bei der Duplikat-Analyse. Siehe Logs für Details."
        )


async def clear_duplicate_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram-Handler zum Löschen des Duplikat-Cache (Kompatibilität)"""
    logger = get_module_logger("DuplicateHandler_Telegram")
    try:
        # Konfiguration aus dem Context holen oder Standardkonfig verwenden
        config = (
            context.bot_data.get("config")
            or EnhancedDuplicateHandler()._get_default_config()
        )
        detector = DuplicateDetector(config=config, logger_factory=get_module_logger)
        duplicate_handler = EnhancedDuplicateHandler(
            config=config, detector=detector, logger_factory=get_module_logger
        )
        stats_before = duplicate_handler.detector.get_statistics()
        deleted_files = []
        for file_path in [
            duplicate_handler.detector.duplicate_cache.url_cache_file,
            duplicate_handler.detector.duplicate_cache.content_cache_file,
        ]:
            if file_path.exists():
                file_path.unlink()
                deleted_files.append(file_path.name)

        duplicate_handler.detector.duplicate_cache.url_cache = {}
        duplicate_handler.detector.duplicate_cache.content_cache = {}

        response = (
            "🧹 Duplikat-Cache erfolgreich geleert!\n\n"
            "Gelöschte Einträge:\n"
            f"• URL-Cache: {stats_before['url_cache_size']}\n"
            f"• Content-Cache: {stats_before['content_cache_size']}\n"
            f"• Dateien gelöscht: {', '.join(deleted_files) if deleted_files else 'Keine'}"
        )
        await update.message.reply_text(response)
        logger.info(f"🧹 Duplikat-Cache durch Benutzer geleert: {deleted_files}")
    except Exception as e:
        logger.error(f"❌ Fehler beim Löschen des Duplikat-Cache: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Fehler beim Löschen des Duplikat-Cache. Siehe Logs für Details."
        )
