# tests/test_control_center_jobs_api.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/jobs (+ /{job_id}), POST /demo, POST /repair-safe-automatic,
POST /{job_id}/cancel — Jobs-Grundgerüst (Phase 1) + erster echter
Job-Typ (Phase 2, siehe control_center/routers/jobs.py-Docstring).

Testet den echten Produktionscode-Pfad (CLAUDE.md Abschnitt 7): der
Router nutzt services/jobs/job_registry.py::JobRegistry unverändert.
Jede Testfunktion bekommt über create_app() eine frische, isolierte
JobRegistry (app.state.job_registry) — kein Reset-Mechanismus nötig.

_DEMO_JOB_STEPS/_DEMO_JOB_STEP_SECONDS werden für schnelle Tests auf
winzige Werte gepatcht (Produktions-Default: 5 Schritte à 1 Sekunde).

Phase-2-Tests mocken services/library_repair/doctor_runner.py::
run_health_scan()/run_safe_automatic_repair() (CLAUDE.md Abschnitt 8:
externe/subprozessgebundene Operationen nicht real in Unit-Tests
ausführen — ein echter Lauf würde die Produktions-Library scannen/
verändern)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio

from config import Config
from services.library_repair.doctor_runner import DoctorRepairResult, DoctorScanResult

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


# ─────────────────────────────────────────────────────────────────────────
# POST /repair-safe-automatic — erster echter Job-Typ (Phase 2)
# ─────────────────────────────────────────────────────────────────────────


def _ok_scan_result(report=None):
    return DoctorScanResult(exit_code=0, report=report or {"health": {"score": 99.0}})


def _failed_scan_result():
    return DoctorScanResult(exit_code=1, report=None, stderr_tail="Scan kaputt")


def _ok_repair_result(stdout="alles repariert"):
    return DoctorRepairResult(exit_code=0, stdout_tail=stdout)


def _nonzero_repair_result():
    return DoctorRepairResult(exit_code=1, stdout_tail="teilweise fehlgeschlagen")


def _timed_out_repair_result():
    return DoctorRepairResult(exit_code=None, timed_out=True, error_message="Timeout nach 900s")


