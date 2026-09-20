# control_center/routers/repair.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/repair-plan — Reparatur-Vorschau (read-only).

Reine Orchestrierung: fuehrt einen frischen Library-Health-Scan aus
(control_center/_library_scan.py — identischer Aufrufpfad wie
routers/health.py) und uebergibt den Report unveraendert an
services/library_repair/planner.py::plan_repairs() (per eigenem
Modul-Docstring: "Reine Funktion... Kein Dateisystem-Zugriff, keine
Ausfuehrung, keine externen Aufrufe"). Mappt das Ergebnis auf das duenne
API-Schema (control_center/schemas/repair.py). Keine eigene Planungs-
/Reparaturlogik hier (CLAUDE.md Abschnitt 4).

Zeigt nur, WAS eine Reparatur tun WUERDE (Master-Prompt Abschnitt 7/21:
Preview vor Execution) — kein Executor wird aufgerufen, keine Datei wird
veraendert. Ausfuehrende Endpunkte (Repair-Execution) sind bewusst NICHT
Teil dieses Schritts (Scope: "Preview, read-only").

Authentifiziert mit mindestens AccessLevel.ADMIN — identische Schwelle
wie routers/findings.py (Repair-Planung ist mindestens so sensibel wie
reine Findings-Anzeige: enthaelt zusaetzlich requires_approval/
is_destructive-Flags, die klar in den Administrations-/Reparaturbereich
gehoeren).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_repair.planner import plan_repairs

from .._library_scan import run_library_scan
from ..dependencies import require_min_access_level
from ..schemas.repair import (
    ArtistRepairPlanResponse,
    RepairPlanResponse,
    plan_to_artist_response,
    plan_to_response,
)

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-repair"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.repair")


@router.get("/repair-plan", response_model=RepairPlanResponse)
def get_repair_plan() -> RepairPlanResponse:
    report = run_library_scan(logger=_logger)
    plan = plan_repairs(report)
    return plan_to_response(plan)


@router.get("/repair-plan/by-artist", response_model=ArtistRepairPlanResponse)
def get_repair_plan_by_artist() -> ArtistRepairPlanResponse:
    """Pendant zur Telegram-Pro-Artist-Auswahl (ARCH-033 §12) — L2/L3 sind
    bewusst NICHT als globaler Batch wie SAFE_AUTOMATIC ausführbar,
    sondern nur pro Artist (docs/adr/0003). Eigener, frischer Scan (wie
    GET /repair-plan) statt Wiederverwendung eines evtl. veralteten
    Client-Zustands."""
    report = run_library_scan(logger=_logger)
    plan = plan_repairs(report)
    return plan_to_artist_response(plan)
