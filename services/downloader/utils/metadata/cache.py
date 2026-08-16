# services/downloader/utils/metadata/cache.py
# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Dict, Any, Optional

from logger import get_module_logger
from utils.metadata_cache import MetadataCache as BaseMetadataCache
from .models import MetadataResult


class MetadataCacheHandler:
    def __init__(self, metadata_cache: BaseMetadataCache, logger=None):
        self.metadata_cache = metadata_cache
        self.logger = logger or get_module_logger("MetadataCacheHandler")

    def _normalize_cache_title(self, title: str) -> str: ...

    def check(
        self,
        track_metadata: Dict,
        dominant_artist: Optional[str],
        final_artist: Optional[str] = None,
        clean_title: Optional[str] = None,
    ) -> Optional[MetadataResult]: ...

    def store(self, result, dominant_artist, cover_source: str = None) -> None:
        """Speichert ein MetadataResult im Cache."""
        try:
            if not result.success:
                return

            cache_key_artist = (
                result.artist.lower().strip() if result.artist else "unknown"
            )
            title_for_cache = result.title
            normalized_title = self._normalize_cache_title(title_for_cache)

            if not normalized_title:
                normalized_title = title_for_cache.lower().strip()

            self.logger.debug(
                f"💾 Cache-Speicherung: original='{title_for_cache}' → normalisiert='{normalized_title}'"
            )

            orig = result.original_metadata or {}
            cache_data = {
                "success": result.success,
                "title": result.title,
                "artist": result.artist,
                "album": result.album,
                "album_artist": result.album_artist,
                "year": result.year,
                "track_number": result.track_number,
                "genres": result.genres,
                "lyrics": result.lyrics,
                "lyrics_source": result.lyrics_source,
                "library_path": (
                    str(result.library_path) if result.library_path else None
                ),
                "artist_source": result.artist_source,
                "genre_source": result.genre_source,
                "title_cleaned": result.title_cleaned,
                "is_duplicate": result.is_duplicate,
                "cover_embedded": result.cover_embedded,
                "musicbrainz_recording_id": orig.get("musicbrainz_recording_id"),
                "musicbrainz_artist_id": orig.get("musicbrainz_artist_id"),
                "musicbrainz_release_id": orig.get("musicbrainz_release_id"),
                "musicbrainz_release_group_id": orig.get(
                    "musicbrainz_release_group_id"
                ),
                "isrc": orig.get("isrc"),
                "cover_source": cover_source,
            }
            self.metadata_cache.store(cache_key_artist, normalized_title, cache_data)
            self.logger.debug(
                f"💾 Metadaten im Cache gespeichert: {cache_key_artist} - {normalized_title}"
            )
        except Exception as e:
            self.logger.warning(f"💾❌ Fehler beim Speichern im Cache: {e}")

    def invalidate(self, artist: str, title: str) -> None:
        """Invalidiert einen einzelnen Cache-Eintrag."""
        try:
            self.metadata_cache.invalidate(artist, title)
            self.logger.info(f"💾 Cache-Eintrag invalidiert: {artist} - {title}")
        except Exception as e:
            self.logger.error(f"💾❌ Fehler beim Cache-Invalidieren: {e}")
