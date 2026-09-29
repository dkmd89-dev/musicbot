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
    MAPPING_ID_GENRE_ALIASES,
    ChannelGenreEntry,
    ChannelGenrePlan,
    GenreAliasEntry,
    GenreAliasPlan,
    MappingConflictError,
    MappingDomainError,
    MappingInvalidInputError,
    MappingUnavailableError,
    MappingUnknownIdError,
    apply_mapping_update,
    get_mapping_entry,
    list_mapping,
    plan_mapping_update,
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
    GenreAliasGetResponse,
    GenreAliasListResponse,
    GenreAliasPreviewResponse,
    GenreAliasSaveBody,
    GenreAliasSaveResponse,
    GenreAliasBody,
    entry_to_schema,
    genre_alias_entry_to_schema,
    genre_alias_plan_to_preview,
    genre_alias_save_to_response,
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


_SUPPORTED_MAPPING_IDS = frozenset({MAPPING_ID_CHANNEL_GENRE, MAPPING_ID_GENRE_ALIASES})


def _ensure_supported(mapping_id: str) -> None:
    if mapping_id not in _SUPPORTED_MAPPING_IDS:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="MAPPING_UNKNOWN",
                message=f"Unbekannte mapping_id: {mapping_id!r}",
            ).model_dump(),
        )


# ── Liste + Einzeleintrag ────────────────────────────────────────────────


@router.get("/{mapping_id}")
def get_mapping(mapping_id: str):
    """Liste aller Eintraege. Antwort-Schema haengt von der mapping_id ab."""
    _ensure_supported(mapping_id)
    try:
        entries = list_mapping(mapping_id, _mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e

    if mapping_id == MAPPING_ID_CHANNEL_GENRE:
        return ChannelGenreListResponse(
            mapping_id=mapping_id,
            entries=[entry_to_schema(e) for e in entries],
            count=len(entries),
        )
    return GenreAliasListResponse(
        mapping_id=mapping_id,
        entries=[genre_alias_entry_to_schema(e) for e in entries],
        count=len(entries),
    )


@router.get("/{mapping_id}/entry")
def get_mapping_entry_endpoint(
    mapping_id: str, key: str = Query(..., min_length=1, max_length=200),
):
    _ensure_supported(mapping_id)
    try:
        entry, etag = get_mapping_entry(mapping_id, key, _mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e

    if mapping_id == MAPPING_ID_CHANNEL_GENRE:
        return ChannelGenreGetResponse(
            mapping_id=mapping_id,
            channel=key,
            exists=entry is not None,
            entry=entry_to_schema(entry),
            etag=etag,
        )
    return GenreAliasGetResponse(
        mapping_id=mapping_id,
        key=key,
        exists=entry is not None,
        entry=genre_alias_entry_to_schema(entry),
        etag=etag,
    )


# ── Preview (read-only) ─────────────────────────────────────────────────


@router.post(
    "/{mapping_id}/preview",
    dependencies=[Depends(verify_same_origin)],
)
def post_mapping_preview(
    mapping_id: str, body: dict, key: str = Query(..., min_length=1, max_length=200),
):
    _ensure_supported(mapping_id)
    try:
        plan = plan_mapping_update(mapping_id, key, body or {}, _mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e

    if isinstance(plan, ChannelGenrePlan):
        return plan_to_preview(mapping_id, key, plan)
    if isinstance(plan, GenreAliasPlan):
        return genre_alias_plan_to_preview(mapping_id, key, plan)
    raise _mapping_http_error(MappingUnknownIdError(f"Unbekannter Plan: {type(plan)}"))


# ── Save (Write mit Etag) ───────────────────────────────────────────────


@router.put(
    "/{mapping_id}",
    dependencies=[Depends(verify_same_origin)],
)
def put_mapping(
    mapping_id: str,
    body: dict,
    key: str = Query(..., min_length=1, max_length=200),
    user_id: int = Depends(get_current_user_id),
):
    _ensure_supported(mapping_id)
    if not isinstance(body, dict) or "etag" not in body:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="MAPPING_INVALID_INPUT", message="etag fehlt im Body."
            ).model_dump(),
        )
    expected_etag = str(body["etag"])
    payload = {k: v for k, v in body.items() if k != "etag"}
    try:
        plan, result = apply_mapping_update(
            mapping_id, key, payload, _mapping_dir(), expected_etag=expected_etag,
        )
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e

    _logger.info(
        f"[control_center] {mapping_id} {getattr(plan, 'change', '?')} "
        f"fuer Key {getattr(plan, 'key', key)!r} von User {user_id} "
        f"(geschrieben={result.written})"
    )

    if isinstance(plan, ChannelGenrePlan):
        return save_to_response(mapping_id, key, plan, result)
    if isinstance(plan, GenreAliasPlan):
        return genre_alias_save_to_response(mapping_id, key, plan, result)
    raise _mapping_http_error(MappingUnknownIdError(f"Unbekannter Plan: {type(plan)}"))
