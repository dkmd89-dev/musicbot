"""
Unit-Tests für StatisticsCalculator (services/statistik/statistics_calculator.py)
— extrahiert aus StatistikService (ARCH-003, P-6). Nutzt ein echtes
PlayHistoryRepository auf tmp_path als Datenquelle (reine Datei-Logik,
kein externer Service - Regel 10-artig), direkter Test der neuen Klasse
ohne Umweg über die StatistikService-Fassade.

Statistics Menu UX & Architecture Optimization: generate_stats() lief
bisher über ein Rolling-N-Day-Window ("month"=30/"year"=365 Tage ab
"jetzt") statt echter Kalenderperioden - die alten, gegen echtes
datetime.now() relative "days_ago"-Tests waren dadurch faktisch
zeitpunktabhängig (nahe an einem Monatswechsel wären sie geflackert).
Alle Tests unten verwenden jetzt den injizierbaren `now`-Parameter mit
FESTEN Referenzdaten - deterministisch unabhängig vom tatsächlichen
Ausführungsdatum, wie vom Master-Prompt (Phase 19) gefordert.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock

from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator


def make_calculator(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    repo = PlayHistoryRepository(history_dir, logger=Mock())
    calc = StatisticsCalculator(repo, tmp_path / "exports", logger=Mock())
    return calc, repo


def _entry(artist: str, title: str, album: str = "Album", *, at: datetime, duration=None):
    return {
        "timestamp": at.isoformat(),
        "tracks": [
            {
                "title": title,
                "artist": artist,
                "album": album,
                "id": "1",
                "duration": duration,
            }
        ],
    }


class TestGenerateStats:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_stats("month", navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_stats("month", navidrome_username="alice") is None

    def test_top_artists_ranked_by_play_count(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Bausa", "Song A", at=now - timedelta(days=1)),
            _entry("Bausa", "Song B", at=now - timedelta(days=2)),
            _entry("Kollegah", "Song C", at=now - timedelta(days=3)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["total_plays"] == 3
        assert stats["top_artists"][0] == ("Bausa", 2)

    def test_entries_outside_period_are_excluded(self, tmp_path):
        """Statistics Menu UX & Output Optimization: ein Account MIT
        Verlauf, aber 0 Plays in der angefragten Periode, liefert jetzt
        ein gültiges Dict (total_plays=0) statt None - ermöglicht dem
        Aufrufer eine periodenbezogene 'noch keine Wiedergaben'-Meldung.
        None bleibt reserviert für 'Account hat überhaupt keinen
        Verlauf' (siehe test_no_history_returns_none)."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Old Song", at=now - timedelta(days=400))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats is not None
        assert stats["total_plays"] == 0
        assert stats["top_songs"] == []
        assert stats["top_artists"] == []

    def test_invalid_timestamp_entry_is_skipped_not_crashed(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        bad_entry = _entry("Bausa", "Song A", at=now - timedelta(days=1))
        bad_entry["timestamp"] = "not-a-timestamp"
        repo.save([bad_entry], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats is not None
        assert stats["total_plays"] == 0

    def test_future_timestamp_entry_is_skipped(self, tmp_path):
        """Phase 9 des Audits: ein Timestamp in der Zukunft (Datenfehler/
        Uhr-Skew) darf keine Kalenderperiode künstlich befüllen."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save(
            [_entry("Bausa", "Future Song", at=now + timedelta(days=5))], "alice"
        )

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats is not None
        assert stats["total_plays"] == 0

    def test_unknown_period_falls_back_to_month(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("decade", navidrome_username="alice", now=now)

        assert stats["period"] == "month"

    def test_result_contains_calendar_period_start_and_end(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["period_start"] == datetime(2026, 6, 1)
        assert stats["period_end"] == datetime(2026, 7, 1)

    def test_top_albums_no_longer_present(self, tmp_path):
        """Statistics Menu UX & Output Optimization: 'Top Alben entfernen'
        - generate_stats() berechnet album_counts/top_albums nicht mehr
        (einziger Konsument war die inzwischen entfernte Album-Sektion
        der Rückblick-Anzeige)."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save(
            [_entry("Bausa", "Song A", album="Some Album", at=now - timedelta(days=1))],
            "alice",
        )

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert "top_albums" not in stats

    def test_top_songs_include_artist_disambiguation(self, tmp_path):
        """Statistics Menu UX & Output Optimization: 'Top Songs
        verbessern' - top_songs zeigt jetzt "Titel — Artist"."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["top_songs"] == [("Song A — Bausa", 1)]


class TestTrackIdentityCollisionSafety:
    """Phase 10 des Audits: 'Artist A - Song X' und 'Artist B - Song X'
    dürfen nicht als derselbe Track gelten - ihre Play-Counts dürfen
    nicht vermischt werden (title-only Gruppierung war der Bug).

    generate_stats()' top_songs zeigt "Titel — Artist" (Statistics Menu
    UX & Output Optimization) - im Gegensatz zu
    generate_timeline_stats()' most_replayed_track NICHT durch
    services/family/family_challenge_service.py eingeschränkt (das
    vergleicht ausschließlich most_replayed_track[0], nicht top_songs),
    verifiziert per repoweitem Grep. Das Artist-Suffix macht kollidierende
    Einträge selbsterklärend statt zweier gleich aussehender Zeilen."""

    def test_same_title_different_artists_are_not_merged(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Artist A", "Song X", at=now - timedelta(days=1)),
            _entry("Artist A", "Song X", at=now - timedelta(days=2)),
            _entry("Artist B", "Song X", at=now - timedelta(days=3)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert len(stats["top_songs"]) == 2
        assert ("Song X — Artist A", 2) in stats["top_songs"]
        assert ("Song X — Artist B", 1) in stats["top_songs"]


class TestCalendarPeriodBounds:
    """Exakte Kalendergrenzen - Phase 19 des Audits (Woche/Monat/Jahr)."""

    def test_week_sunday_belongs_to_previous_monday(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        # Master-Prompt-Beispiel: 2026-09-13 (Sonntag) -> Woche beginnt 2026-09-07.
        start, end = calc._calendar_period_bounds(
            "week", now=datetime(2026, 9, 13, 10, 0)
        )
        assert start == datetime(2026, 9, 7)
        assert end == datetime(2026, 9, 14)

    def test_week_monday_belongs_to_itself(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        # Master-Prompt-Beispiel: 2026-09-14 (Montag) -> Woche beginnt 2026-09-14.
        start, end = calc._calendar_period_bounds(
            "week", now=datetime(2026, 9, 14, 8, 0)
        )
        assert start == datetime(2026, 9, 14)
        assert end == datetime(2026, 9, 21)

    def test_week_tuesday(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, _ = calc._calendar_period_bounds("week", now=datetime(2026, 9, 8, 8, 0))
        assert start == datetime(2026, 9, 7)

    def test_week_exact_start_boundary(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, _ = calc._calendar_period_bounds(
            "week", now=datetime(2026, 9, 7, 0, 0, 0)
        )
        assert start == datetime(2026, 9, 7)

    def test_week_exact_end_boundary(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        # Sonntag 23:59:59 gehoert noch zur Woche, die am Montag beginnt.
        _, end = calc._calendar_period_bounds(
            "week", now=datetime(2026, 9, 13, 23, 59, 59)
        )
        assert end == datetime(2026, 9, 14)

    def test_week_spans_month_change(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        # Woche 2026-09-28 (Mo) - 2026-10-04 (So) ueberspannt den Monatswechsel.
        start, end = calc._calendar_period_bounds(
            "week", now=datetime(2026, 9, 30, 12, 0)
        )
        assert start == datetime(2026, 9, 28)
        assert end == datetime(2026, 10, 5)

    def test_week_spans_year_change(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        # Woche 2026-12-28 (Mo) - 2027-01-03 (So) ueberspannt den Jahreswechsel.
        start, end = calc._calendar_period_bounds(
            "week", now=datetime(2026, 12, 30, 10, 0)
        )
        assert start == datetime(2026, 12, 28)
        assert end == datetime(2027, 1, 4)

    def test_month_first_day(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "month", now=datetime(2026, 6, 1, 0, 0, 1)
        )
        assert start == datetime(2026, 6, 1)
        assert end == datetime(2026, 7, 1)

    def test_month_last_day(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "month", now=datetime(2026, 6, 30, 23, 0)
        )
        assert start == datetime(2026, 6, 1)
        assert end == datetime(2026, 7, 1)

    def test_month_december_rolls_over_to_january_next_year(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "month", now=datetime(2026, 12, 15, 12, 0)
        )
        assert start == datetime(2026, 12, 1)
        assert end == datetime(2027, 1, 1)

    def test_month_february_leap_year(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "month", now=datetime(2024, 2, 29, 12, 0)
        )
        assert start == datetime(2024, 2, 1)
        assert end == datetime(2024, 3, 1)

    def test_month_february_non_leap_year(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "month", now=datetime(2026, 2, 15, 12, 0)
        )
        assert start == datetime(2026, 2, 1)
        assert end == datetime(2026, 3, 1)

    def test_year_january_first(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "year", now=datetime(2026, 1, 1, 0, 0, 1)
        )
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2027, 1, 1)

    def test_year_december_31st(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "year", now=datetime(2026, 12, 31, 23, 0)
        )
        assert start == datetime(2026, 1, 1)
        assert end == datetime(2027, 1, 1)

    def test_year_leap_year_still_spans_exactly_one_calendar_year(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "year", now=datetime(2024, 6, 15, 12, 0)
        )
        assert start == datetime(2024, 1, 1)
        assert end == datetime(2025, 1, 1)

    def test_today_bounds(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        start, end = calc._calendar_period_bounds(
            "today", now=datetime(2026, 9, 13, 15, 30, 0)
        )
        assert start == datetime(2026, 9, 13)
        assert end == datetime(2026, 9, 14)

    def test_unknown_period_raises(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        try:
            calc._calendar_period_bounds("decade")
            assert False, "sollte ValueError werfen"
        except ValueError:
            pass


class TestGenerateStatsBoundaryInclusion:
    """generate_stats() muss die von _calendar_period_bounds() berechneten
    Grenzen tatsaechlich anwenden - Entry-Ebene, nicht nur die reine
    Grenzberechnung."""

    def test_entry_one_second_before_month_start_is_excluded(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 7, 1, 10, 0, 0)
        repo.save(
            [_entry("Bausa", "Last Month", at=datetime(2026, 6, 30, 23, 59, 59))],
            "alice",
        )
        stats = calc.generate_stats("month", navidrome_username="alice", now=now)
        assert stats is not None
        assert stats["total_plays"] == 0

    def test_entry_exactly_at_month_start_is_included(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 7, 1, 10, 0, 0)
        repo.save(
            [_entry("Bausa", "This Month", at=datetime(2026, 7, 1, 0, 0, 0))],
            "alice",
        )
        stats = calc.generate_stats("month", navidrome_username="alice", now=now)
        assert stats is not None
        assert stats["total_plays"] == 1

    def test_entry_from_following_week_bucket_not_double_counted(self, tmp_path):
        """Woche endet exklusiv am naechsten Montag 00:00."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 10, 0, 0)  # Sonntag, Woche 07.-14.09.
        repo.save(
            [_entry("Bausa", "Next Week", at=datetime(2026, 9, 14, 0, 0, 0))],
            "alice",
        )
        stats = calc.generate_stats("week", navidrome_username="alice", now=now)
        assert stats is not None
        assert stats["total_plays"] == 0


