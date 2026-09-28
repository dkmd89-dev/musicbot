# services/jobs/step_context.py
# -*- coding: utf-8 -*-
"""
Task-lokaler Schritt-Melder (Client Consolidation D.12c).

Zweck: feine Verarbeitungsschritte (z. B. aus
EnhancedMetadataProcessor.process_single_track()) einem laufenden
Control-Center-Job zuordnen, OHNE Signaturen in der P0-Download-/
Metadaten-Kette zu ändern.

Warum contextvars statt Callback-Attribut: EnhancedMetadataProcessor ist
ein Singleton, im CC-Prozess laufen bis zu MAX_CONCURRENT_DOWNLOADS Jobs
parallel über dieselbe Instanz. Ein ContextVar ist pro asyncio-Task
isoliert (jede Task erhält beim Erstellen eine Kopie des Kontexts,
asyncio.to_thread() reicht ihn ebenfalls weiter) — Schritte verschiedener
Jobs können sich dadurch nicht vermischen.

Ohne gesetzten Melder (Telegram-Pfad im Bot-Prozess, scripts/, Tests)
ist report_step() wirkungslos. Ein Fehler im Melder wird geschluckt und
darf die aufrufende Pipeline nie unterbrechen.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

from logger import get_module_logger

_logger = get_module_logger("step_context")

_current_reporter: ContextVar[Optional[Callable[[str], None]]] = ContextVar(
    "musicbot_step_reporter", default=None
)


@contextmanager
def step_reporter(callback: Callable[[str], None]) -> Iterator[None]:
    """Setzt `callback` als Schritt-Melder für die aktuelle Task (und
    alle daraus abgeleiteten Tasks/Threads) und setzt ihn am Ende sicher
    zurück."""
    token = _current_reporter.set(callback)
    try:
        yield
    finally:
        _current_reporter.reset(token)


def report_step(message: str) -> None:
    """Meldet einen Schritt an den aktuell gesetzten Melder — No-op, wenn
    keiner gesetzt ist. Muss synchron und nebenwirkungsfrei für den
    Aufrufer bleiben."""
    callback = _current_reporter.get()
    if callback is None:
        return
    try:
        callback(message)
    except Exception as e:  # noqa: BLE001 - Melder darf die Pipeline nie stören
        _logger.warning(f"Schritt-Melder fehlgeschlagen (ignoriert): {e!r}")
