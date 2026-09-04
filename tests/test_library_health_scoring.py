# tests/test_library_health_scoring.py
# -*- coding: utf-8 -*-
"""Health-Scoring: deterministisch, dokumentierte Gewichte, INFO ohne
Wirkung (Prompt Abschnitt 23/31)."""

from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.issues import make_issue
from services.library_health.models import AnalysisState, FileHealth, Severity
from services.library_health.scoring import (
    SEVERITY_PENALTY,
    build_health_section,
    file_health_score,
    status_for,
)


def _fh(tmp_path, rel, issue_codes=()):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    fh = FileHealth(record=build_file_record(p, tmp_path))
    fh.states = {"metadata": AnalysisState.PRESENT}
    for code in issue_codes:
        fh.issues.append(make_issue(code, path=rel))
    return fh


def test_severity_penalty_table_is_fixed():
    assert SEVERITY_PENALTY == {
        Severity.CRITICAL: 40.0,
        Severity.ERROR: 15.0,
        Severity.WARNING: 4.0,
        Severity.INFO: 0.0,
    }


def test_clean_file_scores_100(tmp_path):
    assert file_health_score(_fh(tmp_path, "A/Singles/2020 - x.m4a")) == 100.0


def test_info_only_does_not_reduce_score(tmp_path):
    fh = _fh(tmp_path, "A/Singles/2020 - x.m4a",
             ["LYRICS_MISSING", "META_ISRC_MISSING", "META_MB_RECORDING_MISSING"])
    assert file_health_score(fh) == 100.0


def test_error_and_warning_penalties(tmp_path):
    fh = _fh(tmp_path, "A/Singles/2020 - x.m4a",
             ["META_ARTIST_MISSING", "META_ALBUM_MISSING"])  # ERROR 15 + WARNING 4
    assert file_health_score(fh) == 81.0


def test_score_clamped_at_zero(tmp_path):
    fh = _fh(tmp_path, "A/Singles/2020 - x.m4a", ["AUDIO_NO_STREAM"] * 4)  # 4*40
    assert file_health_score(fh) == 0.0


def test_determinism(tmp_path):
    fhs = [
        _fh(tmp_path, "A/2020 - Rec/01 - a.m4a", ["META_ARTIST_MISSING"]),
        _fh(tmp_path, "A/2020 - Rec/02 - b.m4a"),
    ]
    a = build_health_section(fhs, [])
    b = build_health_section(fhs, [])
    assert a == b


def test_album_and_artist_scores_aggregate(tmp_path):
    fhs = [
        _fh(tmp_path, "A/2020 - Rec/01 - a.m4a", ["META_ARTIST_MISSING"]),  # 85
        _fh(tmp_path, "A/2020 - Rec/02 - b.m4a"),  # 100
    ]
    group_issues = [make_issue("ALBUM_TRACK_GAP", artist="A", album="2020 - Rec")]  # WARNING 4
    section = build_health_section(fhs, group_issues)
    album = section["albums"][0]
    assert album["health_score"] == round((85.0 + 100.0) / 2 - 4.0, 1)  # 88.5
    artist = section["artists"][0]
    assert artist["health_score"] == 92.5  # mean(85,100), keine Artist-Issues
    assert album["file_count"] == 2 and artist["album_count"] == 1


def test_library_score_and_deduction_cap(tmp_path):
    fhs = [_fh(tmp_path, "A/Singles/2020 - x.m4a")]
    dup_issues = [make_issue("DUPLICATE_EXACT", related_files=["a", "b"]) for _ in range(20)]
    section = build_health_section(fhs, dup_issues)
    # library_base 100, Abzug min(15, 0.5 * 20*4) -> 15
    assert section["score"] == 85.0


def test_status_bands():
    assert status_for(95) == "EXCELLENT"
    assert status_for(80) == "GOOD"
    assert status_for(60) == "FAIR"
    assert status_for(30) == "POOR"
    assert status_for(10) == "CRITICAL"


def test_empty_library_scores_100():
    section = build_health_section([], [])
    assert section["score"] == 100.0
    assert section["status"] == "EXCELLENT"
