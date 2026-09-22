# control_center/routers/navidrome.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/navidrome/status — Navidrome-Verbindungsstatus.

CC-AC-10C (Bot & Operations): POST /scan ruft
utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan()
**direkt** auf — bereits vollständig Telegram-frei (siehe dortiger
Docstring, 1:1 aus NavidromeAPI.execute_scan() ausgelagert), keine neue
Application-Layer-Datei nötig. Identischer Subprozess-/Timeout-Pfad wie
der bestehende Telegram-Scan-Callback (kein Job-Wrapping — run_scan()
ist bereits async/nicht-blockierend für den Event-Loop, hält die
HTTP-Verbindung nur bis zu NAVIDROME_SCAN_TIMEOUT (Default 300s) offen,
identisches Verhalten wie Telegram). Zusätzlich ADMIN-Auth (statt USER
wie GET /status) + CSRF-Schutz, da dies eine schreibende/ausführende
Aktion ist.

Reine Orchestrierung: ruft ausschliesslich
services/clients/navidrome_api.py::NavidromeAPI.check_connection()/
get_artists() auf (identischer Aufrufpfad wie der Rest des Projekts,
z. B. handlers/navidrome_menu_handler.py) — keine eigene Fachlogik.

Erstmaliger `async def`-Router in control_center/: NavidromeAPI ist eine
echte, netzwerkgebundene Integration (anders als die bisherigen
Router, die ausschliesslich lokale/synchrone Produktionsfunktionen
aufrufen) — check_connection()/get_artists() sind bereits async
(asyncio.to_thread-gewrappt), FastAPI awaitet sie direkt statt sie
zusaetzlich in einen Threadpool zu schieben.

check_connection() faengt jeden Fehler (falsche/fehlende Config,
Timeout, Verbindungsabbruch) bereits selbst ab und liefert `False` -
kein eigenes Error-Handling hier noetig, identisches Prinzip wie ein
Health-Check. Ein Fehler beim nachgelagerten get_artists()-Aufruf
(z. B. Navidrome antwortet auf ping, aber nicht auf getArtists) darf
das primaere "ist erreichbar"-Signal nicht verdecken - degradiert daher
auf `artist_count=None` statt den ganzen Request fehlschlagen zu lassen.

Authentifiziert mit mindestens AccessLevel.USER (reiner Status, wie
routers/health.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.clients.navidrome_api import NavidromeAPI
from utils.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.navidrome import NavidromeStatusResponse, ScanTriggerResponse

router = APIRouter(
    prefix="/api/v1/navidrome",
    tags=["navidrome"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.navidrome")


@router.get("/status", response_model=NavidromeStatusResponse)
async def get_navidrome_status() -> NavidromeStatusResponse:
    api = NavidromeAPI()
    connected = await api.check_connection()

    artist_count = None
    if connected:
        try:
            artists = await api.get_artists()
            artist_count = len(artists)
        except Exception as e:  # noqa: BLE001
            _logger.error(f"Navidrome erreichbar, aber get_artists() fehlgeschlagen: {e!r}")

    return NavidromeStatusResponse(connected=connected, artist_count=artist_count)


@router.post(
    "/scan",
    response_model=ScanTriggerResponse,
    dependencies=[
        Depends(require_min_access_level(AccessLevel.ADMIN)),
        Depends(verify_same_origin),
    ],
)
async def post_navidrome_scan(user_id: int = Depends(get_current_user_id)) -> ScanTriggerResponse:
    _logger.info(f"🔄 [control_center] Navidrome-Scan angefordert von User {user_id}")
    try:
        result = await NavidromeScanTrigger.run_scan()
    except (AttributeError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="NAVIDROME_SCAN_CONFIG_ERROR", message=str(e)).model_dump(),
        ) from e
    except ScanTimeoutError as e:
        raise HTTPException(
            status_code=504, detail=ErrorDetail(code="NAVIDROME_SCAN_TIMEOUT", message=str(e)).model_dump(),
        ) from e

    return ScanTriggerResponse(
        success=result.success, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
    )
