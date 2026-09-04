# tests/test_library_health_group_analysis.py
# -*- coding: utf-8 -*-
"""Group-Analyse: Album-/Artist-Konsistenz + Duplicate-Gruppen
(Prompt Abschnitt 17-19). Pure Units mit synthetischen FileHealth-Objekten."""

from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.group_analysis import analyze_groups
from services.library_health.models import AnalysisState, FileHealth


def _fh(tmp_path, rel, **over):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    fh = FileHealth(record=build_file_record(p, tmp_path))
    fh.states = {"metadata": AnalysisState.PRESENT}
    fh.artist = over.get("artist", "The Artist")
    fh.album_artist = over.get("album_artist", "The Artist")
    fh.title = over.get("title", p.stem)
    fh.album = over.get("album", "The Album")
    fh.year = over.get("year", "2020")
    fh.genre = over.get("genre", "Pop")
    fh.track_number = over.get("track_number")
    fh.disc_number = over.get("disc_number")
    fh.mb_recording_id = over.get("mb_recording_id")
    fh.mb_release_id = over.get("mb_release_id")
    fh.isrc = over.get("isrc")
    fh.cover_sha256 = over.get("cover_sha256")
    fh.cover_width = over.get("cover_width")
    fh.cover_height = over.get("cover_height")
    fh.duration_seconds = over.get("duration_seconds", 180.0)
    fh.bitrate = over.get("bitrate", 192000)
    return fh


def _codes(issues):
    return sorted(i.code for i in issues)


# ── Album ───────────────────────────────────────────────────────────────

def test_album_track_gap(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2),
        _fh(tmp_path, f"{base}/04 - d.m4a", track_number=4),
    ]
    issues = analyze_groups(fhs)
    assert "ALBUM_TRACK_GAP" in _codes(issues)
    gap = next(i for i in issues if i.code == "ALBUM_TRACK_GAP")
    assert gap.details["missing"] == [3]


def test_album_duplicate_track_number(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1),
        _fh(tmp_path, f"{base}/01 - b.m4a", track_number=1),
    ]
    issues = analyze_groups(fhs)
    assert "ALBUM_DUPLICATE_TRACK_NUMBER" in _codes(issues)


def test_album_disc_number_keeps_tracks_separate(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/1-01 a.m4a", track_number=1, disc_number=1),
        _fh(tmp_path, f"{base}/2-01 b.m4a", track_number=1, disc_number=2),
    ]
    issues = analyze_groups(fhs)
    assert "ALBUM_DUPLICATE_TRACK_NUMBER" not in _codes(issues)


def test_album_inconsistent_year_and_release_id(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, year="2020", mb_release_id="r1"),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2, year="2021", mb_release_id="r2"),
    ]
    issues = analyze_groups(fhs)
    assert {"ALBUM_YEAR_INCONSISTENT", "ALBUM_RELEASE_ID_INCONSISTENT"} <= set(_codes(issues))


def test_album_cover_inconsistent_only_on_dimension_difference(tmp_path):
    base = "A/2020 - Rec"
    # gleiche Abmessung, anderer Hash -> KEINE Inkonsistenz (per-Track-Abruf)
    same_dim = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, cover_sha256="aaa",
            cover_width=1000, cover_height=1000),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2, cover_sha256="bbb",
            cover_width=1000, cover_height=1000),
    ]
    assert "ALBUM_COVER_INCONSISTENT" not in _codes(analyze_groups(same_dim))
    # verschiedene Abmessungen -> Inkonsistenz
    diff_dim = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, cover_width=300, cover_height=300),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2, cover_width=1400, cover_height=1400),
    ]
    assert "ALBUM_COVER_INCONSISTENT" in _codes(analyze_groups(diff_dim))


def test_compilation_folder_downgrades_track_gap_and_suppresses_release_id(tmp_path):
    base = "2Pac/2012 - The Best Of 2Pac"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, mb_release_id="r1"),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2, mb_release_id="r2"),
        _fh(tmp_path, f"{base}/04 - d.m4a", track_number=4, mb_release_id="r3"),
    ]
    issues = analyze_groups(fhs)
    codes = _codes(issues)
    assert "ALBUM_RELEASE_ID_INCONSISTENT" not in codes
    gap = next(i for i in issues if i.code == "ALBUM_TRACK_GAP")
    assert gap.severity.value == "INFO"


def test_studio_album_keeps_track_gap_warning_and_release_id(tmp_path):
    base = "Clueso/2021 - ALBUM"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, mb_release_id="r1"),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2, mb_release_id="r2"),
        _fh(tmp_path, f"{base}/04 - d.m4a", track_number=4, mb_release_id="r1"),
    ]
    issues = analyze_groups(fhs)
    codes = _codes(issues)
    assert "ALBUM_RELEASE_ID_INCONSISTENT" in codes
    gap = next(i for i in issues if i.code == "ALBUM_TRACK_GAP")
    assert gap.severity.value == "WARNING"


