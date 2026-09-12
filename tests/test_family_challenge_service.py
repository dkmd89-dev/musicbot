"""
Phase F4 (Family Hub) - Tests für services/family/family_challenge_service.py.

Fokus:
  - Deterministische (nicht zufällige) Typauswahl pro Tag.
  - Idempotenz von get_or_create_todays_challenge() (kein Doppel-Anlegen).
  - Korrekte Auswertung aller 3 Challenge-Typen, inkl. des personalisierten
    "own_top_song_today" (nutzt die ECHTE StatisticsCalculator-
    Produktionsklasse mit einem gefakten PlayHistoryRepository - siehe
    CLAUDE.md Abschnitt 7, "Produktionscode wirklich testen").
  - Keine Mehrfachwertung derselben Antwort (Master-Prompt, Phase F4).
  - Family-Isolation der Challenges/Punktestände.
"""

from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from services.family.family_challenge_repository import FamilyChallengeRepository
from services.family.family_challenge_service import CHALLENGE_TYPES, FamilyChallengeService
from services.family.family_service import FamilyService


class FakeFamilyRepository:
    def __init__(self, families):
        self._families = families

    def get_all_families(self):
        return dict(self._families)

    def get_family(self, family_id):
        return self._families.get(family_id, {})

    def update_member(self, family_id, telegram_id, updates):
        family = self._families.get(family_id)
        if not family or telegram_id not in family.get("members", {}):
            return False
        family["members"][telegram_id].update(updates)
        return True


class FakePlayHistoryRepository:
    def __init__(self, histories):
        self._histories = histories

    def load(self, navidrome_username):
        return self._histories.get(navidrome_username, [])


import copy

FAMILIES = {
    "main": {
        "name": "Familie",
        "members": {
            "111": {
                "display_name": "Papa",
                "navidrome_user": "papa",
                "active": True,
                "notifications": True,
            },
            "222": {
                "display_name": "Mama",
                "navidrome_user": "mama",
                "active": True,
                "notifications": True,
            },
        },
    },
    "other": {
        "name": "Andere Familie",
        "members": {
            "555": {
                "display_name": "Fremd",
                "navidrome_user": "fremd",
                "active": True,
                "notifications": True,
            }
        },
    },
}


def _make_challenge_repository(tmp_path):
    challenges_file = tmp_path / "family_challenges.json"
    answers_file = tmp_path / "family_challenge_answers.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/family_challenges.json":
            return challenges_file
        if p == "data/family_challenge_answers.json":
            return answers_file
        return Path(p, *args, **kwargs)

    with patch(
        "services.family.family_challenge_repository.Path", side_effect=_fake_path
    ):
        return FamilyChallengeRepository()


def _make_service(tmp_path, family_timeline=None, play_histories=None):
    family_service = FamilyService(repository=FakeFamilyRepository(copy.deepcopy(FAMILIES)))
    family_stats_service = Mock()
    family_stats_service.generate_family_timeline.return_value = family_timeline
    repository = _make_challenge_repository(tmp_path)
    play_history_repository = FakePlayHistoryRepository(play_histories or {})

    return FamilyChallengeService(
        family_service=family_service,
        family_stats_service=family_stats_service,
        repository=repository,
        play_history_repository=play_history_repository,
    )


TIMELINE_WITH_DATA = {
    "periods": {
        "today": {
            "top_artist": ("Clueso", 5),
            "top_song": ("Aufbruch", 3),
        }
    }
}


def _play_entry(title, artist, hour=12):
    from datetime import datetime

    ts = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    return {
        "timestamp": ts.isoformat(),
        "tracks": [{"title": title, "artist": artist, "album": "A", "duration": None}],
    }


class TestPickChallengeType:
    def test_type_is_one_of_the_known_types(self, tmp_path):
        service = _make_service(tmp_path)
        chosen = service._pick_challenge_type(date(2026, 9, 13))
        assert chosen in CHALLENGE_TYPES

    def test_same_day_always_yields_same_type(self, tmp_path):
        service = _make_service(tmp_path)
        day = date(2026, 9, 13)
        assert service._pick_challenge_type(day) == service._pick_challenge_type(day)

    def test_is_deterministic_not_random(self, tmp_path):
        service = _make_service(tmp_path)
        day = date(2026, 9, 13)
        expected = CHALLENGE_TYPES[day.toordinal() % len(CHALLENGE_TYPES)]
        assert service._pick_challenge_type(day) == expected


