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

from pydantic import BaseModel

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
