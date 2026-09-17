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
(get_review_summary()) ueber die GESAMTE Registry-Historie.

POST .../accept + POST .../unaccept (Nachtrag, erster schreibender
Control-Center-Endpunkt ueberhaupt): duenne Wrapper um die bestehenden
services/library_health/findings.py::accept_finding()/unaccept_finding()
— identische Kernfunktionen wie scripts/library_health_review.py, keine
neue Reparatur-/Review-Logik. `reviewed_by` wird auf die authentifizierte
Telegram-ID gesetzt (Audit-Spur, Master-Prompt Regel 31 "Who/What/When/
Result" — bereits vorhandenes Finding.history-Feld, kein neues
Audit-System noetig). Zusaetzlich per verify_same_origin()-Dependency
gegen CSRF abgesichert (siehe dortiger Docstring). Nur diese beiden
Routen sind schreibend — GET .../findings und .../summary bleiben
unveraendert seiteneffektfrei.

KEINE Reparatur-Ausfuehrung, KEIN Loeschen — accept/unaccept aendern
ausschliesslich den Review-Status in der Findings-Registry (Metadaten
ausserhalb der Library), niemals eine Library-Datei. Vollstaendig
reversibel (unaccept_finding() existiert exakt fuer diesen Zweck).

Authentifiziert seit Schritt 3 mit mindestens AccessLevel.ADMIN — spiegelt
die bestehende Telegram-Schwelle 1:1 (Findings-Review ist dort bereits
review:-Bereich == ADMIN, siehe docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
Abschnitt 3), keine Aufweichung fuer die Web-Variante.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_health.findings import (
    DEFAULT_FILENAME as FINDINGS_DEFAULT_FILENAME,
    FindingsRegistry,
    FindingsRegistryError,
    accept_finding,
    get_review_summary,
    group_open_findings_by_category,
    unaccept_finding,
)

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.findings import (
    AcceptFindingRequest,
    FindingActionResponse,
    FindingCategoryGroup,
    FindingsSummaryResponse,
    UnacceptFindingRequest,
    category_groups_to_schema,
    finding_to_action_response,
    review_summary_to_schema,
)

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-findings"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
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


@router.post(
    "/findings/{finding_id}/accept",
    response_model=FindingActionResponse,
    dependencies=[Depends(verify_same_origin)],
)
def accept_finding_endpoint(
    finding_id: str,
    payload: AcceptFindingRequest,
    user_id: int = Depends(get_current_user_id),
) -> FindingActionResponse:
    registry = _load_registry()
    try:
        finding = accept_finding(
            registry, finding_id, reason=payload.reason, reviewed_by=str(user_id)
        )
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="FINDING_NOT_FOUND", message=str(e)).model_dump(),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="REASON_REQUIRED", message=str(e)).model_dump(),
        ) from e
    registry.save()
    return finding_to_action_response(finding)


@router.post(
    "/findings/{finding_id}/unaccept",
    response_model=FindingActionResponse,
    dependencies=[Depends(verify_same_origin)],
)
def unaccept_finding_endpoint(
    finding_id: str,
    payload: UnacceptFindingRequest,
    user_id: int = Depends(get_current_user_id),
) -> FindingActionResponse:
    registry = _load_registry()
    try:
        finding = unaccept_finding(
            registry, finding_id, reviewed_by=str(user_id), note=payload.note
        )
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="FINDING_NOT_FOUND", message=str(e)).model_dump(),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(code="ALREADY_OPEN", message=str(e)).model_dump(),
        ) from e
    registry.save()
    return finding_to_action_response(finding)
