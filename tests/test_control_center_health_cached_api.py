# tests/test_control_center_health_cached_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health/cached — Overview-Dashboard v2
(docs/prompts/CONTROL_CENTER_OVERVIEW_V2.md Abschnitt 4/5/24).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der Router
(control_center/routers/health.py::get_cached_library_health()) ruft
control_center/_library_scan.py::load_cached_report() auf, das einen
echten, von services/library_health/scanner.py::run_scan() erzeugten
Report von der Platte liest (Config.DATA_DIR/library_health_report.json)
— identisches Fixture-/Report-Erzeugungsmuster wie
tests/test_control_center_library_overview.py fuer den strukturgleichen
/artists-overview-Endpunkt.

Kernkontrast zu tests/test_control_center_health_api.py (GET /api/v1/
library/health, bestehend, unveraendert): DORT loest jeder Request einen
frischen run_scan() aus. HIER (neuer /health/cached-Endpunkt) wird NIE
gescannt — das ist die zentrale Performance-Anforderung aus Abschnitt 4
des Auftrags und wird unten explizit bewiesen (test_never_calls_run_scan),
nicht nur durch die UI angenommen (Auftrag §24 „Das muss anhand des
tatsaechlichen Codes geprueft werden. Nicht nur anhand der UI.").
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_health.scanner import run_scan

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


def _real_report(library_root: Path) -> dict:
    return run_scan(library_root, supported_extensions=(".m4a",), expected_extension=".m4a")


def _write_report(data_dir: Path, report: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "library_health_report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
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


@requires_ffmpeg
@pytest.mark.asyncio
async def test_fresh_report_returned_not_stale(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/health/cached")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is False
    assert body["library"] == {"files": 2, "artists": 2, "albums": 0}
    assert body["health"]["status"]
    assert body["scan"]["completed_at"] == report["scan"]["completed_at"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_stale_report_still_returned_but_flagged(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    report["scan"]["completed_at"] = old.isoformat()
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/health/cached")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["library"]["files"] == 2  # weiterhin nutzbare Daten, kein Fehler


@pytest.mark.asyncio
async def test_missing_report_returns_404_without_scanning(client, monkeypatch, tmp_path):
    """Kein Report vorhanden -> 404 LIBRARY_REPORT_MISSING, KEIN
    impliziter Scan — kein ffmpeg/Library noetig, beweist gerade die
    Abwesenheit jeglichen Scan-Versuchs (Auftrag §4 Punkt 2)."""
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/health/cached")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "LIBRARY_REPORT_MISSING"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_corrupt_report_file_treated_as_missing(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "library_health_report.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)

    response = await client.get("/api/v1/library/health/cached")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_REPORT_MISSING"


@pytest.mark.asyncio
async def test_never_calls_run_scan(client, monkeypatch, tmp_path):
    """Performance-Kernanforderung Auftrag §4/§24: /health/cached darf
    run_scan()/run_library_scan() unter keinen Umstaenden erreichen — hart
    per Monkeypatch erzwungen, nicht nur durch Beobachtung der Laufzeit
    angenommen.

    Patcht bewusst control_center._library_scan (nicht
    services.library_health.scanner direkt!) — `from ... import run_scan`
    in _library_scan.py bindet den Namen beim Modul-Import in dessen
    EIGENEN Namensraum; ein Patch auf services.library_health.scanner.run_scan
    aendert diese bereits kopierte Bindung nicht mehr (empirisch verifiziert:
    `control_center._library_scan.run_scan is
    services.library_health.scanner.run_scan` ist False nach einem Patch auf
    Letzterem). Identisches, hier korrektes Patch-Ziel wie das bereits
    bestehende tests/test_control_center_health_api.py::
    test_get_library_health_500_on_scan_failure fuer denselben Grund nutzt.
    Zusaetzlich run_library_scan() selbst gepatcht, da das die tatsaechliche
    Funktion ist, die /health aufruft und die bei einer kuenftigen
    Regression faelschlich auch aus /health/cached heraus erreichbar werden
    koennte."""
    import control_center._library_scan as library_scan

    def _boom(*args, **kwargs):
        raise AssertionError("run_scan()/run_library_scan() darf im /health/cached-Pfad nicht aufgerufen werden")

    monkeypatch.setattr(library_scan, "run_scan", _boom)
    monkeypatch.setattr(library_scan, "run_library_scan", _boom)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/health/cached")

    assert response.status_code == 404  # kein Report, aber vor allem: kein Scan-Versuch


@pytest.mark.asyncio
async def test_existing_health_endpoint_unaffected(client, monkeypatch, tmp_path):
    """Regressionsschutz: /health (ohne /cached) bleibt unveraendert an
    run_library_scan() gebunden, dessen Response-Schema (LibraryHealthResponse)
    bekommt durch diese Aenderung KEIN neues Feld (siehe
    schemas/health.py::CachedLibraryHealthResponse, bewusst eigene
    Subklasse statt Erweiterung der Basisklasse)."""
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "does-not-exist")

    response = await client.get("/api/v1/library/health")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_ROOT_NOT_FOUND"
