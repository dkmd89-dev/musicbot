# control_center/routers/mapping_backups.py
# -*- coding: utf-8 -*-
"""
Versionen der Mapping-Dateien (Backup/Restore).

Endpunkte (ADMIN, POST mit Same-Origin-Schutz):
  GET  /api/v1/admin/mappings/{mapping_id}/backups                          Liste
  POST /api/v1/admin/mappings/{mapping_id}/backups/{version_id}/preview     Diff Version <-> aktuell
  POST /api/v1/admin/mappings/{mapping_id}/backups/{version_id}/restore     Restore mit etag

Der Client uebergibt nur `mapping_id` (Allowlist) und eine `version_id` aus der
Liste; Dateipfade entstehen ausschliesslich serverseitig.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from config import Config
from logger import get_module_logger
from services.access_control import AccessLevel
from services.mapping_admin import MappingDomainError
from services.mapping_backups import default_backup_dir
from services.mapping_restore import apply_restore, list_backup_versions, plan_restore

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.mapping_backups import (
    BackupListResponse,
    RestoreBody,
    RestorePreviewResponse,
    RestoreResponse,
    list_to_response,
    plan_to_preview,
    result_to_response,
)
from .mapping_admin import _mapping_dir, _mapping_http_error

_logger = get_module_logger("control_center.mapping_backups")

router = APIRouter(
    prefix="/api/v1/admin/mappings",
    tags=["mapping-backups"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


def _backup_dir() -> Path:
    return default_backup_dir(Config)


@router.get("/{mapping_id}/backups", response_model=BackupListResponse)
def get_backups(mapping_id: str):
    try:
        versions = list_backup_versions(mapping_id, _backup_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    return list_to_response(mapping_id, versions)


@router.post(
    "/{mapping_id}/backups/{version_id}/preview",
    response_model=RestorePreviewResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_restore_preview(mapping_id: str, version_id: str):
    try:
        plan = plan_restore(mapping_id, version_id, _mapping_dir(), _backup_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    return plan_to_preview(plan)


@router.post(
    "/{mapping_id}/backups/{version_id}/restore",
    response_model=RestoreResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_restore(
    mapping_id: str, version_id: str, body: RestoreBody,
    user_id: int = Depends(get_current_user_id),
):
    try:
        plan, result = apply_restore(
            mapping_id, version_id, _mapping_dir(), _backup_dir(), expected_etag=body.etag,
        )
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    _logger.info(
        f"[control_center] {mapping_id} restore {version_id} von User {user_id} "
        f"(geschrieben={result.written})"
    )
    return result_to_response(plan, result)
