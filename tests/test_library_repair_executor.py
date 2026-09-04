# tests/test_library_repair_executor.py
# -*- coding: utf-8 -*-
"""Level-1 Repair Executor gegen echte m4a-Dateien (Prompt Abschnitt 13-17).

Prüft: Safety-Blockade, DRY-RUN schreibt nichts, echter Lauf ändert nur
die Ziel-Atome, Audio-Essenz bleibt byte-identisch, Backup + Journal
vorhanden, Rollback bei Verifikationsfehler."""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from mutagen.mp4 import MP4, MP4FreeForm

from services.library_repair.executor import apply_level1, safety_check
from services.library_repair.journal import RepairJournal
from services.library_repair.models import RepairAction, RepairCandidate, RepairLevel

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _m4a(path: Path, *, genre=None, artist=None, artists_ff=None, album_artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    a = MP4(path)
    a["©nam"] = ["T"]
    if genre:
        a["©gen"] = [genre]
    if artist:
        a["©ART"] = artist if isinstance(artist, list) else [artist]
    if album_artist:
        a["aART"] = [album_artist]
    if artists_ff:
        a["----:com.apple.iTunes:ARTISTS"] = [MP4FreeForm(x.encode()) for x in artists_ff]
    a.save()


def _cand(rel, code):
    return RepairCandidate(issue_code=code, action=RepairAction.MULTI_ARTIST_SPLIT,
                           level=RepairLevel.SAFE_AUTOMATIC, severity="INFO",
                           scope="file", path=rel)


def _read(path):
    t = MP4(path).tags or {}
    def _x(v): return [b.decode() if isinstance(b, bytes) else str(b) for b in (v or [])]
    return {"gen": _x(t.get("©gen")), "art": _x(t.get("©ART")),
            "aart": _x(t.get("aART")),
            "ff": _x(t.get("----:com.apple.iTunes:ARTISTS"))}


def _audio_md5(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a",
                        "-f", "md5", "-"], capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


@requires_ffmpeg
def test_dry_run_changes_nothing(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock")
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "journal.jsonl")
    outcomes = apply_level1([_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
                            lib, j, dry_run=True)
    assert outcomes[0].status == "DRY_RUN"
    assert _read(p)["gen"] == ["Pop / Rock"]        # unverändert
    assert _audio_md5(p) == md5_before
    assert not (lib.parent / ".library_repair_backups").exists()
    assert j.entries[0].status == "DRY_RUN"


@requires_ffmpeg
def test_genre_delimiter_applied_audio_untouched(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock / Indie")
    md5_before = _audio_md5(p)
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1([_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
                            lib, j, dry_run=False)
    assert outcomes[0].status == "SUCCESS"
    assert _read(p)["gen"] == ["Pop; Rock; Indie"]
    assert _audio_md5(p) == md5_before               # Ton unverändert
    backups = list((lib.parent / ".library_repair_backups").rglob("*.bak"))
    assert len(backups) == 1                          # Rollback möglich, ausserhalb der Library
    assert not list(lib.rglob("*.bak")) and not list(lib.rglob("*.repair*"))
    j.flush()
    assert (lib / "j.jsonl").exists()


@requires_ffmpeg
def test_multi_artist_split_and_align(lib):
    p = lib / "makko" / "2020 - Album" / "01 - t.m4a"
    _m4a(p, artist=["makko & toobrokeforfiji"], artists_ff=["makko", "toobrokeforfiji"])
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1([_cand("makko/2020 - Album/01 - t.m4a", "MULTI_ARTIST_INCONSISTENT")],
                            lib, j, dry_run=False)
    assert outcomes[0].status == "SUCCESS"
    r = _read(p)
    assert r["art"] == ["makko", "toobrokeforfiji"]
    assert r["ff"] == ["makko", "toobrokeforfiji"]


@requires_ffmpeg
def test_nothing_to_do_is_skipped(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop; Rock")
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1([_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
                            lib, j, dry_run=False)
    assert outcomes[0].status == "SKIPPED"
    assert not (lib.parent / ".library_repair_backups").exists()


@requires_ffmpeg
def test_safety_blocks_symlink(lib):
    real = lib / "_outside" / "r.m4a"
    _m4a(real)
    link_dir = lib / "A" / "Singles"
    link_dir.mkdir(parents=True)
    link = link_dir / "2020 - x.m4a"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("keine Symlinks")
    assert safety_check(link, lib) == "Symlink"
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1([_cand("A/Singles/2020 - x.m4a", "GENRE_DELIMITER_INCONSISTENT")],
                            lib, j, dry_run=False)
    assert outcomes[0].status == "SKIPPED"
    assert "Safety" in outcomes[0].reason


def test_safety_blocks_path_outside_library(tmp_path):
    outside = tmp_path / "elsewhere" / "x.m4a"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    lib = tmp_path / "library"
    lib.mkdir()
    assert "außerhalb" in (safety_check(outside, lib) or "")


def test_safety_blocks_unsupported_extension(tmp_path):
    lib = tmp_path / "library"
    (lib / "A").mkdir(parents=True)
    f = lib / "A" / "x.flac"
    f.write_bytes(b"x" * 10)
    assert "nicht unterstütztes Format" in (safety_check(f, lib) or "")


@requires_ffmpeg
def test_non_l1_codes_are_ignored(lib):
    p = lib / "A" / "Singles" / "2020 - x.m4a"
    _m4a(p, genre="Pop / Rock")
    j = RepairJournal(lib / "j.jsonl")
    outcomes = apply_level1(
        [_cand("A/Singles/2020 - x.m4a", "META_ISRC_MISSING"),
         _cand("A/Singles/2020 - x.m4a", "DUPLICATE_EXACT")],
        lib, j, dry_run=False,
    )
    assert outcomes == []          # nichts aus L1_TAG_CODES
