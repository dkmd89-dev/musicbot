# control_center/schemas/runtime_snapshot.py
# -*- coding: utf-8 -*-
"""Schemas für GET /api/v1/admin/runtime-snapshot (E1, Bot-Laufzeit-
Snapshot) - bewusst schlank, kein 1:1-Durchreichen der Snapshot-Datei."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class RecentErrorResponse(BaseModel):
    id: Optional[str] = None
    timestamp: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    module: Optional[str] = None
    message: str = ""


class ErrorSnapshotResponse(BaseModel):
    total_exceptions: int = 0
    by_category: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_module: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    total_handled: int = 0
    avg_processing_time: float = 0.0
    recovery_success_rate: float = 0.0
    recent: List[RecentErrorResponse] = []


class DuplicateSessionResponse(BaseModel):
    total_checks: int = 0
    url_duplicates_found: int = 0
    content_duplicates_found: int = 0
    new_entries_added: int = 0
    duplicates_skipped: int = 0
    duplicate_rate: float = 0.0
    savings_percentage: float = 0.0


class RuntimeSnapshotResponse(BaseModel):
    status: Literal["available", "stale", "missing", "corrupt"]
    message: Optional[str] = None
    age_seconds: Optional[float] = None
    generated_at: Optional[str] = None
    bot_started_at: Optional[str] = None
    interval_seconds: Optional[int] = None
    errors: Optional[ErrorSnapshotResponse] = None
    duplicates: Optional[DuplicateSessionResponse] = None


def _int_map(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in value.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def snapshot_result_to_response(result: Dict[str, Any]) -> RuntimeSnapshotResponse:
    """Reines Mapping von services/bot_runtime_snapshot.py::
    read_bot_runtime_snapshot() - keine Fachlogik."""
    snap = result.get("snapshot") or {}
    sections = snap.get("sections") or {}
    errors = None
    raw_errors = sections.get("errors")
    if isinstance(raw_errors, dict):
        stats = raw_errors.get("stats") or {}
        perf = raw_errors.get("performance") or {}
        errors = ErrorSnapshotResponse(
            total_exceptions=int(stats.get("total_exceptions") or 0),
            by_category=_int_map(stats.get("by_category")),
            by_severity=_int_map(stats.get("by_severity")),
            by_module=_int_map(stats.get("by_module")),
            by_type=_int_map(stats.get("by_type")),
            total_handled=int(perf.get("total_handled") or 0),
            avg_processing_time=float(perf.get("avg_processing_time") or 0.0),
            recovery_success_rate=float(perf.get("recovery_success_rate") or 0.0),
            recent=[
                RecentErrorResponse(**{k: e.get(k) for k in RecentErrorResponse.model_fields if k in e})
                for e in (raw_errors.get("recent") or [])
                if isinstance(e, dict)
            ],
        )
    duplicates = None
    raw_dup = sections.get("duplicates")
    if isinstance(raw_dup, dict):
        duplicates = DuplicateSessionResponse(
            **{k: raw_dup[k] for k in DuplicateSessionResponse.model_fields if k in raw_dup}
        )
    return RuntimeSnapshotResponse(
        status=result["status"],
        message=result.get("message"),
        age_seconds=result.get("age_seconds"),
        generated_at=snap.get("generated_at"),
        bot_started_at=snap.get("bot_started_at"),
        interval_seconds=snap.get("interval_seconds"),
        errors=errors,
        duplicates=duplicates,
    )
