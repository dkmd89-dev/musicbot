# services/library_repair/maintenance_service.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance-Actions — Command-getriebener Orchestrierungsservice
(ARCH-032 Phase 3B, ADR-0001/ADR-0004).

Command-Flow (KEIN Health-Finding-Bezug, ARCH-031 B.1 — anders als
repair_service.py's Finding-Flow):

    Artist wählen
    → Preview (read-only, ruft denselben Executor-Pfad mit dry_run=True
      auf wie Execute — garantiert identische Domain-Entscheidung,
      Auftrag §8.2)
    → (Bestätigung — Telegram-/CLI-Schicht, nicht hier)
    → Execute (executor.py::apply_artist_casing/apply_legacy_genre_cleanup/
      apply_set_genre)
    → Run Record (services/library_repair/run_tracking.py, GETEILT mit
      dem Finding-Repair-Flow — ein Lock, ein Journal, ein Run-Index,
      ADR-0004)

Reine Orchestrierung: kein eigener Safety-/Backup-/Journal-/Mutagen-Code
hier (liegt vollständig in executor.py, ARCH-031 B.3). Kein eigenes
Preview-„Was würde passieren"-Nachbauen der Domain-Regeln — Preview und
Execute rufen denselben Executor-Pfad auf, nur mit unterschiedlichem
`dry_run`.

`--update-manual-mapping` ist bewusst NICHT hier (ARCH-031 A.4,
Auftrag §15) — bleibt CLI-only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import Config
from logger import get_module_logger
from services.library_repair import artist as artist_domain
from services.library_repair import genre as genre_domain
from services.library_repair.executor import (
    ExecOutcome,
    apply_artist_casing,
    apply_legacy_genre_cleanup,
    apply_set_genre,
)
from services.library_repair.journal import RepairJournal
from services.library_repair.run_tracking import (
    KIND_MAINTENANCE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    acquire_repair_lock,
    append_run_record,
    journal_path,
    now_iso,
    release_repair_lock,
)

logger = get_module_logger("MaintenanceService")

ACTION_ARTIST_CASING = "artist-casing"
ACTION_LEGACY_GENRE_CLEANUP = "legacy-genre-cleanup"
ACTION_SET_GENRE = "set-genre"
ALL_ACTIONS = (ACTION_ARTIST_CASING, ACTION_LEGACY_GENRE_CLEANUP, ACTION_SET_GENRE)


class MaintenanceServiceError(Exception):
    """Basisklasse für Fehler dieser Orchestrierung (z. B. unbekannter
    Artist, fehlender Genre-Wert)."""


def _library_root(library_root: Optional[Path]) -> Path:
    return Path(library_root) if library_root is not None else Path(Config.LIBRARY_DIR)


def _mapping_dir(mapping_dir: Optional[Path]) -> Path:
    return Path(mapping_dir) if mapping_dir is not None else Path(Config.GENRE_MAPPING_DIR)


def artist_targets(artist: str, *, library_root: Optional[Path] = None) -> list[str]:
    """Relative .m4a-Pfade unter <library>/<artist>/ — identische
    Semantik zu scripts/fix_artist_casing.py::collect_targets()
    (--artist-Zweig). Das Verzeichnis ist AUSSCHLIESSLICH der Datei-Scope
    (welche Dateien werden betrachtet) — die tatsächliche Aenderung ist
    tag-wert-getrieben, nicht verzeichnisname-getrieben (ARCH-031 B.8)."""
    root = _library_root(library_root)
    artist_dir = root / artist
    if not artist_dir.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in artist_dir.rglob("*.m4a"))


@dataclass
class MaintenancePreview:
    """Read-only Vorschau (Auftrag §8.2/§11.6) — identisch zum
    Execute-Ergebnis, nur mit dry_run=True erzeugt. Keine Datei-Aenderung."""

    action: str
    artist: str
    target_count: int
    outcomes: list[ExecOutcome] = field(default_factory=list)
    read_only: bool = True

    @property
    def changed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "DRY_RUN")


