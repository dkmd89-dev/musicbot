# tests/test_control_center_navidrome_actions.py
# -*- coding: utf-8 -*-
"""
CC-UI Navidrome N5 — Favoriten setzen/entfernen, Scrobble, Songs zu einer
Playlist hinzufügen, plus das neue Feld `starred` in den Antworten.

Testet den echten Router (CLAUDE.md Abschnitt 7); Navidrome ist über
NavidromeAPI.make_request ersetzt (Abschnitt 8). Schreibende Endpunkte:
Zugriffsstufe USER + Origin-Check (wie Playlist-CRUD). Fehlertexte und URLs von
Navidrome dürfen nie in der Antwort landen.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.clients.navidrome_api import NavidromeAPI

_ORIGIN = {"Origin": "http://testserver"}
_OK = {"subsonic-response": {"status": "ok"}}
_LEAK = "Wrong username or password u=alice p=SECRETPW"


def _failed(code: int) -> dict:
    return {"subsonic-response": {"status": "failed", "error": {"code": code, "message": _LEAK}}}


@pytest.fixture
def authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
def navidrome(monkeypatch):
    """Ersetzt make_request; `calls` enthält (endpoint, params), `responses` je Endpunkt."""
    state = {"calls": [], "responses": {}}

    def _fake(self, endpoint, params=None):
        state["calls"].append((endpoint, dict(params or {})))
        return state["responses"].get(endpoint, _OK)

    monkeypatch.setattr(NavidromeAPI, "make_request", _fake)
    return state


# ─────────────────────────────────────────────────────────────────────────
# Favoriten setzen / entfernen
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,param", [("song", "id"), ("album", "albumId"), ("artist", "artistId")])
async def test_favorite_put_and_delete_map_to_star_and_unstar(client, authenticated, navidrome, kind, param):
    added = await client.put(f"/api/v1/navidrome/favorites/{kind}/abc-123_X", headers=_ORIGIN)
    removed = await client.delete(f"/api/v1/navidrome/favorites/{kind}/abc-123_X", headers=_ORIGIN)

    assert added.status_code == 200 and added.json() == {"success": True, "kind": kind, "id": "abc-123_X", "starred": True}
    assert removed.status_code == 200 and removed.json()["starred"] is False
    assert navidrome["calls"] == [("star", {param: "abc-123_X"}), ("unstar", {param: "abc-123_X"})]


@pytest.mark.asyncio
async def test_favorite_rejects_unknown_kind_and_malformed_ids_without_calling_navidrome(client, authenticated, navidrome):
    bad_kind = await client.put("/api/v1/navidrome/favorites/playlist/abc", headers=_ORIGIN)
    assert bad_kind.status_code == 422

    for bad_id in ("a b", "a;b", "a.b", "x" * 65):
        response = await client.put(f"/api/v1/navidrome/favorites/song/{bad_id}", headers=_ORIGIN)
        assert response.status_code == 422, bad_id
    assert navidrome["calls"] == []


@pytest.mark.asyncio
async def test_favorite_requires_login_and_same_origin(client, navidrome, monkeypatch):
    anonymous = await client.put("/api/v1/navidrome/favorites/song/abc", headers=_ORIGIN)
    assert anonymous.status_code == 401

    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    for headers in ({}, {"Origin": "http://evil.example"}):
        response = await client.put("/api/v1/navidrome/favorites/song/abc", headers=headers)
        assert response.status_code == 403
        response = await client.delete("/api/v1/navidrome/favorites/song/abc", headers=headers)
        assert response.status_code == 403
    assert navidrome["calls"] == []


@pytest.mark.asyncio
async def test_favorite_subsonic_failure_maps_to_404_or_502_without_leaking_text(client, authenticated, navidrome):
    navidrome["responses"]["star"] = _failed(70)
    not_found = await client.put("/api/v1/navidrome/favorites/song/abc", headers=_ORIGIN)
    assert not_found.status_code == 404 and "SECRETPW" not in not_found.text

    navidrome["responses"]["star"] = _failed(40)
    other = await client.put("/api/v1/navidrome/favorites/song/abc", headers=_ORIGIN)
    assert other.status_code == 502 and "SECRETPW" not in other.text and "alice" not in other.text


# ─────────────────────────────────────────────────────────────────────────
# Scrobble
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scrobble_now_playing_and_submission(client, authenticated, navidrome):
    now = await client.post("/api/v1/navidrome/scrobble/s1", json={"submission": False}, headers=_ORIGIN)
    counted = await client.post("/api/v1/navidrome/scrobble/s1", json={"submission": True}, headers=_ORIGIN)
    default = await client.post("/api/v1/navidrome/scrobble/s1", json={}, headers=_ORIGIN)

    assert now.status_code == counted.status_code == default.status_code == 200
    assert now.json() == {"success": True}
    assert navidrome["calls"] == [
        ("scrobble", {"id": "s1", "submission": "false"}),
        ("scrobble", {"id": "s1", "submission": "true"}),
        ("scrobble", {"id": "s1", "submission": "true"}),           # Standard = gezählte Wiedergabe
    ]


@pytest.mark.asyncio
async def test_scrobble_validation_auth_and_failure(client, navidrome, monkeypatch):
    anonymous = await client.post("/api/v1/navidrome/scrobble/s1", json={}, headers=_ORIGIN)
    assert anonymous.status_code == 401

    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    assert (await client.post("/api/v1/navidrome/scrobble/s1", json={})).status_code == 403          # Origin fehlt
    assert (await client.post("/api/v1/navidrome/scrobble/a.b", json={}, headers=_ORIGIN)).status_code == 422
    assert (await client.post("/api/v1/navidrome/scrobble/s1", json={"submission": "vielleicht"}, headers=_ORIGIN)).status_code == 422
    assert navidrome["calls"] == []

    navidrome["responses"]["scrobble"] = _failed(0)
    failed = await client.post("/api/v1/navidrome/scrobble/s1", json={}, headers=_ORIGIN)
    assert failed.status_code == 502 and "SECRETPW" not in failed.text


# ─────────────────────────────────────────────────────────────────────────
# Songs zu einer Playlist hinzufügen
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_songs_to_playlist(client, authenticated, navidrome):
    response = await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": ["s1", "s2"]}, headers=_ORIGIN)

    assert response.status_code == 200 and response.json() == {"success": True, "playlist_id": "p1", "added": 2}
    assert navidrome["calls"] == [("updatePlaylist", {"playlistId": "p1", "songIdToAdd": ["s1", "s2"]})]


@pytest.mark.asyncio
@pytest.mark.parametrize("song_ids", [[], ["s1", "a b"], ["../x"], [f"s{i}" for i in range(501)]])
async def test_add_songs_rejects_bad_input_without_calling_navidrome(client, authenticated, navidrome, song_ids):
    response = await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": song_ids}, headers=_ORIGIN)

    assert response.status_code == 422 and navidrome["calls"] == []


@pytest.mark.asyncio
async def test_add_songs_maximum_is_accepted_and_playlist_id_is_validated(client, authenticated, navidrome):
    ok = await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": [f"s{i}" for i in range(500)]}, headers=_ORIGIN)
    assert ok.status_code == 200 and ok.json()["added"] == 500

    bad = await client.post("/api/v1/navidrome/playlists/p 1/songs", json={"song_ids": ["s1"]}, headers=_ORIGIN)
    assert bad.status_code == 422 and len(navidrome["calls"]) == 1


@pytest.mark.asyncio
async def test_add_songs_requires_login_origin_and_reports_failure(client, navidrome, monkeypatch):
    assert (await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": ["s1"]}, headers=_ORIGIN)).status_code == 401

    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    assert (await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": ["s1"]})).status_code == 403

    navidrome["responses"]["updatePlaylist"] = _failed(70)
    missing = await client.post("/api/v1/navidrome/playlists/p1/songs", json={"song_ids": ["s1"]}, headers=_ORIGIN)
    assert missing.status_code == 404 and "SECRETPW" not in missing.text


# ─────────────────────────────────────────────────────────────────────────
# `starred` in den Antworten (Subsonic liefert das Feld nur bei Favoriten)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_starred_flag_in_album_song_artist_and_favorites_responses(client, authenticated, navidrome):
    stamp = "2026-09-29T10:00:00Z"
    navidrome["responses"].update({
        "getAlbum": {"subsonic-response": {"album": {
            "id": "a1", "name": "Album", "starred": stamp,
            "song": [{"id": "s1", "title": "Gemerkt", "starred": stamp}, {"id": "s2", "title": "Normal"}]}}},
        "getSong": {"subsonic-response": {"song": {"id": "s1", "title": "Gemerkt", "starred": stamp}}},
        "getArtist": {"subsonic-response": {"artist": {"id": "ar1", "name": "Artist", "starred": stamp,
                                                        "album": [{"id": "a1", "name": "Album"}]}}},
        "getStarred2": {"subsonic-response": {"starred2": {"song": [{"id": "s1", "title": "Gemerkt", "starred": stamp}]}}},
    })
    album = (await client.get("/api/v1/navidrome/albums/a1")).json()
    assert album["starred"] is True and [s["starred"] for s in album["songs"]] == [True, False]
    assert (await client.get("/api/v1/navidrome/songs/s1")).json()["starred"] is True
    artist = (await client.get("/api/v1/navidrome/artists/ar1")).json()
    assert artist["starred"] is True and artist["albums"][0]["starred"] is False
    assert (await client.get("/api/v1/navidrome/favorites")).json()["songs"][0]["starred"] is True
