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
from services.library_repair.doctor_runner import (
    run_health_scan,
    run_level2_repair,
    run_level3_repair,
    run_safe_automatic_repair,
)
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


# ─────────────────────────────────────────────────────────────────────────
# Level 2 / Level 3 — Pro-Artist-Reparatur (ARCH-033, ADR-0003/ADR-0004)
#
# Bewusst getrennte Funktionen je Level statt eines gemeinsamen
# "execute_level_repair(level=...)" (ADR-0003: L2/L3 werden pro Artist
# GETRENNT bestaetigt - unterschiedliche Blast-Radien/Nebeneffekte,
# siehe docs/adr/0003). execute_safe_automatic_repair() oben bleibt
# unveraendert - diese beiden neuen Funktionen sind eigenstaendige
# Geschwister, kein Refactor der bestehenden Funktion.
#
# Subprozess-Ausfuehrung (doctor_runner.run_level2_repair()/
# run_level3_repair()) statt direktem In-Process-Aufruf von
# executor.py::apply_level2()/apply_external_metadata() - waehrend der
# Implementierung als echter Architekturkonflikt erkannt und mit dem
# Nutzer geklaert (EnhancedMetadataProcessor-Singleton-Risiko, siehe
# doctor_runner.py::_run_level_repair_subprocess()-Docstring). apply_level2()
# und apply_external_metadata() selbst bleiben dadurch komplett
# unveraendert - sie laufen weiterhin (wie schon vor ARCH-033) nur
# innerhalb des scripts/library_repair.py-Subprozesses.
# ─────────────────────────────────────────────────────────────────────────

_LEVEL_LABELS = {"l2": "METADATA_REPROCESSING", "l3": "EXTERNAL_METADATA"}


@dataclass
class LevelRepairResult:
    """Ergebnis eines Pro-Artist L2/L3-Laufs (ARCH-033)."""

    repair_id: str
    artist: str
    level: str  # "l2" | "l3"
    status: str  # SUCCESS | FAILED | SKIPPED
    started_at: str
    finished_at: str
    total: int
    success: int = 0
    failed: int = 0
    skipped: int = 0
    unresolved: int = 0
    resolved_count: int = 0
    entries: list = field(default_factory=list)
    affected_files: list = field(default_factory=list)
    # ARCH-033-F1: affected_files zaehlt ALLE beruehrten Dateien (auch
    # SKIPPED, siehe unten) - bewusst unveraendert, da handlers/
    # repair_musicbot_handler.py der einzige bekannte Konsument mit
    # "tatsaechlich geaendert"-Semantik ist, control_center/routers/
    # jobs.py aber bereits denselben affected_files-Wert mit "beruehrt"-
    # Semantik weiterreicht (repoweit verifiziert). changed_files ist
    # additiv nur fuer den Telegram-Handler gedacht.
    changed_files: list = field(default_factory=list)
    # Bewusst nie berechnet (ARCH-033): kein verlaessliches maschinenlesbares
    # Signal ueber die Subprozess-Grenze hinweg, wie viele Auto-Learn-
    # Mapping-Eintraege sich geaendert haben, ohne fragile Pfad-/Diff-
    # Heuristiken gegen mapping/auto_learned_*.json einzufuehren. Bleibt
    # None - der pauschale Preview-Hinweis (Auftrag §2) deckt die
    # eigentliche Anforderung ("Nutzer weiss, dass es passieren kann") ab.
    auto_learn_changed: Optional[int] = None
    rescan_triggered: bool = False
    error_message: Optional[str] = None


async def _execute_level_repair(
    level: str, artist: str, *, triggered_by: str, scan_timeout: float = 900.0,
) -> LevelRepairResult:
    """Gemeinsame Implementierung fuer execute_level2_repair()/
    execute_level3_repair() - siehe dort fuer die oeffentliche API.
    `level` ist "l2" oder "l3" (intern gemappt auf den echten
    RepairLevel-Wert fuer filter_plan())."""
    repair_level = _LEVEL_LABELS[level]
    # Namens-Lookup im Modul-Globalstate zur AUFRUFZEIT (nicht ein beim
    # Import einmalig gebautes Dict!) - nur so wirkt
    # patch.object(rs, "run_level2_repair"/"run_level3_repair", ...) in
    # Tests (identisches Prinzip wie der bare-name-Aufruf von
    # run_safe_automatic_repair() oben in execute_safe_automatic_repair()).
    # Ein Dict mit frueh gebundenen Funktionsreferenzen wuerde Mocks
    # stillschweigend ignorieren und stattdessen den echten Subprozess
    # gegen die Produktions-Library starten.
    run_repair = globals()["run_level2_repair" if level == "l2" else "run_level3_repair"]

    acquire_repair_lock()
    try:
        started_at = now_iso()
        repair_id = str(uuid.uuid4())

        # Stale-Plan-Schutz (ADR-0003/Abschnitt 41, identisch zu
        # execute_safe_automatic_repair()): immer ein frischer Scan+Plan
        # unmittelbar vor der Ausfuehrung.
        try:
            plan = await build_repair_plan(scan_timeout=scan_timeout)
        except HealthScanFailedError as e:
            return LevelRepairResult(
                repair_id=repair_id, artist=artist, level=level, status=STATUS_FAILED,
                started_at=started_at, finished_at=now_iso(), total=0,
                error_message=f"Health-Scan fehlgeschlagen: {e}",
            )

        candidates = filter_plan(plan, artist=artist, level=repair_level).candidates
        if not candidates:
            return LevelRepairResult(
                repair_id=repair_id, artist=artist, level=level, status=STATUS_SKIPPED,
                started_at=started_at, finished_at=now_iso(), total=0,
            )

        pre_finding_ids = {
            generate_finding_id(_candidate_to_issue_dict(c)) for c in candidates
        }
        issue_codes = sorted({c.issue_code for c in candidates})

        jpath = journal_path()
        offset_before = jpath.stat().st_size if jpath.exists() else 0

        repair_result = await run_repair(artist, timeout=scan_timeout)

        offset_after = jpath.stat().st_size if jpath.exists() else offset_before
        entries = read_journal_window(offset_before, offset_after)
        status_counts = dict(Counter(e.get("status") for e in entries))
        finished_at = now_iso()

        # ── Verification (identisch zu execute_safe_automatic_repair) ────
        resolved_ids: list[str] = []
        rescan_triggered = False
        if status_counts.get(STATUS_SUCCESS, 0) > 0:
            rescan_triggered = True
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
                    for fid in pre_finding_ids:
                        finding = registry.get(fid)
                        if finding is None or finding.status != STATUS_OPEN:
                            continue
                        if fid in post_open_ids:
                            continue
                        registry.review_finding(
                            fid, STATUS_RESOLVED, reviewed_by=f"repair:{triggered_by}",
                            note=f"Automatisch verifiziert nach {repair_level}-Reparatur "
                                 "(erneuter Health-Scan bestätigt Behebung).",
                        )
                        resolved_ids.append(fid)
                    registry.save()

        affected_files = sorted({e.get("file") for e in entries if e.get("file")})
        # ARCH-033-F1 Fix (b): changed_files zaehlt tatsaechlich geaenderte
        # Dateien - SUCCESS/UNRESOLVED IMMER, ein SKIPPED-Eintrag NUR wenn
        # sha256_before != sha256_after (Adversarial-Review-Fund: L2
        # (apply_level2(), executor.py) markiert pro Issue-Code SKIPPED,
        # sobald NUR das Zielfeld DIESES Issues unveraendert blieb -
        # reprocess() laeuft aber immer als volle Pipeline und kann dabei
        # andere Felder geschrieben haben, siehe
        # docs/LIBRARY_REPAIR.md §12/§5. Ein reiner Status-Filter wuerde
        # solche real geschriebenen Dateien unterzaehlen). affected_files
        # bleibt oben unveraendert (andere Konsumenten, siehe
        # LevelRepairResult-Docstring-Kommentar).
        def _wrote_to_disk(entry: dict) -> bool:
            if entry.get("status") in (STATUS_SUCCESS, "UNRESOLVED"):
                return True
            sha_before, sha_after = entry.get("sha256_before"), entry.get("sha256_after")
            return bool(sha_before) and bool(sha_after) and sha_before != sha_after

        changed_files = sorted({
            e.get("file") for e in entries if e.get("file") and _wrote_to_disk(e)
        })

        # ARCH-033-F1 Fix (c), Adversarial-Review-Fund: ein Subprozess, der
        # VOR dem ersten Journal-Write abbricht (scripts/library_repair.py
        # Exit-Code 2/3 - Report-Ladefehler/SCHWERER FEHLER), liefert
        # weder einen Journal-Eintrag noch (anders als bei Start-/Timeout-
        # Fehlern) ein doctor_runner-error_message - ohne diesen Zweig
        # wuerde das als leerer, harmloser Lauf angezeigt statt als Fehler.
        crashed_without_journal = (
            not entries and not repair_result.timed_out and not repair_result.error_message
            and repair_result.exit_code not in (0, None)
        )
        error_message = repair_result.error_message
        if crashed_without_journal:
            stderr_tail = (repair_result.stderr_tail or "").strip()
            error_message = (
                f"Repair-Subprozess beendete sich mit Exit-Code "
                f"{repair_result.exit_code} ohne Journal-Einträge."
                + (f" stderr: {stderr_tail[-500:]}" if stderr_tail else "")
            )

        if repair_result.timed_out or error_message:
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
            "level": repair_level,
            "kind": KIND_REPAIR,
            "artist": artist,
            "exit_code": repair_result.exit_code,
            "status": overall_status,
            "finding_ids": sorted(pre_finding_ids),
            "resolved_finding_ids": resolved_ids,
            "issue_codes": issue_codes,
            "status_counts": status_counts,
            "affected_files": affected_files,
        })

        return LevelRepairResult(
            repair_id=repair_id, artist=artist, level=level, status=overall_status,
            started_at=started_at, finished_at=finished_at, total=len(candidates),
            success=status_counts.get(STATUS_SUCCESS, 0),
            failed=status_counts.get(STATUS_FAILED, 0),
            skipped=status_counts.get(STATUS_SKIPPED, 0),
            unresolved=status_counts.get("UNRESOLVED", 0),
            resolved_count=len(resolved_ids),
            entries=entries, affected_files=affected_files, changed_files=changed_files,
            rescan_triggered=rescan_triggered,
            error_message=error_message,
        )
    finally:
        release_repair_lock()


