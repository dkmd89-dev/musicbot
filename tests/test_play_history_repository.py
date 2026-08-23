"""
Unit-Tests für PlayHistoryRepository (services/statistik/play_history_repository.py)
— extrahiert aus StatistikService (ARCH-003, P-6). Direkter Test der neuen,
isoliert konstruierbaren Klasse (ohne Umweg über die StatistikService-Fassade),
als Beweis echter Testbarkeit der neuen Service-Grenze.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock

from services.statistik.play_history_repository import PlayHistoryRepository


def make_repository(tmp_path):
    return PlayHistoryRepository(tmp_path, logger=Mock())


def _entry(artist: str, title: str, days_ago: int = 0):
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": timestamp,
        "tracks": [{"title": title, "artist": artist, "album": "Album", "id": "1"}],
    }


class TestSanitizeUsername:
    def test_removes_illegal_filename_characters(self, tmp_path):
        repo = make_repository(tmp_path)
        assert repo.sanitize_username("user/name:test") == "user_name_test"

    def test_allows_safe_characters(self, tmp_path):
        repo = make_repository(tmp_path)
        assert repo.sanitize_username("Alice_123.test") == "Alice_123.test"


class TestHistoryFileForUser:
    def test_builds_expected_path(self, tmp_path):
        repo = make_repository(tmp_path)
        assert repo.history_file_for_user("alice") == tmp_path / "play_history_alice.json"


class TestLoad:
    def test_missing_file_returns_empty_list(self, tmp_path):
        repo = make_repository(tmp_path)
        assert repo.load("alice") == []

    def test_empty_file_returns_empty_list(self, tmp_path):
        repo = make_repository(tmp_path)
        repo.history_file_for_user("alice").write_bytes(b"")
        assert repo.load("alice") == []

    def test_valid_file_is_parsed(self, tmp_path):
        repo = make_repository(tmp_path)
        history = [_entry("Bausa", "Song A")]
        repo.history_file_for_user("alice").write_text(
            json.dumps(history), encoding="utf-8"
        )
        assert repo.load("alice") == history

    def test_corrupt_file_is_renamed_and_returns_empty_list(self, tmp_path):
        repo = make_repository(tmp_path)
        history_file = repo.history_file_for_user("alice")
        history_file.write_text("{not valid json", encoding="utf-8")

        result = repo.load("alice")

        assert result == []
        assert not history_file.exists()
        assert len(list(tmp_path.glob("*.corrupt.*"))) == 1


class TestSave:
    def test_save_then_load_roundtrips(self, tmp_path):
        repo = make_repository(tmp_path)
        history = [_entry("Bausa", "Song A"), _entry("Kollegah", "Song B")]
        repo.save(history, "alice")
        assert repo.load("alice") == history


class TestCleanupOldEntries:
    def test_old_entries_beyond_explicit_retention_are_removed(self, tmp_path):
        repo = make_repository(tmp_path)
        history = [
            _entry("Bausa", "Recent Song", days_ago=5),
            _entry("Kollegah", "Old Song", days_ago=400),
        ]
        repo.save(history, "alice")

        repo.cleanup_old_entries("alice", retention_days=30)

        remaining = repo.load("alice")
        assert len(remaining) == 1
        assert remaining[0]["tracks"][0]["title"] == "Recent Song"

    def test_default_retention_reads_config_live(self, tmp_path, monkeypatch):
        """
        retention_days=None muss Config.PLAY_HISTORY_RETENTION_DAYS zum
        AUFRUFZEITPUNKT lesen (nicht beim Konstruieren) - identisch zum
        Ursprungsverhalten in statistik_service.py.
        """
        from config import Config

        monkeypatch.setattr(Config, "PLAY_HISTORY_RETENTION_DAYS", 30)
        repo = make_repository(tmp_path)
        history = [_entry("Bausa", "Old Song", days_ago=400)]
        repo.save(history, "alice")

        repo.cleanup_old_entries("alice")

        assert repo.load("alice") == []

    def test_missing_timestamp_defaults_to_epoch_and_is_removed(self, tmp_path):
        repo = make_repository(tmp_path)
        entry_without_timestamp = _entry("Bausa", "No Timestamp Song")
        del entry_without_timestamp["timestamp"]
        repo.save([entry_without_timestamp], "alice")

        repo.cleanup_old_entries("alice", retention_days=30)

        assert repo.load("alice") == []

    def test_no_entries_removed_leaves_file_untouched(self, tmp_path):
        repo = make_repository(tmp_path)
        history = [_entry("Bausa", "Recent Song", days_ago=1)]
        repo.save(history, "alice")

        repo.cleanup_old_entries("alice", retention_days=30)

        assert repo.load("alice") == history

    def test_empty_history_is_a_noop(self, tmp_path):
        repo = make_repository(tmp_path)
        repo.cleanup_old_entries("alice", retention_days=30)
        assert repo.load("alice") == []
