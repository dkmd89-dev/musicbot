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
from services.mapping_backups import default_backup_dir
from services.mapping_hierarchy import (
    apply_hierarchy_update,
    get_hierarchy_state,
    plan_hierarchy_update,
)
from services.mapping_admin import (
    MAPPING_ID_CHANNEL_GENRE,
    MAPPING_ID_GENRE_ALIASES,
    MAPPING_ID_GENRE_OVERRIDES,
    MAPPING_ID_GENRE_FILTERS,
    MAPPING_ID_GENRE_HIERARCHY,
    MAPPING_ID_SPECIAL_CHANNELS,
    ChannelGenreEntry,
    ChannelGenrePlan,
    GenreAliasEntry,
    GenreAliasPlan,
    GenreOverrideEntry,
    GenreOverridePlan,
    GenreFilterPlan,
    MappingBackupError,
    MappingBackupNotFoundError,
    MappingConflictError,
    MappingDomainError,
    MappingInvalidInputError,
    MappingUnavailableError,
    MappingUnknownIdError,
    SpecialChannelPlan,
    apply_genre_filter_update,
    apply_mapping_update,
    apply_special_channels_update,
    get_genre_filter_state,
    get_mapping_entry,
    get_special_channels_state,
    list_mapping,
    plan_genre_filter_update,
    plan_mapping_update,
    plan_special_channels_update,
)

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas import mapping_hierarchy as hierarchy_schemas
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
    GenreOverrideGetResponse,
    GenreOverrideListResponse,
    GenreOverridePreviewResponse,
    GenreOverrideSaveBody,
    GenreOverrideSaveResponse,
    GenreOverrideBody,
    GenreFilterListResponse,
    GenreFilterPreviewResponse,
    GenreFilterSaveResponse,
    SpecialChannelCategorySchema,
    SpecialChannelListResponse,
    SpecialChannelPreviewResponse,
    SpecialChannelSaveResponse,
    special_channel_plan_to_preview,
    special_channel_save_to_response,
    genre_filter_plan_to_preview,
    genre_filter_save_to_response,
    entry_to_schema,
    genre_override_entry_to_schema,
    genre_override_plan_to_preview,
    genre_override_save_to_response,
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


def _backup_dir() -> Path:
    return default_backup_dir(Config)


def _mapping_http_error(e: MappingDomainError) -> HTTPException:
    if isinstance(e, MappingUnknownIdError):
        status, code = 404, "MAPPING_UNKNOWN"
    elif isinstance(e, MappingBackupNotFoundError):
        status, code = 404, "MAPPING_BACKUP_NOT_FOUND"
    elif isinstance(e, MappingBackupError):
        status, code = 503, "MAPPING_BACKUP_FAILED"
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


