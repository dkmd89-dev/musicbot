# -*- coding: utf-8 -*-
"""M1 (2026-09-29): /api/v1/admin/mappings/{mapping_id} — API-Tests.

Auth-Muster und Fixtures identisch zu
tests/test_control_center_admin_maintenance_api.py (CONTROL_CENTER_DEV_AUTH_BYPASS,
autouse _authenticated, asgi-Client).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}


# ── Fixtures (angelehnt an test_control_center_admin_maintenance_api.py) ──


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(
        Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True)
    )


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "channel_genre.yaml").write_text(
        yaml.safe_dump(
            {"CHANNEL_GENRE_MAP": {
                "Kontor.TV": {
                    "primary": "Electronic",
                    "secondary": ["Dance"],
                    "description": "x",
                },
            }},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mdir)
    return mdir


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app
    import httpx
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _read(mdir: Path) -> dict:
    raw = yaml.safe_load((mdir / "channel_genre.yaml").read_text(encoding="utf-8"))
    return raw["CHANNEL_GENRE_MAP"]


# ── Liste ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_entries(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/channel-genre")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["bot_reload_required"] is True
    assert body["entries"][0]["key"] == "Kontor.TV"


@pytest.mark.asyncio
async def test_unknown_mapping_id_404(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/unknown-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_attempt_404(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/..%2Fetc%2Fpasswd")
    assert r.status_code == 404


# ── Einzeleintrag ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_entry_returns_etag(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/channel-genre/entry",
        params={"channel": "kontor.tv"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exists"] is True
    assert body["entry"]["primary"] == "Electronic"
    assert len(body["etag"]) == 16


@pytest.mark.asyncio
async def test_get_entry_missing(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/channel-genre/entry",
        params={"channel": "nicht-vorhanden"},
    )
    assert r.status_code == 200
    assert r.json()["exists"] is False


# ── Preview ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_requires_same_origin(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/channel-genre/preview",
        params={"channel": "Neu"},
        json={"primary": "Pop", "secondary": []},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_valid(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/channel-genre/preview",
        params={"channel": "Neu"},
        json={"primary": "Pop", "secondary": ["Dance"]},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "create"
    assert body["added"] == ["Dance"]


@pytest.mark.asyncio
async def test_preview_invalid_raises_422(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/channel-genre/preview",
        params={"channel": "Neu"},
        json={"primary": "", "secondary": []},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 422


# ── Save ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_requires_same_origin(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/channel-genre",
        params={"channel": "Neu"},
        json={"primary": "Pop", "secondary": [], "etag": "abc"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_valid_writes_and_returns_reload_required(client, mapping_dir):
    # Etag ermitteln
    r = await client.get(
        "/api/v1/admin/mappings/channel-genre/entry",
        params={"channel": "Neu"},
    )
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/channel-genre",
        params={"channel": "Neu"},
        json={"primary": "Pop", "secondary": ["Dance"], "etag": etag},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True
    assert body["bot_reload_required"] is True
    raw = _read(mapping_dir)
    assert "neu" in raw


@pytest.mark.asyncio
async def test_put_conflict_409(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/channel-genre",
        params={"channel": "Neu"},
        json={"primary": "Pop", "secondary": [], "etag": "deadbeefdeadbeef"},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_put_unchanged_does_not_write(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/channel-genre/entry",
        params={"channel": "Kontor.TV"},
    )
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/channel-genre",
        params={"channel": "Kontor.TV"},
        json={"primary": "Electronic", "secondary": ["Dance"], "description": "x", "etag": etag},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["written"] is False
    assert r.json()["unchanged"] is True
