"""
Phase F4 (Family Hub) - Tests für services/family/family_challenge_repository.py.

Persistenzmuster analog zu tests/test_family_repository.py: Path() wird
während der Konstruktion umgeleitet, damit KEIN Test die reale
data/family_challenges.json / data/family_challenge_answers.json berührt.
"""

from pathlib import Path
from unittest.mock import patch

from services.family.family_challenge_repository import FamilyChallengeRepository


def _make_repository(tmp_path):
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
        repo = FamilyChallengeRepository()
    return repo, challenges_file, answers_file


class TestAddChallenge:
    def test_first_challenge_gets_id_1(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        entry = repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "Frage?", "Clueso")

        assert entry["id"] == 1
        assert entry["family_id"] == "main"
        assert entry["date"] == "2026-09-13"
        assert entry["correct_answer"] == "Clueso"

    def test_ids_increment_across_calls(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        first = repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "F1", "A")
        second = repo.add_challenge("main", "2026-09-14", "family_top_song_today", "F2", "B")

        assert second["id"] == first["id"] + 1

    def test_persists_to_disk(self, tmp_path):
        repo, challenges_file, _ = _make_repository(tmp_path)
        repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "F1", "A")

        reloaded = repo._load(challenges_file)
        assert reloaded["main"]["challenges"][0]["question"] == "F1"


class TestGetChallengeForDate:
    def test_returns_none_when_no_challenge_for_date(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        assert repo.get_challenge_for_date("main", "2026-09-13") is None

    def test_returns_matching_challenge(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "F1", "A")
        repo.add_challenge("main", "2026-09-14", "family_top_song_today", "F2", "B")

        found = repo.get_challenge_for_date("main", "2026-09-14")
        assert found["question"] == "F2"

    def test_does_not_leak_across_families(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "F1", "A")
        assert repo.get_challenge_for_date("other", "2026-09-13") is None


class TestHasAnsweredAndAddAnswer:
    def test_has_answered_false_initially(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        assert repo.has_answered("main", 1, "111") is False

    def test_has_answered_true_after_add_answer(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)
        assert repo.has_answered("main", 1, "111") is True

    def test_has_answered_is_per_user(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)
        assert repo.has_answered("main", 1, "222") is False

    def test_has_answered_is_per_challenge(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)
        assert repo.has_answered("main", 2, "111") is False

    def test_add_answer_persists_to_disk(self, tmp_path):
        repo, _, answers_file = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)

        reloaded = repo._load(answers_file)
        assert reloaded["main"]["answers"][0]["answer"] == "Clueso"

    def test_get_answers_for_challenge_filters_correctly(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)
        repo.add_answer("main", 2, "111", "Nico Santos", 0)

        answers = repo.get_answers_for_challenge("main", 1)
        assert len(answers) == 1
        assert answers[0]["answer"] == "Clueso"


class TestGetTotalPoints:
    def test_sums_points_per_user_across_challenges(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)
        repo.add_answer("main", 2, "111", "Nico Santos", 1)
        repo.add_answer("main", 1, "222", "Falsch", 0)

        totals = repo.get_total_points("main")
        assert totals["111"] == 2
        assert totals["222"] == 0

    def test_returns_empty_dict_for_family_without_answers(self, tmp_path):
        repo, _, _ = _make_repository(tmp_path)
        assert repo.get_total_points("main") == {}


class TestFailedWriteDoesNotMutateLiveCache:
    def test_add_challenge_failed_write_keeps_previous_cache(self, tmp_path, monkeypatch):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_challenge("main", "2026-09-13", "family_top_artist_today", "F1", "A")

        monkeypatch.setattr(
            "services.family.family_challenge_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        repo.add_challenge("main", "2026-09-14", "family_top_song_today", "F2", "B")

        # Cache wurde NICHT auf den (nicht persistierten) neuen Stand gesetzt.
        assert len(repo.challenges_cache["main"]["challenges"]) == 1

    def test_add_answer_failed_write_keeps_previous_cache(self, tmp_path, monkeypatch):
        repo, _, _ = _make_repository(tmp_path)
        repo.add_answer("main", 1, "111", "Clueso", 1)

        monkeypatch.setattr(
            "services.family.family_challenge_repository.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        repo.add_answer("main", 1, "222", "Falsch", 0)

        assert len(repo.answers_cache["main"]["answers"]) == 1
