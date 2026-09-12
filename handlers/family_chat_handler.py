# handlers/family_chat_handler.py
# -*- coding: utf-8 -*-
"""
FamilyChatHandler – Telegram-Präsentation für den Familien-Chat
(Phase F3, Family Hub).

Verantwortlichkeit (Single Responsibility, siehe CLAUDE.md Abschnitt 4):
  - Ausschließlich Telegram-Präsentation (Nachrichtenversand, Formatierung,
    Verteilung neuer Nachrichten über context.bot).
  - Berechtigungsprüfung + Persistenz delegiert an FamilyChatService/
    FamilyService - KEINE Fachlogik hier.

"📝 Nachricht senden" ist ein Zwei-Schritt-Ablauf (Klick -> Freitext).
Bewusst NICHT über TextWorkflowDispatcher (handlers/menu/
text_workflow_dispatcher.py) geführt - dessen WORKFLOW_METHODS ist fest
auf user_mgmt_handler verdrahtet (siehe dortiger Docstring), eine
Erweiterung dafür wäre eine größere, hier nicht gerechtfertigte Änderung.
Stattdessen: ein handler-eigenes `pending_message_senders`-Set, exakt
analog zu NavidromeMenuHandler.browse_states (demselben bereits
etablierten Muster für "wartet auf Freitext außerhalb des generischen
Workflow-Systems"). RichMenuHandler.handle_text_message prüft dieses Set
vor dem generischen Workflow-Dispatch (siehe dortiger Aufruf).

Datenschutz (Master-Prompt, Phase F3): "Nur Mitglieder derselben
family_id dürfen Nachrichten lesen." - jede Methode prüft zuerst
FamilyService.is_active_family_member() bzw. verlässt sich auf
FamilyChatService, das dieselbe Prüfung selbst durchführt.
"""

from typing import Set

from telegram import Update
from telegram.ext import ContextTypes

from emoji import EMOJI
from logger import get_module_logger
from services.family.family_chat_service import FamilyChatService
from services.family.family_service import FamilyService


class FamilyChatHandler:
    """Telegram-Handler für die Familien-Chat-Menüzweige."""

    def __init__(
        self,
        family_service: FamilyService = None,
        chat_service: FamilyChatService = None,
    ):
        self.logger = get_module_logger("FamilyChatHandler")
        self.family_service = family_service or FamilyService()
        self.chat_service = chat_service or FamilyChatService(
            family_service=self.family_service
        )
        # Telegram-IDs, die gerade eine Chat-Nachricht eintippen sollen
        # (siehe Docstring oben - Analogon zu NavidromeMenuHandler.browse_states).
        self.pending_message_senders: Set[int] = set()
        self.logger.info("✅ FamilyChatHandler initialisiert")

    async def _reply_target(self, update: Update):
        return update.callback_query.message if update.callback_query else update.message

    async def _deny_access(self, update: Update) -> None:
        telegram_id = update.effective_user.id
        self.logger.warning(
            f"⛔ Zugriff auf Familien-Chat verweigert für Telegram-ID {telegram_id} "
            "(kein aktives Familienmitglied)."
        )
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ Nur für Familienmitglieder verfügbar.", show_alert=True
            )
        reply_target = await self._reply_target(update)
        if reply_target:
            await reply_target.reply_text(
                f"{EMOJI['warning']} Diese Funktion ist nur für Familienmitglieder verfügbar."
            )

    # ─────────────────────────────────────────────────────────────
    # 📝 Nachricht senden (Schritt 1: Prompt, Schritt 2: process_pending_message)
    # ─────────────────────────────────────────────────────────────

    async def handle_send_message_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            await self._deny_access(update)
            return

        self.pending_message_senders.add(telegram_id)
        reply_target = await self._reply_target(update)
        if reply_target:
            await reply_target.reply_text(
                "📝 Schreibe jetzt deine Nachricht an die Familie "
                "(oder /cancel zum Abbrechen):"
            )

    async def process_pending_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> None:
        """
        Wird von RichMenuHandler.handle_text_message aufgerufen, wenn der
        Absender in `pending_message_senders` steht. Persistiert die
        Nachricht und verteilt sie an alle übrigen aktiven Mitglieder mit
        aktivierten Notifications.
        """
        telegram_id = update.effective_user.id
        self.pending_message_senders.discard(telegram_id)

        entry = self.chat_service.post_message(telegram_id, text)
        if entry is None:
            await update.message.reply_text(
                f"{EMOJI['warning']} Nachricht konnte nicht gesendet werden "
                "(leer oder kein Familienzugriff)."
            )
            return

        await update.message.reply_text(
            f"{EMOJI['success']} Nachricht an die Familie gesendet."
        )

        recipients = self.chat_service.get_notification_recipients(telegram_id)
        sender_name = entry["sender_display_name"]
        broadcast_text = f"💬 {sender_name}:\n{entry['message']}"

        for recipient_id in recipients:
            try:
                await context.bot.send_message(
                    chat_id=int(recipient_id), text=broadcast_text
                )
            except Exception as e:
                self.logger.error(
                    f"❌ Konnte Family-Chat-Nachricht nicht an {recipient_id} "
                    f"zustellen: {e}",
                    exc_info=True,
                )

    # ─────────────────────────────────────────────────────────────
    # 📋 Letzte Nachrichten
    # ─────────────────────────────────────────────────────────────

    async def handle_recent_messages(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        messages = self.chat_service.get_recent_messages(telegram_id, limit=10)

        if messages is None:
            await self._deny_access(update)
            return

        reply_target = await self._reply_target(update)
        if not reply_target:
            return

        if not messages:
            await reply_target.reply_text(
                f"{EMOJI['warning']} Noch keine Nachrichten im Familien-Chat."
            )
            return

        lines = [
            f"💬 {m['sender_display_name']} ({m['created_at'][:16].replace('T', ' ')}):\n"
            f"{m['message']}"
            for m in messages
        ]
        response = "📋 Letzte Nachrichten:\n\n" + "\n\n".join(lines)
        await reply_target.reply_text(response)

    # ─────────────────────────────────────────────────────────────
    # 🔔 Benachrichtigungen (Toggle bei jedem Klick)
    # ─────────────────────────────────────────────────────────────

    async def handle_toggle_notifications(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            await self._deny_access(update)
            return

        currently_enabled = self.chat_service.notifications_enabled(telegram_id)
        new_state = not currently_enabled
        success = self.chat_service.set_notifications(telegram_id, new_state)

        reply_target = await self._reply_target(update)
        if not reply_target:
            return

        if not success:
            await reply_target.reply_text(f"{EMOJI['error']} Konnte nicht gespeichert werden.")
            return

        status_text = "🔔 AN" if new_state else "🔕 AUS"
        await reply_target.reply_text(
            f"Familien-Chat-Benachrichtigungen: {status_text}"
        )
