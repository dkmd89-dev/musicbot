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

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import Config
from handlers.menu.models import AccessLevel
from services.logger_admin import (
    InvalidLogFilenameError,
    get_log_file,
    get_log_file_stats,
    list_log_files,
)

from ..dependencies import require_min_access_level
from ..schemas.logger import (
    LogFileDetailResponse,
    LogFileListResponse,
    LogFileStatsResponse,
    log_file_detail_to_response,
    log_file_list_to_response,
    log_file_stats_to_response,
)

router = APIRouter(
    prefix="/api/v1/admin/logger",
    tags=["admin-logger"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


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
