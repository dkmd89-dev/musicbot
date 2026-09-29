# -*- coding: utf-8 -*-
"""M5 (2026-09-29): /api/v1/admin/mappings/special-channels — API-Tests."""
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
    payload = dict(SPECIAL_CHANNELS=dict(
        Podcast=["Backstage Boxengasse", "Mordlust"],
        Compilations=["Deep Territory"],
        Playlist=["Workout"],
    ))
    (mdir / "special_channel.yaml").write_text(
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


def _read(mdir: Path) -> dict:
    raw = yaml.safe_load((mdir / "special_channel.yaml").read_text(encoding="utf-8"))
    return raw["SPECIAL_CHANNELS"]


@pytest.mark.asyncio
async def test_get_list(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/special-channels")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    names = [c["name"] for c in body["categories"]]
    assert names == ["Podcast", "Compilations", "Playlist"]
    assert len(body["etag"]) == 16


@pytest.mark.asyncio
async def test_get_entry_404(client, mapping_dir):
    r = await client.get(
        "/api/v1/admin/mappings/special-channels/entry",
        params=dict(key="Podcast"),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_preview_requires_same_origin(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_add_channel(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[
            dict(name="Podcast", channels=["Backstage Boxengasse", "Mordlust", "Neu"]),
            dict(name="Compilations", channels=["Deep Territory"]),
            dict(name="Playlist", channels=["Workout"]),
        ]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "update"
    assert any("Podcast: Neu" in a for a in body["added"])
    assert body["comment_warning"] is not None


@pytest.mark.asyncio
async def test_preview_unchanged(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[
            dict(name="Podcast", channels=["Backstage Boxengasse", "Mordlust"]),
            dict(name="Compilations", channels=["Deep Territory"]),
            dict(name="Playlist", channels=["Workout"]),
        ]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200
    assert r.json()["change"] == "unchanged"


@pytest.mark.asyncio
async def test_preview_empty_category_422(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[dict(name="Podcast", channels=[])]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_preview_duplicate_category_casefold_422(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[
            dict(name="Podcast", channels=["A"]),
            dict(name="podcast", channels=["B"]),
        ]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_preview_cross_category_warning(client, mapping_dir):
    r = await client.post(
        "/api/v1/admin/mappings/special-channels/preview",
        json=dict(categories=[
            dict(name="Podcast", channels=["A"]),
            dict(name="Playlist", channels=["A"]),
        ]),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any("A" in w and "Prioritaet" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_put_requires_same_origin(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/special-channels",
        json=dict(categories=[], etag="abc"),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_valid(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/special-channels")
    etag = r.json()["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/special-channels",
        json=dict(
            categories=[
                dict(name="Podcast", channels=["Backstage Boxengasse", "Mordlust"]),
                dict(name="Compilations", channels=["Deep Territory"]),
                dict(name="Playlist", channels=["Workout", "Running Mix"]),
            ],
            etag=etag,
        ),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True
    assert _read(mapping_dir)["Playlist"] == ["Workout", "Running Mix"]


@pytest.mark.asyncio
async def test_put_conflict_409(client, mapping_dir):
    r = await client.put(
        "/api/v1/admin/mappings/special-channels",
        json=dict(categories=[], etag="deadbeefdeadbeef"),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_put_cleanup_dupes(client, mapping_dir):
    """Roh-Datei mit Duplikaten -> PUT mit bereinigter Sicht -> cleanup."""
    payload = dict(SPECIAL_CHANNELS=dict(Podcast=["A", "a", "A"]))
    (mapping_dir / "special_channel.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    r = await client.get("/api/v1/admin/mappings/special-channels")
    body = r.json()
    assert body["categories"][0]["channels"] == ["A"]
    etag = body["etag"]
    r = await client.put(
        "/api/v1/admin/mappings/special-channels",
        json=dict(categories=[dict(name="Podcast", channels=["A"])], etag=etag),
        headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["written"] is True
    assert _read(mapping_dir) == dict(Podcast=["A"])
