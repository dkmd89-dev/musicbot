# services/family/family_challenge_service.py
# -*- coding: utf-8 -*-
"""
FamilyChallengeService – Fachlogik für die tägliche Familien-Musik-
Challenge (Phase F4, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Auswahl des täglichen Challenge-Typs (deterministisch, siehe unten).
  - Ermittlung von Frage + (sofern vorhanden) korrekter Antwort aus der
    bestehenden Play-History-Infrastruktur (FamilyStatsService,
    StatisticsCalculator) - KEINE zweite Statistik-Engine.
  - Auswertung eingereichter Antworten inkl. Duplikatsschutz.
  - KEINE Telegram-Objekte, KEIN Scheduling (siehe
    handlers/family_challenge_scheduler.py für die tägliche Auslösung).

Challenge-Typen (Master-Prompt nennt 5 Beispiele; hiervon wurden bewusst
NUR die 3 zuverlässig aus bereits vorhandenen Play-History-Daten
berechenbaren umgesetzt - "Rate den Song" (bräuchte Audio-/Lyrics-Snippets)
und "Playlist für [Stimmung] erstellen" (keine automatisch prüfbare
"korrekte" Antwort) sind explizit NICHT Teil dieser ersten Version):

  - family_top_artist_today: "Welcher Künstler hatte heute die meisten
    Plays in der Familie?" - korrekte Antwort = FamilyStatsService
    Today-Timeline, family-weit EINE korrekte Antwort.
  - family_top_song_today: dasselbe für den meistgespielten Song.
  - own_top_song_today: "Welches Lied hast du heute am meisten gehört?"
    - korrekte Antwort ist PRO NUTZER verschieden (kein globales
    `correct_answer` in der Challenge selbst), wird bei der Auswertung
    live über StatisticsCalculator.generate_timeline_stats() für den
    jeweils antwortenden Navidrome-User berechnet.

Deterministische statt zufällige Typauswahl: `date.toordinal() % len(TYPES)`
- reproduzierbar (kein Flaky-Test-Risiko durch random.choice) und für
alle Familien am selben Tag derselbe Typ (Familien-Erlebnis: alle sehen
dieselbe Art Frage).
"""

from datetime import date
from typing import Any, Dict, Optional, Tuple

from logger import get_module_logger

from config import Config
from services.family.family_challenge_repository import FamilyChallengeRepository
from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService
from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator

CHALLENGE_TYPES = (
    "family_top_artist_today",
    "family_top_song_today",
    "own_top_song_today",
)

CHALLENGE_QUESTIONS = {
    "family_top_artist_today": (
        "🎤 Welcher Künstler wurde heute in der Familie am häufigsten gehört?"
    ),
    "family_top_song_today": (
        "🎵 Welcher Song wurde heute in der Familie am häufigsten gehört?"
    ),
    "own_top_song_today": "🎧 Welches Lied hast DU heute am meisten gehört?",
}


