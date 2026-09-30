# -*- coding: utf-8 -*-
"""
GET /api/v1/admin/mappings/status — "gespeichert" vs. "Runtime angewendet".
Auth-Muster wie tests/test_control_center_mapping_backups_api.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from config import Config
from services import bot_runtime_snapshot as brs
from services import mapping_admin as ma
from services import mapping_runtime_state as mrs

_SAME_ORIGIN = {"Origin": "http://testserver"}
_URL = "/api/v1/admin/mappings/status"


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(Config, "DATA_DIR", d)
    return d


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch, data_dir):
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    for filename in ma.mapping_file_names().values():
        (mdir / filename).write_text("# Kommentar\nX: 1\n", encoding="utf-8")
    (mdir / "genre_aliases.yaml").write_text("# Aliase\nGENRE_ALIASES:\n  rnb: R&B\n", encoding="utf-8")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mdir)
    return mdir


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app
    import httpx

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _bot_started(mdir: Path) -> None:
    """Simuliert einen laufenden Bot: schreibt den Snapshot mit den beim Start gesehenen Hashes."""
    section = mrs.build_snapshot_section(mrs.hash_mapping_files(mdir), "2026-09-30T08:00:00+00:00")
    brs.write_bot_runtime_snapshot(Config(), {mrs.SECTION_NAME: section}, bot_started_at="2026-09-30T08:00:00+00:00")


def _states(body):
    return {s["mapping_id"]: s["state"] for s in body["statuses"]}


@pytest.mark.asyncio
async def test_without_snapshot_everything_is_unknown(client, mapping_dir):
    r = await client.get(_URL)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot_status"] == "missing" and body["bot_running"] is False
    assert set(_states(body).values()) == {"unknown"}
    assert len(body["statuses"]) == 5


@pytest.mark.asyncio
async def test_status_is_not_mistaken_for_a_mapping_id(client, mapping_dir):
    assert (await client.get(_URL)).status_code == 200
    assert (await client.get("/api/v1/admin/mappings/nicht-erlaubt")).status_code == 404


@pytest.mark.asyncio
async def test_running_bot_with_unchanged_files_is_applied(client, mapping_dir, data_dir):
    _bot_started(mapping_dir)

    body = (await client.get(_URL)).json()

    assert body["snapshot_status"] == "available" and body["bot_running"] is True
    assert body["bot_started_at"] == "2026-09-30T08:00:00+00:00"
    assert set(_states(body).values()) == {"applied"}


@pytest.mark.asyncio
async def test_save_makes_it_pending_and_restore_makes_it_applied_again(client, mapping_dir, data_dir):
    _bot_started(mapping_dir)
    etag = (await client.get("/api/v1/admin/mappings/genre-aliases/entry", params={"key": "x"})).json()["etag"]
    put = await client.put("/api/v1/admin/mappings/genre-aliases", params={"key": "neo soulish"},
                           json={"canonical": "Neo Soul", "etag": etag}, headers=_SAME_ORIGIN)
    assert put.status_code == 200, put.text

    states = _states((await client.get(_URL)).json())
    assert states["genre-aliases"] == "pending_restart"
    assert all(v == "applied" for k, v in states.items() if k != "genre-aliases")

    version_id = (await client.get("/api/v1/admin/mappings/genre-aliases/backups")).json()["versions"][0]["version_id"]
    preview = (await client.post(f"/api/v1/admin/mappings/genre-aliases/backups/{version_id}/preview", headers=_SAME_ORIGIN)).json()
    restore = await client.post(f"/api/v1/admin/mappings/genre-aliases/backups/{version_id}/restore",
                                json={"etag": preview["etag"]}, headers=_SAME_ORIGIN)
    assert restore.status_code == 200, restore.text

    assert _states((await client.get(_URL)).json())["genre-aliases"] == "applied"   # dieselben Bytes wie beim Botstart


@pytest.mark.asyncio
async def test_older_bot_without_section_is_unknown_with_hint(client, mapping_dir, data_dir):
    brs.write_bot_runtime_snapshot(Config(), {}, bot_started_at="2026-09-30T08:00:00+00:00")

    body = (await client.get(_URL)).json()

    assert set(_states(body).values()) == {"unknown"}
    assert "meldet" in body["statuses"][0]["message"]


@pytest.mark.asyncio
async def test_response_has_no_paths_and_only_short_hashes(client, mapping_dir, data_dir):
    _bot_started(mapping_dir)

    text = (await client.get(_URL)).text

    assert str(mapping_dir) not in text and str(data_dir) not in text
    body = (await client.get(_URL)).json()
    assert all(len(s["saved_sha256"]) == 12 for s in body["statuses"])


@pytest.mark.asyncio
async def test_special_channels_carry_the_partial_live_note(client, mapping_dir, data_dir):
    _bot_started(mapping_dir)

    statuses = {s["mapping_id"]: s for s in (await client.get(_URL)).json()["statuses"]}

    assert "je Aufruf" in statuses["special-channels"]["note"]
    assert statuses["genre-aliases"]["note"] is None
