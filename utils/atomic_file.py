# utils/atomic_file.py
# -*- coding: utf-8 -*-
"""
Atomares Schreiben von Textdateien (technischer Helfer, kein Netzwerk).

Gemeinsam genutzt von der Mapping-Administration und dem Mapping-Backup.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

_DEFAULT_FILE_MODE = 0o644


def atomic_write_text(path: Path, text: str) -> None:
    """Schreibt `text` atomar nach `path`: eindeutiges tmp-Sibling (kein
    gemeinsamer fester Name, den ein zweiter Schreiber oder ein Rest eines
    abgestuerzten Laufs stoeren koennte), fsync der Datei, `os.replace`, fsync
    des Verzeichnisses. Bei jedem Fehler wird das tmp-File entfernt und die
    Zieldatei bleibt unveraendert. Die Rechte der bestehenden Datei bleiben
    erhalten (mkstemp legt sonst 0600 an)."""
    path = Path(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = _DEFAULT_FILE_MODE
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
