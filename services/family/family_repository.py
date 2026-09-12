# services/family/family_repository.py
# -*- coding: utf-8 -*-
"""
FamilyRepository – Persistenz der Familienstruktur (Phase F1, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Lesen/Schreiben von data/family_data.json.
  - KEINE Berechtigungslogik (siehe FamilyService), KEINE Telegram-Objekte.

Struktur von data/family_data.json:
    {
      "<family_id>": {
        "name": str,
        "members": {
          "<telegram_id als str>": {
            "display_name": str,
            "navidrome_user": str,
            "active": bool,
            "notifications": bool
          }
        }
      }
    }

Bewusst KEIN separates "role"-Feld pro Mitglied: die bestehende
Rollen-/Berechtigungs-Wahrheit lebt in data/user_data.json
(handlers/admin/user_management_handler.py::UserManagementHandler,
ROLES = user/moderator/admin/owner). Ein dupliziertes Family-Rollenfeld
würde nur eine zweite, potenziell abweichende Quelle schaffen. Wird eine
Rolle für eine Family-Funktion benötigt, fragt FamilyService bei Bedarf
den UserManagementHandler ab statt sie hier zu spiegeln.

Persistenzmuster (atomarer write-tmp + rename) 1:1 übernommen aus
UserManagementHandler._save_users() (handlers/admin/user_management_handler.py),
aus denselben Gründen: ein Prozessabbruch während json.dump() darf die
Familienstruktur nicht leeren/korrumpieren.
"""

from pathlib import Path
from typing import Any, Dict
import copy
import json
import time

from logger import get_module_logger


class FamilyRepository:
    """Lädt/speichert die Familienstruktur aus data/family_data.json."""

    def __init__(self, logger_factory=None):
        self.logger = (logger_factory or get_module_logger)("FamilyRepository")
        self.family_data_file = Path("data/family_data.json")
        self.family_data_cache: Dict[str, Any] = self._load_families()

    def _load_families(self) -> Dict[str, Any]:
        """Lädt die Familienstruktur aus JSON."""
        try:
            if self.family_data_file.exists():
                with open(self.family_data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Family-Daten: {e}")
            return {}

    def _save_families(self, families: Dict[str, Any]) -> bool:
        """Speichert die Familienstruktur atomar und aktualisiert den Cache."""
        tmp_path = self.family_data_file.with_suffix(
            f".tmp_{int(time.time() * 1000)}"
        )
        try:
            self.family_data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(families, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.family_data_file)

            self.family_data_cache = families
            return True
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der Family-Daten: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def get_all_families(self) -> Dict[str, Any]:
        """Gibt eine Kopie der gesamten Familienstruktur zurück."""
        return dict(self.family_data_cache)

    def get_family(self, family_id: str) -> Dict[str, Any]:
        """Gibt die Daten einer einzelnen Familie zurück (leeres Dict, wenn unbekannt)."""
        return self.family_data_cache.get(family_id, {})

    def reload(self) -> None:
        """Erzwingt ein Neuladen des Caches von Platte."""
        self.family_data_cache = self._load_families()

    def update_member(self, family_id: str, telegram_id: str, updates: Dict[str, Any]) -> bool:
        """
        Merged `updates` in die Mitgliedsdaten von `telegram_id` innerhalb
        `family_id` und speichert atomar (Phase F3, Family Chat -
        Notifications-Toggle). Gibt False zurück (kein Schreibvorgang),
        wenn family_id/telegram_id unbekannt sind - KEINE automatische
        Erstellung neuer Mitglieder über diesen Weg.
        """
        # Deep copy statt der (nur flachen) get_all_families()-Kopie - sonst
        # würde das direkte .update() unten den LIVE-Cache bereits mutieren,
        # bevor überhaupt feststeht, ob _save_families() erfolgreich ist
        # (RAM/Disk-Divergenz bei Schreibfehler, siehe _save_families-Docstring).
        families = copy.deepcopy(self.family_data_cache)
        family = families.get(family_id)
        if not family or telegram_id not in family.get("members", {}):
            self.logger.warning(
                f"⚠️ update_member: unbekannte family_id/telegram_id "
                f"({family_id}/{telegram_id})"
            )
            return False

        family["members"][telegram_id].update(updates)
        return self._save_families(families)
