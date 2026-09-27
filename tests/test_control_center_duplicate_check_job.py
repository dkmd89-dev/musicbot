# -*- coding: utf-8 -*-
"""POST /api/v1/jobs/duplicate-check.

Backlog-Punkt "Duplikat-Check im CC" (docs/audits/
WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md §2.3 A / §5 Nr. 4a).

Router -> services/library_repair/duplicate_runner.py::run_duplicate_scan().
Nur der Runner ist ersetzt (kein echter Subprozess); Job-Registry, Auth,
CSRF und die Abbildung des Ergebnisses sind echt — identisches Testmuster
wie tests/test_control_center_genre_revalidation_jobs.py.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_repair.duplicate_runner import DuplicateScanResult
from services.library_repair.run_tracking import RepairAlreadyRunningError

_SAME_ORIGIN = {"Origin": "http://testserver"}

_REPORT = {
    "duplicate_groups": 1,
    "resolved_groups": 1,
    "manual_review_groups": 0,
    "files_scanned": 4,
    "read_only_intact": True,
    "decisions": [
        {
            "title": "Song A",
            "action": "RESOLVED",
            "keep": "/library/Artist/Song A (320).m4a",
            "remove_proposal": ["/library/Artist/Song A (128).m4a"],
            "candidates": [
                {"path": "/library/Artist/Song A (320).m4a", "bitrate": 320},
                {"path": "/library/Artist/Song A (128).m4a", "bitrate": 128},
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 77))


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _patch_runner(monkeypatch, fake):
    import control_center.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "run_duplicate_scan", fake)


async def _start(client, artist="Frischer Artist", headers=_SAME_ORIGIN):
    return await client.post("/api/v1/jobs/duplicate-check", headers=headers, json={"artist": artist})


async def _finished(client, job_id):
    for _ in range(100):
        body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if body["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("Job nicht beendet")


@pytest.mark.asyncio
async def test_job_calls_the_runner_and_returns_the_report(client, monkeypatch):
    calls = []

    async def fake(artist, *a, **kw):
        calls.append(artist)
        return DuplicateScanResult(exit_code=0, report=dict(_REPORT))

    _patch_runner(monkeypatch, fake)
    r = await _start(client)
    assert r.status_code == 200 and r.json()["kind"] == "duplicate_check"

    job = await _finished(client, r.json()["job_id"])

    assert calls == ["Frischer Artist"]
    assert job["status"] == "SUCCEEDED" and job["initiator"] == "77"
    res = job["result"]
    assert res["duplicate_groups"] == 1 and res["resolved_groups"] == 1
    assert res["decisions"][0]["title"] == "Song A"


@pytest.mark.asyncio
async def test_safety_violation_report_still_succeeds(client, monkeypatch):
    """Exit-Code 3 (vom Skript selbst erkannte Safety-Violation) liefert
    weiterhin einen gueltigen Report (read_only_intact=False) - kein
    Fehlschlag, die UI wertet das Flag selbst aus (wie in Telegram)."""

    async def fake(artist, *a, **kw):
        return DuplicateScanResult(exit_code=3, report={**_REPORT, "read_only_intact": False})

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client)).json()["job_id"])
    assert job["status"] == "SUCCEEDED"
    assert job["result"]["read_only_intact"] is False


@pytest.mark.asyncio
async def test_no_report_fails_the_job_with_a_short_stderr_tail(client, monkeypatch):
    async def fake(artist, *a, **kw):
        return DuplicateScanResult(exit_code=1, report=None, stderr_tail="x" * 2000)

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client)).json()["job_id"])
    assert job["status"] == "FAILED" and "Exit-Code 1" in job["error"]
    assert len(job["result"]["stderr_tail"]) == 500


@pytest.mark.asyncio
async def test_timeout_and_start_errors_fail_the_job(client, monkeypatch):
    async def fake(artist, *a, **kw):
        return DuplicateScanResult(exit_code=None, report=None, timed_out=True, error_message="Timeout nach 300s")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client)).json()["job_id"])
    assert job["status"] == "FAILED" and "Timeout" in job["error"]


@pytest.mark.asyncio
async def test_a_running_repair_lock_fails_the_job_with_the_lock_message(client, monkeypatch):
    async def fake(artist, *a, **kw):
        raise RepairAlreadyRunningError("Es läuft bereits eine Reparatur - bitte warten.")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client)).json()["job_id"])
    assert job["status"] == "FAILED" and "läuft bereits eine Reparatur" in job["error"]


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_leak_details(client, monkeypatch):
    async def fake(artist, *a, **kw):
        raise RuntimeError("geheimer Pfad /home/x/.env")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client)).json()["job_id"])
    assert job["status"] == "FAILED" and "geheimer" not in json.dumps(job)


@pytest.mark.asyncio
@pytest.mark.parametrize("artist", ["", "   "])
async def test_invalid_artist_is_rejected_before_any_job_or_runner_call(client, monkeypatch, artist):
    async def fake(*a, **kw):
        raise AssertionError("Runner darf nicht aufgerufen werden")

    _patch_runner(monkeypatch, fake)
    r = await _start(client, artist=artist)
    assert r.status_code == 422
    assert (await client.get("/api/v1/jobs")).json()["jobs"] == []


@pytest.mark.asyncio
async def test_endpoint_requires_same_origin_and_authentication(client, monkeypatch):
    assert (await _start(client, headers={})).status_code == 403
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    assert (await _start(client)).status_code == 401


@pytest.mark.asyncio
async def test_missing_artist_field_is_422(client):
    r = await client.post("/api/v1/jobs/duplicate-check", headers=_SAME_ORIGIN, json={})
    assert r.status_code == 422
