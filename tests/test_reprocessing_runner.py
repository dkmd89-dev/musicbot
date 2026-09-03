# tests/test_reprocessing_runner.py
# -*- coding: utf-8 -*-
"""
Tests fuer services/metadata/reprocessing_runner.py - reine
Subprozess-Orchestrierung fuer scripts/reprocess_artist_metadata.py (siehe
docs/METADATA_REPROCESSING.md Abschnitt 2a).

Testebenen (CLAUDE.md Abschnitt 7/8): reine Parsing-Helfer
(_parse_summary/_extract_log_path) deterministisch gegen synthetische
Strings; asyncio.create_subprocess_exec-Fehlerfaelle (OSError, Timeout)
gemockt; der eigentliche Happy-Path UND der PathSafetyError-Fehlerfall
laufen als echter Subprozess gegen das echte
scripts/reprocess_artist_metadata.py (kein Mock der Kern-Integration -
genau das ist der interessante Teil dieses Moduls).
"""

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mutagen.mp4 import MP4

import services.metadata.reprocessing_runner as rr

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar"
)


def _make_real_m4a(path: Path):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.fixture
def real_artist_dir():
    """Ein echtes, temporaeres Artist-Verzeichnis UNTER der echten,
    hartcodierten Wurzel des Zielskripts (/tmp/musicbot_test/metadaten) -
    run_reprocessing() ruft das Skript mit dessen eigenen Path-Safety-
    Defaults auf, ein anderswo liegendes tmp_path wuerde dort als
    PathSafetyError abgelehnt."""
    name = f"_pytest_reprocessing_runner_{uuid.uuid4().hex[:8]}"
    artist_dir = rr.REPROCESSING_METADATEN_ROOT / name
    (artist_dir / "Singles").mkdir(parents=True)
    yield name, artist_dir
    shutil.rmtree(artist_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
# list_available_artist_dirs()
# ─────────────────────────────────────────────────────────────────────────


class TestListAvailableArtistDirs:
    def test_returns_empty_list_when_root_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rr, "REPROCESSING_METADATEN_ROOT", tmp_path / "does_not_exist")
        assert rr.list_available_artist_dirs() == []

    def test_returns_only_directories_sorted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rr, "REPROCESSING_METADATEN_ROOT", tmp_path)
        (tmp_path / "Zebra").mkdir()
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "not_a_dir.txt").write_text("x")

        assert rr.list_available_artist_dirs() == ["Alpha", "Zebra"]


# ─────────────────────────────────────────────────────────────────────────
# Reine Parsing-Helfer
# ─────────────────────────────────────────────────────────────────────────


class TestParseSummary:
    def test_parses_valid_summary_json_after_log_line(self):
        stdout = 'Log: /tmp/musicbot_test/foo.log\n{\n  "artist": "X",\n  "overall": "PASS"\n}\n'
        result = rr._parse_summary(stdout)
        assert result == {"artist": "X", "overall": "PASS"}

    def test_returns_none_when_no_log_line_present(self):
        assert rr._parse_summary("irgendein anderer Text ohne Log-Zeile") is None

    def test_returns_none_when_json_is_malformed(self):
        stdout = "Log: /tmp/x.log\n{invalid json"
        assert rr._parse_summary(stdout) is None


class TestExtractLogPath:
    def test_extracts_path_from_log_line(self):
        stdout = "irgendwas davor\nLog: /tmp/musicbot_test/foo.log\nirgendwas danach"
        assert rr._extract_log_path(stdout) == "/tmp/musicbot_test/foo.log"

    def test_returns_none_when_no_log_line(self):
        assert rr._extract_log_path("kein Log hier") is None


# ─────────────────────────────────────────────────────────────────────────
# run_reprocessing() - gemockte Fehlerfaelle
# ─────────────────────────────────────────────────────────────────────────


class TestRunReprocessingMockedFailures:
    @pytest.mark.asyncio
    async def test_oserror_on_subprocess_start_is_reported_not_raised(self):
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("kein Interpreter gefunden")),
        ):
            result = await rr.run_reprocessing("irgendein_artist", dry_run=True)

        assert result.exit_code is None
        assert result.summary is None
        assert not result.success
        assert "kein Interpreter gefunden" in result.error_message

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_reports_timed_out(self):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        fake_proc.kill = Mock()
        fake_proc.wait = AsyncMock(return_value=None)

        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)
        ):
            result = await rr.run_reprocessing(
                "irgendein_artist", dry_run=True, timeout=0.01
            )

        assert result.timed_out is True
        assert result.exit_code is None
        assert not result.success
        fake_proc.kill.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# run_reprocessing() - echter Subprozess gegen das echte Skript
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestRunReprocessingRealSubprocess:
    @pytest.mark.asyncio
    async def test_dry_run_against_real_tagged_file_succeeds(self, real_artist_dir):
        name, artist_dir = real_artist_dir
        path = artist_dir / "Singles" / "2024 - Test Titel.m4a"
        _make_real_m4a(path)
        audio = MP4(path)
        audio["©nam"] = ["Test Titel"]
        audio["©ART"] = ["Test Artist"]
        audio["aART"] = ["Test Artist"]
        audio.save()

        result = await rr.run_reprocessing(name, dry_run=True)

        assert result.exit_code == 0
        assert result.success
        assert result.summary["files_processed"] == 1
        assert result.summary["dry_run"] is True
        assert result.log_path

    @pytest.mark.asyncio
    async def test_nonexistent_artist_dir_fails_cleanly_via_path_safety_error(self):
        result = await rr.run_reprocessing(
            f"_pytest_does_not_exist_{uuid.uuid4().hex[:8]}", dry_run=True
        )

        assert result.exit_code != 0
        assert not result.success
        assert result.summary is None
        # Der CLI-Entry-Point (if __name__ == "__main__") gibt die
        # PathSafetyError-Meldung per print() aus - das landet auf stdout,
        # nicht stderr.
        assert "PATH SAFETY" in result.stdout_tail
