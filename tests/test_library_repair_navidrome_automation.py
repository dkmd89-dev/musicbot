# tests/test_library_repair_navidrome_automation.py
# -*- coding: utf-8 -*-
"""
Phase 3, P1.2 — Navidrome-Scan-Automation nach scripts/library_repair.py
--apply. Reine CLI-Wiring-Tests: NavidromeScanTrigger.run_scan() wird
gemockt (kein echter Docker-/Subprocess-Aufruf), echte m4a-Fixtures nur
fuer den End-to-End-Pfad ueber main() (Muster aus
test_library_repair_executor.py uebernommen).
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "library_repair.py"

_spec = importlib.util.spec_from_file_location("library_repair_navidrome_cli", MODULE_PATH)
lr = importlib.util.module_from_spec(_spec)
sys.modules["library_repair_navidrome_cli"] = lr
_spec.loader.exec_module(lr)

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _m4a_with_delimiter_issue(path: Path):
    """Reales m4a mit GENRE_DELIMITER_INCONSISTENT (' / ' statt '; ') -
    ein SAFE_AUTOMATIC-Kandidat, den apply_level1() deterministisch fixt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    from mutagen.mp4 import MP4

    a = MP4(path)
    a["©nam"] = ["T"]
    a["©ART"] = ["A"]
    a["©alb"] = ["Al"]
    a["aART"] = ["A"]
    a["©gen"] = ["Pop / Rock"]
    a.save()


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


class TestTriggerNavidromeScanUnit:
    """Isolierte Tests fuer _trigger_navidrome_scan() (Erfolg/Fehlschlag/Exception)."""

    def test_success_result_does_not_raise(self):
        fake_result = MagicMock(success=True, returncode=0)
        with patch(
            "utils.navidrome_scan_trigger.NavidromeScanTrigger.run_scan",
            new=AsyncMock(return_value=fake_result),
        ):
            lr._trigger_navidrome_scan(Mock())  # darf nicht raisen

    def test_failed_result_does_not_raise_or_change_caller_state(self):
        fake_result = MagicMock(success=False, returncode=1)
        with patch(
            "utils.navidrome_scan_trigger.NavidromeScanTrigger.run_scan",
            new=AsyncMock(return_value=fake_result),
        ):
            lr._trigger_navidrome_scan(Mock())  # darf nicht raisen

    def test_exception_is_swallowed_and_logged(self):
        logger = Mock()
        with patch(
            "utils.navidrome_scan_trigger.NavidromeScanTrigger.run_scan",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            lr._trigger_navidrome_scan(logger)  # darf nicht raisen
        logger.warning.assert_called_once()


@requires_ffmpeg
class TestMainTriggersOnRealSuccess:
    def test_apply_with_real_success_triggers_scan_exactly_once(self, lib):
        _m4a_with_delimiter_issue(lib / "A" / "Singles" / "2020 - T.m4a")

        with patch.object(lr, "_trigger_navidrome_scan") as mock_trigger:
            exit_code = lr.main([
                "--library", str(lib), "--level", "SAFE_AUTOMATIC", "--apply",
            ])

        assert exit_code == 0
        mock_trigger.assert_called_once()

    def test_dry_run_never_triggers_scan_despite_fixable_issue(self, lib):
        _m4a_with_delimiter_issue(lib / "A" / "Singles" / "2020 - T.m4a")

        with patch.object(lr, "_trigger_navidrome_scan") as mock_trigger:
            exit_code = lr.main([
                "--library", str(lib), "--level", "SAFE_AUTOMATIC",
                "--apply", "--dry-run",
            ])

        assert exit_code == 0
        mock_trigger.assert_not_called()

    def test_opt_out_flag_suppresses_scan_despite_real_success(self, lib):
        _m4a_with_delimiter_issue(lib / "A" / "Singles" / "2020 - T.m4a")

        with patch.object(lr, "_trigger_navidrome_scan") as mock_trigger:
            exit_code = lr.main([
                "--library", str(lib), "--level", "SAFE_AUTOMATIC", "--apply",
                "--no-navidrome-scan",
            ])

        assert exit_code == 0
        mock_trigger.assert_not_called()

    def test_no_fixable_candidates_never_triggers_scan(self, lib):
        """Bereits sauber getaggte Datei -> kein Kandidat, fruehe Rueckkehr
        VOR der outcomes-/tally-Berechnung."""
        lib_file = lib / "A" / "Singles" / "2020 - T.m4a"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:a", "aac", "-b:a", "192k", str(lib_file), "-y", "-loglevel", "error"],
            check=True,
        )
        from mutagen.mp4 import MP4

        a = MP4(lib_file)
        a["©nam"] = ["T"]
        a["©ART"] = ["A"]
        a["©alb"] = ["Al"]
        a["aART"] = ["A"]
        a["©gen"] = ["Pop"]
        a.save()

        with patch.object(lr, "_trigger_navidrome_scan") as mock_trigger:
            exit_code = lr.main([
                "--library", str(lib), "--level", "SAFE_AUTOMATIC", "--apply",
            ])

        assert exit_code == 0
        mock_trigger.assert_not_called()
