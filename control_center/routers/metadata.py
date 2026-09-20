# control_center/routers/metadata.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/tracks, /artists, /albums — read-only Metadata-
Browser (Master-Prompt Abschnitt 7 "METADATA MANAGEMENT", erster Schritt:
"Tracks anzeigen / Artists anzeigen / Albums anzeigen").

Reine Orchestrierung: identischer Aufrufpfad wie routers/health.py/
repair.py (ein frischer Library-Health-Scan über
control_center/_library_scan.py::run_library_scan()) — keine neue Scan-
oder Aggregationslogik. `report["files"]`/`report["artists"]`/
`report["albums"]` (services/library_health/report.py bzw. scoring.py)
liefern bereits alle benötigten Felder.

Bewusst NUR lesend in diesem Schritt — Metadata bearbeiten, Reprocessing
starten, Cover verwalten, Mapping anzeigen sind eigene, separat
freizugebende Folgeschritte (Master-Prompt Abschnitt 7 nennt alle als
"perspektivisch", nicht als ein einzelner Schritt).

Pagination (`limit`/`offset`) von Anfang an, siehe schemas/metadata.py-
Docstring.

Authentifiziert mit mindestens AccessLevel.ADMIN (identische Schwelle
wie findings/repair-plan — granulare Pro-Datei-Daten inkl. Pfaden, nicht
nur aggregierte Kennzahlen wie health.py).

GET /tracks?issue_code=... (Nachtrag, "fehlende Metadata finden" aus
Master-Prompt Abschnitt 7): filtert die bereits vorhandene
`issue_codes`-Liste je Track — keine neue Domänenlogik, reine
Filterung bereits berechneter Daten (identisches Prinzip wie
services/library_repair/planner.py::filter_plan(issue_code=...) beim
Repair-Plan). Unbekannter Code liefert eine leere Liste statt eines
Fehlers (identisches Verhalten wie filter_plan()).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from handlers.menu.models import AccessLevel
from logger import get_module_logger

from .._library_scan import run_library_scan
from ..dependencies import require_min_access_level
from ..schemas.metadata import (
    AlbumsResponse,
    ArtistsResponse,
    TracksResponse,
    albums_to_response,
    artists_to_response,
    tracks_to_response,
)

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-metadata"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.metadata")


@router.get("/tracks", response_model=TracksResponse)
def get_tracks(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    issue_code: Optional[str] = Query(default=None),
) -> TracksResponse:
    report = run_library_scan(logger=_logger)
    files = report.get("files", [])
    if issue_code:
        files = [f for f in files if issue_code in f.get("issue_codes", [])]
    return tracks_to_response(files, limit=limit, offset=offset)


@router.get("/artists", response_model=ArtistsResponse)
def get_artists(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ArtistsResponse:
    report = run_library_scan(logger=_logger)
    return artists_to_response(report.get("artists", []), limit=limit, offset=offset)


@router.get("/albums", response_model=AlbumsResponse)
def get_albums(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AlbumsResponse:
    report = run_library_scan(logger=_logger)
    return albums_to_response(report.get("albums", []), limit=limit, offset=offset)
