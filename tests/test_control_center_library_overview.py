# tests/test_control_center_library_overview.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/artists-overview, GET /api/v1/library/artists-overview/{artist}
— Library Artist-Centric UX (CC-AC-1, library_artist_centric_UX.txt).

Testet den echten Produktionscode-Pfad (CLAUDE.md §7): der Router ruft
control_center/_library_scan.py::load_cached_report() auf, das einen
echten, von services/library_health/scanner.py::run_scan() erzeugten
Report von der Platte liest (Config.DATA_DIR/library_health_report.json)
— identische Reportstruktur wie scripts/library_health_check.py sie
tatsächlich schreibt (json.dumps(run_scan(...))), hier direkt über
run_scan() erzeugt statt über das CLI-Skript, um den Report deterministisch
und ohne Subprozess in tmp_path abzulegen.

Kernkontrast zu test_control_center_metadata_api.py (GET /api/v1/library/
artists, bestehend, unverändert): DORT löst jeder Request einen frischen
run_scan() aus. HIER (neue artists-overview-Endpunkte) wird NIE gescannt —
nur der bereits vorhandene, persistierte Report gelesen (Auftrag §7a).
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


def _write_report(data_dir: Path, report: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "library_health_report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8",
    )


def _real_report(library_root: Path) -> dict:
    return run_scan(library_root, supported_extensions=(".m4a",), expected_extension=".m4a")


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


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/artists-overview
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_reads_persisted_report_without_scanning(client, monkeypatch, tmp_path, test_library):
    """Kernanforderung Auftrag §7a: der Endpunkt scannt NICHT selbst -
    er liefert exakt das, was im bereits vorhandenen Report steht, auch
    wenn die Library sich seitdem geändert hat (hier: Library existiert
    nach dem Report-Schreiben gar nicht mehr am ORIGINAL-Pfad, der
    Endpunkt liest trotzdem erfolgreich, da er nie auf Config.LIBRARY_DIR
    zugreift)."""
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "does-not-exist-anymore")

    response = await client.get("/api/v1/library/artists-overview")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    names = sorted(a["artist"] for a in body["artists"])
    assert names == ["Artist One", "Artist Two"]
    assert body["stale"] is False
    assert body["generated_at"] == report["scan"]["completed_at"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_entry_has_expected_fields(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview")

    entry = next(a for a in response.json()["artists"] if a["artist"] == "Artist One")
    assert entry["file_count"] == 2
    assert entry["album_count"] == 1
    assert isinstance(entry["health_score"], float)
    assert 0.0 <= entry["health_score"] <= 100.0
    assert isinstance(entry["issue_codes"], list)


@pytest.mark.asyncio
async def test_missing_report_returns_404_without_scanning(client, monkeypatch, tmp_path):
    """Kein Report vorhanden -> 404 LIBRARY_REPORT_MISSING, KEIN
    impliziter Scan (Auftrag §7a Punkt 2) - kein ffmpeg/Library noetig,
    beweist gerade die Abwesenheit jeglichen Scan-Versuchs."""
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/artists-overview")

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

    response = await client.get("/api/v1/library/artists-overview")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_REPORT_MISSING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_stale_report_still_returned_but_flagged(client, monkeypatch, tmp_path, test_library):
    """Auftrag §7a Punkt 1: aelter als 24h -> Report bleibt nutzbar,
    aber `stale=True` fuer die UI-Kennzeichnung ("Stand: ...")."""
    report = _real_report(test_library)
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    report["scan"]["completed_at"] = old.isoformat()
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["total"] == 2  # weiterhin nutzbare Daten, kein Fehler


@requires_ffmpeg
@pytest.mark.asyncio
async def test_fresh_report_not_flagged_stale(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview")

    assert response.json()["stale"] is False


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/artists-overview/{artist}
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_detail_returns_albums_and_tracks(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview/Artist One")

    assert response.status_code == 200
    body = response.json()
    assert body["artist"] == "Artist One"
    assert body["file_count"] == 2
    assert body["album_count"] == 1
    assert [a["album"] for a in body["albums"]] == ["Album A"]
    assert sorted(t["title"] for t in body["tracks"]) == ["Song A", "Song B"]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_detail_scope_excludes_other_artists(client, monkeypatch, tmp_path, test_library):
    """Artist = stabiler, verzeichnisbasierter Kontext (Auftrag §10) -
    Artist Twos Album/Tracks duerfen bei Artist One nicht auftauchen."""
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview/Artist One")

    body = response.json()
    assert "Album B" not in [a["album"] for a in body["albums"]]
    assert "Song C" not in [t["title"] for t in body["tracks"]]


@requires_ffmpeg
@pytest.mark.asyncio
async def test_unknown_artist_returns_404(client, monkeypatch, tmp_path, test_library):
    report = _real_report(test_library)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview/Does-Not-Exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "ARTIST_NOT_FOUND"


@pytest.mark.asyncio
async def test_artist_detail_missing_report_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/artists-overview/Anyone")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIBRARY_REPORT_MISSING"


@requires_ffmpeg
@pytest.mark.asyncio
async def test_artist_with_no_albums_or_tracks_after_scope_filter(client, monkeypatch, tmp_path):
    """Auftrag §28: Artist Detail darf bei leeren Alben/Tracks nicht
    abbrechen - hier real erzwungen ueber einen Artist mit Datei direkt
    im Artist-Ordner (kein Album-Unterordner, discovery.py klassifiziert
    das als artist_directory gesetzt, album_directory=None)."""
    lib = tmp_path / "library"
    _make_m4a(lib / "Loner" / "loose-track.m4a", artist="Loner", title="Loose")
    report = _real_report(lib)
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")
    _write_report(tmp_path / "data", report)

    response = await client.get("/api/v1/library/artists-overview/Loner")

    assert response.status_code == 200
    body = response.json()
    assert body["album_count"] == 0
    assert body["albums"] == []
    assert len(body["tracks"]) == 1
