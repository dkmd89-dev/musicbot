# control_center/routers/health.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health — Library-Health-Dashboard-Daten.

Reine Orchestrierung: ruft ausschliesslich
services/library_health/scanner.py::run_scan() auf (identischer Aufrufpfad
wie scripts/library_health_check.py) und mappt das Ergebnis auf das duenne
API-Schema (control_center/schemas/health.py::report_to_health_response()).
Keine eigene Scan-/Fachlogik hier (CLAUDE.md Abschnitt 4 — Web ist keine
neue Business-Logic-Schicht).

Read-only (GET ohne Seiteneffekte, Master-Prompt Regel 12) — identische
Read-only-Garantie wie der zugrunde liegende Scanner selbst (siehe
tests/test_library_health_readonly_safety.py).

Authentifiziert seit Schritt 3 (docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
Abschnitt 3): mindestens AccessLevel.USER, serverseitig geprueft ueber
control_center/dependencies.py::require_min_access_level() — derselbe
Auth-Kern wie der Bot, kein reiner UI-Check (Master-Prompt Regel 30).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_health.scanner import run_scan

from ..dependencies import require_min_access_level
from ..schemas.errors import ErrorDetail
from ..schemas.health import LibraryHealthResponse, report_to_health_response

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-health"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.health")


@router.get("/health", response_model=LibraryHealthResponse)
def get_library_health() -> LibraryHealthResponse:
    config = Config()
    library_root = Path(config.LIBRARY_DIR)

    if not library_root.is_dir():
        request_id = uuid.uuid4().hex
        _logger.error(
            f"[{request_id}] Library-Verzeichnis nicht gefunden: {library_root}"
        )
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="LIBRARY_ROOT_NOT_FOUND",
                message="Konfiguriertes Library-Verzeichnis existiert nicht.",
                request_id=request_id,
            ).model_dump(),
        )

    try:
        report = run_scan(
            library_root,
            supported_extensions=tuple(config.SUPPORTED_FORMATS),
            expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
            genre_mapping_dir=config.GENRE_MAPPING_DIR,
            logger=_logger,
        )
    except Exception as e:  # noqa: BLE001
        request_id = uuid.uuid4().hex
        _logger.error(f"[{request_id}] Library-Health-Scan fehlgeschlagen: {e!r}")
        raise HTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="LIBRARY_HEALTH_SCAN_FAILED",
                message="Der Library-Health-Scan ist fehlgeschlagen.",
                request_id=request_id,
            ).model_dump(),
        ) from e

    return report_to_health_response(report)
