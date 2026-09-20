# control_center/schemas/maintenance.py
# -*- coding: utf-8 -*-
"""
Response-Schema für alle Library-Maintenance-Actions (Preview/Execute) —
gemeinsam genutzt von control_center/routers/metadata_actions.py
("Genre setzen") und control_center/routers/admin_maintenance.py
("Artist-Casing", "Legacy-Genre-Cleanup", "Artist umbenennen",
"Titel bearbeiten").

Ursprünglich als `GenrePreviewResponse`/`GenreExecuteResponse` nur für
"Genre setzen" in schemas/metadata.py entstanden — bereits damals rein
generisches Mapping über services/library_repair/maintenance_service.py::
MaintenancePreview/MaintenanceRunResult (referenziert nirgends
"genre"-spezifische Felder). Für die Administration-Maintenance-Actions
hierher verschoben und umbenannt statt dupliziert (kein neuer
Schema-Zwilling für dieselbe Datenform).

Dünnes Mapping — kein 1:1-Durchreichen interner Dataclasses (`issue_code`/
`action`/`backup_path` aus services/library_repair/executor.py::ExecOutcome
sind interne Executor-Details, nicht Teil des API-Contracts).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class MaintenanceOutcomeSchema(BaseModel):
    file: str
    status: str
    before: dict
    after: dict
    reason: Optional[str]


def _outcome_to_schema(o) -> MaintenanceOutcomeSchema:
    return MaintenanceOutcomeSchema(
        file=o.file, status=o.status, before=o.before, after=o.after, reason=o.reason,
    )


class MaintenancePreviewResponse(BaseModel):
    artist: str
    target_count: int
    changed_count: int
    outcomes: list[MaintenanceOutcomeSchema]


def maintenance_preview_to_response(preview) -> MaintenancePreviewResponse:
    """Reines Mapping über services/library_repair/maintenance_service.py::
    MaintenancePreview hinweg."""
    return MaintenancePreviewResponse(
        artist=preview.artist,
        target_count=preview.target_count,
        changed_count=preview.changed_count,
        outcomes=[_outcome_to_schema(o) for o in preview.outcomes],
    )


class MaintenanceExecuteResponse(BaseModel):
    run_id: str
    artist: str
    status: str
    target_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    affected_files: list[str]
    error_message: Optional[str]


def maintenance_execute_to_response(result) -> MaintenanceExecuteResponse:
    """Reines Mapping über MaintenanceRunResult hinweg."""
    return MaintenanceExecuteResponse(
        run_id=result.run_id,
        artist=result.artist,
        status=result.status,
        target_count=result.target_count,
        success_count=result.success_count,
        failed_count=result.failed_count,
        skipped_count=result.skipped_count,
        affected_files=result.affected_files,
        error_message=result.error_message,
    )
