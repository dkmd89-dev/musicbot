"""
Phase F5 (Family Hub) - Hardening-Tests, die NICHT bereits durch die
F1-F4-Testdateien abgedeckt sind.

Die meisten der in der Master-Prompt-Checkliste genannten Punkte
(Berechtigungen, Family Isolation, Statistikaggregation, leere
Play-History, deaktivierte Notifications, Challenge-Duplikate, fremde
Telegram-ID) sind bereits durch die Tests aus F1-F4 abgedeckt (siehe
Abschlussbericht). Diese Datei schließt die zwei verbliebenen, dort noch
nicht explizit geprüften Lücken:

  1. Familienmitglieder OHNE jede Wiedergabe in der Statistikaggregation
     (nicht nur im Challenge-Leaderboard, das war bereits abgedeckt).
  2. Tagesgrenzen ("Zeitzonen/Tagesgrenzen" laut Master-Prompt) - sowohl
     für die kalenderbasierte Familien-Timeline (F2) als auch für die
     tägliche Challenge-Erzeugung (F4).

Zeitzonen-Hinweis: Das gesamte Projekt (StatisticsCalculator,
PlayHistoryPoller, jetzt auch Family Hub) rechnet konsequent mit naiven,
lokalen `datetime.now()`-Zeitstempeln - es gibt projektweit KEINE
Zeitzonen-aware-Logik. Family Hub führt hier bewusst keinen neuen,
abweichenden Standard ein, sondern charakterisiert exakt dasselbe
Verhalten wie die bestehende StatisticsCalculator-Timeline.
"""

import copy
from datetime import date, datetime, timedelta
from unittest.mock import patch

from services.family.family_challenge_service import FamilyChallengeService
from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService


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


FAMILIES_WITH_MEMBER_WITHOUT_PLAYS = {
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
                "display_name": "OhnePlays",
                "navidrome_user": "ohneplays",
                "active": True,
                "notifications": True,
            },
        },
    }
}


def _entry(days_ago=0, title="Song", artist="Artist", at_time=None):
    ts = at_time or (datetime.now() - timedelta(days=days_ago))
    return {
        "timestamp": ts.isoformat(),
        "tracks": [{"title": title, "artist": artist, "album": "Album", "duration": None}],
    }


class TestFamilyStatsMemberWithoutPlays:
    """Master-Prompt F5, Punkt 6: 'Tests für Familienmitglieder ohne Plays'."""

    def _make_service(self, histories):
        family_service = FamilyService(
            repository=FakeFamilyRepository(copy.deepcopy(FAMILIES_WITH_MEMBER_WITHOUT_PLAYS))
        )
        repository = FakePlayHistoryRepository(histories)
        return FamilyStatsService(family_service=family_service, repository=repository)

    def test_aggregation_does_not_crash_when_one_member_has_no_history_file(self):
        # "ohneplays" hat gar keine Play-History-Datei (repository.load()
        # gibt [] zurueck) - simuliert ein registriertes, aber noch nie
        # aktives Familienmitglied.
        service = self._make_service({"papa": [_entry(0)]})

        stats = service.generate_family_stats("main", period="month")

        assert stats is not None
        assert stats["total_plays"] == 1

    def test_member_without_plays_is_absent_from_per_member_not_zero_entry(self):
        service = self._make_service({"papa": [_entry(0)]})
        stats = service.generate_family_stats("main", period="month")

        # Charakterisierung des tatsächlichen Verhaltens: per_member wird
        # nur für Mitglieder mit mindestens einer Wiedergabe im Zeitraum
        # befuellt (kein 0-Eintrag) - kein Bug, aber ein Verhalten, das
        # Aufrufer (Handler) kennen muessen, bevor sie z.B. "222" fehlend
        # als Fehler missinterpretieren.
        assert "222" not in stats["per_member"]
        assert "111" in stats["per_member"]

    def test_champion_is_still_determined_when_other_member_has_zero_plays(self):
        service = self._make_service({"papa": [_entry(0), _entry(0)]})
        champion = service.get_champion("main", period="month")

        assert champion == ("111", "Papa", 2)

    def test_timeline_and_listening_times_do_not_crash_with_one_silent_member(self):
        service = self._make_service({"papa": [_entry(0)]})

        assert service.generate_family_timeline("main") is not None
        assert service.generate_listening_times("main", period="month") is not None

    def test_both_members_without_any_plays_returns_none_not_a_crash(self):
        service = self._make_service({})
        assert service.generate_family_stats("main", period="month") is None
        assert service.get_champion("main", period="month") is None
        assert service.generate_family_timeline("main") is None


