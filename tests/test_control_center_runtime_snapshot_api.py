# tests/test_control_center_runtime_snapshot_api.py
# -*- coding: utf-8 -*-
"""
E1 — GET /api/v1/admin/runtime-snapshot: read-only, nur ADMIN, ehrliche
Zustände (missing/corrupt/stale) ohne vorgetäuschte Werte. Echter
Produktionspfad über services/bot_runtime_snapshot.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from config import Config
from services import bot_runtime_snapshot as brs
from services.access_control import AccessLevel


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    return tmp_path


def _client(access_level=None):
    from control_center.app import create_app
    from control_center.dependencies import get_current_access_level

    app = create_app()
    if access_level is not None:
        app.dependency_overrides[get_current_access_level] = lambda: access_level
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _write(data_dir, sections, generated_at=None):
    payload = {
        "schema_version": 1,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "bot_started_at": "2026-09-28T08:00:00+00:00",
        "pid": 1,
        "interval_seconds": 60,
        "sections": sections,
    }
    (data_dir / brs.SNAPSHOT_FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")


_SECTIONS = {
    "errors": {
        "stats": {
            "total_exceptions": 3,
            "by_category": {"network": 2, "validation": 1},
            "by_type": {"TimeoutError": 2, "ValueError": 1},
            "by_module": {"download_handler": 3},
            "by_severity": {"medium": 3},
            "hourly_counts": {"10": 3},
            "patterns": {"TimeoutError:network": 2},
        },
        "performance": {"total_handled": 3, "avg_processing_time": 0.12, "recovery_success_rate": 0.5, "last_reset": "x"},
        "recovery_attempts_total": 1,
        "recent": [
            {"id": "EXC_1", "timestamp": "2026-09-28T10:00:00", "type": "TimeoutError",
             "category": "network", "severity": "medium", "module": "download_handler", "message": "Timeout"},
        ],
    },
    "duplicates": {
        "total_checks": 4, "url_duplicates_found": 1, "content_duplicates_found": 1,
        "new_entries_added": 2, "duplicates_skipped": 2, "duplicate_rate": 50.0, "savings_percentage": 50.0,
    },
}


@pytest.mark.asyncio
async def test_missing_snapshot_reports_missing_without_values(data_dir):
    async with _client() as c:
        body = (await c.get("/api/v1/admin/runtime-snapshot")).json()

    assert body["status"] == "missing"
    assert body["errors"] is None and body["duplicates"] is None
    assert body["message"]


@pytest.mark.asyncio
async def test_available_snapshot_is_mapped(data_dir):
    _write(data_dir, _SECTIONS)

    async with _client() as c:
        r = await c.get("/api/v1/admin/runtime-snapshot")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "available"
    assert body["bot_started_at"] == "2026-09-28T08:00:00+00:00"
    assert body["errors"]["total_exceptions"] == 3
    assert body["errors"]["by_category"] == {"network": 2, "validation": 1}
    assert body["errors"]["recovery_success_rate"] == 0.5
    assert body["errors"]["recent"][0]["module"] == "download_handler"
    assert body["duplicates"]["total_checks"] == 4
    # kein 1:1-Durchreichen interner Felder
    assert "patterns" not in body["errors"] and "hourly_counts" not in body["errors"]


@pytest.mark.asyncio
async def test_stale_snapshot(data_dir):
    _write(data_dir, _SECTIONS, generated_at=datetime.now(timezone.utc) - timedelta(minutes=10))

    async with _client() as c:
        body = (await c.get("/api/v1/admin/runtime-snapshot")).json()

    assert body["status"] == "stale"
    assert body["errors"]["total_exceptions"] == 3  # letzter bekannter Stand bleibt sichtbar
    assert body["message"]


@pytest.mark.asyncio
async def test_corrupt_snapshot(data_dir):
    (data_dir / brs.SNAPSHOT_FILE_NAME).write_text("{kaputt", encoding="utf-8")

    async with _client() as c:
        body = (await c.get("/api/v1/admin/runtime-snapshot")).json()

    assert body["status"] == "corrupt"
    assert body["errors"] is None


@pytest.mark.asyncio
async def test_non_admin_forbidden(data_dir):
    _write(data_dir, _SECTIONS)

    async with _client(AccessLevel.USER) as c:
        r = await c.get("/api/v1/admin/runtime-snapshot")

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_no_write_endpoint(data_dir):
    async with _client() as c:
        r = await c.post("/api/v1/admin/runtime-snapshot", headers={"Origin": "http://testserver"})

    assert r.status_code == 405
