# tests/test_control_center_auth.py
# -*- coding: utf-8 -*-
"""
Auth-Grundgerüst — Vertical Slice "Health/Dashboard", Schritt 3.

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7):
control_center/dependencies.py direkt (Telegram-Login-Widget-Verifikation,
Session-Token-Erzeugung/-Prüfung) sowie control_center/routers/auth.py
über HTTP (httpx.AsyncClient + ASGITransport, siehe
test_control_center_health_api.py für die Begründung dieser Wahl statt
starlette.testclient.TestClient).

Config.BOT_TOKEN wird pro Test auf einen festen Test-Wert gepatcht (nie
das echte Secret aus .env) — Property-Monkeypatch analog zu
Config.LIBRARY_DIR/DATA_DIR in anderen Control-Center-Tests.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import httpx
import pytest
import pytest_asyncio

from config import Config
from control_center.dependencies import (
    SESSION_TTL_SECONDS,
    create_session_token,
    require_min_access_level,
    verify_session_token,
    verify_telegram_login,
)
from handlers.menu.models import AccessLevel
from services.clients.navidrome_api import NavidromeAPI
from services.statistik_service import StatistikService

TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"


@pytest.fixture(autouse=True)
def _fixed_bot_token(monkeypatch):
    monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: TEST_BOT_TOKEN))


def _signed_telegram_payload(user_id=42, *, auth_date=None, bot_token=TEST_BOT_TOKEN, **extra):
    data = {
        "id": user_id,
        "first_name": "Test",
        "auth_date": auth_date if auth_date is not None else int(time.time()),
        **extra,
    }
    check_fields = {k: v for k, v in data.items() if v is not None}
    data_check_string = "\n".join(f"{k}={check_fields[k]}" for k in sorted(check_fields))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    data["hash"] = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return data


# ─────────────────────────────────────────────────────────────────────────
# verify_telegram_login()
# ─────────────────────────────────────────────────────────────────────────


def test_verify_telegram_login_accepts_correctly_signed_payload():
    payload = _signed_telegram_payload()
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is True


def test_verify_telegram_login_rejects_tampered_field():
    payload = _signed_telegram_payload()
    payload["id"] = 999999  # nach der Signierung veraendert
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


def test_verify_telegram_login_rejects_wrong_hash():
    payload = _signed_telegram_payload()
    payload["hash"] = "0" * 64
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


def test_verify_telegram_login_rejects_missing_hash():
    payload = _signed_telegram_payload()
    del payload["hash"]
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


def test_verify_telegram_login_rejects_signature_from_different_bot_token():
    payload = _signed_telegram_payload(bot_token="other-bot-token")
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


def test_verify_telegram_login_rejects_stale_auth_date():
    payload = _signed_telegram_payload(auth_date=int(time.time()) - 2 * 24 * 3600)
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


def test_verify_telegram_login_rejects_future_auth_date():
    payload = _signed_telegram_payload(auth_date=int(time.time()) + 3600)
    assert verify_telegram_login(payload, bot_token=TEST_BOT_TOKEN) is False


# ─────────────────────────────────────────────────────────────────────────
# Session-Token
# ─────────────────────────────────────────────────────────────────────────


def test_session_token_round_trips_to_correct_user_id():
    token = create_session_token(4711, bot_token=TEST_BOT_TOKEN)
    assert verify_session_token(token, bot_token=TEST_BOT_TOKEN) == 4711


def test_session_token_rejected_with_wrong_bot_token():
    token = create_session_token(4711, bot_token=TEST_BOT_TOKEN)
    assert verify_session_token(token, bot_token="other-bot-token") is None


def test_session_token_rejected_when_tampered():
    token = create_session_token(4711, bot_token=TEST_BOT_TOKEN)
    payload_b64, signature = token.split(".", 1)
    tampered = payload_b64 + "." + ("f" * len(signature))
    assert verify_session_token(tampered, bot_token=TEST_BOT_TOKEN) is None


def test_session_token_rejected_when_malformed():
    assert verify_session_token("not-a-valid-token", bot_token=TEST_BOT_TOKEN) is None


def test_session_token_rejected_when_expired(monkeypatch):
    import control_center.dependencies as deps

    monkeypatch.setattr(deps, "SESSION_TTL_SECONDS", 1)
    token = create_session_token(4711, bot_token=TEST_BOT_TOKEN)
    time.sleep(1.1)
    assert verify_session_token(token, bot_token=TEST_BOT_TOKEN) is None


def test_session_ttl_default_is_positive():
    assert SESSION_TTL_SECONDS > 0


# ─────────────────────────────────────────────────────────────────────────
# require_min_access_level() — Dependency-Factory
# ─────────────────────────────────────────────────────────────────────────


def test_require_min_access_level_rejects_insufficient_level():
    from fastapi import HTTPException

    check = require_min_access_level(AccessLevel.ADMIN)
    with pytest.raises(HTTPException) as exc_info:
        check(level=AccessLevel.USER)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "FORBIDDEN"


def test_require_min_access_level_allows_sufficient_level():
    check = require_min_access_level(AccessLevel.ADMIN)
    assert check(level=AccessLevel.ADMIN) == AccessLevel.ADMIN
    assert check(level=AccessLevel.OWNER) == AccessLevel.OWNER


# ─────────────────────────────────────────────────────────────────────────
# HTTP: POST /api/v1/auth/telegram-callback + GET /api/v1/auth/whoami
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    # https:// statt http:// (anders als in den uebrigen Control-Center-
    # Tests): das Session-Cookie wird mit secure=True gesetzt (Master-Prompt
    # Abschnitt 20/32 - TLS-Pflicht fuer das Telegram-Login-Widget ohnehin
    # gegeben, siehe docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
    # Abschnitt 3). httpx' Cookie-Jar verhaelt sich RFC-6265-konform wie ein
    # echter Browser und wuerde ein Secure-Cookie unter http:// gar nicht
    # erst speichern/mitsenden - das Client-Verhalten muss daher zum
    # Ziel-Deployment (immer hinter TLS) passen, nicht zum lokalen ASGI-Test.
    c = httpx.AsyncClient(transport=transport, base_url="https://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_telegram_callback_accepts_valid_payload_and_sets_cookie(client):
    payload = _signed_telegram_payload(user_id=555)

    response = await client.post("/api/v1/auth/telegram-callback", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "cc_session" in response.cookies


@pytest.mark.asyncio
async def test_telegram_callback_rejects_invalid_signature(client):
    payload = _signed_telegram_payload(user_id=555)
    payload["hash"] = "0" * 64

    response = await client.post("/api/v1/auth/telegram-callback", json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TELEGRAM_LOGIN_INVALID"
    assert "cc_session" not in response.cookies


@pytest.mark.asyncio
async def test_whoami_requires_authentication(client, monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))

    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.asyncio
async def test_whoami_returns_user_id_and_access_level_for_valid_session(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 555))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))

    login_response = await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=555)
    )
    assert login_response.status_code == 200

    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": 555, "access_level": "OWNER"}


@pytest.mark.asyncio
async def test_whoami_resolves_admin_from_config(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))

    await client.post("/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777))
    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": 777, "access_level": "ADMIN"}


@pytest.mark.asyncio
async def test_whoami_defaults_to_user_level_for_unknown_id(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))

    await client.post("/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999))
    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": 999, "access_level": "USER"}


@pytest.mark.asyncio
async def test_whoami_resolves_moderator_from_user_data_json(client, monkeypatch, tmp_path):
    """Nachtrag: get_current_access_level() liest jetzt data/user_data.json
    (ueber services/user_data.py::load_user_data(), Common-Core-Extraktion
    aus UserManagementHandler) - schliesst die zuvor dokumentierte MVP-
    Luecke (MODERATOR war nur ueber Telegram-Rollenverwaltung vergebbar,
    hier zuvor nicht aufgeloest)."""
    import json

    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    (tmp_path / "user_data.json").write_text(
        json.dumps({"555": {"role": "moderator"}}), encoding="utf-8"
    )

    await client.post("/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=555))
    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": 555, "access_level": "MODERATOR"}


@pytest.mark.asyncio
async def test_whoami_rejects_invalid_session_cookie(client):
    client.cookies.set("cc_session", "garbage.notavalidtoken")

    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_INVALID"


# ─────────────────────────────────────────────────────────────────────────
# Dev-Auth-Bypass
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_auth_bypass_disabled_by_default(client):
    """Ohne explizites Setzen ist der Bypass aus (Deny by default) — kein
    Cookie noetig heisst hier weiterhin 401, nicht automatischer Zugriff."""
    response = await client.get("/api/v1/auth/whoami")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dev_auth_bypass_grants_owner_access_without_session(client, monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))

    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": 1, "access_level": "OWNER"}


@pytest.mark.asyncio
async def test_dev_auth_bypass_ignores_invalid_cookie(client, monkeypatch):
    """Der Bypass greift VOR der Cookie-Pruefung - auch ein kaputter Cookie
    darf den Bypass nicht versehentlich verhindern (Reihenfolge-Regression-
    Schutz)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    client.cookies.set("cc_session", "garbage")

    response = await client.get("/api/v1/auth/whoami")

    assert response.status_code == 200
    assert response.json()["user_id"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Authorization-Verdrahtung in den bestehenden Health-/Findings-Routern
# (Schritt 3, Nachtrag: Endpunkte tatsaechlich geschuetzt, nicht nur die
# Mechanik gebaut) — control_center/routers/health.py fordert mindestens
# AccessLevel.USER, control_center/routers/findings.py mindestens
# AccessLevel.ADMIN (spiegelt die bestehende Telegram-Schwelle).
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/library/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoint_accessible_with_plain_user_session(client, monkeypatch):
    """USER reicht fuer den Health-Endpoint (AccessLevel.USER-Schwelle) —
    Config.LIBRARY_DIR zeigt dank tests/conftest.py::_safe_config_defaults
    bereits auf ein leeres, sicheres tmp-Verzeichnis (200 mit 0 Dateien)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/library/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_findings_endpoint_rejects_plain_user_session(client, monkeypatch):
    """USER reicht NICHT fuer Findings (AccessLevel.ADMIN-Schwelle) —
    403, nicht 401 (Session ist gueltig, Berechtigung reicht nur nicht)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/library/findings")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_findings_endpoint_accessible_with_admin_session(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)  # keine echte Registry beruehren
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/library/findings")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_repair_plan_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/library/repair-plan")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_repair_plan_endpoint_rejects_plain_user_session(client, monkeypatch):
    """Dieselbe AccessLevel.ADMIN-Schwelle wie Findings."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/library/repair-plan")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_repair_plan_endpoint_accessible_with_admin_session(client, monkeypatch):
    """Config.LIBRARY_DIR zeigt dank tests/conftest.py::_safe_config_defaults
    bereits auf ein leeres tmp-Verzeichnis - kein ffmpeg noetig, nur die
    Auth-Verdrahtung wird hier geprueft (Fachlogik: test_control_center_repair_api.py)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/library/repair-plan")

    assert response.status_code == 200
    assert response.json()["candidates"] == []


