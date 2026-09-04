# tests/test_library_health_report.py
# -*- coding: utf-8 -*-
"""Report-Struktur + Determinismus (Prompt Abschnitt 24-26/35)."""

from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.file_analysis import analyze_file
from services.library_health.models import AnalysisState, SCHEMA_VERSION
from services.library_health.report import build_report_dict, render_text
from services.library_health.tag_reader import ArtworkData, StreamData, TagData


def _fh(tmp_path, rel, **tag_over):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    rec = build_file_record(p, tmp_path)
    tag_kwargs = dict(state=AnalysisState.PRESENT, artist="A", title="T", album="Al",
                      album_artist="A", year="2020", genre="Pop", track_number=1,
                      artists_primary_tag=["A"])
    tag_kwargs.update(tag_over)
    tags = TagData(**tag_kwargs)
    return analyze_file(
        rec, tags,
        StreamData(state=AnalysisState.PRESENT, has_audio_stream=True, bitrate=192000,
                   duration_seconds=200.0),
        ArtworkData(state=AnalysisState.PRESENT, present=True, width=1000, height=1000,
                    is_square=True),
    )


def _report(tmp_path):
    healths = [
        _fh(tmp_path, "B Artist/Singles/2020 - Two.m4a", artist=None),
        _fh(tmp_path, "A Artist/2019 - Rec/01 - One.m4a"),
    ]
    return build_report_dict(
        library_root=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:05+00:00",
        duration_seconds=5.0,
        file_healths=healths,
    )


def test_schema_shape(tmp_path):
    r = _report(tmp_path)
    assert r["schema_version"] == SCHEMA_VERSION
    for key in ("scan", "library", "health", "statistics", "issues", "files"):
        assert key in r
    assert r["scan"]["pending_analyses"] == []
    assert r["statistics"]["duplicate_groups"] == 0  # keine Dubletten im Fixture
    assert "artists" in r and "albums" in r


def test_files_sorted_by_relative_path(tmp_path):
    r = _report(tmp_path)
    rels = [f["relative_path"] for f in r["files"]]
    assert rels == sorted(rels)


def test_issues_sorted_severity_then_code_then_path(tmp_path):
    r = _report(tmp_path)
    keys = [
        ({"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}[i["severity"]],
         i["issue_code"], i["path"] or "")
        for i in r["issues"]
    ]
    assert keys == sorted(keys)


def test_determinism_same_input_same_report(tmp_path):
    a = _report(tmp_path)
    b = _report(tmp_path)
    # Zeitstempel sind hier fix — der komplette Report muss identisch sein.
    assert a == b


def test_statistics_buckets(tmp_path):
    r = _report(tmp_path)
    s = r["statistics"]
    assert s["total_files"] == 2
    assert s["files_with_errors"] == 1        # artist=None -> ERROR
    assert s["healthy_files"] + s["files_with_warnings"] + s["files_with_errors"] \
        + s["files_not_analyzable"] == 2


def test_render_text_is_str_and_mentions_counts(tmp_path):
    text = render_text(_report(tmp_path))
    assert "MUSIC LIBRARY HEALTH REPORT" in text
    assert "Files:      2" in text
