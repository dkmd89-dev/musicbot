# -*- coding: utf-8 -*-
"""M2 (2026-09-29): /api/v1/admin/mappings/genre-aliases — API-Tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}


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
    (mdir / "genre_aliases.yaml").write_text(
        yaml.safe_dump(
            {"GENRE_ALIASES": {
                "deutschrap": "Deutschrap",
                "german rap": "Deutschrap",
            }},
            allow_unicode=True, sort_keys=False,
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
    return yaml.safe_load((mdir / "genre_aliases.yaml").read_text(encoding="utf-8"))["GENRE_ALIASES"]


@pytest.mark.asyncio
async def test_list_returns_entries(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/genre-aliases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["mapping_id"] == "genre-aliases"
    keys = {e["key"] for e in body["entries"]}
    assert keys == {"deutschrap", "german rap"}


@pytest.mark.asyncio
async def test_get_entry_returns_etag(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-aliases/entry",
        params={"key": "german rap"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["entry"]["canonical"] == "Deutschrap"
    assert len(body["etag"]) == 16


@pytest.mark.asyncio
async def test_get_missing_entry(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-aliases/entry",
        params={"key": "nicht-vorhanden"},
    )
    assert r.status_code == 200
    assert r.json()["exists"] is False


@pytest.mark.asyncio
async def test_preview_requires_same_origin(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-aliases/preview",
        params={"key": "neu"},
        json={"canonical": "Pop"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_valid_create(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-aliases/preview",
        params={"key": "new-alias"},
        json={"canonical": "Pop"},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "create"
    assert body["canonical"] == "Pop"
    assert body["comment_warning"] is not None  # Kommentarverlust-Warnung


@pytest.mark.asyncio
async def test_preview_invalid_canonical_422(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-aliases/preview",
        params={"key": "neu"},
        json={"canonical": ""},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_requires_same_origin(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-aliases",
        params={"key": "neu"},
        json={"canonical": "Pop", "etag": "abc"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_valid_writes_and_returns_reload_required(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-aliases/entry",
        params={"key": "neu"},
    )
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/genre-aliases",
        params={"key": "neu"},
        json={"canonical": "Pop", "etag": etag},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True
    assert body["bot_reload_required"] is True
    raw = _read(mapping_dir)
    assert raw["neu"] == "Pop"


@pytest.mark.asyncio
async def test_put_conflict_409(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-aliases",
        params={"key": "neu"},
        json={"canonical": "Pop", "etag": "deadbeefdeadbeef"},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_put_unchanged_no_write(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-aliases/entry",
        params={"key": "german rap"},
    )
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/genre-aliases",
        params={"key": "german rap"},
        json={"canonical": "Deutschrap", "etag": etag},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200
    assert r.json()["written"] is False
    assert r.json()["unchanged"] is True
