# control_center/routers/mapping_yaml.py
# -*- coding: utf-8 -*-
"""
YAML-Editor der Mapping-Administration (Rohtext, fuer Fortgeschrittene).

Endpunkte (ADMIN, POST/PUT mit Same-Origin-Schutz):
  GET  /api/v1/admin/mappings/{mapping_id}/yaml            Rohtext + Datei-Etag
  POST /api/v1/admin/mappings/{mapping_id}/yaml/preview    Pruefung + Diff (schreibt nie)
  PUT  /api/v1/admin/mappings/{mapping_id}/yaml            Schreiben mit etag (Backup vorher)

Der Client uebergibt nur `mapping_id` (Allowlist) und den Text; Dateipfade
entstehen serverseitig. Sicherheit und Validierung: services/mapping_yaml.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from logger import get_module_logger
from services.access_control import AccessLevel
from services.mapping_admin import MappingDomainError
from services.mapping_yaml import MAX_RAW_BYTES, apply_raw_update, plan_raw_update, read_raw

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.mapping_yaml import (
    RawBody,
    RawFileResponse,
    RawPreviewResponse,
    RawSaveBody,
    RawSaveResponse,
    file_to_response,
    plan_to_preview,
    result_to_response,
)
from .mapping_admin import _backup_dir, _mapping_dir, _mapping_http_error

_logger = get_module_logger("control_center.mapping_yaml")

router = APIRouter(
    prefix="/api/v1/admin/mappings",
    tags=["mapping-yaml"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


# JSON-Escapes koennen den Text aufblaehen; mehr als das Doppelte des Textlimits ist nie legitim.
_MAX_BODY_BYTES = 2 * MAX_RAW_BYTES + 4096


def _limit_body(request: Request) -> None:
    """Weist zu grosse Bodies anhand von Content-Length ab, bevor FastAPI sie liest und parst."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=ErrorDetail(code="MAPPING_YAML_TOO_LARGE", message="Der YAML-Text ist zu groß.").model_dump(),
        )


@router.get("/{mapping_id}/yaml", response_model=RawFileResponse)
def get_yaml(mapping_id: str):
    try:
        return file_to_response(read_raw(mapping_id, _mapping_dir()))
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e


@router.post("/{mapping_id}/yaml/preview", response_model=RawPreviewResponse, dependencies=[Depends(_limit_body), Depends(verify_same_origin)])
def post_yaml_preview(mapping_id: str, body: RawBody):
    try:
        return plan_to_preview(plan_raw_update(mapping_id, body.text, _mapping_dir()))
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e


@router.put("/{mapping_id}/yaml", response_model=RawSaveResponse, dependencies=[Depends(_limit_body), Depends(verify_same_origin)])
def put_yaml(mapping_id: str, body: RawSaveBody, user_id: int = Depends(get_current_user_id)):
    try:
        plan, result = apply_raw_update(
            mapping_id, body.text, _mapping_dir(), expected_etag=body.etag, backup_dir=_backup_dir(),
        )
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    # Nie den Text loggen (kann Fachdaten enthalten): nur Aktion, Nutzer und Ergebnis.
    _logger.info(
        f"[control_center] {mapping_id} yaml {plan.change} von User {user_id} (geschrieben={result.written})"
    )
    return result_to_response(plan, result)