class TestGetOrCreateTodaysChallenge:
    def test_creates_a_new_challenge_when_none_exists(self, tmp_path):
        service = _make_service(tmp_path, family_timeline=TIMELINE_WITH_DATA)
        challenge, created = service.get_or_create_todays_challenge("main")

        assert created is True
        assert challenge["family_id"] == "main"
        assert challenge["date"] == date.today().isoformat()

    def test_second_call_same_day_returns_existing_without_creating_new(self, tmp_path):
        service = _make_service(tmp_path, family_timeline=TIMELINE_WITH_DATA)
        first, first_created = service.get_or_create_todays_challenge("main")
        second, second_created = service.get_or_create_todays_challenge("main")

        assert first_created is True
        assert second_created is False
        assert first["id"] == second["id"]

    def test_challenges_are_isolated_per_family(self, tmp_path):
        # next_id laeuft pro Familie unabhaengig (wie bei
        # FamilyMessageRepository, Phase F3) - id-Kollisionen zwischen
        # Familien sind erwartet und harmlos, da jeder Zugriff ueber
        # get_challenge_for_date()/get_challenge_by_id() immer mit
        # family_id skopiert ist.
        service = _make_service(tmp_path, family_timeline=TIMELINE_WITH_DATA)
        main_challenge, _ = service.get_or_create_todays_challenge("main")
        other_challenge, other_created = service.get_or_create_todays_challenge("other")

        assert other_created is True
        assert other_challenge["family_id"] == "other"
        # Zugriff ueber die eigene family_id liefert weiterhin die richtige Challenge zurueck:
        assert service.repository.get_challenge_by_id(
            "main", main_challenge["id"]
        )["family_id"] == "main"
        assert service.repository.get_challenge_by_id(
            "other", other_challenge["id"]
        )["family_id"] == "other"


