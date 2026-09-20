# control_center/schemas/logs.py
# -*- coding: utf-8 -*-
"""
Response-Schema für GET /api/v1/logs.

Dünnes Mapping über services/logs/reader.py::read_logs() hinweg —
identisches Prinzip wie die übrigen schemas/*.py (kein 1:1-Durchreichen
interner Dataclasses).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from services.logs.reader import LogEntry


class LogEntrySchema(BaseModel):
    time: str
    level: Optional[str]
    component: Optional[str]
    message: str


class LogsResponse(BaseModel):
    source: str
    available_sources: list[str]
    total_matched: int
    limit: int
    entries: list[LogEntrySchema]


def _entry_to_schema(entry: LogEntry) -> LogEntrySchema:
    return LogEntrySchema(
        time=entry.time, level=entry.level, component=entry.component, message=entry.message,
    )


def logs_result_to_response(result: dict) -> LogsResponse:
    return LogsResponse(
        source=result["source"],
        available_sources=result["available_sources"],
        total_matched=result["total_matched"],
        limit=result["limit"],
        entries=[_entry_to_schema(e) for e in result["entries"]],
    )
