# tests/test_library_health_discovery.py
# -*- coding: utf-8 -*-
"""Discovery-Stufe des Library Health Scanners (Prompt Abschnitt 7/31).

Deterministisch, ohne echte Audiodateien — nur leere Dateien mit den
relevanten Endungen (discovery.py liest keine Tags)."""

import os
from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record, discover_files
from services.library_health.models import LibrarySection


def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_discovers_only_supported_extensions(tmp_path):
    _touch(tmp_path / "A" / "Singles" / "2020 - s.m4a")
    _touch(tmp_path / "A" / "Singles" / "cover.jpg")
    _touch(tmp_path / "A" / "Singles" / "notes.txt")
    _touch(tmp_path / "A" / "2019 - Album" / "01 - t.mp3")

    records = discover_files(tmp_path)
    rel = sorted(r.relative_path for r in records)
    assert rel == ["A/2019 - Album/01 - t.mp3", "A/Singles/2020 - s.m4a"]


def test_result_is_sorted_and_stable(tmp_path):
    for name in ("z.m4a", "a.m4a", "m.m4a"):
        _touch(tmp_path / "Artist" / "Singles" / name)
    first = [r.relative_path for r in discover_files(tmp_path)]
    second = [r.relative_path for r in discover_files(tmp_path)]
    assert first == second == sorted(first)


def test_single_classification(tmp_path):
    p = _touch(tmp_path / "Artist" / "Singles" / "2021 - Song.m4a")
    rec = build_file_record(p, tmp_path)
    assert rec.library_section is LibrarySection.MUSIC
    assert rec.is_singles is True
    assert rec.artist_directory == "Artist"
    assert rec.album_directory is None
    assert rec.path_classification == "SINGLE"


def test_album_classification(tmp_path):
    p = _touch(tmp_path / "Artist" / "2018 - Great Record" / "03 - Track.m4a")
    rec = build_file_record(p, tmp_path)
    assert rec.is_singles is False
    assert rec.album_directory == "2018 - Great Record"
    assert rec.path_classification == "ALBUM_LIKE"


def test_compilation_and_playlist_sections(tmp_path):
    comp = _touch(tmp_path / "Compilations" / "Some Channel" / "Artist - X.m4a")
    play = _touch(tmp_path / "Playlist" / "My Mix" / "Artist - Y.m4a")
    rc = build_file_record(comp, tmp_path)
    rp = build_file_record(play, tmp_path)
    assert rc.library_section is LibrarySection.COMPILATIONS
    assert rc.artist_directory is None and rc.album_directory == "Some Channel"
    assert rp.library_section is LibrarySection.PLAYLIST


def test_file_directly_under_library_root_is_unknown(tmp_path):
    p = _touch(tmp_path / "loose.m4a")
    rec = build_file_record(p, tmp_path)
    assert rec.library_section is LibrarySection.UNKNOWN
    assert rec.artist_directory is None


def test_file_directly_in_artist_dir(tmp_path):
    p = _touch(tmp_path / "Artist" / "song.m4a")
    rec = build_file_record(p, tmp_path)
    assert rec.library_section is LibrarySection.MUSIC
    assert rec.artist_directory == "Artist"
    assert rec.album_directory is None
    assert rec.is_singles is False


def test_symlinked_file_is_skipped(tmp_path):
    real = _touch(tmp_path / "_outside" / "real.m4a")
    link_dir = tmp_path / "Artist" / "Singles"
    link_dir.mkdir(parents=True)
    try:
        os.symlink(real, link_dir / "2020 - link.m4a")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks nicht unterstuetzt")
    # nur die echte Datei ausserhalb wird gefunden — nicht der Symlink,
    # und _outside liegt im tmp_path-Scan mit drin, ist aber kein Symlink:
    records = discover_files(tmp_path)
    rels = {r.relative_path for r in records}
    assert "Artist/Singles/2020 - link.m4a" not in rels
    assert "_outside/real.m4a" in rels


def test_missing_root_returns_empty(tmp_path):
    assert discover_files(tmp_path / "does-not-exist") == []