class TestSubmitAnswerFamilyWideTypes:
    def _create_challenge_of_type(self, service, challenge_type, correct_answer):
        return service.repository.add_challenge(
            "main", date.today().isoformat(), challenge_type,
            "Frage?", correct_answer,
        )

    def test_correct_answer_scores_a_point(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        result = service.submit_answer(111, challenge["id"], "Clueso")

        assert result == {
            "status": "ok",
            "correct": True,
            "points": 1,
            "revealed_answer": "Clueso",
        }

    def test_answer_comparison_is_case_insensitive_and_trims_whitespace(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        result = service.submit_answer(111, challenge["id"], "  clueso  ")

        assert result["correct"] is True

    def test_wrong_answer_scores_zero_but_reveals_correct_answer(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        result = service.submit_answer(111, challenge["id"], "Falscher Name")

        assert result["correct"] is False
        assert result["points"] == 0
        assert result["revealed_answer"] == "Clueso"

    def test_null_correct_answer_means_no_one_can_win(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", None)

        result = service.submit_answer(111, challenge["id"], "irgendwas")

        assert result["correct"] is False

    def test_duplicate_answer_is_rejected(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        service.submit_answer(111, challenge["id"], "Clueso")
        second = service.submit_answer(111, challenge["id"], "Clueso")

        assert second == {"status": "already_answered"}

    def test_duplicate_check_is_per_user_not_per_family(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        service.submit_answer(111, challenge["id"], "Clueso")
        second_user_result = service.submit_answer(222, challenge["id"], "Clueso")

        assert second_user_result["status"] == "ok"

    def test_stranger_is_denied(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = self._create_challenge_of_type(service, "family_top_artist_today", "Clueso")

        result = service.submit_answer(999, challenge["id"], "Clueso")

        assert result == {"status": "denied"}

    def test_unknown_challenge_id_returns_not_found(self, tmp_path):
        service = _make_service(tmp_path)
        result = service.submit_answer(111, 9999, "Clueso")
        assert result == {"status": "not_found"}

    def test_member_cannot_answer_another_familys_colliding_challenge_id(self, tmp_path):
        """
        Family-Isolation (Phase F5): next_id laeuft pro Familie unabhaengig
        (siehe TestGetOrCreateTodaysChallenge.test_challenges_are_isolated_per_family),
        d.h. Challenge-IDs KOLLIDIEREN ueblicherweise zwischen Familien (beide
        starten bei 1). submit_answer() muss trotzdem strikt ueber die
        familyid des ANTWORTENDEN aufloesen - ein Mitglied von "main" darf
        niemals versehentlich gegen die gleich-nummerierte Challenge von
        "other" ausgewertet werden.
        """
        service = _make_service(tmp_path)
        main_challenge = self._create_challenge_of_type(
            service, "family_top_artist_today", "Clueso"
        )
        other_challenge = service.repository.add_challenge(
            "other", date.today().isoformat(), "family_top_artist_today", "F?", "AndereAntwort"
        )
        assert main_challenge["id"] == other_challenge["id"]  # Kollision wie erwartet

        # 111 ist Mitglied von "main", NICHT von "other" - Antwort passend
        # zu "other"s korrekter Antwort darf hier nicht ausgewertet werden.
        result = service.submit_answer(111, other_challenge["id"], "AndereAntwort")

        assert result["correct"] is False
        assert result["revealed_answer"] == "Clueso"


class TestSubmitAnswerOwnTopSongToday:
    def test_correct_when_matching_own_actual_top_song_today(self, tmp_path):
        histories = {"papa": [_play_entry("Aufbruch", "Clueso"), _play_entry("Aufbruch", "Clueso")]}
        service = _make_service(tmp_path, play_histories=histories)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "own_top_song_today", "Frage?", None
        )

        result = service.submit_answer(111, challenge["id"], "Aufbruch")

        assert result["correct"] is True
        assert result["revealed_answer"] == "Aufbruch"

    def test_incorrect_when_answer_does_not_match_own_top_song(self, tmp_path):
        histories = {"papa": [_play_entry("Aufbruch", "Clueso")]}
        service = _make_service(tmp_path, play_histories=histories)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "own_top_song_today", "Frage?", None
        )

        result = service.submit_answer(111, challenge["id"], "Falscher Titel")

        assert result["correct"] is False
        assert result["revealed_answer"] == "Aufbruch"

    def test_each_member_is_evaluated_against_their_own_history(self, tmp_path):
        histories = {
            "papa": [_play_entry("Song A", "Artist A")],
            "mama": [_play_entry("Song B", "Artist B")],
        }
        service = _make_service(tmp_path, play_histories=histories)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "own_top_song_today", "Frage?", None
        )

        papa_result = service.submit_answer(111, challenge["id"], "Song A")
        mama_result = service.submit_answer(222, challenge["id"], "Song B")

        assert papa_result["correct"] is True
        assert mama_result["correct"] is True

    def test_no_history_at_all_means_incorrect(self, tmp_path):
        service = _make_service(tmp_path, play_histories={})
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "own_top_song_today", "Frage?", None
        )

        result = service.submit_answer(111, challenge["id"], "irgendwas")

        assert result["correct"] is False
        assert result["revealed_answer"] is None


class TestLeaderboard:
    def test_ranks_members_by_points_descending(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "family_top_artist_today", "F", "Clueso"
        )
        service.submit_answer(111, challenge["id"], "Clueso")  # 1 Punkt
        service.submit_answer(222, challenge["id"], "Falsch")  # 0 Punkte

        leaderboard = service.get_leaderboard("main")

        assert leaderboard[0][0] == "111"
        assert leaderboard[0][2] == 1
        assert leaderboard[1][2] == 0

    def test_member_without_any_answer_appears_with_zero_points(self, tmp_path):
        service = _make_service(tmp_path)
        leaderboard = service.get_leaderboard("main")

        assert {row[0] for row in leaderboard} == {"111", "222"}
        assert all(row[2] == 0 for row in leaderboard)

    def test_leaderboard_is_isolated_per_family(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = service.repository.add_challenge(
            "other", date.today().isoformat(), "family_top_artist_today", "F", "X"
        )
        service.submit_answer(555, challenge["id"], "X")

        main_leaderboard = service.get_leaderboard("main")
        assert all(row[2] == 0 for row in main_leaderboard)


class TestHasUserAnswered:
    def test_false_before_answering(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "family_top_artist_today", "F", "Clueso"
        )
        assert service.has_user_answered(111, challenge["id"]) is False

    def test_true_after_answering(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "family_top_artist_today", "F", "Clueso"
        )
        service.submit_answer(111, challenge["id"], "Clueso")
        assert service.has_user_answered(111, challenge["id"]) is True

    def test_false_for_stranger(self, tmp_path):
        service = _make_service(tmp_path)
        challenge = service.repository.add_challenge(
            "main", date.today().isoformat(), "family_top_artist_today", "F", "Clueso"
        )
        assert service.has_user_answered(999, challenge["id"]) is False