class FamilyChallengeService:
    """Wählt tägliche Challenges aus, stellt Fragen und wertet Antworten aus."""

    def __init__(
        self,
        family_service: Optional[FamilyService] = None,
        family_stats_service: Optional[FamilyStatsService] = None,
        repository: Optional[FamilyChallengeRepository] = None,
        play_history_repository: Optional[PlayHistoryRepository] = None,
        logger_factory=None,
    ):
        self.logger = (logger_factory or get_module_logger)("FamilyChallengeService")
        self.family_service = family_service or FamilyService()
        self.family_stats_service = family_stats_service or FamilyStatsService(
            family_service=self.family_service
        )
        self.repository = repository or FamilyChallengeRepository()
        self._play_history_repository = play_history_repository or PlayHistoryRepository(
            Config.PLAY_HISTORY_FILE, logger=get_module_logger("PlayHistoryRepository")
        )
        self._statistics_calculator = StatisticsCalculator(
            self._play_history_repository,
            Config.STATS_DIR,
            logger=get_module_logger("StatisticsCalculator"),
        )

    # ─────────────────────────────────────────────────────────────
    # Tägliche Challenge erzeugen (idempotent pro family_id + Datum)
    # ─────────────────────────────────────────────────────────────

    def _pick_challenge_type(self, day: date) -> str:
        return CHALLENGE_TYPES[day.toordinal() % len(CHALLENGE_TYPES)]

    def _compute_family_wide_answer(
        self, family_id: str, challenge_type: str
    ) -> Optional[str]:
        timeline = self.family_stats_service.generate_family_timeline(family_id)
        if not timeline:
            return None
        today = timeline["periods"]["today"]
        if challenge_type == "family_top_artist_today":
            top = today.get("top_artist")
        elif challenge_type == "family_top_song_today":
            top = today.get("top_song")
        else:
            return None
        return top[0] if top else None

    def get_or_create_todays_challenge(self, family_id: str) -> Tuple[Dict[str, Any], bool]:
        """
        Gibt die heutige Challenge der Familie zurück - erzeugt sie bei
        Bedarf. Idempotent: ein zweiter Aufruf am selben Tag gibt dieselbe
        (bereits gespeicherte) Challenge zurück, statt eine zweite
        anzulegen (sowohl der Scheduler als auch ein manueller Menü-Klick
        rufen dieselbe Methode auf).

        Returns:
            (challenge, wurde_gerade_neu_erzeugt)
        """
        today_str = date.today().isoformat()
        existing = self.repository.get_challenge_for_date(family_id, today_str)
        if existing:
            return existing, False

        challenge_type = self._pick_challenge_type(date.today())
        question = CHALLENGE_QUESTIONS[challenge_type]
        correct_answer = self._compute_family_wide_answer(family_id, challenge_type)

        created = self.repository.add_challenge(
            family_id, today_str, challenge_type, question, correct_answer
        )
        return created, True

    # ─────────────────────────────────────────────────────────────
    # Antworten einreichen + auswerten
    # ─────────────────────────────────────────────────────────────

    def submit_answer(
        self, telegram_id: int, challenge_id: int, answer_text: str
    ) -> Dict[str, Any]:
        """
        Wertet die Antwort eines Familienmitglieds auf eine Challenge aus.

        Returns ein Dict mit `status` (eine von "denied", "not_found",
        "already_answered", "ok") und - nur bei "ok" - `correct` (bool),
        `points` (int) und `revealed_answer` (str, die tatsächliche
        korrekte Antwort - auch bei falscher Antwort gezeigt, damit der
        Nutzer etwas lernt).
        """
        if not self.family_service.is_active_family_member(telegram_id):
            return {"status": "denied"}

        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        challenge = self.repository.get_challenge_by_id(family_id, challenge_id)
        if challenge is None:
            return {"status": "not_found"}

        user_id = str(telegram_id)
        if self.repository.has_answered(family_id, challenge_id, user_id):
            return {"status": "already_answered"}

        correct, revealed_answer = self._evaluate_answer(telegram_id, challenge, answer_text)
        points = 1 if correct else 0

        self.repository.add_answer(family_id, challenge_id, user_id, answer_text.strip(), points)

        return {
            "status": "ok",
            "correct": correct,
            "points": points,
            "revealed_answer": revealed_answer,
        }

    def _evaluate_answer(
        self, telegram_id: int, challenge: Dict[str, Any], answer_text: str
    ) -> Tuple[bool, Optional[str]]:
        normalized_answer = (answer_text or "").strip().lower()

        if challenge["type"] == "own_top_song_today":
            member = self.family_service.get_member(telegram_id)
            navidrome_user = member.get("navidrome_user") if member else None
            if not navidrome_user:
                return False, None
            timeline = self._statistics_calculator.generate_timeline_stats(navidrome_user)
            most_replayed = (
                timeline["periods"]["today"]["most_replayed_track"] if timeline else None
            )
            if not most_replayed:
                return False, None
            correct_title = most_replayed[0]
            return normalized_answer == correct_title.strip().lower(), correct_title

        # family_top_artist_today / family_top_song_today: fest zum
        # Erzeugungszeitpunkt der Challenge berechnete, family-weite
        # korrekte Antwort.
        correct_answer = challenge.get("correct_answer")
        if not correct_answer:
            return False, None
        return normalized_answer == correct_answer.strip().lower(), correct_answer

    def has_user_answered(self, telegram_id: int, challenge_id: int) -> bool:
        """Für Handler-Schicht: soll noch ein Antwort-Prompt angeboten werden?"""
        family_id = self.family_service.get_family_id_for_telegram_user(telegram_id)
        if family_id is None:
            return False
        return self.repository.has_answered(family_id, challenge_id, str(telegram_id))

    # ─────────────────────────────────────────────────────────────
    # Punktestand
    # ─────────────────────────────────────────────────────────────

    def get_leaderboard(self, family_id: str) -> list:
        """
        Rangliste (absteigend nach Punkten) - [(telegram_id, display_name,
        points), ...]. Mitglieder ohne jede Antwort erscheinen mit 0
        Punkten (Master-Prompt, Phase F5: "Tests für Familienmitglieder
        ohne Plays" - analog hier für Mitglieder ohne Challenge-Antworten).
        """
        totals = self.repository.get_total_points(family_id)
        members = self.family_service.get_members(family_id, active_only=True)

        leaderboard = [
            (tg_id, data.get("display_name", tg_id), totals.get(tg_id, 0))
            for tg_id, data in members.items()
        ]
        leaderboard.sort(key=lambda row: row[2], reverse=True)
        return leaderboard
