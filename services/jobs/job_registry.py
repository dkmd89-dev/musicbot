# services/jobs/job_registry.py
# -*- coding: utf-8 -*-
"""
JobRegistry — prozessweite Registry für Control-Center-Jobs (Vertical
Slice "Jobs-Grundgerüst", Phase 1: nur Infrastruktur).

Zustandsmuster identisch zu services/downloader/active_downloads.py::
ActiveDownloadRegistry: EINE Instanz pro Prozess (hier: pro
control_center-Server-Prozess — gehalten in app.state.job_registry, siehe
control_center/app.py), threading.Lock statt asyncio.Lock, weil sowohl
async Tasks (Event Loop, für laufende Jobs) als auch sync Route-Handler
(Threadpool, für Status-Abfragen) darauf zugreifen — ein asyncio.Lock
wäre dafür nicht sicher.

Nur In-Memory — Jobs überleben einen Prozess-Neustart NICHT (bewusst, wie
ActiveDownloadRegistry: keine Anforderung für Persistenz über einen
Neustart hinweg in diesem Schritt).

Phase 1 (dieser Schritt) kennt nur einen einzigen, klar als Test-/
Demo-Fähigkeit gekennzeichneten Job-Typ ("demo_progress",
control_center/routers/jobs.py) — kein echter Job führt in diesem
Schritt eine reale Operation aus (Master-Prompt Regel 39: keine Fake-
Implementierung, die wie eine fertige Funktion aussieht — deshalb der
eindeutige "demo"-Name statt eines allgemein klingenden Platzhalters).
Repair-Execution als erster echter Job-Typ ist ein eigener, separat
freizugebender Folgeschritt.
"""

from __future__ import annotations

import threading
import uuid
from typing import Dict, List, Optional

from logger import get_module_logger

from .models import Job, JobStatus, now_iso


class JobRegistry:
    def __init__(self, logger_factory=None):
        self._jobs: Dict[str, Job] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.logger = (logger_factory or get_module_logger)("JobRegistry")

    def create(self, kind: str, initiator: str) -> Job:
        job_id = uuid.uuid4().hex
        job = Job(job_id=job_id, kind=kind, initiator=initiator)
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = threading.Event()
        self.logger.info(f"🧩 [JOB] erstellt: {job_id} kind={kind} initiator={initiator}")
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> List[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.RUNNING
                job.started_at = now_iso()

    def update_progress(self, job_id: str, progress: float, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.progress = progress
                if message:
                    job.message = message

    def mark_succeeded(self, job_id: str, result: Optional[dict] = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.SUCCEEDED
                job.progress = 100.0
                job.result = result
                job.finished_at = now_iso()

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = error
                job.finished_at = now_iso()

    def mark_cancelled(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED
                job.finished_at = now_iso()

    def request_cancel(self, job_id: str) -> bool:
        """Fordert den Abbruch an (thread-sicher, analog
        ActiveDownload.request_cancel()). Liefert False bei unbekannter
        job_id, sonst True — der Job selbst muss is_cancel_requested()
        aktiv abfragen (kooperatives Abbrechen, kein hartes Kill)."""
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        return event.is_set() if event is not None else False
