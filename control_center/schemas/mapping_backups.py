# control_center/schemas/mapping_backups.py
# -*- coding: utf-8 -*-
"""Duenne Response-Modelle fuer die Mapping-Versionen (Backup/Restore)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from services.mapping_backups import MAX_BACKUPS_PER_MAPPING, BackupVersion
from services.mapping_restore import RestorePlan, RestoreResult


class BackupVersionSchema(BaseModel):
    version_id: str
    created_at: str
    size: int
    sha256: str


class BackupListResponse(BaseModel):
    mapping_id: str
    versions: List[BackupVersionSchema]
    count: int
    max_versions: int


class RestoreBody(BaseModel):
    etag: str


class RestorePreviewResponse(BaseModel):
    mapping_id: str
    version_id: str
    created_at: str
    change: str
    added: List[str]
    removed: List[str]
    changed: List[str]
    etag: str
    warnings: List[str] = Field(default_factory=list)


class RestoreResponse(RestorePreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool
    message: str


RESTORE_COMMENT_NOTE = (
    "Die Version wird unveraendert (inklusive Kommentaren) zurueckgeschrieben; "
    "der aktuelle Stand wird vorher selbst als Version gesichert."
)
RESTORE_MESSAGE_WRITTEN = (
    "Version wiederhergestellt. Der laufende Bot laedt die Mapping-Dateien beim "
    "Start: die Aenderung wirkt fuer neue Downloads erst nach Bot-Neustart."
)
RESTORE_MESSAGE_UNCHANGED = "Die Version entspricht dem aktuellen Stand — nichts geschrieben."


def version_to_schema(version: BackupVersion) -> BackupVersionSchema:
    return BackupVersionSchema(
        version_id=version.version_id, created_at=version.created_at.isoformat(),
        size=version.size, sha256=version.sha256,
    )


def list_to_response(mapping_id: str, versions: List[BackupVersion]) -> BackupListResponse:
    return BackupListResponse(
        mapping_id=mapping_id, versions=[version_to_schema(v) for v in versions],
        count=len(versions), max_versions=MAX_BACKUPS_PER_MAPPING,
    )


def plan_to_preview(plan: RestorePlan) -> RestorePreviewResponse:
    return RestorePreviewResponse(
        mapping_id=plan.mapping_id, version_id=plan.version_id, created_at=plan.created_at,
        change=plan.change, added=list(plan.added), removed=list(plan.removed),
        changed=list(plan.changed), etag=plan.etag,
        warnings=[RESTORE_COMMENT_NOTE] if plan.change != "unchanged" else [],
    )


def result_to_response(plan: RestorePlan, result: RestoreResult) -> RestoreResponse:
    base = plan_to_preview(plan)
    return RestoreResponse(
        **base.model_dump(),
        written=result.written, unchanged=result.unchanged, new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=RESTORE_MESSAGE_WRITTEN if result.written else RESTORE_MESSAGE_UNCHANGED,
    )
