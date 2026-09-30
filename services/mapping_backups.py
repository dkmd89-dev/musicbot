# services/mapping_backups.py
# -*- coding: utf-8 -*-
"""
Versionsstand der Mapping-Dateien (Backup vor jedem Schreiben).

Ablage: `<backup_dir>/<mapping_id>/<version_id>.yaml`, eine Version ist die
unveraenderte Vorgaengerdatei (inklusive Kommentaren). `version_id` ist ein
UTC-Zeitstempel `YYYYMMDDTHHMMSS_ffffffZ`; er wird nie als Pfad benutzt,
sondern nur gegen die tatsaechlich vorhandenen Versionen aufgeloest. Es werden
die letzten `MAX_BACKUPS_PER_MAPPING` Versionen je Mapping aufbewahrt.

Dieses Modul kennt nur Dateien; welche Mapping-IDs erlaubt sind und wie ein
Restore validiert wird, entscheidet der Aufrufer (services/mapping_admin.py,
services/mapping_restore.py).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from utils.atomic_file import atomic_write_text

MAX_BACKUPS_PER_MAPPING = 20
BACKUP_DIR_NAME = "mapping_backups"

_VERSION_ID = re.compile(r"^\d{8}T\d{6}_\d{6}Z$")
_MAPPING_DIR_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class BackupNotFoundError(LookupError):
    """Version existiert nicht (oder die ID hat kein gueltiges Format)."""


@dataclass(frozen=True)
class BackupVersion:
    version_id: str
    created_at: datetime
    size: int
    sha256: str


def default_backup_dir(config) -> Path:
    """Fester, serverseitig aufgeloester Ort — kein Nutzer-Input."""
    return Path(config.DATA_DIR) / BACKUP_DIR_NAME


def _folder(backup_dir: Path, mapping_id: str) -> Path:
    if not _MAPPING_DIR_NAME.match(mapping_id or ""):
        raise BackupNotFoundError(f"Ungueltige mapping_id: {mapping_id!r}")
    return Path(backup_dir) / mapping_id


def _version_from_file(path: Path) -> Optional[BackupVersion]:
    stem = path.name[: -len(".yaml")] if path.name.endswith(".yaml") else ""
    if not _VERSION_ID.match(stem):
        return None
    created = datetime.strptime(stem, "%Y%m%dT%H%M%S_%fZ").replace(tzinfo=timezone.utc)
    data = path.read_bytes()
    return BackupVersion(stem, created, len(data), hashlib.sha256(data).hexdigest())


def list_versions(backup_dir: Path, mapping_id: str) -> List[BackupVersion]:
    """Vorhandene Versionen, neueste zuerst. Fremde Dateien im Ordner werden ignoriert."""
    folder = _folder(backup_dir, mapping_id)
    if not folder.is_dir():
        return []
    versions = [v for v in (_version_from_file(p) for p in folder.iterdir() if p.is_file()) if v]
    return sorted(versions, key=lambda v: v.version_id, reverse=True)


def read_version(backup_dir: Path, mapping_id: str, version_id: str) -> str:
    """Text einer Version. Die ID muss dem Format entsprechen UND als Datei existieren."""
    if not _VERSION_ID.match(version_id or ""):
        raise BackupNotFoundError("Ungueltige Versions-ID.")
    path = _folder(backup_dir, mapping_id) / f"{version_id}.yaml"
    if not path.is_file():
        raise BackupNotFoundError(f"Version {version_id} nicht gefunden.")
    return path.read_text(encoding="utf-8")


def snapshot(
    backup_dir: Path, mapping_id: str, source: Path, *, now: Optional[datetime] = None,
) -> Optional[BackupVersion]:
    """Legt die aktuelle Datei als neue Version ab und beschneidet die
    Aufbewahrung. Gibt None zurueck, wenn es (noch) keine Datei gibt.
    Fehler (OSError) werden nicht verschluckt: ohne Backup darf nicht
    geschrieben werden."""
    source = Path(source)
    if not source.is_file():
        return None
    folder = _folder(backup_dir, mapping_id)
    folder.mkdir(parents=True, exist_ok=True)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    version_id = moment.strftime("%Y%m%dT%H%M%S_%fZ")
    target = folder / f"{version_id}.yaml"
    while target.exists():  # zwei Schreibvorgaenge im selben Mikrosekunden-Tick
        moment = moment.replace(microsecond=(moment.microsecond + 1) % 1_000_000)
        version_id = moment.strftime("%Y%m%dT%H%M%S_%fZ")
        target = folder / f"{version_id}.yaml"
    atomic_write_text(target, source.read_text(encoding="utf-8"))
    _prune(folder)
    return _version_from_file(target)


def _prune(folder: Path) -> None:
    versions = sorted(
        (p for p in folder.iterdir() if p.is_file() and _version_from_file(p)),
        key=lambda p: p.name, reverse=True,
    )
    for old in versions[MAX_BACKUPS_PER_MAPPING:]:
        old.unlink(missing_ok=True)
