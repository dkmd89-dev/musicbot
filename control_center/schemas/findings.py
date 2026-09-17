# control_center/schemas/findings.py
# -*- coding: utf-8 -*-
"""
Response-Schemas fuer GET /api/v1/library/findings (+ /summary) sowie
POST .../accept und .../unaccept.

Wie schemas/health.py bewusst kein 1:1-Durchreichen der internen
Finding-Dataclass (services/library_health/findings.py::Finding) — Felder,
die reine Review-/Audit-Historie sind (reviewed_by, resolved_at,
resolved_by_scan_at, reopened_at, history) sind bei der Findings-LISTE
NICHT Teil der Response (siehe FindingSchema unten). Diese Route zeigt
ausschliesslich aktuell OFFENE Findings
(services/library_health/findings.py::group_open_findings_by_category()
liefert per Definition nur STATUS_OPEN).

FindingActionResponse (Accept/Unaccept) zeigt dagegen bewusst reviewed_at/
reviewed_by/review_note — das IST hier der Zweck der Response (Bestaetigung
der durchgefuehrten Aktion inkl. Audit-Spur), keine unpassende Symmetrie
zu FindingSchema noetig.
"""

from __future__ import annotations

from pydantic import BaseModel

from services.library_health.findings import CategoryGroup, Finding, ReviewSummary


class FindingSchema(BaseModel):
    finding_id: str
    code: str
    scope: str
    status: str
    artist: str | None
    album: str | None
    title: str | None
    path: str | None
    message: str
    severity: str | None
    confidence: str | None
    occurrences: int
    first_seen: str
    last_seen: str


class FindingCategoryGroup(BaseModel):
    code: str
    tier: str
    open_count: int
    findings: list[FindingSchema]


class FindingsSummaryResponse(BaseModel):
    open: int
    repaired: int
    accepted: int
    accepted_stale: int
    resolved_by_scan: int
    total: int


class AcceptFindingRequest(BaseModel):
    reason: str = ""


class UnacceptFindingRequest(BaseModel):
    note: str | None = None


class FindingActionResponse(BaseModel):
    finding_id: str
    status: str
    reviewed_at: str | None
    reviewed_by: str | None
    review_note: str | None


def _finding_to_schema(finding: Finding) -> FindingSchema:
    return FindingSchema(
        finding_id=finding.finding_id,
        code=finding.code,
        scope=finding.scope,
        status=finding.status,
        artist=finding.artist,
        album=finding.album,
        title=finding.title,
        path=finding.path,
        message=finding.message,
        severity=finding.severity,
        confidence=finding.confidence,
        occurrences=finding.occurrences,
        first_seen=finding.first_seen,
        last_seen=finding.last_seen,
    )


def category_groups_to_schema(groups: list[CategoryGroup]) -> list[FindingCategoryGroup]:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    control_center/schemas/health.py::report_to_health_response()."""
    return [
        FindingCategoryGroup(
            code=g.code,
            tier=g.tier,
            open_count=g.open_count,
            findings=[_finding_to_schema(f) for f in g.findings],
        )
        for g in groups
    ]


def review_summary_to_schema(summary: ReviewSummary) -> FindingsSummaryResponse:
    return FindingsSummaryResponse(**summary.to_dict())


def finding_to_action_response(finding: Finding) -> FindingActionResponse:
    return FindingActionResponse(
        finding_id=finding.finding_id,
        status=finding.status,
        reviewed_at=finding.reviewed_at,
        reviewed_by=finding.reviewed_by,
        review_note=finding.review_note,
    )
