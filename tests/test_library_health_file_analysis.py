# tests/test_library_health_file_analysis.py
# -*- coding: utf-8 -*-
"""Pure-Unit-Tests der Per-Datei-Analyse (Prompt Abschnitt 8-16/31).

Kein Dateisystem, keine Fixtures — synthetische TagData/StreamData/
ArtworkData. Nutzt die ECHTE Produktionsimplementierung
services.library_health.file_analysis (CLAUDE.md Abschnitt 7)."""

from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.file_analysis import analyze_file
from services.library_health.models import AnalysisState, Severity
from services.library_health.tag_reader import ArtworkData, StreamData, TagData


def _record(tmp_path, rel="Artist/Singles/2021 - Song.m4a"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return build_file_record(p, tmp_path)


def _healthy_tags(**over):
    base = dict(
        state=AnalysisState.PRESENT,
        artist="Artist", album_artist="Artist", title="Song",
        album="Song", year="2021", genre="Pop",
        track_number=1, artists_primary_tag=["Artist"],
    )
    base.update(over)
    return TagData(**base)


def _ok_stream(**over):
    base = dict(state=AnalysisState.PRESENT, has_audio_stream=True,
                codec="aac", bitrate=192000, duration_seconds=180.0)
    base.update(over)
    return StreamData(**base)


def _ok_artwork(**over):
    base = dict(state=AnalysisState.PRESENT, present=True, mime_type="image/jpeg",
                width=1000, height=1000, is_square=True, size_bytes=50000)
    base.update(over)
    return ArtworkData(**base)


def _codes(fh):
    return {i.code for i in fh.issues}


def _sev(fh, code):
    return next(i.severity for i in fh.issues if i.code == code)


# ── Metadata ────────────────────────────────────────────────────────────

def test_healthy_file_has_only_info_issues(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(), _ok_stream(), _ok_artwork())
    assert all(i.severity == Severity.INFO for i in fh.issues), _codes(fh)
    assert fh.states["metadata"] == AnalysisState.PRESENT


def test_missing_artist_and_title_are_errors(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(artist=None, title=None),
                      _ok_stream(), _ok_artwork())
    assert {"META_ARTIST_MISSING", "META_TITLE_MISSING"} <= _codes(fh)
    assert _sev(fh, "META_ARTIST_MISSING") == Severity.ERROR


def test_not_analyzable_tags_short_circuit(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      TagData(state=AnalysisState.NOT_ANALYZABLE, error="boom"),
                      _ok_stream(), _ok_artwork())
    assert "META_NOT_ANALYZABLE" in _codes(fh)
    assert fh.states["metadata"] == AnalysisState.NOT_ANALYZABLE
    # audio wird trotzdem analysiert
    assert "audio" in fh.states


def test_year_invalid(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(year="not-a-year"),
                      _ok_stream(), _ok_artwork())
    assert "META_YEAR_INVALID" in _codes(fh)


def test_missing_track_number_is_warning_in_album_context(tmp_path):
    rec = _record(tmp_path, "Artist/2018 - Album/03 - Song.m4a")
    fh = analyze_file(rec, _healthy_tags(track_number=None), _ok_stream(), _ok_artwork())
    assert _sev(fh, "META_TRACK_NUMBER_MISSING") == Severity.WARNING


def test_missing_track_number_is_info_for_single(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(track_number=None),
                      _ok_stream(), _ok_artwork())
    assert _sev(fh, "META_TRACK_NUMBER_MISSING") == Severity.INFO


# ── Genre ───────────────────────────────────────────────────────────────

def test_genre_invalid_via_validator(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(genre="Klingonenpop"),
                      _ok_stream(), _ok_artwork(),
                      genre_validator=lambda g: g == "Pop")
    assert "GENRE_INVALID" in _codes(fh)


def test_genre_delimiter_inconsistent(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(genre="Pop / Rock"),
                      _ok_stream(), _ok_artwork(), genre_validator=lambda g: True)
    assert "GENRE_DELIMITER_INCONSISTENT" in _codes(fh)


def test_current_genre_separator_is_accepted(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(genre="Pop; Rock"),
                      _ok_stream(), _ok_artwork(), genre_validator=lambda g: True)
    assert "GENRE_DELIMITER_INCONSISTENT" not in _codes(fh)


# ── Multi-Artist ────────────────────────────────────────────────────────

def test_semicolon_in_single_artist_value_is_suspicious(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      _healthy_tags(artist="A; B", artists_primary_tag=["A; B"]),
                      _ok_stream(), _ok_artwork())
    assert "MULTI_ARTIST_SUSPICIOUS" in _codes(fh)


def test_feat_in_artist_tag_without_freeform_is_suspicious(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      _healthy_tags(artist="A feat. B", artists_primary_tag=["A feat. B"],
                                    artists_freeform=[]),
                      _ok_stream(), _ok_artwork())
    assert "MULTI_ARTIST_SUSPICIOUS" in _codes(fh)


def test_duplicate_artist_names(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      _healthy_tags(artists_primary_tag=["A"], artists_freeform=["A", "a"]),
                      _ok_stream(), _ok_artwork())
    assert "MULTI_ARTIST_DUPLICATE" in _codes(fh)


def test_album_artist_mismatch_not_flagged_for_compilation(tmp_path):
    rec = _record(tmp_path, "Compilations/Chan/A - X.m4a")
    fh = analyze_file(rec, _healthy_tags(artist="A", album_artist="Various",
                                         artists_primary_tag=["A"]),
                      _ok_stream(), _ok_artwork())
    assert "MULTI_ARTIST_INCONSISTENT" not in _codes(fh)


# ── Artwork ─────────────────────────────────────────────────────────────

def test_artwork_missing(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(),
                      _ok_stream(), ArtworkData(state=AnalysisState.MISSING, present=False))
    assert "ARTWORK_MISSING" in _codes(fh)


def test_artwork_low_res_and_non_square(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(), _ok_stream(),
                      _ok_artwork(width=200, height=300, is_square=False))
    assert {"ARTWORK_LOW_RESOLUTION", "ARTWORK_NON_SQUARE"} <= _codes(fh)


def test_artwork_invalid(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(), _ok_stream(),
                      ArtworkData(state=AnalysisState.INVALID, present=True, error="bad"))
    assert "ARTWORK_INVALID" in _codes(fh)


# ── Lyrics ──────────────────────────────────────────────────────────────

def test_lyrics_missing_is_info(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(lyrics=None), _ok_stream(), _ok_artwork())
    assert _sev(fh, "LYRICS_MISSING") == Severity.INFO


def test_lyrics_empty_is_warning(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(lyrics="   "), _ok_stream(), _ok_artwork())
    assert _sev(fh, "LYRICS_EMPTY") == Severity.WARNING


def test_lyrics_junk_is_invalid(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(lyrics="Lyrics not found"),
                      _ok_stream(), _ok_artwork())
    assert "LYRICS_INVALID" in _codes(fh)


# ── Audio ───────────────────────────────────────────────────────────────

def test_audio_no_stream_is_critical(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(),
                      StreamData(state=AnalysisState.PRESENT, has_audio_stream=False),
                      _ok_artwork())
    assert _sev(fh, "AUDIO_NO_STREAM") == Severity.CRITICAL


def test_audio_corrupt_is_critical(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(),
                      StreamData(state=AnalysisState.INVALID, corrupt=True, error="moov atom not found"),
                      _ok_artwork())
    assert _sev(fh, "AUDIO_CORRUPT") == Severity.CRITICAL


def test_audio_not_analyzable_distinct_from_missing(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(),
                      StreamData(state=AnalysisState.NOT_ANALYZABLE, error="ffprobe timeout"),
                      _ok_artwork())
    assert "AUDIO_NOT_ANALYZABLE" in _codes(fh)
    assert fh.states["audio"] == AnalysisState.NOT_ANALYZABLE


def test_audio_low_bitrate_and_short(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(),
                      _ok_stream(bitrate=96000, duration_seconds=8.0), _ok_artwork())
    assert {"AUDIO_LOW_BITRATE", "AUDIO_VERY_SHORT"} <= _codes(fh)


# ── Loudness ────────────────────────────────────────────────────────────

def test_loudness_missing_is_info_only(tmp_path):
    fh = analyze_file(_record(tmp_path), _healthy_tags(replaygain={}), _ok_stream(), _ok_artwork())
    assert _sev(fh, "LOUDNESS_TAG_MISSING") == Severity.INFO


def test_loudness_invalid(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      _healthy_tags(replaygain={"replaygain_track_gain": "loud"}),
                      _ok_stream(), _ok_artwork())
    assert "LOUDNESS_TAG_INVALID" in _codes(fh)


def test_loudness_partial(tmp_path):
    fh = analyze_file(_record(tmp_path),
                      _healthy_tags(replaygain={"replaygain_track_gain": "-7.5 dB"}),
                      _ok_stream(), _ok_artwork())
    assert "LOUDNESS_TAG_PARTIAL" in _codes(fh)


# ── Struktur / Dateiname ────────────────────────────────────────────────

def test_structure_invalid_path(tmp_path):
    rec = _record(tmp_path, "loose.m4a")
    fh = analyze_file(rec, _healthy_tags(), _ok_stream(), _ok_artwork())
    assert "STRUCTURE_INVALID_PATH" in _codes(fh)


def test_filename_suspicious_double_space(tmp_path):
    rec = _record(tmp_path, "Artist/Singles/2021 -  Song.m4a")
    fh = analyze_file(rec, _healthy_tags(title="Song"), _ok_stream(), _ok_artwork())
    assert "FILENAME_SUSPICIOUS" in _codes(fh)


def test_filename_title_mismatch(tmp_path):
    rec = _record(tmp_path, "Artist/Singles/2021 - Wrong Name.m4a")
    fh = analyze_file(rec, _healthy_tags(title="Actual Title"), _ok_stream(), _ok_artwork())
    assert "FILENAME_TITLE_MISMATCH" in _codes(fh)


def test_filename_matches_convention_no_mismatch(tmp_path):
    rec = _record(tmp_path, "Artist/Singles/2021 - Song.m4a")
    fh = analyze_file(rec, _healthy_tags(title="Song"), _ok_stream(), _ok_artwork())
    assert "FILENAME_TITLE_MISMATCH" not in _codes(fh)


def test_extension_unexpected(tmp_path):
    rec = _record(tmp_path, "Artist/Singles/2021 - Song.ogg")
    fh = analyze_file(rec, _healthy_tags(), _ok_stream(), _ok_artwork(),
                      expected_extension=".m4a")
    assert "FILENAME_EXTENSION_UNEXPECTED" in _codes(fh)


# ── Determinismus ───────────────────────────────────────────────────────

def test_issue_order_is_deterministic_and_severity_first(tmp_path):
    tags = _healthy_tags(artist=None, genre="Pop / Rock", lyrics="   ")
    fh1 = analyze_file(_record(tmp_path), tags, _ok_stream(bitrate=1000), _ok_artwork(width=10, height=10, is_square=False))
    fh2 = analyze_file(_record(tmp_path), tags, _ok_stream(bitrate=1000), _ok_artwork(width=10, height=10, is_square=False))
    assert [i.code for i in fh1.issues] == [i.code for i in fh2.issues]
    ranks = [i.severity for i in fh1.issues]
    # keine INFO vor einem ERROR
    assert ranks == sorted(ranks, key=lambda s: {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}[s.value])
