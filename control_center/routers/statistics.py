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
Name lässt bewusst Raum für einen späteren, admin-only Cross-User-Endpunkt
ohne Pfadkollision.

Authentifiziert mit mindestens AccessLevel.USER (eigene Daten, wie
routers/health.py — anders als die aggregierten, chat-/nutzer-
übergreifenden ADMIN-Endpunkte findings/repair-plan/downloads).
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
from ..schemas.statistics import StatisticsResponse, stats_to_response

router = APIRouter(
    prefix="/api/v1/statistics",
    tags=["statistics"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.statistics")


@router.get("/me", response_model=StatisticsResponse)
def get_my_statistics(
    period: Literal["week", "month", "year"] = Query(default="month"),
    user_id: int = Depends(get_current_user_id),
) -> StatisticsResponse:
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

    service = StatistikService()
    stats = service.generate_stats(period=period, navidrome_username=navidrome_username)
    return stats_to_response(navidrome_username, stats)
