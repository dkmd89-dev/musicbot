"""
Phase F2 (Family Hub) - Tests für services/family/family_stats_service.py.

MASTER PHASE B (Family Statistics Attribution, Identity & UX
Optimization): Fixtures wurden von relativen `days_ago`-Zeitstempeln
(implizit gegen den echten `datetime.now()`) auf injiziertes `now`
umgestellt (Abschnitt 29 verlangt deterministische Tests) - notwendig,
weil `generate_family_stats()`/`generate_listening_times()` jetzt echte
Kalenderperioden statt eines Rolling-Windows verwenden und ein Test wie
"3 Tage vor jetzt" an einer Monatsgrenze sonst flakey werden könnte.
`FIXED_NOW` liegt bewusst in der Monatsmitte, damit ±mehrere Tage sicher
im selben Kalendermonat bleiben.

Verwendet FakeFamilyRepository (wie tests/test_family_service.py) und ein
FakePlayHistoryRepository (in-memory, kein Dateisystemzugriff) - reale
Play-History-Dateien werden NICHT berührt (siehe CLAUDE.md Abschnitt 7/8:
externe/IO-Abhängigkeiten werden gefaked, die zu testende Business-Logik
ist die echte Produktionsklasse, inkl. der intern komponierten echten
StatisticsCalculator-Instanz).
"""

from datetime import datetime, timedelta

from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService
from services.statistik.statistics_calculator import StatisticsCalculator

FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0)


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


