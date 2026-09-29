# services/jobs/job_context.py
# -*- coding: utf-8 -*-
"""
Task-lokale Job-ID (Client Consolidation D.12b.2).

Zweck: Log-Zeilen, die waehrend eines laufenden Jobs entstehen, mit
einer Job-ID anreichern — OHNE Signaturen in der Download-/Metadaten-
Kette zu aendern. Analog zu services/jobs/step_context.py (dort: feine
Schritte), hier: die Job-Identitaet selbst.

Warum contextvars: bis zu MAX_CONCURRENT_DOWNLOADS Jobs laufen parallel
in einem Prozess ueber denselben Logger. ContextVar ist pro asyncio-Task
isoliert (asyncio.create_task kopiert den Kontext; siehe step_context.py)
— Job-IDs koennen sich dadurch nicht vermischen.

Ohne gesetzte Job-ID (Telegram-Pfad, scripts/, Tests) liefert
get_current_job_id() None; der logger.py-Filter setzt dann
record.job_id = "-" und das Format bleibt optisch unveraendert.

Kein logger.py-Import hier — das waere ein Zyklus. logger.py importiert
get_current_job_id() aus diesem Modul.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_current_job_id: ContextVar[Optional[str]] = ContextVar(
    "musicbot_current_job_id", default=None
)


@contextmanager
def bind_job(job_id: Optional[str]) -> Iterator[None]:
    """Bindet `job_id` an die aktuelle Task (und alle daraus abgeleiteten
    Tasks/Threads via create_task / to_thread). Am Ende wird der vorherige
    Zustand sicher wiederhergestellt — verschachtelte bind_job-Aufrufe
    sind erlaubt."""
    token = _current_job_id.set(job_id)
    try:
        yield
    finally:
        _current_job_id.reset(token)


def get_current_job_id() -> Optional[str]:
    """Aktuelle Job-ID oder None (Default, kein Job-Kontext)."""
    return _current_job_id.get()
