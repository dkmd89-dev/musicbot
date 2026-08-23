"""
Unit-Tests für StatisticsCalculator (services/statistik/statistics_calculator.py)
— extrahiert aus StatistikService (ARCH-003, P-6). Nutzt ein echtes
PlayHistoryRepository auf tmp_path als Datenquelle (reine Datei-Logik,
kein externer Service - Regel 10-artig), direkter Test der neuen Klasse
ohne Umweg über die StatistikService-Fassade.
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


def _entry(artist: str, title: str, album: str = "Album", days_ago: int = 0):
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": timestamp,
        "tracks": [{"title": title, "artist": artist, "album": album, "id": "1"}],
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
        history = [
            _entry("Bausa", "Song A", days_ago=1),
            _entry("Bausa", "Song B", days_ago=2),
            _entry("Kollegah", "Song C", days_ago=3),
        ]
        repo.save(history, "alice")

        stats = calc.generate_stats("month", navidrome_username="alice")

        assert stats["total_plays"] == 3
        assert stats["top_artists"][0] == ("Bausa", 2)

    def test_entries_outside_period_are_excluded(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Old Song", days_ago=400)], "alice")

        assert calc.generate_stats("month", navidrome_username="alice") is None

    def test_invalid_timestamp_entry_is_skipped_not_crashed(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        bad_entry = _entry("Bausa", "Song A", days_ago=1)
        bad_entry["timestamp"] = "not-a-timestamp"
        repo.save([bad_entry], "alice")

        assert calc.generate_stats("month", navidrome_username="alice") is None


class TestGetLastPlayedSong:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.get_last_played_song(navidrome_username=None) is None

    def test_no_history_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.get_last_played_song(navidrome_username="alice") is None

    def test_returns_last_entry_with_timestamp(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        history = [
            _entry("Bausa", "Song A", days_ago=2),
            _entry("Kollegah", "Song B", days_ago=1),
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
        history = [
            _entry("Bausa", "Song A", days_ago=1),
            _entry("Bausa", "Song B", days_ago=1),
        ]
        repo.save(history, "alice")

        count = calc.get_play_count_by_artist(
            "bausa", navidrome_username="alice", period="month"
        )
        assert count == 2

    def test_unknown_artist_returns_zero(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", days_ago=1)], "alice")

        count = calc.get_play_count_by_artist(
            "Some Other Artist", navidrome_username="alice", period="month"
        )
        assert count == 0


class TestExportStatsToJson:
    def test_no_username_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.export_stats_to_json(navidrome_username=None) is None

    def test_no_stats_returns_none(self, tmp_path):
        calc, _ = make_calculator(tmp_path)
        assert calc.export_stats_to_json(navidrome_username="alice") is None

    def test_writes_json_file_with_stats(self, tmp_path):
        calc, repo = make_calculator(tmp_path)
        repo.save([_entry("Bausa", "Song A", days_ago=1)], "alice")

        export_path = calc.export_stats_to_json(navidrome_username="alice")

        assert export_path is not None
        assert export_path.exists()
        assert "alice" in export_path.name
