# tests/test_control_center_repair_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/repair-plan — Vertical Slice "Library Repair Preview"
(read-only, kein Executor, keine Datei wird verändert).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router ruft services/library_health/scanner.py::run_scan() (über
control_center/_library_scan.py, identisch zu routers/health.py) und
services/library_repair/planner.py::plan_repairs() unverändert auf —
identischer Aufrufpfad wie scripts/library_repair.py.
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
    # Datei OHNE Artist-Tag -> META_ARTIST_MISSING (deterministisch bekannter
    # Issue-Code, siehe services/library_repair/planner.py Registry).
    _make_m4a(lib / "Artist One" / "Singles" / "2021 - Song A.m4a",
              title="Song A", album="Song A", genre="Pop", year="2021")
    return lib


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Repair-Plan-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
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
async def test_get_repair_plan_maps_known_issue_to_candidate(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    response = await client.get("/api/v1/library/repair-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["plan_schema_version"]
    codes = {c["issue_code"] for c in body["candidates"]}
    assert "META_ARTIST_MISSING" in codes

    candidate = next(c for c in body["candidates"] if c["issue_code"] == "META_ARTIST_MISSING")
    assert candidate["action"] == "METADATA_REPROCESS"
    assert candidate["level"] == "METADATA_REPROCESSING"
    assert candidate["disposition"] == "AUTO_REPAIR"
    assert candidate["requires_external"] is True
    assert candidate["reuses_component"]  # nennt die wiederverwendete Komponente
    assert candidate["is_destructive"] is False


@requires_ffmpeg
@pytest.mark.asyncio
async def test_get_repair_plan_counts_and_totals_are_consistent(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    body = (await client.get("/api/v1/library/repair-plan")).json()

    total_from_counts = sum(body["counts_by_level"].values())
    assert total_from_counts == len(body["candidates"])
    assert body["actionable_total"] + body["manual_review_total"] <= len(body["candidates"])


@pytest.mark.asyncio
async def test_get_repair_plan_response_omits_internal_details(client, test_library, monkeypatch):
    """Master-Prompt Regel 9: lokaler Filesystem-Pfad (library_root) ist
    nicht Teil des API-Contracts — identische Begründung wie bei
    schemas/health.py."""
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    body = (await client.get("/api/v1/library/repair-plan")).json()

    assert "library_root" not in body
    assert set(body.keys()) == {
        "plan_schema_version", "health_score", "counts_by_level",
        "actionable_total", "manual_review_total", "unmapped_issue_codes",
        "candidates",
    }


@pytest.mark.asyncio
async def test_get_repair_plan_404_when_library_root_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "does-not-exist")

    response = await client.get("/api/v1/library/repair-plan")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_ROOT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_repair_plan_500_on_scan_failure(client, test_library, monkeypatch):
    monkeypatch.setattr(Config, "LIBRARY_DIR", test_library)

    import control_center._library_scan as library_scan

    def _boom(*args, **kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(library_scan, "run_scan", _boom)

    response = await client.get("/api/v1/library/repair-plan")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "LIBRARY_HEALTH_SCAN_FAILED"
    assert "kaputt" not in body["error"]["message"]
