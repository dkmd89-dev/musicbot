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
import logging
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


SAMPLE_REPORT_JSON = (
    '{"statistics": {"total_files": 42, '
    '"issues_by_severity": {"ERROR": 1, "WARNING": 2, "INFO": 5, "CRITICAL": 0}}, '
    '"health": {"score": 99.0}}'
)


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
    JSON-Datei an exakt den Pfad, den run_health_scan() erwartet).

    Config.DATA_DIR wird in jedem Test auf tmp_path umgeleitet - seit der
    Persistierungs-Aenderung (Doctor schreibt an den echten, konfigurierten
    Pfad statt in ein isoliertes Tempverzeichnis) wuerde ein ungepatchter
    Testlauf sonst reale Dateien unter dem echten cache/data/ hinterlassen."""

    @pytest.mark.asyncio
    async def test_json_path_is_the_canonical_config_data_dir_path(self, tmp_path):
        """Kein zweiter/eigener Pfad - derselbe Ausdruck wie die CLI-eigene
        Default-Logik (scripts/library_health_check.py) und die
        Library-Statistics-Ansicht (mugge_statistik_handler.py)."""
        captured_cmd = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dr.run_health_scan(timeout=5)

        json_arg = Path(captured_cmd["cmd"][captured_cmd["cmd"].index("--json") + 1])
        assert json_arg == tmp_path / "library_health_report.json"

    @pytest.mark.asyncio
    async def test_parses_json_report_written_by_subprocess(self, tmp_path):
        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            result = await dr.run_health_scan(timeout=5)

        assert result.success
        assert result.exit_code == 0
        assert result.report["statistics"]["total_files"] == 42

    @pytest.mark.asyncio
    async def test_report_is_persisted_at_expected_path_and_is_valid_json(self, tmp_path):
        """Deckt explizit ab, was Aufgabe 1 verlangt: die Datei liegt nach
        dem Lauf tatsaechlich persistent auf der Platte (nicht nur
        transient im Rueckgabewert) und ist valides JSON."""
        import json as _json

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dr.run_health_scan(timeout=5)

        persisted_path = tmp_path / "library_health_report.json"
        assert persisted_path.exists()
        parsed = _json.loads(persisted_path.read_text(encoding="utf-8"))
        assert parsed["statistics"]["total_files"] == 42

    @pytest.mark.asyncio
    async def test_non_zero_exit_and_missing_json_is_not_success(self, tmp_path):
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"boom"))
        fake_proc.returncode = 3

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await dr.run_health_scan(timeout=5)

        assert result.exit_code == 3
        assert result.report is None
        assert not result.success

    @pytest.mark.asyncio
    async def test_corrupt_json_does_not_raise(self, tmp_path):
        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text("{not valid json", encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            result = await dr.run_health_scan(timeout=5)  # darf nicht raisen

        assert result.report is None
        assert not result.success


class TestRunHealthScanDoctorLogging:
    """Aufgabe 1 (Doctor-Logging): jeder Schritt des Ablaufs
    (START -> SCAN -> REPORT -> SAVE -> SUMMARY) muss unter dem Praefix
    "🏥 [DOCTOR]" eindeutig in bot.log nachvollziehbar sein."""

    @pytest.mark.asyncio
    async def test_logs_started_before_subprocess_call(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="LibraryDoctorRunner")

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dr.run_health_scan(timeout=5)

        assert "🏥 [DOCTOR] Health-Scan gestartet" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_completed_report_saved_and_summary_on_success(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="LibraryDoctorRunner")

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            json_path = Path(cmd[cmd.index("--json") + 1])
            json_path.write_text(SAMPLE_REPORT_JSON, encoding="utf-8")
            fake_proc = Mock()
            fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            fake_proc.returncode = 0
            return fake_proc

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=fake_create_subprocess_exec):
            await dr.run_health_scan(timeout=5)

        expected_path = tmp_path / "library_health_report.json"
        assert "🏥 [DOCTOR] Health-Scan abgeschlossen" in caplog.text
        assert f"🏥 [DOCTOR] Report gespeichert: {expected_path}" in caplog.text
        # issues_by_severity: ERROR 1 + WARNING 2 + CRITICAL 0 = 3 (INFO
        # zaehlt bewusst nicht mit, siehe LIBRARY_HEALTH.md §4 "Observation
        # != Defect" - dieselbe Konvention wie die Telegram-Doctor-Anzeige).
        assert "🏥 [DOCTOR] Score: 99.0 | Files: 42 | Issues: 3" in caplog.text

    @pytest.mark.asyncio
    async def test_non_zero_exit_logs_failure_not_success(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="LibraryDoctorRunner")
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b"library nicht gefunden"))
        fake_proc.returncode = 2

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            await dr.run_health_scan(timeout=5)

        assert "🏥 [DOCTOR] Health-Scan fehlgeschlagen" in caplog.text
        assert "🏥 [DOCTOR] Health-Scan abgeschlossen" not in caplog.text
        assert "🏥 [DOCTOR] Report gespeichert" not in caplog.text

    @pytest.mark.asyncio
    async def test_subprocess_start_failure_logs_failure_at_that_step(self, caplog):
        caplog.set_level(logging.INFO, logger="LibraryDoctorRunner")

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError("no such file")),
        ):
            await dr.run_health_scan(timeout=5)

        assert "🏥 [DOCTOR] Health-Scan gestartet" in caplog.text
        assert "🏥 [DOCTOR] Health-Scan fehlgeschlagen" in caplog.text
        assert "🏥 [DOCTOR] Health-Scan abgeschlossen" not in caplog.text

    @pytest.mark.asyncio
    async def test_missing_report_file_despite_exit_zero_logs_failure_not_success(
        self, tmp_path, caplog
    ):
        """Verteidigungsfall: Exit-Code 0, aber die Datei existiert aus
        irgendeinem Grund trotzdem nicht - darf niemals als Erfolg geloggt
        werden (keine irrefuehrenden Erfolgsmeldungen)."""
        caplog.set_level(logging.INFO, logger="LibraryDoctorRunner")
        fake_proc = Mock()
        fake_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        fake_proc.returncode = 0  # schreibt aber bewusst KEINE Datei

        with patch.object(dr.Config, "DATA_DIR", tmp_path), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            result = await dr.run_health_scan(timeout=5)

        assert result.report is None
        assert "🏥 [DOCTOR] Report-Datei fehlt nach Scan" in caplog.text
        assert "🏥 [DOCTOR] Report gespeichert" not in caplog.text


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
