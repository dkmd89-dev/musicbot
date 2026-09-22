# tests/test_control_center_navidrome_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/navidrome/status — Navidrome-Verbindungsstatus.

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/clients/navidrome_api.py::NavidromeAPI.
check_connection()/get_artists() unverändert auf. Navidrome selbst wird
per Mock ersetzt (CLAUDE.md Abschnitt 8: externe Dienste in Unit-Tests
nicht real ansprechen) — identisches Mocking-Prinzip wie
tests/test_navidrome_api_characterization.py (make_request() auf
Instanzebene gepatcht, hier auf Klassenebene, da der Router seine eigene
NavidromeAPI()-Instanz konstruiert).

CC-AC-10C: POST /scan testet denselben Pfad über
utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan() —
ebenfalls gemockt (echter Subprozess-Aufruf ist externe Kommandoausführung,
nicht Teil eines Unit-Tests).
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.clients.navidrome_api import NavidromeAPI
from utils.navidrome_scan_trigger import NavidromeScanTrigger, ScanRunResult, ScanTimeoutError

_SAME_ORIGIN = {"Origin": "http://testserver"}

_PING_OK = {"subsonic-response": {"status": "ok"}}
_PING_FAILED = {"subsonic-response": {"status": "failed"}}
_ARTISTS_TWO = {
    "subsonic-response": {
        "artists": {"index": [{"artist": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]}]}
    }
}


def _fake_make_request(responses: dict):
    def _inner(self, endpoint, params=None):
        return responses[endpoint]
    return _inner


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Navidrome-Status-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_status_connected_with_artist_count(client, monkeypatch):
    monkeypatch.setattr(
        NavidromeAPI, "make_request",
        _fake_make_request({"ping": _PING_OK, "getArtists": _ARTISTS_TWO}),
    )

    response = await client.get("/api/v1/navidrome/status")

    assert response.status_code == 200
    assert response.json() == {"connected": True, "artist_count": 2}


@pytest.mark.asyncio
async def test_status_not_connected_when_ping_fails(client, monkeypatch):
    monkeypatch.setattr(
        NavidromeAPI, "make_request",
        _fake_make_request({"ping": _PING_FAILED}),
    )

    response = await client.get("/api/v1/navidrome/status")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "artist_count": None}


@pytest.mark.asyncio
async def test_status_not_connected_when_ping_raises(client, monkeypatch):
    def _raise(self, endpoint, params=None):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(NavidromeAPI, "make_request", _raise)

    response = await client.get("/api/v1/navidrome/status")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "artist_count": None}


@pytest.mark.asyncio
async def test_status_connected_but_artist_count_none_when_get_artists_fails(client, monkeypatch):
    """Ein Fehler beim nachgelagerten get_artists()-Aufruf darf das
    primaere 'ist erreichbar'-Signal nicht verdecken (Router-Docstring)."""

    def _selective(self, endpoint, params=None):
        if endpoint == "ping":
            return _PING_OK
        raise ConnectionError("getArtists kaputt")

    monkeypatch.setattr(NavidromeAPI, "make_request", _selective)

    response = await client.get("/api/v1/navidrome/status")

    assert response.status_code == 200
    assert response.json() == {"connected": True, "artist_count": None}


# ─────────────────────────────────────────────────────────────────────────
# CC-AC-10C: POST /scan
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_success(client, monkeypatch):
    async def _fake_run_scan():
        return ScanRunResult(success=True, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(NavidromeScanTrigger, "run_scan", _fake_run_scan)

    response = await client.post("/api/v1/navidrome/scan", headers=_SAME_ORIGIN)

    assert response.status_code == 200
    assert response.json() == {"success": True, "returncode": 0, "stdout": "ok", "stderr": ""}


@pytest.mark.asyncio
async def test_scan_reports_config_error(client, monkeypatch):
    async def _fake_run_scan():
        raise AttributeError("NAVIDROME_SCAN_COMMAND ist nicht in Config definiert oder leer.")

    monkeypatch.setattr(NavidromeScanTrigger, "run_scan", _fake_run_scan)

    response = await client.post("/api/v1/navidrome/scan", headers=_SAME_ORIGIN)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scan_reports_timeout(client, monkeypatch):
    async def _fake_run_scan():
        raise ScanTimeoutError(300)

    monkeypatch.setattr(NavidromeScanTrigger, "run_scan", _fake_run_scan)

    response = await client.post("/api/v1/navidrome/scan", headers=_SAME_ORIGIN)

    assert response.status_code == 504


@pytest.mark.asyncio
async def test_scan_rejected_without_origin_header(client, monkeypatch):
    called = False

    async def _fake_run_scan():
        nonlocal called
        called = True
        return ScanRunResult(success=True, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(NavidromeScanTrigger, "run_scan", _fake_run_scan)

    response = await client.post("/api/v1/navidrome/scan")

    assert response.status_code == 403
    assert called is False
