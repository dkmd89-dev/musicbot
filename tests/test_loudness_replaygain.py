# tests/test_loudness_replaygain.py
# -*- coding: utf-8 -*-
"""
Pipeline-Optimierung 2026-09-09 (K1): Schritt 15b schreibt einen
verlustfreien ReplayGain-Tag statt die Datei per FFmpeg-loudnorm neu zu
encodieren.

Kernabsicherung: der Audio-Stream bleibt **byte-identisch** (kein
Re-Encode), und die geschriebenen Freeform-Atome sind deckungsgleich zum
Library-Repair-Loudness-Executor / Health-Scanner
(`----:com.apple.iTunes:replaygain_track_gain` / `_peak`, lowercase).
"""

import shutil
import subprocess

import pytest

from services.metadata.loudness_replaygain import (
    _GAIN_ATOM,
    _PEAK_ATOM,
    apply_replaygain_tags,
)

FFMPEG = shutil.which("ffmpeg")
RSGAIN = shutil.which("rsgain")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _make_m4a(path, *, volume="0.3", freq=440, dur=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={dur}",
            "-af",
            f"volume={volume}",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
            "-y",
            "-loglevel",
            "error",
        ],
        check=True,
    )


def _audio_md5(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return (r.stdout or r.stderr).strip()


def _read_atom(path, atom):
    from mutagen.mp4 import MP4

    raw = (MP4(path).tags or {}).get(atom)
    if not raw:
        return None
    v = raw[0]
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


@requires_ffmpeg
class TestApplyReplayGainTags:
    def test_audio_stream_is_byte_identical(self, tmp_path):
        p = tmp_path / "t.m4a"
        _make_m4a(p, volume="0.05")  # leise → messbarer Gain
        before = _audio_md5(p)

        ok, gain = apply_replaygain_tags(str(p), -16.0)

        assert ok is True
        assert _audio_md5(p) == before, "Audio-Essenz verändert — Re-Encode!"

    def test_replaygain_atoms_are_written_lowercase(self, tmp_path):
        p = tmp_path / "t.m4a"
        _make_m4a(p, volume="0.05")

        ok, gain = apply_replaygain_tags(str(p), -16.0)
        assert ok is True

        gain_tag = _read_atom(p, _GAIN_ATOM)
        peak_tag = _read_atom(p, _PEAK_ATOM)
        assert gain_tag is not None and gain_tag.strip().endswith("dB")
        assert peak_tag is not None and float(peak_tag) > 0

        # UPPERCASE-Variante (rsgain-Default ohne -L) darf NICHT existieren —
        # der Health-Scanner liest nur die lowercase-Atome.
        from mutagen.mp4 import MP4

        keys = list((MP4(p).tags or {}).keys())
        assert "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN" not in keys

    def test_off_target_file_gets_nontrivial_gain(self, tmp_path):
        """Eine Datei, die nicht bei −16 LUFS liegt, bekommt einen
        spürbaren Gain-Wert (Vorzeichen hängt vom Testsignal ab)."""
        p = tmp_path / "quiet.m4a"
        _make_m4a(p, volume="0.02")
        ok, gain = apply_replaygain_tags(str(p), -16.0)
        assert ok is True
        assert gain is not None and abs(gain) > 1.0

    def test_missing_file_returns_false(self, tmp_path):
        ok, gain = apply_replaygain_tags(str(tmp_path / "nope.m4a"), -16.0)
        assert ok is False and gain is None

    def test_unsupported_extension_is_noop(self, tmp_path):
        p = tmp_path / "t.flac"
        p.write_bytes(b"not really flac")
        ok, gain = apply_replaygain_tags(str(p), -16.0)
        assert ok is True and gain is None


@requires_ffmpeg
class TestFfmpegFallbackPath:
    """rsgain wird ausgeklammert → der FFmpeg-Analyse-Fallback muss dieselbe
    lossless Tag-Behandlung liefern."""

    def test_fallback_writes_tags_without_rsgain(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain._rsgain_available",
            lambda: False,
        )
        p = tmp_path / "t.m4a"
        _make_m4a(p, volume="0.05")
        before = _audio_md5(p)

        ok, gain = apply_replaygain_tags(str(p), -16.0)

        assert ok is True
        assert _audio_md5(p) == before
        assert _read_atom(p, _GAIN_ATOM) is not None

    def test_fallback_within_tolerance_writes_no_tag(self, tmp_path, monkeypatch):
        """Liegt die Datei bereits ≤ 2 dB vom Ziel, schreibt der Fallback
        keinen Tag (deckungsgleich zu replaygain_repairs.TOLERANCE_DB)."""
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain._rsgain_available",
            lambda: False,
        )
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain._measure_loudness_ffmpeg",
            lambda path, timeout: (-16.5, -3.0),  # 0.5 dB vom Ziel
        )
        p = tmp_path / "t.m4a"
        _make_m4a(p)

        ok, gain = apply_replaygain_tags(str(p), -16.0)

        assert ok is True
        assert _read_atom(p, _GAIN_ATOM) is None

    def test_fallback_measurement_failure_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain._rsgain_available",
            lambda: False,
        )
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain._measure_loudness_ffmpeg",
            lambda path, timeout: (None, None),
        )
        p = tmp_path / "t.m4a"
        _make_m4a(p)

        ok, gain = apply_replaygain_tags(str(p), -16.0)
        assert ok is False and gain is None


@requires_ffmpeg
def test_replaygain_tag_survives_the_real_tagwriter(tmp_path):
    """Schritt 15b läuft VOR Schritt 17 (TagWriter). Der RG-Tag darf vom
    additiven TagWriter-Schreibpfad nicht überschrieben werden, und der
    Audio-Stream bleibt über beide Schritte byte-identisch."""
    from unittest.mock import Mock

    from services.metadata.tag_writer import TagWriter

    p = tmp_path / "track.m4a"
    _make_m4a(p, volume="0.05")
    md5_before = _audio_md5(p)

    ok, _ = apply_replaygain_tags(str(p), -16.0)
    assert ok is True
    assert _read_atom(p, _GAIN_ATOM) is not None

    TagWriter(logger=Mock()).write_tags(
        target_path=p,
        artist="Test Artist",
        album_info={"album": "Alb", "album_artist": "Test Artist", "year": 2024},
        title="Test Title",
        track_number=None,
        genres_result=None,
        lyrics="la la",
        cover_art=None,
        feat_artists=None,
        mb_ids={"recording_id": "abc"},
    )

    from mutagen.mp4 import MP4

    tags = MP4(p).tags
    assert _read_atom(p, _GAIN_ATOM) is not None, "RG-Tag vom TagWriter überschrieben"
    assert tags.get("©nam") == ["Test Title"]
    assert _audio_md5(p) == md5_before, "Audio-Essenz verändert (15b + 17)"
