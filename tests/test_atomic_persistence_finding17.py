"""
Regressionstests für Finding #17 (INV-02): atomare Persistenz in
utils/lyrics_cache.py::LyricsCache.store() und
services/statistik/play_history_repository.py::PlayHistoryRepository.save().

Vorher schrieben beide per direktem open(path, "w") + json.dump() - ein
Abbruch mitten im Schreiben hinterließ eine leere/abgeschnittene
Zieldatei. Jetzt: write-tmp + os.replace() (Muster wie
MetadataCache.store()/DownloadHistory._write_json_atomic()).

Der Abbruch wird simuliert, indem json.dump() einen Teil schreibt und
dann eine Exception wirft - vor dem Fix landete dieser Teil direkt in der
Zieldatei.
"""

import json
from unittest.mock import Mock

import pytest

from services.statistik.play_history_repository import PlayHistoryRepository
from utils.lyrics_cache import LyricsCache


def _interrupting_dump(exc):
    def dump(obj, fp, *args, **kwargs):
        fp.write('{"partial": ')
        raise exc

    return dump


def _leftover_tmp_files(directory):
    return [p for p in directory.iterdir() if ".tmp_" in p.name]


# ─────────────────────────────────────────────────────────────────────
# LyricsCache.store()
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def lyrics_cache(tmp_path):
    return LyricsCache(cache_dir=tmp_path)


def _lyrics_file(cache, artist, title):
    return cache.cache_path / f"{cache._get_key(artist, title)}.json"


class TestLyricsCacheAtomicStore:
    def test_successful_store_writes_valid_json_and_no_tmp(self, lyrics_cache):
        lyrics_cache.store("Artist", "Song", {"lyrics": "Zeile ä ö ü"})

        path = _lyrics_file(lyrics_cache, "Artist", "Song")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["lyrics"] == "Zeile ä ö ü"
        assert "_cached_at" in data and "_cache_ttl" in data
        assert _leftover_tmp_files(lyrics_cache.cache_path) == []

    def test_overwrite_replaces_existing_entry(self, lyrics_cache):
        lyrics_cache.store("Artist", "Song", {"lyrics": "alt"})
        lyrics_cache.store("Artist", "Song", {"lyrics": "neu"})

        assert lyrics_cache.get("Artist", "Song")["lyrics"] == "neu"
        assert _leftover_tmp_files(lyrics_cache.cache_path) == []

    def test_interrupted_write_keeps_existing_file_intact(
        self, lyrics_cache, monkeypatch
    ):
        lyrics_cache.store("Artist", "Song", {"lyrics": "alt"})
        path = _lyrics_file(lyrics_cache, "Artist", "Song")
        before = path.read_text(encoding="utf-8")

        monkeypatch.setattr(json, "dump", _interrupting_dump(OSError("disk full")))
        lyrics_cache.store("Artist", "Song", {"lyrics": "neu"})  # darf nicht werfen
        monkeypatch.undo()

        assert path.read_text(encoding="utf-8") == before
        assert lyrics_cache.get("Artist", "Song")["lyrics"] == "alt"
        assert _leftover_tmp_files(lyrics_cache.cache_path) == []

    def test_interrupted_first_write_leaves_no_target_file(
        self, lyrics_cache, monkeypatch
    ):
        monkeypatch.setattr(json, "dump", _interrupting_dump(ValueError("boom")))
        lyrics_cache.store("Artist", "Song", {"lyrics": "x"})
        monkeypatch.undo()

        assert not _lyrics_file(lyrics_cache, "Artist", "Song").exists()
        assert lyrics_cache.get("Artist", "Song") is None
        assert _leftover_tmp_files(lyrics_cache.cache_path) == []

    def test_error_is_logged_not_raised(self, tmp_path, monkeypatch):
        logger = Mock()
        cache = LyricsCache(cache_dir=tmp_path, logger_factory=lambda name: logger)
        monkeypatch.setattr(json, "dump", _interrupting_dump(OSError("disk full")))

        cache.store("Artist", "Song", {"lyrics": "x"})

        assert logger.error.called

    def test_tmp_file_is_not_picked_up_by_cleanup(self, lyrics_cache):
        # Verwaiste Temp-Datei (z. B. nach SIGKILL) darf cleanup() nicht
        # als korrupten Cache-Eintrag zählen oder anfassen.
        orphan = lyrics_cache.cache_path / ".abc.json.tmp_deadbeef"
        orphan.write_text('{"partial": ', encoding="utf-8")

        stats = lyrics_cache.cleanup()

        assert stats["deleted_corrupt"] == 0
        assert orphan.exists()


