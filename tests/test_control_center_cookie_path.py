# tests/test_control_center_cookie_path.py
# -*- coding: utf-8 -*-
"""
Session-Cookie-Path im Subpath-Betrieb (Phase 3): cc_session darf hinter
nginx unter /controlcenter nur an diesen Prefix gebunden werden — nicht an
"/" (sonst geht es an Immich/Navidrome/... derselben Domain).
"""

from __future__ import annotations

import hashlib
import hmac
import time

import httpx
import pytest
import pytest_asyncio

from config import Config

TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"


@pytest.fixture(autouse=True)
def _fixed_bot_token(monkeypatch):
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))


def _payload(user_id=42):
    data = {"id": user_id, "first_name": "Test", "auth_date": int(time.time())}
    dcs = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    key = hashlib.sha256(TEST_BOT_TOKEN.encode()).digest()
    data["hash"] = hmac.new(key, dcs.encode(), hashlib.sha256).hexdigest()
    return data


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="https://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _cookie_attrs(response) -> str:
    return next(v for k, v in response.headers.multi_items() if k == "set-cookie")


@pytest.mark.asyncio
async def test_cookie_path_is_root_in_direct_mode(client):
    response = await client.post("/api/v1/auth/telegram-callback", json=_payload())
    assert response.status_code == 200
    assert "Path=/;" in _cookie_attrs(response) + ";"


@pytest.mark.asyncio
async def test_cookie_path_is_bound_to_prefix_behind_proxy(client):
    response = await client.post(
        "/api/v1/auth/telegram-callback",
        json=_payload(),
        headers={"X-Forwarded-Prefix": "/controlcenter"},
    )
    assert response.status_code == 200
    attrs = _cookie_attrs(response)
    assert "Path=/controlcenter;" in attrs + ";"
    assert "Path=/;" not in attrs + ";"
    # Sicherheitsattribute unveraendert
    assert "HttpOnly" in attrs and "Secure" in attrs and "SameSite=strict" in attrs


@pytest.mark.asyncio
async def test_cookie_is_only_sent_under_prefix_by_jar(client):
    """RFC-6265-Cookie-Jar (httpx) wie ein Browser: Cookie fuer /controlcenter
    wird an /controlcenter/... gesendet, nicht an andere Pfade der Domain."""
    response = await client.post(
        "/api/v1/auth/telegram-callback",
        json=_payload(),
        headers={"X-Forwarded-Prefix": "/controlcenter"},
    )
    assert response.status_code == 200
    jar_paths = {c.path for c in client.cookies.jar}
    assert jar_paths == {"/controlcenter"}
    same = httpx.Request("GET", "https://testserver/controlcenter/api/v1/auth/whoami")
    other = httpx.Request("GET", "https://testserver/navidrome/rest/ping")
    client.cookies.set_cookie_header(same)
    client.cookies.set_cookie_header(other)
    assert "cc_session" in same.headers.get("cookie", "")
    assert "cc_session" not in other.headers.get("cookie", "")


@pytest.mark.asyncio
async def test_hostile_prefix_falls_back_to_root_path_cookie(client):
    response = await client.post(
        "/api/v1/auth/telegram-callback",
        json=_payload(),
        headers={"X-Forwarded-Prefix": "//evil.example"},
    )
    assert "Path=/;" in _cookie_attrs(response) + ";"
