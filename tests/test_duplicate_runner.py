# tests/test_duplicate_runner.py
# -*- coding: utf-8 -*-
"""
services/library_repair/duplicate_runner.py — Subprozess-Orchestrierung
fuer scripts/resolve_duplicates.py (Chat-Charakterisierung 2026-09-15).

Testmuster identisch zu tests/test_doctor_runner.py::
TestRunHealthScanSimulatedSuccess: ein simulierter, aber realistischer
Subprozess schreibt REPORT_JSON_PATH, der eigentliche Subprozess wird
nie wirklich gestartet. Config.DATA_DIR wird auf tmp_path umgeleitet,
damit acquire_repair_lock()/release_repair_lock() nicht das echte
data/library_repair.lock beruehren. REPORT_JSON_PATH selbst wird PRO
TEST auf tmp_path gepatcht (das Skript verwendet einen fest verdrahteten
Pfad ausserhalb von Config.DATA_DIR, siehe Modul-Docstring) - ein
ungepatchter Testlauf wuerde sonst /tmp/musicbot_test/... beruehren.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import services.library_repair.duplicate_runner as dup_runner
from services.library_repair.run_tracking import RepairAlreadyRunningError

SAMPLE_REPORT_JSON = json.dumps({
    "timestamp": "2026-09-15T10:00:00+00:00",
    "root": "/mnt/musik_bilder/library/Bausa",
    "files_scanned": 12,
    "duplicate_groups": 1,
    "resolved_groups": 1,
    "manual_review_groups": 0,
    "single_candidate_groups": 10,
    "read_only_intact": True,
    "decisions": [
        {
            "artist": "bausa", "title": "chicago",
            "candidates": [
                {"path": "/mnt/musik_bilder/library/Bausa/a.m4a", "bitrate": 256},
                {"path": "/mnt/musik_bilder/library/Bausa/b.m4a", "bitrate": 128},
            ],
            "keep": "/mnt/musik_bilder/library/Bausa/a.m4a",
            "remove_proposal": ["/mnt/musik_bilder/library/Bausa/b.m4a"],
            "action": "RESOLVED",
            "reason": "higher bitrate",
            "evidence": [],
        },
    ],
})


def _fake_subprocess_writing_report(report_json: str, returncode: int = 0):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        dup_runner.REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        dup_runner.REPORT_JSON_PATH.write_text(report_json, encoding="utf-8")
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        fake_proc.returncode = returncode
        return fake_proc
    return fake_create_subprocess_exec


@pytest.fixture(autouse=True)
def _isolate_report_path(tmp_path, monkeypatch):
    monkeypatch.setattr(dup_runner, "REPORT_JSON_PATH", tmp_path / "report.json")


class TestRunDuplicateScanUsesPathNotArtist:
    """Kernanforderung der Charakterisierung: --artist wuerde IMMER gegen
    die Testbibliothek aufloesen, nie gegen Config.LIBRARY_DIR - der
    Runner MUSS --path verwenden."""

    @pytest.mark.asyncio
    async def test_command_uses_path_flag_with_library_dir_prefix(self, tmp_path):
        captured_cmd = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            dup_runner.REPORT_JSON_PATH.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        cmd = captured_cmd["cmd"]
        assert "--artist" not in cmd
        assert "--path" in cmd
        path_arg = cmd[cmd.index("--path") + 1]
        assert path_arg == "/mnt/musik_bilder/library/Bausa"

    @pytest.mark.asyncio
    async def test_never_passes_execute_flag(self, tmp_path):
        """Read-only Preview only - --execute darf hier nie auftauchen."""
        captured_cmd = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            dup_runner.REPORT_JSON_PATH.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert "--execute" not in captured_cmd["cmd"]
        assert "--confirm-production-execute" not in captured_cmd["cmd"]


class TestRunDuplicateScanSimulatedSuccess:
    @pytest.mark.asyncio
    async def test_parses_report_written_by_subprocess(self, tmp_path):
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_report(SAMPLE_REPORT_JSON)):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert result.success
        assert result.report["duplicate_groups"] == 1
        assert result.report["decisions"][0]["action"] == "RESOLVED"

    @pytest.mark.asyncio
    async def test_non_zero_unexpected_exit_is_not_success(self, tmp_path):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 2

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert not result.success
        assert result.report is None

    @pytest.mark.asyncio
    async def test_exit_code_3_safety_violation_still_parses_report(self, tmp_path):
        """Exit-Code 3 signalisiert eine vom Skript SELBST erkannte
        Safety-Violation (Dateisystem veraendert waehrend Scan) - der
        Report wird trotzdem zurueckgegeben, read_only_intact=False
        transportiert den Zustand an den Aufrufer."""
        violation_report = json.loads(SAMPLE_REPORT_JSON)
        violation_report["read_only_intact"] = False
        report_text = json.dumps(violation_report)

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_report(report_text, returncode=3)):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert result.report is not None
        assert result.report["read_only_intact"] is False

    @pytest.mark.asyncio
    async def test_corrupt_report_does_not_raise(self, tmp_path):
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_report("{not valid json")):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert result.report is None
        assert not result.success


class TestRunDuplicateScanMockedFailures:
    @pytest.mark.asyncio
    async def test_subprocess_start_failure_returns_error_message(self, tmp_path):
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(side_effect=OSError("no such file"))):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert result.exit_code is None
        assert result.error_message is not None
        assert not result.success

    @pytest.mark.asyncio
    async def test_timeout_returns_timed_out_true(self, tmp_path):
        import asyncio

        fake_proc = Mock()
        fake_proc.communicate = AsyncMock()
        fake_proc.kill = Mock()
        fake_proc.wait = AsyncMock()

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)), \
             patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            result = await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        assert result.timed_out
        assert not result.success

    @pytest.mark.asyncio
    async def test_lock_conflict_propagates_repair_already_running_error(self, tmp_path):
        """Teilt sich den globalen Repair-Lock mit Finding-Repair/
        Maintenance/L2/L3 (ADR-0004) - ein bereits laufender anderer
        Lauf muss den Scan verhindern statt gleichzeitig zu schreiben."""
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch.object(
                 dup_runner, "acquire_repair_lock",
                 side_effect=RepairAlreadyRunningError("läuft bereits"),
             ):
            with pytest.raises(RepairAlreadyRunningError):
                await dup_runner.run_duplicate_scan("Bausa", timeout=5)

    @pytest.mark.asyncio
    async def test_lock_released_after_successful_scan(self, tmp_path):
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec",
                   new=_fake_subprocess_writing_report(SAMPLE_REPORT_JSON)):
            await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        from services.library_repair.run_tracking import is_repair_running
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path):
            assert is_repair_running() is False

    @pytest.mark.asyncio
    async def test_lock_released_even_after_failure(self, tmp_path):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 2

        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path), \
             patch.object(dup_runner.Config, "LIBRARY_DIR", "/mnt/musik_bilder/library"), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            await dup_runner.run_duplicate_scan("Bausa", timeout=5)

        from services.library_repair.run_tracking import is_repair_running
        with patch.object(dup_runner.Config, "DATA_DIR", tmp_path):
            assert is_repair_running() is False