# ─────────────────────────────────────────────────────────────────────
# PlayHistoryRepository.save()
# ─────────────────────────────────────────────────────────────────────


def _entry(title):
    return {
        "timestamp": "2026-09-27T12:00:00",
        "tracks": [{"title": title, "artist": "A", "album": "B", "id": title}],
    }


class TestPlayHistoryAtomicSave:
    def test_successful_save_writes_valid_json_and_no_tmp(self, tmp_path):
        repo = PlayHistoryRepository(tmp_path, logger=Mock())

        repo.save([_entry("Song ä")], "alice")

        path = repo.history_file_for_user("alice")
        assert json.loads(path.read_text(encoding="utf-8")) == [_entry("Song ä")]
        assert _leftover_tmp_files(tmp_path) == []

    def test_interrupted_oserror_keeps_existing_history(self, tmp_path, monkeypatch):
        logger = Mock()
        repo = PlayHistoryRepository(tmp_path, logger=logger)
        repo.save([_entry("alt")], "alice")

        monkeypatch.setattr(json, "dump", _interrupting_dump(OSError("disk full")))
        repo.save([_entry("alt"), _entry("neu")], "alice")  # OSError wird geloggt
        monkeypatch.undo()

        assert repo.load("alice") == [_entry("alt")]
        assert logger.error.called
        assert _leftover_tmp_files(tmp_path) == []
        # Recovery-Pfad wurde nicht ausgelöst: keine *.corrupt.*-Datei
        assert list(tmp_path.glob("*.corrupt.*")) == []

    def test_non_oserror_still_propagates_but_keeps_existing_history(
        self, tmp_path, monkeypatch
    ):
        # Bisheriger Vertrag: save() fängt nur IOError/OSError. Ein
        # TypeError (nicht serialisierbar) propagiert weiter - vor dem Fix
        # aber mit bereits abgeschnittener Zieldatei.
        repo = PlayHistoryRepository(tmp_path, logger=Mock())
        repo.save([_entry("alt")], "alice")

        monkeypatch.setattr(json, "dump", _interrupting_dump(TypeError("not json")))
        with pytest.raises(TypeError):
            repo.save([_entry("neu")], "alice")
        monkeypatch.undo()

        assert repo.load("alice") == [_entry("alt")]
        assert _leftover_tmp_files(tmp_path) == []

    def test_missing_history_dir_is_logged_like_before(self, tmp_path):
        # Parent-Verzeichnis wird (wie bisher) nicht von save() angelegt,
        # sondern von StatistikService.__init__; fehlt es, wird geloggt.
        logger = Mock()
        repo = PlayHistoryRepository(tmp_path / "missing", logger=logger)

        repo.save([_entry("x")], "alice")

        assert logger.error.called
        assert not (tmp_path / "missing").exists()

    def test_corrupt_recovery_still_works(self, tmp_path):
        repo = PlayHistoryRepository(tmp_path, logger=Mock())
        repo.history_file_for_user("alice").write_text('{"partial": ', encoding="utf-8")

        assert repo.load("alice") == []
        assert len(list(tmp_path.glob("*.corrupt.*"))) == 1

        repo.save([_entry("neu")], "alice")
        assert repo.load("alice") == [_entry("neu")]

    def test_cleanup_old_entries_uses_atomic_save(self, tmp_path):
        repo = PlayHistoryRepository(tmp_path, logger=Mock())
        old = {"timestamp": "2000-01-01T00:00:00", "tracks": []}
        repo.save([old, _entry("neu")], "alice")

        repo.cleanup_old_entries("alice", retention_days=30)

        assert repo.load("alice") == [_entry("neu")]
        assert _leftover_tmp_files(tmp_path) == []
