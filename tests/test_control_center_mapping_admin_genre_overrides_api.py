# -*- coding: utf-8 -*-
"""M3 (2026-09-29): /api/v1/admin/mappings/genre-overrides — API-Tests."""
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
    (mdir / "genre_overrides.yaml").write_text(
        yaml.safe_dump(
            {"GENRE_OVERRIDES": {
                "hiphop": "Hip Hop",
                "Hip-Hop": "Hip Hop",
                "hip-hop": "Rap",
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
    return yaml.safe_load((mdir / "genre_overrides.yaml").read_text(encoding="utf-8"))["GENRE_OVERRIDES"]


@pytest.mark.asyncio
async def test_list_returns_entries(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/genre-overrides")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3


@pytest.mark.asyncio
async def test_get_entry_exact_case(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-overrides/entry",
        params={"key": "Hip-Hop"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["entry"]["override"] == "Hip Hop"


@pytest.mark.asyncio
async def test_get_entry_lower_variant(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/genre-overrides/entry",
        params={"key": "hip-hop"},
    )
    assert r.status_code == 200
    assert r.json()["entry"]["override"] == "Rap"


@pytest.mark.asyncio
async def test_put_update_exact_case_isolation(client, mapping_dir):
    """PUT 'Hip-Hop' → darf 'hip-hop' nicht anfassen."""
    r = await client.get(
        "/api/v1/admin/mappings/genre-overrides/entry",
        params={"key": "Hip-Hop"},
    )
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/genre-overrides",
        params={"key": "Hip-Hop"},
        json={"override": "Rock", "etag": etag},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    raw = _read(mapping_dir)
    assert raw["Hip-Hop"] == "Rock"
    assert raw["hip-hop"] == "Rap"


@pytest.mark.asyncio
async def test_put_requires_same_origin(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-overrides",
        params={"key": "neu"},
        json={"override": "Pop", "etag": "abc"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_create(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-overrides/preview",
        params={"key": "NeuKey"},
        json={"override": "Pop"},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "create"
    assert body["override"] == "Pop"
    assert body["comment_warning"] is not None


@pytest.mark.asyncio
async def test_put_conflict_409(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/genre-overrides",
        params={"key": "hiphop"},
        json={"override": "Rap", "etag": "deadbeefdeadbeef"},
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_preview_carries_warning_for_uppercase_key(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/genre-overrides/preview",
        params={"key": "Trip Hop"}, json={"override": "Downtempo"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    assert any("Laufzeit" in w for w in r.json()["warnings"])
