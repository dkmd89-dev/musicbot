# control_center/routers/jobs.py
# -*- coding: utf-8 -*-
"""
GET /api/v1/jobs (+ /{job_id}), POST /demo, POST /{job_id}/cancel —
Jobs-Grundgerüst (Vertical Slice "Jobs", Phase 1: nur Infrastruktur).

Reine Orchestrierung um services/jobs/job_registry.py::JobRegistry.
Registry liegt in app.state.job_registry (control_center/app.py) — EINE
Instanz pro Prozess, per Dependency injiziert statt Modul-Level-Global,
damit jeder Testlauf (der create_app() frisch aufruft, wie alle
bestehenden control_center-Tests bereits tun) automatisch eine isolierte
Registry bekommt, ohne einen eigenen Reset-Mechanismus zu brauchen.

**Nur ein einziger, klar als Test-/Demo-Fähigkeit gekennzeichneter
Job-Typ in diesem Schritt** ("demo_progress", POST /demo) — läuft fünf
Sekunden lang und zählt Fortschritt hoch, führt keine reale Operation aus
(Master-Prompt Regel 39: keine Fake-Implementierung, die wie eine fertige
Funktion aussieht). Beweist die Infrastruktur (Erstellen/Abfragen/
Auflisten/Abbrechen), bevor ein echter Job-Typ (z. B. Repair-Execution)
als eigener, separat freizugebender Schritt darauf aufbaut.

POST /demo und POST /{job_id}/cancel sind schreibend (starten bzw.
beeinflussen einen Hintergrund-Task) — beide über verify_same_origin()
CSRF-geschützt, identisches Muster wie Findings Accept/Unaccept.

Authentifiziert mit mindestens AccessLevel.ADMIN — Jobs sind bereits in
diesem Grundgerüst als Administrationsfunktion eingestuft (jeder künftige
echte Job-Typ wird mindestens so sensibel sein, keine Aufweichung nötig).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.jobs.job_registry import JobRegistry

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.jobs import JobListResponse, JobSchema, job_to_schema, jobs_to_response

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_min_access_level(AccessLevel.ADMIN))],
)
_logger = get_module_logger("control_center.jobs")

_DEMO_JOB_STEPS = 5
_DEMO_JOB_STEP_SECONDS = 1


def get_job_registry(request: Request) -> JobRegistry:
    return request.app.state.job_registry


def _get_job_or_404(registry: JobRegistry, job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(code="JOB_NOT_FOUND", message="Unbekannte Job-ID.").model_dump(),
        )
    return job


async def _run_demo_job(registry: JobRegistry, job_id: str) -> None:
    """Reine Test-/Demo-Fähigkeit — führt nichts Reales aus (siehe
    Modul-Docstring). Kooperatives Abbrechen: prüft is_cancel_requested()
    zwischen jedem Schritt, identisches Prinzip wie
    services/downloader/active_downloads.py::ActiveDownload.is_cancel_requested()."""
    registry.mark_running(job_id)
    try:
        for step in range(1, _DEMO_JOB_STEPS + 1):
            if registry.is_cancel_requested(job_id):
                registry.mark_cancelled(job_id)
                return
            await asyncio.sleep(_DEMO_JOB_STEP_SECONDS)
            registry.update_progress(
                job_id, (step / _DEMO_JOB_STEPS) * 100, f"Demo-Schritt {step}/{_DEMO_JOB_STEPS}"
            )
        registry.mark_succeeded(job_id, result={"steps_completed": _DEMO_JOB_STEPS})
    except Exception as e:  # noqa: BLE001
        _logger.error(f"Demo-Job {job_id} fehlgeschlagen: {e!r}")
        registry.mark_failed(job_id, "Interner Fehler im Demo-Job.")


@router.get("", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobListResponse:
    return jobs_to_response(registry.list(limit=limit))


@router.get("/{job_id}", response_model=JobSchema)
def get_job(job_id: str, registry: JobRegistry = Depends(get_job_registry)) -> JobSchema:
    job = _get_job_or_404(registry, job_id)
    return job_to_schema(job)


@router.post("/demo", response_model=JobSchema, dependencies=[Depends(verify_same_origin)])
async def start_demo_job(
    user_id: int = Depends(get_current_user_id),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobSchema:
    job = registry.create(kind="demo_progress", initiator=str(user_id))
    asyncio.create_task(_run_demo_job(registry, job.job_id))
    return job_to_schema(job)


@router.post(
    "/{job_id}/cancel", response_model=JobSchema, dependencies=[Depends(verify_same_origin)]
)
def cancel_job(job_id: str, registry: JobRegistry = Depends(get_job_registry)) -> JobSchema:
    job = _get_job_or_404(registry, job_id)
    registry.request_cancel(job_id)
    return job_to_schema(job)
