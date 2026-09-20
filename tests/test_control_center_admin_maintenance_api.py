# tests/test_control_center_admin_maintenance_api.py
# -*- coding: utf-8 -*-
"""
GET/POST /api/v1/admin/maintenance/{action}/preview|execute — Master-
Prompt Abschnitt 22 "ADMINISTRATION" (Maintenance).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_repair/maintenance_service.py::preview_*()/
execute_*() unverändert auf — identischer Aufrufpfad wie die bestehende
Telegram-"🧹 Library-Wartung"-Fähigkeit (ARCH-032). Gegen echte,
isolierte m4a-Testdateien (nie die Produktionsbibliothek), identisches
Muster wie tests/test_library_repair_maintenance_service.py und
tests/test_control_center_metadata_actions_api.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mutagen.mp4 import MP4, MP4FreeForm

import services.library_repair.run_tracking as rt
from config import Config

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")

_SAME_ORIGIN = {"Origin": "http://testserver"}


def _m4a(path: Path, *, genre=None, artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    a = MP4(path)
    a["\xa9nam"] = ["T"]
    if genre:
        a["\xa9gen"] = [genre]
    if artist:
        a["\xa9ART"] = artist if isinstance(artist, list) else [artist]
    a.save()


def _set_legacy_genre(path: Path, value: str) -> None:
    a = MP4(path)
    a["----:com.apple.iTunes:GENRE"] = [MP4FreeForm(value.encode("utf-8"))]
    a.save()


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Isoliert Lock/Journal/Run-History - niemals die echten
    Produktionsdateien beruehren."""
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
# artist-casing
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_casing_preview_and_execute(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, artist="bausa")
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"bausa": "Bausa"}), encoding="utf-8",
    )

    preview = await client.get(
        "/api/v1/admin/maintenance/artist-casing/preview", params={"artist": "Bausa"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9ART"] == ["bausa"]  # Preview veraendert nichts

    response = await client.post(
        "/api/v1/admin/maintenance/artist-casing/execute",
        params={"artist": "Bausa"}, headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9ART"] == ["Bausa"]
    assert rt.is_repair_running() is False


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_casing_execute_rejected_without_origin_header(client, lib, mapping_dir):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p, artist="bausa")
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"bausa": "Bausa"}), encoding="utf-8",
    )

    response = await client.post(
        "/api/v1/admin/maintenance/artist-casing/execute", params={"artist": "Bausa"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"
    assert MP4(p).tags["\xa9ART"] == ["bausa"]


# ─────────────────────────────────────────────────────────────────────────
# legacy-genre-cleanup
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_legacy_genre_cleanup_preview_and_execute(client, lib):
    p = lib / "Filow" / "Singles" / "a.m4a"
    _m4a(p, genre="Pop")
    _set_legacy_genre(p, "Pop")

    preview = await client.get(
        "/api/v1/admin/maintenance/legacy-genre-cleanup/preview", params={"artist": "Filow"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1

    response = await client.post(
        "/api/v1/admin/maintenance/legacy-genre-cleanup/execute",
        params={"artist": "Filow"}, headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags.get("----:com.apple.iTunes:GENRE") is None


# ─────────────────────────────────────────────────────────────────────────
# artist-rename (manueller Zielwert)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_preview_and_execute(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")

    preview = await client.get(
        "/api/v1/admin/maintenance/artist-rename/preview",
        params={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9ART"] == ["Macloud"]

    response = await client.post(
        "/api/v1/admin/maintenance/artist-rename/execute",
        json={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9ART"] == ["Miksu & Macloud"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_rejects_empty_new_value(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")

    response = await client.post(
        "/api/v1/admin/maintenance/artist-rename/execute",
        json={"artist": "Macloud", "new_artist": "   "},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MAINTENANCE_VALIDATION_ERROR"
    assert MP4(p).tags["\xa9ART"] == ["Macloud"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_rename_execute_409_when_lock_already_held(client, lib):
    p = lib / "Macloud" / "Singles" / "a.m4a"
    _m4a(p, artist="Macloud")
    rt.acquire_repair_lock()
    try:
        response = await client.post(
            "/api/v1/admin/maintenance/artist-rename/execute",
            json={"artist": "Macloud", "new_artist": "Miksu & Macloud"},
            headers=_SAME_ORIGIN,
        )
    finally:
        rt.release_repair_lock()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPAIR_ALREADY_RUNNING"


# ─────────────────────────────────────────────────────────────────────────
# title-edit (manueller Zielwert, genau ein Track)
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_preview_and_execute(client, lib):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    preview = await client.get(
        "/api/v1/admin/maintenance/title-edit/preview",
        params={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
    )
    assert preview.status_code == 200
    assert preview.json()["changed_count"] == 1
    assert MP4(p).tags["\xa9nam"] == ["T"]

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert MP4(p).tags["\xa9nam"] == ["Neuer Titel"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_no_automatic_title_cleanup(client, lib):
    """Master-Prompt/ARCH-Vorgabe: kein automatischer TitleCleaner auf
    den manuellen Zielwert."""
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": '"Titel" prod. XY'},
        headers=_SAME_ORIGIN,
    )

    assert response.status_code == 200
    assert MP4(p).tags["\xa9nam"] == ['"Titel" prod. XY']


@requires_ffmpeg
@pytest.mark.asyncio
async def test_title_edit_execute_rejected_without_origin_header(client, lib):
    p = lib / "Bausa" / "Singles" / "a.m4a"
    _m4a(p)

    response = await client.post(
        "/api/v1/admin/maintenance/title-edit/execute",
        json={"artist": "Bausa", "rel_path": "Bausa/Singles/a.m4a", "new_title": "Neuer Titel"},
    )

    assert response.status_code == 403
    assert MP4(p).tags["\xa9nam"] == ["T"]
