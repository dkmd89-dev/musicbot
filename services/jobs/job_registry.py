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

from .models import Job, JobEvent, JobStatus, now_iso


class JobRegistry:
    # D.12b: Obergrenze für Job.events - bei Überlauf fallen die ältesten
    # Einträge weg (Playlists erzeugen einen Eintrag pro Track).
    MAX_JOB_EVENTS = 100

    def __init__(self, logger_factory=None):
        self._jobs: Dict[str, Job] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.logger = (logger_factory or get_module_logger)("JobRegistry")

    def create(self, kind: str, initiator: str, context: Optional[dict] = None) -> Job:
        job_id = uuid.uuid4().hex
        job = Job(job_id=job_id, kind=kind, initiator=initiator, context=context)
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

    def _append_event(self, job: Job, message: str, progress: Optional[float] = None) -> bool:
        """D.12b: hängt einen Verlaufseintrag an (Aufrufer hält self._lock).
        Aufeinanderfolgende identische Meldungen werden nicht doppelt
        erfasst. Liefert True, wenn ein Eintrag angehängt wurde (dann loggt
        der Aufrufer ihn ausserhalb des Locks via _log_event())."""
        if job.events and job.events[-1].message == message:
            return False
        job.events.append(JobEvent(at=now_iso(), message=message, progress=progress))
        if len(job.events) > self.MAX_JOB_EVENTS:
            del job.events[: len(job.events) - self.MAX_JOB_EVENTS]
        return True

    def _log_event(self, job_id: str, message: str) -> None:
        # Verkürzte Job-ID als Korrelationsschlüssel in control_center.log
        # (Volltextsuche im Log-Dashboard).
        self.logger.info(f"🧩 [JOB {job_id[:8]}] {message}")

    def mark_running(self, job_id: str) -> None:
        appended = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.RUNNING
                job.started_at = now_iso()
                appended = self._append_event(job, "Gestartet", job.progress)
        if appended:
            self._log_event(job_id, "Gestartet")

    def update_progress(self, job_id: str, progress: float, message: str = "") -> None:
        appended = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.progress = progress
                if message:
                    job.message = message
                    appended = self._append_event(job, message, progress)
        if appended:
            self._log_event(job_id, message)

    def mark_succeeded(self, job_id: str, result: Optional[dict] = None) -> None:
        appended = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.SUCCEEDED
                job.progress = 100.0
                job.result = result
                job.finished_at = now_iso()
                appended = self._append_event(job, "Abgeschlossen", 100.0)
        if appended:
            self._log_event(job_id, "Abgeschlossen")

    def mark_failed(self, job_id: str, error: str, result: Optional[dict] = None) -> None:
        """`result` optional (Nachtrag Phase 2/Repair-Execution): ein Job
        kann fehlschlagen, aber trotzdem Diagnosedaten liefern (z. B.
        Subprozess-stdout bei einem Exit-Code != 0) — Job.result ist
        unabhängig vom Status bereits im Modell vorgesehen."""
        event_message = f"Fehlgeschlagen: {error}" if error else "Fehlgeschlagen"
        appended = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = error
                job.result = result
                job.finished_at = now_iso()
                appended = self._append_event(job, event_message, job.progress)
        if appended:
            self._log_event(job_id, event_message)

    def mark_cancelled(self, job_id: str) -> None:
        appended = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED
                job.finished_at = now_iso()
                appended = self._append_event(job, "Abgebrochen", job.progress)
        if appended:
            self._log_event(job_id, "Abgebrochen")

    def request_cancel(self, job_id: str) -> bool:
        """Fordert den Abbruch an (thread-sicher, analog
        ActiveDownload.request_cancel()). Liefert False bei unbekannter
        job_id, sonst True — der Job selbst muss is_cancel_requested()
        aktiv abfragen (kooperatives Abbrechen, kein hartes Kill)."""
        appended = False
        with self._lock:
            event = self._cancel_events.get(job_id)
            job = self._jobs.get(job_id)
            # Nur für noch laufende Jobs protokollieren - ein Cancel auf
            # einen bereits beendeten Job ändert nichts am Ergebnis.
            if event is not None and job is not None and job.finished_at is None and not event.is_set():
                appended = self._append_event(job, "Abbruch angefordert", job.progress)
        if event is None:
            return False
        event.set()
        if appended:
            self._log_event(job_id, "Abbruch angefordert")
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        return event.is_set() if event is not None else False
