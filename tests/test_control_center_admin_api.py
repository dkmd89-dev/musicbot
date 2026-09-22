# tests/test_control_center_admin_api.py
# -*- coding: utf-8 -*-
"""
/api/v1/admin/users — Nutzer-/Rollenverwaltung.

GET testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/user_data.py::load_user_data() unverändert auf —
identische Datenquelle wie handlers/admin/user_management_handler.py.

CC-AC-10B: POST/PATCH/DELETE testen denselben echten Pfad über
services/user_admin.py (kein Nachbau der Validierung im Test, siehe
tests/test_user_admin_service.py für die reinen Unit-Tests der
Fachlogik selbst) — hier liegt der Fokus auf HTTP-Statuscodes,
Persistenz-Roundtrip und CSRF-/Origin-Schutz.
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


# ─────────────────────────────────────────────────────────────────────────
# CC-AC-10B: POST/PATCH/DELETE (User Management Write-Parität)
# ─────────────────────────────────────────────────────────────────────────

_SAME_ORIGIN = {"Origin": "http://testserver"}


def _read_user_data(data_dir):
    path = data_dir / "user_data.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class TestCreateUserEndpoint:
    @pytest.mark.asyncio
    async def test_creates_user_and_persists(self, client, user_data_dir):
        response = await client.post(
            "/api/v1/admin/users",
            json={"telegram_id": 444, "navidrome_user": "robin"},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["telegram_id"] == 444
        assert body["role"] == "user"
        assert body["permissions"] == ["all"]
        assert body["navidrome_user"] == "robin"

        assert _read_user_data(user_data_dir)["444"]["navidrome_user"] == "robin"

    @pytest.mark.asyncio
    async def test_rejects_duplicate_user(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"444": {"role": "user"}})

        response = await client.post(
            "/api/v1/admin/users",
            json={"telegram_id": 444, "navidrome_user": "robin"},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_blank_navidrome_user(self, client, user_data_dir):
        response = await client.post(
            "/api/v1/admin/users",
            json={"telegram_id": 444, "navidrome_user": "   "},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, user_data_dir):
        response = await client.post(
            "/api/v1/admin/users", json={"telegram_id": 444, "navidrome_user": "robin"},
        )

        assert response.status_code == 403
        assert _read_user_data(user_data_dir) == {}


class TestUpdateNavidromeUserEndpoint:
    @pytest.mark.asyncio
    async def test_updates_existing_user(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"444": {"role": "user", "navidrome_user": "old"}})

        response = await client.patch(
            "/api/v1/admin/users/444/navidrome",
            json={"navidrome_user": "new"},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        assert response.json()["navidrome_user"] == "new"
        assert _read_user_data(user_data_dir)["444"]["navidrome_user"] == "new"

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404(self, client, user_data_dir):
        response = await client.patch(
            "/api/v1/admin/users/does-not-exist/navidrome",
            json={"navidrome_user": "new"},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 404


class TestUpdateRoleEndpoint:
    @pytest.mark.asyncio
    async def test_dev_bypass_owner_can_change_role(self, client, user_data_dir):
        """Unter CONTROL_CENTER_DEV_AUTH_BYPASS agiert der Request immer als
        config.OWNER_USER_ID (siehe _authenticated-Fixture) — hier also der
        Positivfall "Owner vergibt Rolle"."""
        _write_user_data(user_data_dir, {"333": {"role": "user"}})

        response = await client.patch(
            "/api/v1/admin/users/333/role", json={"role": "moderator"}, headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "moderator"
        assert body["permissions"] == ["moderate", "download"]

    @pytest.mark.asyncio
    async def test_unknown_role_returns_422(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user"}})

        response = await client.patch(
            "/api/v1/admin/users/333/role",
            json={"role": "superadmin_hack"},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 422
        assert _read_user_data(user_data_dir)["333"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user"}})

        response = await client.patch("/api/v1/admin/users/333/role", json={"role": "admin"})

        assert response.status_code == 403
        assert _read_user_data(user_data_dir)["333"]["role"] == "user"


class TestUpdateRoleOwnerGuardSec005:
    """SEC-005-Parität (siehe services/user_admin.py): nur der echte
    Owner darf per API die Owner-Rolle vergeben — mit einer echten,
    signierten Session statt des Dev-Bypass, da dieser immer als Owner
    agiert (siehe TestUpdateRoleEndpoint-Docstring)."""

    TEST_BOT_TOKEN = "123456:TEST-BOT-TOKEN-not-a-real-secret"
    OWNER_ID = 111
    NON_OWNER_ADMIN_ID = 222

    @pytest.fixture(autouse=True)
    def _real_session_as_non_owner_admin(self, monkeypatch):
        from config import Config

        cls = TestUpdateRoleOwnerGuardSec005
        monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
        monkeypatch.setattr(Config, "BOT_TOKEN", property(lambda self: cls.TEST_BOT_TOKEN))
        monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: cls.OWNER_ID))
        monkeypatch.setattr(Config, "ADMIN_USER_IDS", property(lambda self: [cls.NON_OWNER_ADMIN_ID]))

    def _session_cookie(self):
        from control_center.dependencies import create_session_token

        return create_session_token(self.NON_OWNER_ADMIN_ID, bot_token=self.TEST_BOT_TOKEN)

    @pytest.mark.asyncio
    async def test_non_owner_admin_cannot_promote_to_owner(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user"}})
        client.cookies.set("cc_session", self._session_cookie())

        response = await client.patch(
            "/api/v1/admin/users/333/role", json={"role": "owner"}, headers=_SAME_ORIGIN,
        )

        assert response.status_code == 403
        assert _read_user_data(user_data_dir)["333"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_non_owner_admin_can_still_grant_non_owner_roles(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user"}})
        client.cookies.set("cc_session", self._session_cookie())

        response = await client.patch(
            "/api/v1/admin/users/333/role", json={"role": "moderator"}, headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        assert _read_user_data(user_data_dir)["333"]["role"] == "moderator"


class TestUpdatePermissionsEndpoint:
    @pytest.mark.asyncio
    async def test_sets_permission_list(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user", "permissions": []}})

        response = await client.patch(
            "/api/v1/admin/users/333/permissions",
            json={"permissions": ["download", "stats"]},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 200
        assert response.json()["permissions"] == ["download", "stats"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_permission(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"333": {"role": "user", "permissions": []}})

        response = await client.patch(
            "/api/v1/admin/users/333/permissions",
            json={"permissions": ["root"]},
            headers=_SAME_ORIGIN,
        )

        assert response.status_code == 422


class TestDeleteUserEndpoint:
    @pytest.mark.asyncio
    async def test_deletes_user_and_persists(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"222": {"role": "user"}, "333": {"role": "admin"}})

        response = await client.delete("/api/v1/admin/users/222", headers=_SAME_ORIGIN)

        assert response.status_code == 200
        assert response.json() == {"telegram_id": 222, "role": "user"}
        remaining = _read_user_data(user_data_dir)
        assert "222" not in remaining
        assert "333" in remaining

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404(self, client, user_data_dir):
        response = await client.delete("/api/v1/admin/users/does-not-exist", headers=_SAME_ORIGIN)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_rejected_without_origin_header(self, client, user_data_dir):
        _write_user_data(user_data_dir, {"222": {"role": "user"}})

        response = await client.delete("/api/v1/admin/users/222")

        assert response.status_code == 403
        assert "222" in _read_user_data(user_data_dir)
