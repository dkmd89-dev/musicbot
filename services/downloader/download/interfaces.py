# services/downloader/download/interfaces.py
# -*- coding: utf-8 -*-
"""
Abstrakte Schnittstellen (Protocols) für die Download-Pipeline.

Diese Protocols beschreiben die bestehenden Verträge zwischen
`EnhancedDownloadProcessor`, `MetadataCache` und
`EnhancedMetadataProcessor`, ohne diese Klassen selbst zu verändern.
Sie ermöglichen Mocking/Testing und entkoppeln zukünftige Module
(`cache_manager.py`, `channel_router.py`, etc.) von konkreten
Implementierungen.

WICHTIG:
  - `MetadataResult` wird aus der bestehenden Metadaten-Schicht
    importiert (keine Duplizierung).
  - Protocols sind rein strukturell – bestehende Klassen müssen
    NICHT explizit von ihnen erben, solange die Methoden-Signaturen
    passen (PEP 544, structural subtyping).
"""

from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from services.downloader.utils.metadata.models import MetadataResult


# ═══════════════════════════════════════════════════════════════════════════════
# DownloadCoordinator – Haupt-Einstiegspunkt der Download-Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class DownloadCoordinator(Protocol):
    """
    Abstrahiert den Haupt-Orchestrator (analog zu
    `enhanced_download_with_retry()` / `EnhancedDownloadProcessor`).

    Implementierungen koordinieren Download, Metadaten-Verarbeitung
    und liefern ein einheitliches Ergebnis-Dict zurück
    (`{"success": ..., "type": "single"|"playlist", ...}`).
    """

    async def download(
        self,
        url: str,
        chat_id: Optional[int] = None,
        update_id: int = 0,
        status_callback: Optional[Callable[..., Awaitable[None]]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Führt den vollständigen Download- und Verarbeitungs-Vorgang
        für eine URL (Single-Track oder Playlist) aus.
        """
        ...

    def get_stats(self) -> Dict[str, Any]:
        """
        Gibt aggregierte Session- bzw. Verarbeitungsstatistiken zurück
        (analog zu `EnhancedDownloadProcessor.session_stats` /
        `get_processing_statistics()`).
        """
        ...

    def cleanup(self) -> None:
        """
        Räumt belegte Ressourcen auf (Cache, ProgressTracker, etc.),
        analog zu `EnhancedDownloadProcessor.cleanup()`.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# CacheProvider – Metadaten-Cache-Zugriff
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class CacheProvider(Protocol):
    """
    Abstrahiert den Datei-basierten Metadaten-Cache
    (analog zu `utils.metadata_cache.MetadataCache`).

    Wird von `CacheManager` (Phase 2) sowie direkt von
    `EnhancedDownloadProcessor` verwendet.
    """

    def get(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """
        Liest einen Cache-Eintrag für (artist, title).
        Gibt None zurück bei Cache-Miss, korrupter oder leerer Datei.
        """
        ...

    def store(self, artist: str, title: str, metadata: Dict[str, Any]) -> None:
        """Speichert einen Cache-Eintrag atomar."""
        ...

    def invalidate(self, artist: str, title: str) -> None:
        """Entfernt einen einzelnen Cache-Eintrag."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# MetadataEnricher – Metadaten-Anreicherung pro Track
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class MetadataEnricher(Protocol):
    """
    Abstrahiert die Metadaten-Anreicherung eines einzelnen Tracks
    (analog zu `EnhancedMetadataProcessor`).

    `process_track()` entspricht `process_single_track()`:
    nimmt rohe Track-Metadaten entgegen und gibt ein
    `MetadataResult` zurück (Artist-Bestimmung, Genre, Lyrics,
    Cover-Art, Album/Jahr, Datei-Verschiebung, Tag-Schreiben).
    """

    async def process_track(
        self,
        track_metadata: Dict[str, Any],
        file_utils: Any,
        filename_fixer: Any,
        playlist_metadata: Optional[Dict[str, Any]] = None,
        dominant_artist: Optional[str] = None,
    ) -> MetadataResult:
        """Verarbeitet die Metadaten eines einzelnen Tracks vollständig."""
        ...

    def get_statistics(self) -> Dict[str, Any]:
        """
        Gibt detaillierte Verarbeitungsstatistiken zurück
        (analog zu `get_processing_statistics()`), z. B.
        Normalisierungsraten, Cache-Hit-Rate, Lyrics-Erfolgsrate etc.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Hilfstyp: vereinheitlichtes Ergebnis-Listing (für DownloadCoordinator)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TrackResultCollector(Protocol):
    """
    Optionales Hilfs-Protocol für Komponenten, die eine Liste von
    Track-Ergebnissen (Dicts, kompatibel zu `DownloadResult.to_dict()`)
    entgegennehmen und z. B. in Statistiken oder UI-Updates überführen.
    """

    def collect(self, results: List[Dict[str, Any]]) -> None:
        """Nimmt eine Liste von Track-Ergebnis-Dicts entgegen."""
        ...