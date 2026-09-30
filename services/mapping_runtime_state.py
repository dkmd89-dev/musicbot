# services/mapping_runtime_state.py
# -*- coding: utf-8 -*-
"""
Runtime-Status der Mapping-Dateien: "gespeichert" vs. "vom Bot angewendet".

Der Bot lädt die Mapping-Dateien beim Start und hat keinen Reload-Pfad. Damit
das Control Center ehrlich zeigen kann, ob eine gespeicherte Aenderung schon
wirkt, meldet der Bot im periodischen Laufzeit-Snapshot
(services/bot_runtime_snapshot.py) die beim Start gesehenen SHA-256 der
bearbeitbaren Mapping-Dateien; das Control Center vergleicht sie mit dem
aktuellen Datei-Stand. Es wird nichts geraten: fehlt der Snapshot oder der
Abschnitt, ist der Zustand "unknown".

Datenschutz: der Snapshot enthaelt nur Dateinamen aus der Allowlist und Hashes,
keine Pfade und keine Inhalte.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from services.mapping_admin import mapping_file_names

SECTION_NAME = "mapping_files"
_SHORT = 12

STATE_APPLIED = "applied"
STATE_PENDING = "pending_restart"
STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"

_SPECIAL_NOTE = (
    "Teile der Prüfung lesen special_channel.yaml je Aufruf neu und wirken ohne Neustart; "
    "der Bot-Start ist der einzige garantierte Zeitpunkt."
)


@dataclass(frozen=True)
class MappingRuntimeStatus:
    mapping_id: str
    filename: str
    state: str
    message: str
    saved_sha256: Optional[str] = None
    loaded_sha256: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class RuntimeEvaluation:
    snapshot_status: str
    bot_running: bool
    bot_started_at: Optional[str]
    age_seconds: Optional[float]
    statuses: List[MappingRuntimeStatus] = field(default_factory=list)


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def hash_mapping_files(mapping_dir: Path) -> Dict[str, Optional[str]]:
    """Dateiname -> SHA-256 (None, wenn die Datei fehlt) fuer die Allowlist."""
    return {filename: _sha256(Path(mapping_dir) / filename) for filename in mapping_file_names().values()}


def build_snapshot_section(hashes: Mapping[str, Optional[str]], hashed_at: str) -> Dict[str, Any]:
    """Abschnitt fuer den Bot-Snapshot (nur Dateinamen und Hashes)."""
    return {"hashes": dict(hashes), "hashed_at": hashed_at}


def _short(value: Optional[str]) -> Optional[str]:
    return value[:_SHORT] if value else None


def _unknown(mapping_id: str, filename: str, message: str, saved: Optional[str]) -> MappingRuntimeStatus:
    return MappingRuntimeStatus(
        mapping_id, filename, STATE_UNKNOWN, message, _short(saved), None,
        _SPECIAL_NOTE if mapping_id == "special-channels" else None,
    )


def evaluate(mapping_dir: Path, snapshot_result: Mapping[str, Any]) -> RuntimeEvaluation:
    """Vergleicht den aktuellen Datei-Stand mit dem vom Bot gemeldeten Ladestand.

    `snapshot_result` ist die Rueckgabe von
    services.bot_runtime_snapshot.read_bot_runtime_snapshot()."""
    status = str(snapshot_result.get("status"))
    snapshot = snapshot_result.get("snapshot") or {}
    section = ((snapshot.get("sections") or {}).get(SECTION_NAME)) if status in ("available", "stale") else None
    loaded: Optional[Mapping[str, Optional[str]]] = (section or {}).get("hashes") if isinstance(section, Mapping) else None
    bot_running = status == "available"
    current = hash_mapping_files(mapping_dir)

    statuses: List[MappingRuntimeStatus] = []
    for mapping_id, filename in mapping_file_names().items():
        saved = current[filename]
        if status in ("missing", "corrupt") or not status:
            statuses.append(_unknown(mapping_id, filename, "Kein lesbarer Bot-Snapshot — der Runtime-Stand ist unbekannt.", saved))
            continue
        if loaded is None:
            statuses.append(_unknown(
                mapping_id, filename,
                "Der laufende Bot meldet den Mapping-Stand noch nicht — nach dem nächsten Neustart verfügbar.", saved,
            ))
            continue
        if saved is None:
            statuses.append(MappingRuntimeStatus(mapping_id, filename, STATE_UNAVAILABLE, "Die Datei fehlt.", None, _short(loaded.get(filename))))
            continue
        loaded_hash = loaded.get(filename)
        note = _SPECIAL_NOTE if mapping_id == "special-channels" else None
        if loaded_hash == saved:
            state, message = STATE_APPLIED, "Die Runtime nutzt den gespeicherten Stand."
        else:
            state = STATE_PENDING
            message = "Gespeichert, aber noch nicht angewendet: der Bot lädt die Datei beim Start (Neustart nötig)."
        if not bot_running:
            message += " Der Bot läuft nicht oder schreibt keinen Snapshot mehr — Stand vom letzten Lauf."
        statuses.append(MappingRuntimeStatus(mapping_id, filename, state, message, _short(saved), _short(loaded_hash), note))

    return RuntimeEvaluation(
        snapshot_status=status, bot_running=bot_running,
        bot_started_at=snapshot.get("bot_started_at"), age_seconds=snapshot_result.get("age_seconds"),
        statuses=statuses,
    )
