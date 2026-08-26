# services/downloader/download/models.py
# -*- coding: utf-8 -*-
"""
Dataclasses & Type Aliases für die Download-Pipeline.

Diese Datei enthält ausschließlich reine Datenstrukturen (keine Logik).
`MetadataResult` wird NICHT dupliziert – es lebt weiterhin in
`services.metadata.models` und wird von den
Metadaten-Modulen verwendet. Hier geht es um die Download-Ebene
(Playlist-/Single-Ergebnisse, Fortschritts-Tracking).
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Type Aliases
# ═══════════════════════════════════════════════════════════════════════════════

# Signatur: (chat_id, current_step, total_steps, message, stage_name)
StatusCallback = Callable[[int, int, int, str, str], Awaitable[None]]

# Signatur: (current_value, total_value, label)
ProgressCallback = Callable[[float, float, str], None]


# ═══════════════════════════════════════════════════════════════════════════════
# DownloadResult – Ergebnis eines einzelnen Tracks (Single oder Playlist-Track)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DownloadResult:
    """
    Einheitliches Ergebnis-Objekt für einen verarbeiteten Track.

    Wird sowohl für Single-Downloads als auch für einzelne Tracks
    innerhalb einer Playlist verwendet. Entspricht dem bisherigen
    Dict-Format aus `_process_single_download()` /
    `_process_track_metadata()` / `_build_cache_result()`.
    """

    success: bool
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    year: Optional[int] = None

    # Genre-Informationen (Dict mit "primary"/"secondary" oder None)
    genres: Optional[Dict[str, Any]] = None
    genre_source: Optional[str] = None

    # Datei-Informationen
    library_path: Optional[str] = None
    # DUP-01 (docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
    # eigene Quell-URL des Tracks - fuer die Duplicate-Cache-Registrierung
    # von Playlist-Tracks benoetigt (klassen/download_handler.py).
    url: Optional[str] = None

    # Herkunfts-Informationen
    artist_source: Optional[str] = None
    title_cleaned: bool = False

    # Playlist-Kontext
    playlist_album: Optional[str] = None
    track_number: Optional[int] = None

    # Lyrics & Cover
    lyrics_available: bool = False
    lyrics_source: Optional[str] = None
    cover_embedded: bool = False

    # Status-Flags
    is_duplicate: bool = False
    from_cache: bool = False
    # P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 2): signalisiert
    # eine Zieldateinamens-Kollision in move_to_library() - konsumiert vom
    # Cleanup in klassen/download_handler.py::handle_youtube_links().
    renamed_due_to_conflict: bool = False

    # Fehler-Information (nur bei success=False relevant)
    error: Optional[str] = None

    # Interne Referenz auf den Processor (für Auto-Learning-Folgeschritte etc.)
    # Wird bewusst aus repr/Vergleich ausgeschlossen, da nicht serialisierbar.
    enhanced_processor_ref: Optional[Any] = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Kompatibilitäts-Helper: Erzeugt das alte Dict-Format,
        inkl. `_enhanced_processor_ref`, für Stellen, die noch
        nicht auf das Dataclass-Objekt umgestellt sind.
        """
        data = {
            "success": self.success,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "year": self.year,
            "genres": self.genres,
            "genre_source": self.genre_source,
            "library_path": self.library_path,
            "url": self.url,
            "artist_source": self.artist_source,
            "title_cleaned": self.title_cleaned,
            "playlist_album": self.playlist_album,
            "track_number": self.track_number,
            "lyrics_available": self.lyrics_available,
            "lyrics_source": self.lyrics_source,
            "cover_embedded": self.cover_embedded,
            "is_duplicate": self.is_duplicate,
            "from_cache": self.from_cache,
            "renamed_due_to_conflict": self.renamed_due_to_conflict,
            "error": self.error,
        }
        if self.enhanced_processor_ref is not None:
            data["_enhanced_processor_ref"] = self.enhanced_processor_ref
        return data


# ═══════════════════════════════════════════════════════════════════════════════
# PlaylistResult – Gesamtergebnis einer Playlist-Verarbeitung
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PlaylistResult:
    """
    Aggregiertes Ergebnis einer vollständigen Playlist-Pipeline.

    Entspricht dem Rückgabewert von `enhanced_download_with_retry()`
    für `type == "playlist"`, ergänzt um die Track-Liste aus
    `_process_playlist_download()`.
    """

    success: bool
    tracks: List[DownloadResult] = field(default_factory=list)

    # Playlist-Kontext (Ergebnisse aus Channel-Routing & Jahr-Bestimmung)
    album: Optional[str] = None
    dominant_artist: Optional[str] = None
    year: Optional[int] = None
    playlist_channel: Optional[str] = None

    # Aggregierte Zahlen
    total_tracks: int = 0
    successful_tracks: int = 0
    failed_tracks: int = 0
    cache_hits: int = 0

    error: Optional[str] = None

    # Interne Referenz auf den Processor
    enhanced_processor_ref: Optional[Any] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Leitet Zähl-Felder aus `tracks` ab, falls nicht explizit gesetzt."""
        if not self.total_tracks and self.tracks:
            self.total_tracks = len(self.tracks)
        if not self.successful_tracks and self.tracks:
            self.successful_tracks = sum(1 for t in self.tracks if t.success)
        if not self.failed_tracks and self.tracks:
            self.failed_tracks = sum(1 for t in self.tracks if not t.success)
