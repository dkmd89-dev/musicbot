# control_center/routers/metadata_actions.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/artists/{artist}/genre-preview,
POST /api/v1/library/artists/{artist}/set-genre — erste schreibende
Fähigkeit in Metadata Management (Master-Prompt Abschnitt 7, "Metadata
bearbeiten").

Spiegelt die bestehende, bereits produktive Telegram-/CLI-Fähigkeit
"✏️ Genre setzen" (ARCH-032, docs/LIBRARY_REPAIR.md §11.3/§14.1) — ruft
ausschließlich services/library_repair/maintenance_service.py::
preview_set_genre()/execute_set_genre() auf, die wiederum
executor.py::apply_set_genre() nutzen (Backup + SHA-256- +
Audio-Essenz-Verifikation + Rollback + Journal, bereits produktiv).
Keine neue Ausführungslogik.

Preview und Execute rufen denselben Executor-Pfad auf (dry_run=True/
False) — garantiert identische Domain-Entscheidung, kein eigenes "Was
würde passieren"-Nachbauen (maintenance_service.py-Docstring). Das ist
der Preview→Diff→Confirmation→Execution→Verification-Zyklus aus
Master-Prompt Abschnitt 7: Preview liefert bereits das vollständige
Vorher/Nachher (`before`/`after` je Datei) für eine Diff-Ansicht,
Confirmation ist bewusst Frontend-Verantwortung (wie bei allen
bisherigen destruktiven Control-Center-Fähigkeiten), Verification läuft
bereits innerhalb von apply_set_genre() selbst (Tag-Rücklesen + Audio-
Essenz-Vergleich vor dem endgültigen Replace).

Bewusst NUR `from_mapping=True` (kein Freitext-Genre-Eingabefeld) —
identische Einschränkung wie die bestehende Telegram-Fähigkeit ("set-
genre über Telegram bewusst nur im --from-mapping-Modus", §14.1) — keine
neue, in Telegram nirgends existierende Fähigkeit (identisches Prinzip
wie die Cover-Scope-Entscheidung bei ARCH-033/L2-L3).

`RepairAlreadyRunningError` (gemeinsamer Lock mit Telegram/CLI/Repair)
wird kontrolliert als 409 gemeldet. `MaintenanceServiceError` (Artist
nicht in artist_genre.yaml) wird als 404 gemeldet.

Bewusst synchron (kein Job/Polling wie bei repair-safe-automatic/L2-L3)
— apply_set_genre() schreibt direkt in-process per Mutagen, kein
Subprozess, kein Netzwerk; für die Dateien eines einzelnen Artists
ausreichend schnell für eine normale Request/Response-Antwort.

Authentifiziert mit mindestens AccessLevel.ADMIN. POST ist über
verify_same_origin() CSRF-geschützt, identisches Muster wie Findings
Accept/Unaccept.

Response-Schema (Nachtrag): nach schemas/maintenance.py verschoben
(MaintenancePreviewResponse/MaintenanceExecuteResponse, vormals
GenrePreviewResponse/GenreExecuteResponse) — die Datenform war bereits
generisch, wird jetzt zusätzlich von
control_center/routers/admin_maintenance.py wiederverwendet (Artist-
Casing/Legacy-Genre-Cleanup/Artist-Rename/Titel bearbeiten).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_repair.maintenance_service import (
    MaintenanceServiceError,
    execute_set_genre,
    preview_set_genre,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.maintenance import (
    MaintenanceExecuteResponse,
    MaintenancePreviewResponse,
    maintenance_execute_to_response,
    maintenance_preview_to_response,
)

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-metadata-actions"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.metadata_actions")


@router.get("/artists/{artist}/genre-preview", response_model=MaintenancePreviewResponse)
def get_genre_preview(artist: str) -> MaintenancePreviewResponse:
    try:
        preview = preview_set_genre(artist, from_mapping=True)
    except MaintenanceServiceError as e:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="ARTIST_NOT_IN_MAPPING", message=str(e)).model_dump(),
        ) from e
    return maintenance_preview_to_response(preview)


@router.post(
    "/artists/{artist}/set-genre",
    response_model=MaintenanceExecuteResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_set_genre(
    artist: str, user_id: int = Depends(get_current_user_id)
) -> MaintenanceExecuteResponse:
    try:
        result = execute_set_genre(
            artist, triggered_by=f"control_center:{user_id}", from_mapping=True,
        )
    except MaintenanceServiceError as e:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="ARTIST_NOT_IN_MAPPING", message=str(e)).model_dump(),
        ) from e
    except RepairAlreadyRunningError as e:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(code="REPAIR_ALREADY_RUNNING", message=str(e)).model_dump(),
        ) from e
    return maintenance_execute_to_response(result)
