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

from typing import List, Optional

from pydantic import BaseModel

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
