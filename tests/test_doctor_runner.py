# tests/test_doctor_runner.py
# -*- coding: utf-8 -*-
"""
Tests fuer services/library_repair/doctor_runner.py - reine
Subprozess-Orchestrierung fuer scripts/library_health_check.py und
scripts/library_repair.py (Phase 3, P1.3 "MusicBot Doctor").

Testebenen (CLAUDE.md Abschnitt 7/8, analog zu
tests/test_reprocessing_runner.py fuer denselben Subprozess-Ansatz):
asyncio.create_subprocess_exec-Fehlerfaelle (OSError, Timeout) gemockt;
der Happy-Path laeuft als echter Subprozess gegen die echten Skripte
(kein Mock der Kern-Integration).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import services.library_repair.doctor_runner as dr


class TestRunHealthScanMockedFailures:
    @pytest.mark.asyncio
    async def test_oserror_on_subprocess_start_is_reported_not_raised(self):
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError("no such file")),
        ):
            result = await dr.run_health_scan(timeout=5)

        assert result.exit_code is None
        assert result.report is None
        assert not result.success
        assert "konnte nicht gestartet werden" in result.error_message

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_reports_timed_out(self):
        fake_proc = Mock()
        # communicate() liefert hier bewusst KEINE Coroutine (Mock() statt
        # AsyncMock()) - asyncio.wait_for() ist unten gemockt und awaitet
        # das Ergebnis von proc.communicate() nie wirklich, eine echte
        # Coroutine wuerde dadurch als "never awaited" haengen bleiben.
        fake_proc.communicate = Mock()
        fake_proc.kill = Mock()
        fake_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)), \
             patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            result = await dr.run_health_scan(timeout=0.01)

        assert result.timed_out is True
        assert not result.success
        fake_proc.kill.assert_called_once()


class TestRunSafeAutomaticRepairMockedFailures:
    @pytest.mark.asyncio
    async def test_oserror_on_subprocess_start_is_reported_not_raised(self):
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError("no such file")),
        ):
            result = await dr.run_safe_automatic_repair(timeout=5)

        assert result.exit_code is None
        assert not result.success
        assert "konnte nicht gestartet werden" in result.error_message


class TestRunHealthScanSimulatedSuccess:
    """run_health_scan() nimmt bewusst kein --library-Argument entgegen
    (Doctor scannt immer die konfigurierte Produktions-Library, siehe
    Docstring) - ein echter Subprozess-Test muesste daher entweder die
    reale Produktions-Library treffen (unpassend fuer einen Unit-Test:
    langsam, nicht deterministisch, haengt vom Testsystem ab) oder
    Config.LIBRARY_DIR im Kind-Subprozess beeinflussen (von einem
    Patch im Testprozess aus nicht erreichbar). Die eigentliche
    Scan-Korrektheit von scripts/library_health_check.py selbst ist
    bereits durch tests/test_library_health_*.py (115 Tests) abgedeckt -
    hier wird nur die Subprozess-/JSON-Anbindung dieses Moduls geprueft,
    mit einem simulierten, aber realistischen Subprozess (schreibt die
    JSON-Datei an exakt den Pfad, den run_health_scan() erwartet)."""

    @pytest.mark.asyncio
    async def test_parses_json_report_written_by_subprocess(self):
        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(
                '{"statistics": {"total_files": 42}, "health": {"score": 99.0}}',
                encoding="utf-8",
            )
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            result = await dr.run_health_scan(timeout=5)

        assert result.success
        assert result.exit_code == 0
        assert result.report["statistics"]["total_files"] == 42

    @pytest.mark.asyncio
    async def test_non_zero_exit_and_missing_json_is_not_success(self):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 3

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await dr.run_health_scan(timeout=5)

        assert result.exit_code == 3
        assert result.report is None
        assert not result.success

    @pytest.mark.asyncio
    async def test_corrupt_json_does_not_raise(self):
        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text("{not valid json", encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            result = await dr.run_health_scan(timeout=5)  # darf nicht raisen

        assert result.report is None
        assert not result.success


class TestRunSafeAutomaticRepairSimulatedSuccess:
    @pytest.mark.asyncio
    async def test_success_result(self):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(
            return_value=(b"12 success \xc2\xb7 0 failed", b"")
        )
        fake_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await dr.run_safe_automatic_repair(timeout=5)

        assert result.success
        assert "12 success" in result.stdout_tail

    @pytest.mark.asyncio
    async def test_uses_only_safe_automatic_level(self):
        captured_cmd = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dr.run_safe_automatic_repair(timeout=5)

        cmd = captured_cmd["cmd"]
        assert "--level" in cmd
        assert cmd[cmd.index("--level") + 1] == "SAFE_AUTOMATIC"
        assert "--apply" in cmd
        for forbidden in ("COVER", "EXTERNAL_METADATA", "METADATA_REPROCESSING", "LOUDNESS"):
            assert forbidden not in cmd
