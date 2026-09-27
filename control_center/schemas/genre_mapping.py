# control_center/schemas/genre_mapping.py
# -*- coding: utf-8 -*-
"""
Schemas fuer die Genre-Mapping-Bearbeitung (Primary + Secondary) eines Artists:

  GET  /api/v1/library/artists/{artist}/genre-mapping
  POST /api/v1/library/artists/{artist}/genre-mapping/preview
  PUT  /api/v1/library/artists/{artist}/genre-mapping

Duenne Abbildung von services/library_repair/genre.py (GenreMappingEntry /
GenreMappingPlan / ManualMappingSaveResult) — keine eigene Fachlogik.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.library_repair.genre import (
    GenreMappingEntry,
    GenreMappingPlan,
    ManualMappingSaveResult,
)


class GenreMappingBody(BaseModel):
    primary: str
    secondary: list[str] = Field(default_factory=list)


class GenreMappingSaveBody(GenreMappingBody):
    """`etag` stammt aus GET/Preview: der Eintrag wird nur geschrieben, wenn er
    seitdem unveraendert ist (sonst HTTP 409)."""

    etag: str


class GenreMappingEntrySchema(BaseModel):
    key: str
    primary: str
    secondary: list[str]
    description: str | None = None


class GenreMappingResponse(BaseModel):
    artist: str
    exists: bool
    entry: GenreMappingEntrySchema | None = None
    etag: str
    known_genres: list[str]


class GenreMappingPreviewResponse(BaseModel):
    artist: str
    artist_key: str
    change: str  # create | update | unchanged
    existing: GenreMappingEntrySchema | None = None
    primary: str
    secondary: list[str]
    primary_changed: bool
    added: list[str]
    removed: list[str]
    warnings: list[str]
    etag: str


class GenreMappingSaveResponse(GenreMappingPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


def entry_to_schema(entry: GenreMappingEntry | None) -> GenreMappingEntrySchema | None:
    if entry is None:
        return None
    return GenreMappingEntrySchema(
        key=entry.key, primary=entry.primary, secondary=list(entry.secondary),
        description=None if entry.description is None else str(entry.description),
    )


def plan_to_preview(artist: str, plan: GenreMappingPlan) -> GenreMappingPreviewResponse:
    return GenreMappingPreviewResponse(
        artist=artist, artist_key=plan.artist_key, change=plan.change,
        existing=entry_to_schema(plan.existing), primary=plan.primary,
        secondary=list(plan.secondary), primary_changed=plan.primary_changed,
        added=list(plan.added), removed=list(plan.removed),
        warnings=list(plan.warnings), etag=plan.etag,
    )


SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot lädt artist_genre.yaml beim Start: "
    "für NEUE Downloads wirkt die Änderung erst nach einem Bot-Neustart. "
    "Bereits getaggte Dateien werden über „Genre setzen“ angepasst."
)
SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def save_to_response(
    artist: str, plan: GenreMappingPlan, result: ManualMappingSaveResult, new_etag: str,
) -> GenreMappingSaveResponse:
    base = plan_to_preview(artist, plan)
    return GenreMappingSaveResponse(
        **base.model_dump(),
        written=result.written, unchanged=result.unchanged, new_etag=new_etag,
        bot_reload_required=result.written,
        message=SAVE_MESSAGE_WRITTEN if result.written else SAVE_MESSAGE_UNCHANGED,
    )
