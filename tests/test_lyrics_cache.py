"""
Regressionstest für den in Phase 2 gefundenen LyricsCache.cleanup()-Stub
(analog zu TEST-003/MetadataCacheHandler.check() aus Phase 1): cleanup()
loggte nur Erfolg, löschte aber nie etwas - abgelaufene/korrupte/leere
Cache-Dateien wuchsen unbegrenzt auf Disk, und die Methode wurde
nirgendwo aufgerufen.

Neue Implementierung ist analog zu utils/metadata_cache.py's
MetadataCache.cleanup() (löscht leere/korrupte/TTL-abgelaufene Dateien,
gibt ein Stats-Dict zurück), plus Anbindung in GeniusClient.close().
"""

import json
import time
from unittest.mock import MagicMock

import pytest

from utils.lyrics_cache import LyricsCache


@pytest.fixture
def cache(tmp_path):
    return LyricsCache(cache_dir=tmp_path)


class TestCleanup:
    def test_empty_file_is_deleted(self, cache, tmp_path):
        empty_file = tmp_path / "empty.json"
        empty_file.write_bytes(b"")

        stats = cache.cleanup()

        assert not empty_file.exists()
        assert stats["deleted_empty"] == 1
        assert stats["kept"] == 0

    def test_corrupt_json_is_deleted(self, cache, tmp_path):
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{not valid json", encoding="utf-8")

        stats = cache.cleanup()

        assert not corrupt_file.exists()
        assert stats["deleted_corrupt"] == 1

    def test_expired_entry_is_deleted(self, cache, tmp_path):
        cache.cache_ttl = 1  # 1 Sekunde TTL für den Test
        cache.store("Some Artist", "Some Song", {"lyrics": "..."})

        key = cache._get_key("Some Artist", "Some Song")
        cache_file = tmp_path / f"{key}.json"
        assert cache_file.exists()

        time.sleep(1.1)
        stats = cache.cleanup()

        assert not cache_file.exists()
        assert stats["deleted_expired"] == 1

    def test_valid_unexpired_entry_is_kept(self, cache):
        cache.store("Some Artist", "Some Song", {"lyrics": "..."})

        stats = cache.cleanup()

        assert stats["kept"] == 1
        assert stats["deleted_empty"] == 0
        assert stats["deleted_corrupt"] == 0
        assert stats["deleted_expired"] == 0
        assert cache.get("Some Artist", "Some Song") is not None

    def test_cleanup_on_empty_cache_dir_is_a_noop(self, cache):
        stats = cache.cleanup()
        assert stats == {
            "deleted_empty": 0,
            "deleted_corrupt": 0,
            "deleted_expired": 0,
            "kept": 0,
        }


class TestGeniusClientCloseTriggersCleanup:
    def test_close_calls_lyrics_cache_cleanup(self):
        """
        Ruft GeniusClient.close() ungebunden auf einem Fake-'self' auf, statt
        einen echten GeniusClient zu konstruieren - dessen __init__ würde
        sonst über get_config() reale, konfigurierte Verzeichnisse anlegen.
        close() selbst greift nur auf self.lyrics_cache zu, daher reicht das.
        """
        from services.clients.genius_client import GeniusClient

        fake_self = MagicMock()
        GeniusClient.close(fake_self)

        fake_self.lyrics_cache.cleanup.assert_called_once()
