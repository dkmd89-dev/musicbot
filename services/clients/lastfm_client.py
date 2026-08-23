# services/clients/lastfm_client.py

import asyncio
import pylast
from typing import Optional, Dict, List, Any, Tuple

from config import Config
import async_timeout
from utils.genre_map import GenreMapper
from logger import (
    log_metadata_info,
    log_metadata_debug,
    log_metadata_warning,
    log_metadata_error,
    _module_loggers,
)

metadata_logger = _module_loggers.get("metadata")
if not metadata_logger:
    import logging
    metadata_logger = logging.getLogger("metadata")


class LastFMClient:
    """
    Client zur Abfrage von Last.fm-Metadaten.
    """

    def __init__(self):
        config = Config()
        self.api_key = config.LASTFM_API_KEY
        self.api_secret = config.LASTFM_API_SECRET
        
        # Network initialisieren (genau wie im Test)
        self.network = pylast.LastFMNetwork(
            api_key=self.api_key,
            api_secret=self.api_secret,
            username=None,
            password_hash=None,
        )
        self.genremapper = GenreMapper()
        metadata_logger.info("✨ LastFMClient initialisiert.")

    def _get_lastfm_data(
        self, title: str, artist: str, mbid: str = None
    ) -> Tuple[Optional[Dict], List]:
        """
        Holt Last.fm-Daten für einen Track.
        """
        context_str = f"{artist} - {title}"
        
        try:
            # Artist-Objekt holen (wie im Test)
            artist_obj = self.network.get_artist(artist)
            if not artist_obj:
                log_metadata_debug(f"[{context_str}] Artist nicht gefunden")
                return None, []
            
            log_metadata_debug(f"[{context_str}] Artist gefunden: {artist_obj}")
            
            # Artist-Tags holen (funktioniert wie im Test)
            artist_tags = []
            try:
                tags = artist_obj.get_top_tags(limit=10)
                artist_tags = [tag.item.get_name().lower() for tag in tags]
                if artist_tags:
                    log_metadata_info(f"[{context_str}] 🎤 Artist-Tags: {artist_tags[:5]}")
            except Exception as e:
                log_metadata_debug(f"[{context_str}] Artist-Tags Fehler: {e}")
            
            # Versuche Track-Tags (wenn möglich)
            track_tags = []
            try:
                # Track via get_track versuchen
                track = self.network.get_track(artist, title)
                if track:
                    track_tags_raw = track.get_top_tags(limit=10) or []
                    track_tags = [tag.item.get_name().lower() for tag in track_tags_raw]
                    if track_tags:
                        log_metadata_info(f"[{context_str}] 🏷️ Track-Tags: {track_tags[:5]}")
            except Exception as e:
                log_metadata_debug(f"[{context_str}] Track-Tags Fehler: {e}")
            
            # Kombiniere Tags (Artist-Tags haben Vorrang)
            all_tags = []
            for t in artist_tags + track_tags:
                if t not in all_tags:
                    all_tags.append(t)
            
            # Simuliere track_info für minimalen Fallback
            track_info = {
                "title": title,
                "artist": artist,
                "album": None,
                "listeners": None,
                "playcount": None,
                "wiki": None,
            }
            
            log_metadata_info(f"[{context_str}] ✅ {len(all_tags)} Tags: {all_tags[:5]}")
            return track_info, all_tags
            
        except Exception as e:
            log_metadata_error(f"[{context_str}] Fehler: {e}", exc_info=True)
            return None, []

    async def fetch_metadata(
        self, title: str, artist: str, include_genre: bool = True, mbid: str = None
    ) -> Dict[str, Any]:
        """
        Holt Last.fm-Metadaten.
        """
        context_str = f"{artist} - {title}"
        log_metadata_debug(f"[LastFM] 📥 Hole Metadaten für: {context_str}")
        
        try:
            async with async_timeout.timeout(Config.LASTFM_TIMEOUT):
                track_info, tag_names = await asyncio.to_thread(
                    self._get_lastfm_data, title, artist, mbid
                )
                
                if not track_info:
                    log_metadata_info(f"[LastFM] Keine Daten für {context_str}")
                    return {}
                
                log_metadata_info(f"[LastFM] 🏷️ {len(tag_names)} Tags: {tag_names[:5] if tag_names else 'keine'}")
                
                genre = "unknown"
                if include_genre and tag_names:
                    genre_result = self.genremapper.determine_genre(
                        raw_genre=", ".join(tag_names), artist_name=artist
                    )
                    if genre_result and hasattr(genre_result, "primary") and genre_result.primary:
                        genre = genre_result.primary
                        log_metadata_info(f"[LastFM] 🎵 Genre: '{genre}'")
                
                return {
                    "tags": tag_names,
                    "listeners": track_info.get("listeners"),
                    "playcount": track_info.get("playcount"),
                    "album": track_info.get("album"),
                    "wiki": track_info.get("wiki"),
                    "genre": genre,
                }
                
        except asyncio.TimeoutError:
            log_metadata_warning(f"[LastFM] ⏱️ Timeout für {context_str}")
            return {}
        except Exception as e:
            log_metadata_error(f"[LastFM] ❌ Fehler: {e}")
            return {}