@dataclass
class MaintenanceRunResult:
    run_id: str
    action: str
    artist: str
    status: str  # SUCCESS | FAILED | SKIPPED (Semantik identisch zu
    # RepairRunResult.status - "success>0" gilt als Gesamt-SUCCESS, auch
    # bei einzelnen FAILED-Dateien; success_count/failed_count/
    # skipped_count tragen die Partial-Success-Information fuer die
    # Praesentationsschicht, Auftrag §8.5)
    started_at: str
    finished_at: str
    target_count: int
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    dry_run: bool = False
    affected_files: list = field(default_factory=list)
    error_message: Optional[str] = None


def _overall_status(outcomes: list[ExecOutcome]) -> str:
    success = sum(1 for o in outcomes if o.status == "SUCCESS")
    failed = sum(1 for o in outcomes if o.status == "FAILED")
    if failed > 0 and success == 0:
        return STATUS_FAILED
    if success > 0:
        return STATUS_SUCCESS
    return STATUS_SKIPPED


def _run_result_from_outcomes(
    *, run_id: str, action: str, artist: str, started_at: str,
    target_count: int, outcomes: list[ExecOutcome], dry_run: bool,
) -> MaintenanceRunResult:
    success = sum(1 for o in outcomes if o.status == "SUCCESS")
    failed = sum(1 for o in outcomes if o.status == "FAILED")
    skipped = sum(1 for o in outcomes if o.status in ("SKIPPED", "DRY_RUN"))
    return MaintenanceRunResult(
        run_id=run_id, action=action, artist=artist,
        status=_overall_status(outcomes),
        started_at=started_at, finished_at=now_iso(),
        target_count=target_count, success_count=success,
        failed_count=failed, skipped_count=skipped, dry_run=dry_run,
        affected_files=sorted({o.file for o in outcomes if o.status == "SUCCESS"}),
    )


def _record_run(
    *, run_id: str, action: str, artist: str, started_at: str,
    result: MaintenanceRunResult, triggered_by: str,
) -> None:
    append_run_record({
        "repair_id": run_id,
        "started_at": started_at,
        "finished_at": result.finished_at,
        "triggered_by": triggered_by,
        "level": action.upper().replace("-", "_"),
        "kind": KIND_MAINTENANCE,
        "status": result.status,
        "target_count": result.target_count,
        "status_counts": {
            "SUCCESS": result.success_count,
            "FAILED": result.failed_count,
            "SKIPPED": result.skipped_count,
        },
        "affected_files": result.affected_files,
    })


# ─────────────────────────────────────────────────────────────────────────
# Artist Casing
# ─────────────────────────────────────────────────────────────────────────


def preview_artist_casing(
    artist: str, *, library_root: Optional[Path] = None,
    mapping_dir: Optional[Path] = None,
) -> MaintenancePreview:
    targets = artist_targets(artist, library_root=library_root)
    casing_map = artist_domain.load_casing_map(_mapping_dir(mapping_dir))
    journal = RepairJournal(journal_path())  # nie geflusht -> read-only
    outcomes = apply_artist_casing(
        targets, _library_root(library_root), journal,
        casing_map=casing_map, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_ARTIST_CASING, artist=artist,
        target_count=len(targets), outcomes=outcomes,
    )


