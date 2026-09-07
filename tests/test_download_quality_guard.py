# tests/test_download_quality_guard.py
# -*- coding: utf-8 -*-
"""
Tests für services/downloader/download_quality_guard.py (Phase 3, P2.3,
Bad Download Detector — Stufe A, Observe-Only).

Reine Funktion, unit-testbar: ffprobe-Subprozess in den meisten Tests
gemockt; ein echter ffmpeg-Fixture-Test deckt den realen Happy-Path ab
(CLAUDE.md Abschnitt 8: externe Aufrufe nicht in jedem Unit-Test
wiederholen, aber mindestens einmal real verifizieren).
"""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from services.downloader.download_quality_guard import (
    OBSERVE_MIN_BITRATE_BPS,
    OBSERVE_MIN_DURATION_SECONDS,
    check_download_quality,
)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar"
)


def _fake_ffprobe_result(duration=None, bitrate=None, returncode=0):
    fmt = {}
    if duration is not None:
        fmt["duration"] = str(duration)
    if bitrate is not None:
        fmt["bit_rate"] = str(bitrate)
    stdout = json.dumps({"format": fmt}).encode("utf-8")
    return Mock(returncode=returncode, stdout=stdout, stderr=b"")


class TestCheckDownloadQualityMocked:
    def test_normal_file_is_not_suspicious(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=200.0, bitrate=192000),
        ):
            obs = check_download_quality(Path("/fake/song.m4a"))

        assert not obs.suspicious
        assert obs.flags == []
        assert obs.duration_seconds == 200.0
        assert obs.bitrate == 192000

    def test_very_short_duration_is_flagged(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=5.0, bitrate=192000),
        ):
            obs = check_download_quality(Path("/fake/song.m4a"))

        assert obs.suspicious
        assert any("kurz" in f for f in obs.flags)

    def test_low_bitrate_is_flagged(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=200.0, bitrate=64000),
        ):
            obs = check_download_quality(Path("/fake/song.m4a"))

        assert obs.suspicious
        assert any("Bitrate" in f for f in obs.flags)

    def test_duration_far_below_expected_is_flagged(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=17.0, bitrate=192000),
        ):
            obs = check_download_quality(
                Path("/fake/song.m4a"), expected_duration=200.0
            )

        assert obs.suspicious
        assert any("kürzer als erwartet" in f for f in obs.flags)

    def test_duration_close_to_expected_is_not_flagged(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=195.0, bitrate=192000),
        ):
            obs = check_download_quality(
                Path("/fake/song.m4a"), expected_duration=200.0
            )

        assert not obs.suspicious

    def test_no_expected_duration_skips_mismatch_check(self):
        with patch(
            "subprocess.run",
            return_value=_fake_ffprobe_result(duration=17.0, bitrate=192000),
        ):
            obs = check_download_quality(Path("/fake/song.m4a"), expected_duration=None)

        # 17s liegt unter OBSERVE_MIN_DURATION_SECONDS (20s) - wird ueber
        # die Mindestdauer-Regel geflaggt, nicht ueber den Mismatch.
        assert obs.suspicious
        assert not any("erwartet" in f for f in obs.flags)

    def test_ffprobe_failure_returns_none_values_not_suspicious(self):
        with patch("subprocess.run", return_value=_fake_ffprobe_result(returncode=1)):
            obs = check_download_quality(Path("/fake/broken.m4a"))

        assert obs.duration_seconds is None
        assert obs.bitrate is None
        assert not obs.suspicious  # kein Signal != verdaechtig - kein Raten

    def test_ffprobe_timeout_does_not_raise(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30),
        ):
            obs = check_download_quality(Path("/fake/hangs.m4a"))  # darf nicht raisen

        assert obs.duration_seconds is None
        assert not obs.suspicious

    def test_corrupt_json_output_does_not_raise(self):
        with patch(
            "subprocess.run",
            return_value=Mock(returncode=0, stdout=b"not json", stderr=b""),
        ):
            obs = check_download_quality(Path("/fake/song.m4a"))  # darf nicht raisen

        assert obs.duration_seconds is None
        assert not obs.suspicious

    def test_never_raises_regardless_of_input(self):
        """Stufe A darf unter keinen Umstaenden die aufrufende Pipeline
        crashen - das ist der wichtigste Vertrag dieses Moduls."""
        with patch("subprocess.run", side_effect=OSError("ffprobe missing")):
            obs = check_download_quality(Path("/fake/song.m4a"))  # darf nicht raisen
        assert not obs.suspicious


@requires_ffmpeg
class TestCheckDownloadQualityRealFile:
    def test_real_short_file_is_flagged(self, tmp_path):
        path = tmp_path / "short.m4a"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
            check=True,
        )

        obs = check_download_quality(path)

        assert obs.suspicious
        assert obs.duration_seconds is not None
        assert obs.duration_seconds < OBSERVE_MIN_DURATION_SECONDS

    def test_real_normal_file_is_not_flagged(self, tmp_path):
        path = tmp_path / "normal.m4a"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=25",
             "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
            check=True,
        )

        obs = check_download_quality(path)

        assert not obs.suspicious
        assert obs.bitrate is not None
