# control_center/schemas/repair.py
# -*- coding: utf-8 -*-
"""
Response-Schema für GET /api/v1/library/repair-plan.

Wie schemas/health.py bewusst kein 1:1-Durchreichen der internen
RepairPlan-Dataclass (services/library_repair/models.py) — "library_root"
(lokaler Filesystem-Pfad) wird aus demselben Grund wie bei
schemas/health.py ausgelassen. Ergänzt pro Kandidat die Grob-Disposition
(AUTO_REPAIR/MANUAL_REVIEW/UNREPAIRABLE, services/library_repair/
planner.py::disposition_for_level()) — nützlich für eine Preview-Ansicht,
ohne dass der Client das achtstufige RepairLevel selbst einordnen muss.

Reine Preview: kein Executor wird hier aufgerufen, keine Datei wird
verändert (services/library_repair/planner.py::plan_repairs() ist per
eigenem Modul-Docstring read-only, kein Dateisystem-Zugriff, keine
externen Aufrufe).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.library_repair.models import PLAN_SCHEMA_VERSION, RepairCandidate, RepairPlan
from services.library_repair.planner import (
    ArtistCandidateSummary,
    disposition_for_level,
    group_candidates_by_artist,
)


class RepairCandidateSchema(BaseModel):
    issue_code: str
    action: str
    level: str
    disposition: str
    severity: str
    scope: str
    path: str | None
    artist: str | None
    album: str | None
    title: str | None
    related_files: list[str]
    reuses_component: str
    requires_approval: bool
    requires_external: bool
    is_destructive: bool
    expected_change: str
    issue_message: str


class RepairPlanResponse(BaseModel):
    plan_schema_version: str
    health_score: float | None
    counts_by_level: dict[str, int]
    actionable_total: int
    manual_review_total: int
    unmapped_issue_codes: list[str]
    candidates: list[RepairCandidateSchema]


def _candidate_to_schema(c: RepairCandidate) -> RepairCandidateSchema:
    return RepairCandidateSchema(
        issue_code=c.issue_code,
        action=c.action.value,
        level=c.level.value,
        disposition=disposition_for_level(c.level),
        severity=c.severity,
        scope=c.scope,
        path=c.path,
        artist=c.artist,
        album=c.album,
        title=c.title,
        related_files=c.related_files,
        reuses_component=c.reuses_component,
        requires_approval=c.requires_approval,
        requires_external=c.requires_external,
        is_destructive=c.is_destructive,
        expected_change=c.expected_change,
        issue_message=c.issue_message,
    )


def plan_to_response(plan: RepairPlan) -> RepairPlanResponse:
    """Reines Mapping, keine Planungslogik — identisches Prinzip wie
    schemas/health.py::report_to_health_response()."""
    sorted_candidates = sorted(plan.candidates, key=lambda c: c.sort_key())
    return RepairPlanResponse(
        plan_schema_version=PLAN_SCHEMA_VERSION,
        health_score=plan.health_score,
        counts_by_level=plan.counts(),
        actionable_total=len(plan.actionable()),
        manual_review_total=len(plan.manual_review()),
        unmapped_issue_codes=sorted(plan.unmapped_issue_codes),
        candidates=[_candidate_to_schema(c) for c in sorted_candidates],
    )


class ArtistRepairSummarySchema(BaseModel):
    artist: str
    l2_count: int
    l3_count: int
    total: int


class ArtistRepairPlanResponse(BaseModel):
    plan_schema_version: str
    health_score: float | None
    artists: list[ArtistRepairSummarySchema]


def _artist_summary_to_schema(s: ArtistCandidateSummary) -> ArtistRepairSummarySchema:
    return ArtistRepairSummarySchema(
        artist=s.artist, l2_count=s.l2_count, l3_count=s.l3_count, total=s.total,
    )


class RepairHistoryEntry(BaseModel):
    """Ein Eintrag aus services/library_repair/run_tracking.py::
    load_repair_history() — gemeinsamer Run-Index ueber beide Flows
    (Finding-Repair aus repair_service.py UND Maintenance aus
    maintenance_service.py/genre_revalidation.py, siehe dortige
    append_run_record()-Aufrufstellen). Die vier Producer schreiben
    nicht identische Feldmengen (z. B. `artist`/`finding_ids`/
    `issue_codes` nur bei manchen Runs) — deshalb hier bewusst als
    Optional statt eines strikten, nur fuer einen Producer passenden
    Schemas."""

    repair_id: str
    kind: str
    level: str
    status: str
    started_at: str
    finished_at: str
    triggered_by: str
    artist: str | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    affected_files: list[str] = Field(default_factory=list)
    finding_ids: list[str] | None = None
    resolved_finding_ids: list[str] | None = None
    issue_codes: list[str] | None = None
    regressed_issue_codes: list[str] | None = None
    target_count: int | None = None


class RepairHistoryResponse(BaseModel):
    runs: list[RepairHistoryEntry]
    total: int


def repair_history_to_response(runs: list[dict], *, total: int) -> RepairHistoryResponse:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    plan_to_response(). `.get()` statt Direktzugriff, da die Feldmenge je
    Producer variiert (siehe RepairHistoryEntry-Docstring)."""
    return RepairHistoryResponse(
        runs=[
            RepairHistoryEntry(
                repair_id=r["repair_id"],
                kind=r["kind"],
                level=r["level"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                triggered_by=r["triggered_by"],
                artist=r.get("artist"),
                status_counts=r.get("status_counts") or {},
                affected_files=r.get("affected_files") or [],
                finding_ids=r.get("finding_ids"),
                resolved_finding_ids=r.get("resolved_finding_ids"),
                issue_codes=r.get("issue_codes"),
                regressed_issue_codes=r.get("regressed_issue_codes"),
                target_count=r.get("target_count"),
            )
            for r in runs
        ],
        total=total,
    )


class RepairStatisticsResponse(BaseModel):
    """Reines Passthrough-Schema fuer services/library_repair/
    run_tracking.py::compute_repair_statistics() — Feldnamen 1:1
    uebernommen (bereits eine duenne, versionslose Aggregat-Struktur,
    kein internes Objekt)."""

    total_runs: int
    total: int
    success: int
    failed: int
    skipped: int
    most_common_issue_codes: list[tuple[str, int]]


def repair_statistics_to_response(stats: dict) -> RepairStatisticsResponse:
    return RepairStatisticsResponse(**stats)


def plan_to_artist_response(plan: RepairPlan) -> ArtistRepairPlanResponse:
    """Für die geplante Control-Center-Pendant-Ansicht zur Telegram-Pro-
    Artist-Auswahl (ARCH-033 §12, `docs/LIBRARY_REPAIR.md`) — nutzt
    dieselbe reine Gruppierungsfunktion wie der Telegram-Handler
    (`services/library_repair/planner.py::group_candidates_by_artist()`,
    Default: nur L2/METADATA_REPROCESSING + L3/EXTERNAL_METADATA), bereits
    deterministisch sortiert (absteigend nach Gesamtzahl, dann
    alphabetisch) — reines Mapping, keine eigene Gruppierungslogik hier."""
    groups = group_candidates_by_artist(plan)
    return ArtistRepairPlanResponse(
        plan_schema_version=PLAN_SCHEMA_VERSION,
        health_score=plan.health_score,
        artists=[_artist_summary_to_schema(s) for s in groups.values()],
    )