def execute_artist_casing_fix(
    artist: str, *, triggered_by: str, library_root: Optional[Path] = None,
    mapping_dir: Optional[Path] = None,
) -> MaintenanceRunResult:
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = artist_targets(artist, library_root=library_root)
        casing_map = artist_domain.load_casing_map(_mapping_dir(mapping_dir))
        journal = RepairJournal(journal_path())
        outcomes = apply_artist_casing(
            targets, _library_root(library_root), journal,
            casing_map=casing_map, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_ARTIST_CASING, artist=artist,
            started_at=started_at, target_count=len(targets),
            outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_ARTIST_CASING, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()


# ─────────────────────────────────────────────────────────────────────────
# Legacy Genre Cleanup
# ─────────────────────────────────────────────────────────────────────────


def preview_legacy_genre_cleanup(
    artist: str, *, library_root: Optional[Path] = None,
) -> MaintenancePreview:
    targets = artist_targets(artist, library_root=library_root)
    journal = RepairJournal(journal_path())
    outcomes = apply_legacy_genre_cleanup(
        targets, _library_root(library_root), journal, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_LEGACY_GENRE_CLEANUP, artist=artist,
        target_count=len(targets), outcomes=outcomes,
    )


def execute_legacy_genre_cleanup(
    artist: str, *, triggered_by: str, library_root: Optional[Path] = None,
) -> MaintenanceRunResult:
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = artist_targets(artist, library_root=library_root)
        journal = RepairJournal(journal_path())
        outcomes = apply_legacy_genre_cleanup(
            targets, _library_root(library_root), journal, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_LEGACY_GENRE_CLEANUP, artist=artist,
            started_at=started_at, target_count=len(targets),
            outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_LEGACY_GENRE_CLEANUP, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()


# ─────────────────────────────────────────────────────────────────────────
# Set Genre
# ─────────────────────────────────────────────────────────────────────────


def resolve_target_genre(
    artist: str, *, genre: Optional[str] = None, from_mapping: bool = False,
    mapping_dir: Optional[Path] = None,
) -> str:
    """Bestimmt den zu schreibenden Genre-Wert (Mapping-Lookup vs.
    manueller Wert ist Orchestrierungs-Entscheidung, nicht Aufgabe des
    Executors — ARCH-031 §6.4)."""
    if from_mapping:
        value = genre_domain.genre_from_mapping(
            artist, _mapping_dir(mapping_dir) / "artist_genre.yaml"
        )
        if not value:
            raise MaintenanceServiceError(
                f"Artist {artist!r} nicht in artist_genre.yaml gefunden."
            )
        return value
    if not genre:
        raise MaintenanceServiceError(
            "Kein Genre angegeben (genre= oder from_mapping=True erforderlich)."
        )
    normalized = genre_domain.normalize_genre_input(genre)
    if not normalized:
        raise MaintenanceServiceError("Genre ist nach Normalisierung leer.")
    return normalized


def preview_set_genre(
    artist: str, *, genre: Optional[str] = None, from_mapping: bool = False,
    only_if_missing: bool = False, library_root: Optional[Path] = None,
    mapping_dir: Optional[Path] = None,
) -> MaintenancePreview:
    target_genre = resolve_target_genre(
        artist, genre=genre, from_mapping=from_mapping, mapping_dir=mapping_dir,
    )
    targets = artist_targets(artist, library_root=library_root)
    journal = RepairJournal(journal_path())
    outcomes = apply_set_genre(
        targets, _library_root(library_root), journal,
        target_genre=target_genre, only_if_missing=only_if_missing, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_SET_GENRE, artist=artist,
        target_count=len(targets), outcomes=outcomes,
    )


def execute_set_genre(
    artist: str, *, triggered_by: str, genre: Optional[str] = None,
    from_mapping: bool = False, only_if_missing: bool = False,
    library_root: Optional[Path] = None, mapping_dir: Optional[Path] = None,
) -> MaintenanceRunResult:
    target_genre = resolve_target_genre(
        artist, genre=genre, from_mapping=from_mapping, mapping_dir=mapping_dir,
    )
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = artist_targets(artist, library_root=library_root)
        journal = RepairJournal(journal_path())
        outcomes = apply_set_genre(
            targets, _library_root(library_root), journal,
            target_genre=target_genre, only_if_missing=only_if_missing, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_SET_GENRE, artist=artist,
            started_at=started_at, target_count=len(targets),
            outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_SET_GENRE, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()
