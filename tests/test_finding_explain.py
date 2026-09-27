# -*- coding: utf-8 -*-
"""Finding-Erklaerung (services/library_health/finding_explain.py) und der
gemeinsame Vergleich file_analysis.compare_filename_to_title().

Kritischste Eigenschaft: die Erklaerung darf NIE eine andere Entscheidung
treffen als der Scanner. Deshalb laeuft ein Konsistenztest gegen den echten
`analyze_file()`-Produktionspfad (CLAUDE.md Abschnitt 7).
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.file_analysis import analyze_file, compare_filename_to_title
from services.library_health.finding_explain import (
    FILE_MISSING,
    FILE_NO_PATH,
    FILE_NO_TITLE_TAG,
    FILE_NOT_APPLICABLE,
    FILE_OK,
    FILE_OUTSIDE_LIBRARY,
    FILE_TAGS_UNREADABLE,
    diff_segments,
    explain_finding,
    supported_codes,
)
from services.library_health.findings import Finding
from services.library_health.models import AnalysisState
from services.library_health.tag_reader import ArtworkData, StreamData, TagData


def _tags(**over) -> TagData:
    base = dict(state=AnalysisState.PRESENT, artist="Artist", album_artist="Artist", title="Song",
                album="Song", year="2021", genre="Pop", track_number=1, artists_primary_tag=["Artist"])
    base.update(over)
    return TagData(**base)


def _finding(path="Artist/Singles/2021 - Song.m4a", code="FILENAME_TITLE_MISMATCH", **kw) -> Finding:
    d = dict(finding_id="fid1", code=code, scope="file", path=path, title="Titel beim Scan",
             message="m")
    d.update(kw)
    return Finding(**d)


def _make_file(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


# ── compare_filename_to_title ───────────────────────────────────────────

def test_compare_splits_prefix_and_remainder() -> None:
    r = compare_filename_to_title("03 - Intro feat. Mioso", "Intro (feat. Mioso)")
    assert r["prefix"] == "03 - "
    assert r["remainder"] == "Intro feat. Mioso"
    assert r["title"] == "Intro (feat. Mioso)"
    assert r["normalized_remainder"] == r["normalized_title"] == "intro feat. mioso"
    assert r["matches"] is True


@pytest.mark.parametrize("stem,title,matches", [
    ("2021 - Song", "Song", True),
    ("Artist - Song", "SONG", True),                        # casefold
    ("2021 - More Love feat. Okfella", "More Love (feat. Okfella)", True),
    ("2021 - Souvenir Industrie", "Souvenir (Industrie)", True),
    ("2021 - Song (Remix)", "Song", False),                 # semantischer Zusatz bleibt
    ("2021 - Song  x", "Song x", True),                     # Whitespace
    ("2021 - Wrong Name", "Actual Title", False),
    ("2021 - Song", "Song (Live)", False),
])
def test_compare_matches_table(stem, title, matches) -> None:
    assert compare_filename_to_title(stem, title)["matches"] is matches


def test_unicode_nfc_vs_nfd_is_never_a_difference() -> None:
    """Beide Seiten werden auf NFC normalisiert: eine NFD-Schreibweise kann
    kein FILENAME_TITLE_MISMATCH ausloesen."""
    nfc = unicodedata.normalize("NFC", "Über")
    nfd = unicodedata.normalize("NFD", "Über")
    assert nfc != nfd
    assert compare_filename_to_title(f"2021 - {nfd}", nfc)["matches"] is True


@pytest.mark.parametrize("stem,title", [
    ("Song", "Song"),
    ("2021 - Song", "Song"),
    ("2021 - Song (Remix)", "Song"),
    ("2021 - More Love feat. Okfella", "More Love (feat. Okfella)"),
    ("Artist - Wrong Name", "Actual Title"),
    ("2021 - Song", "Song (Live)"),
    ("Kygo - Take Me Back", "Take Me Back (Radio)"),
])
def test_compare_agrees_with_production_analyze_file(tmp_path, stem, title) -> None:
    """Konsistenz: Erklaerung == Scanner-Entscheidung (echter analyze_file)."""
    p = _make_file(tmp_path, f"Artist/Singles/{stem}.m4a")
    record = build_file_record(p, tmp_path)
    fh = analyze_file(
        record, _tags(title=title),
        StreamData(state=AnalysisState.PRESENT, has_audio_stream=True, codec="aac", bitrate=192000,
                   duration_seconds=180.0),
        ArtworkData(state=AnalysisState.PRESENT, present=True, mime_type="image/jpeg", width=1000,
                    height=1000, is_square=True, size_bytes=1),
    )
    scanner_flags_mismatch = "FILENAME_TITLE_MISMATCH" in {i.code for i in fh.issues}
    assert scanner_flags_mismatch is (not compare_filename_to_title(record.filename_stem, title)["matches"])


# ── diff_segments ───────────────────────────────────────────────────────

def test_diff_segments_reconstruct_both_sides() -> None:
    a, b = "intro feat. mioso", "intro mioso feat."
    segs = diff_segments(a, b)
    assert "".join(s["a"] for s in segs) == a
    assert "".join(s["b"] for s in segs) == b
    assert {s["op"] for s in segs} <= {"equal", "replace", "delete", "insert"}


def test_diff_segments_identical_and_empty() -> None:
    assert diff_segments("abc", "abc") == [{"op": "equal", "a": "abc", "b": "abc"}]
    assert diff_segments("", "") == []
    assert diff_segments("", "x") == [{"op": "insert", "a": "", "b": "x"}]


def test_diff_segments_caps_huge_input() -> None:
    segs = diff_segments("a" * 50000, "b" * 50000)
    assert sum(len(s["a"]) for s in segs) <= 2000


# ── explain_finding ─────────────────────────────────────────────────────

def test_supported_codes_lists_filename_title_mismatch() -> None:
    assert supported_codes() == ("FILENAME_TITLE_MISMATCH",)


def test_unsupported_code_is_reported_honestly_without_touching_disk(tmp_path) -> None:
    calls = []
    exp = explain_finding(_finding(code="META_ISRC_MISSING"), tmp_path,
                          tag_reader=lambda p: calls.append(p) or _tags())
    assert exp.supported is False and exp.file_status == FILE_NOT_APPLICABLE
    assert exp.evidence is None and calls == []


def test_finding_without_path(tmp_path) -> None:
    assert explain_finding(_finding(path=None), tmp_path).file_status == FILE_NO_PATH
    assert explain_finding(_finding(path=""), tmp_path).file_status == FILE_NO_PATH


@pytest.mark.parametrize("rel", ["../outside.m4a", "Artist/../../outside.m4a", "/etc/passwd", "."])
def test_path_outside_library_is_rejected_and_never_read(tmp_path, rel) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    (tmp_path / "outside.m4a").write_bytes(b"x")
    calls = []
    exp = explain_finding(_finding(path=rel), lib, tag_reader=lambda p: calls.append(p) or _tags())
    assert exp.file_status == FILE_OUTSIDE_LIBRARY
    assert calls == []


def test_symlink_escaping_the_library_is_rejected(tmp_path) -> None:
    lib = tmp_path / "lib"
    (lib / "Artist").mkdir(parents=True)
    secret = tmp_path / "secret.m4a"
    secret.write_bytes(b"x")
    os.symlink(secret, lib / "Artist" / "link.m4a")
    calls = []
    exp = explain_finding(_finding(path="Artist/link.m4a"), lib,
                          tag_reader=lambda p: calls.append(p) or _tags())
    assert exp.file_status == FILE_OUTSIDE_LIBRARY and calls == []


def test_missing_file(tmp_path) -> None:
    exp = explain_finding(_finding(path="Artist/Singles/gone.m4a"), tmp_path)
    assert exp.file_status == FILE_MISSING
    assert "nicht mehr vorhanden" in exp.message


def test_unreadable_tags(tmp_path) -> None:
    _make_file(tmp_path, "Artist/Singles/2021 - Song.m4a")
    exp = explain_finding(
        _finding(), tmp_path,
        tag_reader=lambda p: TagData(state=AnalysisState.NOT_ANALYZABLE, error="boom"))
    assert exp.file_status == FILE_TAGS_UNREADABLE and "boom" in exp.message and exp.evidence is None


@pytest.mark.parametrize("title", [None, "", "   "])
def test_no_title_tag(tmp_path, title) -> None:
    _make_file(tmp_path, "Artist/Singles/2021 - Song.m4a")
    exp = explain_finding(_finding(), tmp_path, tag_reader=lambda p: _tags(title=title))
    assert exp.file_status == FILE_NO_TITLE_TAG and exp.evidence is None


def test_mismatch_evidence_comes_from_disk_not_from_the_finding(tmp_path) -> None:
    _make_file(tmp_path, "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a")
    seen = []
    exp = explain_finding(
        _finding(path="01099/2019 - Skyr/01 - Intro feat. Mioso.m4a", title="Alter Titel"), tmp_path,
        tag_reader=lambda p: seen.append(p) or _tags(title="Intro (Mioso)"))
    assert exp.supported and exp.file_status == FILE_OK and exp.evidence_kind == "filename_title"
    ev = exp.evidence
    assert ev["stem"] == "01 - Intro feat. Mioso"      # aktueller Dateiname (Platte)
    assert ev["prefix"] == "01 - "
    assert ev["remainder"] == "Intro feat. Mioso"
    assert ev["title"] == "Intro (Mioso)"               # aktuelles Titel-Tag (Platte)
    assert ev["title_at_scan"] == "Alter Titel"         # Registry-Wert bleibt separat
    assert ev["normalized_remainder"] == "intro feat. mioso"
    assert ev["normalized_title"] == "intro mioso"
    assert ev["matches"] is False
    assert "".join(s["a"] for s in ev["segments"]) == ev["normalized_remainder"]
    assert "".join(s["b"] for s in ev["segments"]) == ev["normalized_title"]
    assert seen == [(tmp_path / "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a").resolve()]


def test_stale_finding_shows_matches_true(tmp_path) -> None:
    _make_file(tmp_path, "Artist/Singles/2021 - Song.m4a")
    exp = explain_finding(_finding(), tmp_path, tag_reader=lambda p: _tags(title="Song"))
    assert exp.evidence["matches"] is True
    assert exp.evidence["segments"] == [{"op": "equal", "a": "song", "b": "song"}]


def test_explain_is_read_only(tmp_path) -> None:
    p = _make_file(tmp_path, "Artist/Singles/2021 - Song.m4a")
    before = (p.read_bytes(), p.stat().st_mtime_ns, sorted(x.name for x in p.parent.iterdir()))
    explain_finding(_finding(), tmp_path, tag_reader=lambda q: _tags(title="Other"))
    assert (p.read_bytes(), p.stat().st_mtime_ns, sorted(x.name for x in p.parent.iterdir())) == before


def test_default_tag_reader_is_resolved_at_call_time(tmp_path, monkeypatch) -> None:
    import services.library_health.finding_explain as fe

    _make_file(tmp_path, "Artist/Singles/2021 - Song.m4a")
    monkeypatch.setattr(fe, "read_tags", lambda p: _tags(title="Patched"))
    assert explain_finding(_finding(), tmp_path).evidence["title"] == "Patched"
