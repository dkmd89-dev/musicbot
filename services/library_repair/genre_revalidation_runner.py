# services/library_repair/genre_revalidation_runner.py
# -*- coding: utf-8 -*-
"""
Reine Subprozess-Orchestrierung für scripts/revalidate_genre.py (Library
Genre Management v2, Chat-Charakterisierung 2026-09-15).

Ruft das Skript AUSSCHLIESSLICH als eigenständigen Subprozess auf,
importiert services.library_repair.genre_revalidation NIE direkt aus dem
Telegram-Handler - identisches Prinzip wie doctor_runner.py/
duplicate_runner.py.

WARUM Subprozess (nicht in-process, wie schon bei ARCH-033 L2/L3
entschieden): GenreMapper und ArtistNormalizer sind beide SingletonMixin.
Ein in-process-Aufruf von genre_revalidation.run_genre_revalidation()
aus dem laufenden Bot-Prozess heraus wuerde NICHT frische Instanzen
konstruieren, sondern die BEREITS beim Bot-Start fuer die Live-Download-
Pipeline konstruierten Singletons wiederverwenden/potenziell parallel
mutieren - exakt dasselbe Risiko, das den Subprozess-Pfad fuer L2/L3
(ADR-0003-Implementierung) begruendet hat. Der Subprozess bekommt
dagegen einen komplett frischen Interpreter mit frischen Singletons.

Teilt sich den globalen Repair-Lock mit Finding-Repair/Maintenance/L2/L3/
Duplikat-Check (ADR-0004-Prinzip): scripts/revalidate_genre.py schreibt
sein JSON-Ergebnis an einen FESTEN Pfad (Config.DATA_DIR/
genre_revalidation_result.json) - zwei gleichzeitige Revalidierungen
wuerden sich sonst gegenseitig die Ergebnisdatei ueberschreiben, bevor
der jeweils andere Aufrufer sie zurückgelesen hat (identisches Argument
wie duplicate_runner.py).
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

logger = get_module_logger("GenreRevalidationRunner")

REVALIDATE_SCRIPT = SCRIPTS_DIR / "revalidate_genre.py"
DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass
class GenreRevalidationRunResult:
    """Ergebnis eines revalidate_genre.py-Subprozess-Laufs fuer EINEN
    Artist - `data` enthaelt das vollstaendige, per --json geschriebene
    RevalidationResult-Dict (siehe genre_revalidation.RevalidationResult)."""

    exit_code: Optional[int]
    data: Optional[Dict[str, Any]]
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code in (0, 1) and self.data is not None

    @property
    def outcome(self) -> Optional[str]:
        return self.data.get("outcome") if self.data else None

    @property
    def mutated(self) -> bool:
        return bool(self.data.get("mutated")) if self.data else False


def _json_path() -> Path:
    return Path(Config.DATA_DIR) / "genre_revalidation_result.json"


async def run_genre_revalidation_subprocess(
    artist: str, *, apply: bool = False, timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> GenreRevalidationRunResult:
    """Read-only Preview (apply=False) oder tatsaechliche Mutation
    (apply=True, nur wenn die Overturn-Regel erfuellt ist - siehe
    genre_revalidation.run_genre_revalidation()) fuer EINEN Artist."""
    json_path = _json_path()
    cmd = [sys.executable, str(REVALIDATE_SCRIPT), "--artist", artist, "--json", str(json_path)]
    if apply:
        cmd.append("--apply")

    logger.info(f"🔄 Genre-Revalidierung gestartet für Artist={artist} (apply={apply})")

    acquire_repair_lock()
    try:
        returncode, stdout_text, stderr_text, error_message, timed_out = (
            await _run_subprocess(cmd, timeout)
        )

        if error_message:
            logger.error(f"❌ Genre-Revalidierung fehlgeschlagen (Subprozess-Start/Timeout): {error_message}")
            return GenreRevalidationRunResult(
                exit_code=None, data=None, timed_out=timed_out, error_message=error_message,
            )

        if returncode not in (0, 1):
            # Exit-Code 1 = RevalidationResult.error_message gesetzt (z. B.
            # Last.fm-Fehler) - trotzdem gueltiges JSON, kein harter Fehler.
            logger.error(
                f"❌ Genre-Revalidierung fehlgeschlagen (Exit-Code {returncode}): "
                f"{stderr_text[-500:] or 'kein stderr'}"
            )
            return GenreRevalidationRunResult(
                exit_code=returncode, data=None,
                stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
            )

        data: Optional[Dict[str, Any]] = None
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"❌ Revalidierungs-Ergebnisdatei unlesbar: {e}")
        else:
            logger.error(f"❌ Revalidierungs-Ergebnisdatei fehlt nach Lauf: {json_path}")

        if data is not None:
            logger.info(
                f"✅ Genre-Revalidierung für {artist} abgeschlossen: "
                f"outcome={data.get('outcome')}, mutated={data.get('mutated')}"
            )

        return GenreRevalidationRunResult(
            exit_code=returncode, data=data,
            stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:],
        )
    finally:
        release_repair_lock()
