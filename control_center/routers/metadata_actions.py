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

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.library_repair.genre import (
    GenreDomainError,
    GenreMappingConflictError,
    GenreMappingUnavailableError,
    apply_manual_genre_mapping,
    get_genre_mapping,
    known_genres,
    plan_manual_genre_mapping,
)
from services.library_repair.maintenance_service import (
    MaintenanceServiceError,
    execute_set_genre,
    preview_set_genre,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.genre_mapping import (
    GenreMappingBody,
    GenreMappingPreviewResponse,
    GenreMappingResponse,
    GenreMappingSaveBody,
    GenreMappingSaveResponse,
    entry_to_schema,
    plan_to_preview,
    save_to_response,
)
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


# ── Genre-Mapping bearbeiten (Primary + Secondary) ─────────────────────────
#
# Duenne Wrapper um services/library_repair/genre.py (get_genre_mapping /
# plan_manual_genre_mapping / apply_manual_genre_mapping). Das Mapping
# (mapping/artist_genre.yaml) ist Fachlogik (CLAUDE.md §10): erst Vorschau,
# dann Schreiben mit Etag (Konflikt -> 409). Die Tags der Dateien werden NICHT
# hier geaendert, sondern weiter ueber genre-preview/set-genre (aus dem
# Mapping). Der laufende Bot laedt das Mapping beim Start (GenreMapper) —
# `bot_reload_required` sagt das ehrlich.


def _mapping_dir() -> Path:
    return Path(Config.GENRE_MAPPING_DIR)


def _genre_mapping_http_error(e: GenreDomainError) -> HTTPException:
    if isinstance(e, GenreMappingUnavailableError):
        status, code = 503, "GENRE_MAPPING_UNAVAILABLE"
    elif isinstance(e, GenreMappingConflictError):
        status, code = 409, "GENRE_MAPPING_CHANGED"
    else:
        status, code = 422, "GENRE_INPUT_INVALID"
    return HTTPException(
        status_code=status, detail=ErrorDetail(code=code, message=str(e)).model_dump(),
    )


@router.get("/artists/{artist}/genre-mapping", response_model=GenreMappingResponse)
def get_artist_genre_mapping(artist: str) -> GenreMappingResponse:
    try:
        entry, etag = get_genre_mapping(artist, _mapping_dir())
    except GenreDomainError as e:
        raise _genre_mapping_http_error(e) from e
    return GenreMappingResponse(
        artist=artist, exists=entry is not None, entry=entry_to_schema(entry), etag=etag,
        known_genres=known_genres(_mapping_dir() / "artist_genre.yaml"),
    )


@router.post(
    "/artists/{artist}/genre-mapping/preview",
    response_model=GenreMappingPreviewResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_genre_mapping_preview(artist: str, body: GenreMappingBody) -> GenreMappingPreviewResponse:
    """Reine Vorschau (schreibt nichts): was aendert sich im Mapping?"""
    try:
        plan = plan_manual_genre_mapping(artist, body.primary, body.secondary, _mapping_dir())
    except GenreDomainError as e:
        raise _genre_mapping_http_error(e) from e
    return plan_to_preview(artist, plan)


@router.put(
    "/artists/{artist}/genre-mapping",
    response_model=GenreMappingSaveResponse,
    dependencies=[Depends(verify_same_origin)],
)
def put_artist_genre_mapping(
    artist: str, body: GenreMappingSaveBody, user_id: int = Depends(get_current_user_id),
) -> GenreMappingSaveResponse:
    try:
        plan, result = apply_manual_genre_mapping(
            artist, body.primary, body.secondary, _mapping_dir(),
            expected_etag=body.etag,
            default_description="Manuell gesetzt via Control Center",
        )
        _, new_etag = get_genre_mapping(artist, _mapping_dir())
    except GenreDomainError as e:
        raise _genre_mapping_http_error(e) from e
    _logger.info(
        f"🎭 [control_center] Genre-Mapping {plan.change} für Artist-Key {plan.artist_key!r} "
        f"von User {user_id} (geschrieben={result.written})"
    )
    return save_to_response(artist, plan, result, new_etag)
