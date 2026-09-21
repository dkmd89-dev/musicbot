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
    apply_album_artist_edit,
    apply_album_edit,
    apply_artist_casing,
    apply_artist_rename,
    apply_legacy_genre_cleanup,
    apply_set_genre,
    apply_title_edit,
    read_current_album,
    read_current_album_artist,
    read_current_title,
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

# Manual Metadata Editing v1 (ARCH-032-Folgeauftrag) - bewusst NICHT in
# ALL_ACTIONS: dieses Tupel treibt weiterhin nur die drei bestehenden,
# generischen Single-Tap-CLI-/Telegram-Actions (scripts/library_repair.py
# --maintenance-action, handlers/menu/actions/library.py::
# _MAINTENANCE_ACTIONS). Artist-Rename/Title-Edit sind mehrstufige
# Freitext-Flows (wie set-genre seit Library Genre Management v2) mit
# eigenen Callback-Routen (libmaint:meta:*) - kein CLI-Zugang, kein
# --maintenance-action-Wert (Auftrag bewusst Telegram-only, Abschnitt 1).
ACTION_ARTIST_RENAME = "artist-rename"
ACTION_TITLE_EDIT = "title-edit"

# Manual Metadata Editing v2 (ARCH-032-Folgeauftrag) - dieselbe bewusste
# Nicht-Aufnahme in ALL_ACTIONS wie ACTION_ARTIST_RENAME/ACTION_TITLE_EDIT
# oben (eigene mehrstufige Telegram-only-Flows, kein CLI-Zugang).
ACTION_ALBUM_EDIT = "album-edit"
ACTION_ALBUM_ARTIST_EDIT = "album-artist-edit"

_MAX_MANUAL_VALUE_LEN = 200


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


def resolve_track_by_index(
    artist: str, idx: int, *, library_root: Optional[Path] = None
) -> Optional[str]:
    """Loest einen Button-Index gegen eine frisch ermittelte Track-Liste
    dieses Artists auf (ARCH-031 B.8-Muster wie
    library_artists.py::resolve_artist_by_index() - kein Rohpfad aus
    Telegram-callback_data). Nutzt dieselbe Zielmenge wie alle anderen
    Maintenance-Actions (artist_targets()) - kein zweiter Library-Scan
    fuer Manual Title Editing (Auftrag Abschnitt 16)."""
    targets = artist_targets(artist, library_root=library_root)
    if 0 <= idx < len(targets):
        return targets[idx]
    return None


