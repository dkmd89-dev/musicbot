# tests/test_control_center_root_path.py
# -*- coding: utf-8 -*-
"""
Root-Path-Spike (Phase 1): X-Forwarded-Prefix -> scope["root_path"].

Beweist gegen die echte App (create_app(), gepinnte FastAPI/Starlette-
Version), dass
  - ohne Header alles unveraendert bleibt (Direktbetrieb 127.0.0.1:8420),
  - mit `X-Forwarded-Prefix: /controlcenter` request.scope["root_path"]
    "/controlcenter" ist, Routing/Static weiter auf Root-Pfaden matchen
    (nginx entfernt den Prefix) und Slash-Redirects den Prefix behalten,
  - manipulierte Header-Werte ignoriert werden.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import Request

from control_center.root_path import normalize_prefix

PREFIX_HEADER = {"X-Forwarded-Prefix": "/controlcenter"}


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()

    @app.get("/__probe")
    def probe(request: Request) -> dict:
        return {
            "root_path": request.scope["root_path"],
            "path": request.scope["path"],
            "static_url": str(request.url_for("static", path="common.css")),
        }

    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_direct_access_root_path_is_empty(client):
    body = (await client.get("/__probe")).json()
    assert body["root_path"] == ""
    assert body["path"] == "/__probe"
    assert body["static_url"] == "http://testserver/static/common.css"


@pytest.mark.asyncio
async def test_forwarded_prefix_sets_root_path(client):
    body = (await client.get("/__probe", headers=PREFIX_HEADER)).json()
    assert body["root_path"] == "/controlcenter"
    # nginx entfernt den Prefix: das Routing sieht weiterhin den Root-Pfad
    assert body["path"] == "/__probe"
    assert body["static_url"] == "http://testserver/controlcenter/static/common.css"


@pytest.mark.asyncio
async def test_trailing_slash_in_header_is_normalized(client):
    body = (await client.get("/__probe", headers={"X-Forwarded-Prefix": "/controlcenter/"})).json()
    assert body["root_path"] == "/controlcenter"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/downloads", "/admin"])
async def test_pages_still_route_with_prefix_header(client, path):
    response = await client.get(path, headers=PREFIX_HEADER)
    assert response.status_code == 200
    assert "MusicBot Control Center" in response.text


@pytest.mark.asyncio
async def test_static_mount_still_served_with_prefix_header(client):
    response = await client.get("/static/common.js", headers=PREFIX_HEADER)
    assert response.status_code == 200
    assert "function checkAuth" in response.text


@pytest.mark.asyncio
async def test_slash_redirect_without_prefix(client):
    response = await client.get("/downloads/")
    assert response.status_code == 307
    assert response.headers["location"] == "http://testserver/downloads"


@pytest.mark.asyncio
async def test_slash_redirect_keeps_prefix(client):
    response = await client.get("/downloads/", headers=PREFIX_HEADER)
    assert response.status_code == 307
    assert response.headers["location"] == "http://testserver/controlcenter/downloads"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    ["//evil.example", "http://evil.example", "/a b", "/../etc", "/a/./b", "controlcenter", "/", "", "/x?y=1", "/x#f"],
)
async def test_invalid_prefix_is_ignored(client, bad):
    body = (await client.get("/__probe", headers={"X-Forwarded-Prefix": bad})).json()
    assert body["root_path"] == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""), ("", ""), ("/", ""), ("/controlcenter", "/controlcenter"),
        ("/controlcenter/", "/controlcenter"), ("/a/b", "/a/b"),
        ("//x", ""), ("/..", ""), ("x", ""),
    ],
)
def test_normalize_prefix(raw, expected):
    assert normalize_prefix(raw) == expected
