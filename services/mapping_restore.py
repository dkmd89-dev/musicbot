# services/mapping_restore.py
# -*- coding: utf-8 -*-
"""
Restore einer Mapping-Version (Backup/Restore der Mapping-Administration).

Ein Restore ist ein normaler, Etag-geschuetzter Write: Der Aufrufer holt sich
per plan_restore() den Diff samt aktuellem Etag und bestaetigt mit
apply_restore(). Geschrieben wird der Text der Version unveraendert
(Kommentare bleiben erhalten). Vorher wird der aktuelle Stand selbst als
Version abgelegt, ein Restore ist damit wieder umkehrbar.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from services import mapping_admin as ma
from services import mapping_backups as mb


@dataclass
class RestorePlan:
    mapping_id: str
    version_id: str
    created_at: str
    change: str  # "update" | "unchanged"
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    etag: str = ""


@dataclass
class RestoreResult:
    written: bool
    unchanged: bool
    version_id: str
    new_etag: str


def list_backup_versions(mapping_id: str, backup_dir: Path) -> List[mb.BackupVersion]:
    ma.get_descriptor(mapping_id)  # Allowlist
    return mb.list_versions(backup_dir, mapping_id)


def _read_version(mapping_id: str, version_id: str, backup_dir: Path) -> str:
    ma.get_descriptor(mapping_id)  # Allowlist, bevor irgendein Pfad gebildet wird
    try:
        return mb.read_version(backup_dir, mapping_id, version_id)
    except mb.BackupNotFoundError as e:
        raise ma.MappingBackupNotFoundError(str(e)) from e


def _describe_text(mapping_id: str, text: str) -> Dict[str, str]:
    """Liest den Text mit denselben Parsern wie die Administration (in einem
    temporaeren Verzeichnis). Ist die Version nicht lesbar, wird sie abgelehnt."""
    descriptor = ma.get_descriptor(mapping_id)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / descriptor.filename).write_text(text, encoding="utf-8")
        try:
            return ma.describe_mapping(mapping_id, Path(tmp))
        except ma.MappingUnavailableError as e:
            raise ma.MappingInvalidInputError(
                "Diese Version ist nicht lesbar und kann nicht wiederhergestellt werden."
            ) from e


def _diff(current: Dict[str, str], target: Dict[str, str]) -> Tuple[List[str], List[str], List[str]]:
    added = [f"{k}: {v}" for k, v in target.items() if k not in current]
    removed = [f"{k}: {v}" for k, v in current.items() if k not in target]
    changed = [f"{k}: {current[k]} → {v}" for k, v in target.items() if k in current and current[k] != v]
    return added, removed, changed


def _plan(mapping_id: str, version_id: str, mapping_dir: Path, backup_dir: Path) -> Tuple[RestorePlan, str]:
    descriptor = ma.get_descriptor(mapping_id)
    text = _read_version(mapping_id, version_id, backup_dir)
    target = _describe_text(mapping_id, text)
    path = ma.mapping_file_path(descriptor, mapping_dir)
    if not path.is_file():
        raise ma.MappingUnavailableError(f"{path} existiert nicht.")
    current_text = path.read_text(encoding="utf-8")
    created = next(
        (v.created_at.isoformat() for v in mb.list_versions(backup_dir, mapping_id) if v.version_id == version_id), "",
    )
    added, removed, changed = _diff(ma.describe_mapping(mapping_id, mapping_dir), target)
    plan = RestorePlan(
        mapping_id=mapping_id, version_id=version_id, created_at=created,
        change="unchanged" if text == current_text else "update",
        added=added, removed=removed, changed=changed,
        etag=ma.get_current_etag(mapping_id, mapping_dir),
    )
    return plan, text


def plan_restore(mapping_id: str, version_id: str, mapping_dir: Path, backup_dir: Path) -> RestorePlan:
    return _plan(mapping_id, version_id, mapping_dir, backup_dir)[0]


def apply_restore(
    mapping_id: str, version_id: str, mapping_dir: Path, backup_dir: Path, *, expected_etag: str,
) -> Tuple[RestorePlan, RestoreResult]:
    descriptor = ma.get_descriptor(mapping_id)
    with ma.write_guard(descriptor, mapping_dir):
        plan, text = _plan(mapping_id, version_id, mapping_dir, backup_dir)
        if plan.etag != expected_etag:
            raise ma.MappingConflictError(
                "Der Mapping-Stand wurde seit der Vorschau geaendert. "
                "Bitte neu laden und erneut pruefen."
            )
        if plan.change == "unchanged":
            return plan, RestoreResult(False, True, version_id, plan.etag)
        ma.snapshot_before_write(descriptor, mapping_dir, backup_dir)
        ma.write_mapping_text(ma.mapping_file_path(descriptor, mapping_dir), text)
        return plan, RestoreResult(True, False, version_id, ma.get_current_etag(mapping_id, mapping_dir))
