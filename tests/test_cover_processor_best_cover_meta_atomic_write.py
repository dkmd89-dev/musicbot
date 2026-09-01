# tests/test_cover_processor_best_cover_meta_atomic_write.py
# -*- coding: utf-8 -*-
"""
AE-03 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 19): anders als
CoverProcessor._cache_set() (bereits per RES-02 atomar, siehe
tests/test_cover_processor_cache_atomic_write.py) schrieb
_cache_best_cover() die Metadaten-JSON-Datei (Score/Aufloesung/Quelle des
gewaehlten Covers, ein reines Diagnose-Sidecar) bisher per direktem
open(meta_path, "w") + json.dump() - ein Prozessabbruch/Fehler waehrend
des Schreibens konnte die Datei leeren oder korrumpieren.

Geringer Blast-Radius (verifiziert): kein Konsument im Repo liest diese
Metadaten-Datei je zurueck (_meta_path() wird ausschliesslich hier
geschrieben) - eine Korruption haette keine funktionale Auswirkung gehabt.
Dennoch fuer Konsistenz mit dem etablierten Muster (RES-02,
DuplicateCache._write_json_atomic(), MetadataCache.store()) behoben.

Fix: write-tmp + atomarer os.replace(), identisches Muster zu _cache_set().

Nutzt denselben Testaufbau wie test_cover_processor_cache_atomic_write.py:
_CACHE_DIR ist eine Modul-Level-Konstante, wird per monkeypatch auf
tmp_path umgeleitet, um den echten cache/covers-Ordner nicht zu beruehren.
"""

import json
from pathlib import Path

import pytest

from services.metadata.cover_processor import CoverCandidate, CoverProcessor


@pytest.fixture
def processor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.metadata.cover_processor._CACHE_DIR", str(tmp_path)
    )
    return CoverProcessor()


def _make_candidate(**overrides):
    defaults = dict(
        source="fanart",
        data=b"fake-image-bytes",
        width=1000,
        height=1000,
        file_size_kb=250,
        total_score=95,
        image_hash="abc123",
        jpeg_quality=90,
        color_count=12,
        sharpness=3.5,
    )
    defaults.update(overrides)
    return CoverCandidate(**defaults)


def _read_meta_file(tmp_path):
    files = list(Path(tmp_path).glob("*.json"))
    assert len(files) == 1, f"Erwartet genau eine Metadaten-Datei, gefunden: {files}"
    return json.loads(files[0].read_text())


class TestCacheBestCoverAtomicWrite:
    def test_successful_write_stores_correct_metadata(self, processor, tmp_path):
        candidate = _make_candidate()

        processor._cache_best_cover("Some Artist", "Some Title", candidate)

        meta = _read_meta_file(tmp_path)
        assert meta["source"] == "fanart"
        assert meta["artist"] == "Some Artist"
        assert meta["title"] == "Some Title"
        assert meta["score"] == 95

    def test_interrupted_write_leaves_previous_valid_metadata_untouched(
        self, processor, tmp_path, monkeypatch
    ):
        # Erster, erfolgreicher Schreibvorgang - reale Datei auf Platte.
        processor._cache_best_cover(
            "Some Artist", "Some Title", _make_candidate(source="original")
        )
        assert _read_meta_file(tmp_path)["source"] == "original"

        # Zweiter Schreibvorgang wird simuliert unterbrochen (Absturz
        # waehrend des atomaren Umbenennens).
        monkeypatch.setattr(
            "services.metadata.cover_processor.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        processor._cache_best_cover(
            "Some Artist", "Some Title", _make_candidate(source="corrupted-attempt")
        )

        # Die Metadaten-Datei muss weiterhin ihren letzten GUELTIGEN Zustand
        # haben - nicht die halb geschriebenen/verworfenen neuen Daten.
        assert _read_meta_file(tmp_path)["source"] == "original"

    def test_interrupted_write_leaves_no_leftover_tmp_files(
        self, processor, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "services.metadata.cover_processor.os.replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        processor._cache_best_cover("Some Artist", "Some Title", _make_candidate())

        leftover = [p for p in Path(tmp_path).iterdir() if ".tmp_" in p.name]
        assert leftover == []