def _entry(days_ago=0, title="Song", artist="Artist", album="Album", duration=None,
           at_time=None, now=FIXED_NOW):
    ts = at_time or (now - timedelta(days=days_ago))
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

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["total_plays"] == 5
        assert stats["per_member"]["111"]["plays"] == 2
        assert stats["per_member"]["222"]["plays"] == 3
        assert stats["top_artists"][0]["artist"] == "B"
        assert stats["top_artists"][0]["total_plays"] == 3

    def test_excludes_inactive_member_from_aggregation(self):
        histories = {
            "papa": [_entry(1)],
            "opa": [_entry(1), _entry(1), _entry(1)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["total_plays"] == 1
        assert "333" not in stats["per_member"]

    def test_excludes_plays_of_other_family(self):
        histories = {
            "papa": [_entry(1)],
            "fremd": [_entry(1), _entry(1)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["total_plays"] == 1

    def test_returns_none_when_no_plays_in_period(self):
        # außerhalb des Kalendermonats UND -jahres von FIXED_NOW (2026-06)
        histories = {"papa": [_entry(400, now=FIXED_NOW)]}
        service = _make_service(histories)

        assert service.generate_family_stats("main", period="month", now=FIXED_NOW) is None
        assert service.generate_family_stats("main", period="year", now=FIXED_NOW) is None

    def test_returns_none_when_family_has_no_history_at_all(self):
        service = _make_service({})
        assert service.generate_family_stats("main", period="month", now=FIXED_NOW) is None

    def test_returns_none_for_unknown_family_id(self):
        service = _make_service({"papa": [_entry(1)]})
        assert (
            service.generate_family_stats("does-not-exist", period="month", now=FIXED_NOW)
            is None
        )

    def test_listening_seconds_unreliable_when_all_durations_missing(self):
        histories = {"papa": [_entry(1, duration=None)]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["listening_seconds_reliable"] is False
        assert stats["listening_seconds"] == 0

    def test_listening_seconds_reliable_and_summed_when_duration_present(self):
        histories = {
            "papa": [_entry(1, duration=180), _entry(1, duration=None)],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["listening_seconds_reliable"] is True
        assert stats["listening_seconds"] == 180

    def test_period_start_and_end_present_and_calendar_based(self):
        histories = {"papa": [_entry(1)]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        assert stats["period_start"] == datetime(2026, 6, 1)
        assert stats["period_end"] == datetime(2026, 7, 1)


class TestGenerateFamilyStatsCalendarPeriods:
    """Abschnitt 28 A - PERIODS: week/month/year sind ECHTE
    Kalenderperioden (kein Rolling-Window mehr), period_end exklusiv,
    Wochenwechsel/Monatswechsel/Jahreswechsel werden korrekt abgegrenzt."""

    def test_week_starts_monday_and_end_is_exclusive(self):
        # 2026-06-15 ist ein Montag
        monday_midnight = datetime(2026, 6, 15, 0, 0, 0)
        now = monday_midnight.replace(hour=9)
        histories = {
            "papa": [
                _entry(at_time=monday_midnight, now=now),  # genau Wochenstart -> zählt
                _entry(
                    at_time=monday_midnight - timedelta(seconds=1), now=now
                ),  # Sonntag davor -> zählt nicht
            ]
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="week", now=now)

        assert stats["total_plays"] == 1
        assert stats["period_start"] == datetime(2026, 6, 15)
        assert stats["period_end"] == datetime(2026, 6, 22)

    def test_month_boundary_excludes_previous_month(self):
        first_of_month = datetime(2026, 6, 1, 0, 0, 0)
        histories = {
            "papa": [
                _entry(at_time=first_of_month, now=first_of_month),
                _entry(
                    at_time=first_of_month - timedelta(seconds=1), now=first_of_month
                ),  # 31.05. -> zählt nicht
            ]
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=first_of_month)

        assert stats["total_plays"] == 1

    def test_year_boundary_excludes_previous_year(self):
        new_year = datetime(2026, 1, 1, 0, 0, 0)
        histories = {
            "papa": [
                _entry(at_time=new_year, now=new_year),
                _entry(at_time=new_year - timedelta(seconds=1), now=new_year),  # 2025 -> zählt nicht
            ]
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="year", now=new_year)

        assert stats["total_plays"] == 1
        assert stats["period_start"] == datetime(2026, 1, 1)
        assert stats["period_end"] == datetime(2027, 1, 1)

    def test_reuses_canonical_calendar_period_bounds(self):
        """Kein zweiter Kalender-Code - period_start/period_end stimmen
        exakt mit StatisticsCalculator._calendar_period_bounds() überein."""
        service = _make_service({"papa": [_entry(1)]})
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        expected_start, expected_end = StatisticsCalculator(
            service.repository, export_dir="/tmp"
        )._calendar_period_bounds("month", now=FIXED_NOW)
        assert stats["period_start"] == expected_start
        assert stats["period_end"] == expected_end


class TestArtistIdentityCaseInsensitive:
    """Abschnitt 9 + 28 B - Makko/makko/MAKKO müssen als derselbe Artist
    aggregiert werden; Display-Wert ist deterministisch (häufigste
    Original-Schreibweise, kein blindes lowercase)."""

    def test_case_variants_are_aggregated_into_one_artist(self):
        histories = {
            "papa": [_entry(1, artist="Makko"), _entry(1, artist="makko")],
            "mama": [_entry(1, artist="MAKKO")],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        matching = [a for a in stats["top_artists"] if a["artist"].casefold() == "makko"]
        assert len(matching) == 1
        assert matching[0]["total_plays"] == 3

    def test_display_value_is_most_frequent_original_casing(self):
        histories = {
            "papa": [_entry(1, artist="makko"), _entry(1, artist="makko")],
            "mama": [_entry(1, artist="Makko")],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        matching = [a for a in stats["top_artists"] if a["artist"].casefold() == "makko"]
        assert matching[0]["artist"] == "makko"

    def test_display_value_tie_break_is_deterministic_first_seen(self):
        # gleiche Häufigkeit (1x je Schreibweise) -> zuerst gesehene Variante gewinnt
        histories = {"papa": [_entry(1, artist="Makko"), _entry(2, artist="makko")]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        matching = [a for a in stats["top_artists"] if a["artist"].casefold() == "makko"]
        # papa's history wird chronologisch sortiert geparst (aeltester Eintrag
        # zuerst) - "makko" (2 Tage alt) kommt vor "Makko" (1 Tag alt).
        assert matching[0]["artist"] == "makko"

    def test_split_artists_reused_not_reimplemented(self):
        """` • `/` & ` splitten weiterhin über StatisticsCalculator._split_artists() -
        keine zweite Split-Regel; combo-Artist wird jedem Teil-Artist gutgeschrieben."""
        histories = {"papa": [_entry(1, artist="toobrokeforfiji • SIN Davis • makko")]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        artist_names = {a["artist"] for a in stats["top_artists"]}
        assert artist_names == {"toobrokeforfiji", "SIN Davis", "makko"}
        assert all(a["total_plays"] == 1 for a in stats["top_artists"])

    def test_ampersand_band_name_known_accepted_edge_case(self):
        """Pinnt denselben akzeptierten Grenzfall wie
        StatisticsCalculator._split_artists() (siehe dessen Docstring/
        docs/FINDINGS_INDEX.md) - keine neue/zweite Regel hier, nur
        Charakterisierung der Weitergabe."""
        histories = {"papa": [_entry(1, artist="Simon & Garfunkel")]}
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        artist_names = {a["artist"] for a in stats["top_artists"]}
        assert artist_names == {"Simon", "Garfunkel"}


class TestSongIdentity:
    """Abschnitt 10 + 28 C: Songs werden über
    StatisticsCalculator._identity_key() (Artist+Titel) identifiziert -
    gleicher Titel unterschiedlicher Artist bleibt getrennt."""

    def test_same_title_different_artist_not_merged(self):
        histories = {
            "papa": [_entry(1, title="Song X", artist="Artist A")],
            "mama": [_entry(1, title="Song X", artist="Artist B")],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        songs = [s for s in stats["top_songs"] if s["title"] == "Song X"]
        assert len(songs) == 2
        assert {s["artists"] for s in songs} == {"Artist A", "Artist B"}
        assert all(s["total_plays"] == 1 for s in songs)

    def test_same_song_different_case_artist_is_not_merged(self):
        """Song-Identity ist bewusst NICHT case-insensitive (anders als
        Artist-Identity, siehe Klassen-Docstring) - identisch zur
        Personal-Statistics-Semantik von _identity_key()."""
        histories = {
            "papa": [_entry(1, title="Song X", artist="makko")],
            "mama": [_entry(1, title="Song X", artist="Makko")],
        }
        service = _make_service(histories)

        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        songs = [s for s in stats["top_songs"] if s["title"] == "Song X"]
        assert len(songs) == 2


class TestFamilyAggregation:
    """Abschnitt 11 + 28 D: kein Cross-Member-Deduplication, Summe der
    Member-Plays == Song-total_plays, Summe der Song-Plays == Family-total."""

    def test_one_member(self):
        histories = {"papa": [_entry(1, title="X"), _entry(1, title="X")]}
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        song = stats["top_songs"][0]
        assert song["total_plays"] == 2
        assert len(song["members"]) == 1

    def test_multiple_members_same_song_no_dedup(self):
        histories = {
            "papa": [_entry(1, title="X")] * 5,
            "mama": [_entry(1, title="X")] * 3,
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        song = stats["top_songs"][0]
        assert song["total_plays"] == 8

    def test_member_plays_sum_equals_song_total(self):
        histories = {
            "papa": [_entry(1, title="X")] * 5,
            "mama": [_entry(1, title="X")] * 3,
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        song = stats["top_songs"][0]
        assert sum(m["plays"] for m in song["members"]) == song["total_plays"]

    def test_song_totals_sum_equals_family_total(self):
        histories = {
            "papa": [_entry(1, title="X"), _entry(1, title="Y")],
            "mama": [_entry(1, title="X")],
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        assert sum(s["total_plays"] for s in stats["top_songs"]) == stats["total_plays"]


class TestMemberAttribution:
    """Abschnitt 12 + 28 E: reale Zuordnung aus den Play-Events, keine
    Schätzung; 0-Play-Mitglieder tauchen in Attribution/Rankings nicht auf."""

    def test_real_attribution_from_play_events(self):
        histories = {
            "papa": [_entry(1, title="X")] * 15,
            "mama": [_entry(1, title="X")] * 5,
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        song = stats["top_songs"][0]
        by_name = {m["display_name"]: m["plays"] for m in song["members"]}
        assert by_name == {"Papa": 15, "Mama": 5}

    def test_multiple_members_attributed(self):
        histories = {"papa": [_entry(1)], "mama": [_entry(1)]}
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        assert len(stats["top_songs"][0]["members"]) == 2

    def test_single_member_attributed(self):
        histories = {"papa": [_entry(1)]}
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        assert len(stats["top_songs"][0]["members"]) == 1

    def test_zero_play_member_excluded_from_song_attribution(self):
        histories = {"papa": [_entry(1)]}  # mama hat keine History
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        member_names = {m["display_name"] for m in stats["top_songs"][0]["members"]}
        assert "Mama" not in member_names


class TestArtistAttribution:
    """Abschnitt 28 F: Artist -> Member Plays."""

    def test_artist_attribution_matches_members(self):
        histories = {
            "papa": [_entry(1, artist="X")] * 4,
            "mama": [_entry(1, artist="X")] * 2,
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)
        artist = next(a for a in stats["top_artists"] if a["artist"] == "X")
        by_name = {m["display_name"]: m["plays"] for m in artist["members"]}
        assert by_name == {"Papa": 4, "Mama": 2}


class TestGetChampion:
    def test_champion_is_member_with_most_plays(self):
        histories = {
            "papa": [_entry(1)],
            "mama": [_entry(1), _entry(1), _entry(1)],
        }
        service = _make_service(histories)

        champion = service.get_champion("main", period="month", now=FIXED_NOW)

        assert champion == ("222", "Mama", 3)

    def test_champion_is_none_when_no_plays(self):
        service = _make_service({})
        assert service.get_champion("main", period="month", now=FIXED_NOW) is None


class TestGenerateFamilyTimeline:
    """generate_family_timeline() ist in MASTER PHASE B bewusst
    unverändert (siehe services/family/family_stats_service.py-Docstring)
    - Tests unverändert gegenüber Vor-Phase-B-Stand, nutzen weiterhin
    echte datetime.now()-relative Zeitstempel (kein now-Parameter)."""

    def test_today_bucket_counts_only_todays_plays(self):
        now = datetime.now()
        yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
        histories = {
            "papa": [_entry(0, at_time=now, now=now), _entry(0, at_time=yesterday_start, now=now)],
        }
        service = _make_service(histories)

        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["track_count"] == 1

    def test_per_member_breakdown_present_in_each_period(self):
        now = datetime.now()
        histories = {"papa": [_entry(at_time=now)], "mama": [_entry(at_time=now)]}
        service = _make_service(histories)

        timeline = service.generate_family_timeline("main")

        assert timeline["periods"]["today"]["per_member"] == {"Papa": 1, "Mama": 1}

    def test_top_song_is_the_most_replayed_title_today(self):
        now = datetime.now()
        histories = {
            "papa": [
                _entry(at_time=now, title="Song A"),
                _entry(at_time=now, title="Song A"),
                _entry(at_time=now, title="Song B"),
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
        fixed = FIXED_NOW.replace(hour=14, minute=0, second=0, microsecond=0)
        histories = {"papa": [_entry(at_time=fixed, now=FIXED_NOW), _entry(at_time=fixed, now=FIXED_NOW)]}
        service = _make_service(histories)

        result = service.generate_listening_times("main", period="month", now=FIXED_NOW)

        assert result["by_hour"][14] == 2
        assert result["by_weekday"][fixed.weekday()] == 2
        assert result["total_plays"] == 2

    def test_returns_none_when_no_plays_in_period(self):
        service = _make_service({"papa": [_entry(400, now=FIXED_NOW)]})
        assert service.generate_listening_times("main", period="month", now=FIXED_NOW) is None

    def test_period_start_and_end_present(self):
        service = _make_service({"papa": [_entry(1)]})
        result = service.generate_listening_times("main", period="month", now=FIXED_NOW)
        assert result["period_start"] == datetime(2026, 6, 1)
        assert result["period_end"] == datetime(2026, 7, 1)


class TestGenerateMonthlyTrend:
    def test_counts_plays_per_calendar_month(self):
        this_month = FIXED_NOW.replace(day=1, hour=12)
        last_month_ref = this_month - timedelta(days=1)
        last_month = last_month_ref.replace(day=1, hour=12)

        histories = {
            "papa": [
                _entry(at_time=this_month, now=FIXED_NOW),
                _entry(at_time=this_month, now=FIXED_NOW),
                _entry(at_time=last_month, now=FIXED_NOW),
            ]
        }
        service = _make_service(histories)

        trend = service.generate_monthly_trend("main", months=3, now=FIXED_NOW)

        assert trend["plays_by_month"][this_month.strftime("%Y-%m")] == 2
        assert trend["plays_by_month"][last_month.strftime("%Y-%m")] == 1
        assert trend["months"][-1] == this_month.strftime("%Y-%m")

    def test_returns_none_when_no_plays_at_all(self):
        service = _make_service({})
        assert service.generate_monthly_trend("main", now=FIXED_NOW) is None


class TestConsistencyWithPersonalStatistics:
    """Abschnitt 28 J - kritischer Konsistenz-Test: Family-Attribution
    eines Members muss für dieselbe Periode/History dieselbe Play-Summe
    ergeben wie StatisticsCalculator.generate_stats() für denselben
    Navidrome-User (gleicher Input + gleiche Periodenfilterung + gleiche
    Member-Zuordnung). Für Artists wird wegen Multi-Artist-Splitting NICHT
    verlangt, dass die Summe aller Artist-Zählungen == total_plays ist
    (siehe StatisticsCalculator._split_artists()-Docstring) - stattdessen
    wird geprüft, dass identische Split-Artist-Play-Counts entstehen."""

    def test_member_total_plays_matches_personal_statistics_for_same_period(self):
        histories = {
            "papa": [_entry(1, title="X"), _entry(2, title="Y"), _entry(3, title="Z")],
            "mama": [_entry(1, title="X")],
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        personal_calculator = StatisticsCalculator(service.repository, export_dir="/tmp")
        personal_papa = personal_calculator.generate_stats(
            period="month", navidrome_username="papa", now=FIXED_NOW
        )

        assert stats["per_member"]["111"]["plays"] == personal_papa["total_plays"]

    def test_member_artist_split_counts_match_personal_statistics(self):
        histories = {
            "papa": [_entry(1, artist="A • B"), _entry(1, artist="A • B"), _entry(1, artist="C")],
        }
        service = _make_service(histories)
        stats = service.generate_family_stats("main", period="month", now=FIXED_NOW)

        personal_calculator = StatisticsCalculator(service.repository, export_dir="/tmp")
        personal_papa = personal_calculator.generate_stats(
            period="month", navidrome_username="papa", now=FIXED_NOW
        )
        personal_artist_counts = dict(personal_papa["top_artists_split"])

        for artist_entry in stats["top_artists"]:
            name = artist_entry["artist"]
            # Nur Papa ist in dieser Familie aktiv mit Verlauf - die
            # Family-weite Artist-Play-Zahl entspricht daher exakt Papas
            # eigener top_artists_split-Zahl fuer denselben Artist.
            assert artist_entry["total_plays"] == personal_artist_counts[name]
