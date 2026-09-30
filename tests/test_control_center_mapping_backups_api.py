# -*- coding: utf-8 -*-
"""
API der Mapping-Versionen: /api/v1/admin/mappings/{mapping_id}/backups
(Liste, Vorschau, Restore) und das automatische Backup beim PUT.
Auth-Muster wie tests/test_control_center_mapping_admin_api.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}
_BASE = "/api/v1/admin/mappings/genre-aliases"
_TEXT = "# Aliase\nGENRE_ALIASES:\n  rnb: R&B\n"


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", d)
    return d


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch, data_dir):
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    (mdir / "genre_aliases.yaml").write_text(_TEXT, encoding="utf-8")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mdir)
    return mdir


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app
    import httpx

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _put_alias(client, key, canonical):
    etag = (await client.get(f"{_BASE}/entry", params={"key": "__probe__"})).json()["etag"]
    return await client.put(
        _BASE, params={"key": key}, json={"canonical": canonical, "etag": etag}, headers=_SAME_ORIGIN,
    )


def _text(mdir: Path) -> str:
    return (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_list_is_empty_before_first_write(client, mapping_dir):
    r = await client.get(f"{_BASE}/backups")

    assert r.status_code == 200, r.text
    assert r.json()["versions"] == [] and r.json()["count"] == 0
    assert r.json()["max_versions"] == 20


@pytest.mark.asyncio
async def test_put_creates_a_backup_of_the_previous_file(client, mapping_dir, data_dir):
    r = await _put_alias(client, "neo soulish", "Neo Soul")
    assert r.status_code == 200, r.text

    body = (await client.get(f"{_BASE}/backups")).json()

    assert body["count"] == 1
    version = body["versions"][0]
    assert set(version) >= {"version_id", "created_at", "size", "sha256"}
    stored = data_dir / "mapping_backups" / "genre-aliases" / f"{version['version_id']}.yaml"
    assert stored.read_text(encoding="utf-8") == _TEXT


@pytest.mark.asyncio
async def test_preview_and_restore_roundtrip(client, mapping_dir):
    await _put_alias(client, "neo soulish", "Neo Soul")
    version_id = (await client.get(f"{_BASE}/backups")).json()["versions"][0]["version_id"]

    preview = await client.post(f"{_BASE}/backups/{version_id}/preview", headers=_SAME_ORIGIN)
    assert preview.status_code == 200, preview.text
    pbody = preview.json()
    assert pbody["change"] == "update" and pbody["version_id"] == version_id
    assert any("neo soulish" in x for x in pbody["removed"])

    r = await client.post(
        f"{_BASE}/backups/{version_id}/restore", json={"etag": pbody["etag"]}, headers=_SAME_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True and body["bot_reload_required"] is True
    assert "Neustart" in body["message"]
    assert _text(mapping_dir) == _TEXT  # Kommentar ist zurueck
    assert (await client.get(f"{_BASE}/backups")).json()["count"] == 2  # Restore legt selbst eine Version an


@pytest.mark.asyncio
async def test_restore_with_stale_etag_is_409_and_changes_nothing(client, mapping_dir):
    await _put_alias(client, "a", "A1")
    version_id = (await client.get(f"{_BASE}/backups")).json()["versions"][0]["version_id"]
    etag = (await client.post(f"{_BASE}/backups/{version_id}/preview", headers=_SAME_ORIGIN)).json()["etag"]
    await _put_alias(client, "b", "B1")
    current = _text(mapping_dir)

    r = await client.post(f"{_BASE}/backups/{version_id}/restore", json={"etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MAPPING_CHANGED"
    assert _text(mapping_dir) == current


@pytest.mark.asyncio
async def test_restore_requires_etag_in_body(client, mapping_dir):
    await _put_alias(client, "a", "A1")
    version_id = (await client.get(f"{_BASE}/backups")).json()["versions"][0]["version_id"]

    r = await client.post(f"{_BASE}/backups/{version_id}/restore", json={}, headers=_SAME_ORIGIN)

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_write_endpoints_require_same_origin(client, mapping_dir):
    await _put_alias(client, "a", "A1")
    version_id = (await client.get(f"{_BASE}/backups")).json()["versions"][0]["version_id"]

    assert (await client.post(f"{_BASE}/backups/{version_id}/preview")).status_code == 403
    assert (await client.post(f"{_BASE}/backups/{version_id}/restore", json={"etag": "x"})).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["20990101T000000_000000Z", "nicht-gueltig", "%2e%2e", "2026"])
async def test_unknown_or_malformed_version_is_404(client, mapping_dir, bad):
    r = await client.post(f"{_BASE}/backups/{bad}/preview", headers=_SAME_ORIGIN)

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "MAPPING_BACKUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_version_id_with_path_separator_never_reaches_the_filesystem(client, mapping_dir):
    # Ein Schraegstrich passt nicht auf den Routen-Parameter -> 404 ohne Dateizugriff.
    r = await client.post(f"{_BASE}/backups/%2E%2E%2Fetc/preview", headers=_SAME_ORIGIN)

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unknown_mapping_id_is_404(client, mapping_dir):
    r = await client.get("/api/v1/admin/mappings/nicht-erlaubt/backups")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_corrupt_version_is_422_and_file_unchanged(client, mapping_dir, data_dir):
    await _put_alias(client, "a", "A1")
    folder = data_dir / "mapping_backups" / "genre-aliases"
    (folder / "20200101T000000_000000Z.yaml").write_text("GENRE_ALIASES: [kaputt: :", encoding="utf-8")
    current = _text(mapping_dir)

    r = await client.post(f"{_BASE}/backups/20200101T000000_000000Z/preview", headers=_SAME_ORIGIN)

    assert r.status_code == 422
    assert _text(mapping_dir) == current


@pytest.mark.asyncio
async def test_put_returns_503_and_writes_nothing_when_backup_is_not_possible(client, mapping_dir, data_dir):
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.write_text("ich bin eine Datei", encoding="utf-8")  # DATA_DIR unbrauchbar -> kein Backup moeglich

    r = await _put_alias(client, "a", "A1")

    assert r.status_code == 503
    assert r.json()["error"]["code"] == "MAPPING_BACKUP_FAILED"
    assert _text(mapping_dir) == _TEXT


@pytest.mark.asyncio
async def test_filters_and_special_channels_puts_also_create_backups(client, tmp_path, monkeypatch, data_dir):
    mdir = tmp_path / "mapping2"
    mdir.mkdir()
    (mdir / "genre_filters.yaml").write_text("IGNORE_SECONDARY:\n- rock\n", encoding="utf-8")
    (mdir / "special_channel.yaml").write_text("SPECIAL_CHANNELS:\n  Podcast:\n  - A\n", encoding="utf-8")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mdir)

    f_etag = (await client.get("/api/v1/admin/mappings/genre-filters")).json()["etag"]
    await client.put("/api/v1/admin/mappings/genre-filters", json={"values": ["rock", "indie"], "etag": f_etag}, headers=_SAME_ORIGIN)
    s_etag = (await client.get("/api/v1/admin/mappings/special-channels")).json()["etag"]
    await client.put(
        "/api/v1/admin/mappings/special-channels",
        json={"categories": [{"name": "Podcast", "channels": ["A", "B"]}], "etag": s_etag}, headers=_SAME_ORIGIN,
    )

    for mapping_id in ("genre-filters", "special-channels"):
        assert (await client.get(f"/api/v1/admin/mappings/{mapping_id}/backups")).json()["count"] == 1
