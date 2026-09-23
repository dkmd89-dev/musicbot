# -*- coding: utf-8 -*-
"""
CC-LOGGER-L2 — Response-Schemas für /api/v1/admin/logger/*.

Dünnes Mapping über services/logger_admin.py + services/logs/reader.py
hinweg — identisches Prinzip wie schemas/logs.py. Kein 1:1-Durchreichen
interner Dataclasses.

**Bewusst NICHT enthalten** (L2-Scope, Audit-Doc
docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md):
- Keine "current_level"-Felder (Class B, prozesslokal, nicht
  autoritativ aus dem CC-Prozess).
- Keine "enabled"-Felder für Module/Handler (Class B, ebenso).
- Kein `module_logger_config.json`-Content (L1-Analyse: nicht
  autoritativ für Runtime — siehe Audit-Doc).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.logger_admin import LogFileMeta, LogFileStats, human_size_str
from services.logs.reader import LogEntry

from .logs import LogEntrySchema, _entry_to_schema


class LogFileSchema(BaseModel):
    name: str
    size_bytes: int
    size_human: str
    modified_at: str  # ISO-8601


class LogFileListResponse(BaseModel):
    files: List[LogFileSchema]
    total: int


class LogFileStatsResponse(BaseModel):
    """Aggregat über alle Logdateien — ausschließlich aus
    Dateisystem-Metadaten.

    `oldest_file`/`oldest_age_days` beziehen sich auf die **älteste
    Datei nach Dateisystem-mtime**, nicht auf „die älteste Logmeldung".
    Die Logzeilen selbst tragen im Root-Format kein Datum, eine Aussage
    über den ältesten Log-Eintrag wäre nicht verlässlich ableitbar —
    die Grenze ist bewusst die Datei-Ebene."""

    total_files: int
    total_size_bytes: int
    total_size_human: str
    largest_file: Optional[str]
    largest_size_bytes: int
    largest_size_human: str
    oldest_file: Optional[str]
    oldest_age_days: int


class LogFileDetailResponse(BaseModel):
    name: str
    size_bytes: int
    size_human: str
    modified_at: str
    source: str
    available_sources: List[str]
    total_matched: int
    limit: int
    entries: List[LogEntrySchema]


def _file_meta_to_schema(meta: LogFileMeta) -> LogFileSchema:
    return LogFileSchema(
        name=meta.name,
        size_bytes=meta.size_bytes,
        size_human=human_size_str(meta.size_bytes),
        modified_at=meta.modified_at.isoformat(),
    )


def log_file_list_to_response(files: List[LogFileMeta]) -> LogFileListResponse:
    return LogFileListResponse(
        files=[_file_meta_to_schema(f) for f in files],
        total=len(files),
    )


def log_file_stats_to_response(stats: LogFileStats) -> LogFileStatsResponse:
    return LogFileStatsResponse(
        total_files=stats.total_files,
        total_size_bytes=stats.total_size_bytes,
        total_size_human=human_size_str(stats.total_size_bytes),
        largest_file=stats.largest_file,
        largest_size_bytes=stats.largest_size_bytes,
        largest_size_human=human_size_str(stats.largest_size_bytes),
        oldest_file=stats.oldest_file,
        oldest_age_days=stats.oldest_age_days,
    )


def log_file_detail_to_response(result: dict) -> LogFileDetailResponse:
    """`result` ist das unveränderte dict aus
    services/logs/reader.py::read_logs() (identische Struktur wie
    schemas.logs.LogsResponse). `name`/`size_bytes`/`modified_at` kommen
    zusätzlich aus einem stat()-Aufruf im Router, damit der Response
    Datei-Metadaten und Inhalt gemeinsam trägt (ein Roundtrip statt
    zwei)."""
    entries = [e for e in result.get("entries", []) if isinstance(e, LogEntry)]
    return LogFileDetailResponse(
        # name/size/modified werden vom Router injiziert (siehe dort).
        name=result.get("_file_name", ""),
        size_bytes=result.get("_file_size_bytes", 0),
        size_human=human_size_str(result.get("_file_size_bytes", 0)),
        modified_at=result.get("_file_modified_at", ""),
        source=result.get("source", ""),
        available_sources=result.get("available_sources", []),
        total_matched=result.get("total_matched", 0),
        limit=result.get("limit", 0),
        entries=[_entry_to_schema(e) for e in entries],
    )


# =====================================================================
# CC-LOGGER-L4 Stufe 1 — Persistente Logger-Konfiguration
# =====================================================================
#
# Wichtig: alle Felder beschreiben ausschliesslich die *persistente*
# Konfiguration (data/module_logger_config.json). Sie sind keine Aussage
# ueber den laufenden Bot-Prozess. Aenderungen werden erst beim naechsten
# Bot-Start wirksam — das ist im Response-Text explizit benannt.


class ModuleConfigSchema(BaseModel):
    """Ein einzelner Modul-Eintrag aus der persistenten Konfiguration.

    Feldnamen identisch zur bestehenden JSON (enabled, level,
    file_handler, console_handler, custom_format) — keine Umbenennung,
    damit die Datei kompatibel bleibt."""

    enabled: bool = True
    level: str = "INFO"
    file_handler: bool = True
    console_handler: bool = True
    custom_format: Optional[str] = None


class LoggerConfigResponse(BaseModel):
    """GET /api/v1/admin/logger/config — vollstaendige persistente
    Logger-Konfiguration."""

    modules: Dict[str, ModuleConfigSchema]
    total: int
    """Anzahl Module in der Konfiguration."""


class LoggerConfigPatchRequest(BaseModel):
    """PATCH-Body fuer die persistente Logger-Konfiguration.

    Struktur: `{"modules": {"<module_name>": {"level": "DEBUG"}, ...}}`.

    Nur der Top-Level-Key `modules` ist erlaubt (extra="forbid"). Die
    Feinvalidierung der inneren Struktur (unbekannte Module, unbekannte
    Felder, ungueltige Level-Werte) erfolgt bewusst NICHT in Pydantic,
    sondern im Application Layer — dort koennen wir stabile Fehler-Codes
    (LOGGER_CONFIG_UNKNOWN_MODULE, LOGGER_CONFIG_INVALID_LEVEL, ...)
    liefern, die der Router auf HTTP-Codes mappt.
    """

    model_config = ConfigDict(extra="forbid")

    modules: Dict[str, Dict[str, Any]] = Field(
        ...,
        description=(
            "Dict von Modulname -> Partial-Update. Nur Felder aus "
            "{enabled, level, file_handler, console_handler} sind "
            "erlaubt. Unbekannte Module werden abgelehnt."
        ),
    )


class LoggerConfigPatchResponse(BaseModel):
    """PATCH /api/v1/admin/logger/config — Bestaetigung.

    Der `message`-Text macht ausdruecklich klar, dass die Aenderung erst
    beim naechsten Bot-Start wirksam wird — die API behauptet bewusst
    NICHT die Anwendung im laufenden Prozess (L3-Entscheidung, siehe
    docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md).
    """

    success: bool
    message: str
    modules_updated: List[str]
    """Namen der Module, deren Konfiguration tatsaechlich veraendert wurde."""

    total: int
    """Anzahl Module in der Konfiguration nach dem Patch."""


def logger_config_to_response(data: Dict[str, Any]) -> LoggerConfigResponse:
    """Mappt das rohe dict aus services/logger_admin.py auf das
    Response-Schema. Fehlende Felder in einem Modul-Eintrag werden durch
    ModuleConfigSchema-Defaults ergaenzt."""
    modules: Dict[str, ModuleConfigSchema] = {}
    for name, fields in data.items():
        if not isinstance(fields, dict):
            # Sollte durch App-Layer-Validierung nicht passieren, aber
            # defensiv: fehlerhafte Eintraege mit Defaults ueberspringen.
            continue
        modules[name] = ModuleConfigSchema(
            enabled=fields.get("enabled", True),
            level=fields.get("level", "INFO"),
            file_handler=fields.get("file_handler", True),
            console_handler=fields.get("console_handler", True),
            custom_format=fields.get("custom_format"),
        )
    return LoggerConfigResponse(modules=modules, total=len(modules))


# =====================================================================
# CC-LOGGER-L5.1 — Runtime-Status (Snapshot)
# =====================================================================
#
# Beschreibt den zuletzt geschriebenen Runtime-Snapshot
# (data/logger_runtime_snapshot.json). Explizite Semantik:
#
#     "state after last successful bot startup"
#
# Kein Live-State. Kein Fake-State bei fehlendem/korruptem Snapshot.


class RuntimeSnapshotSchema(BaseModel):
    """Der tatsaechlich gelesene Snapshot-Inhalt.

    Wird nur bei `status="available"` befuellt."""

    model_config = ConfigDict(extra="allow")
    # extra="allow": der Snapshot ist ein vom Bot geschriebenes,
    # versioniertes Dokument. Neue Felder in einer kuenftigen
    # schema_version duerfen den Read-Client nicht brechen.


class LoggerRuntimeStatusResponse(BaseModel):
    """GET /api/v1/admin/logger/runtime-status.

    `status`:
      - "available" — Snapshot vorhanden und vollstaendig, `snapshot`
        befuellt.
      - "missing"   — kein Snapshot vorhanden (Bot seit Einfuehrung
        nicht erfolgreich gestartet, oder Write ist fehlgeschlagen).
      - "corrupt"   — Snapshot vorhanden, aber unlesbar/unvollstaendig.

    `state_semantics` ist konstant und drueckt aus, dass der Snapshot
    **kein Live-State** ist — er beschreibt den Zustand nach dem
    letzten erfolgreichen Bot-Start."""

    status: str
    state_semantics: str = "state_after_last_successful_bot_start"
    snapshot: Optional[RuntimeSnapshotSchema] = None
    message: Optional[str] = None


def runtime_snapshot_result_to_response(result: dict) -> LoggerRuntimeStatusResponse:
    """Mappt das dict aus services/logger_admin.py::read_runtime_snapshot()
    auf das Response-Schema. Kein Fake-State: bei `missing`/`corrupt`
    ist `snapshot` None."""
    status = result.get("status", "missing")
    if status == "available":
        return LoggerRuntimeStatusResponse(
            status="available",
            snapshot=RuntimeSnapshotSchema(**result["snapshot"]),
        )
    return LoggerRuntimeStatusResponse(
        status=status,
        message=result.get("message"),
    )


# =====================================================================
# CC-LOGGER-L5.3 — Apply/Restart
# =====================================================================
#
# Semantik: POST /logger/apply ist ein **administrativer Bot-Neustart**
# mit Preflight, nicht eine "Logger live anwenden"-Aktion. Der
# Preflight-Status wird strukturiert ausgewiesen, damit Clients nicht
# versehentlich "unverified" als "clear" lesen.


class PreflightStatusSchema(BaseModel):
    """Strukturierter Preflight-Status (siehe
    services/logger_admin.py::evaluate_apply_preflight).

    - `status`: "clear" | "blocked" | "unverified"
    - `checked`:  welche Quellen tatsaechlich geprueft wurden
    - `active`:   erkannte aktive Kategorien (nur `repair` bekannt)
    - `unverified`: nicht pruefbare Kategorien (z.B. downloads, backups)
    - `message`:  Klartext-Erklaerung
    """

    status: str
    checked: Dict[str, bool]
    active: Dict[str, bool]
    unverified: List[str]
    message: str


class LoggerApplyResponse(BaseModel):
    """Erfolgs-Response von POST /api/v1/admin/logger/apply.

    `status="applied"` bedeutet: Preflight freigegeben, Config validiert,
    Restart wurde geplant. Der eigentliche Restart laeuft verzoegert
    (Response-before-restart) und kann NICHT synchron bestaetigt werden
    — die bestehende BotRestartTrigger-Semantik schluckt Fehler intern,
    siehe L5-Audit 'Bekannte Einschraenkungen'."""

    status: str  # "applied"
    message: str
    preflight: PreflightStatusSchema
