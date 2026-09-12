# services/family/family_challenge_repository.py
# -*- coding: utf-8 -*-
"""
FamilyChallengeRepository – Persistenz für tägliche Familien-Challenges
und ihre Antworten (Phase F4, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Lesen/Schreiben von data/family_challenges.json und
    data/family_challenge_answers.json.
  - KEINE Fachlogik (Challenge-Auswahl, Auswertung siehe
    FamilyChallengeService), KEINE Telegram-Objekte.

Beide Dateien werden hier gemeinsam verwaltet (statt in zwei getrennten
Repository-Klassen), weil eine Antwort immer eine Challenge referenziert
(FK-artige Beziehung) und Aufrufer (FamilyChallengeService) i.d.R. beides
zusammen brauchen (z.B. Duplikatsprüfung: "hat User X Challenge Y schon
beantwortet?").

Struktur data/family_challenges.json:
    {
      "<family_id>": {
        "next_id": int,
        "challenges": [
          {
            "id": int,
            "family_id": str,
            "date": str (YYYY-MM-DD),
            "type": str,
            "question": str,
            "correct_answer": Optional[str],
            "created_at": str (ISO)
          }
        ]
      }
    }

Struktur data/family_challenge_answers.json:
    {
      "<family_id>": {
        "answers": [
          {
            "challenge_id": int,
            "user_id": str,
            "answer": str,
            "points": int,
            "answered_at": str (ISO)
          }
        ]
      }
    }

Persistenzmuster (atomarer write-tmp + rename, Deep-Copy vor Mutation)
1:1 übernommen aus FamilyRepository/FamilyMessageRepository - siehe
dortige Docstrings zur Begründung.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import copy
import json
import time

from logger import get_module_logger


class FamilyChallengeRepository:
    """Lädt/speichert tägliche Familien-Challenges und ihre Antworten."""

    def __init__(self, logger_factory=None):
        self.logger = (logger_factory or get_module_logger)("FamilyChallengeRepository")
        self.challenges_file = Path("data/family_challenges.json")
        self.answers_file = Path("data/family_challenge_answers.json")
        self.challenges_cache: Dict[str, Any] = self._load(self.challenges_file)
        self.answers_cache: Dict[str, Any] = self._load(self.answers_file)

    def _load(self, path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Laden von {path}: {e}")
            return {}

    def _save(self, path: Path, data: Dict[str, Any]) -> bool:
        tmp_path = path.with_suffix(f".tmp_{int(time.time() * 1000)}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(path)
            return True
        except Exception as e:
            self.logger.error(f"❌ Fehler beim Speichern von {path}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # ─────────────────────────────────────────────────────────────
    # Challenges
    # ─────────────────────────────────────────────────────────────

    def get_challenge_for_date(self, family_id: str, date_str: str) -> Optional[Dict[str, Any]]:
        """Gibt die Challenge einer Familie für ein bestimmtes Datum zurück, oder None."""
        family = self.challenges_cache.get(family_id, {})
        for challenge in family.get("challenges", []):
            if challenge.get("date") == date_str:
                return challenge
        return None

    def get_challenge_by_id(self, family_id: str, challenge_id: int) -> Optional[Dict[str, Any]]:
        family = self.challenges_cache.get(family_id, {})
        for challenge in family.get("challenges", []):
            if challenge.get("id") == challenge_id:
                return challenge
        return None

    def add_challenge(
        self,
        family_id: str,
        date_str: str,
        challenge_type: str,
        question: str,
        correct_answer: Optional[str],
    ) -> Dict[str, Any]:
        """Legt eine neue Challenge für `family_id`/`date_str` an und persistiert sie."""
        challenges = copy.deepcopy(self.challenges_cache)
        family = challenges.setdefault(family_id, {"next_id": 1, "challenges": []})

        entry = {
            "id": family["next_id"],
            "family_id": family_id,
            "date": date_str,
            "type": challenge_type,
            "question": question,
            "correct_answer": correct_answer,
            "created_at": datetime.now().isoformat(),
        }
        family["next_id"] += 1
        family["challenges"].append(entry)

        if self._save(self.challenges_file, challenges):
            self.challenges_cache = challenges
        else:
            self.logger.error(
                f"❌ Challenge für family_id={family_id}/{date_str} konnte nicht "
                "persistiert werden."
            )
        return entry

    # ─────────────────────────────────────────────────────────────
    # Antworten
    # ─────────────────────────────────────────────────────────────

    def has_answered(self, family_id: str, challenge_id: int, user_id: str) -> bool:
        """Keine Mehrfachwertung derselben Antwort (Master-Prompt, Phase F4)."""
        family = self.answers_cache.get(family_id, {})
        return any(
            a.get("challenge_id") == challenge_id and a.get("user_id") == user_id
            for a in family.get("answers", [])
        )

    def add_answer(
        self, family_id: str, challenge_id: int, user_id: str, answer: str, points: int
    ) -> Dict[str, Any]:
        answers = copy.deepcopy(self.answers_cache)
        family = answers.setdefault(family_id, {"answers": []})

        entry = {
            "challenge_id": challenge_id,
            "user_id": user_id,
            "answer": answer,
            "points": points,
            "answered_at": datetime.now().isoformat(),
        }
        family["answers"].append(entry)

        if self._save(self.answers_file, answers):
            self.answers_cache = answers
        else:
            self.logger.error(
                f"❌ Antwort von user_id={user_id} auf challenge_id={challenge_id} "
                f"(family_id={family_id}) konnte nicht persistiert werden."
            )
        return entry

    def get_answers_for_challenge(
        self, family_id: str, challenge_id: int
    ) -> List[Dict[str, Any]]:
        family = self.answers_cache.get(family_id, {})
        return [
            a for a in family.get("answers", []) if a.get("challenge_id") == challenge_id
        ]

    def get_total_points(self, family_id: str) -> Dict[str, int]:
        """Kumulierte Punkte je user_id über alle Challenges der Familie (Leaderboard)."""
        family = self.answers_cache.get(family_id, {})
        totals: Dict[str, int] = {}
        for a in family.get("answers", []):
            user_id = a.get("user_id")
            totals[user_id] = totals.get(user_id, 0) + a.get("points", 0)
        return totals
