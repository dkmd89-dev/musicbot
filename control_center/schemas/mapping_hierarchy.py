# control_center/schemas/mapping_hierarchy.py
# -*- coding: utf-8 -*-
"""
Schemas der Genre-Hierarchie (genre-hierarchy) in der Mapping-Administration.

Dünne Response-Modelle über services/mapping_hierarchy.py; die Fachlogik
(Baum-Validierung, Diff, Writer) liegt ausschließlich im Service.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from services.mapping_hierarchy import (
    HierarchyChange,
    HierarchyEntry,
    HierarchyPlan,
    HierarchySaveResult,
)


class HierarchyEntrySchema(BaseModel):
    genre: str
    parent: Optional[str] = None
    depth: int
    children: int


class HierarchyListResponse(BaseModel):
    mapping_id: str
    entries: List[HierarchyEntrySchema]
    count: int
    etag: str
    warnings: List[str] = Field(default_factory=list)
    bot_reload_required: bool = True


class HierarchyBody(BaseModel):
    """Gewünschter Endzustand: eine Zeile je Genre, `parent` leer/null = Wurzel."""

    entries: List[dict]


class HierarchySaveBody(HierarchyBody):
    etag: str


class HierarchyChangeSchema(BaseModel):
    genre: str
    kind: str
    old_parent: Optional[str] = None
    new_parent: Optional[str] = None
    old_depth: Optional[int] = None
    new_depth: Optional[int] = None
    affected: List[str] = Field(default_factory=list)
    affected_count: int = 0


class HierarchyPreviewResponse(BaseModel):
    mapping_id: str
    change: str
    added: List[str]
    removed: List[str]
    changed: List[str]
    changes: List[HierarchyChangeSchema]
    entries: List[HierarchyEntrySchema]
    warnings: List[str] = Field(default_factory=list)
    etag: str
    # Der Writer ändert nur betroffene Zeilen; Kommentare bleiben erhalten.
    comment_warning: Optional[str] = None


class HierarchySaveResponse(HierarchyPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


HIERARCHY_SAVE_MESSAGE_WRITTEN = (
    "Gespeichert. Für neue Downloads ist ein Bot-Neustart erforderlich: "
    "der Bot lädt genre_hierarchy.yaml beim Start."
)
HIERARCHY_SAVE_MESSAGE_UNCHANGED = "Hierarchie war bereits identisch — nichts geschrieben."


def entry_to_schema(entry: HierarchyEntry) -> HierarchyEntrySchema:
    return HierarchyEntrySchema(
        genre=entry.genre, parent=entry.parent, depth=entry.depth, children=entry.children,
    )


def _change_to_schema(change: HierarchyChange) -> HierarchyChangeSchema:
    return HierarchyChangeSchema(
        genre=change.genre, kind=change.kind, old_parent=change.old_parent, new_parent=change.new_parent,
        old_depth=change.old_depth, new_depth=change.new_depth,
        affected=list(change.affected), affected_count=change.affected_count,
    )


def plan_to_preview(plan: HierarchyPlan) -> HierarchyPreviewResponse:
    return HierarchyPreviewResponse(
        mapping_id=plan.mapping_id,
        change=plan.change,
        added=list(plan.added),
        removed=list(plan.removed),
        changed=list(plan.changed),
        changes=[_change_to_schema(c) for c in plan.changes],
        entries=[entry_to_schema(e) for e in plan.entries],
        warnings=list(plan.warnings),
        etag=plan.etag,
    )


def save_to_response(plan: HierarchyPlan, result: HierarchySaveResult) -> HierarchySaveResponse:
    base = plan_to_preview(plan)
    return HierarchySaveResponse(
        **base.model_dump(),
        written=result.written,
        unchanged=result.unchanged,
        new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=HIERARCHY_SAVE_MESSAGE_WRITTEN if result.written else HIERARCHY_SAVE_MESSAGE_UNCHANGED,
    )
