# services/library_repair/models.py
# -*- coding: utf-8 -*-
"""
Smart Library Repair — Domain-Modelle (Phase 2).

Reine Datencontainer + Enums. Analog zu services/library_health/models.py.

Der Repair Planner ist **read-only** — er klassifiziert Health-Issues zu
Reparaturaktionen und erzeugt einen Plan. Die tatsaechliche Ausfuehrung
(Executor) ist ein separater, explizit geschuetzter Schritt (--apply,
Phase 2 PR 2+).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

PLAN_SCHEMA_VERSION = "1.0"


class RepairLevel(str, Enum):
    """Sicherheitsstufe einer Reparatur (Prompt Abschnitt 6-11)."""

    SAFE_AUTOMATIC = "SAFE_AUTOMATIC"          # L1: deterministisch aus vorhandenen Daten
    METADATA_REPROCESSING = "METADATA_REPROCESSING"  # L2: reprocess_artist_metadata.py
    EXTERNAL_METADATA = "EXTERNAL_METADATA"    # L3: MusicBrainz-/Metadata-Pipeline
    COVER = "COVER"                            # CoverProcessor
    LOUDNESS = "LOUDNESS"                      # normalize_test_library_loudness.py
    DUPLICATE = "DUPLICATE"                    # resolve_duplicates.py
    MANUAL_REVIEW = "MANUAL_REVIEW"            # kein sicherer automatischer Pfad
    NOT_REPAIRABLE = "NOT_REPAIRABLE"          # reine Beobachtung / nichts zu tun


class RepairAction(str, Enum):
    """Konkrete Aktion. Jede bildet auf eine BESTEHENDE Komponente ab —
    keine neue Reparaturlogik in diesem Layer (Prompt Abschnitt 21)."""

    GENRE_DELIMITER_NORMALIZE = "GENRE_DELIMITER_NORMALIZE"
    MULTI_ARTIST_SPLIT = "MULTI_ARTIST_SPLIT"
    FILENAME_RENAME_IN_PLACE = "FILENAME_RENAME_IN_PLACE"
    TRACK_NUMBER_FIX = "TRACK_NUMBER_FIX"
    METADATA_REPROCESS = "METADATA_REPROCESS"
    EXTERNAL_ID_LOOKUP = "EXTERNAL_ID_LOOKUP"
    COVER_FETCH = "COVER_FETCH"
    LOUDNESS_NORMALIZE = "LOUDNESS_NORMALIZE"
    DUPLICATE_RESOLVE = "DUPLICATE_RESOLVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NONE = "NONE"


@dataclass(frozen=True)
class RepairSpec:
    """Statische Zuordnung Issue-Code -> Reparatur (Registry in planner.py)."""

    issue_code: str
    action: RepairAction
    level: RepairLevel
    reuses_component: str            # welche bestehende Komponente ausfuehrt
    requires_approval: bool          # muss der Nutzer zustimmen?
    requires_external: bool          # braucht es einen externen Dienst?
    is_destructive: bool             # kann Daten/Struktur verlieren?
    expected_change: str             # was wuerde sich aendern


@dataclass
class RepairCandidate:
    """Eine geplante Reparatur fuer genau ein Health-Issue."""

    issue_code: str
    action: RepairAction
    level: RepairLevel
    severity: str
    scope: str
    path: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    related_files: list[str] = field(default_factory=list)
    reuses_component: str = ""
    requires_approval: bool = True
    requires_external: bool = False
    is_destructive: bool = False
    expected_change: str = ""
    issue_message: str = ""

    def sort_key(self) -> tuple:
        return (self.level.value, self.issue_code, self.path or "",
                self.artist or "", self.album or "")

    def to_dict(self) -> dict:
        return {
            "issue_code": self.issue_code,
            "action": self.action.value,
            "level": self.level.value,
            "severity": self.severity,
            "scope": self.scope,
            "path": self.path,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "related_files": self.related_files,
            "reuses_component": self.reuses_component,
            "requires_approval": self.requires_approval,
            "requires_external": self.requires_external,
            "is_destructive": self.is_destructive,
            "expected_change": self.expected_change,
            "issue_message": self.issue_message,
        }


@dataclass
class RepairPlan:
    """Vollstaendiger, deterministisch sortierter Reparaturplan."""

    library_root: str
    health_score: Optional[float]
    candidates: list[RepairCandidate] = field(default_factory=list)
    unmapped_issue_codes: list[str] = field(default_factory=list)

    # ── Aggregation ────────────────────────────────────────────────────
    def by_level(self) -> dict[str, list[RepairCandidate]]:
        out: dict[str, list[RepairCandidate]] = {}
        for c in self.candidates:
            out.setdefault(c.level.value, []).append(c)
        return out

    def counts(self) -> dict[str, int]:
        levels = self.by_level()
        return {lvl: len(cs) for lvl, cs in sorted(levels.items())}

    def manual_review(self) -> list[RepairCandidate]:
        return [c for c in self.candidates if c.level is RepairLevel.MANUAL_REVIEW]

    def actionable(self) -> list[RepairCandidate]:
        """Alles ausser MANUAL_REVIEW / NOT_REPAIRABLE."""
        skip = {RepairLevel.MANUAL_REVIEW, RepairLevel.NOT_REPAIRABLE}
        return [c for c in self.candidates if c.level not in skip]

    def to_dict(self) -> dict:
        return {
            "plan_schema_version": PLAN_SCHEMA_VERSION,
            "library_root": self.library_root,
            "health_score": self.health_score,
            "counts_by_level": self.counts(),
            "actionable_total": len(self.actionable()),
            "manual_review_total": len(self.manual_review()),
            "unmapped_issue_codes": sorted(self.unmapped_issue_codes),
            "candidates": [c.to_dict() for c in
                           sorted(self.candidates, key=lambda c: c.sort_key())],
        }
