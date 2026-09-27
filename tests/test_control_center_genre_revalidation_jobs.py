# -*- coding: utf-8 -*-
"""POST /api/v1/jobs/genre-revalidation-preview und /genre-revalidation-apply.

Router -> services/library_repair/genre_revalidation_runner.py::
run_genre_revalidation_subprocess(). Nur der Runner ist ersetzt (kein echter
Last.fm-Aufruf, kein Subprozess); Job-Registry, Auth, CSRF und die Abbildung des
Ergebnisses sind echt.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_repair.genre_revalidation_runner import GenreRevalidationRunResult
from services.library_repair.run_tracking import RepairAlreadyRunningError

_SAME_ORIGIN = {"Origin": "http://testserver"}

_DATA = {
    "artist": "Frischer Artist", "outcome": "OVERTURN_ALLOWED",
    "reason": "Neuer Kandidat erfüllt die Overturn-Regel - Änderung zulässig.",
    "manual_mapping_protected": False, "current_primary": "Pop", "current_secondary": [],
    "candidate_primary": "Hip Hop", "candidate_secondary": ["Deutschrap"], "candidate_source": "lastfm",
    "learning_status": "LEARNED", "locked_primary": "Hip Hop", "observation_count": 3,
    "mutated": False, "error_message": None,
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

    monkeypatch.setattr(jobs_router, "run_genre_revalidation_subprocess", fake)


async def _start(client, mode, artist="Frischer Artist", headers=_SAME_ORIGIN):
    return await client.post(f"/api/v1/jobs/genre-revalidation-{mode}", headers=headers, json={"artist": artist})


async def _finished(client, job_id):
    for _ in range(100):
        body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if body["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("Job nicht beendet")


@pytest.mark.asyncio
async def test_preview_job_calls_the_runner_without_apply_and_returns_the_result(client, monkeypatch):
    calls = []

    async def fake(artist, *, apply=False, triggered_by="cli", **kw):
        calls.append((artist, apply, triggered_by))
        return GenreRevalidationRunResult(exit_code=0, data=dict(_DATA))

    _patch_runner(monkeypatch, fake)
    r = await _start(client, "preview")
    assert r.status_code == 200 and r.json()["kind"] == "genre_revalidation_preview"

    job = await _finished(client, r.json()["job_id"])

    assert calls == [("Frischer Artist", False, "control_center:77")]
    assert job["status"] == "SUCCEEDED" and job["initiator"] == "77"
    res = job["result"]
    assert res["mode"] == "preview" and res["outcome"] == "OVERTURN_ALLOWED"
    assert res["candidate_primary"] == "Hip Hop" and res["current_primary"] == "Pop"
    assert res["mutated"] is False and res["bot_reload_required"] is False


@pytest.mark.asyncio
async def test_apply_job_calls_the_runner_with_apply_and_reports_the_mutation(client, monkeypatch):
    calls = []

    async def fake(artist, *, apply=False, triggered_by="cli", **kw):
        calls.append((artist, apply, triggered_by))
        return GenreRevalidationRunResult(exit_code=0, data={**_DATA, "mutated": True})

    _patch_runner(monkeypatch, fake)
    r = await _start(client, "apply")
    assert r.json()["kind"] == "genre_revalidation_apply"
    job = await _finished(client, r.json()["job_id"])

    assert calls == [("Frischer Artist", True, "control_center:77")]
    assert job["result"]["mode"] == "apply" and job["result"]["mutated"] is True
    assert job["result"]["bot_reload_required"] is True          # nur wenn wirklich geschrieben wurde


@pytest.mark.asyncio
async def test_blocked_manual_is_a_finished_job_without_mutation(client, monkeypatch):
    async def fake(artist, **kw):
        return GenreRevalidationRunResult(exit_code=0, data={
            **_DATA, "outcome": "BLOCKED_MANUAL", "manual_mapping_protected": True,
            "candidate_primary": None, "candidate_secondary": []})

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "apply")).json()["job_id"])
    assert job["status"] == "SUCCEEDED"
    assert job["result"]["outcome"] == "BLOCKED_MANUAL" and job["result"]["mutated"] is False


@pytest.mark.asyncio
async def test_lastfm_error_with_exit_code_1_still_carries_the_data(client, monkeypatch):
    async def fake(artist, **kw):
        return GenreRevalidationRunResult(exit_code=1, data={
            **_DATA, "outcome": "NO_CANDIDATE", "error_message": "lastfm down", "candidate_primary": None})

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "preview")).json()["job_id"])
    assert job["status"] == "SUCCEEDED" and job["result"]["error_message"] == "lastfm down"
    assert job["result"]["exit_code"] == 1


@pytest.mark.asyncio
async def test_subprocess_failure_without_data_fails_the_job_with_a_short_stderr_tail(client, monkeypatch):
    async def fake(artist, **kw):
        return GenreRevalidationRunResult(exit_code=3, data=None, stderr_tail="x" * 2000)

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "apply")).json()["job_id"])
    assert job["status"] == "FAILED" and "Exit-Code 3" in job["error"]
    assert job["result"]["mode"] == "apply" and len(job["result"]["stderr_tail"]) == 500


@pytest.mark.asyncio
async def test_timeout_and_start_errors_fail_the_job(client, monkeypatch):
    async def fake(artist, **kw):
        return GenreRevalidationRunResult(exit_code=None, data=None, timed_out=True, error_message="Timeout nach 60s")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "preview")).json()["job_id"])
    assert job["status"] == "FAILED" and "Timeout" in job["error"]


@pytest.mark.asyncio
async def test_a_running_repair_lock_fails_the_job_with_the_lock_message(client, monkeypatch):
    async def fake(artist, **kw):
        raise RepairAlreadyRunningError("Es läuft bereits eine Reparatur - bitte warten.")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "apply")).json()["job_id"])
    assert job["status"] == "FAILED" and "läuft bereits eine Reparatur" in job["error"]


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_leak_details(client, monkeypatch):
    async def fake(artist, **kw):
        raise RuntimeError("geheimer Pfad /home/x/.env")

    _patch_runner(monkeypatch, fake)
    job = await _finished(client, (await _start(client, "preview")).json()["job_id"])
    assert job["status"] == "FAILED" and "geheimer" not in json.dumps(job)


@pytest.mark.asyncio
@pytest.mark.parametrize("artist", ["", "   ", "-M-", "--apply", "a\nb", "x" * 201])
@pytest.mark.parametrize("mode", ["preview", "apply"])
async def test_invalid_artist_is_rejected_before_any_job_or_runner_call(client, monkeypatch, artist, mode):
    async def fake(*a, **kw):
        raise AssertionError("Runner darf nicht aufgerufen werden")

    _patch_runner(monkeypatch, fake)
    r = await _start(client, mode, artist=artist)
    assert r.status_code == 422
    assert (await client.get("/api/v1/jobs")).json()["jobs"] == []


@pytest.mark.asyncio
async def test_endpoints_require_same_origin_and_authentication(client, monkeypatch):
    assert (await _start(client, "apply", headers={})).status_code == 403
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: False))
    assert (await _start(client, "apply")).status_code == 401
    assert (await _start(client, "preview")).status_code == 401


@pytest.mark.asyncio
async def test_missing_artist_field_is_422(client):
    r = await client.post("/api/v1/jobs/genre-revalidation-apply", headers=_SAME_ORIGIN, json={})
    assert r.status_code == 422
