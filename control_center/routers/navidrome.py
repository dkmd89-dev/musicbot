# control_center/routers/navidrome.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/navidrome/status — Navidrome-Verbindungsstatus.

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

from fastapi import APIRouter, Depends

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.clients.navidrome_api import NavidromeAPI

from ..dependencies import require_min_access_level
from ..schemas.navidrome import NavidromeStatusResponse

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
