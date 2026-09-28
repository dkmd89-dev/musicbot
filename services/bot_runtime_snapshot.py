# services/bot_runtime_snapshot.py
# -*- coding: utf-8 -*-
"""
Bot-Laufzeit-Snapshot (Web-Paritäts-Entscheidung 1 = E1, Backlog 5,
2026-09-28).

Der Bot hält Laufzeitzustand, den das Control Center (eigener Prozess)
nicht sehen kann: Fehlerstatistik des ExceptionMonitor, letzte Fehler,
Performance/Recovery des EnhancedErrorHandler, Sitzungszähler des
DuplicateDetector. E1: Der Bot schreibt diesen Zustand periodisch
(SNAPSHOT_INTERVAL_SECONDS, zusätzlich beim Start und beim Herunterfahren)
atomar nach `<DATA_DIR>/bot_runtime_snapshot.json`; das CC liest nur.
Zurücksetzen bleibt Telegram-only (kein Schreibpfad CC -> Bot).
Vorlage: services/logger_admin.py::write/read_runtime_snapshot() (L5).

Datenschutz (CLAUDE.md §12, Nutzerentscheidung "streng"): Fehler-Einträge
enthalten ausschließlich id/timestamp/type/category/severity/module und
eine gekürzte, per services/logs/reader.py::redact_secrets() redigierte
Message - NIE den Telegram-Kontext (Nutzer, Chat, Nachrichtentexte,
Callback-Daten), NIE Stacktraces. sanitize_exception_record() ist die
einzige Stelle, über die Fehler-Einträge in den Snapshot gelangen.

Ehrlichkeit: read_bot_runtime_snapshot() rekonstruiert nichts -
fehlende/korrupte Datei wird als solche gemeldet, ein veralteter Stand
(Bot schreibt nicht mehr) als "stale".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from services.logger_admin import atomic_write_json
from services.logs.reader import redact_secrets

SNAPSHOT_FILE_NAME = "bot_runtime_snapshot.json"
SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_INTERVAL_SECONDS = 60
STALE_AFTER_SECONDS = 3 * SNAPSHOT_INTERVAL_SECONDS
MAX_RECENT_ERRORS = 50
MAX_MESSAGE_LENGTH = 200

_ALLOWED_ERROR_FIELDS = ("id", "timestamp", "type", "category", "severity")


def snapshot_path(config: Any) -> Path:
    """Fester, serverseitig aufgelöster Pfad - kein Nutzer-Input."""
    return Path(config.DATA_DIR) / SNAPSHOT_FILE_NAME


def sanitize_exception_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Reduziert einen ExceptionMonitor-Eintrag auf die erlaubten Felder.
    `module` stammt aus record["context"]["module"] - sonst wird vom
    Kontext nichts übernommen."""
    sanitized: Dict[str, Any] = {k: record.get(k) for k in _ALLOWED_ERROR_FIELDS}
    context = record.get("context")
    module = context.get("module") if isinstance(context, Mapping) else None
    sanitized["module"] = str(module) if module is not None else None
    message = redact_secrets(str(record.get("message") or ""))
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH] + "…"
    sanitized["message"] = message
    return sanitized


def write_bot_runtime_snapshot(
    config: Any,
    sections: Mapping[str, Any],
    *,
    bot_started_at: str,
) -> Optional[Path]:
    """Schreibt den Snapshot atomar. Fehler werden NICHT propagiert
    (Observability, nicht Lifecycle-kritisch) - Rückgabe None bei Fehler."""
    path = snapshot_path(config)
    payload: Dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bot_started_at": bot_started_at,
        "pid": os.getpid(),
        "interval_seconds": SNAPSHOT_INTERVAL_SECONDS,
        "sections": dict(sections),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, json.loads(json.dumps(payload, default=str)))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Bot-Runtime-Snapshot konnte nicht geschrieben werden: {e!r}")
        return None
    return path


def read_bot_runtime_snapshot(config: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rückgabe: {"status": "available"|"stale"|"missing"|"corrupt",
    "snapshot": {...} (bei available/stale), "age_seconds": float|None,
    "message": str|None}."""
    path = snapshot_path(config)
    if not path.exists():
        return {
            "status": "missing",
            "snapshot": None,
            "age_seconds": None,
            "message": "Noch kein Bot-Snapshot vorhanden (Bot seit Einführung nicht gestartet oder Schreiben fehlgeschlagen).",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(data["generated_at"])
        if not isinstance(data.get("sections"), dict):
            raise ValueError("sections fehlt")
    except Exception as e:  # noqa: BLE001
        return {
            "status": "corrupt",
            "snapshot": None,
            "age_seconds": None,
            "message": f"Bot-Snapshot nicht lesbar: {type(e).__name__}",
        }
    now = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    age = max(0.0, (now - generated_at).total_seconds())
    stale = age > STALE_AFTER_SECONDS
    return {
        "status": "stale" if stale else "available",
        "snapshot": data,
        "age_seconds": age,
        "message": (
            "Bot schreibt keinen Snapshot mehr (gestoppt oder abgestürzt) - letzter bekannter Stand."
            if stale
            else None
        ),
    }
