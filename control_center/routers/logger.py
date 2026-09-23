# -*- coding: utf-8 -*-
"""
CC-LOGGER-L2 — Read-API unter /api/v1/admin/logger/*.

Ausschließlich Klasse-A-Funktionen (shared-filesystem-basiert, siehe
services/logger_admin.py-Docstring und Audit-Doc
docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md). Kein Runtime-Control,
kein Config-Write, kein IPC.

**Route-Reihenfolge ist kritisch:** `/files/stats` MUSS vor
`/files/{name}` deklariert werden — sonst interpretiert FastAPI
`stats` als Dateinamen. Siehe die explizite Reihenfolge unten.

**Abgrenzung zu GET /api/v1/logs:** jene Route liefert
zeilen-orientierte Live-Ansicht (Filter/Level/Search über EINEN
Source) und bleibt unverändert. Diese Route liefert
datei-orientierte Übersicht (Metadaten + Aggregat + Tail-Ansicht)
und ersetzt NICHT die bestehende Route.

Auth: mindestens AccessLevel.ADMIN (identische Schwelle wie
/api/v1/logs). Kein CSRF — reine GET-Endpunkte ohne Seiteneffekt
(Master-Prompt Regel 12).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.logger_admin import (
    InvalidLogFilenameError,
    LoggerApplyRateLimiter,
    LoggerConfigError,
    evaluate_apply_preflight,
    get_log_file,
    get_log_file_stats,
    list_log_files,
    read_logger_config,
    read_runtime_snapshot,
    update_logger_config,
)
from utils.bot_restart_trigger import BotRestartTrigger

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.logger import (
    LoggerApplyResponse,
    LoggerConfigPatchRequest,
    LoggerConfigPatchResponse,
    LoggerConfigResponse,
    LoggerRuntimeStatusResponse,
    LogFileDetailResponse,
    LogFileListResponse,
    LogFileStatsResponse,
    PreflightStatusSchema,
    log_file_detail_to_response,
    log_file_list_to_response,
    log_file_stats_to_response,
    logger_config_to_response,
    runtime_snapshot_result_to_response,
)

router = APIRouter(
    prefix="/api/v1/admin/logger",
    tags=["admin-logger"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.logger")


def _log_dir() -> Path:
    return Path(Config().LOG_DIR)


# ---------------------------------------------------------------------
# Reihenfolge: /files/stats VOR /files/{name}. FastAPI/Starlette matchen
# Routen in Deklarations-Reihenfolge; "stats" würde sonst als
# Dateiname interpretiert und im App-Layer in
# InvalidLogFilenameError → 404 enden.
# ---------------------------------------------------------------------

@router.get("/files", response_model=LogFileListResponse)
def get_log_files() -> LogFileListResponse:
    """Liste aller tatsächlich vorhandenen Logdateien (aktuelle +
    rotierte + Modul-Dateien), sortiert nach mtime (neueste zuerst)."""
    files = list_log_files(_log_dir())
    return log_file_list_to_response(files)


@router.get("/files/stats", response_model=LogFileStatsResponse)
def get_log_files_stats() -> LogFileStatsResponse:
    """Aggregat über alle Logdateien: Anzahl, Gesamtgröße, größte
    Datei, älteste Datei. Keine Runtime-Aussage, nur Filesystem-Metriken."""
    stats = get_log_file_stats(_log_dir())
    return log_file_stats_to_response(stats)


@router.get("/files/{name}", response_model=LogFileDetailResponse)
def get_log_file_detail(
    name: str,
    level: Optional[str] = Query(default=None),
    component: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(
        default=200,
        ge=1,
        le=2000,
        description=(
            "Maximale Anzahl zurückgegebener Einträge. "
            "Default 200, Minimum 1, Maximum 2000. "
            "Werte außerhalb dieses Bereichs werden mit HTTP 422 "
            "abgelehnt — kein stillschweigendes Clamping."
        ),
    ),
) -> LogFileDetailResponse:
    """Inhalt + Metadaten einer einzelnen Logdatei. Filter (level/
    component/search) und `limit` werden unverändert an
    services/logs/reader.py::read_logs() weitergereicht — keine zweite
    Parser-/Filter-Logik.

    **Limit-Grenzen (server-seitig, nicht verhandelbar):**
    Default 200, Minimum 1, Maximum 2000. FastAPI lehnt Werte außerhalb
    mit HTTP 422 ab (Query(ge=1, le=2000)); zusätzlich validiert
    services/logger_admin.py::get_log_file() denselben Bereich
    defensiv, damit direkte Aufrufer (ohne HTTP-Durchlauf) nicht
    stillschweigend übergroße Limits durchreichen.

    Truncation wird über `total_matched` > `limit` kommuniziert
    (identisches Muster wie Accepted-Findings-Panel)."""
    log_dir = _log_dir()
    try:
        result = get_log_file(
            log_dir,
            name=name,
            level=level,
            component=component,
            search=search,
            limit=limit,
        )
    except InvalidLogFilenameError as e:
        # 404 statt 500 oder leerem 200 — die Whitelist-Verletzung ist
        # ein Nutzerfehler (Tippfehler, Traversal-Versuch), kein
        # Serverfehler.
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Datei-Metadaten für den Response zusammenstellen — ein einziger
    # stat() statt eines zweiten Roundtrips über /files.
    path = log_dir / name
    try:
        st = path.stat()
    except OSError as e:
        # Race: Datei war in der Whitelist, ist aber zwischen
        # list_log_sources() und stat() verschwunden (Rotation).
        raise HTTPException(status_code=404, detail=f"Logdatei nicht mehr verfügbar: {name}") from e

    result["_file_name"] = name
    result["_file_size_bytes"] = st.st_size
    result["_file_modified_at"] = datetime.fromtimestamp(st.st_mtime).isoformat()

    return log_file_detail_to_response(result)


# =====================================================================
# CC-LOGGER-L4 Stufe 1 — Persistente Logger-Konfiguration
# =====================================================================
#
# Reine Persistenz-API. Kein Runtime-Control — die Semantik ist "wirksam
# beim naechsten Bot-Start" (siehe L3-Entscheidung). Der Router ruft
# ausschliesslich services/logger_admin.py auf; keine Datei-I/O hier.

_LOGGER_CONFIG_ERROR_TO_HTTP = {
    "LOGGER_CONFIG_MISSING": 409,
    "LOGGER_CONFIG_CORRUPT": 500,
    "LOGGER_CONFIG_UNREADABLE": 500,
    "LOGGER_CONFIG_WRITE_FAILED": 500,
    "LOGGER_CONFIG_PATCH_INVALID": 422,
    "LOGGER_CONFIG_UNKNOWN_MODULE": 422,
    "LOGGER_CONFIG_UNKNOWN_FIELD": 422,
    "LOGGER_CONFIG_INVALID_LEVEL": 422,
    "LOGGER_CONFIG_INVALID_TYPE": 422,
}


def _map_logger_config_error(exc: LoggerConfigError) -> HTTPException:
    status = _LOGGER_CONFIG_ERROR_TO_HTTP.get(exc.code, 500)
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/config", response_model=LoggerConfigResponse)
def get_logger_config() -> LoggerConfigResponse:
    """Liefert die persistente Logger-Konfiguration
    (data/module_logger_config.json).

    **Das ist NICHT der Runtime-Zustand des laufenden Bots.** Die
    Antwort beschreibt ausschliesslich die persistierte Absicht, die
    beim naechsten Bot-Start angewendet wird (siehe L3-Entscheidung).
    Fehlende Datei -> leeres `modules`-Objekt (kein Fehler)."""
    try:
        data = read_logger_config(Config())
    except LoggerConfigError as e:
        raise _map_logger_config_error(e) from e
    return logger_config_to_response(data)


@router.patch(
    "/config",
    response_model=LoggerConfigPatchResponse,
    dependencies=[Depends(verify_same_origin)],
)
def patch_logger_config(body: LoggerConfigPatchRequest) -> LoggerConfigPatchResponse:
    """Aktualisiert die persistente Logger-Konfiguration.

    **Merge-by-module, merge-by-field.** Nur die im Body genannten
    Module werden angefasst; innerhalb eines Moduls nur die genannten
    Felder.

    **Semantik: wirksam beim naechsten Bot-Start.** Diese API bestaetigt
    ausdruecklich NICHT die Anwendung im laufenden Bot-Prozess — das
    waere eine Fake-Live-API und ist nach L3-Entscheidung verboten
    (siehe docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_
    DECISION_2026-09-23.md).

    Fehler-Codes:
    - 409 `LOGGER_CONFIG_MISSING` — keine persistente Config vorhanden
    - 422 `LOGGER_CONFIG_UNKNOWN_MODULE` / `LOGGER_CONFIG_UNKNOWN_FIELD`
      / `LOGGER_CONFIG_INVALID_LEVEL` / `LOGGER_CONFIG_INVALID_TYPE` /
      `LOGGER_CONFIG_PATCH_INVALID`
    - 500 `LOGGER_CONFIG_CORRUPT` / `LOGGER_CONFIG_WRITE_FAILED`"""
    cfg = Config()
    try:
        new_config = update_logger_config(cfg, body.modules)
    except LoggerConfigError as e:
        raise _map_logger_config_error(e) from e

    return LoggerConfigPatchResponse(
        success=True,
        message=(
            "Logger-Konfiguration wurde gespeichert und wird beim "
            "naechsten Bot-Start wirksam. Der laufende Bot-Prozess "
            "wurde NICHT veraendert."
        ),
        modules_updated=sorted(body.modules.keys()),
        total=len(new_config),
    )


# =====================================================================
# CC-LOGGER-L5.1 — Runtime-Status (Snapshot)
# =====================================================================


@router.get("/runtime-status", response_model=LoggerRuntimeStatusResponse)
def get_logger_runtime_status() -> LoggerRuntimeStatusResponse:
    """Liefert den zuletzt geschriebenen Runtime-Snapshot des Bots
    (`data/logger_runtime_snapshot.json`).

    **Das ist NICHT der Live-Zustand des laufenden Bots.** Der Snapshot
    wird einmalig beim erfolgreichen Bot-Startup geschrieben und
    beschreibt den Zustand *nach dem letzten Start*. Bei fehlendem
    oder unvollstaendigem Snapshot wird kein Fake-State konstruiert
    — der Aufrufer erhaelt `status="missing"` bzw. `status="corrupt"`.

    Der Router delegiert vollstaendig an
    services/logger_admin.py::read_runtime_snapshot()."""
    result = read_runtime_snapshot(Config())
    return runtime_snapshot_result_to_response(result)


# =====================================================================
# CC-LOGGER-L5.3 — Controlled Apply / Restart
# =====================================================================

_RESTART_SERVICE_NAME = "bot"
# Identisch zu admin_operations.py::_PRE_RESTART_DELAY_SECONDS —
# Response geht zuerst zurueck, Restart laeuft verzoegert.
_PRE_RESTART_DELAY_SECONDS = 2.0


def _get_apply_limiter(request: Request) -> LoggerApplyRateLimiter:
    return request.app.state.logger_apply_limiter


@router.post(
    "/apply",
    response_model=LoggerApplyResponse,
    dependencies=[Depends(verify_same_origin)],
)
async def post_logger_apply(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> LoggerApplyResponse:
    """Wendet die persistierte Logger-Konfiguration durch einen
    kontrollierten Bot-Neustart an.

    **Semantik:** das ist ein administrativer Bot-Restart, nicht
    "Logger live aendern". Die persistierte Konfiguration ist der Anlass,
    der eigentliche Vorgang ist der Restart. Die Response bestaetigt
    ausdruecklich NICHT, dass der Bot danach erfolgreich neu gestartet
    ist (Response-before-restart).

    Ablauf:

        Auth (Router-Dependency, ADMIN)
            |
        CSRF (verify_same_origin)
            |
        Rate-Limit (LoggerApplyRateLimiter, 60s)
            |
        Config validieren (persistierte Config muss lesbar und
                           vollstaendig sein)
            |
        Preflight (Repair-Lock)
            |
            +-- blocked  -> HTTP 409, keine Mutation, kein Restart
            |
            +-- clear / unverified  -> Restart planen
                                          |
                                          -> Response 200

    Bei `unverified` wird der Restart ausgeloest, aber die Response
    weist die nicht pruefbaren Aktivitaeten strukturiert aus
    (`preflight.status="unverified"`, `preflight.unverified=[...]`).
    """
    # --- 1. Rate-Limit ---
    limiter = _get_apply_limiter(request)
    allowed, retry_after = limiter.try_acquire()
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "LOGGER_APPLY_RATE_LIMITED",
                "message": (
                    f"Rate-Limit aktiv. Naechster Apply fruehestens in "
                    f"{retry_after:.0f}s."
                ),
                "retry_after_seconds": int(retry_after) + 1,
            },
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    # --- 2. Config validieren ---
    # Wir muessen sicher sein, dass die persistierte Config existiert und
    # vollstaendig ist — sonst startet der Bot nach dem Restart mit
    # Defaults, was der Nutzer nicht wollte. Wir schreiben die Config
    # NICHT neu (das ist Aufgabe des PATCH-Endpoints).
    try:
        config = read_logger_config(Config())
    except LoggerConfigError as e:
        raise _map_logger_config_error(e) from e

    if not config:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOGGER_CONFIG_MISSING",
                "message": (
                    "Keine persistierte Logger-Konfiguration vorhanden. "
                    "Es gibt nichts anzuwenden — Restart abgebrochen."
                ),
            },
        )

    # --- 3. Preflight ---
    preflight = evaluate_apply_preflight()
    preflight_schema = PreflightStatusSchema(**preflight)

    if preflight["status"] == "blocked":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOGGER_APPLY_BLOCKED",
                "message": preflight["message"],
                "preflight": preflight,
            },
        )

    # --- 4. Restart planen (Response-before-restart) ---
    _logger.warning(
        f"🔄 [control_center] Logger-Apply (Restart) angefordert von "
        f"User {user_id} — Preflight={preflight['status']}"
    )
    asyncio.get_running_loop().call_later(
        _PRE_RESTART_DELAY_SECONDS,
        BotRestartTrigger.trigger_restart,
        _RESTART_SERVICE_NAME,
    )

    return LoggerApplyResponse(
        status="applied",
        message=(
            "Konfiguration validiert, Preflight freigegeben. "
            "Bot-Neustart wird in Kuerze ausgeloest. Der Bot wendet die "
            "persistierte Logger-Konfiguration beim Neustart an."
        ),
        preflight=preflight_schema,
    )
