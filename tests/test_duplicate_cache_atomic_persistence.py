"""
P0-B (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27):
services/duplicate/cache.py::DuplicateCache._save_caches() schrieb
url_duplicates.json/content_duplicates.json vorher per direktem
open(mode="w") + json.dump() - ein Prozessabbruch waehrend des Schreibens
konnte die Duplikat-Erkennungs-Caches leeren oder korrumpieren (INV-02-
Verletzung in einem laut CLAUDE.md §15 P0-kritischen Bereich).

Fix: write-tmp + atomarer rename, analog zu MetadataCache.store()
(utils/metadata_cache.py) und dem FINDING-5-Fix fuer video_id_index.json.

INV-01 (Event-Loop-Blockierung) wird fuer diese Komponente in dieser Phase
bewusst NICHT behoben - siehe Docstring von _save_caches() fuer die
Begruendung (Async-Kaskade durch DuplicateDetector/EnhancedDuplicateHandler
waere eine "mass conversion", ausserhalb des Scopes; keine gemessene
meaningful Blockierungsdauer bei typischen Cache-Groessen). Da add_entry()/
_save_caches() weiterhin vollstaendig synchron ohne await dazwischen laufen,
aendert der atomare Write NICHTS an der Concurrency-Situation - ein
dedizierter Concurrent-Update-Test ist daher fuer DIESEN Fix nicht
erforderlich (anders als bei P0-A auto_learn.py, wo asyncio.to_thread()
tatsaechlich eingefuehrt wurde).
"""

from datetime import datetime
from pathlib import Path

import pytest

from services.downloader.models import DuplicateEntry
from services.duplicate.cache import DuplicateCache


@pytest.fixture
def cache(tmp_path):
    return DuplicateCache(cache_dir=str(tmp_path / "duplicate_cache"))


def _entry(artist="Some Artist", title="Some Song", url="https://youtu.be/ABC123"):
    return DuplicateEntry(
        artist=artist,
        title=title,
        url=url,
        file_path=None,
        download_date=datetime.now(),
    )


class TestSaveCachesAtomicWrite:
    def test_interrupted_write_leaves_previous_valid_caches_untouched(
        self, cache, monkeypatch
    ):
        # Erster, erfolgreicher Schreibvorgang - reale Dateien auf Platte.
        cache.add_entry(_entry(artist="Stable Artist", title="Stable Song"))
        assert cache.url_cache_file.exists()
        assert cache.content_cache_file.exists()
        original_url_content = cache.url_cache_file.read_text(encoding="utf-8")
        original_content_content = cache.content_cache_file.read_text(
            encoding="utf-8"
        )

        # Zweiter Schreibvorgang wird simuliert unterbrochen (Absturz waehrend
        # json.dump()).
        monkeypatch.setattr(
            "services.duplicate.cache.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        cache.add_entry(_entry(artist="New Artist During Crash", title="New Song"))

        # Die auf Platte liegenden Dateien muessen weiterhin ihren letzten
        # GUELTIGEN Zustand haben - nicht leer/korrupt.
        assert cache.url_cache_file.read_text(encoding="utf-8") == original_url_content
        assert (
            cache.content_cache_file.read_text(encoding="utf-8")
            == original_content_content
        )

    def test_interrupted_write_leaves_no_leftover_tmp_files(self, cache, monkeypatch):
        monkeypatch.setattr(
            "services.duplicate.cache.json.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        cache.add_entry(_entry())

        leftover = list(cache.cache_path.glob("*.tmp_*"))
        assert leftover == []

    def test_successful_write_updates_files_correctly(self, cache):
        cache.add_entry(_entry(artist="Fresh Artist", title="Fresh Song"))

        reloaded = DuplicateCache(cache_dir=str(cache.cache_path))
        found = reloaded.check_content_duplicate("Fresh Artist", "Fresh Song")
        assert found is not None
        assert found.artist == "Fresh Artist"