class TestFamilyTimelineDayBoundary:
    """Master-Prompt F5, Punkt 9: 'Tests für Zeitzonen-/Tagesgrenzen'
    (charakterisiert das bestehende, naive lokale datetime.now()-Verhalten,
    identisch zu StatisticsCalculator.generate_timeline_stats()).

    Bewusst KEIN Mocking von datetime.now(): generate_family_timeline()
    ruft datetime.now()/datetime.fromisoformat() aus demselben,
    ungetrennten `datetime`-Import auf - ein Mock des gesamten Moduls
    würde auch fromisoformat() brechen (liefert dann ein MagicMock statt
    eines echten datetime, jeder Vergleich würde daraufhin fälschlich
    "wahr" auswerten). Stattdessen wie in tests/test_statistics_calculator.py
    etabliert: echte, relative datetime.now()-Zeitstempel statt Freezing.
    """

    def _make_service(self, histories):
        family_service = FamilyService(
            repository=FakeFamilyRepository(copy.deepcopy(FAMILIES_WITH_MEMBER_WITHOUT_PLAYS))
        )
        repository = FakePlayHistoryRepository(histories)
        return FamilyStatsService(family_service=family_service, repository=repository)

    def test_entry_exactly_at_midnight_counts_as_today(self):
        midnight_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        service = self._make_service({"papa": [_entry(at_time=midnight_today)]})
        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["track_count"] == 1

    def test_entry_one_microsecond_before_midnight_counts_as_yesterday_not_today(self):
        midnight_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        just_before_midnight = midnight_today - timedelta(microseconds=1)

        service = self._make_service({"papa": [_entry(at_time=just_before_midnight)]})
        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["track_count"] == 0


class TestFamilyChallengeDayBoundary:
    """Master-Prompt F5, Punkt 9: dieselbe Tagesgrenzen-Anforderung,
    hier für die taegliche Challenge-Erzeugung (F4)."""

    def _make_service(self, tmp_path, family_timeline=None):
        from pathlib import Path

        from services.family.family_challenge_repository import FamilyChallengeRepository

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
            repository = FamilyChallengeRepository()

        family_service = FamilyService(
            repository=FakeFamilyRepository(
                copy.deepcopy(FAMILIES_WITH_MEMBER_WITHOUT_PLAYS)
            )
        )
        from unittest.mock import Mock

        family_stats_service = Mock()
        family_stats_service.generate_family_timeline.return_value = family_timeline

        return FamilyChallengeService(
            family_service=family_service,
            family_stats_service=family_stats_service,
            repository=repository,
            play_history_repository=FakePlayHistoryRepository({}),
        )

    def test_a_challenge_dated_yesterday_does_not_satisfy_todays_lookup(self, tmp_path):
        service = self._make_service(tmp_path)
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        service.repository.add_challenge(
            "main", yesterday_str, "family_top_artist_today", "Gestrige Frage", "X"
        )

        challenge, created = service.get_or_create_todays_challenge("main")

        assert created is True
        assert challenge["date"] == date.today().isoformat()
        assert challenge["question"] != "Gestrige Frage"

    def test_yesterdays_challenge_remains_untouched_after_todays_is_created(self, tmp_path):
        service = self._make_service(tmp_path)
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        yesterday_challenge = service.repository.add_challenge(
            "main", yesterday_str, "family_top_artist_today", "Gestrige Frage", "X"
        )

        service.get_or_create_todays_challenge("main")

        still_there = service.repository.get_challenge_by_id(
            "main", yesterday_challenge["id"]
        )
        assert still_there["date"] == yesterday_str
        assert still_there["question"] == "Gestrige Frage"
