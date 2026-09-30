# control_center/schemas/mapping_yaml.py
# -*- coding: utf-8 -*-
"""Duenne Modelle fuer den YAML-Editor der Mapping-Administration."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from services.mapping_yaml import RawFile, RawPlan, RawResult


class RawFileResponse(BaseModel):
    mapping_id: str
    filename: str
    text: str
    etag: str
    size: int
    max_bytes: int


class RawBody(BaseModel):
    text: str


class RawSaveBody(RawBody):
    etag: str


class RawPreviewResponse(BaseModel):
    mapping_id: str
    change: str
    added: List[str]
    removed: List[str]
    changed: List[str]
    warnings: List[str] = Field(default_factory=list)
    text_diff: List[str] = Field(default_factory=list)
    etag: str


class RawSaveResponse(RawPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool
    message: str


RAW_MESSAGE_WRITTEN = (
    "YAML gespeichert. Der laufende Bot lädt die Mapping-Dateien beim Start: "
    "die Änderung wirkt für neue Downloads erst nach Bot-Neustart."
)
RAW_MESSAGE_UNCHANGED = "Der Text entspricht bereits der Datei — nichts geschrieben."


def file_to_response(raw: RawFile) -> RawFileResponse:
    return RawFileResponse(
        mapping_id=raw.mapping_id, filename=raw.filename, text=raw.text, etag=raw.etag,
        size=raw.size, max_bytes=raw.max_bytes,
    )


def plan_to_preview(plan: RawPlan) -> RawPreviewResponse:
    return RawPreviewResponse(
        mapping_id=plan.mapping_id, change=plan.change, added=list(plan.added), removed=list(plan.removed),
        changed=list(plan.changed), warnings=list(plan.warnings), text_diff=list(plan.text_diff), etag=plan.etag,
    )


def result_to_response(plan: RawPlan, result: RawResult) -> RawSaveResponse:
    return RawSaveResponse(
        **plan_to_preview(plan).model_dump(),
        written=result.written, unchanged=result.unchanged, new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=RAW_MESSAGE_WRITTEN if result.written else RAW_MESSAGE_UNCHANGED,
    )