_SUPPORTED_MAPPING_IDS = frozenset({MAPPING_ID_CHANNEL_GENRE, MAPPING_ID_GENRE_ALIASES, MAPPING_ID_GENRE_OVERRIDES, MAPPING_ID_GENRE_FILTERS, MAPPING_ID_SPECIAL_CHANNELS, MAPPING_ID_GENRE_HIERARCHY})


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
    """Liste aller Eintraege bzw. Werte. Antwort-Schema haengt von der mapping_id ab."""
    _ensure_supported(mapping_id)
    if mapping_id == MAPPING_ID_GENRE_FILTERS:
        try:
            values, etag, warnings = get_genre_filter_state(_mapping_dir())
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return GenreFilterListResponse(
            mapping_id=mapping_id,
            values=values,
            count=len(values),
            etag=etag,
            warnings=warnings,
        )
    if mapping_id == MAPPING_ID_GENRE_HIERARCHY:
        try:
            entries, etag, warnings = get_hierarchy_state(_mapping_dir())
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return hierarchy_schemas.HierarchyListResponse(
            mapping_id=mapping_id,
            entries=[hierarchy_schemas.entry_to_schema(e) for e in entries],
            count=len(entries),
            etag=etag,
            warnings=warnings,
        )
    if mapping_id == MAPPING_ID_SPECIAL_CHANNELS:
        try:
            categories, etag, warnings = get_special_channels_state(_mapping_dir())
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return SpecialChannelListResponse(
            mapping_id=mapping_id,
            categories=[
                SpecialChannelCategorySchema(name=c.name, channels=list(c.channels))
                for c in categories
            ],
            count=len(categories),
            etag=etag,
            warnings=warnings,
        )

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
    if mapping_id == MAPPING_ID_GENRE_OVERRIDES:
        return GenreOverrideListResponse(
            mapping_id=mapping_id,
            entries=[genre_override_entry_to_schema(e) for e in entries],
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
    if mapping_id in (MAPPING_ID_GENRE_FILTERS, MAPPING_ID_SPECIAL_CHANNELS, MAPPING_ID_GENRE_HIERARCHY):
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="MAPPING_NO_ENTRIES",
                message=f"{mapping_id} hat keine Einzeleintraege; GET auf die Liste verwenden.",
            ).model_dump(),
        )
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
    if mapping_id == MAPPING_ID_GENRE_OVERRIDES:
        return GenreOverrideGetResponse(
            mapping_id=mapping_id,
            key=key,
            exists=entry is not None,
            entry=genre_override_entry_to_schema(entry),
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
    mapping_id: str,
    body: dict,
    key: Optional[str] = Query(default=None, min_length=1, max_length=200),
):
    _ensure_supported(mapping_id)
    if mapping_id == MAPPING_ID_GENRE_FILTERS:
        try:
            plan = plan_genre_filter_update(
                (body or {}).get("values", []), _mapping_dir(),
            )
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return genre_filter_plan_to_preview(plan)
    if mapping_id == MAPPING_ID_GENRE_HIERARCHY:
        try:
            hierarchy_plan = plan_hierarchy_update((body or {}).get("entries", []), _mapping_dir())
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return hierarchy_schemas.plan_to_preview(hierarchy_plan)
    if mapping_id == MAPPING_ID_SPECIAL_CHANNELS:
        try:
            plan = plan_special_channels_update(
                (body or {}).get("categories", []), _mapping_dir(),
            )
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        return special_channel_plan_to_preview(plan)

    if key is None:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="MAPPING_INVALID_INPUT",
                message="Query-Parameter 'key' fehlt.",
            ).model_dump(),
        )
    try:
        plan = plan_mapping_update(mapping_id, key, body or {}, _mapping_dir())
    except MappingDomainError as e:
        raise _mapping_http_error(e) from e

    if isinstance(plan, ChannelGenrePlan):
        return plan_to_preview(mapping_id, key, plan)
    if isinstance(plan, GenreAliasPlan):
        return genre_alias_plan_to_preview(mapping_id, key, plan)
    if isinstance(plan, GenreOverridePlan):
        return genre_override_plan_to_preview(mapping_id, key, plan)
    raise _mapping_http_error(MappingUnknownIdError(f"Unbekannter Plan: {type(plan)}"))


# ── Save (Write mit Etag) ───────────────────────────────────────────────


@router.put(
    "/{mapping_id}",
    dependencies=[Depends(verify_same_origin)],
)
def put_mapping(
    mapping_id: str,
    body: dict,
    key: Optional[str] = Query(default=None, min_length=1, max_length=200),
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

    if mapping_id == MAPPING_ID_GENRE_FILTERS:
        try:
            plan, result = apply_genre_filter_update(
                payload.get("values", []), _mapping_dir(),
                expected_etag=expected_etag, backup_dir=_backup_dir(),
            )
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        _logger.info(
            f"[control_center] {mapping_id} {plan.change} von User {user_id} "
            f"(geschrieben={result.written})"
        )
        return genre_filter_save_to_response(plan, result)
    if mapping_id == MAPPING_ID_GENRE_HIERARCHY:
        try:
            hierarchy_plan, hierarchy_result = apply_hierarchy_update(
                payload.get("entries", []), _mapping_dir(),
                expected_etag=expected_etag, backup_dir=_backup_dir(),
            )
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        _logger.info(
            f"[control_center] {mapping_id} {hierarchy_plan.change} von User {user_id} "
            f"(geschrieben={hierarchy_result.written})"
        )
        return hierarchy_schemas.save_to_response(hierarchy_plan, hierarchy_result)
    if mapping_id == MAPPING_ID_SPECIAL_CHANNELS:
        try:
            plan, result = apply_special_channels_update(
                payload.get("categories", []), _mapping_dir(),
                expected_etag=expected_etag, backup_dir=_backup_dir(),
            )
        except MappingDomainError as e:
            raise _mapping_http_error(e) from e
        _logger.info(
            f"[control_center] {mapping_id} {plan.change} von User {user_id} "
            f"(geschrieben={result.written})"
        )
        return special_channel_save_to_response(plan, result)

    if key is None:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="MAPPING_INVALID_INPUT",
                message="Query-Parameter 'key' fehlt.",
            ).model_dump(),
        )
    try:
        plan, result = apply_mapping_update(
            mapping_id, key, payload, _mapping_dir(), expected_etag=expected_etag,
            backup_dir=_backup_dir(),
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
    if isinstance(plan, GenreOverridePlan):
        return genre_override_save_to_response(mapping_id, key, plan, result)
    raise _mapping_http_error(MappingUnknownIdError(f"Unbekannter Plan: {type(plan)}"))
