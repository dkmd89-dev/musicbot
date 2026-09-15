# control_center/routers/health.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health — Library-Health-Dashboard-Daten.

Reine Orchestrierung: ruft ausschliesslich control_center/_library_scan.py::
run_library_scan() auf (identischer Aufrufpfad wie
scripts/library_health_check.py) und mappt das Ergebnis auf das duenne
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

from fastapi import APIRouter, Depends

from handlers.menu.models import AccessLevel
from logger import get_module_logger

from .._library_scan import run_library_scan
from ..dependencies import require_min_access_level
from ..schemas.health import LibraryHealthResponse, report_to_health_response

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-health"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.health")


@router.get("/health", response_model=LibraryHealthResponse)
def get_library_health() -> LibraryHealthResponse:
    report = run_library_scan(logger=_logger)
    return report_to_health_response(report)
