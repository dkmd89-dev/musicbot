# control_center/schemas/mapping_status.py
# -*- coding: utf-8 -*-
"""Duenne Response-Modelle fuer den Runtime-Status der Mapping-Dateien."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

from services.mapping_runtime_state import RuntimeEvaluation


class MappingRuntimeStatusSchema(BaseModel):
    mapping_id: str
    filename: str
    state: Literal["applied", "pending_restart", "unknown", "unavailable"]
    message: str
    saved_sha256: Optional[str] = None
    loaded_sha256: Optional[str] = None
    note: Optional[str] = None


class MappingStatusResponse(BaseModel):
    snapshot_status: str
    bot_running: bool
    bot_started_at: Optional[str] = None
    age_seconds: Optional[float] = None
    statuses: List[MappingRuntimeStatusSchema]


def evaluation_to_response(evaluation: RuntimeEvaluation) -> MappingStatusResponse:
    return MappingStatusResponse(
        snapshot_status=evaluation.snapshot_status, bot_running=evaluation.bot_running,
        bot_started_at=evaluation.bot_started_at, age_seconds=evaluation.age_seconds,
        statuses=[MappingRuntimeStatusSchema(**vars(s)) for s in evaluation.statuses],
    )
