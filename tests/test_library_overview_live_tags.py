# -*- coding: utf-8 -*-
"""
Bugfix 2026-09-27 — Artist-Detail-Endpunkt liest editierbare Felder
live aus den Datei-Tags.

Hintergrund: Nach einem erfolgreichen Metadaten-Edit (Title/Artist/
Album/Albumartist/Genre/Jahr) ueber /library/{artist} zeigte die UI
weiterhin die alten Werte, weil der Endpunkt ausschliesslich aus dem
persistenten Report las und der Report nach einem Edit nicht
invalidiert wird.

Fix: `artist_detail_to_response(..., library_root=...)` liest die
editierbaren Felder pro Track live via
`services/library_health/tag_reader.py::read_tags()`. Aggregierte
Felder (file_size, issue_codes, mb_recording_id, isrc, integrated_lufs)
bleiben aus dem Report. Fallback bei Lesefehler: unveraenderter
Report-Wert, kein 500er.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pytest

from control_center.schemas.metadata import artist_detail_to_response


# =====================================================================
# Fixtures
# =====================================================================


def _have_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


needs_ffmpeg = pytest.mark.skipif(
    not _have_ffmpeg(), reason="ffmpeg nicht verfuegbar"
)


@pytest.fixture
def tmp_library(tmp_path: Path):
    """Erzeugt eine isolierte Mini-Library mit einem getaggten m4a-Track."""
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def _write_tagged_m4a(
    path: Path,
    *,
    title: str,
    artists: list[str],
    album: str,
    genre: Optional[str] = None,
    year: Optional[str] = None,
    album_artist: Optional[str] = None,
) -> None:
    """Erzeugt eine echte m4a-Datei via ffmpeg und setzt ihre Tags
    via mutagen — identisches Vorgehen wie in bestehenden
    Library-Health-Tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "0.1", "-c:a", "aac", "-y", str(path)],
        capture_output=True, check=True,
    )
    from mutagen.mp4 import MP4

    mp4 = MP4(str(path))
    mp4["\xa9nam"] = [title]
    mp4["\xa9ART"] = artists
    mp4["\xa9alb"] = [album]
    if album_artist:
        mp4["aART"] = [album_artist]
    if genre:
        mp4["\xa9gen"] = [genre]
    if year:
        mp4["\xa9day"] = [year]
    mp4.save()


def _make_report(
    *,
    relative_path: str,
    artist_directory: str,
    stale_values: dict,
) -> dict:
    """Baut einen Minimal-Report mit STALE-Werten fuer den Live-Read-Test."""
    track = {
        "relative_path": relative_path,
        "artist_directory": artist_directory,
        "artist": stale_values.get("artist", "STALE"),
        "album": stale_values.get("album", "STALE"),
        "title": stale_values.get("title", "STALE"),
        "album_artist": stale_values.get("album_artist", "STALE"),
        "genre": stale_values.get("genre", "STALE"),
        "year": stale_values.get("year", "1999"),
        "track_number": stale_values.get("track_number"),
        "disc_number": stale_values.get("disc_number"),
        "file_size": stale_values.get("file_size", 999),
        "issue_codes": stale_values.get("issue_codes", ["META_ISRC_MISSING"]),
        "mb_recording_id": None,
        "mb_release_id": None,
        "isrc": None,
        "integrated_lufs": None,
        "filename": Path(relative_path).name,
        "extension": "m4a",
        "library_section": "music",
        "album_directory": None,
    }
    return {
        "files": [track],
        "artists": [{
            "artist": artist_directory,
            "file_count": 1,
            "album_count": 0,
            "health_score": 100.0,
            "issue_codes": [],
        }],
        "albums": [],
    }


# =====================================================================
# Tests
# =====================================================================


class TestLiveReadEditableFields:
    @needs_ffmpeg
    def test_editierbare_felder_kommen_aus_tags(self, tmp_library: Path) -> None:
        """Kernvertrag: nach einem Edit liefert der Endpunkt die Tag-Werte,
        nicht die stale Report-Werte."""
        rel = "Apache/Singles/2026 - Testtrack -.m4a"
        _write_tagged_m4a(
            tmp_library / rel,
            title="Testtrack",
            artists=["Apache 207", "Nina Chuba"],
            album="Testalbum",
            genre="Hip Hop",
            year="2026",
        )
        report = _make_report(
            relative_path=rel,
            artist_directory="Apache",
            stale_values={
                "title": "Testtrack -",       # stale
                "artist": "Apache",           # stale
                "album": "Testtrack -",       # stale
                "genre": "Unknown",           # stale
                "year": "2025",               # stale
            },
        )

        resp = artist_detail_to_response(
            report, artist="Apache", stale=False, library_root=tmp_library,
        )
        track = resp.tracks[0]

        assert track.title == "Testtrack"
        assert track.artist == "Apache 207, Nina Chuba"
        assert track.album == "Testalbum"
        assert track.genre == "Hip Hop"
        assert track.year == "2026"

    @needs_ffmpeg
    def test_aggregierte_felder_bleiben_aus_report(self, tmp_library: Path) -> None:
        """file_size und issue_codes kommen weiterhin aus dem Report —
        Live-Read betrifft nur die editierbaren Felder."""
        rel = "Apache/Singles/track.m4a"
        _write_tagged_m4a(
            tmp_library / rel,
            title="T",
            artists=["A"],
            album="Alb",
        )
        report = _make_report(
            relative_path=rel,
            artist_directory="Apache",
            stale_values={
                "file_size": 999,
                "issue_codes": ["META_ISRC_MISSING", "LYRICS_MISSING"],
            },
        )
        resp = artist_detail_to_response(
            report, artist="Apache", stale=False, library_root=tmp_library,
        )
        track = resp.tracks[0]
        assert track.file_size == 999
        assert track.issue_codes == ["META_ISRC_MISSING", "LYRICS_MISSING"]

    def test_fallback_bei_fehlender_datei(self, tmp_library: Path) -> None:
        """Fehlende Datei → unveraenderter Report-Wert, kein Crash."""
        rel = "Apache/Singles/does-not-exist.m4a"
        report = _make_report(
            relative_path=rel,
            artist_directory="Apache",
            stale_values={"title": "Stale Title", "artist": "Stale Artist"},
        )
        # Kein File angelegt → Live-Read schlaegt fehl → Fallback
        resp = artist_detail_to_response(
            report, artist="Apache", stale=False, library_root=tmp_library,
        )
        track = resp.tracks[0]
        assert track.title == "Stale Title"
        assert track.artist == "Stale Artist"

    def test_ohne_library_root_bleiben_report_werte(
        self, tmp_library: Path,
    ) -> None:
        """Rueckwaertskompatibel: ohne library_root-Parameter greift
        der Live-Read nicht — bestehende Aufrufer (Tests, Konsumenten)
        sehen dieselben Werte wie vorher."""
        rel = "Apache/Singles/x.m4a"
        report = _make_report(
            relative_path=rel,
            artist_directory="Apache",
            stale_values={"title": "Nur aus Report", "artist": "Auch Report"},
        )
        resp = artist_detail_to_response(report, artist="Apache", stale=False)
        track = resp.tracks[0]
        assert track.title == "Nur aus Report"
        assert track.artist == "Auch Report"
