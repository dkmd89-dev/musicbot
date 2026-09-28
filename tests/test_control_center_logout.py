# tests/test_control_center_logout.py
# -*- coding: utf-8 -*-
"""
POST /api/v1/auth/logout: löscht das Session-Cookie (gleicher Path/Flags
wie beim Setzen, auch im Subpath-Betrieb hinter nginx), Same-Origin-Check,
idempotent ohne Session. Echte Session-Erzeugung über
control_center/dependencies.py::create_session_token().
"""

from __future__ import annotations

import httpx
import pytest

from config import Config
from control_center.dependencies import SESSION_COOKIE_NAME, create_session_token

TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"
ORIGIN = {"Origin": "https://testserver"}


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 555))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)


def _client():
    from control_center.app import create_app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="https://testserver")


def _logged_in(c, user_id=555):
    # Domain/Path wie bei einem vom Server gesetzten Cookie (httpx-Cookiejar
    # speichert den punktlosen Host "testserver" als "testserver.local") -
    # sonst würde das Lösch-Cookie des Servers einen anderen Eintrag treffen.
    c.cookies.set(
        SESSION_COOKIE_NAME,
        create_session_token(user_id, bot_token=TEST_BOT_TOKEN),
        domain="testserver.local",
        path="/",
    )


@pytest.mark.asyncio
async def test_logout_clears_session_and_whoami_is_401():
    async with _client() as c:
        _logged_in(c)
        assert (await c.get("/api/v1/auth/whoami")).status_code == 200

        r = await c.post("/api/v1/auth/logout", headers=ORIGIN)

        assert r.status_code == 200
        set_cookie = r.headers["set-cookie"].lower()
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie
        assert "max-age=0" in set_cookie
        assert "path=/" in set_cookie
        assert "secure" in set_cookie and "httponly" in set_cookie and "samesite=strict" in set_cookie
        assert (await c.get("/api/v1/auth/whoami")).status_code == 401


@pytest.mark.asyncio
async def test_logout_uses_subpath_cookie_path_behind_nginx():
    async with _client() as c:
        _logged_in(c)
        r = await c.post(
            "/api/v1/auth/logout", headers={**ORIGIN, "X-Forwarded-Prefix": "/controlcenter"}
        )

    assert r.status_code == 200
    assert "path=/controlcenter" in r.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_logout_without_session_is_ok():
    async with _client() as c:
        r = await c.post("/api/v1/auth/logout", headers=ORIGIN)

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_logout_rejected_without_origin_header():
    async with _client() as c:
        _logged_in(c)
        r = await c.post("/api/v1/auth/logout")
        still = await c.get("/api/v1/auth/whoami")

    assert r.status_code == 403
    assert "set-cookie" not in r.headers
    assert still.status_code == 200
