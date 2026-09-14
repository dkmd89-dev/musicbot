# services/library_repair/run_tracking.py
# -*- coding: utf-8 -*-
"""
Shared Run Tracking (ARCH-032 Phase 3, ADR-0004).

Extrahiert aus repair_service.py — reiner Move, KEINE Verhaltensaenderung
(gleiche Dateipfade, gleiche Lock-Semantik, gleiche JSON-Struktur, gleiche
Fehlerbehandlung, gleiche Rueckgabewerte). Von repair_service.py
(Finding-Flow) UND maintenance_service.py (Command-Flow, ARCH-032
Phase 3B) gemeinsam genutzt — EIN Lock, EIN Journal, EIN Run-Index fuer
beide Flows (ARCH-031 B.6, ADR-0004 Variante C statt Duplikat/Vermischung).

`repair_service.py` re-exportiert die hier definierten Namen fuer
Rueckwaertskompatibilitaet bestehender Importe
(`from services.library_repair.repair_service import load_repair_history`
funktioniert unveraendert weiter).
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Config
from logger import get_module_logger

logger = get_module_logger("RepairRunTracking")

RUNS_INDEX_FILENAME = "library_repair_runs.json"
LOCK_FILENAME = "library_repair.lock"
JOURNAL_FILENAME = "library_repair_journal.jsonl"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

# Run-Record "kind" (ARCH-031 B.6/ADR-0004): additiv. Alte Records ohne
# dieses Feld gelten als "repair" (Rueckwaertskompatibilitaet) — keine
# Migration bestehender library_repair_runs.json-Dateien erzwungen.
KIND_REPAIR = "repair"
KIND_MAINTENANCE = "maintenance"


class RepairServiceError(Exception):
    """Basisklasse fuer Fehler der Repair-/Maintenance-Orchestrierung."""


class RepairAlreadyRunningError(RepairServiceError):
    """Wird geworfen, wenn bereits ein Repair- oder Maintenance-Lauf aktiv
    ist (EIN gemeinsamer Lock ueber beide Flows, ARCH-031 B.6)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_dir() -> Path:
    return Path(Config.DATA_DIR)


def journal_path() -> Path:
    return data_dir() / JOURNAL_FILENAME


def runs_index_path() -> Path:
    return data_dir() / RUNS_INDEX_FILENAME


def lock_path() -> Path:
    return data_dir() / LOCK_FILENAME


# ─────────────────────────────────────────────────────────────────────────
# Concurrency-Schutz — EIN gemeinsamer Lock fuer Finding-Repair UND
# Maintenance-Actions (kein Feingranularitaets-Lock pro Artist, bewusste
# Vereinfachung, ARCH-031 B.6).
# ─────────────────────────────────────────────────────────────────────────


def acquire_repair_lock() -> None:
    """Atomare, prozessuebergreifende Sperre (O_CREAT|O_EXCL) - schuetzt
    gegen einen zweiten gleichzeitigen Telegram-Tap (Repair ODER
    Maintenance) und gegen einen parallel von der Kommandozeile
    gestarteten `scripts/library_repair.py --apply`-Lauf."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()}|{now_iso()}")
    except FileExistsError as e:
        raise RepairAlreadyRunningError(
            "Es läuft bereits eine Reparatur - bitte warten, bis diese "
            "abgeschlossen ist."
        ) from e


def release_repair_lock() -> None:
    lock_path().unlink(missing_ok=True)


def is_repair_running() -> bool:
    return lock_path().exists()


# ─────────────────────────────────────────────────────────────────────────
# Journal-Fenster-Lesen (fuer Run-Korrelation)
# ─────────────────────────────────────────────────────────────────────────


def read_journal_window(offset_before: int, offset_after: int) -> list[dict]:
    path = journal_path()
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
# Repair-/Maintenance-Runs-Index (History, Statistik)
# ─────────────────────────────────────────────────────────────────────────


def write_json_atomic(path: Path, data: dict) -> None:
    """write-tmp + Path.replace() - dasselbe, im Projekt etablierte Muster
    (INV-02) wie services/library_health/findings.py::FindingsRegistry."""
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


def load_runs_index() -> dict:
    path = runs_index_path()
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


def append_run_record(record: dict) -> None:
    data = load_runs_index()
    data["runs"].append(record)
    write_json_atomic(runs_index_path(), data)


def load_repair_history(limit: Optional[int] = None) -> list[dict]:
    """Repair-/Maintenance-History (beide Flows, ein gemeinsamer Index) -
    neueste zuerst. `limit=None` liefert alle Eintraege."""
    runs = list(reversed(load_runs_index().get("runs", [])))
    return runs[:limit] if limit else runs


def compute_repair_statistics() -> dict:
    """Statistik ueber BEIDE Flows (Finding-Repair + Maintenance) -
    ausschliesslich aus der tatsaechlichen Run-History berechnet, keine
    hartkodierten Werte. Aggregiert weiterhin unveraendert ueber alle
    Runs (kein Split nach `kind` in dieser Phase - reine
    Datenverfuegbarkeit fuer kuenftige UI-Filterung, ARCH-031 B.6)."""
    runs = load_runs_index().get("runs", [])
    totals: Counter = Counter()
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
