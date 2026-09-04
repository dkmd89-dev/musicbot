# tests/test_library_health_tag_reader.py
# -*- coding: utf-8 -*-
"""Read-only I/O-Adapter (tag_reader.py) gegen echte, per ffmpeg erzeugte
Dateien. Prompt Abschnitt 8/11/15/31."""

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from services.library_health.models import AnalysisState
from services.library_health.tag_reader import (
    measure_loudness, probe_stream, read_artwork, read_tags,
)

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _make_m4a(path: Path, *, seconds=2, tags=True, cover_px=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    if not tags and cover_px is None:
        return
    a = MP4(path)
    if tags:
        a["©nam"] = ["My Title"]
        a["©ART"] = ["Main Artist"]
        a["aART"] = ["Main Artist"]
        a["©alb"] = ["My Album"]
        a["©day"] = ["2022"]
        a["©gen"] = ["Pop; Rock"]
        a["trkn"] = [(3, 12)]
        a["©lyr"] = ["la la la"]
        a["----:com.apple.iTunes:MusicBrainz Recording Id"] = [b"rec-123"]
        a["----:com.apple.iTunes:ISRC"] = [b"DEXXX0000001"]
        a["----:com.apple.iTunes:ARTISTS"] = [b"Main Artist", b"Feature X"]
    if cover_px:
        buf = io.BytesIO()
        Image.new("RGB", (cover_px, cover_px), (10, 20, 30)).save(buf, "JPEG")
        a["covr"] = [MP4Cover(buf.getvalue(), imageformat=MP4Cover.FORMAT_JPEG)]
    a.save()


@requires_ffmpeg
def test_read_tags_full(tmp_path):
    p = tmp_path / "song.m4a"
    _make_m4a(p, cover_px=800)
    t = read_tags(p)
    assert t.state == AnalysisState.PRESENT
    assert t.artist == "Main Artist"
    assert t.title == "My Title"
    assert t.album == "My Album"
    assert t.year == "2022"
    assert t.genre == "Pop; Rock"
    assert t.track_number == 3
    assert t.mb_recording_id == "rec-123"
    assert t.isrc == "DEXXX0000001"
    assert t.artists_freeform == ["Main Artist", "Feature X"]
    assert t.lyrics == "la la la"


@requires_ffmpeg
def test_read_tags_no_tag_block(tmp_path):
    p = tmp_path / "bare.m4a"
    _make_m4a(p, tags=False)
    t = read_tags(p)
    # kein Tag-Block => MISSING, NICHT NOT_ANALYZABLE
    assert t.state in (AnalysisState.MISSING, AnalysisState.PRESENT)
    assert t.artist is None and t.title is None


@requires_ffmpeg
def test_read_tags_corrupt_file_is_not_analyzable(tmp_path):
    p = tmp_path / "broken.m4a"
    p.write_bytes(b"this is not an mp4 container at all")
    t = read_tags(p)
    assert t.state == AnalysisState.NOT_ANALYZABLE
    assert t.error


@requires_ffmpeg
def test_probe_stream_ok(tmp_path):
    p = tmp_path / "s.m4a"
    _make_m4a(p, seconds=3, tags=False)
    s = probe_stream(p)
    assert s.state == AnalysisState.PRESENT
    assert s.has_audio_stream is True
    assert s.codec == "aac"
    assert 2.5 < (s.duration_seconds or 0) < 3.6


@requires_ffmpeg
def test_probe_stream_corrupt(tmp_path):
    p = tmp_path / "broken.m4a"
    p.write_bytes(b"\x00" * 4096)
    s = probe_stream(p)
    assert s.state in (AnalysisState.NOT_ANALYZABLE, AnalysisState.INVALID)
    assert not s.has_audio_stream


@requires_ffmpeg
def test_read_artwork_present_and_measured(tmp_path):
    p = tmp_path / "s.m4a"
    _make_m4a(p, cover_px=640)
    art = read_artwork(p)
    assert art.state == AnalysisState.PRESENT
    assert art.present is True
    assert art.width == art.height == 640
    assert art.is_square is True
    assert art.mime_type == "image/jpeg"


@requires_ffmpeg
def test_read_artwork_missing(tmp_path):
    p = tmp_path / "s.m4a"
    _make_m4a(p, tags=True)
    art = read_artwork(p)
    assert art.state == AnalysisState.MISSING
    assert art.present is False


@requires_ffmpeg
def test_measure_loudness_returns_lufs_and_touches_nothing(tmp_path):
    p = tmp_path / "s.m4a"
    _make_m4a(p, seconds=3, tags=True, cover_px=200)
    before = (p.stat().st_size, p.stat().st_mtime_ns)
    ld = measure_loudness(p)
    assert ld.state == AnalysisState.PRESENT
    assert isinstance(ld.integrated_lufs, float)
    assert -70.0 < ld.integrated_lufs < 0.0
    assert ld.true_peak is not None
    # rein lesend: keine temp-Datei, Datei unveraendert
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before
    assert list(tmp_path.iterdir()) == [p]


@requires_ffmpeg
def test_measure_loudness_missing_file_is_not_analyzable(tmp_path):
    ld = measure_loudness(tmp_path / "does-not-exist.m4a")
    assert ld.state == AnalysisState.NOT_ANALYZABLE
    assert ld.integrated_lufs is None
