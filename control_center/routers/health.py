# control_center/routers/health.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health — Library-Health-Dashboard-Daten (frischer Scan).
GET /api/v1/library/health/cached — dieselben Daten aus dem bereits
    vorhandenen persistenten Report, OHNE Scan (Overview-Dashboard,
    CONTROL_CENTER_OVERVIEW_V2.md Abschnitt 4/5).

Reine Orchestrierung: /health ruft ausschliesslich
control_center/_library_scan.py::run_library_scan() auf (identischer
Aufrufpfad wie scripts/library_health_check.py) und mappt das Ergebnis auf
das duenne API-Schema (control_center/schemas/health.py::
report_to_health_response()). /health/cached ruft stattdessen
load_cached_report() auf (identisches Read-only-Prinzip wie
control_center/routers/library_overview.py fuer /artists-overview). Keine
eigene Scan-/Fachlogik hier (CLAUDE.md Abschnitt 4 — Web ist keine neue
Business-Logic-Schicht).

/health bleibt bewusst unveraendert und weiterhin der einzige Aufrufer von
run_library_scan() aus diesem Router: control_center/templates/health.html
(dedizierte Health-Seite) haengt an diesem Endpoint und seinem
Live-Scan-Verhalten — das ist hier nicht Teil des Auftrags. Das
Overview-Dashboard (control_center/templates/overview.html) verwendet ab
CONTROL_CENTER_OVERVIEW_V2.md ausschliesslich /health/cached, um den
bislang bei jedem Overview-Aufruf ausgeloesten vollen Library-Scan
(~37s auf Produktion) zu vermeiden — identisches Muster wie bereits bei
GET /api/v1/library/artists-overview (CC-AC-1) fuer GET /api/v1/library/
artists entschieden: bestehenden, von anderer Stelle bewusst
Klick-gesteuert genutzten Endpoint unveraendert lassen, stattdessen
additiv ergaenzen (Auftrag §43 Hard-Stop-Geist, CLAUDE.md Abschnitt 20
„Legacy-/Kompatibilitätsschichten nicht ohne Beweis entfernen").

Read-only (GET ohne Seiteneffekte, Master-Prompt Regel 12) — identische
Read-only-Garantie wie der zugrunde liegende Scanner selbst (siehe
tests/test_library_health_readonly_safety.py).

Authentifiziert seit Schritt 3 (docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
Abschnitt 3): mindestens AccessLevel.USER, serverseitig geprueft ueber
control_center/dependencies.py::require_min_access_level() — derselbe
Auth-Kern wie der Bot, kein reiner UI-Check (Master-Prompt Regel 30).
Identische Schwelle fuer /health/cached, da Overview bereits heute bei
USER-Level auf /health zugreift.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from handlers.menu.models import AccessLevel
from logger import get_module_logger

from .._library_scan import load_cached_report, run_library_scan
from ..dependencies import require_min_access_level
from ..schemas.errors import ErrorDetail
from ..schemas.health import (
    CachedLibraryHealthResponse,
    LibraryHealthResponse,
    report_to_cached_health_response,
    report_to_health_response,
)

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


@router.get("/health/cached", response_model=CachedLibraryHealthResponse)
def get_cached_library_health() -> CachedLibraryHealthResponse:
    """Liest den persistenten Library-Health-Report (kein Scan) — Konsument:
    Overview-Dashboard. Identisches 404-Muster wie routers/library_overview.py::
    _require_cached_report()."""
    report, stale = load_cached_report(logger=_logger)
    if report is None:
        request_id = uuid.uuid4().hex
        _logger.warning(f"[{request_id}] Kein persistenter Library-Report vorhanden")
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="LIBRARY_REPORT_MISSING",
                message=(
                    "Noch kein Library-Report vorhanden. Bitte zuerst einen "
                    "Health-Scan ausführen (Telegram: „🩺 MusicBot Doctor“, "
                    "oder CLI: scripts/library_health_check.py)."
                ),
                request_id=request_id,
            ).model_dump(),
        )
    return report_to_cached_health_response(report, stale=stale)
