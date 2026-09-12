# handlers/family_challenge_handler.py
# -*- coding: utf-8 -*-
"""
FamilyChallengeHandler – Telegram-Präsentation für die tägliche
Familien-Musik-Challenge (Phase F4, Family Hub).

Verantwortlichkeit (Single Responsibility, siehe CLAUDE.md Abschnitt 4):
  - Ausschließlich Telegram-Präsentation. Auswahl/Auswertung der
    Challenge delegiert an FamilyChallengeService.

"✅ Antworten" ist ein Zwei-Schritt-Ablauf (Klick -> Freitext), nach
demselben Muster wie handlers/family_chat_handler.py ("📝 Nachricht
senden") - siehe dortiger Docstring zur Begründung gegen den generischen
TextWorkflowDispatcher. Unterschied zu Family-Chat: hier muss zusätzlich
die `challenge_id` mitgeführt werden, an die sich die als nächstes
eintreffende Freitext-Nachricht richtet - deshalb ein Dict
(`pending_answers: Dict[telegram_id, challenge_id]`) statt eines reinen
Sets.
"""

from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from emoji import EMOJI
from logger import get_module_logger
from services.family.family_challenge_service import FamilyChallengeService
from services.family.family_service import FamilyService


class FamilyChallengeHandler:
    """Telegram-Handler für die Familien-Challenge-Menüzweige."""

    def __init__(
        self,
        family_service: FamilyService = None,
        challenge_service: FamilyChallengeService = None,
    ):
        self.logger = get_module_logger("FamilyChallengeHandler")
        self.family_service = family_service or FamilyService()
        self.challenge_service = challenge_service or FamilyChallengeService(
            family_service=self.family_service
        )
        # Telegram-ID -> challenge_id, auf die die naechste Freitext-
        # Nachricht dieses Users als Antwort angewendet wird.
        self.pending_answers: Dict[int, int] = {}
        self.logger.info("✅ FamilyChallengeHandler initialisiert")

    async def _reply_target(self, update: Update):
        return update.callback_query.message if update.callback_query else update.message

    async def _deny_access(self, update: Update) -> None:
        telegram_id = update.effective_user.id
        self.logger.warning(
            f"⛔ Zugriff auf Familien-Challenge verweigert für Telegram-ID "
            f"{telegram_id} (kein aktives Familienmitglied)."
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
    # ❓ Heutige Challenge
    # ─────────────────────────────────────────────────────────────

    async def handle_todays_challenge(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            await self._deny_access(update)
            return

        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        challenge, _ = self.challenge_service.get_or_create_todays_challenge(family_id)

        reply_target = await self._reply_target(update)
        if not reply_target:
            return

        already_answered = self.challenge_service.has_user_answered(
            telegram_id, challenge["id"]
        )
        hint = (
            "\n\n✅ Du hast heute schon geantwortet."
            if already_answered
            else "\n\nAntworte über '✅ Antworten' im Menü."
        )
        await reply_target.reply_text(
            f"🎯 Heutige Familien-Challenge:\n\n{challenge['question']}{hint}"
        )

    # ─────────────────────────────────────────────────────────────
    # ✅ Antworten (Schritt 1: Prompt, Schritt 2: process_pending_answer)
    # ─────────────────────────────────────────────────────────────

    async def handle_answer_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            await self._deny_access(update)
            return

        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        challenge, _ = self.challenge_service.get_or_create_todays_challenge(family_id)

        reply_target = await self._reply_target(update)
        if not reply_target:
            return

        if self.challenge_service.has_user_answered(telegram_id, challenge["id"]):
            await reply_target.reply_text(
                f"{EMOJI['warning']} Du hast heute schon geantwortet - "
                "keine Mehrfachwertung."
            )
            return

        self.pending_answers[telegram_id] = challenge["id"]
        await reply_target.reply_text(
            f"❓ {challenge['question']}\n\n"
            "Schreibe jetzt deine Antwort (oder /cancel zum Abbrechen):"
        )

    async def process_pending_answer(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> None:
        """
        Wird von RichMenuHandler.handle_text_message aufgerufen, wenn der
        Absender in `pending_answers` steht.
        """
        telegram_id = update.effective_user.id
        challenge_id = self.pending_answers.pop(telegram_id, None)
        if challenge_id is None:
            return

        result = self.challenge_service.submit_answer(telegram_id, challenge_id, text)

        if result["status"] == "already_answered":
            await update.message.reply_text(
                f"{EMOJI['warning']} Du hast heute schon geantwortet - "
                "keine Mehrfachwertung."
            )
            return
        if result["status"] in ("denied", "not_found"):
            await update.message.reply_text(
                f"{EMOJI['error']} Antwort konnte nicht ausgewertet werden."
            )
            return

        if result["correct"]:
            await update.message.reply_text(
                f"{EMOJI['success']} Richtig! +{result['points']} Punkt."
            )
        else:
            revealed = result.get("revealed_answer")
            suffix = f"\nRichtige Antwort: {revealed}" if revealed else ""
            await update.message.reply_text(
                f"{EMOJI['warning']} Leider falsch.{suffix}"
            )

    # ─────────────────────────────────────────────────────────────
    # 🏆 Punktestand
    # ─────────────────────────────────────────────────────────────

    async def handle_leaderboard(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            await self._deny_access(update)
            return

        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        leaderboard = self.challenge_service.get_leaderboard(family_id)

        reply_target = await self._reply_target(update)
        if not reply_target:
            return

        if not leaderboard:
            await reply_target.reply_text(
                f"{EMOJI['warning']} Noch keine Familienmitglieder für den Punktestand."
            )
            return

        lines = [
            f"{idx + 1}. {name}: {points} Punkte"
            for idx, (_, name, points) in enumerate(leaderboard)
        ]
        await reply_target.reply_text("🏆 Punktestand Familien-Challenge:\n\n" + "\n".join(lines))
