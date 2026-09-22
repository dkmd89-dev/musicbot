# tests/test_control_center_health_score_history_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/health/score-history — Health-Score-Verlauf
(control_center/routers/health.py, Nachtrag zu api_health.md Abschnitt 6).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der Router
ruft services/library_health/score_history.py::read_score_history()
unveraendert auf — identische Datei (Config.DATA_DIR/
library_health_score_history.jsonl) wie jeder echte Scan sie befuellt
(append_score_history()), hier nur direkt vorbefuellt statt ueber einen
echten Scan (kein ffmpeg noetig, reiner API-Contract-Test)."""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_health.score_history import SCORE_HISTORY_FILENAME


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prueft die Score-History-Fachlogik, nicht die
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


def _write_history(data_dir, entries: list[dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / SCORE_HISTORY_FILENAME, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@pytest.mark.asyncio
async def test_no_history_file_returns_empty_entries(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/health/score-history")

    assert response.status_code == 200
    assert response.json() == {"entries": []}


@pytest.mark.asyncio
async def test_returns_entries_in_chronological_order(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    entries = [
        {"timestamp": "2026-09-01T00:00:00+00:00", "score": 80.0, "status": "GOOD",
         "total_issues": 5, "total_files": 100},
        {"timestamp": "2026-09-02T00:00:00+00:00", "score": 85.0, "status": "GOOD",
         "total_issues": 3, "total_files": 101},
    ]
    _write_history(data_dir, entries)

    response = await client.get("/api/v1/library/health/score-history")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == entries


@pytest.mark.asyncio
async def test_limit_returns_only_newest_entries(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    entries = [
        {"timestamp": f"2026-09-0{i}T00:00:00+00:00", "score": float(i), "status": "GOOD",
         "total_issues": 0, "total_files": 1}
        for i in range(1, 4)
    ]
    _write_history(data_dir, entries)

    response = await client.get("/api/v1/library/health/score-history?limit=1")

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["timestamp"] == "2026-09-03T00:00:00+00:00"


@pytest.mark.asyncio
async def test_unparseable_lines_are_skipped_not_fatal(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / SCORE_HISTORY_FILENAME).write_text(
        '{"timestamp": "2026-09-01T00:00:00+00:00", "score": 80.0, "status": "GOOD", '
        '"total_issues": 0, "total_files": 1}\n'
        "{not valid json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)

    response = await client.get("/api/v1/library/health/score-history")

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 1


@pytest.mark.asyncio
async def test_requires_at_least_user_access_level(monkeypatch, tmp_path):
    """Identische Schwelle wie GET /health (routers/health.py: mindestens
    AccessLevel.USER) — score-history gehoert zum selben Router."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        response = await c.get("/api/v1/library/health/score-history")

    assert response.status_code == 401
