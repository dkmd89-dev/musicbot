# control_center/routers/admin_maintenance.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance-Actions im Web — Master-Prompt Abschnitt 22
"ADMINISTRATION" (Maintenance), ui_prompt.txt Abschnitt 22 identisch.

Spiegelt die bestehenden, bereits produktiven Telegram-Maintenance-
Flows (ARCH-032 "🧹 Library-Wartung" + der neuere "📝 Metadaten
bearbeiten"-Zweig, `handlers/library_maintenance_handler.py`) — ruft
ausschließlich services/library_repair/maintenance_service.py::
preview_*()/execute_*() auf. **Keine neue Ausführungslogik**, identisches
Prinzip wie control_center/routers/metadata_actions.py ("Genre setzen",
bereits produktiv, nutzt dieselben Preview/Execute-Response-Schemas aus
schemas/maintenance.py).

Vier Aktionen, jede als eigenes Preview/Execute-Endpunktpaar (bewusst
KEIN einzelner generischer "/maintenance/{action}"-Dispatcher — die
Aktionen unterscheiden sich in ihren Parametern, ein generischer
Endpunkt würde das nur verschleiern):

- **`artist-casing`** — Groß-/Kleinschreibung eines Artists aus
  `mapping/artist_overrides.json` korrigieren. Nur `artist`.
- **`legacy-genre-cleanup`** — entfernt veraltete Freeform-Genre-Atome.
  Nur `artist`.
- **`artist-rename`** — manueller Artist-Zielwert (KEIN Casing-Mapping/
  keine Normalisierung — explizite Nutzerentscheidung, identisch zur
  Telegram-Fähigkeit "📝 Metadaten bearbeiten → Artist"). `artist` +
  `new_artist`.
- **`title-edit`** — manueller Titel-Zielwert für GENAU EINEN Track
  (KEIN automatischer TitleCleaner). `artist` + `rel_path` (aus dem
  bereits vorhandenen Track-Browser, GET /api/v1/library/tracks, zu
  kopieren — kein eigener Track-Picker in diesem Schritt) + `new_title`.

Preview und Execute rufen denselben Executor-Pfad auf (dry_run=True/
False) — identisches Preview→Diff→Confirmation→Execution→Verification-
Prinzip wie "Genre setzen" (maintenance_service.py-Docstring).

`MaintenanceServiceError` bedeutet hier (anders als bei "Genre setzen")
i. d. R. eine ungültige manuelle Eingabe (leer/zu lang/Zeilenumbruch,
`_validate_manual_value()`) — als 422 gemeldet, nicht 404.
`RepairAlreadyRunningError` (gemeinsamer Lock mit Telegram/CLI/Repair/
L2-L3/Genre setzen) wird als 409 gemeldet.

Bewusst synchron (kein Job/Polling) — identische Begründung wie
metadata_actions.py: reine In-Process-Mutagen-Schreibvorgänge für die
Dateien eines Artists bzw. eine einzelne Datei, kein Subprozess, kein
Netzwerk.

Authentifiziert mit mindestens AccessLevel.ADMIN. POST-Endpunkte sind
über verify_same_origin() CSRF-geschützt.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_repair.maintenance_service import (
    MaintenanceServiceError,
    execute_artist_casing_fix,
    execute_artist_rename,
    execute_legacy_genre_cleanup,
    execute_title_edit,
    preview_artist_casing,
    preview_artist_rename,
    preview_legacy_genre_cleanup,
    preview_title_edit,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.admin_maintenance import (
    ArtistRenameRequest,
    TitleEditRequest,
)
from ..schemas.errors import ErrorDetail
from ..schemas.maintenance import (
    MaintenanceExecuteResponse,
    MaintenancePreviewResponse,
    maintenance_execute_to_response,
    maintenance_preview_to_response,
)

router = APIRouter(
    prefix="/api/v1/admin/maintenance",
    tags=["admin-maintenance"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.admin_maintenance")


def _validation_error(e: MaintenanceServiceError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=ErrorDetail(code="MAINTENANCE_VALIDATION_ERROR", message=str(e)).model_dump(),
    )


def _lock_conflict_error(e: RepairAlreadyRunningError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=ErrorDetail(code="REPAIR_ALREADY_RUNNING", message=str(e)).model_dump(),
    )


# ── Artist-Casing ───────────────────────────────────────────────────────


@router.get("/artist-casing/preview", response_model=MaintenancePreviewResponse)
def get_artist_casing_preview(artist: str = Query(...)) -> MaintenancePreviewResponse:
    return maintenance_preview_to_response(preview_artist_casing(artist))


@router.post(
    "/artist-casing/execute",
    response_model=MaintenanceExecuteResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_artist_casing_execute(
    artist: str = Query(...), user_id: int = Depends(get_current_user_id),
) -> MaintenanceExecuteResponse:
    try:
        result = execute_artist_casing_fix(artist, triggered_by=f"control_center:{user_id}")
    except RepairAlreadyRunningError as e:
        raise _lock_conflict_error(e) from e
    return maintenance_execute_to_response(result)


# ── Legacy-Genre-Cleanup ────────────────────────────────────────────────


@router.get("/legacy-genre-cleanup/preview", response_model=MaintenancePreviewResponse)
def get_legacy_genre_cleanup_preview(artist: str = Query(...)) -> MaintenancePreviewResponse:
    return maintenance_preview_to_response(preview_legacy_genre_cleanup(artist))


@router.post(
    "/legacy-genre-cleanup/execute",
    response_model=MaintenanceExecuteResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_legacy_genre_cleanup_execute(
    artist: str = Query(...), user_id: int = Depends(get_current_user_id),
) -> MaintenanceExecuteResponse:
    try:
        result = execute_legacy_genre_cleanup(artist, triggered_by=f"control_center:{user_id}")
    except RepairAlreadyRunningError as e:
        raise _lock_conflict_error(e) from e
    return maintenance_execute_to_response(result)


# ── Artist umbenennen (manueller Zielwert) ──────────────────────────────


@router.get("/artist-rename/preview", response_model=MaintenancePreviewResponse)
def get_artist_rename_preview(
    artist: str = Query(...), new_artist: str = Query(...),
) -> MaintenancePreviewResponse:
    try:
        preview = preview_artist_rename(artist, new_artist)
    except MaintenanceServiceError as e:
        raise _validation_error(e) from e
    return maintenance_preview_to_response(preview)


@router.post(
    "/artist-rename/execute",
    response_model=MaintenanceExecuteResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_artist_rename_execute(
    payload: ArtistRenameRequest, user_id: int = Depends(get_current_user_id),
) -> MaintenanceExecuteResponse:
    try:
        result = execute_artist_rename(
            payload.artist, payload.new_artist, triggered_by=f"control_center:{user_id}",
        )
    except MaintenanceServiceError as e:
        raise _validation_error(e) from e
    except RepairAlreadyRunningError as e:
        raise _lock_conflict_error(e) from e
    return maintenance_execute_to_response(result)


# ── Titel bearbeiten (manueller Zielwert, genau ein Track) ──────────────


@router.get("/title-edit/preview", response_model=MaintenancePreviewResponse)
def get_title_edit_preview(
    artist: str = Query(...), rel_path: str = Query(...), new_title: str = Query(...),
) -> MaintenancePreviewResponse:
    try:
        preview = preview_title_edit(artist, rel_path, new_title)
    except MaintenanceServiceError as e:
        raise _validation_error(e) from e
    return maintenance_preview_to_response(preview)


@router.post(
    "/title-edit/execute",
    response_model=MaintenanceExecuteResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_title_edit_execute(
    payload: TitleEditRequest, user_id: int = Depends(get_current_user_id),
) -> MaintenanceExecuteResponse:
    try:
        result = execute_title_edit(
            payload.artist, payload.rel_path, payload.new_title,
            triggered_by=f"control_center:{user_id}",
        )
    except MaintenanceServiceError as e:
        raise _validation_error(e) from e
    except RepairAlreadyRunningError as e:
        raise _lock_conflict_error(e) from e
    return maintenance_execute_to_response(result)
