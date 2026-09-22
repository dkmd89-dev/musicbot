# services/backup_admin.py
# -*- coding: utf-8 -*-
"""
CC-AC-10C (Control Center Admin API, Bot & Operations) — Telegram-freier
Application-Layer für Backup-Operationen (Bot-Verzeichnis + Musikbibliothek).

Bildet dieselbe Fachlogik nach, die
handlers/admin/backup_handler.py::BackupHandler bereits für den
Telegram-Bot implementiert (Archiv-Erstellung, Rotation, SEC-006
Path-Traversal-Schutz in resolve_backup_path()) — **eigenständige
Implementierung statt Import**, weil services/ laut
tests/test_services_layer_boundary.py niemals aus handlers/ importieren
darf (BackupHandler hält Telegram-Objekte). Identische Konstanten/
Defaults wie BackupHandler.__init__() (siehe dortige Werte).

Persistenz-/Prozessmechanik (tarfile, Path.glob/.unlink) ist hier
identisch zur Telegram-Seite dupliziert — CC-AC-10.md §20 sieht die
Telegram-Migration selbst bewusst erst in CC-AC-10G vor (siehe
services/user_admin.py-Docstring für dieselbe Begründung bei User
Management). BackupHandler bleibt in diesem Slice unverändert.
"""

from __future__ import annotations

import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

DEFAULT_BOT_SOURCE = "/mnt/900gb/entwickeln/rich"
DEFAULT_LIB_SOURCE = "/mnt/900gb/entwickeln/rich/library"
DEFAULT_DEST_DIR = "/mnt/250gb/Musikserver"
DEFAULT_MAX_KEEP = 5
DEFAULT_EXCLUDE_PATTERNS = [
    "library",  # Musikbibliothek separat sichern
    "__pycache__",
    ".git",
    "*.pyc",
    "import/downloads",
    "import/temp",
    "cache",
]

BACKUP_TYPES = ("bot", "library")


class BackupAdminError(Exception):
    """Basisklasse für Validierungsfehler dieses Moduls."""


class InvalidBackupTypeError(BackupAdminError):
    pass


class BackupNotFoundError(BackupAdminError):
    pass


class InvalidBackupFilenameError(BackupAdminError):
    """SEC-006: der aufgelöste Pfad liegt außerhalb von dest_dir."""


@dataclass(frozen=True)
class BackupPaths:
    bot_source: Path
    lib_source: Path
    dest_dir: Path
    max_keep: int
    exclude_patterns: List[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Any) -> "BackupPaths":
        dest_dir = Path(getattr(config, "BACKUP_DEST_DIR", DEFAULT_DEST_DIR))
        dest_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            bot_source=Path(getattr(config, "BACKUP_BOT_SOURCE_DIR", DEFAULT_BOT_SOURCE)),
            lib_source=Path(getattr(config, "BACKUP_LIBRARY_SOURCE_DIR", DEFAULT_LIB_SOURCE)),
            dest_dir=dest_dir,
            max_keep=int(getattr(config, "BACKUP_MAX_KEEP", DEFAULT_MAX_KEEP)),
            exclude_patterns=list(
                getattr(config, "BACKUP_EXCLUDE_PATTERNS", DEFAULT_EXCLUDE_PATTERNS)
            ),
        )


@dataclass
class BackupEntry:
    name: str
    path: Path
    size: int
    created_at: datetime


def human_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def list_backups(paths: BackupPaths, backup_type: str) -> List[BackupEntry]:
    prefix = f"{backup_type}_backup_"
    backups = []
    for f in paths.dest_dir.glob(f"{prefix}*.tar.gz"):
        try:
            stat = f.stat()
            backups.append(
                BackupEntry(
                    name=f.name, path=f, size=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )
        except OSError:
            pass
    return sorted(backups, key=lambda b: b.created_at, reverse=True)


def _archive_filter(exclude: List[str]):
    def _filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        for pattern in exclude:
            if pattern.startswith("*."):
                if tarinfo.name.endswith(pattern[1:]):
                    return None
            elif pattern in tarinfo.name:
                return None
        return tarinfo

    return _filter


def rotate_backups(paths: BackupPaths, backup_type: str, *, logger: Any = None) -> List[str]:
    """Entfernt älteste Backups oberhalb max_keep, gibt gelöschte Dateinamen zurück."""
    backups = list_backups(paths, backup_type)
    removed = []
    while len(backups) > paths.max_keep:
        oldest = backups.pop()
        try:
            oldest.path.unlink()
            removed.append(oldest.name)
        except OSError as e:
            if logger:
                logger.warning(f"⚠️ Konnte {oldest.name} nicht löschen: {e}")
    return removed


def create_backup(paths: BackupPaths, backup_type: str, *, logger: Any = None) -> BackupEntry:
    """Erstellt ein tar.gz-Archiv + rotiert danach — synchrones Datei-I/O
    (identisch zur Telegram-Seite, die dies über run_in_executor()
    ausführt, siehe BackupHandler-Docstring zu INV-01). Der Aufrufer
    (Job in control_center/routers/admin_operations.py) ist für das
    Executor-/Thread-Wrapping verantwortlich, nicht diese Funktion."""
    if backup_type not in BACKUP_TYPES:
        raise InvalidBackupTypeError(f"Unbekannter Backup-Typ: {backup_type}")

    if backup_type == "bot":
        source, exclude = paths.bot_source, paths.exclude_patterns
    else:
        source, exclude = paths.lib_source, []

    paths.dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = paths.dest_dir / f"{backup_type}_backup_{timestamp}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(str(source), arcname=source.name, filter=_archive_filter(exclude))

    rotate_backups(paths, backup_type, logger=logger)

    stat = archive_path.stat()
    return BackupEntry(
        name=archive_path.name, path=archive_path, size=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime),
    )


def resolve_backup_path(paths: BackupPaths, filename: str) -> Path:
    """SEC-006 Path-Traversal-Schutz — identisch zu
    BackupHandler._resolve_backup_path()."""
    candidate = (paths.dest_dir / filename).resolve()
    if not candidate.is_relative_to(paths.dest_dir.resolve()):
        raise InvalidBackupFilenameError(f"Pfad außerhalb von {paths.dest_dir}: {filename}")
    return candidate


def delete_backup(paths: BackupPaths, filename: str) -> str:
    """Löscht eine Backup-Datei, gibt den Dateinamen zurück."""
    filepath = resolve_backup_path(paths, filename)
    if not filepath.exists():
        raise BackupNotFoundError(f"Backup nicht gefunden: {filename}")
    filepath.unlink()
    return filepath.name
