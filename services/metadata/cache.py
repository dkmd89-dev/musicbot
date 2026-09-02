# services/metadata/cache.py
# -*- coding: utf-8 -*-

import json
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional

from logger import get_module_logger
from utils.metadata_cache import MetadataCache as BaseMetadataCache
from .models import MetadataResult


class MetadataCacheHandler:
    def __init__(self, metadata_cache: BaseMetadataCache, logger=None):
        self.metadata_cache = metadata_cache
        self.logger = logger or get_module_logger("MetadataCacheHandler")
        self._video_id_index_path = self.metadata_cache.cache_path / "video_id_index.json"
        self._video_id_index = self._load_video_id_index()

    def _normalize_cache_title(self, title: str) -> str: ...

    def _load_video_id_index(self) -> Dict[str, Dict[str, str]]:
        """Laedt video_id -> {"artist", "title"} Index (siehe TEST-003-Fix)."""
        if not self._video_id_index_path.exists():
            return {}
        try:
            with open(self._video_id_index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.warning(f"⚠️ Konnte video_id_index nicht laden: {e}")
            return {}

    def _save_video_id_index(self) -> None:
        """
        Schreibt den video_id-Index atomar (write-tmp -> rename), analog zu
        MetadataCache.store() (utils/metadata_cache.py). FINDING-5
        (docs/archive/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md): direktes
        open(mode="w") truncatet die Datei sofort beim Oeffnen - ein
        Prozessabbruch waehrend json.dump() hinterliess vorher eine leere
        oder ungueltige Indexdatei.
        """
        tmp_path = self._video_id_index_path.with_suffix(
            f".tmp_{int(time.time() * 1000)}"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._video_id_index, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self._video_id_index_path)
        except Exception as e:
            self.logger.warning(f"⚠️ Konnte video_id_index nicht speichern: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def check(
        self,
        track_metadata: Dict,
        dominant_artist: Optional[str],
        final_artist: Optional[str] = None,
        clean_title: Optional[str] = None,
    ) -> Optional[MetadataResult]:
        """
        Cache-Hit-Pruefung (TEST-003-Fix).

        check() wird VOR der Artist-/Titel-Bereinigung aufgerufen (nur rohe
        track_metadata), waehrend store() NACH der Bereinigung unter
        result.artist/result.title speichert - ein direkter Artist::Titel-
        Lookup aus rohen Daten wuerde praktisch nie treffen. Stattdessen wird
        die YouTube-Video-ID (track_metadata["id"]) als stabiler Zwischen-
        Schluessel genutzt: sie ist bereits zum Check-Zeitpunkt vorhanden und
        aendert sich durch die Bereinigung nicht.
        """
        try:
            video_id = track_metadata.get("id") if track_metadata else None
            if not video_id:
                return None

            lookup = self._video_id_index.get(video_id)
            if not lookup:
                return None

            cached = self.metadata_cache.get(lookup["artist"], lookup["title"])
            if not cached:
                return None

            library_path_str = cached.get("library_path")
            if library_path_str and not Path(library_path_str).exists():
                self.logger.debug(
                    f"💾 Cache-Eintrag fuer video_id={video_id} verweist auf "
                    f"nicht mehr existierende Datei ({library_path_str}) → Miss"
                )
                return None

            self.logger.debug(f"💾 Cache-Treffer fuer video_id={video_id}")
            return MetadataResult(
                success=cached.get("success", True),
                title=cached.get("title"),
                artist=cached.get("artist"),
                album=cached.get("album"),
                album_artist=cached.get("album_artist"),
                year=cached.get("year"),
                track_number=cached.get("track_number"),
                genres=cached.get("genres"),
                lyrics=cached.get("lyrics"),
                lyrics_source=cached.get("lyrics_source"),
                cover_embedded=cached.get("cover_embedded", False),
                loudness_normalized=cached.get("loudness_normalized", False),
                library_path=Path(library_path_str) if library_path_str else None,
                original_metadata=track_metadata,
                artist_source=cached.get("artist_source"),
                genre_source=cached.get("genre_source"),
                title_cleaned=cached.get("title_cleaned", False),
                is_duplicate=cached.get("is_duplicate", False),
                from_cache=True,
                mb_recording_id=cached.get("musicbrainz_recording_id"),
                mb_artist_id=cached.get("musicbrainz_artist_id"),
                mb_release_id=cached.get("musicbrainz_release_id"),
                mb_release_group_id=cached.get("musicbrainz_release_group_id"),
                mb_isrc=cached.get("isrc"),
            )
        except Exception as e:
            self.logger.warning(f"💾❌ Fehler bei Cache-Pruefung: {e}")
            return None

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
                "loudness_normalized": result.loudness_normalized,
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

            # TEST-003-Fix: video_id-Index aktuell halten, damit check() diesen
            # Eintrag beim naechsten Mal ueber die stabile Video-ID findet.
            video_id = orig.get("id")
            if video_id:
                self._video_id_index[video_id] = {
                    "artist": cache_key_artist,
                    "title": normalized_title,
                }
                self._save_video_id_index()
        except Exception as e:
            self.logger.warning(f"💾❌ Fehler beim Speichern im Cache: {e}")

    def invalidate(self, artist: str, title: str) -> None:
        """Invalidiert einen einzelnen Cache-Eintrag."""
        try:
            self.metadata_cache.invalidate(artist, title)
            self.logger.info(f"💾 Cache-Eintrag invalidiert: {artist} - {title}")
        except Exception as e:
            self.logger.error(f"💾❌ Fehler beim Cache-Invalidieren: {e}")
