# tests/test_library_repair_executor_l2_real_pipeline.py
# -*- coding: utf-8 -*-
"""
Production-Audit 2026-09-08, Test-Gap #2: apply_level2() wurde bisher
ausschliesslich gegen eine im Testfile nachgebaute _fake_reprocess()-Stub-
Funktion getestet (tests/test_library_repair_executor.py), nie gegen die
echte Produktions-Pipeline (services/metadata/track_reprocessor.py::
process_file) - genau der Pfad, der die beiden im Audit gefundenen realen
Defekte verursacht hat (SUCCESS-Status war nicht an das auslösende Issue
gebunden; ein reiner Lyrics-Repair veränderte real auch Genre/Cover).

Dieser Test verdrahtet apply_level2() exakt wie
scripts/library_repair.py::_build_reprocess() gegen den echten
process_file()-Aufruf - nur die externen Adapter (Genre/Lyrics/Cover)
sind gemockt (CLAUDE.md Abschnitt 8: externe Dienste in Unit-Tests nicht
real ansprechen), TagWriter ist der echte Produktions-TagWriter.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from mutagen.mp4 import MP4

from services.library_repair.executor import apply_level2
from services.library_repair.journal import RepairJournal
from services.library_repair.models import RepairAction, RepairCandidate, RepairLevel
from services.metadata.tag_writer import TagWriter
from services.metadata.track_reprocessor import NullReprocessLog, process_file

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")

_ATOM = {"artist": "©ART", "title": "©nam", "album": "©alb",
         "album_artist": "aART", "year": "©day"}


def _make_m4a(path: Path, **tags):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    if tags:
        a = MP4(path)
        for k, v in tags.items():
            a[_ATOM[k]] = [v]
        a.save()


class _DummyGenreResult:
    def __init__(self, primary="Pop", secondary=None):
        self.primary = primary
        self.secondary = secondary or []
        self.source = "unit_test"
        self.mb_ids = {}


def _make_stub_processor(*, lyrics):
    """Minimaler Stand-in mit genau den Attributen, die process_file()
    tatsaechlich verwendet - analog zum etablierten Muster in
    tests/test_reprocess_artist_metadata.py::make_processor_stub(), hier
    lokal gehalten, um diese Testdatei unabhaengig lauffaehig zu halten.
    tag_writer ist IMMER der echte Produktions-TagWriter."""
    processor = Mock()
    processor.artist_normalizer.normalize.side_effect = lambda a: a
    processor.title_cleaner.light_title_cleanup.side_effect = lambda title, artist: title
    processor.title_cleaner.build_search_title.side_effect = (
        lambda parsed_title, original_title, final_artist: original_title
    )
    processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
        return_value=_DummyGenreResult()
    )
    processor.lyrics_processor.fetch_lyrics_with_fallback = AsyncMock(
        return_value=(lyrics, "genius" if lyrics else None)
    )
    processor.cover_processor.get_cover_art = Mock(return_value=(None, None))
    processor.tag_writer = TagWriter(logger=Mock())
    processor.auto_learn_manager = Mock()
    processor.auto_learn_manager.preview_featured_artists = Mock(return_value=[])
    processor.auto_learn_manager.observe_featured_artists = AsyncMock(return_value=[])
    processor.auto_learn_manager.preview_genre_learning = Mock(return_value={
        "artist": None, "observed_primary": None, "observed_secondary": [],
        "decision": "SKIPPED_NO_GENRE", "existing": None, "predicted_primary": None,
        "predicted_secondary": [], "predicted_observations": 0, "predicted_confidence": None,
    })
    processor.auto_learn_manager.learn_genre = AsyncMock(return_value=False)
    return processor


def _reprocess_fn(processor):
    """Verdrahtet apply_level2() exakt wie scripts/library_repair.py::
    _build_reprocess() gegen den echten process_file()-Aufruf."""

    def _fn(path, artist_root, dry_run):
        return asyncio.run(
            process_file(path, artist_root, processor, Mock(), Mock(),
                        NullReprocessLog(), dry_run=dry_run)
        )
    return _fn


def _cand(rel, code):
    return RepairCandidate(issue_code=code, action=RepairAction.METADATA_REPROCESS,
                           level=RepairLevel.METADATA_REPROCESSING, severity="INFO",
                           scope="file", path=rel)


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


@requires_ffmpeg
def test_lyrics_missing_stays_skipped_when_real_pipeline_finds_no_lyrics(lib):
    """Regressionstest fuer den Production-Audit-Fund: die ECHTE Pipeline
    aendert bei einem Lyrics-Repair-Versuch auch Genre (hier simuliert als
    Nebeneffekt), aber wenn Lyrics selbst NICHT gefunden werden, muss
    LYRICS_MISSING SKIPPED bleiben statt (wie vor dem Fix) SUCCESS."""
    p = lib / "makko" / "Singles" / "2020 - Titel.m4a"
    _make_m4a(p, artist="makko", title="Titel", album="Titel", album_artist="makko", year="2020")
    j = RepairJournal(lib / "j.jsonl")
    processor = _make_stub_processor(lyrics=None)

    outcomes = apply_level2(
        [_cand("makko/Singles/2020 - Titel.m4a", "LYRICS_MISSING")],
        lib, j, _reprocess_fn(processor), dry_run=False,
    )

    assert outcomes[0].issue_code == "LYRICS_MISSING"
    assert outcomes[0].status == "SKIPPED"
    # Genre wurde von der echten Pipeline trotzdem gesetzt (Nebeneffekt) -
    # SUCCESS fuer LYRICS_MISSING darf sich davon nicht taeuschen lassen.
    assert MP4(p)["©gen"] == ["Pop"]


@requires_ffmpeg
def test_lyrics_missing_succeeds_when_real_pipeline_finds_lyrics(lib):
    """Gegenprobe: findet die echte Pipeline tatsaechlich Lyrics, bleibt
    SUCCESS korrekt erhalten."""
    p = lib / "makko" / "Singles" / "2020 - Titel.m4a"
    _make_m4a(p, artist="makko", title="Titel", album="Titel", album_artist="makko", year="2020")
    j = RepairJournal(lib / "j.jsonl")
    processor = _make_stub_processor(lyrics="Echte Lyrics")

    outcomes = apply_level2(
        [_cand("makko/Singles/2020 - Titel.m4a", "LYRICS_MISSING")],
        lib, j, _reprocess_fn(processor), dry_run=False,
    )

    assert outcomes[0].issue_code == "LYRICS_MISSING"
    assert outcomes[0].status == "SUCCESS"
    assert MP4(p)["©lyr"] == ["Echte Lyrics"]