def _resolve_within_library(rel_path: str, library_root: Path) -> Path:
    """Verweigert Pfade ausserhalb der Library-Wurzel (Defense-in-Depth
    an der Service-Grenze — alle aktuellen Aufrufer beziehen `rel_path`
    bereits ausschliesslich aus resolve_track_by_index()/album_targets(),
    nie aus rohem Telegram-callback_data; dieser Check haertet zusaetzlich
    gegen einen kuenftigen, weniger sorgfaeltigen Aufrufer ab)."""
    root = library_root.resolve()
    candidate = (library_root / rel_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise MaintenanceServiceError(f"Pfad außerhalb der Library: {rel_path!r}")
    return candidate


def current_title(rel_path: str, *, library_root: Optional[Path] = None) -> str:
    """Liest den aktuellen Titel-Tag (©nam) fuer die Eingabe-/Preview-
    Anzeige des Manual Title Editing (rein lesend, Auftrag Abschnitt 8).
    `rel_path` kommt ausschliesslich aus resolve_track_by_index()
    (server-seitig neu aufgeloest, kein Rohpfad aus callback_data)."""
    root = _library_root(library_root)
    return read_current_title(_resolve_within_library(rel_path, root))


# ─────────────────────────────────────────────────────────────────────────
# Album-Target-Resolution (Manual Metadata Editing v2, Auftrag Abschnitt
# 6-9/22/23) — VERZEICHNIS-basiert, identische Konvention wie
# artist_targets() oben, eine Ebene tiefer: <library>/<artist>/<album>/.
# Album-Scope ist damit deterministisch, gehoert ausschliesslich zum
# gewaehlten Album-Kontext und mischt keine anderen Alben/Artists (Auftrag
# §22) — zwei Ordner mit identischem sichtbaren Albumnamen (z. B.
# "2024 - Album X" vs. "2025 - Album X") bleiben unabhaengige Scopes, ein
# Ordner mit bereits inkonsistenten ©alb-Werten bleibt vollstaendig im
# Scope (Auftrag §23 — siehe executor.py::apply_album_edit()-Docstring).
# Wiederverwendet exakt dieselbe Klassifikation wie der bereits
# bestehende Health-Scanner (services/library_health/discovery.py /
# group_analysis.py's (artist_directory, album_directory)-Gruppierung),
# hier als leichtgewichtiger Verzeichnis-Adapter ohne die schwerere
# FileHealth-/Tag-Scan-Infrastruktur des vollen Health-Scans (Auftrag
# §22: "keine neue vollstaendige Library-Scan-Architektur").
# ─────────────────────────────────────────────────────────────────────────


def album_targets(
    artist: str, album: str, *, library_root: Optional[Path] = None
) -> list[str]:
    """Relative .m4a-Pfade des Album-Kontexts `album` unter
    <library>/<artist>/. `album` MUSS ein exakter Wert aus
    library_artists.py::list_artist_albums()/resolve_album_by_index() sein
    (kein Rohpfad aus Telegram-callback_data) — entweder ein
    Verzeichnisname (Mehr-Track-Album, `<library>/<artist>/<album>/*.m4a`)
    oder `"<Singles-Ordner>/<Dateiname>"` (Einzel-Track-Scope einer
    Single, Nutzer-Fund 2026-09-20 — list_artist_albums() listet jede
    Single individuell statt den gesamten Singles-Ordner als einen
    gemeinsamen Bulk-Kontext, Auftrag §24 bleibt dadurch respektiert).

    Defense-in-Depth (Adversarial-Review-Fund 2026-09-21, CC-AC-3, Runde 2
    nach fehlgeschlagenem Blacklist-Versuch der Runde 1 - ".", "./",
    ".//." umgingen `".." in Path(album).parts` vollstaendig, da
    `root/artist/"."` zu `root/artist` kollabiert): seit
    control_center/routers/admin_maintenance.py::album-edit/albumartist-edit
    sind `artist` UND `album` erstmals direkt per HTTP von einem
    authentifizierten ADMIN-Client frei waehlbar (der bisherige
    Telegram-Pfad loest immer ueber resolve_album_by_index() serverseitig
    gegen eine frisch ermittelte Liste auf, nie aus rohem Nutzertext).
    Statt einzelne Traversal-Muster auszuschliessen (Blacklist, siehe
    oben - unvollstaendig) wird deshalb eine positive Containment-Pruefung
    verwendet, identisches Prinzip wie die bestehende
    `_resolve_within_library()` weiter oben in diesem Modul, hier
    zweistufig (Artist-Verzeichnis MUSS echt innerhalb der Library liegen,
    Album-Ziel MUSS echt innerhalb des Artist-Verzeichnisses liegen -
    "echt" == ungleich UND nicht nur zufaellig namensgleich, schliesst
    `artist="."`/`""`/`".."` und `album="."`/`".."`/absolute Pfade
    gleichermassen aus). `Path.resolve()` folgt dabei auch Symlinks, was
    nebenbei einen mit `list_artist_albums()` inkonsistenten
    Symlink-Verzeichnis-Fall schliesst (dessen Verzeichnis-Zweig anders
    als der Datei-Zweig zuvor nicht auf `is_symlink()` prüfte). Bei
    fehlendem Artist-/Album-Pfad, ungueltiger Pfadform, zu langem
    Pfadsegment (`OSError ENAMETOOLONG`) oder einer Symlink-Schleife
    (`Path.resolve()` wirft dafuer unter Python 3.12 ein `RuntimeError`,
    kein `OSError` - Adversarial-Review-Fund 2026-09-21, Runde 3: die
    Runde-2-Fassung deckte nur den `resolve()`-Aufruf selbst ab, nicht
    die nachfolgenden `is_dir()`/`is_file()`/`rglob()`-Aufrufe, die
    denselben `OSError` erneut auf demselben zu langen Pfad auswerfen
    koennen) leere Zielmenge - identisches Fehlerbild wie ein schlicht
    falscher Albumname, kein neuer Fehlerpfad (HTTP 500 statt 422/200)."""
    root = _library_root(library_root)
    try:
        root_resolved = root.resolve()
        artist_scope = (root / artist).resolve()
        candidate = (root / artist / album).resolve()
        if root_resolved == artist_scope or root_resolved not in artist_scope.parents:
            return []
        if artist_scope == candidate or artist_scope not in candidate.parents:
            return []
        if candidate.is_dir():
            return sorted(str(p.relative_to(root_resolved)) for p in candidate.rglob("*.m4a"))
        if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() == ".m4a":
            return [str(candidate.relative_to(root_resolved))]
    except (OSError, ValueError, RuntimeError):
        return []
    return []


def current_album(artist: str, album: str, *, library_root: Optional[Path] = None) -> str:
    """Liest den aktuellen ©alb-Wert repraesentativ von der ersten Datei
    im Album-Scope (rein lesend, Preview-/Eingabe-Anzeige, Auftrag §8) -
    der Scope kann bereits inkonsistente ©alb-Werte enthalten (§23);
    apply_album_edit() liest/vergleicht bei der Ausfuehrung unabhaengig
    davon erneut pro Datei."""
    root = _library_root(library_root)
    targets = album_targets(artist, album, library_root=root)
    if not targets:
        return ""
    return read_current_album(_resolve_within_library(targets[0], root))


def current_album_artist(artist: str, album: str, *, library_root: Optional[Path] = None) -> str:
    """Liest den aktuellen aART-Wert repraesentativ von der ersten Datei
    im Album-Scope (rein lesend, Auftrag §10) - identisches Prinzip wie
    current_album()."""
    root = _library_root(library_root)
    targets = album_targets(artist, album, library_root=root)
    if not targets:
        return ""
    return read_current_album_artist(_resolve_within_library(targets[0], root))


def _validate_manual_value(value: Optional[str], *, label: str) -> str:
    """Domain-seitige Validierung (Defense-in-Depth zu den Format-Checks
    in handlers/library_maintenance_handler.py, Auftrag Abschnitt 14) -
    liefert den getrimmten Zielwert oder wirft MaintenanceServiceError."""
    if value is None:
        raise MaintenanceServiceError(f"Kein neuer {label} angegeben.")
    if "\n" in value or "\r" in value:
        raise MaintenanceServiceError(
            f"{label} darf keine Zeilenumbrüche enthalten."
        )
    trimmed = value.strip()
    if not trimmed:
        raise MaintenanceServiceError(f"{label} darf nicht leer sein.")
    if len(trimmed) > _MAX_MANUAL_VALUE_LEN:
        raise MaintenanceServiceError(
            f"{label} zu lang (max. {_MAX_MANUAL_VALUE_LEN} Zeichen)."
        )
    return trimmed


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


# ─────────────────────────────────────────────────────────────────────────
# Manual Artist Editing (Auftrag Abschnitt 5-7) - expliziter Nutzer-
# Zielwert, KEIN Casing-Mapping/keine Normalisierung (Auftrag Abschnitt 6).
# ─────────────────────────────────────────────────────────────────────────


def preview_artist_rename(
    artist: str, new_artist: str, *, library_root: Optional[Path] = None,
) -> MaintenancePreview:
    new_artist = _validate_manual_value(new_artist, label="Artist-Name")
    targets = artist_targets(artist, library_root=library_root)
    journal = RepairJournal(journal_path())  # nie geflusht -> read-only
    outcomes = apply_artist_rename(
        targets, _library_root(library_root), journal,
        old_artist=artist, new_artist=new_artist, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_ARTIST_RENAME, artist=artist,
        target_count=len(targets), outcomes=outcomes,
    )


def execute_artist_rename(
    artist: str, new_artist: str, *, triggered_by: str,
    library_root: Optional[Path] = None,
) -> MaintenanceRunResult:
    new_artist = _validate_manual_value(new_artist, label="Artist-Name")
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = artist_targets(artist, library_root=library_root)
        journal = RepairJournal(journal_path())
        outcomes = apply_artist_rename(
            targets, _library_root(library_root), journal,
            old_artist=artist, new_artist=new_artist, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_ARTIST_RENAME, artist=artist,
            started_at=started_at, target_count=len(targets),
            outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_ARTIST_RENAME, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()


# ─────────────────────────────────────────────────────────────────────────
# Manual Title Editing (Auftrag Abschnitt 8/9) - IMMER track-spezifisch,
# KEIN TitleCleaner (der manuell eingegebene Zielwert ist die explizite
# Nutzerentscheidung).
# ─────────────────────────────────────────────────────────────────────────


def preview_title_edit(
    artist: str, rel_path: str, new_title: str, *,
    library_root: Optional[Path] = None,
) -> MaintenancePreview:
    new_title = _validate_manual_value(new_title, label="Titel")
    journal = RepairJournal(journal_path())  # nie geflusht -> read-only
    outcomes = apply_title_edit(
        [rel_path], _library_root(library_root), journal,
        new_title=new_title, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_TITLE_EDIT, artist=artist, target_count=1, outcomes=outcomes,
    )


def execute_title_edit(
    artist: str, rel_path: str, new_title: str, *, triggered_by: str,
    library_root: Optional[Path] = None,
) -> MaintenanceRunResult:
    new_title = _validate_manual_value(new_title, label="Titel")
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        journal = RepairJournal(journal_path())
        outcomes = apply_title_edit(
            [rel_path], _library_root(library_root), journal,
            new_title=new_title, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_TITLE_EDIT, artist=artist,
            started_at=started_at, target_count=1,
            outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_TITLE_EDIT, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()


# ─────────────────────────────────────────────────────────────────────────
# Manual Album Editing (Auftrag Abschnitt 6-9) - expliziter Nutzer-
# Zielwert fuer ©alb ueber den gesamten (verzeichnisbasierten) Album-Scope.
# ─────────────────────────────────────────────────────────────────────────


def preview_album_edit(
    artist: str, album: str, new_album: str, *, library_root: Optional[Path] = None,
) -> MaintenancePreview:
    new_album = _validate_manual_value(new_album, label="Albumname")
    targets = album_targets(artist, album, library_root=library_root)
    journal = RepairJournal(journal_path())  # nie geflusht -> read-only
    outcomes = apply_album_edit(
        targets, _library_root(library_root), journal, new_album=new_album, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_ALBUM_EDIT, artist=artist, target_count=len(targets), outcomes=outcomes,
    )


def execute_album_edit(
    artist: str, album: str, new_album: str, *, triggered_by: str,
    library_root: Optional[Path] = None,
) -> MaintenanceRunResult:
    new_album = _validate_manual_value(new_album, label="Albumname")
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = album_targets(artist, album, library_root=library_root)
        journal = RepairJournal(journal_path())
        outcomes = apply_album_edit(
            targets, _library_root(library_root), journal, new_album=new_album, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_ALBUM_EDIT, artist=artist,
            started_at=started_at, target_count=len(targets), outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_ALBUM_EDIT, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()


# ─────────────────────────────────────────────────────────────────────────
# Manual Album Artist Editing (Auftrag Abschnitt 10-13) - AUSSCHLIESSLICH
# aART, ©ART/©alb/©nam bleiben unangetastet (siehe
# executor.py::apply_album_artist_edit()).
# ─────────────────────────────────────────────────────────────────────────


def preview_album_artist_edit(
    artist: str, album: str, new_album_artist: str, *,
    library_root: Optional[Path] = None,
) -> MaintenancePreview:
    new_album_artist = _validate_manual_value(new_album_artist, label="Albuminterpret")
    targets = album_targets(artist, album, library_root=library_root)
    journal = RepairJournal(journal_path())  # nie geflusht -> read-only
    outcomes = apply_album_artist_edit(
        targets, _library_root(library_root), journal,
        new_album_artist=new_album_artist, dry_run=True,
    )
    return MaintenancePreview(
        action=ACTION_ALBUM_ARTIST_EDIT, artist=artist,
        target_count=len(targets), outcomes=outcomes,
    )


def execute_album_artist_edit(
    artist: str, album: str, new_album_artist: str, *, triggered_by: str,
    library_root: Optional[Path] = None,
) -> MaintenanceRunResult:
    new_album_artist = _validate_manual_value(new_album_artist, label="Albuminterpret")
    acquire_repair_lock()
    try:
        started_at = now_iso()
        run_id = str(uuid.uuid4())
        targets = album_targets(artist, album, library_root=library_root)
        journal = RepairJournal(journal_path())
        outcomes = apply_album_artist_edit(
            targets, _library_root(library_root), journal,
            new_album_artist=new_album_artist, dry_run=False,
        )
        journal.flush()
        result = _run_result_from_outcomes(
            run_id=run_id, action=ACTION_ALBUM_ARTIST_EDIT, artist=artist,
            started_at=started_at, target_count=len(targets), outcomes=outcomes, dry_run=False,
        )
        _record_run(
            run_id=run_id, action=ACTION_ALBUM_ARTIST_EDIT, artist=artist,
            started_at=started_at, result=result, triggered_by=triggered_by,
        )
        return result
    finally:
        release_repair_lock()
