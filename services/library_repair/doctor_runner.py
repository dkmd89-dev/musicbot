# services/library_repair/doctor_runner.py
# -*- coding: utf-8 -*-
"""
Reine Subprozess-Orchestrierung fuer scripts/library_health_check.py und
scripts/library_repair.py (Phase 3, P1.3 "MusicBot Doctor").

Ruft beide Skripte AUSSCHLIESSLICH als eigenstaendige Subprozesse auf,
importiert sie nie - gleiches Muster wie
services/metadata/reprocessing_runner.py fuer
scripts/reprocess_artist_metadata.py. Beide Ziel-Skripte sind rein
synchron (kein `async def`); der Subprozess-Weg haelt den Bot-Event-Loop
frei und isoliert einen Scanner-/Executor-Absturz vom Bot-Prozess.

Keine Telegram-Importe (CLAUDE.md Abschnitt 4, Schichtgrenze services/).
Der Telegram-seitige Aufrufer ist handlers/library_doctor_handler.py.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from logger import get_module_logger

logger = get_module_logger("LibraryDoctorRunner")

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
HEALTH_CHECK_SCRIPT = SCRIPTS_DIR / "library_health_check.py"
REPAIR_SCRIPT = SCRIPTS_DIR / "library_repair.py"

# Ein Health-Scan gegen die reale Library kann laut LIBRARY_HEALTH.md
# mehrere Minuten dauern (insbesondere mit --measure-loudness, hier bewusst
# NICHT gesetzt - Doctor macht einen schnellen Tag-/Struktur-Scan, keine
# Loudness-Analyse). Grosszuegiger Timeout als Sicherheitsnetz gegen einen
# haengenden Subprozess, keine realistische Normalerwartung.
DEFAULT_TIMEOUT_SECONDS = 900.0


@dataclass
class DoctorScanResult:
    """Ergebnis eines library_health_check.py-Subprozess-Laufs."""

    exit_code: Optional[int]
    report: Optional[Dict[str, Any]]
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.report is not None


@dataclass
class DoctorRepairResult:
    """Ergebnis eines library_repair.py --level SAFE_AUTOMATIC --apply-Laufs."""

    exit_code: Optional[int]
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0


async def _run_subprocess(
    cmd: list, timeout: float
) -> Tuple[Optional[int], str, str, Optional[str], bool]:
    """Gemeinsame Subprozess-Mechanik fuer beide Doctor-Laeufe. Gibt
    (returncode, stdout, stderr, error_message, timed_out) zurueck -
    error_message gesetzt heisst: kein returncode verfuegbar (Start-
    Fehler oder Timeout)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return None, "", "", f"Subprozess konnte nicht gestartet werden: {e}", False

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (
            None, "", "",
            f"Timeout nach {timeout:.0f}s - Prozess wurde beendet.",
            True,
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    return proc.returncode, stdout_text, stderr_text, None, False


async def run_health_scan(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> DoctorScanResult:
    """Startet scripts/library_health_check.py --json <tmp-Datei> als
    Subprozess (read-only, siehe docs/LIBRARY_HEALTH.md) und liest den
    erzeugten JSON-Report zurueck."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = Path(tmp_dir) / "doctor_report.json"
        cmd = [sys.executable, str(HEALTH_CHECK_SCRIPT), "--json", str(json_path)]

        logger.info("🩺 Starte Library-Health-Scan (Doctor)")
        returncode, stdout_text, stderr_text, error_message, timed_out = (
            await _run_subprocess(cmd, timeout)
        )

        if error_message:
            logger.error(f"❌ Health-Scan-Subprozess-Fehler: {error_message}")
            return DoctorScanResult(
                exit_code=None, report=None, timed_out=timed_out,
                error_message=error_message,
            )

        report: Optional[Dict[str, Any]] = None
        if json_path.exists():
            try:
                report = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"❌ Health-Report unlesbar nach Scan: {e}")

        if returncode == 0:
            logger.info("✅ Health-Scan erfolgreich beendet")
        else:
            logger.warning(f"⚠️ Health-Scan beendet mit Exit-Code {returncode}")

        return DoctorScanResult(
            exit_code=returncode, report=report,
            stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
        )


async def run_safe_automatic_repair(
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> DoctorRepairResult:
    """Startet scripts/library_repair.py --level SAFE_AUTOMATIC --apply als
    Subprozess - bewusst NUR dieser eine, verlustfreie Level (siehe
    docs/LIBRARY_REPAIR.md §3: kein Netzwerk, kein Re-Encode). Alle
    externen/destruktiven Level (COVER/EXTERNAL_METADATA/
    METADATA_REPROCESSING/LOUDNESS/DUPLICATE) bleiben ueber diesen Weg
    bewusst unerreichbar - das ist keine Vereinfachung, sondern dieselbe
    Sicherheitsgrenze, die --apply auch auf der Kommandozeile hat."""
    cmd = [
        sys.executable, str(REPAIR_SCRIPT),
        "--level", "SAFE_AUTOMATIC", "--apply",
    ]

    logger.info("🔧 Starte SAFE_AUTOMATIC-Repair (Doctor)")
    returncode, stdout_text, stderr_text, error_message, timed_out = (
        await _run_subprocess(cmd, timeout)
    )

    if error_message:
        logger.error(f"❌ Repair-Subprozess-Fehler: {error_message}")
        return DoctorRepairResult(
            exit_code=None, timed_out=timed_out, error_message=error_message,
        )

    if returncode == 0:
        logger.info("✅ Repair-Lauf erfolgreich beendet")
    else:
        logger.warning(f"⚠️ Repair-Lauf beendet mit Exit-Code {returncode}")

    return DoctorRepairResult(
        exit_code=returncode,
        stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
    )
