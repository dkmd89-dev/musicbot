# tests/test_control_center_health_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health — Vertical Slice "Health/Dashboard", Schritt 1.

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7: Tests
gegen die echte Implementierung, nicht gegen eine im Testfile
nachgebaute Kopie): der Router ruft services/library_health/scanner.py::
run_scan() unveraendert auf (identischer Aufrufpfad wie
scripts/library_health_check.py, siehe tests/test_library_health_
readonly_safety.py fuer dasselbe Fixture-Muster mit echten
ffmpeg-generierten m4a-Dateien).

Config.LIBRARY_DIR zeigt dank tests/conftest.py::_safe_config_defaults
bereits session-weit auf ein leeres, sicheres tmp-Verzeichnis - fuer
Tests mit echtem Scan-Inhalt wird es hier zusaetzlich testlokal per
monkeypatch auf eine eigene kleine Test-Library umgebogen (identisches
Muster wie in conftest.py selbst).

httpx.AsyncClient(transport=httpx.ASGITransport(...)) statt
starlette.testclient.TestClient: die im Environment installierte
fastapi/starlette-Version (0.103.2/0.27.0, absichtlich hier belassen wegen
einer Versionsbindung von spotdl 4.4.3 <0.104/<0.24 im selben, ungetrennten
Python-Environment, siehe docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md)
ist mit der bereits installierten httpx 0.28.1 nicht kompatibel (TestClient
reicht intern ein von httpx 0.28 entferntes `app=`-Kwarg durch).
httpx.ASGITransport ist die von httpx selbst empfohlene, versionsunabhaengige
Alternative — sie ist reinrassig async, daher async Client + async Tests
(@pytest.mark.asyncio, bereits etabliertes Projektmuster, siehe
tests/test_doctor_runner.py).
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
    _make_m4a(lib / "Artist One" / "Singles" / "2021 - Song A.m4a",
              artist="Artist One", title="Song A", album="Song A", genre="Pop", year="2021")
    _make_m4a(lib / "Artist Two" / "Singles" / "2020 - Bare.m4a")
    return lib


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft den Health-Endpoint selbst, nicht die seit
    Schritt 3 davorliegende Authentifizierung (dafür: tests/test_control_center_auth.py)
    — Dev-Auth-Bypass steht dafür genau bereit (control_center/dependencies.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_library_health_returns_mapped_report(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/health")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"]
    assert body["scanner_version"]
    assert body["library"] == {"files": 2, "artists": 2, "albums": 0}
    assert body["health"]["status"]
    assert body["statistics"]["total_files"] == 2


@pytest.mark.asyncio
async def test_get_library_health_response_omits_internal_details(client, test_library, monkeypatch):
    """Master-Prompt Regel 9: interne Implementierungsdetails (lokaler
    Filesystem-Pfad, Roh-Issue-/Datei-Listen) sind nicht Teil des
    API-Contracts dieser duennen Dashboard-Response."""
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/health")
    body = response.json()

    assert "root" not in body["library"]
    assert "weights" not in body["health"]
    assert set(body.keys()) == {
        "schema_version", "scanner_version", "scan", "library", "health", "statistics",
    }


@pytest.mark.asyncio
async def test_get_library_health_404_when_library_root_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "does-not-exist")

    response = await client.get("/api/v1/library/health")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "LIBRARY_ROOT_NOT_FOUND"
    assert body["error"]["request_id"]


@pytest.mark.asyncio
async def test_get_library_health_500_on_scan_failure(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    import control_center.routers.health as health_router

    def _boom(*args, **kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(health_router, "run_scan", _boom)

    response = await client.get("/api/v1/library/health")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "LIBRARY_HEALTH_SCAN_FAILED"
    assert "kaputt" not in body["error"]["message"]  # interne Details nicht im Client-Response
