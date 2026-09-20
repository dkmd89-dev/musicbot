# tests/test_control_center_metadata_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/tracks, /artists, /albums — read-only Metadata-
Browser (Master-Prompt Abschnitt 7, erster Schritt).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_health/scanner.py::run_scan() (über
control_center/_library_scan.py, identisch zu routers/health.py/
repair.py) unveraendert auf.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _make_m4a(path: Path, seconds=1, **tags):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    if tags:
        from mutagen.mp4 import MP4

        a = MP4(path)
        for k, v in tags.items():
            a[{"artist": "\xa9ART", "title": "\xa9nam", "album": "\xa9alb",
               "genre": "\xa9gen", "year": "\xa9day"}[k]] = [v]
        a.save()


@pytest.fixture
def test_library(tmp_path):
    lib = tmp_path / "library"
    _make_m4a(lib / "Artist One" / "Album A" / "01 - Song A.m4a",
              artist="Artist One", title="Song A", album="Album A",
              genre="Pop", year="2021")
    _make_m4a(lib / "Artist One" / "Album A" / "02 - Song B.m4a",
              artist="Artist One", title="Song B", album="Album A",
              genre="Pop", year="2021")
    _make_m4a(lib / "Artist Two" / "Album B" / "01 - Song C.m4a",
              artist="Artist Two", title="Song C", album="Album B",
              genre="Rock", year="2022")
    return lib


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prueft die Metadata-Browser-Fachlogik, nicht die
    Authentifizierung (dafuer: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/tracks
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_tracks_returns_metadata_for_each_file(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/tracks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["tracks"]) == 3
    titles = {t["title"] for t in body["tracks"]}
    assert titles == {"Song A", "Song B", "Song C"}
    song_a = next(t for t in body["tracks"] if t["title"] == "Song A")
    assert song_a["artist"] == "Artist One"
    assert song_a["album"] == "Album A"
    assert song_a["genre"] == "Pop"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_tracks_respects_pagination(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/tracks", params={"limit": 2, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["tracks"]) == 2

    response2 = await client.get("/api/v1/library/tracks", params={"limit": 2, "offset": 2})
    assert len(response2.json()["tracks"]) == 1


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_tracks_response_omits_internal_details(client, test_library, monkeypatch):
    """Master-Prompt Regel 9: interne Analyse-/Klassifikationsdetails
    (states/path_classification) sind kein Teil des API-Contracts."""
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    body = (await client.get("/api/v1/library/tracks")).json()

    track = body["tracks"][0]
    assert "states" not in track
    assert "path_classification" not in track


@pytest.mark.asyncio
async def test_get_tracks_404_when_library_root_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "does-not-exist")

    response = await client.get("/api/v1/library/tracks")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_ROOT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_tracks_empty_library_returns_empty_list(client, tmp_path, monkeypatch):
    lib = tmp_path / "empty_library"
    lib.mkdir()
    monkeypatch.setattr(Config, "LIBRARY_DIR", lib)

    body = (await client.get("/api/v1/library/tracks")).json()

    assert body["total"] == 0
    assert body["tracks"] == []


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_tracks_rejects_invalid_limit(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/tracks", params={"limit": 0})

    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/artists
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_artists_groups_by_artist_directory(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/artists")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    by_name = {a["artist"]: a for a in body["artists"]}
    assert by_name["Artist One"]["file_count"] == 2
    assert by_name["Artist One"]["album_count"] == 1
    assert by_name["Artist Two"]["file_count"] == 1
    assert "health_score" in by_name["Artist One"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_artists_respects_pagination(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/artists", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["artists"]) == 1


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/albums
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_albums_groups_by_artist_and_album(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/albums")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    album_a = next(a for a in body["albums"] if a["album"] == "Album A")
    assert album_a["artist"] == "Artist One"
    assert album_a["file_count"] == 2


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_albums_respects_pagination(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/albums", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["albums"]) == 1


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/mapping-summary — "Mapping anzeigen"
#
# Testet gegen die ECHTEN Mapping-Dateien in mapping/ (nicht isoliert/
# gemockt) - identisches Prinzip wie tests/test_genre_processor.py, das
# denselben GenreMapper bereits gegen config.GENRE_MAPPING_DIR
# charakterisiert (CLAUDE.md Abschnitt 10: Mapping-Dateien sind
# Fachlogik). GenreMapper aendert nichts an den Dateien (reine
# Lesefunktion), daher unbedenklich. Exakte Zahlen werden bewusst NICHT
# geprueft (die Mapping-Dateien aendern sich im echten Projekt) - nur
# strukturelle Eigenschaften.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_mapping_summary_returns_real_mapping_counts(client):
    response = await client.get("/api/v1/library/mapping-summary")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "artists", "channels", "hierarchy", "rules", "aliases", "overrides",
        "unique_primary_genres",
    }
    for value in body.values():
        assert isinstance(value, int)
        assert value >= 0
    # Die echte mapping/-Registry ist nicht leer (Produktions-Mappingdaten).
    assert body["artists"] > 0
    assert body["unique_primary_genres"] > 0


@pytest.mark.asyncio
async def test_get_mapping_summary_omits_runtime_cache_stats(client):
    """Nur Mapping-Inhalt, keine Laufzeit-Query-/Cache-Statistiken
    (queries/cache_hits/fuzzy_matches/rule_matches/cache_hit_rate) - die
    waeren fuer eine frische Anfrage nicht aussagekraeftig."""
    body = (await client.get("/api/v1/library/mapping-summary")).json()

    assert "queries" not in body
    assert "cache_hit_rate" not in body
