# control_center/routers/admin_duplicates.py
# -*- coding: utf-8 -*-
"""
Duplikat-Cache-Verwaltung im Control Center (Web-Paritäts-Backlog 4b,
2026-09-28) - Web-Gegenstück zum Telegram-Menü "Admin → Duplikate"
(handlers/duplicate_handler.py::EnhancedDuplicateHandler).

Dünner Router ohne eigene Fachlogik: ruft ausschließlich
services/duplicate/admin.py auf (dieselbe Implementierung wie Telegram).
Seit D.13 wirkt ein hier geleerter Cache sofort auch im Bot-Prozess
(DuplicateCache erkennt die Dateiänderung und lädt neu).

Nicht enthalten: die Sitzungszähler des DuplicateDetector (total_checks,
Duplikat-Rate, ...) - sie leben nur im Speicher des Bot-Prozesses und
kommen mit dem Bot-Snapshot (Entscheidung 1 / E1).

AccessLevel.ADMIN wie in Telegram (_ADMIN_ONLY_PREFIXES "dup:"); das
Leeren braucht Same-Origin + explizites confirm=true.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from config import Config
from logger import get_module_logger
from services.access_control import AccessLevel
from services.duplicate import admin as duplicate_admin

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.admin_duplicates import (
    ClearDuplicateCacheRequest,
    ClearDuplicateCacheResponse,
    DuplicateCacheStatsResponse,
)
from ..schemas.errors import ErrorDetail

router = APIRouter(
    prefix="/api/v1/admin/duplicates",
    tags=["admin-duplicates"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.admin_duplicates")


@router.get("/stats", response_model=DuplicateCacheStatsResponse)
def get_duplicate_cache_stats() -> DuplicateCacheStatsResponse:
    stats = duplicate_admin.get_duplicate_cache_stats(duplicate_admin.cache_for_config(Config()))
    return DuplicateCacheStatsResponse(
        url_entries=stats.url_entries,
        content_entries=stats.content_entries,
        oldest_entry=stats.oldest_entry,
        newest_entry=stats.newest_entry,
    )


@router.post(
    "/clear",
    response_model=ClearDuplicateCacheResponse,
    dependencies=[Depends(verify_same_origin)],
)
def clear_duplicate_cache(
    payload: ClearDuplicateCacheRequest,
    user_id: int = Depends(get_current_user_id),
) -> ClearDuplicateCacheResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="CONFIRMATION_REQUIRED",
                message="Leeren des Duplikat-Caches muss ausdrücklich bestätigt werden.",
            ).model_dump(),
        )
    result = duplicate_admin.clear_duplicate_cache(duplicate_admin.cache_for_config(Config()))
    _logger.info(
        f"🧹 Duplikat-Cache über das Control Center geleert (user_id={user_id}): "
        f"{result.url_entries_removed} URL / {result.content_entries_removed} Content"
    )
    return ClearDuplicateCacheResponse(
        url_entries_removed=result.url_entries_removed,
        content_entries_removed=result.content_entries_removed,
        deleted_files=result.deleted_files,
    )
