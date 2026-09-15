# control_center/routers/findings.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/findings (+ /summary) — Library-Findings-Anzeige.

Reine Orchestrierung: liest ausschliesslich die bestehende, persistente
Findings-Registry (services/library_health/findings.py::FindingsRegistry)
— identische Datenquelle wie scripts/library_health_review.py. Kein neuer
Scan, kein Schreibzugriff (Master-Prompt Regel 12: GET ohne Seiteneffekte)
— die Registry wird nur GELESEN, niemals gemerged/gespeichert. Aktuelle
Findings entstehen weiterhin ausschliesslich ueber
scripts/library_health_check.py (Scan + Merge), nicht ueber diese Route.

Zeigt nur aktuell OFFENE Findings (group_open_findings_by_category()
liefert per Definition nur STATUS_OPEN) plus eine Tri-State-Zusammenfassung
(get_review_summary()) ueber die GESAMTE Registry-Historie. Keine
Accept-/Unaccept-/Review-Endpoints in diesem Schritt (Scope laut
Freigabe: "nur Findings anzeigen, read-only").

Noch OHNE Authentifizierung — siehe control_center/routers/health.py fuer
denselben Hinweis/Grund.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import Config
from logger import get_module_logger
from services.library_health.findings import (
    DEFAULT_FILENAME as FINDINGS_DEFAULT_FILENAME,
    FindingsRegistry,
    FindingsRegistryError,
    get_review_summary,
    group_open_findings_by_category,
)

from ..schemas.errors import ErrorDetail
from ..schemas.findings import (
    FindingCategoryGroup,
    FindingsSummaryResponse,
    category_groups_to_schema,
    review_summary_to_schema,
)

router = APIRouter(prefix="/api/v1/library", tags=["library-findings"])
_logger = get_module_logger("control_center.findings")


def _findings_registry_path(config: Config) -> Path:
    """Identische Default-Pfad-Formel wie scripts/library_health_check.py
    (dort per --findings-registry ueberschreibbar, hier bewusst fest —
    kein Query-Parameter fuer einen beliebigen Dateipfad, siehe Security-
    Checkliste in docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
    Abschnitt 6 "Path Traversal")."""
    return Path(config.DATA_DIR) / FINDINGS_DEFAULT_FILENAME


def _load_registry() -> FindingsRegistry:
    config = Config()
    path = _findings_registry_path(config)
    try:
        return FindingsRegistry(path, logger=_logger)
    except FindingsRegistryError as e:
        request_id = uuid.uuid4().hex
        _logger.error(f"[{request_id}] Findings-Registry ungueltig: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="FINDINGS_REGISTRY_INVALID",
                message="Die Findings-Registry ist nicht lesbar.",
                request_id=request_id,
            ).model_dump(),
        ) from e


@router.get("/findings", response_model=list[FindingCategoryGroup])
def get_open_findings() -> list[FindingCategoryGroup]:
    registry = _load_registry()
    groups = group_open_findings_by_category(registry)
    return category_groups_to_schema(groups)


@router.get("/findings/summary", response_model=FindingsSummaryResponse)
def get_findings_summary() -> FindingsSummaryResponse:
    registry = _load_registry()
    summary = get_review_summary(registry)
    return review_summary_to_schema(summary)
