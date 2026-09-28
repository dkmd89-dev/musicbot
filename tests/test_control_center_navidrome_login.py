# tests/test_control_center_navidrome_login.py
# -*- coding: utf-8 -*-
"""
Backlog 9 — POST /api/v1/auth/navidrome-login: echter Router + echte
Session-/Rollenlogik; nur der Navidrome-Aufruf ist gefakt
(services.web_auth.authenticate_navidrome_login bekommt seinen Verifier
über verify_navidrome_credentials, das hier ersetzt wird).

Geprüft: Freischaltung nur per user_data (Telegram-verknüpft oder
Web-Benutzer), einheitliche Fehlermeldung, Rate-Limit mit Retry-After,
503 bei nicht erreichbarem Navidrome, Same-Origin, Rolle höchstens ADMIN,
Passwort nie in Log/Antwort.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from config import Config
from services import web_auth
from services.clients.navidrome_api import CREDENTIALS_INVALID, CREDENTIALS_OK, CREDENTIALS_UNAVAILABLE

TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"
SECRET = "Sup3r-Geheim!"
ORIGIN = {"Origin": "https://testserver"}
OWNER_ID = 555


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: OWNER_ID))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    (tmp_path / "user_data.json").write_text(json.dumps({
        str(OWNER_ID): {"role": "owner", "navidrome_user": "robin"},
        "111": {"role": "admin", "navidrome_user": "Admina"},
        "-1": {"role": "user", "navidrome_user": "webby", "account_type": "web"},
    }), encoding="utf-8")


@pytest.fixture
def verifier(monkeypatch):
    """Ersetzt nur den Navidrome-Aufruf; Rückgabe steuerbar."""
    state = {"outcome": CREDENTIALS_OK, "calls": []}

    def fake(username, password):
        state["calls"].append((username, password))
        return state["outcome"]

    monkeypatch.setattr(web_auth, "verify_navidrome_credentials", fake)
    original = web_auth.authenticate_navidrome_login

    def patched(user_data, username, password, *, verifier=fake):
        return original(user_data, username, password, verifier=verifier)

    monkeypatch.setattr(web_auth, "authenticate_navidrome_login", patched)
    return state


def _client():
    from control_center.app import create_app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="https://testserver")


async def _login(c, username, password=SECRET, headers=ORIGIN):
    return await c.post("/api/v1/auth/navidrome-login", json={"username": username, "password": password}, headers=headers)


@pytest.mark.asyncio
async def test_web_user_login_creates_session(verifier):
    async with _client() as c:
        r = await _login(c, "webby")
        assert r.status_code == 200
        who = (await c.get("/api/v1/auth/whoami")).json()

    assert who == {"user_id": -1, "access_level": "USER"}
    assert verifier["calls"] == [("webby", SECRET)]


@pytest.mark.asyncio
async def test_linked_telegram_user_gets_same_identity(verifier):
    async with _client() as c:
        await _login(c, "ADMINA")  # ohne Groß-/Kleinschreibung
        who = (await c.get("/api/v1/auth/whoami")).json()

    assert who == {"user_id": 111, "access_level": "ADMIN"}


@pytest.mark.asyncio
async def test_owner_via_navidrome_is_capped_to_admin(verifier):
    async with _client() as c:
        await _login(c, "robin")
        who = (await c.get("/api/v1/auth/whoami")).json()

    assert who == {"user_id": OWNER_ID, "access_level": "ADMIN"}


@pytest.mark.asyncio
async def test_wrong_password_and_not_enabled_look_identical(verifier):
    async with _client() as c:
        verifier["outcome"] = CREDENTIALS_INVALID
        wrong = await _login(c, "webby")
        verifier["outcome"] = CREDENTIALS_OK
        unknown = await _login(c, "fremd")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "LOGIN_INVALID"
    assert "set-cookie" not in unknown.headers


@pytest.mark.asyncio
async def test_rate_limit_after_five_failures(verifier):
    verifier["outcome"] = CREDENTIALS_INVALID
    async with _client() as c:
        for _ in range(web_auth.MAX_FAILURES):
            assert (await _login(c, "webby")).status_code == 401
        blocked = await _login(c, "webby")
        calls_before = len(verifier["calls"])
        verifier["outcome"] = CREDENTIALS_OK
        still_blocked = await _login(c, "webby")

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert still_blocked.status_code == 429  # auch mit richtigem Passwort
    assert len(verifier["calls"]) == calls_before  # Navidrome nicht mehr gefragt


@pytest.mark.asyncio
async def test_navidrome_unavailable_returns_503(verifier):
    verifier["outcome"] = CREDENTIALS_UNAVAILABLE
    async with _client() as c:
        r = await _login(c, "webby")

    assert r.status_code == 503
    assert r.json()["error"]["code"] == "NAVIDROME_UNAVAILABLE"


@pytest.mark.asyncio
async def test_rejected_without_origin_header(verifier):
    async with _client() as c:
        r = await _login(c, "webby", headers={})

    assert r.status_code == 403
    assert verifier["calls"] == []


@pytest.mark.asyncio
async def test_password_never_logged_or_returned(verifier, caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as c:
        ok = await _login(c, "webby")
        verifier["outcome"] = CREDENTIALS_INVALID
        bad = await _login(c, "webby")

    assert SECRET not in caplog.text
    assert SECRET not in ok.text and SECRET not in bad.text
    assert SECRET not in ok.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_navidrome_session_cookie_is_restrictive(verifier):
    async with _client() as c:
        r = await _login(c, "webby")

    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
