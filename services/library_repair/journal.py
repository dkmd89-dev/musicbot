# services/library_repair/journal.py
# -*- coding: utf-8 -*-
"""
Repair Journal + Rollback-Info (Prompt Abschnitt 17).

Append-Only JSONL: ein Objekt pro tatsaechlich (oder im Dry-Run
hypothetisch) geaenderter Datei. Bestehende Eintraege werden nie
veraendert. Enthaelt alles fuer eine manuelle Wiederherstellung:
Datei, alte/neue Werte, Aktion, Zeit, Status, Fehler, Backup-Pfad,
SHA-256 vorher/nachher.

Kein neues Backup-Framework (Prompt Abschnitt 17): die eigentliche
Sicherung ist eine `.repairbak`-Sibling-Kopie — dasselbe Muster wie
scripts/normalize_test_library_loudness.py (`.{name}.lufs_backup`).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class JournalEntry:
    timestamp: str
    file: str
    issue_code: str
    action: str
    status: str                       # SUCCESS | FAILED | SKIPPED | DRY_RUN
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    sha256_before: Optional[str] = None
    sha256_after: Optional[str] = None
    audio_sha256_before: Optional[str] = None
    audio_sha256_after: Optional[str] = None
    backup_path: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = False


class RepairJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[JournalEntry] = []

    def record(self, entry: JournalEntry) -> None:
        self.entries.append(entry)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def flush(self) -> None:
        """Alle bisher gesammelten Eintraege append-only anhaengen."""
        if not self.entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
        self.entries = []

    def summary(self) -> dict:
        from collections import Counter

        c = Counter(e.status for e in self.entries)
        return {"total": len(self.entries), **c}
