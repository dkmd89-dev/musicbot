# services/library_health/score_history.py
# -*- coding: utf-8 -*-
"""
Health-Score-Verlauf — Append-only Zeitreihe der Health-Scores über
mehrere Scans hinweg (Chat-Charakterisierung 2026-09-15).

Bisher wurde bei jedem Scan ausschließlich `library_health_report.json`
überschrieben (reiner Snapshot, keine Historie) - dieses Modul ergänzt
eine fünfte, rein additive Ausgabedatei
(`library_health_score_history.jsonl`) neben den bestehenden vier
(JSON/Text/Markdown-Summary/Findings-Registry).

Bewusst NICHT von services/library_health/scanner.py importiert - der
reine, lesende Scan-Kern bleibt frei von jeglichem Schreibzugriff (siehe
tests/test_library_health_readonly_safety.py::
test_scanner_import_graph_has_no_writer_modules()). Stattdessen rufen
die AUFRUFER von run_scan() diese Funktion auf, nachdem der Report
bereits geschrieben wurde:
  - scripts/library_health_check.py (CLI, jeder direkte Aufruf)
  - services/library_repair/doctor_runner.py::run_health_scan() startet
    genau dieses Script als Subprozess (kein zweiter Aufrufer nötig) -
    jeder Telegram-Scan (MusicBot Doctor, Reparaturvorschläge,
    Verification-Rescans nach einer Reparatur) landet dadurch
    automatisch mit im Verlauf.

Append-only per einfachem `open(path, "a")` - identisches, bereits
etabliertes Muster wie services/library_repair/journal.py (RepairJournal.
flush()), NICHT das schwerere Write-tmp+replace()-Muster aus
_write_atomic() (dort für vollständige Neuschreibungen einer Datei
gedacht, hier für einen einzelnen angehängten JSON-Objekt-pro-Zeile-
Eintrag unnötig). Ein Crash mitten im Schreiben kann höchstens die
letzte Zeile beschädigen - read_score_history() überspringt nicht
parsebare Zeilen defensiv, identisches Prinzip wie
run_tracking.py::read_journal_window().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import Config

SCORE_HISTORY_FILENAME = "library_health_score_history.jsonl"


def score_history_path() -> Path:
    return Path(Config.DATA_DIR) / SCORE_HISTORY_FILENAME


def append_score_history(report: Dict[str, Any], *, path: Optional[Path] = None) -> None:
    """Hängt einen Verlaufs-Eintrag für einen abgeschlossenen Scan an.

    Nimmt den bereits fertigen Report-Dict entgegen (dieselbe Struktur
    wie von scanner.py::run_scan() zurückgegeben bzw.
    library_health_report.json) - liest KEINE eigene Datei, führt KEINEN
    eigenen Scan durch. `report.get("health", {}).get("score")` kann
    `None` sein (z. B. `status: UNSCORED` bei 0 Dateien) - wird dann
    unverändert als `None` gespeichert, kein künstlicher 0-Wert."""
    entry = {
        "timestamp": report.get("scan", {}).get("completed_at"),
        "score": report.get("health", {}).get("score"),
        "status": report.get("health", {}).get("status"),
        "total_issues": len(report.get("issues") or []),
        "total_files": report.get("library", {}).get("files"),
    }
    p = path or score_history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_score_history(
    *, path: Optional[Path] = None, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Liest die Score-Historie, chronologisch aufsteigend (älteste
    zuerst - Schreibreihenfolge = Append-Reihenfolge). `limit` liefert
    nur die letzten `limit` Einträge (neueste Scans). Fehlerhafte/nicht
    parsebare Zeilen werden übersprungen statt die gesamte Historie
    unlesbar zu machen."""
    p = path or score_history_path()
    if not p.exists():
        return []

    entries: List[Dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if limit is not None and limit >= 0:
        entries = entries[-limit:]
    return entries
