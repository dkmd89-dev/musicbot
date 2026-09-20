# tests/test_control_center_metadata_actions_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/artists/{artist}/genre-preview,
POST /api/v1/library/artists/{artist}/set-genre — erste schreibende
Fähigkeit in Metadata Management (Master-Prompt Abschnitt 7, "Metadata
bearbeiten").

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_repair/maintenance_service.py::
preview_set_genre()/execute_set_genre() unverändert auf — identischer
Aufrufpfad wie die bestehende Telegram-/CLI-"Genre setzen"-Fähigkeit
(ARCH-032). Gegen echte, isolierte m4a-Testdateien (nie die
Produktions-Library), identisches Muster wie
tests/test_library_repair_maintenance_service.py.
"""

from __future__ import annotations

import shutil
import subprocess
import yaml
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mutagen.mp4 import MP4

import services.library_repair.run_tracking as rt
from config import Config

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")

_SAME_ORIGIN = {"Origin": "http://testserver"}


def _m4a(path: Path, *, genre=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    a = MP4(path)
    a["\xa9nam"] = ["Song"]
    if genre:
        a["\xa9gen"] = [genre]
    a.save()


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prueft die set-genre-Fachlogik, nicht die
    Authentifizierung (dafuer: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Isoliert Lock/Journal/Run-History (services/library_repair/
    run_tracking.py) - niemals die echten Produktionsdateien beruehren."""
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "library"
    monkeypatch.setattr(Config, "LIBRARY_DIR", d)
    return d


@pytest.fixture
def mapping_dir(tmp_path, monkeypatch):
    d = tmp_path / "mapping"
    d.mkdir()
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", d)
    return d


def _write_mapping(mapping_dir, artist: str, primary_genre: str):
    (mapping_dir / "artist_genre.yaml").write_text(
        yaml.safe_dump({"ARTIST_GENRE_MAP": {artist: {"primary": primary_genre}}}),
        encoding="utf-8",
    )


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
# GET /api/v1/library/artists/{artist}/genre-preview
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_genre_preview_shows_diff_without_changing_file(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, genre="OldGenre")
    _write_mapping(mapping_dir, "Bausa", "Deutschrap")

    response = await client.get("/api/v1/library/artists/Bausa/genre-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["artist"] == "Bausa"
    assert body["target_count"] == 1
    assert body["changed_count"] == 1
    outcome = body["outcomes"][0]
    assert outcome["before"]["genre"] == "OldGenre"
    assert outcome["after"]["genre"] == "Deutschrap"
    # Datei tatsaechlich unveraendert (reine Vorschau):
    assert MP4(p).tags["\xa9gen"] == ["OldGenre"]


@pytest.mark.asyncio
async def test_genre_preview_404_when_artist_not_in_mapping(client, lib, mapping_dir):
    _write_mapping(mapping_dir, "SomeoneElse", "Pop")

    response = await client.get("/api/v1/library/artists/Unknown/genre-preview")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIST_NOT_IN_MAPPING"


# ─────────────────────────────────────────────────────────────────────────
# POST /api/v1/library/artists/{artist}/set-genre
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_set_genre_writes_tag_and_records_run(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, genre="OldGenre")
    _write_mapping(mapping_dir, "Bausa", "Deutschrap")

    response = await client.post(
        "/api/v1/library/artists/Bausa/set-genre", headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["success_count"] == 1
    assert MP4(p).tags["\xa9gen"] == ["Deutschrap"]

    history = rt.load_repair_history()
    assert len(history) == 1
    assert history[0]["kind"] == rt.KIND_MAINTENANCE
    assert rt.is_repair_running() is False  # Lock wieder freigegeben


@pytest.mark.asyncio
async def test_set_genre_404_when_artist_not_in_mapping(client, lib, mapping_dir):
    response = await client.post(
        "/api/v1/library/artists/Unknown/set-genre", headers=_SAME_ORIGIN,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIST_NOT_IN_MAPPING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_set_genre_409_when_lock_already_held(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, genre="OldGenre")
    _write_mapping(mapping_dir, "Bausa", "Deutschrap")
    rt.acquire_repair_lock()  # simuliert einen bereits laufenden Telegram-/CLI-Lauf
    try:
        response = await client.post(
            "/api/v1/library/artists/Bausa/set-genre", headers=_SAME_ORIGIN,
        )
    finally:
        rt.release_repair_lock()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPAIR_ALREADY_RUNNING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_set_genre_rejected_without_origin_header(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, genre="OldGenre")
    _write_mapping(mapping_dir, "Bausa", "Deutschrap")

    response = await client.post("/api/v1/library/artists/Bausa/set-genre")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"
    # Datei unveraendert - CSRF-Check greift vor jeder Ausfuehrung:
    assert MP4(p).tags["\xa9gen"] == ["OldGenre"]
