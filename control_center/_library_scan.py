# control_center/_library_scan.py
# -*- coding: utf-8 -*-
"""
Gemeinsamer Scan-Aufruf fuer Endpunkte, die einen frischen Library-
Health-Report brauchen (routers/health.py, routers/repair.py) —
identischer run_scan()-Aufrufpfad wie scripts/library_health_check.py,
identische 404/500-Fehlerbehandlung an einer Stelle statt dupliziert
(Master-Prompt Regel 7).

load_cached_report() (Library Artist-Centric UX, CC-AC-1, Auftrag §7a)
ergaenzt einen LESENDEN Gegenpart: liest den bereits vorhandenen,
persistenten Report (`Config.DATA_DIR/library_health_report.json`,
befuellt von scripts/library_health_check.py bzw. dem Telegram-„MusicBot
Doctor"-Subprozess ueber services/library_repair/doctor_runner.py::
run_health_scan(), siehe LIBRARY_REPAIR.md §9) STATT einen neuen Scan
auszuloesen. `run_library_scan()` oben bleibt fuer seine bestehenden
Konsumenten (health.py/repair.py/metadata.py, allesamt bewusst
Klick-/Job-ausgeloest, nie Seiten-Auto-Load) unveraendert."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from config import Config
from services.library_health.scanner import run_scan

from .schemas.errors import ErrorDetail


def run_library_scan(*, logger) -> dict:
    """Führt einen frischen Library-Health-Scan aus.

    Wirft HTTPException(404), wenn das konfigurierte Library-Root nicht
    existiert, HTTPException(500) bei einem Scan-Fehler — beide bereits im
    einheitlichen Fehlerformat (control_center/schemas/errors.py)."""
    config = Config()
    library_root = Path(config.LIBRARY_DIR)

    if not library_root.is_dir():
        request_id = uuid.uuid4().hex
        logger.error(f"[{request_id}] Library-Verzeichnis nicht gefunden: {library_root}")
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="LIBRARY_ROOT_NOT_FOUND",
                message="Konfiguriertes Library-Verzeichnis existiert nicht.",
                request_id=request_id,
            ).model_dump(),
        )

    try:
        return run_scan(
            library_root,
            supported_extensions=tuple(config.SUPPORTED_FORMATS),
            expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
            genre_mapping_dir=config.GENRE_MAPPING_DIR,
            logger=logger,
        )
    except Exception as e:  # noqa: BLE001
        request_id = uuid.uuid4().hex
        logger.error(f"[{request_id}] Library-Health-Scan fehlgeschlagen: {e!r}")
        raise HTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="LIBRARY_HEALTH_SCAN_FAILED",
                message="Der Library-Health-Scan ist fehlgeschlagen.",
                request_id=request_id,
            ).model_dump(),
        ) from e


def _report_path() -> Path:
    return Path(Config.DATA_DIR) / "library_health_report.json"


def load_cached_report(
    *, max_age_hours: float = 24.0, logger,
) -> tuple[Optional[dict], bool]:
    """Liest den persistenten Library-Health-Report, OHNE einen Scan
    auszuloesen (Auftrag §7a). Rueckgabe `(report, is_stale)`:

    - Datei fehlt oder ist nicht lesbar/parsebar -> `(None, False)`
      (Aufrufer meldet dafuer HTTPException(404, code=
      "LIBRARY_REPORT_MISSING") - hier bewusst KEINE Exception, damit
      der 404-Text/Code an EINER Stelle je Endpunkt bleibt, nicht hier
      dupliziert wird).
    - Datei vorhanden, `scan.completed_at` juenger als `max_age_hours`
      -> `(report, False)`.
    - Datei vorhanden, aber aelter (oder `completed_at` fehlt/unlesbar,
      defensiv als "nicht mehr sicher frisch" behandelt) -> `(report,
      True)` - der Report bleibt trotzdem nutzbar (Auftrag §7a: „Report
      lesen UND im UI sichtbar kennzeichnen, ohne automatisch neu zu
      scannen")."""
    path = _report_path()
    if not path.is_file():
        return None, False
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # noqa: BLE001
        logger.error(f"Persistenter Library-Report nicht lesbar ({path}): {e!r}")
        return None, False

    is_stale = True
    completed_at = (report.get("scan") or {}).get("completed_at")
    if completed_at:
        try:
            completed = datetime.fromisoformat(completed_at)
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            is_stale = (datetime.now(timezone.utc) - completed) > timedelta(hours=max_age_hours)
        except ValueError:
            is_stale = True
    return report, is_stale
