# handlers/error_handler.py
# -*- coding: utf-8 -*-
"""
🚨 DEDICATED ERROR HANDLER
Zentrales Error Handling für Telegram Bot mit detailliertem Logging und Recovery
"""

import traceback
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError, NetworkError, TimedOut, BadRequest

from config import Config
from logger import get_module_logger


class BotErrorHandler:
    """Zentraler Error Handler für alle Bot-Operationen"""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("BotErrorHandler")

        # Debug-Modus
        self.debug_mode = getattr(config, "DEBUG_MODE", False)
        self.log_traceback = getattr(config, "LOG_TRACEBACK", True)

        # Error-Statistiken
        self.error_stats = {
            "total_errors": 0,
            "network_errors": 0,
            "parsing_errors": 0,
            "timeout_errors": 0,
            "bad_request_errors": 0,
            "unknown_errors": 0,
            "last_error_time": None,
            "error_types": {},
        }

        # Error-Recovery Strategien
        self.recovery_attempts = {}
        self.max_recovery_attempts = 3

        # Benutzer-Nachricht Templates
        self.error_messages = {
            "generic": "❌ Es ist ein Fehler aufgetreten. Bitte versuche es erneut.",
            "network": "🌐 Verbindungsproblem. Versuche es in einem Moment erneut.",
            "timeout": "⏱️ Zeitüberschreitung. Bitte versuche es erneut.",
            "parsing": "📝 Nachrichtenformat-Fehler. Bitte versuche es erneut.",
            "bad_request": "❌ Ungültige Anfrage. Überprüfe deine Eingabe.",
            "rate_limit": "⏳ Zu viele Anfragen. Warte einen Moment.",
            "file_error": "📁 Dateifehler. Versuche es mit einer anderen Datei.",
            "permission_error": "🔒 Keine Berechtigung für diese Aktion.",
        }

        self.logger.info("🚨 Error-Handler initialisiert")

    async def handle_error(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Hauptmethode für Error Handling"""
        self.error_stats["total_errors"] += 1
        self.error_stats["last_error_time"] = datetime.now().isoformat()

        error = context.error
        error_type = type(error).__name__

        # Statistiken aktualisieren
        if error_type in self.error_stats["error_types"]:
            self.error_stats["error_types"][error_type] += 1
        else:
            self.error_stats["error_types"][error_type] = 1

        # Error-Details sammeln
        error_details = await self._collect_error_details(update, context, error)

        # Error klassifizieren und behandeln
        error_category = self._classify_error(error)
        self.logger.error(
            f"🚨 {error_category.upper()}-Fehler: {error_type} - {str(error)}"
        )

        # Detailliertes Logging
        if self.debug_mode or self.log_traceback:
            await self._log_detailed_error(error_details)

        # Recovery versuchen
        recovery_success = await self._attempt_recovery(update, context, error_category)

        # Benutzer benachrichtigen
        await self._notify_user(update, error_category, recovery_success)

        # Error für kritische Überwachung weiterleiten
        await self._handle_critical_errors(error_details)

    async def _collect_error_details(
        self, update: object, context: ContextTypes.DEFAULT_TYPE, error: Exception
    ) -> Dict[str, Any]:
        """Sammelt detaillierte Error-Informationen"""
        details = {
            "timestamp": datetime.now().isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "update_type": type(update).__name__ if update else "Unknown",
            "user_id": None,
            "chat_id": None,
            "message_text": None,
            "callback_data": None,
            "traceback": None,
        }

        # Traceback sammeln
        if self.log_traceback:
            details["traceback"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )

        # Update-spezifische Details
        if isinstance(update, Update):
            if update.effective_user:
                details["user_id"] = update.effective_user.id
                details["username"] = update.effective_user.username

            if update.effective_chat:
                details["chat_id"] = update.effective_chat.id
                details["chat_type"] = update.effective_chat.type

            if update.message:
                details["message_text"] = (
                    update.message.text[:100] if update.message.text else None
                )
                details["message_date"] = (
                    update.message.date.isoformat() if update.message.date else None
                )

            if update.callback_query:
                details["callback_data"] = update.callback_query.data

        # Context-Details
        if hasattr(context, "user_data") and context.user_data:
            details["user_data_keys"] = list(context.user_data.keys())

        if hasattr(context, "chat_data") and context.chat_data:
            details["chat_data_keys"] = list(context.chat_data.keys())

        return details

    def _classify_error(self, error: Exception) -> str:
        """Klassifiziert Fehler nach Typ"""
        if isinstance(error, NetworkError):
            self.error_stats["network_errors"] += 1
            return "network"
        elif isinstance(error, TimedOut):
            self.error_stats["timeout_errors"] += 1
            return "timeout"
        elif isinstance(error, BadRequest):
            self.error_stats["bad_request_errors"] += 1
            if "can't parse entities" in str(error).lower():
                self.error_stats["parsing_errors"] += 1
                return "parsing"
            elif "file not found" in str(error).lower():
                return "file_error"
            elif "forbidden" in str(error).lower():
                return "permission_error"
            elif "too many requests" in str(error).lower():
                return "rate_limit"
            else:
                return "bad_request"
        else:
            self.error_stats["unknown_errors"] += 1
            return "unknown"

    async def _log_detailed_error(self, error_details: Dict[str, Any]) -> None:
        """Loggt detaillierte Error-Informationen"""
        self.logger.error("=" * 80)
        self.logger.error("🔍 DETAILLIERTE ERROR-ANALYSE")
        self.logger.error("=" * 80)

        for key, value in error_details.items():
            if key == "traceback" and value:
                self.logger.error(f"📋 {key.upper()}:\n{value}")
            elif value is not None:
                self.logger.error(f"📌 {key.upper()}: {value}")

        self.logger.error("=" * 80)

    async def _attempt_recovery(
        self, update: object, context: ContextTypes.DEFAULT_TYPE, error_category: str
    ) -> bool:
        """Versucht automatische Recovery"""
        if not isinstance(update, Update):
            return False

        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return False

        # Recovery-Versuche verfolgen
        recovery_key = f"{user_id}_{error_category}"
        attempts = self.recovery_attempts.get(recovery_key, 0)

        if attempts >= self.max_recovery_attempts:
            self.logger.warning(f"⚠️ Max Recovery-Versuche erreicht für {recovery_key}")
            return False

        self.recovery_attempts[recovery_key] = attempts + 1

        try:
            if error_category == "parsing":
                # Markdown-Parsing-Fehler: Fallback auf Plain Text
                return await self._recover_parsing_error(update, context)
            elif error_category == "network":
                # Netzwerk-Fehler: Retry nach kurzer Pause
                return await self._recover_network_error(update, context)
            elif error_category == "timeout":
                # Timeout: Simplified Response
                return await self._recover_timeout_error(update, context)
            else:
                return False

        except Exception as recovery_error:
            self.logger.error(f"❌ Recovery fehlgeschlagen: {recovery_error}")
            return False

    async def _recover_parsing_error(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Recovery für Markdown-Parsing-Fehler"""
        self.logger.info("🔧 Versuche Recovery für Parsing-Fehler...")

        try:
            fallback_message = "ℹ️ Nachricht wurde vereinfacht dargestellt. Verwende /menu für Navigation."

            if update.callback_query:
                await update.callback_query.edit_message_text(fallback_message)
            else:
                await update.effective_message.reply_text(fallback_message)

            self.logger.info("✅ Parsing-Error Recovery erfolgreich")
            return True
        except Exception:
            return False

    async def _recover_network_error(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Recovery für Netzwerk-Fehler"""
        self.logger.info("🔧 Versuche Recovery für Netzwerk-Fehler...")

        try:
            import asyncio

            await asyncio.sleep(1)  # Kurze Pause

            retry_message = "🔄 Verbindung wiederhergestellt. Bitte versuche es erneut."

            if update.callback_query:
                await update.callback_query.answer(retry_message)
            else:
                await update.effective_message.reply_text(retry_message)

            self.logger.info("✅ Network-Error Recovery erfolgreich")
            return True
        except Exception:
            return False

    async def _recover_timeout_error(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Recovery für Timeout-Fehler"""
        self.logger.info("🔧 Versuche Recovery für Timeout-Fehler...")

        try:
            timeout_message = (
                "⏱️ Vorgang dauerte zu lange. Verwende einfachere Befehle."
            )

            if update.callback_query:
                await update.callback_query.answer(timeout_message)
            else:
                await update.effective_message.reply_text(timeout_message)

            self.logger.info("✅ Timeout-Error Recovery erfolgreich")
            return True
        except Exception:
            return False

    async def _notify_user(
        self, update: object, error_category: str, recovery_success: bool
    ) -> None:
        """Benachrichtigt Benutzer über Fehler"""
        if not isinstance(update, Update) or not update.effective_message:
            return

        # Recovery-Info hinzufügen
        if recovery_success:
            return  # Recovery hat bereits Nachricht gesendet

        # Standard Error-Nachricht basierend auf Kategorie
        error_msg = self.error_messages.get(
            error_category, self.error_messages["generic"]
        )

        # Zusätzliche Hilfe je nach Error-Typ
        if error_category == "parsing":
            error_msg += "\n\nTipp: Verwende die Buttons statt Text-Eingaben."
        elif error_category == "network":
            error_msg += "\n\nÜberprüfe deine Internetverbindung."
        elif error_category == "rate_limit":
            error_msg += "\n\nWarte 30 Sekunden bevor du es erneut versuchst."

        try:
            if update.callback_query:
                await update.callback_query.answer("❌ Fehler aufgetreten")
                try:
                    await update.callback_query.edit_message_text(error_msg)
                except:
                    await update.effective_message.reply_text(error_msg)
            else:
                await update.effective_message.reply_text(error_msg)
        except Exception as notification_error:
            self.logger.error(
                f"❌ Konnte Benutzer nicht benachrichtigen: {notification_error}"
            )

    async def _handle_critical_errors(self, error_details: Dict[str, Any]) -> None:
        """Behandelt kritische Fehler die Admin-Attention benötigen"""
        critical_errors = [
            "PermissionError",
            "DatabaseError",
            "ConfigurationError",
            "SecurityError",
        ]

        if error_details["error_type"] in critical_errors:
            self.logger.critical(f"🚨 KRITISCHER FEHLER: {error_details['error_type']}")

            # Hier könnte eine Admin-Benachrichtigung implementiert werden
            await self._notify_admin_if_configured(error_details)

        # Häufige Fehler erkennen
        error_type = error_details["error_type"]
        if error_type in self.error_stats["error_types"]:
            count = self.error_stats["error_types"][error_type]
            if count > 10:  # Mehr als 10 Fehler desselben Typs
                self.logger.warning(
                    f"⚠️ Häufiger Fehler erkannt: {error_type} ({count}x)"
                )

    async def _notify_admin_if_configured(self, error_details: Dict[str, Any]) -> None:
        """Benachrichtigt Admin bei kritischen Fehlern (falls konfiguriert)"""
        if hasattr(self.config, "ADMIN_CHAT_ID") and self.config.ADMIN_CHAT_ID:
            # Implementation für Admin-Benachrichtigung
            # Dies würde eine Telegram-Nachricht an den Admin senden
            pass

    def get_error_statistics(self) -> Dict[str, Any]:
        """Gibt aktuelle Error-Statistiken zurück"""
        return {
            **self.error_stats,
            "recovery_attempts": len(self.recovery_attempts),
            "active_recovery_keys": list(self.recovery_attempts.keys()),
        }

    def reset_error_statistics(self) -> None:
        """Setzt Error-Statistiken zurück"""
        self.logger.info("📊 Error-Statistiken zurückgesetzt")
        self.error_stats = {
            "total_errors": 0,
            "network_errors": 0,
            "parsing_errors": 0,
            "timeout_errors": 0,
            "bad_request_errors": 0,
            "unknown_errors": 0,
            "last_error_time": None,
            "error_types": {},
        }
        self.recovery_attempts.clear()

    def reset_recovery_attempts(self, user_id: Optional[int] = None) -> None:
        """Setzt Recovery-Versuche zurück"""
        if user_id:
            keys_to_remove = [
                key
                for key in self.recovery_attempts.keys()
                if key.startswith(str(user_id))
            ]
            for key in keys_to_remove:
                del self.recovery_attempts[key]
            self.logger.info(f"🔄 Recovery-Versuche für User {user_id} zurückgesetzt")
        else:
            self.recovery_attempts.clear()
            self.logger.info("🔄 Alle Recovery-Versuche zurückgesetzt")

    async def log_custom_error(
        self, error_message: str, error_context: Dict[str, Any] = None
    ) -> None:
        """Loggt benutzerdefinierte Fehler"""
        self.logger.error(f"🔧 Custom Error: {error_message}")
        if error_context:
            for key, value in error_context.items():
                self.logger.error(f"   📌 {key}: {value}")


# Factory Function
def create_error_handler(
    config: Config, logger_factory: Callable = None
) -> BotErrorHandler:
    """Erstellt Error Handler Instanz"""
    return BotErrorHandler(config, logger_factory)
