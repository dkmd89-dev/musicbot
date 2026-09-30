# -*- coding: utf-8 -*-
"""
API des YAML-Editors: /api/v1/admin/mappings/{mapping_id}/yaml
(GET Rohtext, POST preview, PUT mit Datei-Etag). Auth-Muster wie
tests/test_control_center_mapping_backups_api.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}
_BASE = "/api/v1/admin/mappings/genre-aliases/yaml"
_TEXT = "# Aliase\nGENRE_ALIASES:\n  rnb: R&B  # klassisch\n"


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


def _text(mdir: Path) -> str:
    return (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_get_returns_raw_text_verbatim_with_etag_and_limit(client, mapping_dir):
    r = await client.get(_BASE)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == _TEXT and body["filename"] == "genre_aliases.yaml"
    assert len(body["etag"]) == 16 and body["max_bytes"] == 512 * 1024 and body["size"] == len(_TEXT.encode())


@pytest.mark.asyncio
async def test_preview_reports_diffs_and_never_writes(client, mapping_dir, data_dir):
    new = "# Aliase\nGENRE_ALIASES:\n  rnb: Rhythm and Blues\n  neo: Neo Soul\n"

    r = await client.post(f"{_BASE}/preview", json={"text": new}, headers=_SAME_ORIGIN)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["change"] == "update" and any("neo" in a for a in body["added"]) and any("rnb" in c for c in body["changed"])
    assert any(line.startswith("+") and "Neo Soul" in line for line in body["text_diff"])
    assert body["etag"] == (await client.get(_BASE)).json()["etag"]
    assert _text(mapping_dir) == _TEXT and not (data_dir / "mapping_backups").exists()


@pytest.mark.asyncio
async def test_put_writes_text_verbatim_creates_backup_and_visual_editor_sees_it(client, mapping_dir, data_dir):
    etag = (await client.get(_BASE)).json()["etag"]
    new = "# Neuer Kopf\nGENRE_ALIASES:\n  rnb: R&B  # bleibt\n  neo soulish: Neo Soul\n"

    r = await client.put(_BASE, json={"text": new, "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] is True and body["bot_reload_required"] is True and "Neustart" in body["message"]
    assert _text(mapping_dir) == new
    assert body["new_etag"] == (await client.get(_BASE)).json()["etag"]
    versions = (await client.get("/api/v1/admin/mappings/genre-aliases/backups")).json()
    assert versions["count"] == 1
    entry = (await client.get("/api/v1/admin/mappings/genre-aliases/entry", params={"key": "neo soulish"})).json()
    assert entry["entry"]["canonical"] == "Neo Soul"


@pytest.mark.asyncio
async def test_put_unchanged_writes_nothing(client, mapping_dir, data_dir):
    etag = (await client.get(_BASE)).json()["etag"]

    r = await client.put(_BASE, json={"text": _TEXT, "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 200 and r.json()["written"] is False and r.json()["unchanged"] is True
    assert not (data_dir / "mapping_backups").exists()


@pytest.mark.asyncio
async def test_stale_etag_is_409_and_changes_nothing(client, mapping_dir):
    etag = (await client.get(_BASE)).json()["etag"]
    mapping_dir.joinpath("genre_aliases.yaml").write_text(_TEXT + "  neu: Pop\n", encoding="utf-8")
    current = _text(mapping_dir)

    r = await client.put(_BASE, json={"text": "GENRE_ALIASES:\n  x: Jazz\n", "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 409 and r.json()["error"]["code"] == "MAPPING_CHANGED"
    assert _text(mapping_dir) == current


@pytest.mark.asyncio
@pytest.mark.parametrize("text,fragment", [
    ("GENRE_ALIASES:\n  a: !!python/object/apply:os.system ['x']\n", "Tags"),
    ("GENRE_ALIASES:\n  a: &x Jazz\n  b: *x\n", "Anker"),
    ("GENRE_ALIASES:\n  a: Jazz\n---\nGENRE_ALIASES: {}\n", "ein YAML-Dokument"),
    ("EVIL:\n  a: Jazz\n", "GENRE_ALIASES"),
    ("GENRE_ALIASES:\n  a: 5\n", "Text sein"),
])
async def test_unsafe_or_invalid_text_is_422_on_preview_and_put_and_never_written(client, mapping_dir, text, fragment):
    etag = (await client.get(_BASE)).json()["etag"]

    p = await client.post(f"{_BASE}/preview", json={"text": text}, headers=_SAME_ORIGIN)
    w = await client.put(_BASE, json={"text": text, "etag": etag}, headers=_SAME_ORIGIN)

    for r in (p, w):
        assert r.status_code == 422 and r.json()["error"]["code"] == "MAPPING_INVALID_INPUT"
        assert fragment in r.json()["error"]["message"]
    assert _text(mapping_dir) == _TEXT


@pytest.mark.asyncio
async def test_oversized_text_is_422(client, mapping_dir):
    big = "GENRE_ALIASES:\n" + "".join(f"  k{n}: Jazz\n" for n in range(60000))

    r = await client.post(f"{_BASE}/preview", json={"text": big}, headers=_SAME_ORIGIN)

    assert r.status_code == 422 and "zu groß" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_body_shape_is_validated(client, mapping_dir):
    assert (await client.post(f"{_BASE}/preview", json={}, headers=_SAME_ORIGIN)).status_code == 422
    assert (await client.put(_BASE, json={"text": _TEXT}, headers=_SAME_ORIGIN)).status_code == 422   # etag fehlt
    assert (await client.post(f"{_BASE}/preview", json={"text": 5}, headers=_SAME_ORIGIN)).status_code == 422


@pytest.mark.asyncio
async def test_writes_require_same_origin(client, mapping_dir):
    assert (await client.post(f"{_BASE}/preview", json={"text": _TEXT})).status_code == 403
    assert (await client.put(_BASE, json={"text": _TEXT, "etag": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_unknown_mapping_id_is_404(client, mapping_dir):
    assert (await client.get("/api/v1/admin/mappings/nicht-erlaubt/yaml")).status_code == 404
    assert (await client.post("/api/v1/admin/mappings/nicht-erlaubt/yaml/preview", json={"text": "a: b"}, headers=_SAME_ORIGIN)).status_code == 404


@pytest.mark.asyncio
async def test_put_returns_503_and_writes_nothing_when_backup_is_not_possible(client, mapping_dir, data_dir):
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.write_text("ich bin eine Datei", encoding="utf-8")
    etag = (await client.get(_BASE)).json()["etag"]

    r = await client.put(_BASE, json={"text": "GENRE_ALIASES:\n  x: Jazz\n", "etag": etag}, headers=_SAME_ORIGIN)

    assert r.status_code == 503 and r.json()["error"]["code"] == "MAPPING_BACKUP_FAILED"
    assert _text(mapping_dir) == _TEXT


@pytest.mark.asyncio
async def test_status_reports_pending_restart_after_raw_save(client, mapping_dir, data_dir):
    from services import bot_runtime_snapshot as brs, mapping_runtime_state as mrs

    section = mrs.build_snapshot_section(mrs.hash_mapping_files(mapping_dir), "2026-09-30T08:00:00+00:00")
    data_dir.mkdir(parents=True, exist_ok=True)
    brs.write_bot_runtime_snapshot(Config(), {mrs.SECTION_NAME: section}, bot_started_at="2026-09-30T08:00:00+00:00")
    etag = (await client.get(_BASE)).json()["etag"]
    await client.put(_BASE, json={"text": "# nur Kommentar geändert\nGENRE_ALIASES:\n  rnb: R&B\n", "etag": etag}, headers=_SAME_ORIGIN)

    states = {s["mapping_id"]: s["state"] for s in (await client.get("/api/v1/admin/mappings/status")).json()["statuses"]}

    assert states["genre-aliases"] == "pending_restart"   # auch reine Formataenderungen sind ein neuer Datei-Stand


@pytest.mark.asyncio
async def test_huge_body_is_rejected_by_content_length_before_parsing(client, mapping_dir):
    huge = '{"text": "' + "a" * (2 * 1024 * 1024) + '"}'

    p = await client.post(f"{_BASE}/preview", content=huge, headers={**_SAME_ORIGIN, "Content-Type": "application/json"})
    w = await client.put(_BASE, content=huge, headers={**_SAME_ORIGIN, "Content-Type": "application/json"})

    for r in (p, w):
        assert r.status_code == 413 and r.json()["error"]["code"] == "MAPPING_YAML_TOO_LARGE"
    assert _text(mapping_dir) == _TEXT
