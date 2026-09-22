# control_center/schemas/health.py
# -*- coding: utf-8 -*-
"""
Response-Schema fuer GET /api/v1/library/health.

Bewusst kein 1:1-Durchreichen des internen Report-Dicts aus
services/library_health/report.py::build_report_dict() (Master-Prompt
Abschnitt 16/31, Regel 9: interne Implementierungsdetails werden nicht
automatisch Teil des API-Contracts). Die schweren, pro-Datei aufgeloesten
Felder ("issues", "files", "artists", "albums") sind bewusst NICHT Teil
dieser Response — sie gehoeren zum separaten Findings-Endpunkt (siehe
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md Abschnitt 1), der
noch nicht Teil dieses Schritts ist. Das Dashboard braucht fuer die
Health-Kacheln nur Score/Status/Statistik-Aggregate.

"library.root" (lokaler Filesystem-Pfad) wird ebenfalls bewusst
weggelassen — kein Mehrwert fuers Dashboard, aber unnoetige Preisgabe der
lokalen Verzeichnisstruktur an jeden Client dieser (im MVP noch
unauthentifizierten) Route.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScanInfo(BaseModel):
    started_at: str
    completed_at: str
    duration_seconds: float


class LibraryInfo(BaseModel):
    files: int
    artists: int
    albums: int


class HealthScoreInfo(BaseModel):
    score: float | None
    status: str


class LibraryHealthResponse(BaseModel):
    schema_version: str
    scanner_version: str
    scan: ScanInfo
    library: LibraryInfo
    health: HealthScoreInfo
    # Bereits stabile, versionierte Aggregat-Struktur aus
    # services/library_health/report.py::build_statistics() — kein
    # Roh-Dataclass-Durchreichen, aber fuer den MVP als dünnes Mapping
    # unveraendert uebernommen statt jedes Einzelfeld erneut zu duplizieren.
    statistics: dict[str, Any] = Field(default_factory=dict)


class CachedLibraryHealthResponse(LibraryHealthResponse):
    """Antwort von GET /api/v1/library/health/cached (Overview-Dashboard,
    CONTROL_CENTER_OVERVIEW_V2.md Abschnitt 5) — identische Felder wie
    LibraryHealthResponse, plus `stale`. Bewusst eigene Subklasse statt
    Erweiterung von LibraryHealthResponse selbst: GET /health (Health-Seite,
    frischer Scan) bleibt dadurch byte-identisch zu vorher, insbesondere
    faellt tests/test_control_center_health_api.py::
    test_get_library_health_response_omits_internal_details() (strikte
    `set(body.keys())`-Pruefung) nicht durch ein neues, dort ungewolltes
    Feld aus."""

    stale: bool


def report_to_health_response(report: dict) -> LibraryHealthResponse:
    """Mappt das volle run_scan()-Report-Dict auf die duenne API-Response.

    Reines Mapping, keine Scan-/Fachlogik — identisches Prinzip wie
    services/library_health/report.py::render_text()/render_summary_markdown().
    Felder wie "library.root" (lokaler Pfad) oder "health.weights" werden
    bewusst per explizitem Feldzugriff ausgelassen statt per **dict-Splat
    (das wuerde sie nur durch Pydantics Default-Verhalten "unbekannte
    Felder ignorieren" verschwinden lassen — hier ist der Ausschluss
    absichtlich sichtbar im Code, nicht implizit)."""
    scan = report["scan"]
    library = report["library"]
    health = report["health"]
    return LibraryHealthResponse(
        schema_version=report["schema_version"],
        scanner_version=report["scanner_version"],
        scan=ScanInfo(
            started_at=scan["started_at"],
            completed_at=scan["completed_at"],
            duration_seconds=scan["duration_seconds"],
        ),
        library=LibraryInfo(
            files=library["files"],
            artists=library["artists"],
            albums=library["albums"],
        ),
        health=HealthScoreInfo(
            score=health.get("score"),
            status=health.get("status", "UNSCORED"),
        ),
        statistics=report["statistics"],
    )


def report_to_cached_health_response(report: dict, *, stale: bool) -> CachedLibraryHealthResponse:
    """Wie report_to_health_response(), zusaetzlich mit `stale`-Flag aus
    _library_scan.py::load_cached_report(). Baut bewusst auf der
    bestehenden Mapping-Funktion auf (kein zweites Feld-fuer-Feld-Mapping,
    Master-Prompt Regel 7/CLAUDE.md Abschnitt 10 „keine unkontrollierten
    Bulk-Aenderungen")."""
    base = report_to_health_response(report)
    return CachedLibraryHealthResponse(**base.model_dump(), stale=stale)


class ScoreHistoryEntry(BaseModel):
    """Ein Eintrag aus services/library_health/score_history.py::
    read_score_history() — identische Feldnamen wie dort geschrieben
    (append_score_history()), reines Passthrough-Schema ohne Umbenennung."""

    timestamp: str | None
    score: float | None
    status: str | None
    total_issues: int | None
    total_files: int | None


class ScoreHistoryResponse(BaseModel):
    entries: list[ScoreHistoryEntry]


def score_history_to_response(entries: list[dict]) -> ScoreHistoryResponse:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    report_to_health_response(). Fehlt ein Feld in einem aelteren Eintrag
    (Schema-Drift ueber die Zeit), liefert `.get()` `None` statt eines
    KeyError — dieselbe defensive Haltung wie read_score_history() selbst
    gegenueber nicht parsebaren Zeilen."""
    return ScoreHistoryResponse(
        entries=[
            ScoreHistoryEntry(
                timestamp=e.get("timestamp"),
                score=e.get("score"),
                status=e.get("status"),
                total_issues=e.get("total_issues"),
                total_files=e.get("total_files"),
            )
            for e in entries
        ]
    )
