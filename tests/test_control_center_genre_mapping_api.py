# -*- coding: utf-8 -*-
"""GET/POST-preview/PUT /api/v1/library/artists/{artist}/genre-mapping.

Echter Produktionspfad: Router -> services/library_repair/genre.py -> echte
artist_genre.yaml in einem tmp-Verzeichnis (Config.GENRE_MAPPING_DIR).
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import yaml

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}

_YAML = """ARTIST_GENRE_MAP:
  Dua Lipa:
    primary: Pop
    secondary:
    - Dance Pop
    - Disco
    description: Britische Popsaengerin
  apache 207:
    primary: Hip Hop
    secondary:
    - Deutschrap
    - Trap
    description: Rapper
"""


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "mapping"
    d.mkdir()
    (d / "artist_genre.yaml").write_text(_YAML, encoding="utf-8")
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", d)
    return d


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _map(d: Path) -> dict:
    return yaml.safe_load((d / "artist_genre.yaml").read_text(encoding="utf-8"))["ARTIST_GENRE_MAP"]


BASE = "/api/v1/library/artists"


# ── GET ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_structured_entry_etag_and_known_genres(client, mapping_dir):
    r = await client.get(f"{BASE}/apache 207/genre-mapping")
    assert r.status_code == 200
    b = r.json()
    assert b["exists"] is True
    assert b["entry"] == {"key": "apache 207", "primary": "Hip Hop", "secondary": ["Deutschrap", "Trap"],
                          "description": "Rapper"}
    assert b["etag"] and "Disco" in b["known_genres"] and "Trap" in b["known_genres"]


@pytest.mark.asyncio
async def test_get_is_case_insensitive_and_returns_the_real_key(client, mapping_dir):
    b = (await client.get(f"{BASE}/dua lipa/genre-mapping")).json()
    assert b["entry"]["key"] == "Dua Lipa"


@pytest.mark.asyncio
async def test_get_unknown_artist_exists_false_with_etag(client, mapping_dir):
    b = (await client.get(f"{BASE}/Metallica/genre-mapping")).json()
    assert b["exists"] is False and b["entry"] is None and b["etag"]


@pytest.mark.asyncio
async def test_get_missing_mapping_file_is_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", tmp_path / "leer")
    r = await client.get(f"{BASE}/x/genre-mapping")
    assert r.status_code == 503 and "GENRE_MAPPING_UNAVAILABLE" in r.text


# ── Preview ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preview_shows_removed_added_and_writes_nothing(client, mapping_dir):
    before = (mapping_dir / "artist_genre.yaml").read_bytes()
    r = await client.post(f"{BASE}/apache 207/genre-mapping/preview", headers=_SAME_ORIGIN,
                          json={"primary": "Hip Hop", "secondary": ["Deutschrap", "Pop Rap"]})
    assert r.status_code == 200
    b = r.json()
    assert b["change"] == "update" and b["removed"] == ["Trap"] and b["added"] == ["Pop Rap"]
    assert b["primary_changed"] is False and b["existing"]["secondary"] == ["Deutschrap", "Trap"]
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


@pytest.mark.asyncio
async def test_preview_normalizes_input_and_warns_about_unknown_genres(client, mapping_dir):
    b = (await client.post(f"{BASE}/apache 207/genre-mapping/preview", headers=_SAME_ORIGIN,
                           json={"primary": "  Hip Hop ", "secondary": ["Trapp", "trapp", "", "Hip hop"]})).json()
    assert b["primary"] == "Hip Hop" and b["secondary"] == ["Trapp"]
    assert len(b["warnings"]) == 1 and "Trapp" in b["warnings"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"primary": "", "secondary": []},
    {"primary": "Pop; Rock", "secondary": []},
    {"primary": "Pop", "secondary": ["a\nb"]},
    {"primary": "x" * 101, "secondary": []},
])
async def test_preview_rejects_invalid_input_with_422(client, mapping_dir, body):
    r = await client.post(f"{BASE}/apache 207/genre-mapping/preview", headers=_SAME_ORIGIN, json=body)
    assert r.status_code == 422 and "GENRE_INPUT_INVALID" in r.text


@pytest.mark.asyncio
async def test_preview_requires_same_origin(client, mapping_dir):
    r = await client.post(f"{BASE}/apache 207/genre-mapping/preview", json={"primary": "Pop", "secondary": []})
    assert r.status_code == 403


# ── PUT ────────────────────────────────────────────────────────────────

async def _etag(client, artist):
    return (await client.get(f"{BASE}/{artist}/genre-mapping")).json()["etag"]


@pytest.mark.asyncio
async def test_put_edits_primary_and_secondary_and_preserves_other_entries(client, mapping_dir):
    before = _map(mapping_dir)
    r = await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN, json={
        "primary": "Pop", "secondary": ["Deutschrap", "Pop Rap"], "etag": await _etag(client, "apache 207")})
    assert r.status_code == 200
    b = r.json()
    assert b["written"] is True and b["bot_reload_required"] is True and "Bot-Neustart" in b["message"]
    assert b["new_etag"] != b["etag"]
    after = _map(mapping_dir)
    assert after["apache 207"]["primary"] == "Pop" and after["apache 207"]["secondary"] == ["Deutschrap", "Pop Rap"]
    assert after["apache 207"]["description"] == "Rapper"
    assert after["Dua Lipa"] == before["Dua Lipa"] and list(after) == list(before)


@pytest.mark.asyncio
async def test_put_wrong_secondary_removed_correct_one_set_for_a_mixed_case_artist(client, mapping_dir):
    """Der Kernfall des Auftrags + die Regression: 'Dua Lipa' hat gemischte Schreibweise."""
    r = await client.put(f"{BASE}/Dua Lipa/genre-mapping", headers=_SAME_ORIGIN, json={
        "primary": "Pop", "secondary": ["Dance Pop", "Synthpop"], "etag": await _etag(client, "Dua Lipa")})
    assert r.status_code == 200 and r.json()["removed"] == ["Disco"] and r.json()["added"] == ["Synthpop"]
    m = _map(mapping_dir)
    assert [k for k in m if k.casefold() == "dua lipa"] == ["Dua Lipa"]        # kein Duplikat-Key
    assert m["Dua Lipa"]["secondary"] == ["Dance Pop", "Synthpop"]


@pytest.mark.asyncio
async def test_put_creates_a_new_artist_with_control_center_description(client, mapping_dir):
    r = await client.put(f"{BASE}/Metallica/genre-mapping", headers=_SAME_ORIGIN, json={
        "primary": "Heavy Metal", "secondary": ["Thrash Metal"], "etag": await _etag(client, "Metallica")})
    assert r.status_code == 200 and r.json()["change"] == "create"
    e = _map(mapping_dir)["metallica"]
    assert e["primary"] == "Heavy Metal" and e["description"] == "Manuell gesetzt via Control Center"


@pytest.mark.asyncio
async def test_put_stale_etag_is_409_and_writes_nothing(client, mapping_dir):
    etag = await _etag(client, "apache 207")
    await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN,
                     json={"primary": "Hip Hop", "secondary": ["Trap"], "etag": etag})   # 1. Aenderung
    before = (mapping_dir / "artist_genre.yaml").read_bytes()

    r = await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN,
                         json={"primary": "Pop", "secondary": [], "etag": etag})           # veralteter Etag

    assert r.status_code == 409 and "GENRE_MAPPING_CHANGED" in r.text
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


@pytest.mark.asyncio
async def test_put_unchanged_writes_nothing(client, mapping_dir):
    before = (mapping_dir / "artist_genre.yaml").read_bytes()
    r = await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN, json={
        "primary": "Hip Hop", "secondary": ["Deutschrap", "Trap"], "etag": await _etag(client, "apache 207")})
    b = r.json()
    assert r.status_code == 200 and b["written"] is False and b["bot_reload_required"] is False
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


@pytest.mark.asyncio
async def test_put_invalid_input_is_422_and_writes_nothing(client, mapping_dir):
    before = (mapping_dir / "artist_genre.yaml").read_bytes()
    r = await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN, json={
        "primary": "Pop; Rock", "secondary": [], "etag": await _etag(client, "apache 207")})
    assert r.status_code == 422
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


@pytest.mark.asyncio
async def test_put_requires_etag_and_same_origin(client, mapping_dir):
    assert (await client.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN,
                             json={"primary": "Pop", "secondary": []})).status_code == 422       # etag Pflicht
    assert (await client.put(f"{BASE}/apache 207/genre-mapping",
                             json={"primary": "Pop", "secondary": [], "etag": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_endpoints_require_authentication(mapping_dir, monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    from control_center.app import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver") as c:
        assert (await c.get(f"{BASE}/apache 207/genre-mapping")).status_code == 401
        assert (await c.post(f"{BASE}/apache 207/genre-mapping/preview", headers=_SAME_ORIGIN,
                             json={"primary": "Pop", "secondary": []})).status_code == 401
        assert (await c.put(f"{BASE}/apache 207/genre-mapping", headers=_SAME_ORIGIN,
                            json={"primary": "Pop", "secondary": [], "etag": "x"})).status_code == 401


@pytest.mark.asyncio
async def test_existing_genre_preview_and_set_genre_routes_are_unshadowed(client, mapping_dir):
    """Neue Routen duerfen die bestehenden /genre-preview- und /set-genre-Routen nicht stoeren."""
    r = await client.get(f"{BASE}/Unbekannt/genre-preview")
    assert r.status_code == 404 and "ARTIST_NOT_IN_MAPPING" in r.text
