# services/downloader/download_concurrency.py
# -*- coding: utf-8 -*-
"""
Cross-Process-Download-Concurrency (Client Consolidation Phase D/E,
Nachtrag docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md
Abschnitt 11).

Hintergrund: `klassen/download_handler.py::_get_download_semaphore()`
begrenzt aktive Downloads bisher über ein modulglobales
`asyncio.Semaphore` — das ist faktisch prozessglobal (nicht wirklich
"MAX_CONCURRENT_DOWNLOADS insgesamt"), weil bislang nur ein
downloadfähiger Prozess existierte (der Bot). Mit einem zweiten,
eigenständigen Download-Pfad im Control-Center-Prozess (JobRegistry,
siehe FINDINGS_INDEX.md "Downloads nicht aus dem Control Center
startbar") würde ein zweites, unabhängiges Semaphore diese Grenze nicht
mehr durchsetzen — die Summe paralleler Downloads über beide Prozesse
könnte MAX_CONCURRENT_DOWNLOADS überschreiten.

Mechanismus (Architekturentscheidung "Option B"): `MAX_CONCURRENT_DOWNLOADS`
Slot-Dateien unter `Config.DATA_DIR/download_slots/`, atomar belegt über
`os.open(O_CREAT|O_EXCL|O_WRONLY)` — dieselbe, im Projekt bereits
produktive Grundidee wie
`services/library_repair/run_tracking.py::acquire_repair_lock()`, hier
von einem Mutex (1 Slot) auf einen Zähler (N Slots) erweitert. Bot- und
Control-Center-Prozess rufen exakt denselben Helfer auf — keine zweite
Zählimplementierung.

WICHTIG (Regel 2, "Bestehendes Verhalten nicht unbewusst ändern"): das
bisherige `asyncio.Semaphore`-Verhalten ist ein WARTENDER Erwerb (ein
Download, der keinen Platz bekommt, wird nicht abgelehnt, sondern
gequeued, bis ein Platz frei wird) - kein Fail-Fast wie bei
`acquire_repair_lock()`. `acquire_download_slot()` bildet das bewusst
nach (Poll-Loop statt sofortigem Fehler), damit der Wechsel auf den
Cross-Process-Mechanismus dieses Warteverhalten nicht stillschweigend
in ein Fail-Fast-Verhalten ändert.

Verwaiste Slots (Prozessabsturz, Nutzerentscheidung 2026-09-28): NUR
Diagnose (PID+Timestamp im Slot-Inhalt, identisch zum bestehenden
Repair-Lock-Format `"<pid>|<iso-timestamp>"`, siehe `read_slot_info()`).
KEIN automatisches Freigeben — identisches Verhalten zum bestehenden
Repair-Lock (kein Stale-Timeout, keine PID-Liveness-Prüfung), keine neue
Fehlerklasse (PID-Wiederverwendung, falsches TTL-Timing) eingeführt.
Aufräumen eines verwaisten Slots bleibt eine manuelle/Admin-Aufgabe.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from config import Config
from logger import get_module_logger

logger = get_module_logger("DownloadConcurrency")

SLOTS_DIRNAME = "download_slots"
DEFAULT_POLL_INTERVAL_SECONDS = 0.5


def slots_dir() -> Path:
    return Path(Config.DATA_DIR) / SLOTS_DIRNAME


def slot_path(index: int) -> Path:
    return slots_dir() / f"slot_{index}.lock"


@dataclass
class SlotInfo:
    """Diagnosedaten eines belegten Slots - siehe Modul-Docstring
    ("nur Diagnose, kein Auto-Release")."""

    index: int
    pid: int
    since: str


def _try_acquire_slot(index: int) -> bool:
    """Atomarer Belegungsversuch für genau einen Slot. Liefert False bei
    bereits belegtem Slot (analog zum FileExistsError-Fang in
    acquire_repair_lock()), statt eine Exception nach aussen zu
    reichen - acquire_download_slot() probiert bewusst alle Slots
    durch, ein einzelner belegter Slot ist kein Fehlerfall."""
    path = slot_path(index)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()}|{time.strftime('%Y-%m-%dT%H:%M:%S%z')}")
    return True


def release_download_slot(index: int) -> None:
    slot_path(index).unlink(missing_ok=True)
    logger.info(f"📤 [DL-SLOT] Freigegeben: slot={index}")


def read_slot_info(index: int) -> Optional[SlotInfo]:
    """Liefert die Diagnosedaten eines belegten Slots, oder None, wenn
    der Slot frei ist oder die Datei nicht im erwarteten Format vorliegt
    (z. B. während eines laufenden `_try_acquire_slot()`-Schreibvorgangs
    - kein Fehler, einfach (noch) keine verwertbare Information)."""
    path = slot_path(index)
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    pid_part, sep, since_part = content.partition("|")
    if not sep or not pid_part.isdigit():
        return None
    return SlotInfo(index=index, pid=int(pid_part), since=since_part)


async def acquire_download_slot(
    max_concurrent: int, *, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
) -> int:
    """Wartet, bis einer von `max_concurrent` Slots frei ist, belegt ihn
    atomar und liefert dessen Index. Wartend statt Fail-Fast (siehe
    Modul-Docstring) - kein Timeout, identisches Prinzip wie das
    bisherige `asyncio.Semaphore` (das ebenfalls unbegrenzt wartet)."""
    slots_dir().mkdir(parents=True, exist_ok=True)
    while True:
        for index in range(max_concurrent):
            if _try_acquire_slot(index):
                logger.info(f"📥 [DL-SLOT] Belegt: slot={index}/{max_concurrent}")
                return index
        await asyncio.sleep(poll_interval)


@asynccontextmanager
async def download_slot(
    max_concurrent: int, *, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
) -> AsyncIterator[int]:
    """Async-Context-Manager-Fassade um acquire_download_slot()/
    release_download_slot() - Slot wird auch bei einer Exception im
    Download selbst zuverlässig freigegeben (finally), identisches
    Prinzip wie `async with semaphore:` zuvor."""
    index = await acquire_download_slot(max_concurrent, poll_interval=poll_interval)
    try:
        yield index
    finally:
        release_download_slot(index)
