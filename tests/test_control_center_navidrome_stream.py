# tests/test_control_center_navidrome_stream.py
# -*- coding: utf-8 -*-
"""
CC-UI Navidrome N3 — GET /api/v1/navidrome/stream/{song_id}.

Testet den echten Router- und Client-Code (CLAUDE.md Abschnitt 7); Navidrome
selbst ist ersetzt (Abschnitt 8): der Client-Test patcht requests.get, der
Router-Test NavidromeAPI.open_stream. Schwerpunkt Sicherheit (Abschnitt 12):
Subsonic-Zugangsdaten (u=/p=) dürfen nie in Antwort, Fehlermeldung oder Log
landen; der Browser kennt nur das Session-Cookie.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import pytest_asyncio
import requests
from requests.structures import CaseInsensitiveDict

from config import Config
from services.clients import navidrome_api
from services.clients.navidrome_api import NavidromeAPI

_SECRET = "s3cr3t-Passw0rd"
_USER = "musicbot-user"


class _FakeConfig:
    NAVIDROME_URL = "http://navidrome.invalid:4533"
    NAVIDROME_USER = _USER
    NAVIDROME_PASS = _SECRET


class _FakeUpstream:
    def __init__(self, status=200, headers=None, chunks=(b"abc", b"def"), json_body=None):
        self.status_code = status
        self.headers = CaseInsensitiveDict(headers if headers is not None else {"Content-Type": "audio/mpeg"})
        self._chunks = chunks
        self._json = json_body
        self.closed = False

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def json(self):
        if self._json is None:
            raise ValueError("kein JSON")
        return self._json

    def close(self):
        self.closed = True


@pytest.fixture
def authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
def upstream(monkeypatch):
    """Ersetzt NavidromeAPI.open_stream; liefert (calls, set_response)."""
    state = {"calls": [], "response": _FakeUpstream(), "raises": None}

    def _open(self, song_id, range_header=None):
        state["calls"].append((song_id, range_header))
        if state["raises"]:
            raise state["raises"]
        return state["response"]

    monkeypatch.setattr(NavidromeAPI, "open_stream", _open)
    return state


# ─────────────────────────────────────────────────────────────────────────
# Client: NavidromeAPI.open_stream
# ─────────────────────────────────────────────────────────────────────────


def test_open_stream_requests_raw_stream_with_server_side_credentials(monkeypatch):
    seen = {}

    def _get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return "RESPONSE"

    monkeypatch.setattr(navidrome_api.requests, "get", _get)
    result = NavidromeAPI(config=_FakeConfig()).open_stream("song-1", "bytes=100-")

    assert result == "RESPONSE"
    assert seen["url"] == "http://navidrome.invalid:4533/rest/stream.view"
    assert seen["stream"] is True and seen["headers"] == {"Range": "bytes=100-"}
    assert seen["params"]["id"] == "song-1" and seen["params"]["format"] == "raw"
    assert seen["params"]["u"] == _USER and seen["params"]["p"] == _SECRET       # nur serverseitig
    assert _SECRET not in seen["url"]                                             # nie in der URL


def test_open_stream_without_range_sends_no_range_header(monkeypatch):
    seen = {}
    monkeypatch.setattr(navidrome_api.requests, "get", lambda url, **kw: seen.update(kw) or "R")
    NavidromeAPI(config=_FakeConfig()).open_stream("song-1")

    assert seen["headers"] == {}


def test_open_stream_connection_error_is_masked_and_has_no_cause(monkeypatch):
    def _get(url, **kwargs):
        raise requests.exceptions.ConnectionError(
            f"HTTPConnectionPool: Max retries exceeded with url: /rest/stream.view?u={_USER}&p={_SECRET}&id=1")

    monkeypatch.setattr(navidrome_api.requests, "get", _get)
    with pytest.raises(RuntimeError) as excinfo:
        NavidromeAPI(config=_FakeConfig()).open_stream("1")

    assert _SECRET not in str(excinfo.value) and _USER not in str(excinfo.value)
    assert "p=***" in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


# ─────────────────────────────────────────────────────────────────────────
# Router: GET /api/v1/navidrome/stream/{song_id}
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_requires_login(client, upstream):
    response = await client.get("/api/v1/navidrome/stream/abc123")

    assert response.status_code == 401
    assert upstream["calls"] == []                     # ohne Anmeldung wird Navidrome nie gefragt


@pytest.mark.asyncio
async def test_stream_passes_audio_bytes_and_safe_headers(client, authenticated, upstream):
    upstream["response"] = _FakeUpstream(
        headers={"Content-Type": "audio/mpeg", "Content-Length": "6", "Set-Cookie": "x=1",
                 "Server": "Navidrome", "X-Internal": "geheim"})
    response = await client.get("/api/v1/navidrome/stream/abc-123_X")

    assert response.status_code == 200 and response.content == b"abcdef"
    assert response.headers["content-type"] == "audio/mpeg" and response.headers["content-length"] == "6"
    assert response.headers["accept-ranges"] == "bytes" and response.headers["cache-control"] == "private, no-cache"
    for leaked in ("set-cookie", "server", "x-internal"):
        assert leaked not in response.headers
    assert upstream["calls"] == [("abc-123_X", None)]
    assert upstream["response"].closed is True          # Upstream-Verbindung wird immer geschlossen


@pytest.mark.asyncio
async def test_stream_forwards_range_and_returns_206(client, authenticated, upstream):
    upstream["response"] = _FakeUpstream(
        status=206, chunks=(b"cdef",),
        headers={"Content-Type": "audio/flac", "Content-Range": "bytes 2-5/6", "Content-Length": "4"})
    response = await client.get("/api/v1/navidrome/stream/s1", headers={"Range": "bytes=2-"})

    assert upstream["calls"] == [("s1", "bytes=2-")]
    assert response.status_code == 206 and response.content == b"cdef"
    assert response.headers["content-range"] == "bytes 2-5/6"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_range", ["bytes=abc", "bytes=0-5,10-20", "items=0-5", "bytes=-", "bytes=0-5\r\nX: y"])
async def test_stream_ignores_unusable_range_headers(client, authenticated, upstream, bad_range):
    try:
        response = await client.get("/api/v1/navidrome/stream/s1", headers={"Range": bad_range})
    except httpx.InvalidURL:  # pragma: no cover - CR/LF kann httpx selbst nicht senden
        pytest.skip("Header nicht sendbar")

    assert response.status_code == 200
    assert upstream["calls"] == [("s1", None)]          # ungültiger Bereich -> ganze Datei, nichts weitergereicht


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["a b", "a;b", "a.b", "x" * 65, "ä"])
async def test_stream_rejects_malformed_song_ids(client, authenticated, upstream, bad_id):
    response = await client.get(f"/api/v1/navidrome/stream/{bad_id}")

    assert response.status_code == 422
    assert upstream["calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, 404), (400, 404), (416, 416), (500, 502), (503, 502), (401, 502)])
async def test_stream_maps_upstream_errors(client, authenticated, upstream, status, expected):
    upstream["response"] = _FakeUpstream(status=status, headers={"Content-Type": "text/plain"}, chunks=(b"SECRET-BODY",))
    response = await client.get("/api/v1/navidrome/stream/s1")

    assert response.status_code == expected
    assert "SECRET-BODY" not in response.text          # Upstream-Body wird nie weitergereicht
    assert upstream["response"].closed is True


@pytest.mark.asyncio
async def test_stream_subsonic_json_error_is_not_served_as_audio(client, authenticated, upstream):
    """Subsonic meldet Fehler oft als HTTP 200 + JSON (z. B. Code 70 'nicht gefunden')."""
    not_found = {"subsonic-response": {"status": "failed", "error": {"code": 70, "message": "Song not found"}}}
    upstream["response"] = _FakeUpstream(headers={"Content-Type": "application/json"}, json_body=not_found)
    response = await client.get("/api/v1/navidrome/stream/s1")
    assert response.status_code == 404 and upstream["response"].closed is True

    bad_auth = {"subsonic-response": {"status": "failed", "error": {"code": 40, "message": "Wrong username or password"}}}
    upstream["response"] = _FakeUpstream(headers={"Content-Type": "application/json"}, json_body=bad_auth)
    response = await client.get("/api/v1/navidrome/stream/s1")
    assert response.status_code == 502 and "password" not in response.text.lower()


@pytest.mark.asyncio
async def test_stream_rejects_non_audio_success_response(client, authenticated, upstream):
    upstream["response"] = _FakeUpstream(headers={"Content-Type": "text/html"})
    response = await client.get("/api/v1/navidrome/stream/s1")

    assert response.status_code == 502 and upstream["response"].closed is True


@pytest.mark.asyncio
async def test_stream_connection_failure_hides_details_and_logs_no_credentials(client, authenticated, upstream, caplog):
    upstream["raises"] = RuntimeError(f"Max retries exceeded with url: /rest/stream.view?u={_USER}&p={_SECRET}")
    with caplog.at_level(logging.DEBUG):
        response = await client.get("/api/v1/navidrome/stream/s1")

    assert response.status_code == 502
    assert _SECRET not in response.text and _USER not in response.text
    assert _SECRET not in caplog.text and _USER not in caplog.text


@pytest.mark.asyncio
async def test_stream_interrupted_upstream_still_closes_connection(client, authenticated, upstream):
    class _Breaking(_FakeUpstream):
        def iter_content(self, chunk_size=1):
            yield b"abc"
            raise requests.exceptions.ChunkedEncodingError(f"kaputt p={_SECRET}")

    upstream["response"] = _Breaking()
    response = await client.get("/api/v1/navidrome/stream/s1")

    assert response.content == b"abc"
    assert upstream["response"].closed is True
