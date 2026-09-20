# control_center/routers/logs.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/logs — Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS" /
ui_prompt.txt Abschnitt 23, erster Schritt (bisher komplett
unbearbeitet, siehe Gap-Analyse in docs/audits/
CONTROL_CENTER_ARCHITECTURE_2026-09-15.md).

Reine Orchestrierung: ruft ausschließlich services/logs/reader.py::
read_logs() auf (liest die bereits bestehenden Logdateien aus
Config.LOG_DIR, identische Discovery wie die bestehende Telegram-
Log-Verwaltung `EnhancedLoggerMenuHandler`) — keine neue Logging-
Infrastruktur, keine Fachlogik hier.

Filter: `source` (welche Datei — aktuelle oder rotiertes Backup),
`level`, `component`, `search`, `limit`. **Bewusst KEIN Zeitraum-/Job-/
User-Filter** — die zugrundeliegenden Logzeilen enthalten weder ein
Datum noch eine strukturierte Job-/User-Korrelation (siehe
services/logs/reader.py-Docstring für die vollständige Begründung) —
ein solcher Filter würde eine Genauigkeit vortäuschen, die die
Datenquelle nicht hergibt (Master-Prompt Regel 38).

Security: services/logs/reader.py redigiert offensichtliche
Secret-Muster bereits defensiv, bevor eine Zeile hier den Prozess
verlässt (Master-Prompt Abschnitt 23/31).

Authentifiziert mit mindestens AccessLevel.ADMIN (identische Schwelle
wie Findings/Repair-Plan/Metadata — Logzeilen können interne Pfade/
Fehlermeldungen enthalten).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query

from config import Config
from handlers.menu.models import AccessLevel
from services.logs.reader import read_logs

from ..dependencies import require_min_access_level
from ..schemas.logs import LogsResponse, logs_result_to_response

router = APIRouter(
    prefix="/api/v1",
    tags=["logs"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)


@router.get("/logs", response_model=LogsResponse)
def get_logs(
    source: Optional[str] = Query(default=None),
    level: Optional[str] = Query(default=None),
    component: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> LogsResponse:
    config = Config()
    result = read_logs(
        Path(config.LOG_DIR),
        default_source=Path(config.LOG_FILE).name,
        source=source, level=level, component=component, search=search, limit=limit,
    )
    return logs_result_to_response(result)
