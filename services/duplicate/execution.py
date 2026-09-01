# services/duplicate/execution.py
# -*- coding: utf-8 -*-
"""
Duplicate Resolution Phase 3 — Execute-Implementierung (Delete).

Basis: MusicBot — Duplicate Resolution Phase 3 Auftrag ("SAFE EXECUTE
IMPLEMENTATION"). Erste Phase, in der tatsächliche Dateien gelöscht
werden dürfen - "Safety > Cleanup Completeness" bleibt oberstes Prinzip
(Auftrag, wortgleich aus Phase 1-2.3 übernommen).

## Architektur-Grenze

Dieses Modul ist reine Orchestrierung + Filesystem-Mutation - es
DUPLIZIERT keine bestehende Logik:
  - Klassifikation/Confidence: services/duplicate/classification.py
  - Decision Matrix/Safety Gate: services/duplicate/resolution.py
  - Tag-/ffprobe-Lesen, Path-Safety (ALLOWED_ROOT/FORBIDDEN_ROOTS):
    scripts/resolve_duplicates.py (per Dependency Injection eingebunden,
    siehe `validate_file_within_root`/`build_candidate_from_path`-
    Parameter unten - keine eigene Kopie der Sicherheitslogik).

## Zweistufiges Sicherheitsmodell (Auftrag Abschnitt 4/6/7/17)

    SCAN (scripts/resolve_duplicates.py, unverändert)
      ↓
    RESOLVE (resolution.py::resolve_group(), unverändert)
      ↓
    build_execution_plan()  — Manifest MIT Fingerprints (Größe+SHA-256)
      ↓
    explizite --execute (CLI-Flag, siehe scripts/resolve_duplicates.py)
      ↓
    execute_group() pro Gruppe:
        revalidate_group()  — Stufe 1: Fingerprint/Path-Safety
                               Stufe 2: semantische Neuentscheidung
                               (resolve_group() ERNEUT auf frisch von
                               der Platte gelesenen Candidate-Objekten)
      ↓
    NUR bei vollständig PASS: einzelne, validierte unlink()-Aufrufe
      ↓
    KEEP-Integrität nach dem Delete erneut verifiziert

Kein Rollback-Versprechen (Auftrag Abschnitt 17) - stattdessen wird VOR
dem ersten Delete einer Gruppe vollständig validiert (Gruppen-Atomarität,
Auftrag Abschnitt 12: schlägt EIN Kandidat der Gruppe fehl, wird die
GESAMTE Gruppe übersprungen, kein Teil-Delete).

## Bekannte Scope-Grenze (dokumentiert, nicht Teil des Auftrags)

revalidate_group() prüft ausschließlich die im Execution Plan bereits
bekannten Kandidaten-Pfade (KEEP + REMOVE) erneut - es erfolgt KEIN
vollständiger Re-Scan des Zielverzeichnisses. Ein zwischen Plan-Erstellung
und Execute NEU hinzugekommener, potenziell kollidierender Kandidat wird
dadurch nicht erkannt. Der Auftrag verlangt Robustheit gegenüber
VERÄNDERTEN bekannten Dateien (TOCTOU, Abschnitt 7) und Gruppen-
Atomarität (Abschnitt 12) - beides ist abgedeckt; ein vollständiger
Re-Scan pro Gruppe wäre eine deutlich teurere, im Auftrag nicht
verlangte Erweiterung (Overengineering-Vermeidung, siehe Abschnitt 23).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from services.duplicate.classification import (
    Candidate,
    Confidence,
    candidate_confidence,
)
from services.duplicate.resolution import GroupAction, ResolutionDecision, resolve_group


# ─────────────────────────────────────────────────────────────────────────
# Fingerprinting (Auftrag Abschnitt 5/6 - "Der SHA-256-Wert ist besonders
# wichtig")
# ─────────────────────────────────────────────────────────────────────────


def compute_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Vollständiger SHA-256 des Dateiinhalts (nicht zu verwechseln mit
    Candidate.cover_sha256, das nur die eingebetteten Cover-Bytes hasht).
    None bei jedem Lesefehler (Datei verschwunden/nicht lesbar) - wird
    vom Aufrufer als Revalidierungs-Fehlschlag behandelt, niemals
    stillschweigend als "unverändert" interpretiert."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


@dataclass(frozen=True)
class FileFingerprint:
    """Unveränderlicher Schnappschuss (Pfad, Größe, SHA-256) - Grundlage
    jedes TOCTOU-Revalidierungsvergleichs (Auftrag Abschnitt 5/6/7)."""

    path: Path
    size: int
    sha256: str

    @classmethod
    def capture(cls, path: Path) -> Optional["FileFingerprint"]:
        """None, wenn die Datei nicht (mehr) existiert/lesbar ist - der
        Aufrufer MUSS das als Fehlschlag behandeln, nie als 0-Byte-Datei
        missinterpretieren."""
        try:
            size = path.stat().st_size
        except OSError:
            return None
        sha256 = compute_file_sha256(path)
        if sha256 is None:
            return None
        return cls(path=path, size=size, sha256=sha256)


# ─────────────────────────────────────────────────────────────────────────
# Execution Plan / Manifest (Auftrag Abschnitt 5)
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class ExecutionPlanEntry:
    """Ein Eintrag im Execution Plan - EIN Eintrag pro Duplicate-Gruppe
    mit action == RESOLVED (Auftrag Abschnitt 11: nur REMOVE_PROPOSALS,
    niemals UNKNOWN/MANUAL_REVIEW/AMBIGUOUS/SKIPPED). Wird VOR jedem
    Delete erneut vollständig validiert (revalidate_group()) - niemals
    blind ausgeführt (Auftrag Abschnitt 4/17)."""

    normalized_artist: str
    normalized_title: str
    keep: FileFingerprint
    remove: List[FileFingerprint]
    reason: str
    confidence: str
    duration_seconds: Optional[float]
    mb_recording_id: Optional[str]
    isrc: Optional[str]
    safety_gate: str  # "PASSED" - RESOLVED-Gruppen sind laut resolve_group() nie geblockt


def build_execution_plan(decisions: List[ResolutionDecision]) -> List[ExecutionPlanEntry]:
    """Baut den Execution Plan AUSSCHLIESSLICH aus Entscheidungen mit
    action == GroupAction.RESOLVED. Gruppen-atomar bereits HIER: kann für
    KEEP oder auch nur EINEN REMOVE-Kandidaten kein Fingerprint erfasst
    werden (Datei nicht lesbar), wird die GESAMTE Gruppe nicht in den
    Plan aufgenommen (Auftrag Abschnitt 12 - Gruppen-Atomarität gilt
    bereits bei der Planerstellung, nicht erst bei der Revalidierung).

    Zusätzliche Verteidigungslinie (defensiv, da durch resolve_group()
    bereits strukturell garantiert, siehe dessen Modul-Docstring Safety
    Gate): jeder Kandidat muss Confidence.HIGH besitzen, sonst wird die
    Gruppe übersprungen.
    """
    plan: List[ExecutionPlanEntry] = []
    for decision in decisions:
        if decision.action != GroupAction.RESOLVED:
            continue
        if decision.keep is None or not decision.remove_proposals:
            continue
        if candidate_confidence(decision.keep) != Confidence.HIGH:
            continue
        if any(candidate_confidence(c) != Confidence.HIGH for c in decision.remove_proposals):
            continue

        keep_fp = FileFingerprint.capture(decision.keep.path)
        if keep_fp is None:
            continue

        remove_fps: List[FileFingerprint] = []
        group_plannable = True
        for candidate in decision.remove_proposals:
            fp = FileFingerprint.capture(candidate.path)
            if fp is None:
                group_plannable = False
                break
            remove_fps.append(fp)
        if not group_plannable:
            continue

        plan.append(
            ExecutionPlanEntry(
                normalized_artist=decision.normalized_artist,
                normalized_title=decision.normalized_title,
                keep=keep_fp,
                remove=remove_fps,
                reason=decision.reason,
                confidence=candidate_confidence(decision.keep).value,
                duration_seconds=decision.keep.duration_seconds,
                mb_recording_id=decision.keep.mb_recording_id,
                isrc=decision.keep.isrc,
                safety_gate="PASSED",
            )
        )
    return plan


# ─────────────────────────────────────────────────────────────────────────
# Pre-Delete Revalidation (Auftrag Abschnitt 6/7/8/17 - TOCTOU-Schutz)
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class RevalidationResult:
    ok: bool
    stage: Optional[str] = None  # "path_safety" | "fingerprint" | "semantic"
    reason: Optional[str] = None


def revalidate_group(
    entry: ExecutionPlanEntry,
    validate_file_within_root: Callable[[Path], bool],
    build_candidate_from_path: Callable[[Path], Candidate],
) -> RevalidationResult:
    """Zweistufige Pre-Delete-Revalidierung, unmittelbar vor jedem Delete
    aufzurufen (Auftrag Abschnitt 6):

    Stufe 1 - Path-Safety + Fingerprint (TOCTOU-Schutz, Abschnitt 7/8):
    für KEEP und JEDEN REMOVE-Kandidaten - Pfad muss weiterhin innerhalb
    des erlaubten Roots liegen (injizierte `validate_file_within_root`,
    identisch zur Scan-Zeit-Prüfung in scripts/resolve_duplicates.py -
    keine eigene Kopie der Sicherheitslogik), Datei muss existieren,
    Größe UND SHA-256 müssen exakt dem Plan entsprechen. EIN
    abweichender Kandidat blockiert die GESAMTE Gruppe (Abschnitt 9/12 -
    Gruppen-Atomarität, "Safety vor Partial Cleanup").

    Stufe 2 - semantische Neuentscheidung (Abschnitt 6 "Safety Gate
    still PASS"): baut frische Candidate-Objekte aus den AKTUELLEN
    Dateien (injizierte `build_candidate_from_path` - identische
    Tag-/ffprobe-Lesepipeline wie beim ursprünglichen Scan) und führt
    resolve_group() ERNEUT aus. Nur wenn (action, KEEP-Pfad,
    REMOVE-Pfade) exakt mit dem geplanten Eintrag übereinstimmen, gilt
    die Gruppe weiterhin sicher löschbar - eine zwischenzeitliche
    Metadatenänderung (z. B. neue MusicBrainz-ID, geänderte Duration),
    die das Safety Gate heute anders entscheiden würde, wird dadurch
    erkannt.
    """
    all_fingerprints = [entry.keep] + entry.remove

    for fp in all_fingerprints:
        if not validate_file_within_root(fp.path):
            return RevalidationResult(
                ok=False, stage="path_safety",
                reason=f"Path Safety FAIL: {fp.path}",
            )

    for fp in all_fingerprints:
        current = FileFingerprint.capture(fp.path)
        if current is None:
            return RevalidationResult(
                ok=False, stage="fingerprint",
                reason=f"Datei nicht mehr lesbar/vorhanden: {fp.path}",
            )
        if current.size != fp.size:
            return RevalidationResult(
                ok=False, stage="fingerprint",
                reason=f"Dateigröße geändert seit Planerstellung: {fp.path}",
            )
        if current.sha256 != fp.sha256:
            return RevalidationResult(
                ok=False, stage="fingerprint",
                reason=f"SHA-256 geändert seit Planerstellung: {fp.path}",
            )

    fresh_keep = build_candidate_from_path(entry.keep.path)
    fresh_removes = [build_candidate_from_path(fp.path) for fp in entry.remove]
    fresh_decision = resolve_group([fresh_keep] + fresh_removes)

    if fresh_decision.action != GroupAction.RESOLVED:
        return RevalidationResult(
            ok=False, stage="semantic",
            reason=f"Safety Gate nicht mehr PASSED (jetzt: {fresh_decision.action.value})",
        )
    if fresh_decision.keep is None or fresh_decision.keep.path != entry.keep.path:
        return RevalidationResult(
            ok=False, stage="semantic",
            reason="KEEP-Kandidat hat sich seit Planerstellung geändert",
        )
    fresh_remove_paths = {c.path for c in fresh_decision.remove_proposals}
    planned_remove_paths = {fp.path for fp in entry.remove}
    if fresh_remove_paths != planned_remove_paths:
        return RevalidationResult(
            ok=False, stage="semantic",
            reason="REMOVE-Kandidaten haben sich seit Planerstellung geändert",
        )

    return RevalidationResult(ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Execute (Auftrag Abschnitt 9/12/13/14/16)
# ─────────────────────────────────────────────────────────────────────────


class FileDeleteStatus(str, Enum):
    DELETED = "DELETED"
    SKIPPED_GROUP_INVALID = "SKIPPED_GROUP_INVALID"
    FAILED = "FAILED"


@dataclass
class FileExecutionResult:
    path: Path
    status: FileDeleteStatus
    error: Optional[str] = None


@dataclass
class GroupExecutionResult:
    entry: ExecutionPlanEntry
    group_ok: bool
    skip_stage: Optional[str]
    skip_reason: Optional[str]
    file_results: List[FileExecutionResult] = field(default_factory=list)
    keep_intact: bool = True


def execute_group(
    entry: ExecutionPlanEntry,
    validate_file_within_root: Callable[[Path], bool],
    build_candidate_from_path: Callable[[Path], Candidate],
) -> GroupExecutionResult:
    """Revalidiert die Gruppe (siehe revalidate_group()) und löscht NUR
    bei vollständigem PASS die REMOVE-Kandidaten - einzeln, per
    `Path.unlink()` (Auftrag Abschnitt 13: keine Shell-Kommandos, kein
    `rm -rf`, keine Verzeichnislöschung, keine rekursiven Deletes).

    KEEP wird HIER NIEMALS gelöscht (INV-D16) - `entry.keep.path` ist
    strukturell nie Teil von `entry.remove` (garantiert durch
    resolve_group()/build_execution_plan()); zusätzlich verteidigt eine
    explizite Laufzeitprüfung pro Datei dagegen.
    """
    revalidation = revalidate_group(entry, validate_file_within_root, build_candidate_from_path)
    if not revalidation.ok:
        return GroupExecutionResult(
            entry=entry,
            group_ok=False,
            skip_stage=revalidation.stage,
            skip_reason=revalidation.reason,
            file_results=[
                FileExecutionResult(
                    path=fp.path, status=FileDeleteStatus.SKIPPED_GROUP_INVALID,
                    error=revalidation.reason,
                )
                for fp in entry.remove
            ],
            keep_intact=True,  # nichts wurde angefasst
        )

    file_results: List[FileExecutionResult] = []
    for fp in entry.remove:
        if fp.path == entry.keep.path:
            # INV-D16 defensiv: strukturell durch resolve_group() bereits
            # ausgeschlossen, hier zusätzlich zur Laufzeit verweigert.
            file_results.append(
                FileExecutionResult(
                    path=fp.path, status=FileDeleteStatus.FAILED,
                    error="INTERNAL SAFETY: REMOVE-Pfad identisch mit KEEP-Pfad - Delete verweigert",
                )
            )
            continue
        try:
            fp.path.unlink()
            if fp.path.exists():
                file_results.append(
                    FileExecutionResult(
                        path=fp.path, status=FileDeleteStatus.FAILED,
                        error="Datei existiert nach unlink() weiterhin",
                    )
                )
            else:
                file_results.append(FileExecutionResult(path=fp.path, status=FileDeleteStatus.DELETED))
        except OSError as e:
            file_results.append(
                FileExecutionResult(path=fp.path, status=FileDeleteStatus.FAILED, error=str(e))
            )

    keep_after = FileFingerprint.capture(entry.keep.path)
    keep_intact = keep_after is not None and keep_after.sha256 == entry.keep.sha256 and keep_after.size == entry.keep.size

    group_ok = keep_intact and all(r.status == FileDeleteStatus.DELETED for r in file_results)

    return GroupExecutionResult(
        entry=entry,
        group_ok=group_ok,
        skip_stage=None,
        skip_reason=None,
        file_results=file_results,
        keep_intact=keep_intact,
    )
