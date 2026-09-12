"""
Phase F2 (Family Hub) - Tests für services/family/family_stats_service.py.

Verwendet FakeFamilyRepository (wie tests/test_family_service.py) und ein
FakePlayHistoryRepository (in-memory, kein Dateisystemzugriff) - reale
Play-History-Dateien werden NICHT berührt (siehe CLAUDE.md Abschnitt 7/8:
externe/IO-Abhängigkeiten werden gefaked, die zu testende Business-Logik
ist die echte Produktionsklasse).
"""

from datetime import datetime, timedelta

from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService


class FakeFamilyRepository:
    def __init__(self, families):
        self._families = families

    def get_all_families(self):
        return dict(self._families)

    def get_family(self, family_id):
        return self._families.get(family_id, {})


class FakePlayHistoryRepository:
    def __init__(self, histories):
        # {navidrome_user: [entry, ...]}
        self._histories = histories

    def load(self, navidrome_username):
        return self._histories.get(navidrome_username, [])


def _entry(days_ago, title="Song", artist="Artist", album="Album", duration=None,
           at_time=None):
    ts = at_time or (datetime.now() - timedelta(days=days_ago))
    return {
        "timestamp": ts.isoformat(),
        "tracks": [
            {
                "title": title,
                "artist": artist,
                "album": album,
                "id": "abc",
                "duration": duration,
                "player": "Symfonium",
                "username": "n/a",
            }
        ],
    }


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
            "333": {
                "display_name": "Opa",
                "navidrome_user": "opa",
                "active": False,
                "notifications": True,
            },
        },
    },
    "other": {
        "name": "Andere Familie",
        "members": {
            "999": {
                "display_name": "Fremd",
                "navidrome_user": "fremd",
                "active": True,
                "notifications": True,
            }
        },
    },
}


def _make_service(histories):
    family_service = FamilyService(repository=FakeFamilyRepository(FAMILIES))
    repository = FakePlayHistoryRepository(histories)
    return FamilyStatsService(family_service=family_service, repository=repository)


class TestGenerateFamilyStats:
    def test_aggregates_plays_across_all_active_members(self):
        histories = {
            "papa": [_entry(1, artist="A"), _entry(2, artist="A")],
            "mama": [_entry(1, artist="B"), _entry(2, artist="B"), _entry(3, artist="B")],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month")

        assert stats["total_plays"] == 5
        assert stats["per_member"]["111"]["plays"] == 2
        assert stats["per_member"]["222"]["plays"] == 3
        assert stats["top_artists"][0] == ("B", 3)

    def test_excludes_inactive_member_from_aggregation(self):
        histories = {
            "papa": [_entry(1)],
            "opa": [_entry(1), _entry(1), _entry(1)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month")

        assert stats["total_plays"] == 1
        assert "333" not in stats["per_member"]

    def test_excludes_plays_of_other_family(self):
        histories = {
            "papa": [_entry(1)],
            "fremd": [_entry(1), _entry(1)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month")

        assert stats["total_plays"] == 1

    def test_returns_none_when_no_plays_in_period(self):
        histories = {"papa": [_entry(400)]}  # außerhalb von "month" (30 Tage) und "year" (365 Tage)
        service = _make_service(histories)

        assert service.generate_family_stats("main", period="month") is None
        assert service.generate_family_stats("main", period="year") is None

    def test_returns_none_when_family_has_no_history_at_all(self):
        service = _make_service({})
        assert service.generate_family_stats("main", period="month") is None

    def test_returns_none_for_unknown_family_id(self):
        service = _make_service({"papa": [_entry(1)]})
        assert service.generate_family_stats("does-not-exist", period="month") is None

    def test_listening_seconds_unreliable_when_all_durations_missing(self):
        histories = {"papa": [_entry(1, duration=None)]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month")

        assert stats["listening_seconds_reliable"] is False
        assert stats["listening_seconds"] == 0

    def test_listening_seconds_reliable_and_summed_when_duration_present(self):
        histories = {
            "papa": [_entry(1, duration=180), _entry(1, duration=None)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month")

        assert stats["listening_seconds_reliable"] is True
        assert stats["listening_seconds"] == 180


class TestGetChampion:
    def test_champion_is_member_with_most_plays(self):
        histories = {
            "papa": [_entry(1)],
            "mama": [_entry(1), _entry(1), _entry(1)],
        }
        service = _make_service(histories)

        champion = service.get_champion("main", period="month")

        assert champion == ("222", "Mama", 3)

    def test_champion_is_none_when_no_plays(self):
        service = _make_service({})
        assert service.get_champion("main", period="month") is None


class TestGenerateFamilyTimeline:
    def test_today_bucket_counts_only_todays_plays(self):
        now = datetime.now()
        yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
        histories = {
            "papa": [_entry(0, at_time=now), _entry(0, at_time=yesterday_start)],
        }
        service = _make_service(histories)

        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["track_count"] == 1

    def test_per_member_breakdown_present_in_each_period(self):
        histories = {"papa": [_entry(0)], "mama": [_entry(0)]}
        service = _make_service(histories)

        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["per_member"] == {"Papa": 1, "Mama": 1}

    def test_top_song_is_the_most_replayed_title_today(self):
        histories = {
            "papa": [
                _entry(0, title="Song A"),
                _entry(0, title="Song A"),
                _entry(0, title="Song B"),
            ],
        }
        service = _make_service(histories)

        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["top_song"] == ("Song A", 2)

    def test_returns_none_when_no_history(self):
        service = _make_service({})
        assert service.generate_family_timeline("main") is None


class TestGenerateListeningTimes:
    def test_buckets_plays_by_hour_and_weekday(self):
        fixed = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
        # auf einen Tag legen, der sicher innerhalb des 30-Tage-Fensters liegt
        fixed = fixed - timedelta(days=1)
        histories = {"papa": [_entry(0, at_time=fixed), _entry(0, at_time=fixed)]}
        service = _make_service(histories)

        result = service.generate_listening_times("main", period="month")

        assert result["by_hour"][14] == 2
        assert result["by_weekday"][fixed.weekday()] == 2
        assert result["total_plays"] == 2

    def test_returns_none_when_no_plays_in_period(self):
        service = _make_service({"papa": [_entry(400)]})
        assert service.generate_listening_times("main", period="month") is None


class TestGenerateMonthlyTrend:
    def test_counts_plays_per_calendar_month(self):
        now = datetime.now()
        this_month = now.replace(day=1, hour=12)
        last_month_ref = this_month - timedelta(days=1)
        last_month = last_month_ref.replace(day=1, hour=12)

        histories = {
            "papa": [
                _entry(0, at_time=this_month),
                _entry(0, at_time=this_month),
                _entry(0, at_time=last_month),
            ]
        }
        service = _make_service(histories)

        trend = service.generate_monthly_trend("main", months=3)

        assert trend["plays_by_month"][this_month.strftime("%Y-%m")] == 2
        assert trend["plays_by_month"][last_month.strftime("%Y-%m")] == 1
        assert trend["months"][-1] == this_month.strftime("%Y-%m")

    def test_returns_none_when_no_plays_at_all(self):
        service = _make_service({})
        assert service.generate_monthly_trend("main") is None
