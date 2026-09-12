# services/family/family_message_repository.py
# -*- coding: utf-8 -*-
"""
FamilyMessageRepository – Persistenz der Familien-Chat-Nachrichten
(Phase F3, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Lesen/Schreiben von data/family_messages.json.
  - KEINE Berechtigungslogik (siehe FamilyChatService), KEINE Telegram-
    Objekte, KEINE Verteilung an Empfänger.

Struktur von data/family_messages.json:
    {
      "<family_id>": {
        "next_id": int,
        "messages": [
          {
            "id": int,
            "family_id": str,
            "sender_user_id": str,
            "sender_display_name": str,
            "message": str,
            "created_at": str (ISO)
          }
        ]
      }
    }

Persistenzmuster (atomarer write-tmp + rename) 1:1 übernommen aus
FamilyRepository/UserManagementHandler - siehe dortige Docstrings.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import copy
import json
import time

from logger import get_module_logger

# Bewusst klein gehalten: Telegram selbst limitiert eine Nachricht auf 4096
# Zeichen - ein Family-Chat-Eintrag braucht keine Nähe an dieses Limit.
MAX_STORED_MESSAGES_PER_FAMILY = 500


class FamilyMessageRepository:
    """Lädt/speichert Familien-Chat-Nachrichten aus data/family_messages.json."""

    def __init__(self, logger_factory=None):
        self.logger = (logger_factory or get_module_logger)("FamilyMessageRepository")
        self.family_messages_file = Path("data/family_messages.json")
        self.cache: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            if self.family_messages_file.exists():
                with open(self.family_messages_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden der Family-Messages: {e}")
            return {}

    def _save(self, data: Dict[str, Any]) -> bool:
        tmp_path = self.family_messages_file.with_suffix(
            f".tmp_{int(time.time() * 1000)}"
        )
        try:
            self.family_messages_file.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.family_messages_file)

            self.cache = data
            return True
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern der Family-Messages: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def add_message(
        self,
        family_id: str,
        sender_user_id: str,
        sender_display_name: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Fügt eine neue Nachricht für `family_id` hinzu und gibt den
        gespeicherten Eintrag zurück. Bei Speicherfehler wird trotzdem der
        (nicht persistierte) Eintrag zurückgegeben, aber geloggt - der
        Aufrufer (FamilyChatService) entscheidet, ob er das dem Nutzer
        meldet.

        Begrenzt die gespeicherte Historie je Familie auf
        MAX_STORED_MESSAGES_PER_FAMILY (älteste zuerst entfernt), damit
        data/family_messages.json nicht unbegrenzt wächst - "Letzte
        Nachrichten" liest ohnehin nur die letzten 10.
        """
        # Deep copy statt flacher Kopie - sonst würden die Mutationen unten
        # (family["messages"].append(...)) den LIVE-Cache bereits ändern,
        # bevor feststeht, ob _save() erfolgreich ist (RAM/Disk-Divergenz
        # bei Schreibfehler, analog FamilyRepository.update_member()).
        families = copy.deepcopy(self.cache)
        family = families.setdefault(family_id, {"next_id": 1, "messages": []})

        entry = {
            "id": family["next_id"],
            "family_id": family_id,
            "sender_user_id": str(sender_user_id),
            "sender_display_name": sender_display_name,
            "message": message,
            "created_at": datetime.now().isoformat(),
        }
        family["next_id"] += 1
        family["messages"].append(entry)
        if len(family["messages"]) > MAX_STORED_MESSAGES_PER_FAMILY:
            family["messages"] = family["messages"][-MAX_STORED_MESSAGES_PER_FAMILY:]

        if not self._save(families):
            self.logger.error(
                f"❌ Nachricht von '{sender_display_name}' (family_id={family_id}) "
                "konnte nicht persistiert werden."
            )
        return entry

    def get_recent_messages(self, family_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Letzte `limit` Nachrichten einer Familie, chronologisch aufsteigend
        (älteste zuerst) - wie ein von oben nach unten lesbarer Chatverlauf.
        """
        family = self.cache.get(family_id, {})
        messages = family.get("messages", [])
        if limit <= 0:
            return []
        return list(messages[-limit:])