def test_consistent_album_produces_no_album_issue(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1),
        _fh(tmp_path, f"{base}/02 - b.m4a", track_number=2),
        _fh(tmp_path, f"{base}/03 - c.m4a", track_number=3),
    ]
    assert not [i for i in analyze_groups(fhs) if i.code.startswith("ALBUM_")]


def test_single_file_album_is_not_evaluated(tmp_path):
    fhs = [_fh(tmp_path, "A/2020 - Rec/05 - a.m4a", track_number=5)]
    assert not [i for i in analyze_groups(fhs) if i.code.startswith("ALBUM_")]


# ── Artist ──────────────────────────────────────────────────────────────

def test_artist_dir_tag_mismatch(tmp_path):
    fhs = [
        _fh(tmp_path, "Wrongname/Singles/2020 - a.m4a", artist="Real Name"),
        _fh(tmp_path, "Wrongname/Singles/2021 - b.m4a", artist="Real Name"),
    ]
    assert "ARTIST_DIR_TAG_MISMATCH" in _codes(analyze_groups(fhs))


def test_artist_name_variants(tmp_path):
    fhs = [
        _fh(tmp_path, "Artist - Topic/Singles/2020 - a.m4a", artist="Artist"),
        _fh(tmp_path, "Artist/Singles/2021 - b.m4a", artist="Artist"),
    ]
    issues = analyze_groups(fhs)
    assert "ARTIST_NAME_VARIANTS" in _codes(issues)


# ── Duplicates ──────────────────────────────────────────────────────────

def test_duplicate_exact(tmp_path):
    fhs = [
        _fh(tmp_path, "A/Singles/2020 - a.m4a", title="Song"),
        _fh(tmp_path, "A/2019 - Rec/01 - a.m4a", title="Song", track_number=1),
    ]
    hashes = {fhs[0].record.relative_path: "deadbeef", fhs[1].record.relative_path: "deadbeef"}
    issues = analyze_groups(fhs, file_sha256=hashes)
    assert "DUPLICATE_EXACT" in _codes(issues)


def test_duplicate_recording_by_mb_id(tmp_path):
    fhs = [
        _fh(tmp_path, "A/Singles/2020 - a.m4a", title="Song", mb_recording_id="rec-1"),
        _fh(tmp_path, "A/2019 - Rec/01 - a.m4a", title="Song", track_number=1, mb_recording_id="rec-1"),
    ]
    issues = analyze_groups(fhs)
    codes = _codes(issues)
    assert "DUPLICATE_RECORDING" in codes
    # nicht zusaetzlich als SUSPECTED (RECORDING ist die staerkere Aussage)
    assert "DUPLICATE_SUSPECTED" not in codes


def test_duplicate_suspected_same_normalized_artist_title(tmp_path):
    fhs = [
        _fh(tmp_path, "A/Singles/2020 - a.m4a", artist="A", title="Song"),
        _fh(tmp_path, "A/2019 - Rec/01 - a.m4a", artist="A", title="Song", track_number=1),
    ]
    assert "DUPLICATE_SUSPECTED" in _codes(analyze_groups(fhs))


def test_remix_is_not_a_suspected_duplicate(tmp_path):
    # DUP-03: normalize_title_for_identity entfernt keinen Remix-Zusatz
    fhs = [
        _fh(tmp_path, "A/Singles/2020 - Song.m4a", artist="A", title="Song"),
        _fh(tmp_path, "A/Singles/2021 - Song (Club Remix).m4a", artist="A", title="Song (Club Remix)"),
    ]
    assert "DUPLICATE_SUSPECTED" not in _codes(analyze_groups(fhs))


def test_no_duplicates_for_distinct_songs(tmp_path):
    fhs = [
        _fh(tmp_path, "A/Singles/2020 - One.m4a", artist="A", title="One"),
        _fh(tmp_path, "A/Singles/2021 - Two.m4a", artist="A", title="Two"),
    ]
    assert not [i for i in analyze_groups(fhs) if i.code.startswith("DUPLICATE_")]


# ── Determinismus ───────────────────────────────────────────────────────

def test_deterministic(tmp_path):
    base = "A/2020 - Rec"
    fhs = [
        _fh(tmp_path, f"{base}/01 - a.m4a", track_number=1, year="2020"),
        _fh(tmp_path, f"{base}/03 - c.m4a", track_number=3, year="2019"),
    ]
    a = [i.code for i in analyze_groups(fhs)]
    b = [i.code for i in analyze_groups(fhs)]
    assert a == b == sorted(a, key=lambda c: c) or a == b