class TestGetLastPlayedSong:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.get_last_played_song(navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.get_last_played_song(navidrome_username="alice") is None

    def test_returns_last_entry_with_timestamp(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Bausa", "Song A", at=now - timedelta(days=2)),
            _entry("Kollegah", "Song B", at=now - timedelta(days=1)),
        ]
        repo.save(history, "alice")

        last = calc.get_last_played_song(navidrome_username="alice")

        assert last["title"] == "Song B"
        assert "timestamp" in last


class TestGetPlayCountByArtist:
    def test_no_username_returns_zero(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.get_play_count_by_artist("Bausa", navidrome_username=None) == 0

    def test_counts_case_insensitively(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime.now()
        history = [
            _entry("Bausa", "Song A", at=now),
            _entry("Bausa", "Song B", at=now),
        ]
        repo.save(history, "alice")

        count = calc.get_play_count_by_artist(
            "bausa", navidrome_username="alice", period="month"
        )
        assert count == 2

    def test_unknown_artist_returns_zero(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", at=datetime.now())], "alice")

        count = calc.get_play_count_by_artist(
            "Some Other Artist", navidrome_username="alice", period="month"
        )
        assert count == 0


def _entry_with_genres(artist: str, title: str, genres: list, *, at: datetime):
    """NAV-F8: baut einen History-Eintrag mit dem strukturierten
    'genres'-Feld (List[str], bereits so wie PlayHistoryPoller es aus
    Navidromes [{'name': ...}, ...]-Response extrahiert - siehe
    generate_genre_stats()-Docstring: das ist die bevorzugte
    Datenquelle, NICHT das einfache 'genre'-Feld)."""
    entry = _entry(artist, title, at=at)
    entry["tracks"][0]["genres"] = genres
    return entry


class TestGenerateGenreStats:
    """NAV-F8 (Navidrome Menu System Audit): Top-N-Genres nach Plays,
    All-Time, V1 bewusst einfach (kein Kalenderzeitraum). Nutzt
    ausschließlich das strukturierte 'genres'-Feld, siehe
    generate_genre_stats()-Docstring."""

    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_genre_stats(navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_genre_stats(navidrome_username="alice") is None

    def test_counts_descending_by_plays(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry_with_genres("A", "Song 1", ["Hip-Hop"], at=now - timedelta(days=3)),
            _entry_with_genres("B", "Song 2", ["Hip-Hop"], at=now - timedelta(days=2)),
            _entry_with_genres("C", "Song 3", ["Pop"], at=now - timedelta(days=1)),
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result["top_genres"] == [("Hip-Hop", 2), ("Pop", 1)]
        assert result["total_plays_with_genre"] == 3

    def test_caps_at_top_n(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry_with_genres("A", f"Song {i}", [f"Genre{i}"], at=now - timedelta(days=i))
            for i in range(15)
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice", top_n=10)

        assert len(result["top_genres"]) == 10

    def test_entries_without_genres_are_skipped_not_counted_as_unbekannt(self, tmp_path):
        """Ältere Verlaufseinträge (vor NAV-F8) haben kein 'genres'-Feld -
        dürfen nicht in einer 'Unbekannt'-Sammelkategorie landen."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("A", "Song 1", at=now - timedelta(days=1)),  # kein genres-Feld
            _entry_with_genres("B", "Song 2", ["Pop"], at=now),
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result["top_genres"] == [("Pop", 1)]
        assert result["total_plays_with_genre"] == 1

    def test_history_without_any_genres_returns_empty_top_genres(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("A", "Song 1", at=datetime.now())], "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result is not None
        assert result["top_genres"] == []
        assert result["total_plays_with_genre"] == 0

    def test_multi_genre_track_credits_every_genre_once(self, tmp_path):
        """Kernanforderung NAV-F8: ein Multi-Genre-Track (z.B. Hip Hop +
        Deutschrap + Emo Rap + Cloud Rap) zaehlt fuer JEDES zugeordnete
        Genre einmal - die Summe der Genre-Counts kann daher groesser
        als total_plays_with_genre sein (analog top_artists_split)."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry_with_genres(
                "A", "Song 1",
                ["Hip Hop", "Deutschrap", "Emo Rap", "Cloud Rap"],
                at=now,
            ),
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result["total_plays_with_genre"] == 1
        assert dict(result["top_genres"]) == {
            "Hip Hop": 1, "Deutschrap": 1, "Emo Rap": 1, "Cloud Rap": 1,
        }
        assert sum(count for _, count in result["top_genres"]) == 4 > result["total_plays_with_genre"]

    def test_duplicate_genre_within_same_play_counted_once(self, tmp_path):
        """Doppelte Genre-Eintraege innerhalb DESSELBEN Plays duerfen
        nicht doppelt gezaehlt werden (Set-Dedup pro Play)."""
        calc, repo = make_calculator(tmp_path)
        history = [
            _entry_with_genres(
                "A", "Song 1", ["Hip Hop", "Hip Hop"], at=datetime(2026, 6, 15),
            ),
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result["top_genres"] == [("Hip Hop", 1)]
        assert result["total_plays_with_genre"] == 1

    def test_same_genre_across_different_plays_is_counted_per_play(self, tmp_path):
        """Dedup gilt nur INNERHALB eines Plays - dasselbe Genre in zwei
        verschiedenen Plays zaehlt beide Male."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry_with_genres("A", "Song 1", ["Hip Hop"], at=now - timedelta(days=1)),
            _entry_with_genres("B", "Song 2", ["Hip Hop"], at=now),
        ]
        repo.save(history, "alice")

        result = calc.generate_genre_stats(navidrome_username="alice")

        assert result["top_genres"] == [("Hip Hop", 2)]
        assert result["total_plays_with_genre"] == 2


class TestExportStatsToJson:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.export_stats_to_json(navidrome_username=None) is None

    def test_no_stats_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.export_stats_to_json(navidrome_username="alice") is None

    def test_writes_json_file_with_stats(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", at=datetime.now())], "alice")

        export_path = calc.export_stats_to_json(navidrome_username="alice")

        assert export_path is not None
        assert export_path.exists()
        assert "alice" in export_path.name


class TestUserIsolation:
    """Phase 12 des Audits: persoenliche Statistiken duerfen niemals
    fremde User-Daten anzeigen."""

    def test_generate_stats_never_mixes_two_users_history(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Artist A", "Alice Song", at=now)], "alice")
        repo.save(
            [
                _entry("Artist B", "Bob Song 1", at=now),
                _entry("Artist B", "Bob Song 2", at=now),
            ],
            "bob",
        )

        alice_stats = calc.generate_stats("month", navidrome_username="alice", now=now)
        bob_stats = calc.generate_stats("month", navidrome_username="bob", now=now)

        assert alice_stats["total_plays"] == 1
        assert bob_stats["total_plays"] == 2
        alice_songs = {label for label, _ in alice_stats["top_songs"]}
        bob_songs = {label for label, _ in bob_stats["top_songs"]}
        assert alice_songs.isdisjoint(bob_songs)

    def test_generate_timeline_stats_never_mixes_two_users_history(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Artist A", "Alice Song", at=now)], "alice")
        repo.save([_entry("Artist B", "Bob Song", at=now)], "bob")

        alice_timeline = calc.generate_timeline_stats(
            navidrome_username="alice", now=now
        )
        bob_timeline = calc.generate_timeline_stats(navidrome_username="bob", now=now)

        assert alice_timeline["today"]["top_artist"] == ("Artist A", 1)
        assert bob_timeline["today"]["top_artist"] == ("Artist B", 1)


class TestGenerateTimelineStats:
    """MASTER PHASE — MUSIC TIMELINE — FINAL CLOSURE: Timeline deckt nur
    noch "today" ab (kein "periods"-Wrapper, kein week/month mehr - siehe
    generate_timeline_stats()-Docstring). Woche-/Monats-Kalendergrenzen
    selbst bleiben unverändert und sind weiterhin über
    TestCalendarPeriodBounds abgedeckt."""

    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_timeline_stats(navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_timeline_stats(navidrome_username="alice") is None

    def test_only_invalid_timestamps_returns_none(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        bad = _entry("Bausa", "Song A", at=datetime(2026, 6, 15))
        bad["timestamp"] = "kaputt"
        repo.save([bad], "alice")
        assert calc.generate_timeline_stats(navidrome_username="alice") is None

    def test_return_has_no_periods_wrapper(self, tmp_path):
        """Section 5: Return enthält "navidrome_username"/"today", KEIN
        "periods"-Feld mehr."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert set(timeline.keys()) == {"navidrome_username", "today"}
        assert timeline["navidrome_username"] == "alice"
        assert "periods" not in timeline
        assert "week" not in timeline
        assert "month" not in timeline

    def test_today_track_count_for_single_play(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["track_count"] == 1

    def test_play_before_today_is_excluded(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save(
            [_entry("Bausa", "Yesterday", at=datetime(2026, 9, 12, 10, 0))], "alice"
        )

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["track_count"] == 0

    def test_today_starts_at_local_calendar_day_begin(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["period_start"] == datetime(2026, 9, 13)

    def test_today_ends_at_next_local_calendar_day_begin(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["period_end"] == datetime(2026, 9, 14)

    def test_same_title_different_artists_are_not_merged_in_timeline(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("Artist A", "Song X", at=now),
            _entry("Artist A", "Song X", at=now - timedelta(hours=1)),
            _entry("Artist B", "Song X", at=now - timedelta(hours=2)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        most_replayed = timeline["today"]["most_replayed_track"]

        # Klartext-Titel (kompatibel mit family_challenge_service.py) -
        # Artist A gewinnt mit 2 Plays gegen Artist B's 1 Play, beide
        # Zaehler blieben getrennt (kein Merge auf "Song X": 3).
        assert most_replayed == ("Song X", 2)

    def test_most_replayed_track_stays_a_title_plays_tuple(self, tmp_path):
        """Section 5/10: most_replayed_track bleibt intern (title, plays)
        - kein reiner String-Contract (Family-Challenge-Kompatibilität)."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("Clueso", "Mit dir alleine sein", at=now),
            _entry("Clueso", "Mit dir alleine sein", at=now - timedelta(hours=1)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        most_replayed = timeline["today"]["most_replayed_track"]

        assert most_replayed == ("Mit dir alleine sein", 2)
        assert isinstance(most_replayed, tuple)

    def test_new_track_detected_first_time_seen_today(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Brand New Song", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["new_track_count"] == 1

    def test_track_seen_before_today_is_not_counted_as_new(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            # Erstmals gehoert letzten Monat - nicht "neu" heute, obwohl
            # heute erneut gespielt (Identitaet ueber _identity_key("title")).
            _entry("Bausa", "Old Favorite", at=datetime(2026, 8, 1, 10, 0)),
            _entry("Bausa", "Old Favorite", at=now),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["new_track_count"] == 0

    def test_future_timestamp_is_excluded(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save(
            [_entry("Bausa", "From The Future", at=now + timedelta(days=10))], "alice"
        )

        assert calc.generate_timeline_stats(navidrome_username="alice", now=now) is None

    def test_missing_duration_counts_as_zero_listening_seconds(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now, duration=None)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["listening_seconds"] == 0

    def test_duration_zero_is_handled(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now, duration=0)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["listening_seconds"] == 0

    def test_large_duration_sums_correctly(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("Bausa", "Song A", at=now, duration=7200),
            _entry("Bausa", "Song B", at=now - timedelta(hours=1), duration=3600),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["listening_seconds"] == 10800

    def test_multiple_artists_and_albums_ranked_correctly(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("Clueso", "Song A", album="Album 1", at=now),
            _entry("Clueso", "Song B", album="Album 1", at=now - timedelta(hours=1)),
            _entry("Makko", "Song C", album="Album 2", at=now - timedelta(hours=2)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        today = timeline["today"]

        assert today["top_artist"] == ("Clueso", 2)
        assert today["top_album"] == ("Album 1", 2)

    def test_top_genre_none_when_no_genres_present(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["top_genre"] is None

    def test_top_genre_ranked_by_play_count(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry_with_genres("Bausa", "Song A", ["Hip-Hop"], at=now),
            _entry_with_genres(
                "Bausa", "Song B", ["Hip-Hop"], at=now - timedelta(hours=1)
            ),
            _entry_with_genres("Bausa", "Song C", ["Pop"], at=now - timedelta(hours=2)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["top_genre"] == ("Hip-Hop", 2)

    def test_top_genre_multi_genre_track_counts_each_genre_once(self, tmp_path):
        """Ein Play mit mehreren Genres traegt zu jedem Genre bei, aber
        ein Genre wird innerhalb DESSELBEN Plays nur einmal gezaehlt
        (Set-Dedup, dieselbe Regel wie generate_genre_stats())."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry_with_genres(
                "Bausa", "Song A", ["Hip-Hop", "Hip-Hop", "Deutschrap"], at=now
            ),
            _entry_with_genres(
                "Bausa", "Song B", ["Deutschrap"], at=now - timedelta(hours=1)
            ),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        # "Hip-Hop" nur 1x (ein Play trotz Duplikat im "genres"-Feld),
        # "Deutschrap" 2x (zwei separate Plays) -> Deutschrap gewinnt.
        assert timeline["today"]["top_genre"] == ("Deutschrap", 2)


class TestSplitArtists:
    """Statistics UX & Architecture (v Final), Abschnitt 5/27: Artist-
    Splitting NUR an ' • ' und ' & ', explizit NICHT an '/', ',',
    'feat.', 'ft.'."""

    def test_splits_on_bullet_separator(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("makko • The Chainsmokers") == [
            "makko", "The Chainsmokers",
        ]

    def test_splits_on_ampersand_separator(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Artist A & Artist B") == ["Artist A", "Artist B"]

    def test_slash_is_not_split(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Miksu/Macloud") == ["Miksu/Macloud"]

    def test_comma_is_not_split(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Artist, Artist") == ["Artist, Artist"]

    def test_feat_is_not_split(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Artist feat. Artist") == ["Artist feat. Artist"]

    def test_ft_is_not_split(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Artist ft. Artist") == ["Artist ft. Artist"]

    def test_empty_or_missing_becomes_unbekannt(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("") == ["Unbekannt"]
        assert calc._split_artists(None) == ["Unbekannt"]

    def test_split_artists_breaks_ampersand_band_names(self, tmp_path):
        """Akzeptierter Grenzfall (docs/FINDINGS_INDEX.md): ein Bandname,
        der selbst '&' enthält (z. B. "Simon & Garfunkel"), wird nach den
        vorgegebenen Splitting-Regeln fälschlich in zwei Artists zerlegt.
        Bewusst akzeptiert, nicht behoben - die Trennermenge (' • '/' & ')
        ist im Master-Prompt "Statistics UX & Architecture (v Final)"
        explizit und abschließend definiert, eine Ausnahmeliste für
        bekannte Bandnamen wäre unwartbar (welche Namen? nach welcher
        Quelle gepflegt?). Echte Lösung, falls dies je zum echten Problem
        wird: kanonische Artist-Auflösung über die im Track-Dict bereits
        vorhandene Navidrome-`id` statt String-Heuristik. Dieser Test
        pinnt das akzeptierte (nicht das wünschenswerte) Verhalten als
        Regressionsschutz - schlägt er künftig fehl, hat sich die
        Splitting-Logik geändert und die Akzeptanz-Entscheidung in
        docs/FINDINGS_INDEX.md muss neu bewertet werden."""
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("Simon & Garfunkel") == ["Simon", "Garfunkel"]

    def test_three_way_split(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc._split_artists("A • B & C") == ["A", "B", "C"]


class TestGenerateStatsAdditiveFields:
    """Statistics UX & Architecture (v Final), Abschnitt 3/4/5:
    top_songs_detailed/top_artists_split sind ADDITIV - top_songs/
    top_artists bleiben unverändert (Rückwärtskompatibilität)."""

    def test_existing_fields_still_present_and_unchanged(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["top_songs"] == [("Song A — Bausa", 1)]
        assert stats["top_artists"] == [("Bausa", 1)]

    def test_top_songs_detailed_has_no_string_combination(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["top_songs_detailed"] == [("Song A", "Bausa", 1)]

    def test_top_songs_detailed_keeps_same_artist_distinct_from_different_artist(
        self, tmp_path
    ):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Artist A", "Song X", at=now - timedelta(days=1)),
            _entry("Artist B", "Song X", at=now - timedelta(days=2)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert ("Song X", "Artist A", 1) in stats["top_songs_detailed"]
        assert ("Song X", "Artist B", 1) in stats["top_songs_detailed"]

    def test_top_artists_split_splits_before_aggregation(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("makko • The Chainsmokers", "Song A", at=now - timedelta(days=1)),
            _entry("The Chainsmokers", "Song B", at=now - timedelta(days=2)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        split_map = dict(stats["top_artists_split"])
        assert split_map["makko"] == 1
        assert split_map["The Chainsmokers"] == 2

    def test_split_artist_sum_can_exceed_total_plays(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save(
            [_entry("Artist A & Artist B", "Song A", at=now - timedelta(days=1))],
            "alice",
        )

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["total_plays"] == 1
        assert sum(c for _, c in stats["top_artists_split"]) == 2

    def test_missing_artist_becomes_unbekannt(self, tmp_path):
        """Master-Prompt Abschnitt 10/27: fehlender Artist -> 'Unbekannt',
        sowohl in top_songs_detailed als auch top_artists_split."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("", "Song A", at=now - timedelta(days=1))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["top_songs_detailed"] == [("Song A", "Unbekannt", 1)]
        assert stats["top_artists_split"] == [("Unbekannt", 1)]

    def test_empty_period_has_empty_additive_fields(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Old Song", at=now - timedelta(days=400))], "alice")

        stats = calc.generate_stats("month", navidrome_username="alice", now=now)

        assert stats["top_songs_detailed"] == []
        assert stats["top_artists_split"] == []


class TestGenerateYearStats:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_year_stats(navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.generate_year_stats(navidrome_username="alice") is None

    def test_period_bounds_match_calendar_period_bounds(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=now)], "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["year"] == 2026
        assert stats["period_start"] == datetime(2026, 1, 1)
        assert stats["period_end"] == datetime(2027, 1, 1)

    def test_monthly_plays_has_exactly_12_entries_chronological(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=datetime(2026, 3, 10))], "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert len(stats["monthly_plays"]) == 12
        assert [name for name, _ in stats["monthly_plays"]] == [
            "Januar", "Februar", "März", "April", "Mai", "Juni",
            "Juli", "August", "September", "Oktober", "November", "Dezember",
        ]
        assert stats["monthly_plays"][2] == ("März", 1)
        assert stats["monthly_plays"][0] == ("Januar", 0)

    def test_total_plays_equals_sum_of_monthly_plays(self, tmp_path):
        """Master-Prompt Abschnitt 16.1: verbindliche Invariante."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Bausa", "Song A", at=datetime(2026, 1, 5)),
            _entry("Bausa", "Song B", at=datetime(2026, 1, 20)),
            _entry("Bausa", "Song C", at=datetime(2026, 6, 1)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_plays"] == sum(p for _, p in stats["monthly_plays"])
        assert stats["total_plays"] == 3

    def test_future_and_invalid_timestamps_excluded_from_both_total_and_monthly(
        self, tmp_path
    ):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        bad = _entry("Bausa", "Bad", at=datetime(2026, 2, 1))
        bad["timestamp"] = "not-a-timestamp"
        history = [
            _entry("Bausa", "Good", at=datetime(2026, 3, 1)),
            bad,
            _entry("Bausa", "Future", at=now + timedelta(days=5)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_plays"] == 1
        assert sum(p for _, p in stats["monthly_plays"]) == 1

    def test_total_songs_uses_identity_key_not_title_only(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Artist A", "Song X", at=datetime(2026, 1, 1)),
            _entry("Artist B", "Song X", at=datetime(2026, 2, 1)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_songs"] == 2

    def test_total_artists_uses_split_identities(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("makko • The Chainsmokers", "Song A", at=datetime(2026, 1, 1)),
            _entry("makko", "Song B", at=datetime(2026, 2, 1)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_artists"] == 2  # makko, The Chainsmokers

    def test_total_albums_uses_identity_key(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Artist A", "Song 1", album="Greatest Hits", at=datetime(2026, 1, 1)),
            _entry("Artist B", "Song 2", album="Greatest Hits", at=datetime(2026, 2, 1)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_albums"] == 2

    def test_totals_derived_from_full_history_not_top10(self, tmp_path):
        """KPIs duerfen NICHT aus den (auf 10 gekappten) Top-Listen
        abgeleitet werden."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Bausa", f"Song {i}", at=datetime(2026, 1, 1))
            for i in range(15)
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["total_songs"] == 15
        assert len(stats["top_songs_detailed"]) == 10

    def test_strongest_month_is_month_with_most_plays(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = (
            [_entry("Bausa", f"J{i}", at=datetime(2026, 1, 1)) for i in range(2)]
            + [_entry("Bausa", f"F{i}", at=datetime(2026, 2, 1)) for i in range(5)]
        )
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["highlights"]["strongest_month"]["name"] == "Februar"
        assert stats["highlights"]["strongest_month"]["plays"] == 5

    def test_strongest_month_tie_break_is_chronologically_first(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = (
            [_entry("Bausa", f"F{i}", at=datetime(2026, 2, 1)) for i in range(3)]
            + [_entry("Bausa", f"M{i}", at=datetime(2026, 3, 1)) for i in range(3)]
        )
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["highlights"]["strongest_month"]["name"] == "Februar"

    def test_delta_pct_none_when_fewer_than_three_active_months(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = [
            _entry("Bausa", "A", at=datetime(2026, 1, 1)),
            _entry("Bausa", "B", at=datetime(2026, 2, 1)),
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["highlights"]["strongest_month"]["delta_pct"] is None

    def test_delta_pct_computed_with_three_or_more_active_months(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        history = (
            [_entry("Bausa", f"J{i}", at=datetime(2026, 1, 1)) for i in range(4)]
            + [_entry("Bausa", f"F{i}", at=datetime(2026, 2, 1)) for i in range(4)]
            + [_entry("Bausa", f"M{i}", at=datetime(2026, 3, 1)) for i in range(10)]
        )
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)
        # total=18, average=18/12=1.5, strongest=10 -> (10-1.5)/1.5*100 = 566.67 -> 567
        assert stats["highlights"]["strongest_month"]["delta_pct"] == 567
        assert stats["highlights"]["strongest_month"]["delta_pct"] >= 0

    def test_delta_pct_zero_on_exact_tie_with_average(self, tmp_path):
        """12 Monate mit je gleich vielen Plays -> stärkster Monat ==
        Durchschnitt -> delta_pct == 0."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 12, 15, 12, 0, 0)
        history = [
            _entry("Bausa", f"T{month}", at=datetime(2026, month, 1))
            for month in range(1, 13)
        ]
        repo.save(history, "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats["highlights"]["strongest_month"]["delta_pct"] == 0

    def test_delta_pct_none_when_total_plays_is_zero(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        # Historie existiert, aber ausserhalb des Jahres 2026.
        repo.save([_entry("Bausa", "Old", at=datetime(2024, 1, 1))], "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert stats is not None
        assert stats["total_plays"] == 0
        assert stats["highlights"]["strongest_month"]["delta_pct"] is None

    def test_highlights_contains_only_strongest_month(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 6, 15, 12, 0, 0)
        repo.save([_entry("Bausa", "Song A", at=datetime(2026, 3, 1))], "alice")

        stats = calc.generate_year_stats(navidrome_username="alice", now=now)

        assert set(stats["highlights"].keys()) == {"strongest_month"}
        assert set(stats["highlights"]["strongest_month"].keys()) == {
            "name", "plays", "delta_pct",
        }


class TestTimelineArtistSplit:
    """Music Timeline Consistency & UX, Abschnitt 2/7.2: generate_timeline_stats()
    muss denselben Artist-Split wie generate_stats() verwenden - vorher
    zaehlte ein Combo-String wie 'A • B • C' als EIN Artist."""

    def test_combo_artist_counts_as_two_split_artists(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save(
            [_entry("makko • The Chainsmokers", "Song A", at=now)], "alice"
        )

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        today = timeline["today"]

        # Beide Artists erhalten 1 Play - keiner der beiden ist der
        # unveraenderte Combo-String.
        assert today["top_artist"] in [("makko", 1), ("The Chainsmokers", 1)]

    def test_three_way_combo_counts_as_three_artists(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("Toobrokeforfiji • SIN Davis • makko", "Song A", at=now),
            _entry("makko", "Song B", at=now - timedelta(hours=1)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        today = timeline["today"]

        # makko kommt in beiden Plays vor (Combo + Solo) -> 2 Plays,
        # gewinnt gegen Toobrokeforfiji/SIN Davis mit je 1 Play.
        assert today["top_artist"] == ("makko", 2)

    def test_slash_artist_not_split_in_timeline(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save([_entry("Miksu/Macloud", "Song A", at=now)], "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["top_artist"] == ("Miksu/Macloud", 1)

    def test_ampersand_artist_split_in_timeline(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        history = [
            _entry("A & B", "Song A", at=now),
            _entry("A", "Song B", at=now - timedelta(hours=1)),
        ]
        repo.save(history, "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        assert timeline["today"]["top_artist"] == ("A", 2)

    def test_top_album_and_most_replayed_track_remain_unsplit(self, tmp_path):
        """most_replayed_track/top_album duerfen NICHT gesplittet werden
        (Family-Challenge-Kompatibilitaet, siehe _identity_key()-Docstring)."""
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save(
            [_entry("A & B", "Song X", album="Album Y", at=now)], "alice"
        )

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)
        today = timeline["today"]

        assert today["most_replayed_track"] == ("Song X", 1)
        assert today["top_album"] == ("Album Y", 1)


class TestTimelineConsistencyWithPeriodReview:
    """MASTER PHASE — MUSIC TIMELINE — FINAL CLOSURE: Timeline berechnet
    nur noch "today" - ein direkter Cross-Check gegen generate_stats()
    ("week"/"month") ist damit nicht mehr möglich/sinnvoll (generate_stats()
    kennt keine "today"-Periode). Die frühere
    week/month-Konsistenzprüfung (Music Timeline Consistency & UX,
    Abschnitt 7.1) entfällt daher ersatzlos - beide Funktionen nutzen
    weiterhin denselben _split_artists()-Helper (siehe
    TestTimelineArtistSplit/TestGenerateStatsAdditiveFields), nur nicht
    mehr für denselben Zeitraum vergleichbar. Verbleibender Test prüft
    die "today"-Aggregation selbst gegen eine manuell berechnete
    Erwartung."""

    def _history_with_combo_artists(self, now):
        return [
            _entry("Clueso", "Song A", at=now),
            _entry("Clueso", "Song B", at=now - timedelta(hours=1)),
            _entry("Clueso • makko", "Song C", at=now - timedelta(hours=2)),
            _entry("makko", "Song D", at=now - timedelta(hours=3)),
        ]

    def test_timeline_today_top_artist_uses_split_artist_aggregation(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        now = datetime(2026, 9, 13, 15, 0, 0)
        repo.save(self._history_with_combo_artists(now), "alice")

        timeline = calc.generate_timeline_stats(navidrome_username="alice", now=now)

        # Clueso: 2 Solo-Plays + 1 Combo-Play = 3; makko: 1 Combo + 1 Solo = 2.
        assert timeline["today"]["top_artist"] == ("Clueso", 3)
