# control_center/schemas/jobs.py
# -*- coding: utf-8 -*-
"""Response-Schemas für GET /api/v1/jobs (+ /{job_id}), POST /demo,
POST /{job_id}/cancel."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from services.jobs.models import Job


class JobSchema(BaseModel):
    job_id: str
    kind: str
    initiator: str
    status: str
    progress: float
    message: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: list[JobSchema]


def job_to_schema(job: Job) -> JobSchema:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    control_center/schemas/health.py::report_to_health_response()."""
    return JobSchema(
        job_id=job.job_id,
        kind=job.kind,
        initiator=job.initiator,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        error=job.error,
    )


def jobs_to_response(jobs: list[Job]) -> JobListResponse:
    return JobListResponse(jobs=[job_to_schema(j) for j in jobs])


class ArtistLevelRepairRequest(BaseModel):
    """Body für POST /repair-level2 und /repair-level3 — Artist als Body-
    statt Pfad-Parameter (identisches Muster wie AcceptFindingRequest in
    schemas/findings.py), da Artist-Namen beliebige Zeichen enthalten
    können."""

    artist: str
