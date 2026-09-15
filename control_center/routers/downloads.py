# control_center/routers/downloads.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/downloads/history — Download-Verlauf, chat-übergreifend.

Reine Orchestrierung: liest ausschliesslich die bestehende, persistente
services/downloader/download_history.py::DownloadHistoryStore (identische
Datenquelle/Pfad wie handlers/menu/rich_menu_handler.py — Config.DOWNLOAD_HISTORY_DIR,
absoluter Pfad). Kein Schreibzugriff (Master-Prompt Regel 12: GET ohne
Seiteneffekte).

Ausdrücklich NICHT Teil dieser Route: Live-Fortschritt laufender Downloads
(services/downloader/active_downloads.py::ActiveDownloadRegistry). Diese
Registry lebt laut eigenem Modul-Docstring ausschliesslich im
Arbeitsspeicher des Bot-Prozesses (gehalten von RichMenuHandler über
dessen gesamte Laufzeit) — control_center/ läuft als separater Prozess
(docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 7) ohne
gemeinsamen Speicher mit bot.py und kann diesen Zustand daher grundsätzlich
nicht lesen, unabhängig von der Implementierung hier. Siehe Nachtrag im
Architektur-Dokument für die dazu getroffene Scope-Entscheidung
("nur Download-Verlauf, kein Live-Status").

Authentifiziert mit mindestens AccessLevel.ADMIN — die aggregierte,
chat-übergreifende Sicht zeigt potenziell Downloads anderer Nutzer/
Familienmitglieder, nicht nur die eigenen (anders als die Telegram-eigene
"📋 Download-Verlauf"-Ansicht, die nur den jeweils eigenen Chat zeigt) —
identische Schwelle wie routers/findings.py und routers/repair.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from config import Config
from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.downloader.download_history import DownloadHistoryStore

from ..dependencies import require_min_access_level
from ..schemas.downloads import DownloadHistoryResponse, history_to_response

router = APIRouter(
    prefix="/api/v1/downloads",
    tags=["downloads"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.downloads")


@router.get("/history", response_model=DownloadHistoryResponse)
def get_download_history(
    limit: int = Query(default=50, ge=1, le=200),
) -> DownloadHistoryResponse:
    config = Config()
    store = DownloadHistoryStore(cache_dir=str(config.DOWNLOAD_HISTORY_DIR), logger=_logger)
    entries = store.get_all_recent(limit=limit)
    return history_to_response(entries)
