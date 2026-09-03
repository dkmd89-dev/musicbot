"""
Download-Verlauf (docs/FINDINGS_INDEX.md, "Download-Verlauf/Erneut-
versuchen, persistenter Speicher"): Tests für
services/downloader/download_history.py::DownloadHistoryStore.

Struktureller Zwilling zu tests/test_duplicate_cache_atomic_persistence.py
(DuplicateCache) - gleiches Muster: pro-Test-tmp_path-Fixture, Persistenz
über eine frische Instanz verifiziert statt nur In-Memory-State.
"""

import json

import pytest

from services.downloader.download_history import (
    MAX_ENTRIES_PER_CHAT,
    DownloadHistoryEntry,
    DownloadHistoryStore,
)


@pytest.fixture
def store(tmp_path):
    return DownloadHistoryStore(cache_dir=str(tmp_path / "download_history"))


def _add(store, chat_id=123, url="https://youtu.be/ABC", title="Song", artist="Artist", status="success"):
    store.add_entry(chat_id, url=url, title=title, artist=artist, status=status)


class TestAddEntryAndGetRecent:
    def test_single_entry_roundtrips(self, store):
        _add(store, title="Erster Track", artist="Erster Artist")
        recent = store.get_recent(123)
        assert len(recent) == 1
        assert recent[0].title == "Erster Track"
        assert recent[0].artist == "Erster Artist"
        assert recent[0].status == "success"
        assert recent[0].url == "https://youtu.be/ABC"
        assert recent[0].timestamp  # nicht leer

    def test_newest_entry_first(self, store):
        _add(store, title="Alt")
        _add(store, title="Neu")
        recent = store.get_recent(123)
        assert [e.title for e in recent] == ["Neu", "Alt"]

    def test_different_chats_are_isolated(self, store):
        _add(store, chat_id=1, title="Chat-1-Track")
        _add(store, chat_id=2, title="Chat-2-Track")
        assert [e.title for e in store.get_recent(1)] == ["Chat-1-Track"]
        assert [e.title for e in store.get_recent(2)] == ["Chat-2-Track"]

    def test_unknown_chat_returns_empty_list(self, store):
        assert store.get_recent(999) == []

    def test_missing_title_artist_default_to_unbekannt(self, store):
        store.add_entry(1, url="https://youtu.be/X", title="", artist="", status="failed")
        recent = store.get_recent(1)
        assert recent[0].title == "Unbekannt"
        assert recent[0].artist == "Unbekannt"


class TestCapPerChat:
    def test_cap_removes_oldest_first(self, store):
        for i in range(MAX_ENTRIES_PER_CHAT + 5):
            _add(store, title=f"Track {i}")
        recent = store.get_recent(123, limit=MAX_ENTRIES_PER_CHAT)
        assert len(recent) == MAX_ENTRIES_PER_CHAT
        # Die letzten MAX_ENTRIES_PER_CHAT hinzugefuegten muessen erhalten
        # sein (neueste zuerst), die aeltesten 5 sind verdraengt.
        expected_titles = [
            f"Track {i}" for i in range(MAX_ENTRIES_PER_CHAT + 4, 4, -1)
        ]
        assert [e.title for e in recent] == expected_titles

    def test_cap_is_per_chat_not_global(self, store):
        for i in range(MAX_ENTRIES_PER_CHAT):
            _add(store, chat_id=1, title=f"C1-{i}")
        _add(store, chat_id=2, title="C2-only")
        assert len(store.get_recent(1)) == MAX_ENTRIES_PER_CHAT
        assert len(store.get_recent(2)) == 1


class TestPersistence:
    def test_entries_survive_reload_from_disk(self, store):
        _add(store, title="Persistenter Track")
        reloaded = DownloadHistoryStore(cache_dir=str(store.cache_path))
        recent = reloaded.get_recent(123)
        assert len(recent) == 1
        assert recent[0].title == "Persistenter Track"

    def test_written_file_is_valid_json(self, store):
        _add(store)
        assert store.history_file.exists()
        with open(store.history_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "123" in data
        assert len(data["123"]) == 1

    def test_missing_file_on_first_load_is_not_an_error(self, tmp_path):
        # Kein vorheriger add_entry() - Datei existiert noch nicht.
        fresh = DownloadHistoryStore(cache_dir=str(tmp_path / "fresh_history"))
        assert fresh.get_recent(1) == []

    def test_corrupted_file_falls_back_to_empty_without_raising(self, tmp_path):
        cache_dir = tmp_path / "corrupt_history"
        cache_dir.mkdir(parents=True)
        (cache_dir / "download_history.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        broken = DownloadHistoryStore(cache_dir=str(cache_dir))
        assert broken.get_recent(1) == []


class TestGetEntryByPosition:
    def test_position_zero_is_newest(self, store):
        _add(store, title="Alt")
        _add(store, title="Neu")
        entry = store.get_entry_by_position(123, 0)
        assert entry.title == "Neu"

    def test_position_one_is_second_newest(self, store):
        _add(store, title="Alt")
        _add(store, title="Neu")
        entry = store.get_entry_by_position(123, 1)
        assert entry.title == "Alt"

    def test_out_of_range_position_returns_none(self, store):
        _add(store, title="Einziger")
        assert store.get_entry_by_position(123, 5) is None
        assert store.get_entry_by_position(123, -1) is None

    def test_unknown_chat_returns_none(self, store):
        assert store.get_entry_by_position(999, 0) is None


class TestDownloadHistoryEntryRoundtrip:
    def test_to_dict_from_dict_roundtrip(self):
        entry = DownloadHistoryEntry(
            url="https://youtu.be/X",
            title="T",
            artist="A",
            status="cancelled",
            timestamp="2026-09-03T12:00:00",
        )
        restored = DownloadHistoryEntry.from_dict(entry.to_dict())
        assert restored == entry
