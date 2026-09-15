# services/library_repair/duplicate_runner.py
# -*- coding: utf-8 -*-
"""
Reine Subprozess-Orchestrierung für scripts/resolve_duplicates.py
(Chat-Charakterisierung 2026-09-15, "Duplikat-Qualitäts-Check").

Ruft das Skript AUSSCHLIESSLICH als eigenständigen Subprozess auf,
importiert es nie - identisches Muster wie doctor_runner.py für
library_health_check.py/library_repair.py.

Bewusst NUR der Dry-Run-Scan (Preview, read-only) ist über Telegram
angebunden - kein Execute/Delete. Grund: der Nutzer hatte ursprünglich
"automatisch ersetzen statt nur melden" vorgeschlagen - das würde die
gesamte, im Projekt etablierte Sicherheitsphilosophie durchbrechen
(jede andere Mutation läuft über Plan → Preview → explizite Bestätigung
→ Execute, nie automatisch). Einigung im Chat: Erkennung + Vorschlag ja,
automatische Ausführung nein. Das tatsächliche Löschen bleibt für diese
erste Stufe CLI-only:

    scripts/library_repair.py --allow-delete --artist <Name> --apply

(dockt intern bereits an exakt dieses Skript an, siehe
docs/LIBRARY_REPAIR.md §6d). Eine Telegram-Anbindung des Löschens selbst
wäre eine eigene, spätere Entscheidung (ADR-0003-artiges Muster: erst
Preview etablieren, Execute-Freigabe separat).

WICHTIG (bei der Charakterisierung entdeckt, betrifft die Aufruf-Form
hier): scripts/resolve_duplicates.py kennt zwei komplett verschiedene
Scan-Roots:
  --artist <Name>   löst IMMER gegen ALLOWED_ROOT auf
                     (/tmp/musicbot_test/library, reine Testbibliothek) -
                     NIEMALS gegen die Produktionslibrary, unabhängig von
                     --execute.
  --path <Pfad>      ist der einzige Weg, die echte Produktionslibrary
                     (Config.LIBRARY_DIR, dort als "Read-Only-Produktions-
                     Root" registriert, siehe validate_scan_root() im
                     Skript) zu adressieren.
Dieser Runner ruft deshalb IMMER "--path <Config.LIBRARY_DIR>/<artist>"
auf, NIE "--artist" (das Skript-eigene --artist wäre hier ein stiller
No-Op gegen eine leere Testbibliothek, kein Fehler, aber auch kein
Ergebnis - ein leicht zu übersehender Stolperstein für jeden künftigen
Aufrufer dieses Moduls).

Teilt sich den bestehenden globalen Repair-Lock mit Finding-Repair/
Library-Maintenance/L2/L3 (ADR-0004-Prinzip) - nicht weil der Dry-Run
selbst die Library verändert (tut er nicht), sondern weil
REPORT_JSON_PATH eine einzige, feste Datei ist (kein Config.DATA_DIR-
Bezug, siehe scripts/resolve_duplicates.py) - zwei gleichzeitige Scans
würden sich sonst gegenseitig die Report-Datei überschreiben, bevor der
jeweils andere Aufrufer sie zurückgelesen hat.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from config import Config
from logger import get_module_logger
from services.library_repair.doctor_runner import SCRIPTS_DIR, _run_subprocess
from services.library_repair.run_tracking import acquire_repair_lock, release_repair_lock

logger = get_module_logger("DuplicateRunner")

RESOLVE_DUPLICATES_SCRIPT = SCRIPTS_DIR / "resolve_duplicates.py"

# Fest im Skript selbst verdrahtet (kein Config.DATA_DIR-Bezug, keine
# CLI-Override-Option) - siehe Modul-Docstring.
REPORT_JSON_PATH = Path("/tmp/musicbot_test/duplicate_resolution_report.json")

DEFAULT_TIMEOUT_SECONDS = 300.0


@dataclass
class DuplicateScanResult:
    """Ergebnis eines resolve_duplicates.py-Dry-Run-Laufs für EINEN Artist."""

    exit_code: Optional[int]
    report: Optional[Dict[str, Any]]
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.report is not None


async def run_duplicate_scan(
    artist: str, timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> DuplicateScanResult:
    """Read-only Dry-Run-Scan für EINEN Artist gegen die echte
    Produktionslibrary (siehe Modul-Docstring für --path statt
    --artist). Kein --execute, keine Mutation - reiner Lesezugriff auf
    die Library und die bereits bestehende Report-Datei."""
    artist_path = Path(Config.LIBRARY_DIR) / artist
    cmd = [sys.executable, str(RESOLVE_DUPLICATES_SCRIPT), "--path", str(artist_path)]

    logger.info(f"🔁 Duplikat-Scan gestartet für Artist={artist}")

    acquire_repair_lock()
    try:
        returncode, stdout_text, stderr_text, error_message, timed_out = (
            await _run_subprocess(cmd, timeout)
        )

        if error_message:
            logger.error(f"❌ Duplikat-Scan fehlgeschlagen (Subprozess-Start/Timeout): {error_message}")
            return DuplicateScanResult(
                exit_code=None, report=None, timed_out=timed_out,
                error_message=error_message,
            )

        if returncode not in (0, 3):
            # Exit-Code 3 = Safety-Violation-Erkennung des Skripts selbst
            # (Dateisystem hat sich waehrend des Scans veraendert) - wird
            # unten ueber report["read_only_intact"] transportiert, kein
            # harter Fehlerfall hier.
            logger.error(
                f"❌ Duplikat-Scan fehlgeschlagen (Exit-Code {returncode}): "
                f"{stderr_text[-500:] or 'kein stderr'}"
            )
            return DuplicateScanResult(
                exit_code=returncode, report=None,
                stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
            )

        report: Optional[Dict[str, Any]] = None
        if REPORT_JSON_PATH.exists():
            try:
                report = json.loads(REPORT_JSON_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"❌ Duplikat-Report-Datei unlesbar nach Scan: {e}")
        else:
            logger.error(f"❌ Duplikat-Report-Datei fehlt nach Scan (Exit-Code {returncode}): {REPORT_JSON_PATH}")

        if report is not None:
            logger.info(
                f"✅ Duplikat-Scan für {artist} abgeschlossen: "
                f"{report.get('duplicate_groups', 0)} Gruppe(n), "
                f"{report.get('resolved_groups', 0)} auto-auflösbar."
            )

        return DuplicateScanResult(
            exit_code=returncode, report=report,
            stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
        )
    finally:
        release_repair_lock()
