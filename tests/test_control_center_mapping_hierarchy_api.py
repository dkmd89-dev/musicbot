# -*- coding: utf-8 -*-
"""M6: /api/v1/admin/mappings/genre-hierarchy — API-Tests (Liste, Preview, Save,
Konflikt, Validierung, Versionen, kein YAML-Editor, Runtime-Status)."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from config import Config
from services import bot_runtime_snapshot as brs
from services import mapping_runtime_state as mrs

_SAME_ORIGIN = {"Origin": "http://testserver"}
_URL = "/api/v1/admin/mappings/genre-hierarchy"
_REAL = Path(__file__).resolve().parent.parent / "mapping" / "genre_hierarchy.yaml"


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
    (mdir / "genre_hierarchy.yaml").write_text(_REAL.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mdir)
    return mdir


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app
    import httpx

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _bytes(mdir: Path) -> bytes:
    return (mdir / "genre_hierarchy.yaml").read_bytes()


async def _state(client):
    body = (await client.get(_URL)).json()
    return [{"genre": e["genre"], "parent": e["parent"]} for e in body["entries"]], body["etag"]


def _reparent(entries, genre, parent):
    return [dict(e, parent=parent) if e["genre"] == genre else e for e in entries]


# ── Lesen ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_tree_with_depth_children_and_etag(client, mapping_dir):
    r = await client.get(_URL)

    assert r.status_code == 200, r.text
    body = r.json()
    by = {e["genre"]: e for e in body["entries"]}
    assert body["count"] == 187 and len(body["etag"]) == 16 and body["warnings"] == []
    assert by["Hip Hop"]["parent"] is None and by["Hip Hop"]["depth"] == 0
    assert by["Drill"] == {"genre": "Drill", "parent": "Hip Hop", "depth": 1, "children": 4}


@pytest.mark.asyncio
async def test_entry_endpoint_does_not_exist_for_the_tree(client, mapping_dir):
    r = await client.get(f"{_URL}/entry", params={"key": "Drill"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "MAPPING_NO_ENTRIES"


@pytest.mark.asyncio
async def test_missing_file_is_503(client, mapping_dir):
    (mapping_dir / "genre_hierarchy.yaml").unlink()
    assert (await client.get(_URL)).status_code == 503


# ── Preview ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_shows_parent_change_with_affected_children_and_never_writes(client, mapping_dir):
    entries, etag = await _state(client)
    before = _bytes(mapping_dir)

    r = await client.post(f"{_URL}/preview", json={"entries": _reparent(entries, "Hardstyle", "Drill")}, headers=_SAME_ORIGIN)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "update" and body["etag"] == etag
    assert body["changed"] == ["Hardstyle: Electronic → Drill"]
    change = body["changes"][0]
    assert change["kind"] == "parent_changed" and change["old_depth"] == 1 and change["new_depth"] == 2
    assert change["affected_count"] == 8 and "Rawstyle" in change["affected"]
    assert any("Genre-Priorität" in w for w in body["warnings"])
    assert body["comment_warning"] is None
    assert _bytes(mapping_dir) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate, message", [
    (lambda e: _reparent(e, "Hip Hop", "UK Drill"), "Zyklus"),
    (lambda e: _reparent(e, "Drill", "Drill"), "eigener Eltern-Eintrag"),
    (lambda e: _reparent(e, "Drill", "Nicht Vorhanden"), "existiert nicht"),
    (lambda e: e + [{"genre": "Drill", "parent": None}], "Doppeltes Genre"),
    (lambda e: e + [{"genre": "", "parent": None}], "nicht leer"),
    (lambda e: [x for x in e if x["genre"] != "Drill"], "'Drill' existiert nicht"),
])
async def test_invalid_trees_are_422_with_a_readable_message(client, mapping_dir, mutate, message):
    entries, _ = await _state(client)
    before = _bytes(mapping_dir)

    r = await client.post(f"{_URL}/preview", json={"entries": mutate(entries)}, headers=_SAME_ORIGIN)

    assert r.status_code == 422, r.text
    assert message in r.json()["error"]["message"]
    assert _bytes(mapping_dir) == before


# ── Save ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_writes_only_the_changed_line_and_is_honest_about_the_restart(client, mapping_dir):
    entries, etag = await _state(client)
    before = _bytes(mapping_dir).decode("utf-8")

    r = await client.put(_URL, json={"entries": _reparent(entries, "Drill", "Deutschrap"), "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True and body["bot_reload_required"] is True
    assert "Bot-Neustart erforderlich" in body["message"] and "aktualisiert" not in body["message"]
    assert body["new_etag"] != etag
    after = _bytes(mapping_dir).decode("utf-8")
    assert after == before.replace("  Drill: Hip Hop\n", "  Drill: Deutschrap\n")
    assert (await client.get(_URL)).json()["etag"] == body["new_etag"]


@pytest.mark.asyncio
async def test_put_unchanged_writes_nothing(client, mapping_dir):
    entries, etag = await _state(client)
    before = _bytes(mapping_dir)

    r = await client.put(_URL, json={"entries": entries, "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 200 and r.json()["unchanged"] is True and r.json()["bot_reload_required"] is False
    assert _bytes(mapping_dir) == before


@pytest.mark.asyncio
async def test_stale_etag_is_409_and_changes_nothing(client, mapping_dir):
    entries, etag = await _state(client)
    (mapping_dir / "genre_hierarchy.yaml").write_text(_bytes(mapping_dir).decode("utf-8") + "  Ska: Rock\n", encoding="utf-8")
    before = _bytes(mapping_dir)

    r = await client.put(_URL, json={"entries": _reparent(entries, "Drill", "Deutschrap"), "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 409 and r.json()["error"]["code"] == "MAPPING_CHANGED"
    assert _bytes(mapping_dir) == before


@pytest.mark.asyncio
async def test_invalid_put_is_422_and_leaves_the_file_untouched(client, mapping_dir):
    entries, etag = await _state(client)
    before = _bytes(mapping_dir)

    r = await client.put(_URL, json={"entries": _reparent(entries, "Hip Hop", "UK Drill"), "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 422 and "Zyklus" in r.json()["error"]["message"]
    assert _bytes(mapping_dir) == before


@pytest.mark.asyncio
async def test_put_requires_etag_and_same_origin(client, mapping_dir):
    entries, etag = await _state(client)
    before = _bytes(mapping_dir)

    no_etag = await client.put(_URL, json={"entries": entries}, headers=_SAME_ORIGIN)
    no_origin = await client.put(_URL, json={"entries": entries, "etag": etag})

    assert no_etag.status_code == 422
    assert no_origin.status_code == 403
    assert _bytes(mapping_dir) == before


@pytest.mark.asyncio
async def test_put_creates_a_backup_and_restore_brings_the_old_tree_back(client, mapping_dir):
    entries, etag = await _state(client)
    original = _bytes(mapping_dir)
    put = await client.put(_URL, json={"entries": _reparent(entries, "Drill", "Deutschrap"), "etag": etag}, headers=_SAME_ORIGIN)
    assert put.status_code == 200

    versions = (await client.get(f"{_URL}/backups")).json()["versions"]
    assert len(versions) == 1
    version_id = versions[0]["version_id"]
    preview = await client.post(f"{_URL}/backups/{version_id}/preview", headers=_SAME_ORIGIN)
    assert preview.status_code == 200 and preview.json()["changed"] == ["Drill: Deutschrap → Hip Hop"]
    restore = await client.post(f"{_URL}/backups/{version_id}/restore", json={"etag": preview.json()["etag"]}, headers=_SAME_ORIGIN)

    assert restore.status_code == 200, restore.text
    assert _bytes(mapping_dir) == original


@pytest.mark.asyncio
async def test_restoring_an_invalid_tree_is_422_and_changes_nothing(client, mapping_dir, data_dir):
    from services import mapping_backups

    bad = "GENRE_HIERARCHY:\n  R: null\n  A: B\n  B: A\n"
    mapping_backups.snapshot(data_dir / "mapping_backups", "genre-hierarchy", _write(mapping_dir, bad))
    (mapping_dir / "genre_hierarchy.yaml").write_text(_REAL.read_text(encoding="utf-8"), encoding="utf-8")
    before = _bytes(mapping_dir)
    version_id = (await client.get(f"{_URL}/backups")).json()["versions"][0]["version_id"]

    r = await client.post(f"{_URL}/backups/{version_id}/preview", headers=_SAME_ORIGIN)

    assert r.status_code == 422 and "Zyklus" in r.json()["error"]["message"]
    assert _bytes(mapping_dir) == before


def _write(mdir: Path, text: str) -> Path:
    path = mdir / "genre_hierarchy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ── Kein Rohtext-Editor fuer den Baum ────────────────────────────────────


@pytest.mark.asyncio
async def test_the_tree_has_no_yaml_editor(client, mapping_dir):
    before = _bytes(mapping_dir)
    text = _REAL.read_text(encoding="utf-8")

    get = await client.get(f"{_URL}/yaml")
    preview = await client.post(f"{_URL}/yaml/preview", json={"text": text}, headers=_SAME_ORIGIN)
    put = await client.put(f"{_URL}/yaml", json={"text": text + "\n# x\n", "etag": "e"}, headers=_SAME_ORIGIN)

    assert (get.status_code, preview.status_code, put.status_code) == (404, 404, 404)
    assert _bytes(mapping_dir) == before


# ── Runtime-Status ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_saved_hierarchy_is_pending_restart_until_the_bot_reloads(client, mapping_dir):
    section = mrs.build_snapshot_section(mrs.hash_mapping_files(mapping_dir), "2026-09-30T08:00:00+00:00")
    brs.write_bot_runtime_snapshot(Config(), {mrs.SECTION_NAME: section}, bot_started_at="2026-09-30T08:00:00+00:00")
    statuses = {s["mapping_id"]: s["state"] for s in (await client.get("/api/v1/admin/mappings/status")).json()["statuses"]}
    assert statuses["genre-hierarchy"] == "applied"

    entries, etag = await _state(client)
    await client.put(_URL, json={"entries": _reparent(entries, "Drill", "Deutschrap"), "etag": etag}, headers=_SAME_ORIGIN)

    statuses = {s["mapping_id"]: s["state"] for s in (await client.get("/api/v1/admin/mappings/status")).json()["statuses"]}
    assert statuses["genre-hierarchy"] == "pending_restart"
