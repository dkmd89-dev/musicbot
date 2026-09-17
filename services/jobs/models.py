# services/jobs/models.py
# -*- coding: utf-8 -*-
"""
Jobs — Domain-Modelle (Vertical Slice "Jobs-Grundgerüst", Nachtrag zum
MusicBot Control Center, Phase 1: nur Infrastruktur, noch keine echte
Job-Ausführung — siehe services/jobs/job_registry.py-Docstring).

Reine Datencontainer, kein I/O, kein Telegram-/Web-Bezug — analog zu
services/library_health/models.py bzw. services/library_repair/models.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    """Zustand eines einzelnen Jobs. Rein In-Memory (siehe JobRegistry) —
    kein Anspruch auf Persistenz über einen Prozess-Neustart hinweg."""

    job_id: str
    kind: str
    initiator: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    created_at: str = field(default_factory=now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "initiator": self.initiator,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }
