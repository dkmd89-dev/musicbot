# services/library_health/models.py
# -*- coding: utf-8 -*-
"""
Library Health Scanner — Domain-Modelle (Phase 1).

Reine Datencontainer + Enums, keine Fachlogik, kein Dateisystem-/Tag-Zugriff.
Analog zu services/duplicate/classification.py (dort ebenfalls: Modelle +
pure Functions, die I/O-Schicht liegt getrennt im scripts/-Wrapper bzw. hier
in tag_reader.py/discovery.py).

Der Scanner ist ausschliesslich diagnostisch (Prompt Abschnitt 2/37) — es
gibt hier bewusst KEINE "fix"/"repair"/"resolution"-Felder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# Stabile, versionierte Schema-/Scanner-Kennung (Prompt Abschnitt 24).
# schema_version aendert sich NUR bei einer inkompatiblen Report-Struktur-
# aenderung, scanner_version bei einer inhaltlichen Analyse-/Regel-aenderung.
SCHEMA_VERSION = "1.0"
SCANNER_VERSION = "1.0"


class AnalysisState(str, Enum):
    """Prompt Abschnitt 9: strikt getrennt. 'Nicht analysierbar != nicht
    vorhanden.'"""

    PRESENT = "PRESENT"
    MISSING = "MISSING"
    INVALID = "INVALID"
    PARTIAL = "PARTIAL"
    NOT_ANALYZABLE = "NOT_ANALYZABLE"


class Severity(str, Enum):
    """Prompt Abschnitt 21. INFO ist KEIN Qualitaetsdefekt (Abschnitt 22/23)."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# Rang fuer deterministische Sortierung (hoeher = schwerer).
_SEVERITY_RANK = {
    Severity.CRITICAL: 3,
    Severity.ERROR: 2,
    Severity.WARNING: 1,
    Severity.INFO: 0,
}


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


class Scope(str, Enum):
    FILE = "file"
    ALBUM = "album"
    ARTIST = "artist"
    LIBRARY = "library"


class LibrarySection(str, Enum):
    """Welcher Teil der Library-Konvention (utils/filenamefixer.py::
    build_final_path()) diese Datei zugeordnet ist."""

    MUSIC = "music"          # LIBRARY_DIR/<Artist>/(Singles|<Jahr - Album>)/...
    COMPILATIONS = "compilations"
    PLAYLIST = "playlist"
    UNKNOWN = "unknown"      # ausserhalb jeder bekannten Struktur


@dataclass
class Issue:
    """Ein einzelner diagnostischer Befund (Prompt Abschnitt 25).

    Nach der Konstruktion nicht mehr mutiert (per Konvention, kein
    frozen=True — der Aufbau in file_analysis.py setzt Felder schrittweise).
    """

    code: str
    severity: Severity
    scope: Scope
    message: str
    path: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    details: dict = field(default_factory=dict)
    confidence: Optional[str] = None
    related_files: list[str] = field(default_factory=list)

    def sort_key(self) -> tuple:
        """Deterministische Reihenfolge (Prompt Abschnitt 35): schwerste
        zuerst, dann stabil nach Code/Pfad/Message."""
        return (
            -severity_rank(self.severity),
            self.code,
            self.path or "",
            self.artist or "",
            self.album or "",
            self.message,
        )

    def to_dict(self) -> dict:
        return {
            "issue_code": self.code,
            "severity": self.severity.value,
            "scope": self.scope.value,
            "path": self.path,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "message": self.message,
            "details": self.details,
            "confidence": self.confidence,
            "related_files": self.related_files,
        }


@dataclass
class FileRecord:
    """Ergebnis der Discovery-Stufe (Prompt Abschnitt 7). Reine Pfad-/
    Struktur-Fakten, noch keine Tag-Analyse."""

    absolute_path: Path
    relative_path: str
    filename: str
    filename_stem: str
    extension: str
    file_size: int
    parent_directory: str
    artist_directory: Optional[str]
    album_directory: Optional[str]
    is_singles: bool
    library_section: LibrarySection
    # services/duplicate/classification.Classification-Wert (SINGLE/
    # ALBUM_LIKE/AMBIGUOUS) — als String gehalten, um models.py frei von
    # einem Import auf die duplicate-Domain zu halten.
    path_classification: str

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "filename": self.filename,
            "extension": self.extension,
            "file_size": self.file_size,
            "artist_directory": self.artist_directory,
            "album_directory": self.album_directory,
            "is_singles": self.is_singles,
            "library_section": self.library_section.value,
            "path_classification": self.path_classification,
        }


@dataclass
class FileHealth:
    """Aggregiertes Per-Datei-Analyseergebnis (file_analysis.py)."""

    record: FileRecord
    states: dict = field(default_factory=dict)   # {"metadata": AnalysisState, ...}
    issues: list[Issue] = field(default_factory=list)
    # Rohe, bereits gelesene Kernwerte — nur fuer den Report / die
    # Group-Analyse (PR2), nicht fuer eine Entscheidung.
    artist: Optional[str] = None
    album_artist: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    year: Optional[str] = None
    genre: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    mb_recording_id: Optional[str] = None
    mb_release_id: Optional[str] = None
    isrc: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            **self.record.to_dict(),
            "states": {k: v.value for k, v in self.states.items()},
            "artist": self.artist,
            "album_artist": self.album_artist,
            "title": self.title,
            "album": self.album,
            "year": self.year,
            "genre": self.genre,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "mb_recording_id": self.mb_recording_id,
            "mb_release_id": self.mb_release_id,
            "isrc": self.isrc,
            "issue_codes": sorted({i.code for i in self.issues}),
        }
