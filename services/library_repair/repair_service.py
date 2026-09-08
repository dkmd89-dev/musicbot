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

Der Journal (siehe oben) hat keine Lauf-Gruppierung (kein "welche
Einträge gehören zu EINEM Telegram-Tap"). Da das Journal selbst bewusst
NICHT verändert wird (Abschnitt 30: bestehende Infrastruktur
wiederverwenden, keine invasive Änderung an einem bereits gehärteten,
1300+ Zeilen umfassenden Modul), führt dieser Service einen kleinen,
zusätzlichen Read-only-kompatiblen Laufindex (`library_repair_runs.json`)
- er verweist per Byte-Offset-Fenster auf die tatsächlich im Journal
bereits vorhandenen Einträge, dupliziert deren Inhalt aber nicht
(Abschnitt 44: "nur wenn keine geeignete Persistenz vorhanden ist, darf
eine neue Repair History eingeführt werden" - die Lauf-GRUPPIERUNG fehlt
im Journal, die Datei-FAKTEN selbst nicht).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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

logger = get_module_logger("RepairService")

RUNS_INDEX_FILENAME = "library_repair_runs.json"
LOCK_FILENAME = "library_repair.lock"
JOURNAL_FILENAME = "library_repair_journal.jsonl"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


class RepairServiceError(Exception):
    """Basisklasse für Fehler dieses Services."""


class RepairAlreadyRunningError(RepairServiceError):
    """Wird geworfen, wenn bereits ein Repair-Lauf aktiv ist (Abschnitt 42)."""


class HealthScanFailedError(RepairServiceError):
    """Der zugrunde liegende Health-Scan (Plan-Grundlage) ist fehlgeschlagen."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_dir() -> Path:
    return Path(Config.DATA_DIR)


def _journal_path() -> Path:
    return _data_dir() / JOURNAL_FILENAME


def _runs_index_path() -> Path:
    return _data_dir() / RUNS_INDEX_FILENAME


def _lock_path() -> Path:
    return _data_dir() / LOCK_FILENAME


def _findings_registry_path() -> Path:
    return _data_dir() / FINDINGS_DEFAULT_FILENAME


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
# Concurrency-Schutz (Abschnitt 42)
# ─────────────────────────────────────────────────────────────────────────


def acquire_repair_lock() -> None:
    """Atomare, prozessübergreifende Sperre (O_CREAT|O_EXCL) - schützt
    sowohl gegen einen zweiten gleichzeitigen Telegram-Tap als auch gegen
    einen parallel von der Kommandozeile gestarteten
    `scripts/library_repair.py --apply`-Lauf. Es gab zuvor KEINEN
    Lock-/Job-Mechanismus für Repair-Läufe (verifiziert: weder
    doctor_runner.py noch scripts/library_repair.py hatten einen) - dies
    ist die in Abschnitt 42 geforderte, bislang fehlende Schutzmaßnahme."""
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()}|{_now_iso()}")
    except FileExistsError as e:
        raise RepairAlreadyRunningError(
            "Es läuft bereits eine Reparatur - bitte warten, bis diese "
            "abgeschlossen ist."
        ) from e


def release_repair_lock() -> None:
    _lock_path().unlink(missing_ok=True)


def is_repair_running() -> bool:
    return _lock_path().exists()


# ─────────────────────────────────────────────────────────────────────────
# Journal-Fenster-Lesen (fuer Run-Korrelation, siehe Modul-Docstring)
# ─────────────────────────────────────────────────────────────────────────


def _read_journal_window(offset_before: int, offset_after: int) -> list[dict]:
    path = _journal_path()
    if not path.exists() or offset_after <= offset_before:
        return []
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        f.seek(offset_before)
        chunk = f.read(offset_after - offset_before)
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


# ─────────────────────────────────────────────────────────────────────────
# Repair-Runs-Index (Repair History, Abschnitt 44/45)
# ─────────────────────────────────────────────────────────────────────────


def _write_json_atomic(path: Path, data: dict) -> None:
    """write-tmp + Path.replace() - dasselbe, im Projekt etablierte Muster
    (INV-02) wie services/library_health/findings.py::FindingsRegistry.
    _write_json_atomic() und diverse weitere Stores (siehe dortigen
    Kommentar)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp_{int(time.time() * 1000)}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load_runs_index() -> dict:
    path = _runs_index_path()
    if not path.exists():
        return {"runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning(f"⚠️ Repair-Runs-Index unlesbar, wird als leer behandelt: {path}")
        return {"runs": []}
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return {"runs": []}
    return data


def _append_run_record(record: dict) -> None:
    data = _load_runs_index()
    data["runs"].append(record)
    _write_json_atomic(_runs_index_path(), data)


def load_repair_history(limit: Optional[int] = None) -> list[dict]:
    """Repair History (Abschnitt 44/45) - neueste zuerst. `limit=None`
    liefert alle Einträge."""
    runs = list(reversed(_load_runs_index().get("runs", [])))
    return runs[:limit] if limit else runs


def compute_repair_statistics() -> dict:
    """Repair-Statistik (Abschnitt 46) - ausschließlich aus der
    tatsächlichen Repair History berechnet, keine hartkodierten Werte."""
    runs = _load_runs_index().get("runs", [])
    totals = Counter()
    code_counts: Counter = Counter()
    for run in runs:
        counts = run.get("status_counts") or {}
        for status, n in counts.items():
            totals[status] += n
        for code in run.get("issue_codes") or []:
            code_counts[code] += 1

    return {
        "total_runs": len(runs),
        "total": sum(totals.values()),
        "success": totals.get(STATUS_SUCCESS, 0),
        "failed": totals.get(STATUS_FAILED, 0),
        "skipped": totals.get(STATUS_SKIPPED, 0),
        "most_common_issue_codes": code_counts.most_common(),
    }


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
        started_at = _now_iso()

        try:
            plan = await build_repair_plan(scan_timeout=scan_timeout)
        except HealthScanFailedError as e:
            return RepairRunResult(
                repair_id=str(uuid.uuid4()), status=STATUS_FAILED,
                started_at=started_at, finished_at=_now_iso(),
                candidates_total=0, resolved_count=0,
                error_message=f"Health-Scan fehlgeschlagen: {e}",
            )

        safe_candidates = get_safe_automatic_candidates(plan)
        if not safe_candidates:
            return RepairRunResult(
                repair_id=str(uuid.uuid4()), status=STATUS_SKIPPED,
                started_at=started_at, finished_at=_now_iso(),
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

        journal_path = _journal_path()
        offset_before = journal_path.stat().st_size if journal_path.exists() else 0

        repair_result = await run_safe_automatic_repair(timeout=scan_timeout)

        offset_after = journal_path.stat().st_size if journal_path.exists() else offset_before
        entries = _read_journal_window(offset_before, offset_after)
        status_counts = dict(Counter(e.get("status") for e in entries))
        finished_at = _now_iso()

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

        _append_run_record({
            "repair_id": repair_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "triggered_by": triggered_by,
            "level": "SAFE_AUTOMATIC",
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
