# control_center/_library_scan.py
# -*- coding: utf-8 -*-
"""
Gemeinsamer Scan-Aufruf fuer Endpunkte, die einen frischen Library-
Health-Report brauchen (routers/health.py, routers/repair.py) —
identischer run_scan()-Aufrufpfad wie scripts/library_health_check.py,
identische 404/500-Fehlerbehandlung an einer Stelle statt dupliziert
(Master-Prompt Regel 7).
"""

from __future__ import annotations

import uuid
from pathlib import Path

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