async def execute_level2_repair(
    artist: str, *, triggered_by: str, scan_timeout: float = 900.0,
) -> LevelRepairResult:
    """Pro-Artist L2-Reparatur (METADATA_REPROCESSING, ARCH-033/ADR-0003).
    Ruft scripts/library_repair.py --artist <artist> --level
    METADATA_REPROCESSING --apply als Subprozess auf (doctor_runner.
    run_level2_repair()) - apply_level2() selbst bleibt unveraendert.
    Nutzt denselben Lock/Journal/Run-Index wie SAFE_AUTOMATIC und die
    Library-Wartung (run_tracking.py, ADR-0004); Run-Record-`kind` bleibt
    "repair" (nicht "maintenance") - dies ist Finding-getriebene
    Reparatur, keine Command-getriebene Maintenance-Action."""
    return await _execute_level_repair(
        "l2", artist, triggered_by=triggered_by, scan_timeout=scan_timeout,
    )


async def execute_level3_repair(
    artist: str, *, triggered_by: str, scan_timeout: float = 900.0,
) -> LevelRepairResult:
    """Pro-Artist L3-Reparatur (EXTERNAL_METADATA, ARCH-033/ADR-0003).
    Analog execute_level2_repair() - ruft
    doctor_runner.run_level3_repair() auf. Netzwerk-/Rate-Limit-Fehler
    gegen MusicBrainz schlagen sichtbar als FAILED nieder (im Journal-
    Eintrag der jeweiligen Datei dokumentiert durch
    apply_external_metadata() selbst) - kein stilles SKIPPED."""
    return await _execute_level_repair(
        "l3", artist, triggered_by=triggered_by, scan_timeout=scan_timeout,
    )
