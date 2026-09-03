# services/metadata/reprocessing_runner.py
# -*- coding: utf-8 -*-
"""
Reine Subprozess-Orchestrierung fuer scripts/reprocess_artist_metadata.py.

Ruft das Skript AUSSCHLIESSLICH als eigenstaendigen Subprozess auf, importiert
es nie (siehe docs/METADATA_REPROCESSING.md Abschnitt 2a) - genau diese
Trennung macht die dort dokumentierten Singleton-Risiken
(EnhancedMetadataProcessor/ArtistNormalizer/GenreMapper sind SingletonMixin)
irrelevant, ohne den Singleton-Mechanismus der geteilten Metadata-Pipeline
selbst anfassen zu muessen.

Keine Telegram-Importe (CLAUDE.md Abschnitt 4, Schichtgrenze services/).
Der Telegram-seitige Aufrufer ist handlers/menu/reprocessing_menu_handler.py.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_module_logger

logger = get_module_logger("ReprocessingRunner")

# Muss mit scripts/reprocess_artist_metadata.py::DEFAULT_METADATEN_ROOT
# uebereinstimmen. Bewusst als eigene Konstante dupliziert statt importiert -
# scripts/ ist laut CLAUDE.md Abschnitt 4 keine Laufzeit-Schicht des Bots,
# dieses Modul soll den Bot-Prozess deshalb nicht mit scripts/ verknuepfen.
REPROCESSING_METADATEN_ROOT = Path("/tmp/musicbot_test/metadaten")

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "reprocess_artist_metadata.py"
)

# Grosszuegig bemessen (mehrere externe API-Aufrufe pro Track) - dient nur
# als Sicherheitsnetz gegen einen wirklich haengenden Subprozess, nicht als
# realistische Erwartung fuer normale Laeufe.
DEFAULT_TIMEOUT_SECONDS = 1800.0


@dataclass
class ReprocessingRunResult:
    """Ergebnis eines einzelnen reprocess_artist_metadata.py-Subprozess-Laufs."""

    exit_code: Optional[int]
    summary: Optional[Dict[str, Any]]
    log_path: Optional[str]
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.summary is not None


def list_available_artist_dirs() -> List[str]:
    """Listet die aktuell vorhandenen Artist-Verzeichnisse unter
    REPROCESSING_METADATEN_ROOT (sortiert, nur Verzeichnisse). Leere Liste,
    falls die Wurzel (noch) nicht existiert."""
    if not REPROCESSING_METADATEN_ROOT.exists():
        return []
    return sorted(
        p.name for p in REPROCESSING_METADATEN_ROOT.iterdir() if p.is_dir()
    )


def _parse_summary(stdout_text: str) -> Optional[Dict[str, Any]]:
    """main() schreibt zuletzt eine Zeile 'Log: <pfad>' gefolgt vom
    JSON-formatierten summary-Dict (json.dumps(summary, indent=2,
    default=str)). Liefert None, falls das Muster nicht gefunden wird oder
    das JSON nicht parsebar ist (z.B. Absturz vor diesem Punkt)."""
    lines = stdout_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Log: "):
            json_text = "\n".join(lines[i + 1 :])
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                return None
    return None


def _extract_log_path(stdout_text: str) -> Optional[str]:
    for line in stdout_text.splitlines():
        if line.startswith("Log: "):
            return line[len("Log: ") :].strip()
    return None


async def run_reprocessing(
    artist_dir_name: str,
    dry_run: bool,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ReprocessingRunResult:
    """Startet scripts/reprocess_artist_metadata.py als eigenstaendigen
    Subprozess fuer den gegebenen Artist-Ordnernamen (relativ zu
    REPROCESSING_METADATEN_ROOT) und wartet auf dessen Abschluss.

    Gibt bei jedem Fehlschlag (ungueltiger Pfad, Singleton-Safety-Abbruch,
    Timeout, ...) ein ReprocessingRunResult mit exit_code != 0 bzw.
    timed_out=True zurueck - wirft selbst keine Exception fuer erwartbare
    Fehlerfaelle des Subprozesses (PathSafetyError/SingletonSafetyError
    dort werden zu einem nicht-null Exit-Code plus Fehlertext auf stderr,
    genau wie bei der bestehenden CLI-Nutzung).
    """
    input_path = REPROCESSING_METADATEN_ROOT / artist_dir_name
    cmd = [sys.executable, str(SCRIPT_PATH), "--input", str(input_path)]
    if dry_run:
        cmd.append("--dry-run")

    logger.info(
        f"🔧 Starte Reprocessing-Subprozess ({'DRY-RUN' if dry_run else 'LIVE'}) "
        f"fuer Artist '{artist_dir_name}'"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        logger.error(f"❌ Reprocessing-Subprozess konnte nicht gestartet werden: {e}")
        return ReprocessingRunResult(
            exit_code=None,
            summary=None,
            log_path=None,
            error_message=f"Subprozess konnte nicht gestartet werden: {e}",
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.error(
            f"⏱️ Reprocessing-Subprozess fuer '{artist_dir_name}' nach "
            f"{timeout:.0f}s abgebrochen (Timeout)"
        )
        return ReprocessingRunResult(
            exit_code=None,
            summary=None,
            log_path=None,
            timed_out=True,
            error_message=f"Timeout nach {timeout:.0f}s - Prozess wurde beendet.",
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    summary = _parse_summary(stdout_text)
    log_path = summary.get("log") if summary else _extract_log_path(stdout_text)

    if proc.returncode != 0:
        logger.warning(
            f"⚠️ Reprocessing-Subprozess fuer '{artist_dir_name}' beendet mit "
            f"Exit-Code {proc.returncode}"
        )
    else:
        logger.info(
            f"✅ Reprocessing-Subprozess fuer '{artist_dir_name}' erfolgreich "
            f"beendet (Exit-Code 0)"
        )

    return ReprocessingRunResult(
        exit_code=proc.returncode,
        summary=summary,
        log_path=log_path,
        stdout_tail=stdout_text[-2000:],
        stderr_tail=stderr_text[-2000:],
    )
