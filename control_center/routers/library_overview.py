# control_center/routers/library_overview.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/artists-overview, GET /api/v1/library/artists-overview/{artist}
— Library Artist-Centric UX (CC-AC-1, library_artist_centric_UX.txt).

Bewusst EIGENER Router statt Erweiterung von routers/metadata.py: gleiche
Rohdaten (Library-Health-Report), aber andere Quelle. metadata.py's
GET /artists/GET /tracks/GET /albums bleiben unveraendert an
control_center/_library_scan.py::run_library_scan() gebunden (frischer
Scan, ~37s auf der Produktionsbibliothek) - ihr einziger Konsument ist
weiterhin die bestehende, bewusst Klick-gesteuerte "Library-Metadata"-
Sektion (control_center/templates/library.html, unten im selben
Template erhalten). Ein neuer automatischer Seitenaufruf-Ladepfad darf
diesen Scan laut Auftrag §7a NICHT ungefragt mit ausloesen - deshalb
hier ein separater, rein lesender Pfad ueber
_library_scan.py::load_cached_report() (persistenter Report,
Config.DATA_DIR/library_health_report.json, kein Scan).

Reine Orchestrierung (Router-Regel, Auftrag §22): kein Tag-Parsing, keine
Album-Gruppierung, keine Artist-Normalisierung hier - Reportdaten kommen
bereits vollstaendig aggregiert aus services/library_health/scoring.py
(ueber den persistierten Report), Schema-Mapping bleibt in
schemas/metadata.py (artists_overview_to_response()/
artist_detail_to_response(), identisches Prinzip wie
artists_to_response() oben).

Fehlt der persistente Report komplett (noch nie gescannt, oder aelter
als jede DATA_DIR-Bereinigung) -> HTTPException(404,
code="LIBRARY_REPORT_MISSING") - kein impliziter Scan-Trigger aus einem
GET heraus (Auftrag §7a Punkt 2). Das Erzeugen eines frischen Reports
bleibt bewusst ausserhalb dieses (READ-ONLY, Auftrag CC-AC-1) Schritts -
bestehende Wege ausserhalb dieser UI (CLI scripts/library_health_check.py,
Telegram "🩺 MusicBot Doctor") bleiben davon unberuehrt nutzbar.

Authentifiziert mit derselben Schwelle wie routers/metadata.py
(AccessLevel.ADMIN) - identische granulare Pro-Datei-/Pro-Artist-Daten.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from handlers.menu.models import AccessLevel
from logger import get_module_logger

from .._library_scan import load_cached_report
from ..dependencies import require_min_access_level
from ..schemas.errors import ErrorDetail
from ..schemas.metadata import (
    ArtistDetailResponse,
    ArtistsOverviewResponse,
    artist_detail_to_response,
    artists_overview_to_response,
)

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library-overview"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.library_overview")


def _require_cached_report() -> tuple[dict, bool]:
    report, stale = load_cached_report(logger=_logger)
    if report is None:
        request_id = uuid.uuid4().hex
        _logger.warning(f"[{request_id}] Kein persistenter Library-Report vorhanden")
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="LIBRARY_REPORT_MISSING",
                message=(
                    "Noch kein Library-Report vorhanden. Bitte zuerst einen "
                    "Health-Scan ausführen (Telegram: „🩺 MusicBot Doctor“, "
                    "oder CLI: scripts/library_health_check.py)."
                ),
                request_id=request_id,
            ).model_dump(),
        )
    return report, stale


@router.get("/artists-overview", response_model=ArtistsOverviewResponse)
def get_artists_overview() -> ArtistsOverviewResponse:
    report, stale = _require_cached_report()
    return artists_overview_to_response(report, stale=stale)


@router.get("/artists-overview/{artist}", response_model=ArtistDetailResponse)
def get_artist_overview_detail(artist: str) -> ArtistDetailResponse:
    report, stale = _require_cached_report()
    detail = artist_detail_to_response(report, artist=artist, stale=stale)
    if detail is None:
        request_id = uuid.uuid4().hex
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="ARTIST_NOT_FOUND",
                message=f"Artist „{artist}“ nicht in der Library gefunden.",
                request_id=request_id,
            ).model_dump(),
        )
    return detail
