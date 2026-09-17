# tests/test_control_center_jobs_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/jobs (+ /{job_id}), POST /demo, POST /{job_id}/cancel —
Jobs-Grundgerüst (Vertical Slice "Jobs", Phase 1: nur Infrastruktur,
noch kein echter Job-Typ — siehe control_center/routers/jobs.py-Docstring).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router nutzt services/jobs/job_registry.py::JobRegistry unverändert.
Jede Testfunktion bekommt über create_app() eine frische, isolierte
JobRegistry (app.state.job_registry) — kein Reset-Mechanismus nötig.

_DEMO_JOB_STEPS/_DEMO_JOB_STEP_SECONDS werden für schnelle Tests auf
winzige Werte gepatcht (Produktions-Default: 5 Schritte à 1 Sekunde).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio

from config import Config

_SAME_ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    """Dieses Testfile prüft die Jobs-Fachlogik, nicht die
    Authentifizierung (dafür: tests/test_control_center_auth.py)."""
    monkeypatch.setattr(Config, "CONTROL_CENTER_DEV_AUTH_BYPASS", property(lambda self: True))


@pytest.fixture(autouse=True)
def _fast_demo_job(monkeypatch):
    """Produktions-Default (5 Schritte à 1s) waere fuer Tests zu langsam -
    hier auf 2 Schritte à 10ms gepatcht, damit der Hintergrund-Task
    (asyncio.create_task in derselben Event Loop wie der Test) schnell
    durchlaeuft."""
    import control_center.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "_DEMO_JOB_STEPS", 2)
    monkeypatch.setattr(jobs_router, "_DEMO_JOB_STEP_SECONDS", 0.01)


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


@pytest.mark.asyncio
async def test_list_jobs_empty_initially(client):
    response = await client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


@pytest.mark.asyncio
async def test_get_job_404_for_unknown_id(client):
    response = await client.get("/api/v1/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_start_demo_job_returns_pending_job(client):
    response = await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "demo_progress"
    assert body["status"] in ("PENDING", "RUNNING")
    assert body["job_id"]


@pytest.mark.asyncio
async def test_start_demo_job_rejected_without_origin_header(client):
    response = await client.post("/api/v1/jobs/demo")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_demo_job_reaches_succeeded_with_full_progress(client):
    job_id = (await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)).json()["job_id"]

    await asyncio.sleep(0.2)  # laesst den Hintergrund-Task (2 Schritte a 10ms) durchlaufen

    response = await client.get(f"/api/v1/jobs/{job_id}")
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["progress"] == 100.0
    assert body["result"] == {"steps_completed": 2}
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


@pytest.mark.asyncio
async def test_demo_job_records_initiator(client, monkeypatch):
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 777))

    job_id = (await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)).json()["job_id"]

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["initiator"] == "777"


@pytest.mark.asyncio
async def test_list_jobs_shows_started_job(client):
    started = (await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)).json()

    body = (await client.get("/api/v1/jobs")).json()

    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["job_id"] == started["job_id"]


@pytest.mark.asyncio
async def test_cancel_job_stops_before_completion(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    # Deutlich laengere Schritte, damit genug Zeit zum Abbrechen bleibt,
    # bevor der Job von selbst fertig waere.
    monkeypatch.setattr(jobs_router, "_DEMO_JOB_STEPS", 20)
    monkeypatch.setattr(jobs_router, "_DEMO_JOB_STEP_SECONDS", 0.05)

    job_id = (await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)).json()["job_id"]
    await asyncio.sleep(0.06)  # mind. ein Schritt ist bereits gelaufen

    cancel_response = await client.post(
        f"/api/v1/jobs/{job_id}/cancel", headers=_SAME_ORIGIN
    )
    assert cancel_response.status_code == 200

    await asyncio.sleep(0.1)  # dem Hintergrund-Task Zeit geben, den Abbruch zu bemerken

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "CANCELLED"
    assert body["progress"] < 100.0


@pytest.mark.asyncio
async def test_cancel_job_404_for_unknown_id(client):
    response = await client.post(
        "/api/v1/jobs/does-not-exist/cancel", headers=_SAME_ORIGIN
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_cancel_job_rejected_with_mismatched_origin(client):
    job_id = (await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)).json()["job_id"]

    response = await client.post(
        f"/api/v1/jobs/{job_id}/cancel", headers={"Origin": "http://evil.example"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_list_jobs_respects_limit(client):
    for _ in range(3):
        await client.post("/api/v1/jobs/demo", headers=_SAME_ORIGIN)

    response = await client.get("/api/v1/jobs", params={"limit": 2})

    assert len(response.json()["jobs"]) == 2


@pytest.mark.asyncio
async def test_list_jobs_rejects_invalid_limit(client):
    response = await client.get("/api/v1/jobs", params={"limit": 0})

    assert response.status_code == 422