# ─────────────────────────────────────────────────────────────────────────
# POST /health-scan — reiner Health-Scan als Job (Phase 4, api_health.md
# Abschnitt 5) — isolierter Scan-Teil von repair-safe-automatic oben, ohne
# anschliessende Reparatur.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_scan_job_succeeds(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result(report={"health": {"score": 87.5, "status": "GOOD"},
                                        "library": {"files": 10, "artists": 2, "albums": 3}})

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)

    job_id = (
        await client.post("/api/v1/jobs/health-scan", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["kind"] == "library_health_scan"
    assert body["status"] == "SUCCEEDED"
    assert body["result"]["health"] == {"score": 87.5, "status": "GOOD"}
    assert body["result"]["library"] == {"files": 10, "artists": 2, "albums": 3}


@pytest.mark.asyncio
async def test_health_scan_job_fails_when_scan_fails(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _failed_scan_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)

    job_id = (
        await client.post("/api/v1/jobs/health-scan", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert body["result"]["exit_code"] == 1


@pytest.mark.asyncio
async def test_health_scan_job_rejected_without_origin_header(client):
    response = await client.post("/api/v1/jobs/health-scan")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_health_scan_job_records_initiator(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 77))

    job_id = (
        await client.post("/api/v1/jobs/health-scan", headers=_SAME_ORIGIN)
    ).json()["job_id"]

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["initiator"] == "77"


@pytest.mark.asyncio
async def test_repair_job_succeeds_when_scan_and_repair_succeed(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result()

    async def _fake_repair():
        return _ok_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_repair)

    job_id = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "SUCCEEDED"
    assert body["result"]["phase"] == "repair"
    assert body["result"]["exit_code"] == 0


@pytest.mark.asyncio
async def test_repair_job_fails_when_scan_fails_and_never_starts_repair(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    repair_called = False

    async def _fake_scan():
        return _failed_scan_result()

    async def _fake_repair():
        nonlocal repair_called
        repair_called = True
        return _ok_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_repair)

    job_id = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert body["result"]["phase"] == "scan"
    assert repair_called is False


@pytest.mark.asyncio
async def test_repair_job_fails_on_repair_timeout(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result()

    async def _fake_timeout_repair():
        return _timed_out_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_timeout_repair)

    job_id = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert "Timeout" in body["error"]


@pytest.mark.asyncio
async def test_repair_job_fails_with_diagnostic_result_on_nonzero_exit(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result()

    async def _fake_repair():
        return _nonzero_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_repair)

    job_id = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert body["result"]["stdout_tail"] == "teilweise fehlgeschlagen"
    assert "1" in body["error"]


@pytest.mark.asyncio
async def test_repair_job_cancel_between_scan_and_repair_prevents_repair(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    repair_called = False

    async def _slow_scan():
        await asyncio.sleep(0.08)
        return _ok_scan_result()

    async def _fake_repair():
        nonlocal repair_called
        repair_called = True
        return _ok_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _slow_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_repair)

    job_id = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()["job_id"]
    await asyncio.sleep(0.02)  # Job ist im Scan (der 0.08s dauert)
    await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=_SAME_ORIGIN)
    await asyncio.sleep(0.15)  # Scan beendet sich, Abbruch-Check greift

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "CANCELLED"
    assert repair_called is False


@pytest.mark.asyncio
async def test_repair_job_rejected_without_origin_header(client):
    response = await client.post("/api/v1/jobs/repair-safe-automatic")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_repair_job_records_initiator(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_scan():
        return _ok_scan_result()

    async def _fake_repair():
        return _ok_repair_result()

    monkeypatch.setattr(jobs_router, "run_health_scan", _fake_scan)
    monkeypatch.setattr(jobs_router, "run_safe_automatic_repair", _fake_repair)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 555))

    body = (
        await client.post("/api/v1/jobs/repair-safe-automatic", headers=_SAME_ORIGIN)
    ).json()
    assert body["initiator"] == "555"
    assert body["kind"] == "repair_safe_automatic"


# ─────────────────────────────────────────────────────────────────────────
# POST /repair-level2, POST /repair-level3 — Pro-Artist L2/L3 (Phase 3,
# Pendant zu ARCH-033 §12 Telegram-Flow)
# ─────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field  # noqa: E402


@dataclass
class _FakeLevelRepairResult:
    repair_id: str = "repair-1"
    artist: str = "Kygo"
    level: str = "l2"
    status: str = "SUCCESS"
    started_at: str = "2026-09-20T00:00:00+00:00"
    finished_at: str = "2026-09-20T00:01:00+00:00"
    total: int = 3
    success: int = 3
    failed: int = 0
    skipped: int = 0
    unresolved: int = 0
    resolved_count: int = 2
    entries: list = field(default_factory=list)
    affected_files: list = field(default_factory=list)
    rescan_triggered: bool = True
    error_message: str | None = None


@pytest.mark.parametrize("level,endpoint,kind", [
    ("l2", "repair-level2", "repair_level2"),
    ("l3", "repair-level3", "repair_level3"),
])
@pytest.mark.asyncio
async def test_level_repair_job_succeeds(client, monkeypatch, level, endpoint, kind):
    import control_center.routers.jobs as jobs_router

    captured = {}

    async def _fake_execute(artist, *, triggered_by):
        captured["artist"] = artist
        captured["triggered_by"] = triggered_by
        return _FakeLevelRepairResult(level=level, artist=artist)

    monkeypatch.setattr(
        jobs_router, "execute_level2_repair" if level == "l2" else "execute_level3_repair",
        _fake_execute,
    )

    response = await client.post(
        f"/api/v1/jobs/{endpoint}", json={"artist": "Kygo"}, headers=_SAME_ORIGIN,
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert response.json()["kind"] == kind

    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "SUCCEEDED"
    assert body["result"]["artist"] == "Kygo"
    assert body["result"]["success"] == 3
    assert body["result"]["resolved_count"] == 2
    assert captured["artist"] == "Kygo"
    assert captured["triggered_by"].startswith("control_center:")


@pytest.mark.parametrize("level,endpoint", [("l2", "repair-level2"), ("l3", "repair-level3")])
@pytest.mark.asyncio
async def test_level_repair_job_skipped_when_no_candidates_counts_as_success(
    client, monkeypatch, level, endpoint
):
    import control_center.routers.jobs as jobs_router

    async def _fake_execute(artist, *, triggered_by):
        return _FakeLevelRepairResult(
            level=level, artist=artist, status="SKIPPED", total=0, success=0,
        )

    monkeypatch.setattr(
        jobs_router, "execute_level2_repair" if level == "l2" else "execute_level3_repair",
        _fake_execute,
    )

    job_id = (
        await client.post(
            f"/api/v1/jobs/{endpoint}", json={"artist": "Kygo"}, headers=_SAME_ORIGIN,
        )
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "SUCCEEDED"
    assert body["result"]["status"] == "SKIPPED"


@pytest.mark.parametrize("level,endpoint", [("l2", "repair-level2"), ("l3", "repair-level3")])
@pytest.mark.asyncio
async def test_level_repair_job_fails_with_diagnostic_result(client, monkeypatch, level, endpoint):
    import control_center.routers.jobs as jobs_router

    async def _fake_execute(artist, *, triggered_by):
        return _FakeLevelRepairResult(
            level=level, artist=artist, status="FAILED", success=0, failed=3,
            error_message="Subprozess mit Exit-Code 1 beendet.",
        )

    monkeypatch.setattr(
        jobs_router, "execute_level2_repair" if level == "l2" else "execute_level3_repair",
        _fake_execute,
    )

    job_id = (
        await client.post(
            f"/api/v1/jobs/{endpoint}", json={"artist": "Kygo"}, headers=_SAME_ORIGIN,
        )
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert body["error"] == "Subprozess mit Exit-Code 1 beendet."
    assert body["result"]["failed"] == 3


@pytest.mark.parametrize("level,endpoint", [("l2", "repair-level2"), ("l3", "repair-level3")])
@pytest.mark.asyncio
async def test_level_repair_job_fails_when_lock_already_held(client, monkeypatch, level, endpoint):
    """Teilt sich den prozessübergreifenden Lock mit Telegram/CLI
    (services/library_repair/run_tracking.py::acquire_repair_lock()) —
    ein bereits laufender Lauf lässt den Job kontrolliert als FAILED
    enden statt eines rohen 500ers."""
    import control_center.routers.jobs as jobs_router
    from services.library_repair.repair_service import RepairAlreadyRunningError

    async def _fake_execute(artist, *, triggered_by):
        raise RepairAlreadyRunningError("Es läuft bereits eine Reparatur.")

    monkeypatch.setattr(
        jobs_router, "execute_level2_repair" if level == "l2" else "execute_level3_repair",
        _fake_execute,
    )

    job_id = (
        await client.post(
            f"/api/v1/jobs/{endpoint}", json={"artist": "Kygo"}, headers=_SAME_ORIGIN,
        )
    ).json()["job_id"]
    await asyncio.sleep(0.05)

    body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert body["status"] == "FAILED"
    assert "bereits eine Reparatur" in body["error"]


@pytest.mark.parametrize("endpoint", ["repair-level2", "repair-level3"])
@pytest.mark.asyncio
async def test_level_repair_job_rejects_empty_artist(client, endpoint):
    response = await client.post(
        f"/api/v1/jobs/{endpoint}", json={"artist": "   "}, headers=_SAME_ORIGIN,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ARTIST_REQUIRED"


@pytest.mark.parametrize("endpoint", ["repair-level2", "repair-level3"])
@pytest.mark.asyncio
async def test_level_repair_job_rejected_without_origin_header(client, endpoint):
    response = await client.post(f"/api/v1/jobs/{endpoint}", json={"artist": "Kygo"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_CHECK_FAILED"


@pytest.mark.asyncio
async def test_level_repair_job_records_initiator(client, monkeypatch):
    import control_center.routers.jobs as jobs_router

    async def _fake_execute(artist, *, triggered_by):
        return _FakeLevelRepairResult(artist=artist)

    monkeypatch.setattr(jobs_router, "execute_level2_repair", _fake_execute)
    monkeypatch.setattr(Config, "OWNER_USER_ID", property(lambda self: 999))

    body = (
        await client.post(
            "/api/v1/jobs/repair-level2", json={"artist": "Kygo"}, headers=_SAME_ORIGIN,
        )
    ).json()
    assert body["initiator"] == "999"
