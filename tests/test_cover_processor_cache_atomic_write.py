"""
RES-02 (docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md,
Kurzliste): services/metadata/cover_processor.py::CoverProcessor._cache_set()
schrieb Cover-Art-Bytes bisher per direktem open(path, "wb") + f.write() -
ein Prozessabbruch/Fehler waehrend des Schreibens konnte die gecachte
Cover-Datei leeren oder korrumpieren (INV-02-artige Verletzung, im
Gegensatz zu den beiden bereits etablierten atomaren Mustern in
services/duplicate/cache.py::_write_json_atomic() und
utils/metadata_cache.py::store()).

Fix: write-tmp + atomarer os.replace(), analog zu den beiden genannten
Mustern (dort JSON-spezifisch, hier fuer rohe Bytes adaptiert, da
_cache_set() Bilddaten statt JSON schreibt).

Nutzt denselben Testaufbau wie tests/test_duplicate_cache_atomic_persistence.py
(INV-02-Fix fuer DuplicateCache): erfolgreicher Schreibvorgang zuerst,
danach ein simuliert unterbrochener zweiter Schreibvorgang - die zuletzt
gueltigen Daten muessen erhalten bleiben, kein Tmp-Rest darf zurueckbleiben.

_CACHE_DIR ist ein Modul-Level-Konstante (kein Konstruktor-Parameter) -
wird hier per monkeypatch auf tmp_path umgeleitet, um den echten
cache/covers-Ordner des Repositories nicht zu beruehren.
"""

from pathlib import Path

import pytest

from services.metadata.cover_processor import CoverProcessor


@pytest.fixture
def processor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.metadata.cover_processor._CACHE_DIR", str(tmp_path)
    )
    return CoverProcessor()


class TestCacheSetAtomicWrite:
    def test_successful_write_stores_correct_data(self, processor):
        processor._cache_set("mykey", b"fake-image-bytes")

        assert processor._cache_get("mykey") == b"fake-image-bytes"

    def test_interrupted_write_leaves_previous_valid_cache_untouched(
        self, processor, monkeypatch
    ):
        # Erster, erfolgreicher Schreibvorgang - reale Datei auf Platte.
        processor._cache_set("mykey", b"original-valid-bytes")
        assert processor._cache_get("mykey") == b"original-valid-bytes"

        # Zweiter Schreibvorgang wird simuliert unterbrochen (Absturz waehrend
        # des atomaren Umbenennens).
        monkeypatch.setattr(
            "services.metadata.cover_processor.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        processor._cache_set("mykey", b"corrupted-attempt-bytes")

        # Die gecachte Datei muss weiterhin ihren letzten GUELTIGEN Zustand
        # haben - nicht die halb geschriebenen/verworfenen neuen Daten.
        assert processor._cache_get("mykey") == b"original-valid-bytes"

    def test_interrupted_write_leaves_no_leftover_tmp_files(
        self, processor, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "services.metadata.cover_processor.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        processor._cache_set("mykey", b"data")

        leftover = [p for p in Path(tmp_path).iterdir() if ".tmp_" in p.name]
        assert leftover == []

    def test_cache_disabled_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.metadata.cover_processor._CACHE_DIR", str(tmp_path)
        )
        processor = CoverProcessor(cache_enabled=False)

        processor._cache_set("mykey", b"data")

        assert processor._cache_get("mykey") is None
        assert list(Path(tmp_path).iterdir()) == []
