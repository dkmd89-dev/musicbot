# control_center/routers/statistics.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/statistics/me — eigene Play-History-Statistik.

Reine Orchestrierung: löst zunächst über services/user_data.py::
get_navidrome_user() (Common-Core-Extraktion, siehe control_center/
dependencies.py-Docstring) den zur aktuell authentifizierten Telegram-ID
gehörenden Navidrome-Username auf, ruft dann ausschließlich
services/statistik_service.py::StatistikService.generate_stats() auf —
identischer Aufrufpfad wie handlers/mugge_statistik_handler.py. Keine
eigene Statistik-Berechnung hier (CLAUDE.md Abschnitt 4).

"/me" statt eines generischen "/api/v1/statistics": die Statistik ist
strikt pro Navidrome-Benutzer (generate_stats() liefert None ohne einen
konkreten navidrome_username — es gibt keine "globale" Statistik). Der
Name lässt bewusst Raum für den Cross-User-Endpunkt unten ohne
Pfadkollision ("/me" ist als literaler Pfad zuerst registriert und
gewinnt gegen "/{navidrome_username}").

Authentifiziert mit mindestens AccessLevel.USER (eigene Daten, wie
routers/health.py — anders als die aggregierten, chat-/nutzer-
übergreifenden ADMIN-Endpunkte findings/repair-plan/downloads).

GET /{navidrome_username} (Nachtrag) hebt die Schwelle für genau diese
eine Route zusätzlich auf AccessLevel.ADMIN an (Route-Level-Dependency
zusätzlich zur Router-Level-USER-Schwelle) — erster Admin-only-Einblick
in fremde Hörstatistiken, natürliche Ergänzung zur bereits vorhandenen
Admin-Nutzerübersicht (routers/admin.py). Bewusst kein eigener Endpunkt
zur Auflösung Telegram-ID→Navidrome-Username nötig: die Admin-Übersicht
liefert `navidrome_user` bereits pro Zeile mit.

GET /me/genres, GET /me/music-dna (Nachtrag): schließen den zweiten seit
dem ursprünglichen Statistics-Schritt offenen Punkt — reines Mapping auf
services/statistik_service.py::StatistikService.generate_genre_stats()/
generate_music_dna() (beide bereits produktiv, All-Time statt
Kalenderzeitraum, siehe dortige Docstrings). Bewusst nur "/me" in diesem
Schritt (kein Cross-User-Pendant für Genre/DNA) — kleinster sinnvoller
Schritt, analog dazu, dass auch die reguläre Cross-User-Statistik ein
eigener, separat freigegebener Folgeschritt war. Zwei Pfadsegmente
("/me/genres"/"/me/music-dna") kollidieren nicht mit dem einsegmentigen
"/{navidrome_username}" (Starlettes Pfad-Matching prüft die Segmentzahl).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.statistik_service import StatistikService
from services.user_data import get_navidrome_user, load_user_data

from ..dependencies import get_current_user_id, require_min_access_level
from ..schemas.errors import ErrorDetail
from ..schemas.statistics import (
    GenreStatsResponse,
    MusicDnaResponse,
    StatisticsResponse,
    TimelineResponse,
    genre_stats_to_response,
    music_dna_to_response,
    stats_to_response,
    timeline_to_response,
)

router = APIRouter(
    prefix="/api/v1/statistics",
    tags=["statistics"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.statistics")


def _resolve_own_navidrome_username(user_id: int) -> str:
    """Gemeinsame Telegram-ID→Navidrome-Username-Auflösung für alle
    "/me"-Endpunkte dieses Routers — identische 404-Semantik überall."""
    config = Config()
    user_data = load_user_data(Path(config.DATA_DIR) / "user_data.json", logger=_logger)
    navidrome_username = get_navidrome_user(user_data, user_id)
    if not navidrome_username:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="NAVIDROME_USER_NOT_CONFIGURED",
                message="Für diesen Account ist kein Navidrome-Benutzer hinterlegt.",
            ).model_dump(),
        )
    return navidrome_username


@router.get("/me", response_model=StatisticsResponse)
def get_my_statistics(
    period: Literal["week", "month", "year"] = Query(default="month"),
    user_id: int = Depends(get_current_user_id),
) -> StatisticsResponse:
    navidrome_username = _resolve_own_navidrome_username(user_id)
    service = StatistikService()
    stats = service.generate_stats(period=period, navidrome_username=navidrome_username)
    return stats_to_response(navidrome_username, stats)


@router.get("/me/genres", response_model=GenreStatsResponse)
def get_my_genre_stats(
    top_n: int = Query(default=10, ge=1, le=50),
    user_id: int = Depends(get_current_user_id),
) -> GenreStatsResponse:
    navidrome_username = _resolve_own_navidrome_username(user_id)
    service = StatistikService()
    stats = service.generate_genre_stats(navidrome_username, top_n=top_n)
    return genre_stats_to_response(navidrome_username, stats)


@router.get("/me/music-dna", response_model=MusicDnaResponse)
def get_my_music_dna(
    top_n: int = Query(default=5, ge=1, le=50),
    user_id: int = Depends(get_current_user_id),
) -> MusicDnaResponse:
    navidrome_username = _resolve_own_navidrome_username(user_id)
    service = StatistikService()
    stats = service.generate_music_dna(navidrome_username, top_n=top_n)
    return music_dna_to_response(navidrome_username, stats)


@router.get("/me/timeline", response_model=TimelineResponse)
def get_my_timeline(
    user_id: int = Depends(get_current_user_id),
) -> TimelineResponse:
    navidrome_username = _resolve_own_navidrome_username(user_id)
    service = StatistikService()
    stats = service.generate_timeline_stats(navidrome_username=navidrome_username)
    return timeline_to_response(stats)


@router.get(
    "/{navidrome_username}",
    response_model=StatisticsResponse,
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
def get_user_statistics(
    navidrome_username: str,
    period: Literal["week", "month", "year"] = Query(default="month"),
) -> StatisticsResponse:
    service = StatistikService()
    stats = service.generate_stats(period=period, navidrome_username=navidrome_username)
    return stats_to_response(navidrome_username, stats)
