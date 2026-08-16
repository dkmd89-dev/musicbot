"""
Characterization-Tests fuer StatistikService (services/statistik_service.py),
Phase 2 - bislang 0 Tests, obwohl es den kompletten History/Stats-Cache-
Bereich aus CLAUDE.md Abschnitt 14 implementiert.

CHARTS_DIR/USER_HISTORY_DIR sind Klassenattribute (an Config.STATS_DIR/
Config.PLAY_HISTORY_FILE gebunden bei Modul-Import) - werden hier per
monkeypatch VOR der Konstruktion auf tmp_path umgebogen.

Nur die synchronen, dateibasierten Methoden werden getestet
(_load_history, _save_history, _cleanup_old_entries, generate_stats,
get_play_count_by_artist). _run_history_updater() (Endlosschleife) und
start_polling() werden bewusst NICHT aufgerufen.
"""

import json
from datetime import datetime, timedelta

import pytest

from services.statistik_service import StatistikService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(StatistikService, "CHARTS_DIR", tmp_path / "stats_charts")
    monkeypatch.setattr(StatistikService, "USER_HISTORY_DIR", tmp_path / "user_histories")
    return StatistikService()


def _history_file(service, username: str):
    return service.USER_HISTORY_DIR / f"play_history_{username}.json"


def _entry(artist: str, title: str, album: str = "Some Album", days_ago: int = 0):
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": timestamp,
        "tracks": [
            {
                "title": title,
                "artist": artist,
                "album": album,
                "id": "1",
                "duration": 180,
                "player": "test-player",
                "username": "alice",
            }
        ],
    }


class TestLoadHistory:
    def test_missing_file_returns_empty_list(self, service):
        assert service._load_history("alice") == []

    def test_empty_file_returns_empty_list(self, service):
        _history_file(service, "alice").write_bytes(b"")
        assert service._load_history("alice") == []

    def test_valid_file_is_parsed(self, service):
        history = [_entry("Bausa", "Song A")]
        _history_file(service, "alice").write_text(
            json.dumps(history), encoding="utf-8"
        )
        assert service._load_history("alice") == history

    def test_corrupt_file_is_renamed_and_returns_empty_list(self, service):
        history_file = _history_file(service, "alice")
        history_file.write_text("{not valid json", encoding="utf-8")

        result = service._load_history("alice")

        assert result == []
        assert not history_file.exists()
        corrupt_files = list(service.USER_HISTORY_DIR.glob("*.corrupt.*"))
        assert len(corrupt_files) == 1


class TestSaveHistory:
    def test_save_then_load_roundtrips(self, service):
        history = [_entry("Bausa", "Song A"), _entry("Kollegah", "Song B")]
        service._save_history(history, "alice")
        assert service._load_history("alice") == history


class TestCleanupOldEntries:
    def test_old_entries_beyond_retention_are_removed(self, service, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "PLAY_HISTORY_RETENTION_DAYS", 30)

        history = [
            _entry("Bausa", "Recent Song", days_ago=5),
            _entry("Kollegah", "Old Song", days_ago=400),
        ]
        service._save_history(history, "alice")

        service._cleanup_old_entries("alice")

        remaining = service._load_history("alice")
        assert len(remaining) == 1
        assert remaining[0]["tracks"][0]["title"] == "Recent Song"

    def test_missing_timestamp_defaults_to_epoch_and_is_removed(
        self, service, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "PLAY_HISTORY_RETENTION_DAYS", 30)

        entry_without_timestamp = _entry("Bausa", "No Timestamp Song")
        del entry_without_timestamp["timestamp"]
        service._save_history([entry_without_timestamp], "alice")

        service._cleanup_old_entries("alice")

        assert service._load_history("alice") == []

    def test_no_entries_removed_leaves_file_untouched(self, service, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "PLAY_HISTORY_RETENTION_DAYS", 30)

        history = [_entry("Bausa", "Recent Song", days_ago=1)]
        service._save_history(history, "alice")

        service._cleanup_old_entries("alice")

        assert service._load_history("alice") == history


class TestGenerateStats:
    def test_no_username_returns_none(self, service):
        assert service.generate_stats("month", navidrome_username=None) is None

    def test_no_history_returns_none(self, service):
        assert service.generate_stats("month", navidrome_username="alice") is None

    def test_top_artists_ranked_by_play_count(self, service):
        history = [
            _entry("Bausa", "Song A", days_ago=1),
            _entry("Bausa", "Song B", days_ago=2),
            _entry("Kollegah", "Song C", days_ago=3),
        ]
        service._save_history(history, "alice")

        stats = service.generate_stats("month", navidrome_username="alice")

        assert stats["total_plays"] == 3
        assert stats["top_artists"][0] == ("Bausa", 2)

    def test_entries_outside_period_are_excluded(self, service):
        history = [_entry("Bausa", "Old Song", days_ago=400)]
        service._save_history(history, "alice")

        stats = service.generate_stats("month", navidrome_username="alice")

        assert stats is None


class TestGetPlayCountByArtist:
    def test_no_username_returns_zero(self, service):
        assert service.get_play_count_by_artist("Bausa", navidrome_username=None) == 0

    def test_counts_case_insensitively(self, service):
        history = [_entry("Bausa", "Song A", days_ago=1), _entry("Bausa", "Song B", days_ago=1)]
        service._save_history(history, "alice")

        count = service.get_play_count_by_artist(
            "bausa", navidrome_username="alice", period="month"
        )
        assert count == 2

    def test_unknown_artist_returns_zero(self, service):
        history = [_entry("Bausa", "Song A", days_ago=1)]
        service._save_history(history, "alice")

        count = service.get_play_count_by_artist(
            "Some Other Artist", navidrome_username="alice", period="month"
        )
        assert count == 0
