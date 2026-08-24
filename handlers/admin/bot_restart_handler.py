# handlers/admin/bot_restart_handler.py
# -*- coding: utf-8 -*-
"""
🔄 BotRestartHandler – Bot-Neustart via systemd über Telegram-Button

Ermöglicht autorisierten Admins, den Bot-Service sauber über
`sudo systemctl restart bot` neu zu starten.

Voraussetzung (einmalig auf dem Server einrichten):
  sudo visudo
  # Folgende Zeile hinzufügen:
  robin ALL=(ALL) NOPASSWD: /bin/systemctl restart bot

CHANGELOG:
  - v1.0  (2025-07)  Erstellt: Confirmation-Dialog, Execute, Cancel
  - v1.1  (2026-04)  Fix: MarkdownV2 -> HTML (Escape-Probleme behoben)
  - v1.2  (2026-08)  POST-ARCH-009 P-1: systemctl-Prozesssteuerung nach
                      utils/bot_restart_trigger.py ausgelagert (siehe
                      docs/MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md)
"""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from logger import get_module_logger
from utils.bot_restart_trigger import BotRestartTrigger

# Name des systemd-Service (muss mit /etc/systemd/system/<NAME>.service übereinstimmen)
_SERVICE_NAME = "bot"

# Verzögerung in Sekunden, bevor systemctl aufgerufen wird.
# Gibt python-telegram-bot Zeit, die letzte Nachricht noch zu senden.
_PRE_RESTART_DELAY = 2.0


class BotRestartHandler:
    """
    Handler für den Bot-Neustart via systemd.

    Ablauf:
        1. Admin öffnet Admin-Menü → klickt „🔄 Bot neu starten"
        2. Bestätigungsdialog erscheint (Ja / Abbrechen)
        3. Bei Bestätigung:  Statusnachricht senden → kurz warten → restart
        4. Der systemd-Service startet den Prozess automatisch neu
    """

    def __init__(self, config, logger_factory=None):
        self.config = config
        self.logger = (logger_factory or get_module_logger)("BotRestartHandler")
        self.service_name = _SERVICE_NAME
        self.logger.info(
            "🔄 BotRestartHandler initialisiert (Service: %s)", self.service_name
        )

    # ------------------------------------------------------------------
    # Öffentliche Handler-Methoden (werden vom RichMenuSystem aufgerufen)
    # ------------------------------------------------------------------

    async def show_restart_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Zeigt den Bestätigungs-Dialog für den Bot-Neustart.
        Wird durch den Menü-Button „🔄 Bot neu starten" ausgelöst.
        """
        query = update.callback_query
        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        await query.answer()

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Ja, jetzt neu starten",
                        callback_data="restart:confirm",
                    ),
                    InlineKeyboardButton(
                        "❌ Abbrechen",
                        callback_data="restart:cancel",
                    ),
                ]
            ]
        )

        # Verwende HTML anstelle von MarkdownV2, um Escape-Probleme zu vermeiden
        await query.edit_message_text(
            "⚠️ <b>Bot neu starten</b>\n\n"
            f"Service: <code>{self.service_name}</code>\n\n"
            "• Alle aktiven Sessions werden beendet\n"
            "• Der Bot ist kurz (~5-10 Sek.) nicht erreichbar\n"
            "• Danach startet er automatisch neu\n\n"
            "<b>Wirklich jetzt neu starten?</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        self.logger.info("ℹ️ Restart-Bestätigung angezeigt für User %s", user_id)

    async def execute_restart(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Führt den Bot-Neustart aus, nachdem der Admin bestätigt hat.

        Reihenfolge:
          1. Berechtigungsprüfung
          2. Statusnachricht senden (Bot antwortet noch)
          3. Kurz warten (damit Telegram die Nachricht zustellt)
          4. systemctl restart aufrufen → Prozess wird beendet
        """
        query = update.callback_query
        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        await query.answer("🔄 Neustart wird eingeleitet …")

        self.logger.warning("🔄 Bot-Neustart angefordert von Admin User-ID %s", user_id)

        # Statusnachricht senden – diese erreicht den User noch vor dem Neustart
        await query.edit_message_text(
            "🔄 <b>Bot wird neu gestartet …</b>\n\n"
            "Bitte warte ca. 10 Sekunden.\n"
            "Danach ist der Bot wieder vollständig verfügbar.",
            parse_mode="HTML",
        )

        # Neustart in separatem Task, damit obige Nachricht gesendet werden kann
        asyncio.get_event_loop().call_later(
            _PRE_RESTART_DELAY,
            BotRestartTrigger.trigger_restart,
            self.service_name,
        )

    async def cancel_restart(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Bricht den Neustart ab und schließt den Bestätigungs-Dialog.
        """
        query = update.callback_query
        user_id = update.effective_user.id

        await query.answer("✅ Neustart abgebrochen")

        await query.edit_message_text(
            "✅ <b>Neustart abgebrochen</b>\n\n" "Der Bot läuft weiterhin normal.",
            parse_mode="HTML",
        )
        self.logger.info("ℹ️ Neustart abgebrochen von User %s", user_id)

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _is_admin(self, user_id: int) -> bool:
        """Prüft, ob der User Admin- oder Owner-Rechte hat."""
        if user_id == getattr(self.config, "OWNER_USER_ID", None):
            return True
        return user_id in getattr(self.config, "ADMIN_USER_IDS", [])
