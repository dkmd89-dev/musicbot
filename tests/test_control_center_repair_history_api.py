# tests/test_control_center_repair_history_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/library/repairs/history + /repairs/statistics
(control_center/routers/repair.py, Nachtrag zu api_health.md Abschnitt 12).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der Router
ruft services/library_repair/run_tracking.py::load_repair_history()/
compute_repair_statistics() unveraendert auf — identische Datei
(Config.DATA_DIR/library_repair_runs.json) wie append_run_record() sie aus
repair_service.py/maintenance_service.py/genre_revalidation.py befuellt,
hier direkt vorbefuellt statt ueber einen echten Reparaturlauf (kein
ffmpeg/Subprozess noetig, reiner API-Contract-Test)."""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_repair.run_tracking import RUNS_INDEX_FILENAME


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


def _write_runs(data_dir, runs: list[dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / RUNS_INDEX_FILENAME).write_text(
        json.dumps({"runs": runs}, ensure_ascii=False), encoding="utf-8",
    )


_SAFE_AUTOMATIC_RUN = {
    "repair_id": "r1", "started_at": "2026-09-01T00:00:00+00:00",
    "finished_at": "2026-09-01T00:01:00+00:00", "triggered_by": "control_center:1",
    "level": "SAFE_AUTOMATIC", "kind": "repair", "exit_code": 0, "status": "SUCCESS",
    "finding_ids": ["f1"], "resolved_finding_ids": ["f1"], "issue_codes": ["META_ARTIST_MISSING"],
    "status_counts": {"SUCCESS": 1, "FAILED": 0, "SKIPPED": 0}, "affected_files": ["/a.m4a"],
    "regressed_issue_codes": [],
}
_L2_RUN = {
    "repair_id": "r2", "started_at": "2026-09-02T00:00:00+00:00",
    "finished_at": "2026-09-02T00:02:00+00:00", "triggered_by": "control_center:1",
    "level": "METADATA_REPROCESSING", "kind": "repair", "artist": "Artist One",
    "exit_code": 0, "status": "SUCCESS", "finding_ids": ["f2"], "resolved_finding_ids": [],
    "issue_codes": [], "status_counts": {"SUCCESS": 0, "FAILED": 1, "SKIPPED": 0},
    "affected_files": [],
}
_MAINTENANCE_RUN = {
    "repair_id": "r3", "started_at": "2026-09-03T00:00:00+00:00",
    "finished_at": "2026-09-03T00:00:30+00:00", "triggered_by": "telegram:2",
    "level": "GENRE_REVALIDATION", "kind": "maintenance", "artist": "Artist Two",
    "status": "SUCCESS", "status_counts": {"SUCCESS": 1, "SKIPPED": 0, "FAILED": 0},
    "affected_files": [],
}


@pytest.mark.asyncio
async def test_no_history_file_returns_empty(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/repairs/history")

    assert response.status_code == 200
    assert response.json() == {"runs": [], "total": 0}


@pytest.mark.asyncio
async def test_history_returns_runs_newest_first_across_both_flows(client, monkeypatch, tmp_path):
    """Ein gemeinsamer Index ueber Finding-Repair (kind=repair) UND
    Maintenance (kind=maintenance) — identisch zu load_repair_history()."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    _write_runs(data_dir, [_SAFE_AUTOMATIC_RUN, _L2_RUN, _MAINTENANCE_RUN])

    response = await client.get("/api/v1/library/repairs/history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [r["repair_id"] for r in body["runs"]] == ["r3", "r2", "r1"]
    assert body["runs"][0]["kind"] == "maintenance"
    assert body["runs"][0]["artist"] == "Artist Two"
    # SAFE_AUTOMATIC-Runs haben keinen Artist (globaler Batch):
    assert body["runs"][2]["artist"] is None
    assert body["runs"][2]["regressed_issue_codes"] == []


@pytest.mark.asyncio
async def test_history_limit_truncates_but_keeps_total(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    _write_runs(data_dir, [_SAFE_AUTOMATIC_RUN, _L2_RUN, _MAINTENANCE_RUN])

    response = await client.get("/api/v1/library/repairs/history?limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["runs"]) == 1
    assert body["runs"][0]["repair_id"] == "r3"


@pytest.mark.asyncio
async def test_statistics_empty_when_no_runs(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    response = await client.get("/api/v1/library/repairs/statistics")

    assert response.status_code == 200
    assert response.json() == {
        "total_runs": 0, "total": 0, "success": 0, "failed": 0, "skipped": 0,
        "most_common_issue_codes": [],
    }


@pytest.mark.asyncio
async def test_statistics_aggregates_status_counts_and_issue_codes(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    _write_runs(data_dir, [_SAFE_AUTOMATIC_RUN, _L2_RUN, _MAINTENANCE_RUN])

    response = await client.get("/api/v1/library/repairs/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 3
    assert body["success"] == 2  # 1 (safe_automatic) + 1 (maintenance)
    assert body["failed"] == 1  # L2-Run
    assert body["skipped"] == 0
    assert ["META_ARTIST_MISSING", 1] in body["most_common_issue_codes"]


@pytest.mark.asyncio
async def test_history_and_statistics_require_at_least_admin_access_level(monkeypatch, tmp_path):
    """Identische Schwelle wie GET /repair-plan (repair.router: mindestens
    AccessLevel.ADMIN, Auftrag §15 "Repair History/Actions" == ADMIN)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    monkeypatch.setattr(Config, "DATA_DIR", tmp_path / "data")

    from control_center.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        history_response = await c.get("/api/v1/library/repairs/history")
        stats_response = await c.get("/api/v1/library/repairs/statistics")

    assert history_response.status_code == 401
    assert stats_response.status_code == 401