@pytest.mark.asyncio
async def test_downloads_history_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/downloads/history")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_downloads_history_endpoint_rejects_plain_user_session(client, monkeypatch):
    """Dieselbe AccessLevel.ADMIN-Schwelle wie Findings/Repair-Plan."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/downloads/history")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_downloads_history_endpoint_accessible_with_admin_session(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    monkeypatch.setattr(Config, "DOWNLOAD_HISTORY_DIR", tmp_path)  # keine echte Historie beruehren
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/downloads/history")

    assert response.status_code == 200
    assert response.json() == {"entries": []}


@pytest.mark.asyncio
async def test_statistics_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/statistics/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_statistics_endpoint_accessible_with_plain_user_session(client, monkeypatch, tmp_path):
    """USER reicht (eigene Daten, wie Health) - kein Navidrome-User
    konfiguriert ergibt 404, nicht 401/403 (Fachlogik, nicht Auth)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/statistics/me")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NAVIDROME_USER_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_cross_user_statistics_endpoint_rejects_plain_user_session(client, monkeypatch, tmp_path):
    """Anders als /me braucht GET /{navidrome_username} AccessLevel.ADMIN
    (fremde Hörstatistiken) - 403, nicht 401 (Session ist gueltig, Rolle
    reicht nur nicht)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(StatistikService, "CHARTS_DIR", tmp_path / "stats_charts")
    monkeypatch.setattr(StatistikService, "USER_HISTORY_DIR", tmp_path / "user_histories")
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/statistics/alice")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_cross_user_statistics_endpoint_accessible_with_admin_session(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    monkeypatch.setattr(StatistikService, "CHARTS_DIR", tmp_path / "stats_charts")
    monkeypatch.setattr(StatistikService, "USER_HISTORY_DIR", tmp_path / "user_histories")
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/statistics/alice")

    assert response.status_code == 200
    assert response.json()["navidrome_username"] == "alice"
    assert response.json()["has_data"] is False  # keine Historie fuer "alice" angelegt


@pytest.mark.asyncio
async def test_logs_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/logs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logs_endpoint_rejects_plain_user_session(client, monkeypatch, tmp_path):
    """Dieselbe AccessLevel.ADMIN-Schwelle wie Findings/Repair-Plan/
    Metadata - Logzeilen koennen interne Pfade/Fehlermeldungen
    enthalten."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(Config, "LOG_FILE", tmp_path / "bot.log")
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/logs")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_logs_endpoint_accessible_with_admin_session(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(Config, "LOG_FILE", tmp_path / "bot.log")
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/logs")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_navidrome_status_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/navidrome/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_navidrome_status_endpoint_accessible_with_plain_user_session(client, monkeypatch):
    """USER reicht (reiner Status, wie Health). NavidromeAPI wird gemockt
    (CLAUDE.md Abschnitt 8) - nur die Auth-Verdrahtung wird hier geprueft
    (Fachlogik: test_control_center_navidrome_api.py)."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    monkeypatch.setattr(
        NavidromeAPI, "make_request",
        lambda self, endpoint, params=None: {"subsonic-response": {"status": "failed"}},
    )
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/navidrome/status")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "artist_count": None}


@pytest.mark.asyncio
async def test_admin_users_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_users_endpoint_rejects_plain_user_session(client, monkeypatch):
    """Dieselbe AccessLevel.ADMIN-Schwelle wie Findings/Repair-Plan/Downloads."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/admin/users")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_admin_users_endpoint_accessible_with_admin_session(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)  # keine echten User-Daten beruehren
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/admin/users")

    assert response.status_code == 200
    assert response.json() == {"users": []}


@pytest.mark.asyncio
async def test_findings_accept_endpoint_requires_authentication(client):
    """Erster schreibender Endpunkt — Auth-Verdrahtung wie alle anderen
    ADMIN-Routen (Fachlogik/Origin-Check: test_control_center_findings_api.py)."""
    response = await client.post(
        "/api/v1/library/findings/does-not-exist/accept",
        json={"reason": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_findings_accept_endpoint_rejects_plain_user_session(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.post(
        "/api/v1/library/findings/does-not-exist/accept",
        json={"reason": "x"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_jobs_endpoint_requires_authentication(client):
    response = await client.get("/api/v1/jobs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_jobs_endpoint_rejects_plain_user_session(client, monkeypatch):
    """Dieselbe AccessLevel.ADMIN-Schwelle wie Findings/Repair-Plan/Downloads."""
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: []))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=999)
    )

    response = await client.get("/api/v1/jobs")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_jobs_endpoint_accessible_with_admin_session(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 1))
    monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [777]))
    await client.post(
        "/api/v1/auth/telegram-callback", json=_signed_telegram_payload(user_id=777)
    )

    response = await client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}
