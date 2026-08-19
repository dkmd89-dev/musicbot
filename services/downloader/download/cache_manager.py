# services/downloader/download/cache_manager.py
# -*- coding: utf-8 -*-
"""
CacheManager – zentrale Cache-Lookup-Logik für Single- und Playlist-Tracks.

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Cache-LESEN (lookup) und Ergebnis-Dict-Aufbau.
  - KEIN Download, KEINE Metadaten-Verarbeitung, KEIN Channel-Routing.

Dependency Injection:
  - `MetadataCache`-Instanz wird injiziert (kein Singleton-Zugriff).
  - `ArtistNormalizer` wird injiziert (für Stufe-2-Parsing).
  - Eigene Logger-Instanz via `get_module_logger`.

Log-Marker bleiben unverändert: [CACHE], "Stufe 1", "Stufe 2".
"""

from pathlib import Path
from typing import Any, Dict, Optional

from logger import get_module_logger
from utils.metadata_cache import MetadataCache


class CacheManager:
    """
    Kapselt den 2-stufigen Cache-Lookup für Playlist-Tracks sowie den
    einfachen Cache-Lookup für Single-Downloads.

    Stufe 1 (Playlist): direkter Lookup mit (dominant_artist | track-artist, titel)
    Stufe 2 (Playlist): ArtistMap-Parsing des Original-Titels → alternativer Lookup
    Single             : direkter Lookup mit (artist, titel) aus video_info
    """

    def __init__(
        self,
        metadata_cache: MetadataCache,
        artist_normalizer=None,
        logger=None,
        logger_factory=None,
    ):
        self.metadata_cache = metadata_cache
        self.artist_normalizer = artist_normalizer
        self.logger = logger or (logger_factory or get_module_logger)("CacheManager")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API – Playlist
    # ─────────────────────────────────────────────────────────────────────────

    def lookup_playlist_track(
        self,
        track_info: Dict[str, Any],
        dominant_artist: Optional[str],
        album_name: str,
        playlist_year: Optional[int],
        track_idx: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Zweistufiger Cache-Lookup für einen Playlist-Track:

          Stufe 1 – Direkter Lookup mit dominant_artist + bereinigtem Titel
          Stufe 2 – ArtistMap-Parsing des Original-Titels → alternativer Lookup

        Gibt ein Ergebnis-Dict (kompatibel zu `DownloadResult.to_dict()`) zurück
        oder None bei Cache-Miss in beiden Stufen.

        HINWEIS: `_enhanced_processor_ref` wird hier NICHT gesetzt – das obliegt
        dem Aufrufer (download_utils.py), da der CacheManager keine Referenz auf
        den Processor besitzt (Dependency Injection / keine zirkulären Abhängigkeiten).
        """
        key_artist = dominant_artist or track_info.get("artist", "Unknown")
        key_title = track_info.get("title", "Unknown")

        self.logger.debug(
            f"💾 [CACHE] Stufe 1 – Lookup:\n"
            f"   Artist-Key : '{key_artist}'\n"
            f"   Titel-Key  : '{key_title}'"
        )

        # ── Stufe 1 ──────────────────────────────────────────────────────────
        cached = self.metadata_cache.get(key_artist, key_title)
        if cached and cached.get("library_path"):
            cached_path = Path(cached["library_path"])
            if cached_path.exists():
                self.logger.info(
                    f"💾 [CACHE] ✅ Stufe-1-HIT:\n"
                    f"   Schlüssel : '{key_artist}' / '{key_title}'\n"
                    f"   Pfad      : {cached_path}"
                )
                return self._build_result(
                    cached, cached_path, album_name, playlist_year, track_idx
                )
            else:
                self.logger.warning(
                    f"💾 [CACHE] ⚠️ Stufe-1-Eintrag gefunden, aber Datei fehlt: {cached_path}"
                )

        # ── Stufe 2: ArtistMap-Parsing des Original-Titels ─────────────────────
        search_title = track_info.get("original_youtube_title") or track_info.get(
            "title", ""
        )
        if not search_title:
            self.logger.debug("💾 [CACHE] Stufe 2 übersprungen – kein Titel verfügbar")
            return None

        if self.artist_normalizer is None or not hasattr(
            self.artist_normalizer, "parse_youtube_title"
        ):
            self.logger.debug(
                "💾 [CACHE] Stufe 2 übersprungen – kein ArtistNormalizer verfügbar"
            )
            return None

        self.logger.debug(
            f"💾 [CACHE] Stufe 2 – ArtistMap-Parsing:\n"
            f"   Original-Titel : '{search_title}'"
        )
        try:
            # BUG-011: parse_youtube_title() liefert ParseResult (Dataclass,
            # kein Dict) - .get()/[...] warfen hier bisher IMMER AttributeError/
            # TypeError, vom umschliessenden except stillschweigend auf Debug-
            # Level abgefangen. Stufe 2 funktionierte dadurch nie. Fix:
            # Attribut-Zugriff statt Dict-Zugriff.
            parsed = self.artist_normalizer.parse_youtube_title(search_title)
            if parsed and parsed.main_artist and parsed.title:
                alt_artist = parsed.main_artist
                alt_title = parsed.title

                self.logger.debug(
                    f"   Geparst → Artist: '{alt_artist}', Titel: '{alt_title}'"
                )

                alt_cached = self.metadata_cache.get(alt_artist, alt_title)
                if alt_cached and alt_cached.get("library_path"):
                    alt_path = Path(alt_cached["library_path"])
                    if alt_path.exists():
                        self.logger.info(
                            f"💾 [CACHE] ✅ Stufe-2-HIT (ArtistMap-Parsing):\n"
                            f"   Artist  : '{alt_artist}'\n"
                            f"   Titel   : '{alt_title}'\n"
                            f"   Pfad    : {alt_path}"
                        )
                        result = self._build_result(
                            alt_cached, alt_path, album_name, playlist_year, track_idx
                        )
                        result["artist_source"] = "artist_map_cache"
                        result["title_cleaned"] = True
                        return result
                    else:
                        self.logger.warning(
                            f"💾 [CACHE] ⚠️ Stufe-2-Eintrag gefunden, aber Datei fehlt: {alt_path}"
                        )
        except Exception as e:
            self.logger.debug(f"💾 [CACHE] Stufe-2-Parsing fehlgeschlagen: {e}")

        self.logger.debug("💾 [CACHE] MISS – kein Treffer in beiden Stufen")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API – Single-Track
    # ─────────────────────────────────────────────────────────────────────────

    def lookup_single_track(
        self, artist: str, title: str
    ) -> Optional[Dict[str, Any]]:
        """
        Direkter Cache-Lookup für einen Single-Download mit (artist, title).

        Gibt ein Ergebnis-Dict (kompatibel zu `DownloadResult.to_dict()`) zurück
        oder None bei Cache-Miss bzw. fehlender Library-Datei.
        """
        self.logger.info(
            f"💾 [CACHE] Prüfe Single-Cache:\n"
            f"   Artist-Key : '{artist}'\n"
            f"   Titel-Key  : '{title}'"
        )

        cached_metadata = self.metadata_cache.get(artist, title)
        if cached_metadata and cached_metadata.get("library_path"):
            cached_path = Path(cached_metadata["library_path"])
            if cached_path.exists():
                self.logger.info(f"💾 [CACHE] ✅ HIT für Single:\n" f"   Pfad : {cached_path}")
                return {
                    "success": True,
                    "title": cached_metadata.get("title"),
                    "artist": cached_metadata.get("artist"),
                    "album": cached_metadata.get("album"),
                    "year": cached_metadata.get("year"),
                    "genres": cached_metadata.get("genres"),
                    "library_path": str(cached_path),
                    "artist_source": cached_metadata.get("artist_source", "cache"),
                    "genre_source": cached_metadata.get("genre_source", "cache"),
                    "lyrics_available": bool(cached_metadata.get("lyrics")),
                    "lyrics_source": cached_metadata.get("lyrics_source"),
                    "title_cleaned": cached_metadata.get("title_cleaned", False),
                    "from_cache": True,
                }
            else:
                self.logger.warning(
                    f"💾 [CACHE] ⚠️ Cache-Eintrag vorhanden, aber Datei fehlt: {cached_path}"
                )
        else:
            self.logger.debug("💾 [CACHE] MISS – kein Eintrag gefunden")

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _build_result(
        self,
        cached: Dict[str, Any],
        path: Path,
        album_name: str,
        playlist_year: Optional[int],
        track_idx: int,
    ) -> Dict[str, Any]:
        """Baut ein einheitliches Cache-Ergebnis-Dict für Playlist-Treffer."""
        return {
            "success": True,
            "title": cached.get("title"),
            "artist": cached.get("artist"),
            "album": album_name,
            "year": playlist_year,
            "genres": cached.get("genres"),
            "library_path": str(path),
            "artist_source": cached.get("artist_source", "cache"),
            "genre_source": cached.get("genre_source", "cache"),
            "playlist_album": album_name,
            "track_number": track_idx,
            "lyrics_available": bool(cached.get("lyrics")),
            "lyrics_source": cached.get("lyrics_source"),
            "is_duplicate": False,
            "title_cleaned": cached.get("title_cleaned", False),
            "from_cache": True,
        }