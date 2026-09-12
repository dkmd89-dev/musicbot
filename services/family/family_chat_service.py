# services/family/family_chat_service.py
# -*- coding: utf-8 -*-
"""
FamilyChatService – Fachlogik für den bot-internen Familien-Chat
(Phase F3, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Berechtigungsprüfung (Family-Membership, via FamilyService) vor jedem
    Lese-/Schreibzugriff auf Nachrichten.
  - Persistenz-Delegation an FamilyMessageRepository.
  - Ermittlung der Empfänger-Telegram-IDs für die Verteilung neuer
    Nachrichten (aktive Mitglieder mit aktivierten Notifications, ohne
    den Absender selbst).
  - KEINE Telegram-Objekte, KEIN tatsächliches Senden (das bleibt
    handlers/family_chat_handler.py vorbehalten - dort ist `context.bot`
    verfügbar).

Datenschutz (Master-Prompt, Phase F3): "Nur Mitglieder derselben
family_id dürfen Nachrichten lesen." - `get_recent_messages()` gibt daher
None zurück, wenn der anfragende Telegram-Nutzer kein AKTIVES
Familienmitglied ist, statt eine leere Liste (die Handler-Schicht muss
diesen Unterschied kennen: None = kein Zugriff, [] = Zugriff erlaubt,
aber noch keine Nachrichten).
"""

from typing import Any, Dict, List, Optional

from logger import get_module_logger

from services.family.family_message_repository import FamilyMessageRepository
from services.family.family_service import FamilyService

# Telegram begrenzt eine Nachricht auf 4096 Zeichen. Deutlich darunter
# gekappt, damit für den Broadcast-Präfix ("💬 <Name>:\n") und eine
# eventuelle Zeichen-Encoding-Differenz sicher Platz bleibt.
MAX_MESSAGE_LENGTH = 2000


class FamilyChatService:
    """Prüft Zugriff, persistiert Chat-Nachrichten und ermittelt Empfänger."""

    def __init__(
        self,
        family_service: Optional[FamilyService] = None,
        message_repository: Optional[FamilyMessageRepository] = None,
        logger_factory=None,
    ):
        self.logger = (logger_factory or get_module_logger)("FamilyChatService")
        self.family_service = family_service or FamilyService()
        self.message_repository = message_repository or FamilyMessageRepository()

    def post_message(self, telegram_id: int, message_text: str) -> Optional[Dict[str, Any]]:
        """
        Persistiert eine Nachricht von `telegram_id`.

        Returns:
            Den gespeicherten Nachrichten-Eintrag, oder None, wenn
            `telegram_id` kein aktives Familienmitglied ist oder die
            Nachricht nach dem Trimmen leer ist.
        """
        if not self.family_service.is_active_family_member(telegram_id):
            self.logger.warning(
                f"⛔ post_message verweigert für Telegram-ID {telegram_id} "
                "(kein aktives Familienmitglied)."
            )
            return None

        text = (message_text or "").strip()
        if not text:
            return None
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH]

        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        member = self.family_service.get_member(telegram_id)
        display_name = member.get("display_name", str(telegram_id)) if member else str(telegram_id)

        return self.message_repository.add_message(
            family_id, str(telegram_id), display_name, text
        )

    def get_recent_messages(
        self, telegram_id: int, limit: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Letzte `limit` Nachrichten der Familie von `telegram_id`.

        Returns:
            None, wenn `telegram_id` kein aktives Familienmitglied ist
            (Datenschutz - Zugriff verweigert). Sonst eine Liste
            (möglicherweise leer, wenn noch keine Nachrichten existieren).
        """
        if not self.family_service.is_active_family_member(telegram_id):
            return None
        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        return self.message_repository.get_recent_messages(family_id, limit=limit)

    def get_notification_recipients(
        self, telegram_id: int, family_id: Optional[str] = None
    ) -> List[str]:
        """
        Telegram-IDs aller aktiven Familienmitglieder mit aktivierten
        Notifications, OHNE den Absender selbst (Selbstbenachrichtigung
        wäre nutzlos - der Absender kennt seine eigene Nachricht bereits).
        """
        if family_id is None:
            family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        if family_id is None:
            return []

        members = self.family_service.get_members(family_id, active_only=True)
        sender_id_str = str(telegram_id)
        return [
            tg_id
            for tg_id, data in members.items()
            if tg_id != sender_id_str and data.get("notifications", False)
        ]

    def set_notifications(self, telegram_id: int, enabled: bool) -> bool:
        """Delegiert an FamilyService - siehe dortige Docstring."""
        return self.family_service.set_notifications(telegram_id, enabled)

    def notifications_enabled(self, telegram_id: int) -> bool:
        """Delegiert an FamilyService - siehe dortige Docstring."""
        return self.family_service.notifications_enabled(telegram_id)
