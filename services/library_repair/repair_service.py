# services/library_repair/repair_service.py
# -*- coding: utf-8 -*-
"""
Repair MusicBot — Orchestrierungsservice (Aufgabe "Repair MusicBot", Teil C).

Verantwortlichkeit (Aufgabe Abschnitt 1/7):

    Findings lesen
    → Reparierbarkeit bestimmen
    → Repair Plan erstellen
    → Preview erzeugen
    → (Bestätigung verlangen — Telegram-/CLI-Schicht, nicht hier)
    → Repair Executor ausführen
    → Verification durchführen
    → Findings nach erfolgreicher Verification aktualisieren
    → Repair History speichern

Reine Orchestrierung um BEREITS BESTEHENDE Komponenten (Abschnitt 30) -
keine zweite Repair-Engine, kein zweiter Safety-/Rollback-Mechanismus:

    services/library_repair/doctor_runner.py::run_health_scan()/
        run_safe_automatic_repair()   — bereits gehärteter Subprozess-Pfad
                                         (derselbe, den MusicBot Doctor
                                         nutzt); der Scan-Aufruf triggert
                                         intern bereits den Findings-Merge
                                         (scripts/library_health_check.py).
    services/library_repair/planner.py::plan_repairs()/filter_plan()
                                       — bestehender, read-only Planner.
    services/library_repair/journal.py::RepairJournal
                                       — bestehende Repair-History-Quelle
                                         (append-only JSONL, ein Eintrag
                                         pro tatsächlich geänderter Datei).
    services/library_health/findings.py::FindingsRegistry
                                       — Status-Änderung AUSSCHLIESSLICH
                                         nach erfolgreicher Verification,
                                         NIE automatisch FALSE_POSITIVE
                                         (Abschnitt 39).

Bewusst NUR SAFE_AUTOMATIC über diesen Weg ausführbar - identische
Sicherheitsgrenze wie MusicBot Doctor (siehe
handlers/library_doctor_handler.py, docs/LIBRARY_REPAIR.md §3): alle
externen/destruktiven Level (COVER/EXTERNAL_METADATA/
METADATA_REPROCESSING/LOUDNESS/DUPLICATE) bleiben CLI-only. Repair
MusicBot ist KEINE Ausweitung dieser Grenze, sondern eine reichhaltigere
Oberfläche (Plan/Preview/History/Statistik) für denselben, bereits
etablierten Ausführungspfad.

Lock/Journal-Fenster/Run-Index/History/Statistik sind seit ARCH-032
Phase 3 (ADR-0004) nach services/library_repair/run_tracking.py
ausgelagert - geteilte Infrastruktur mit dem neuen Command-getriebenen
Maintenance-Flow (services/library_repair/maintenance_service.py). Diese
Datei re-exportiert die dort definierten Namen fuer Rueckwaertskompatibilitaet
bestehender Importe (z. B. handlers/repair_musicbot_handler.py).
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from config import Config
from logger import get_module_logger
from services.library_health.findings import (
    STATUS_OPEN,
    STATUS_RESOLVED,
    FindingsRegistry,
    generate_finding_id,
)
from services.library_health.findings import DEFAULT_FILENAME as FINDINGS_DEFAULT_FILENAME
from services.library_repair.doctor_runner import run_health_scan, run_safe_automatic_repair
from services.library_repair.models import RepairCandidate, RepairPlan
from services.library_repair.planner import filter_plan, plan_repairs
from services.library_repair.run_tracking import (
    KIND_REPAIR,
    RUNS_INDEX_FILENAME,
    LOCK_FILENAME,
    JOURNAL_FILENAME,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
    RepairAlreadyRunningError,
    RepairServiceError,
    acquire_repair_lock,
    append_run_record,
    compute_repair_statistics,
    data_dir,
    is_repair_running,
    journal_path,
    load_repair_history,
    load_runs_index,
    lock_path,
    now_iso,
    read_journal_window,
    release_repair_lock,
    runs_index_path,
    write_json_atomic,
)

logger = get_module_logger("RepairService")


class HealthScanFailedError(RepairServiceError):
    """Der zugrunde liegende Health-Scan (Plan-Grundlage) ist fehlgeschlagen."""


def _findings_registry_path():
    return data_dir() / FINDINGS_DEFAULT_FILENAME


def _candidate_to_issue_dict(candidate: RepairCandidate) -> dict:
    """Bildet einen RepairCandidate auf dasselbe Dict-Schema ab, das
    generate_finding_id() erwartet (Issue.to_dict()-Schema) - RepairPlan
    trägt bewusst KEIN eigenes finding_id-Feld (Abschnitt 30: bestehende
    Modelle in services/library_repair/models.py bleiben unverändert),
    die Identität wird bei Bedarf aus denselben Feldern neu abgeleitet,
    die auch der Scanner für dasselbe Issue geliefert hat."""
    return {
        "issue_code": candidate.issue_code,
        "scope": candidate.scope,
        "artist": candidate.artist,
        "album": candidate.album,
        "title": candidate.title,
        "path": candidate.path,
        "related_files": candidate.related_files,
    }


def _open_issues(report: dict) -> list[dict]:
    """Filtert die (bereits vom Scan-Lauf Findings-annotierten) Issues auf
    aktuell OFFENE Befunde (Abschnitt 28/39) - Repair darf niemals
    FALSE_POSITIVE- oder bereits RESOLVED-Findings als Reparaturkandidaten
    anbieten. Ein Issue ohne 'finding_status'-Feld (Report ohne Findings-
    Integration) gilt als offen - identische Konvention wie
    report.py::_split_issues_by_finding_status()."""
    return [
        i for i in report.get("issues", [])
        if i.get("finding_status", STATUS_OPEN) == STATUS_OPEN
    ]


# ─────────────────────────────────────────────────────────────────────────
# Plan / Preview (Abschnitt 28/29/31/32)
# ─────────────────────────────────────────────────────────────────────────


async def build_repair_plan(*, scan_timeout: float = 900.0) -> RepairPlan:
    """Führt einen frischen, read-only Health-Scan aus (identischer,
    bereits gehärteter Subprozess-Pfad wie MusicBot Doctor - inkl. dem
    darin bereits integrierten Findings-Merge) und baut daraus einen
    RepairPlan AUSSCHLIESSLICH aus aktuell OFFENEN Findings (Abschnitt 28).

    Wirft HealthScanFailedError, wenn der Scan selbst fehlschlägt - kein
    Plan wird ohne einen tatsächlich erfolgreichen Scan erzeugt."""
    scan_result = await run_health_scan(timeout=scan_timeout)
    if not scan_result.success or scan_result.report is None:
        raise HealthScanFailedError(
            scan_result.error_message or f"Exit-Code {scan_result.exit_code}"
        )
    open_report = dict(scan_result.report)
    open_report["issues"] = _open_issues(scan_result.report)
    return plan_repairs(open_report)


def get_safe_automatic_candidates(plan: RepairPlan) -> list[RepairCandidate]:
    """Nur SAFE_AUTOMATIC ist über Telegram tatsächlich ausführbar
    (Abschnitt 34, identische Grenze wie MusicBot Doctor) - alle anderen
    Level werden im Plan zwar angezeigt (Abschnitt 29: nicht reparierbare/
    nicht-Telegram-ausführbare Findings müssen gekennzeichnet werden),
    aber nie automatisch gestartet."""
    return filter_plan(plan, level="SAFE_AUTOMATIC").candidates


@dataclass
class RepairPreview:
    """Read-only Vorschau (Abschnitt 32) - identifiziert Executor,
    betroffene Findings/Dateien und Safety-Level, OHNE etwas zu verändern."""

    level: str
    executor_components: list[str]
    candidates: list[RepairCandidate]
    affected_files: list[str]
    read_only: bool = True

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


def build_preview(candidates: list[RepairCandidate], *, level: str = "SAFE_AUTOMATIC") -> RepairPreview:
    """Reines Rendering-Dict aus bereits vorhandenen Plan-Daten - kein
    Dateisystemzugriff, keine Änderung (Abschnitt 32: 'Preview MUSS
    read-only sein')."""
    components = sorted({c.reuses_component for c in candidates if c.reuses_component})
    files = sorted({c.path for c in candidates if c.path})
    return RepairPreview(
        level=level, executor_components=components, candidates=list(candidates),
        affected_files=files,
    )


# ─────────────────────────────────────────────────────────────────────────
# Execute + Verification (Abschnitt 35/38/39/40/41)
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class RepairRunResult:
    repair_id: str
    status: str  # SUCCESS | FAILED | SKIPPED
    started_at: str
    finished_at: str
    candidates_total: int
    resolved_count: int
    status_counts: dict = field(default_factory=dict)
    affected_files: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    error_message: Optional[str] = None
    # Production-Audit 2026-09-08 (Verification-Asymmetrie CLI vs. Telegram):
    # Issue-Codes, die NICHT von dieser Reparatur berührt wurden, aber nach
    # dem Verification-Scan MEHR offene Findings zeigen als davor - Signal
    # für eine unerwartete Nebenwirkung, analog zu scripts/library_repair.py
    # ::_verification_scan()'s regressed-Erkennung, hier zusätzlich pro
    # Issue-Code statt nur aggregiert über die ganze Library.
    regressed_issue_codes: list = field(default_factory=list)


async def execute_safe_automatic_repair(
    *, triggered_by: str, scan_timeout: float = 900.0,
) -> RepairRunResult:
    """Führt den bestehenden SAFE_AUTOMATIC-Executor-Pfad aus
    (doctor_runner.run_safe_automatic_repair(), identisch zu MusicBot
    Doctor) und markiert Findings ausschließlich nach erfolgreicher
    Verification als RESOLVED (Abschnitt 38/40) - niemals automatisch
    FALSE_POSITIVE (Abschnitt 39).

    Baut UNMITTELBAR vor der Ausführung einen komplett frischen Plan
    (Abschnitt 41: 'Stale Repair Plan') - es wird nie ein an anderer
    Stelle zuvor erzeugter Plan wiederverwendet, die Ausführung kann
    daher strukturell nicht auf einem veralteten Plan basieren.
    """
    acquire_repair_lock()
    try:
        started_at = now_iso()

        try:
            plan = await build_repair_plan(scan_timeout=scan_timeout)
        except HealthScanFailedError as e:
            return RepairRunResult(
                repair_id=str(uuid.uuid4()), status=STATUS_FAILED,
                started_at=started_at, finished_at=now_iso(),
                candidates_total=0, resolved_count=0,
                error_message=f"Health-Scan fehlgeschlagen: {e}",
            )

        safe_candidates = get_safe_automatic_candidates(plan)
        if not safe_candidates:
            return RepairRunResult(
                repair_id=str(uuid.uuid4()), status=STATUS_SKIPPED,
                started_at=started_at, finished_at=now_iso(),
                candidates_total=0, resolved_count=0,
            )

        pre_finding_ids = {
            generate_finding_id(_candidate_to_issue_dict(c)) for c in safe_candidates
        }
        issue_codes = sorted({c.issue_code for c in safe_candidates})
        # Baseline für die Regressionserkennung unten - kostenlos aus dem
        # bereits vorhandenen Plan abgeleitet (build_repair_plan() hat den
        # Scan bereits durchgeführt, kein zusätzlicher I/O nötig).
        pre_open_counts = Counter(c.issue_code for c in plan.candidates)

        jpath = journal_path()
        offset_before = jpath.stat().st_size if jpath.exists() else 0

        repair_result = await run_safe_automatic_repair(timeout=scan_timeout)

        offset_after = jpath.stat().st_size if jpath.exists() else offset_before
        entries = read_journal_window(offset_before, offset_after)
        status_counts = dict(Counter(e.get("status") for e in entries))
        finished_at = now_iso()

        # ── Verification (Abschnitt 38/40): erneuter Health-Scan ─────────
        resolved_ids: list[str] = []
        regressed_issue_codes: list[str] = []
        try:
            post_scan = await run_health_scan(timeout=scan_timeout)
        except Exception as e:  # noqa: BLE001
            logger.error(f"💥 Verification-Scan fehlgeschlagen: {e}", exc_info=True)
            post_scan = None

        if post_scan is not None and post_scan.success and post_scan.report is not None:
            post_open_ids = {
                i.get("finding_id") for i in post_scan.report.get("issues", [])
                if i.get("finding_status", STATUS_OPEN) == STATUS_OPEN
            }
            try:
                registry = FindingsRegistry(_findings_registry_path())
            except Exception as e:  # noqa: BLE001
                logger.error(f"💥 Findings-Registry nicht ladbar für Verification: {e}")
                registry = None

            if registry is not None:
                # Regressionserkennung (Production-Audit 2026-09-08): ein
                # Issue-Code, den diese Reparatur nicht berührt hat, aber
                # der nach dem Scan MEHR offene Findings zeigt als vorher,
                # ist ein Hinweis auf eine unerwartete Nebenwirkung. Vor dem
                # Resolve-Loop unten berechnet, damit das eigene Setzen von
                # RESOLVED die Zählung nicht verfälscht.
                post_open_counts = Counter(f.code for f in registry.get_open_findings())
                regressed_issue_codes.extend(sorted(
                    code for code, n in post_open_counts.items()
                    if code not in issue_codes and n > pre_open_counts.get(code, 0)
                ))
                for fid in pre_finding_ids:
                    finding = registry.get(fid)
                    if finding is None or finding.status != STATUS_OPEN:
                        continue
                    if fid in post_open_ids:
                        continue  # weiterhin erkannt -> NICHT verifiziert behoben
                    registry.review_finding(
                        fid, STATUS_RESOLVED, reviewed_by=f"repair:{triggered_by}",
                        note="Automatisch verifiziert nach SAFE_AUTOMATIC-Reparatur "
                             "(erneuter Health-Scan bestätigt Behebung).",
                    )
                    resolved_ids.append(fid)
                registry.save()

        repair_id = str(uuid.uuid4())
        affected_files = sorted({e.get("file") for e in entries if e.get("file")})

        if repair_result.timed_out or repair_result.error_message:
            overall_status = STATUS_FAILED
        elif status_counts.get(STATUS_FAILED, 0) > 0 and status_counts.get(STATUS_SUCCESS, 0) == 0:
            overall_status = STATUS_FAILED
        elif status_counts.get(STATUS_SUCCESS, 0) > 0:
            overall_status = STATUS_SUCCESS
        else:
            overall_status = STATUS_SKIPPED

        append_run_record({
            "repair_id": repair_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "triggered_by": triggered_by,
            "level": "SAFE_AUTOMATIC",
            "kind": KIND_REPAIR,
            "exit_code": repair_result.exit_code,
            "status": overall_status,
            "finding_ids": sorted(pre_finding_ids),
            "resolved_finding_ids": resolved_ids,
            "issue_codes": issue_codes,
            "status_counts": status_counts,
            "affected_files": affected_files,
            "regressed_issue_codes": regressed_issue_codes,
        })

        return RepairRunResult(
            repair_id=repair_id, status=overall_status,
            started_at=started_at, finished_at=finished_at,
            candidates_total=len(pre_finding_ids), resolved_count=len(resolved_ids),
            status_counts=status_counts, affected_files=affected_files, entries=entries,
            error_message=repair_result.error_message,
            regressed_issue_codes=regressed_issue_codes,
        )
    finally:
        release_repair_lock()
