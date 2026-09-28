# tests/test_enhanced_metadata_processor_step_reporting.py
# -*- coding: utf-8 -*-
"""
D.12c — EnhancedMetadataProcessor.process_single_track() meldet feine
Schritte über services/jobs/step_context.report_step().

P0-Schutz (CLAUDE.md §9/§16): das MetadataResult muss mit und ohne
gesetzten Melder identisch sein, ein fehlerhafter Melder darf die
Pipeline nicht beeinflussen. Echte Produktionsklassen, externe Dienste
gefakt - Fixtures aus tests/test_metadata_processor_happy_path.py.
"""

from __future__ import annotations

import asyncio

from services.jobs.step_context import step_reporter
from tests.test_metadata_processor_happy_path import (  # noqa: F401 - Fixtures
    filename_fixer,
    happy_path_config,
    processor,
)

FULL_PIPELINE_STEPS = [
    "Cache prüfen…",
    "Künstler bestimmen…",
    "Titel bestimmen…",
    "Genre bestimmen…",
    "Lyrics suchen…",
    "Cover laden…",
    "Album & Jahr bestimmen…",
    "ReplayGain-Analyse…",
    "In Bibliothek verschieben…",
    "Tags schreiben…",
]


def _track(tmp_path, video_id, name="song.mp3", song="Step Song"):
    source = tmp_path / name
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    return {
        "title": f"Step Artist - {song} (Official Video)",
        "artist": "Step Artist",
        "uploader": "Step Artist",
        "channel": "Step Artist",
        "id": video_id,
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }


def _comparable(result):
    # Titel bewusst ausgenommen (beide Läufe nutzen verschiedene Titel,
    # siehe test_result_is_identical_with_and_without_reporter).
    return (
        result.success, result.error, result.artist,
        result.from_cache, result.is_duplicate,
        result.library_path is not None,
    )


def test_steps_are_reported_in_pipeline_order(processor, filename_fixer, tmp_path):
    received = []

    async def run():
        with step_reporter(received.append):
            return await processor.process_single_track(
                track_metadata=_track(tmp_path, "STEP001"), filename_fixer=filename_fixer
            )

    result = asyncio.run(run())

    assert result.success is True
    assert received == FULL_PIPELINE_STEPS


def test_cache_hit_reports_cache_steps_only(processor, filename_fixer, tmp_path):
    asyncio.run(
        processor.process_single_track(
            track_metadata=_track(tmp_path, "STEPCACHE", "first.mp3"), filename_fixer=filename_fixer
        )
    )
    received = []

    async def run():
        with step_reporter(received.append):
            return await processor.process_single_track(
                track_metadata=_track(tmp_path, "STEPCACHE", "second.mp3"),
                filename_fixer=filename_fixer,
            )

    result = asyncio.run(run())

    assert result.from_cache is True
    assert received == ["Cache prüfen…", "Aus Cache übernommen"]


def test_result_is_identical_with_and_without_reporter(processor, filename_fixer, tmp_path):
    """Characterization: der Melder ist rein additiv - gleiche Eingabe,
    gleiches Ergebnis. Verschiedene video_ids (sonst Metadaten-Cache-Hit)
    und Titel (sonst In-Memory-Duplikat über processed_titles des
    Singletons, Schritt 8 - bestehendes Verhalten, unabhängig vom
    Melder)."""
    without = asyncio.run(
        processor.process_single_track(
            track_metadata=_track(tmp_path, "STEPCMP1", "a.mp3", "Song A"), filename_fixer=filename_fixer
        )
    )

    async def run():
        with step_reporter(lambda _m: None):
            return await processor.process_single_track(
                track_metadata=_track(tmp_path, "STEPCMP2", "b.mp3", "Song B"), filename_fixer=filename_fixer
            )

    with_reporter = asyncio.run(run())

    assert _comparable(with_reporter) == _comparable(without)
    assert without.title == "Song A" and with_reporter.title == "Song B"


def test_failing_reporter_does_not_change_result(processor, filename_fixer, tmp_path):
    def boom(_msg):
        raise RuntimeError("Melder kaputt")

    async def run():
        with step_reporter(boom):
            return await processor.process_single_track(
                track_metadata=_track(tmp_path, "STEPBOOM"), filename_fixer=filename_fixer
            )

    result = asyncio.run(run())

    assert result.success is True
    assert result.error is None
