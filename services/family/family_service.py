# services/family/family_service.py
# -*- coding: utf-8 -*-
"""
FamilyService – Berechtigungslogik für den privaten Family-Hub (Phase F1).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Family-Membership-/Zugriffsprüfungen und Lesezugriff
    auf Family-Mitgliederdaten (via injiziertes FamilyRepository).
  - KEINE Telegram-Objekte, KEINE Statistik-Berechnung.

Serverseitige Zugriffsprüfung (Master-Prompt, Phase F1 "Datenschutz"):

    Telegram User ID → Familienmitglied? → Family ID → Zugriff erlaubt

Jede zukünftige Family-Funktion (Statistik, Chat, Challenges) MUSS vor
jedem Zugriff `is_active_family_member()` bzw. `get_family_id_for_telegram_user()`
aufrufen. Ein normaler Bot-Benutzer, der kein Familienmitglied ist, darf
niemals Family-Daten sehen.

Keine automatische Zuordnung: ein Telegram-Nutzer ist ausschließlich dann
Familienmitglied, wenn er explizit unter einer family_id in
data/family_data.json unter "members" eingetragen ist.
"""

from typing import Any, Dict, List, Optional

from logger import get_module_logger

from services.family.family_repository import FamilyRepository


class FamilyService:
    """Prüft Family-Mitgliedschaft/Zugriff und liest Family-Mitgliederdaten."""

    def __init__(self, repository: Optional[FamilyRepository] = None, logger_factory=None):
        self.logger = (logger_factory or get_module_logger)("FamilyService")
        self.repository = repository or FamilyRepository()

    def get_all_family_ids(self) -> List[str]:
        """Alle bekannten family_ids (Phase F4 - Scheduler iteriert darüber)."""
        return list(self.repository.get_all_families().keys())

    def get_family_id_for_telegram_user(self, telegram_id: int) -> Optional[str]:
        """
        Ermittelt die family_id für eine Telegram-ID.

        Returns:
            family_id, wenn die Telegram-ID explizit als Mitglied einer
            Familie eingetragen ist, sonst None (KEINE automatische
            Zuordnung, KEIN Fallback).
        """
        telegram_id_str = str(telegram_id)
        for family_id, family in self.repository.get_all_families().items():
            if telegram_id_str in family.get("members", {}):
                return family_id
        return None

    def is_family_member(self, telegram_id: int) -> bool:
        """True, wenn die Telegram-ID irgendeiner Familie zugeordnet ist (unabhängig von active)."""
        return self.get_family_id_for_telegram_user(telegram_id) is not None

    def get_member(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Gibt die Mitgliedsdaten für eine Telegram-ID zurück, oder None."""
        family_id = self.get_family_id_for_telegram_user(telegram_id)
        if family_id is None:
            return None
        family = self.repository.get_family(family_id)
        return family.get("members", {}).get(str(telegram_id))

    def is_active_family_member(self, telegram_id: int) -> bool:
        """
        True nur, wenn die Telegram-ID Familienmitglied UND aktiv ist.

        Dies ist die maßgebliche Zugriffsprüfung für alle Family-Funktionen
        (Statistik, Chat, Challenges) - ein inaktives Mitglied darf keine
        Family-Funktionen nutzen.
        """
        member = self.get_member(telegram_id)
        if member is None:
            return False
        return bool(member.get("active", True))

    def get_members(self, family_id: str, active_only: bool = False) -> Dict[str, Dict[str, Any]]:
        """Gibt die Mitglieder einer Familie zurück (leeres Dict, wenn Familie unbekannt)."""
        family = self.repository.get_family(family_id)
        members = family.get("members", {})
        if not active_only:
            return dict(members)
        return {
            tg_id: data
            for tg_id, data in members.items()
            if data.get("active", True)
        }

    def notifications_enabled(self, telegram_id: int) -> bool:
        """True, wenn das Mitglied existiert, aktiv ist UND Notifications aktiviert hat."""
        member = self.get_member(telegram_id)
        if member is None:
            return False
        if not member.get("active", True):
            return False
        return bool(member.get("notifications", False))

    def set_notifications(self, telegram_id: int, enabled: bool) -> bool:
        """
        Aktiviert/deaktiviert Family-Benachrichtigungen für ein Mitglied
        (Phase F3, Family Chat). Gibt False zurück, wenn die Telegram-ID
        kein Familienmitglied ist - KEINE automatische Zuordnung.
        """
        family_id = self.get_family_id_for_telegram_user(telegram_id)
        if family_id is None:
            return False
        return self.repository.update_member(
            family_id, str(telegram_id), {"notifications": bool(enabled)}
        )

    def get_navidrome_users(self, family_id: str, active_only: bool = True) -> Dict[str, str]:
        """
        Gibt {telegram_id: navidrome_user} für eine Familie zurück - Grundlage
        für FamilyStatsService (Phase F2), um Play-History pro Mitglied zu laden.
        Mitglieder ohne gesetzten navidrome_user werden ausgelassen.
        """
        members = self.get_members(family_id, active_only=active_only)
        return {
            tg_id: data["navidrome_user"]
            for tg_id, data in members.items()
            if data.get("navidrome_user")
        }
