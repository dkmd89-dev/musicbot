# -*- coding: utf-8 -*-
"""M4 (2026-09-29): /api/v1/admin/mappings/genre-filters — API-Tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from config import Config

_SAME_ORIGIN = dict(Origin="http://testserver")


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
    payload = dict(IGNORE_SECONDARY=["rock", "indie", "pop"])
    (mdir / "genre_filters.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
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


def _read(mdir: Path) -> list:
    return yaml.safe_load((mdir / "genre_filters.yaml").read_text(encoding="utf-8"))["IGNORE_SECONDARY"]


@pytest.mark.asyncio
async def test_get_list(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/genre-filters")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert body["values"] == ["rock", "indie", "pop"]
    assert len(body["etag"]) == 16


@pytest.mark.asyncio
async def test_get_list_normalizes_and_warns(client, mapping_dir):
    payload = dict(IGNORE_SECONDARY=["rock", "Rock", "ROCK", "indie"])
    (mapping_dir / "genre_filters.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    r = await client.get("/api/v1/admin/mappings/genre-filters")
    assert r.status_code == 200
    body = r.json()
    assert body["values"] == ["rock", "indie"]
    assert any("Duplikate" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_get_entry_404(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-filters/entry",
        params=dict(key="rock"),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_requires_same_origin(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-filters/preview",
        json=dict(values=["rock"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_add(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-filters/preview",
        json=dict(values=["rock", "indie", "pop", "jazz"]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "update"
    assert body["added"] == ["jazz"]
    assert body["removed"] == []
    assert body["comment_warning"] is not None


@pytest.mark.asyncio
async def test_preview_unchanged(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-filters/preview",
        json=dict(values=["rock", "indie", "pop"]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200
    assert r.json()["change"] == "unchanged"


@pytest.mark.asyncio
async def test_preview_invalid_422(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-filters/preview",
        json=dict(values=["", "rock"]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_requires_same_origin(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-filters",
        json=dict(values=["rock"], etag="abc"),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_valid(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/genre-filters")
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/genre-filters",
        json=dict(values=["rock", "indie"], etag=etag),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True
    assert body["values"] == ["rock", "indie"]
    assert _read(mapping_dir) == ["rock", "indie"]


@pytest.mark.asyncio
async def test_put_conflict_409(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-filters",
        json=dict(values=["rock"], etag="deadbeefdeadbeef"),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_put_cleanup(client, mapping_dir):
    """Datei mit Duplikaten -> PUT mit bereits-bereinigtem Ziel -> cleanup."""
    payload = dict(IGNORE_SECONDARY=["rock", "Rock", "ROCK", "indie"])
    (mapping_dir / "genre_filters.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    r = await client.get("/api/v1/admin/mappings/genre-filters")
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/genre-filters",
        json=dict(values=["rock", "indie"], etag=etag),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["written"] is True
    assert _read(mapping_dir) == ["rock", "indie"]
