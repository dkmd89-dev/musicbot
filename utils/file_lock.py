# utils/file_lock.py
# -*- coding: utf-8 -*-
"""
Prozessübergreifender Datei-Lock (`fcntl.flock`) für Read-Modify-Write-
Zyklen auf JSON-Dateien, die bot.service UND control-center.service
gleichzeitig beschreiben.

Ursprung: services/user_data.py::_cross_process_lock() (CC-AC-10G, A.7,
Client Consolidation Phase A). Hierher verschoben (D.13), damit
DownloadHistoryStore und DuplicateCache dasselbe, bereits bewährte Muster
nutzen statt einer zweiten Implementierung — services/user_data.py
verwendet weiterhin exakt diese Funktion (Alias `_cross_process_lock`).
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def cross_process_lock(path: Path) -> Iterator[None]:
    """Hält einen exklusiven `fcntl.flock` auf einer `<path>.lock`-Datei,
    solange der `with`-Block läuft. Die Lock-Datei selbst trägt keine
    Nutzdaten, nur ihr Dateideskriptor dient als Lock-Handle
    (Standardmuster für `fcntl.flock` unter Linux).

    Nicht reentrant innerhalb desselben Prozesses über verschiedene
    Datei-Handles hinweg — Aufrufer dürfen den Lock für denselben Pfad
    nicht verschachtelt anfordern."""
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
