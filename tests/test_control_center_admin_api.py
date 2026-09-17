# tests/test_control_center_admin_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/admin/users — registrierte Nutzer/Rollen (read-only).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/user_data.py::load_user_data() unverändert auf —
identische Datenquelle wie handlers/admin/user_management_handler.py.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from config import Config


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Admin-Users-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def user_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    return data_dir


def _write_user_data(data_dir, data: dict):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_data.json").write_text(json.dumps(data), encoding="utf-8")


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
async def test_get_users_empty_when_no_file(client, user_data_dir):
    response = await client.get("/api/v1/admin/users")

    assert response.status_code == 200
    assert response.json() == {"users": []}


@pytest.mark.asyncio
async def test_get_users_returns_role_and_navidrome_mapping(client, user_data_dir):
    _write_user_data(user_data_dir, {
        "111": {
            "role": "moderator", "navidrome_user": "alice",
            "created_at": "2026-01-01T00:00:00", "permissions": ["all"],
        },
    })

    response = await client.get("/api/v1/admin/users")

    assert response.status_code == 200
    assert response.json() == {
        "users": [
            {
                "telegram_id": 111, "role": "moderator",
                "navidrome_user": "alice", "created_at": "2026-01-01T00:00:00",
            }
        ]
    }


@pytest.mark.asyncio
async def test_get_users_sorted_by_telegram_id(client, user_data_dir):
    _write_user_data(user_data_dir, {
        "300": {"role": "user"},
        "100": {"role": "admin"},
        "200": {"role": "moderator"},
    })

    body = (await client.get("/api/v1/admin/users")).json()

    assert [u["telegram_id"] for u in body["users"]] == [100, 200, 300]


@pytest.mark.asyncio
async def test_get_users_defaults_missing_fields(client, user_data_dir):
    _write_user_data(user_data_dir, {"111": {}})

    body = (await client.get("/api/v1/admin/users")).json()

    assert body["users"][0] == {
        "telegram_id": 111, "role": "user",
        "navidrome_user": None, "created_at": None,
    }


@pytest.mark.asyncio
async def test_get_users_response_omits_permissions_field(client, user_data_dir):
    """Master-Prompt Regel 9: kein 1:1-Durchreichen des Roh-Dicts —
    "permissions" ist bewusst nicht Teil dieser duennen Anzeige."""
    _write_user_data(user_data_dir, {"111": {"role": "admin", "permissions": ["all"]}})

    body = (await client.get("/api/v1/admin/users")).json()

    assert set(body["users"][0].keys()) == {
        "telegram_id", "role", "navidrome_user", "created_at",
    }
