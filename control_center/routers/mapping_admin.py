# control_center/routers/mapping_admin.py
# -*- coding: utf-8 -*-
"""
Mapping-Administration im Control Center (M1, 2026-09-29).

Endpunkte:
  GET  /api/v1/admin/mappings/{mapping_id}                 Liste
  GET  /api/v1/admin/mappings/{mapping_id}/entry           Ein Eintrag
  POST /api/v1/admin/mappings/{mapping_id}/preview         Diff (kein Write)
  PUT  /api/v1/admin/mappings/{mapping_id}                 Write mit Etag

ADMIN-only. PUT und POST sind Same-Origin-geschützt. Der Client übergibt
ausschliesslich die `mapping_id`; Dateipfade kommen nie aus dem Request.
M1 deckt nur `channel-genre` ab.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import Config
from logger import get_module_logger
from services.access_control import AccessLevel
from services.mapping_admin import (
    MAPPING_ID_CHANNEL_GENRE,
    MappingConflictError,
    MappingDomainError,
    MappingInvalidInputError,
    MappingUnavailableError,
    MappingUnknownIdError,
    apply_channel_genre_update,
    get_channel_genre,
    list_channel_genres,
    plan_channel_genre_update,
)

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.mapping_admin import (
    ChannelGenreGetResponse,
    ChannelGenreListResponse,
    ChannelGenrePreviewResponse,
    ChannelGenreSaveBody,
    ChannelGenreSaveResponse,
    ChannelGenreBody,
    entry_to_schema,
    plan_to_preview,
    save_to_response,
)

_logger = get_module_logger("control_center.mapping_admin")

router = APIRouter(
    prefix="/api/v1/admin/mappings",
    tags=["mappings"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


def _mapping_dir() -> Path:
    return Path(Config.GENRE_MAPPING_DIR)


def _mapping_http_error(e: MappingDomainError) -> HTTPException:
    if isinstance(e, MappingUnknownIdError):
        status, code = 404, "MAPPING_UNKNOWN"
    elif isinstance(e, MappingUnavailableError):
        status, code = 503, "MAPPING_UNAVAILABLE"
    elif isinstance(e, MappingConflictError):
        status, code = 409, "MAPPING_CHANGED"
    elif isinstance(e, MappingInvalidInputError):
        status, code = 422, "MAPPING_INVALID_INPUT"
    else:
        status, code = 422, "MAPPING_DOMAIN_ERROR"
    return HTTPException(
        status_code=status,
        detail=ErrorDetail(code=code, message=str(e)).model_dump(),
    )


def _ensure_supported(mapping_id: str) -> None:
    if mapping_id != MAPPING_ID_CHANNEL_GENRE:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="MAPPING_UNKNOWN",
                message=f"Unbekannte mapping_id: {mapping_id!r}",
            ).model_dump(),
        )


# ── Liste + Einzeleintrag ────────────────────────────────────────────────


@router.get("/{mapping_id}", response_model=ChannelGenreListResponse)
def get_mapping(mapping_id: str) -> ChannelGenreListResponse:
    _ensure_supported(mapping_id)
    try:
        entries = list_channel_genres(_mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    return ChannelGenreListResponse(
        mapping_id=mapping_id,
        entries=[entry_to_schema(e) for e in entries],
        count=len(entries),
    )


@router.get("/{mapping_id}/entry", response_model=ChannelGenreGetResponse)
def get_mapping_entry(
    mapping_id: str, channel: str = Query(..., min_length=1, max_length=200),
) -> ChannelGenreGetResponse:
    _ensure_supported(mapping_id)
    try:
        entry, etag = get_channel_genre(channel, _mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    return ChannelGenreGetResponse(
        mapping_id=mapping_id,
        channel=channel,
        exists=entry is not None,
        entry=entry_to_schema(entry),
        etag=etag,
    )


# ── Preview (read-only) ─────────────────────────────────────────────────


@router.post(
    "/{mapping_id}/preview",
    response_model=ChannelGenrePreviewResponse,
    dependencies=[Depends(verify_same_origin)],
)
def post_mapping_preview(
    mapping_id: str, body: ChannelGenreBody, channel: str = Query(..., min_length=1, max_length=200),
) -> ChannelGenrePreviewResponse:
    _ensure_supported(mapping_id)
    try:
        plan = plan_channel_genre_update(
            channel, body.primary, body.secondary, body.description, _mapping_dir(),
        )
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    return plan_to_preview(mapping_id, channel, plan)


# ── Save (Write mit Etag) ───────────────────────────────────────────────


@router.put(
    "/{mapping_id}",
    response_model=ChannelGenreSaveResponse,
    dependencies=[Depends(verify_same_origin)],
)
def put_mapping(
    mapping_id: str,
    body: ChannelGenreSaveBody,
    channel: str = Query(..., min_length=1, max_length=200),
    user_id: int = Depends(get_current_user_id),
) -> ChannelGenreSaveResponse:
    _ensure_supported(mapping_id)
    try:
        plan, result = apply_channel_genre_update(
            channel, body.primary, body.secondary, body.description,
            _mapping_dir(), expected_etag=body.etag,
        )
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e
    _logger.info(
        f"📺 [control_center] channel-genre {plan.change} für Key {plan.key!r} "
        f"von User {user_id} (geschrieben={result.written})"
    )
    return save_to_response(mapping_id, channel, plan, result)
