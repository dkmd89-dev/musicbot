# services/downloader/utils/enhanced_metadata_processor.py
# -*- coding: utf-8 -*-

import re
import asyncio
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Tuple

from logger import get_module_logger, setup_module_logging
from config import Config

from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper
from utils.youtube_parser import parse_youtube_title
from utils.filenamefixer import (
    FilenameFixerTool,
    get_special_category,
    get_special_channel_info,
    load_special_channels_merged,
)
from services.clients.genius_client import GeniusClient
from utils.metadata_cache import MetadataCache
from utils.singleton import SingletonMixin

from services.downloader.utils.metadata.models import (
    MetadataResult,
    EnhancedProcessingStats,
    split_main_and_featuring,
)
from services.metadata.cache import MetadataCacheHandler
from services.metadata.artist_processor import ArtistProcessor
from services.metadata.title_cleaner import TitleCleaner
from services.metadata.genre_processor import GenreProcessor
from services.metadata.album_processor import AlbumProcessor
from services.metadata.lyrics_processor import LyricsProcessor
from services.metadata.cover_processor import CoverProcessor
from services.metadata.auto_learn import AutoLearnManager
from services.metadata.tag_writer import TagWriter
from services.downloader.utils.download_artifact_cleanup import (
    cleanup_single_download_artifact,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Hauptklasse
# ═══════════════════════════════════════════════════════════════════════════════


class EnhancedMetadataProcessor(SingletonMixin):
    """
    Orchestriert die erweiterte Metadatenverarbeitung.
    Alle Einzelverantwortlichkeiten sind in Sub-Prozessoren ausgelagert.
    """

    def _do_init(
        self,
        config=None,
        logger_factory: Optional[Callable] = None,
        genius_logger=None,
        cache_logger=None,
    ):
        self.config = config or self._get_default_config()
        self.logger_factory = logger_factory or get_module_logger

        log_file_path = (
            Path(getattr(self.config, "LOG_DIR", "logs"))
            / "enhanced_metadata_processor.log"
        )
        self.logger = setup_module_logging(
            "EnhancedMetadataProcessor",
            log_file=str(log_file_path),
            level="DEBUG",
            use_colors=True,
            use_emojis=True,
        )

        self.genius_logger = genius_logger or self.logger_factory("GeniusClient")
        self.cache_logger = cache_logger or self.logger_factory("MetadataCache")

        self.logger.info("Initialisiere Enhanced Metadata Processor...")

        # ── Sub-Prozessoren ──────────────────────────────────────────────────
        artist_config = ArtistConfig(
            library_dir=getattr(self.config, "LIBRARY_DIR", "library"),
            override_file=getattr(
                self.config, "ARTIST_OVERRIDE_FILE", "./artist_overrides.json"
            ),
        )
        self.artist_normalizer = ArtistNormalizer(artist_config)
        self.artist_processor = ArtistProcessor(
            artist_normalizer=self.artist_normalizer,
            logger=self.logger_factory("ArtistProcessor"),
        )

        self.genre_mapper = GenreMapper(
            mapping_dir=getattr(self.config, "GENRE_MAPPING_DIR", "mapping")
        )
        self.genre_processor = GenreProcessor(
            config=self.config,
            genre_mapper=self.genre_mapper,
            logger=self.logger_factory("GenreProcessor"),
        )

        self.genius_client = GeniusClient(logger=self.genius_logger)
        self.lyrics_processor = LyricsProcessor(
            genius_client=self.genius_client,
            logger=self.logger_factory("LyricsProcessor"),
        )

        # Cover-Processor mit Fanart.tv API-Key aus Config
        _fanart_key = getattr(self.config, "FANART_API_KEY", None) or ""
        self.cover_processor = CoverProcessor(
            fanart_api_key=_fanart_key or None,
            logger=self.logger_factory("CoverProcessor"),
        )

        self.metadata_cache_obj = MetadataCache(
            cache_dir=getattr(self.config, "METADATA_CACHE_DIR", "metadata_cache")
        )
        self.cache_handler = MetadataCacheHandler(
            self.metadata_cache_obj, self.cache_logger
        )

        self.title_cleaner = TitleCleaner(logger=self.logger_factory("TitleCleaner"))
        self.album_processor = AlbumProcessor(
            logger=self.logger_factory("AlbumProcessor"),
        )

        self.auto_learn_manager = AutoLearnManager(
            config=self.config,
            artist_normalizer=self.artist_normalizer,
            genre_mapper=self.genre_mapper,
            logger=self.logger_factory("AutoLearnManager"),
        )

        self.tag_writer = TagWriter(
            logger=self.logger_factory("TagWriter"),
            artist_normalizer=self.artist_normalizer,
        )

        self.processing_stats = EnhancedProcessingStats()
        self.processed_titles: set = set()

        # Lazy MB/LFM Clients (initialisiert beim ersten Genre-Aufruf)
        self._mb_client = None
        self._lfm_client = None

        self.logger.info("✅ Enhanced Metadata Processor erfolgreich initialisiert")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche Statistik-API
    # ─────────────────────────────────────────────────────────────────────────

    def get_processing_statistics(self) -> Dict[str, Any]:
        stats = {
            "total_processed": self.processing_stats.total_processed,
            "successful_normalizations": self.processing_stats.successful_normalizations,
            "successful_genre_mappings": self.processing_stats.successful_genre_mappings,
            "dominant_artist_used": self.processing_stats.dominant_artist_used,
            "youtube_parser_used": self.processing_stats.youtube_parser_used,
            "lyrics_found": self.processing_stats.lyrics_found,
            "cover_art_found": self.processing_stats.cover_art_found,
            "duplicate_tracks": self.processing_stats.duplicate_tracks,
            "cache_hits": self.processing_stats.cache_hits,
            "cache_misses": self.processing_stats.cache_misses,
            "title_cleaned_by_artist_map": self.processing_stats.title_cleaned_by_artist_map,
            "artist_map_parsing_fallback": self.processing_stats.artist_map_parsing_fallback,
        }
        total = max(self.processing_stats.total_processed, 1)
        cache_total = max(stats["cache_hits"] + stats["cache_misses"], 1)
        stats.update(
            {
                "normalization_rate": (stats["successful_normalizations"] / total)
                * 100,
                "genre_mapping_rate": (stats["successful_genre_mappings"] / total)
                * 100,
                "lyrics_success_rate": (stats["lyrics_found"] / total) * 100,
                "cover_art_found_rate": (stats["cover_art_found"] / total) * 100,
                "youtube_parser_rate": (stats["youtube_parser_used"] / total) * 100,
                "cache_hit_rate": (stats["cache_hits"] / cache_total) * 100,
            }
        )
        return stats

    def reset_statistics(self):
        self.processing_stats = EnhancedProcessingStats()
        self.processed_titles.clear()
        self.logger.info("📊 Verarbeitungsstatistiken zurückgesetzt")

    def cleanup(self):
        if hasattr(self, "metadata_cache_obj"):
            self.metadata_cache_obj.cleanup()
        if hasattr(self, "genius_client"):
            self.genius_client.close()
        self.logger.info("🧹 Enhanced Metadata Processor cleanup abgeschlossen")

    async def aclose(self) -> None:
        """
        Async-fähiger Cleanup für Komponenten, die asynchrone Ressourcen
        halten (aktuell: GeniusClient/aiohttp-Session). Ergänzt cleanup(),
        ersetzt es nicht - ruft es selbst NICHT auf (identisches Verhalten
        zum vorher in bot.py lebenden Code, der ebenfalls unabhängig von
        cleanup() lief).
        """
        genius = getattr(self, "genius_client", None)
        if not genius:
            return
        try:
            if hasattr(genius, "async_close") and asyncio.iscoroutinefunction(
                genius.async_close
            ):
                await genius.async_close()
                self.logger.debug("✅ GeniusClient async_close() aufgerufen")
            elif hasattr(genius, "_session"):
                session = genius._session
                if session and not session.closed:
                    await session.close()
                    self.logger.debug("✅ GeniusClient._session direkt geschlossen")
            if hasattr(genius, "close"):
                genius.close()
        except Exception as e:
            self.logger.debug(f"ℹ️ Async-Cleanup von GeniusClient: {e}")

    def invalidate_cache_entry(self, artist: str, title: str) -> None:
        """Invalidiert einen einzelnen Cache-Eintrag."""
        self.cache_handler.invalidate(artist, title)

    # ─────────────────────────────────────────────────────────────────────────
    # Hauptverarbeitung
    # ─────────────────────────────────────────────────────────────────────────
    async def process_single_track(
        self,
        track_metadata,
        filename_fixer,
        playlist_metadata=None,
        dominant_artist=None,
    ):
        """Hauptmethode für Track-Verarbeitung"""
        if track_metadata is None:
            self.logger.error("❌ track_metadata ist None!")
            return MetadataResult(
                success=False,
                title="Fehler",
                artist="Unbekannt",
                error="track_metadata is None",
            )

        self.logger.info("🚀 1️⃣ Starte erweiterte Track-Metadatenverarbeitung...")

        # ARCH-005 (Temp-Cleanup) Strategie C: vor Schritt 14 gebunden, damit
        # der except-Block unten immer einen definierten Wert sieht (auch
        # wenn der Fehler VOR Schritt 14 auftrat, wo original_path erst
        # gesetzt wird).
        original_path: Optional[Path] = None

        try:
            self.processing_stats.total_processed += 1

            # ── 2. Cache-Check ───────────────────────────────────────────────
            self.logger.info("💾 2️⃣ Prüfe Metadaten-Cache...")
            cache_result = self.cache_handler.check(track_metadata, dominant_artist)
            if cache_result:
                self.processing_stats.cache_hits += 1
                self.logger.info(f"💾✅ Cache-Treffer für: {cache_result.title}")
                return cache_result
            self.processing_stats.cache_misses += 1
            self.logger.info("💾❌ Kein Cache-Treffer. Starte volle Verarbeitung.")

            # ── 3. Basis-Daten ───────────────────────────────────────────────
            self.logger.debug("📋 3️⃣ Extrahiere Basis-Daten...")
            raw_title = track_metadata.get("title", "Unbekannter Titel")
            raw_artist = track_metadata.get("artist") or track_metadata.get("uploader")
            video_id = track_metadata.get("id")
            channel_name = (
                track_metadata.get("channel") or track_metadata.get("uploader") or ""
            )
            _channel_for_special_detection = (
                track_metadata.get("playlist_channel") or channel_name
            )
            try:
                _normalized_channel = self.artist_normalizer.normalize(
                    _channel_for_special_detection
                )
                if _normalized_channel and _normalized_channel.lower() not in (
                    "unknown",
                    "unbekannt",
                    "",
                ):
                    _channel_for_special_detection = _normalized_channel
            except Exception as _norm_err:
                self.logger.debug(
                    f"⚠️ Channel-Normalisierung fehlgeschlagen: {_norm_err}"
                )

            _PODCAST_CHANNELS = {"backstage boxengasse", "sky sport formel 1"}
            _is_podcast_channel = (
                channel_name.strip().lower() in _PODCAST_CHANNELS
                or _channel_for_special_detection.strip().lower() in _PODCAST_CHANNELS
            )

            # ── 4. YouTube-Titel parsen ──────────────────────────────────────
            self.logger.debug("📺 4️⃣ Parse YouTube-Titel...")
            if _is_podcast_channel:
                youtube_parsed: Dict[str, Any] = {}
                youtube_parser_used = False
                parsed_by_artist_map = False
            else:
                youtube_parsed = parse_youtube_title(raw_title)
                youtube_parser_used = bool(
                    youtube_parsed.get("artist") or youtube_parsed.get("song_title")
                )
            if youtube_parser_used:
                self.processing_stats.youtube_parser_used += 1

            # ── 5. Artist-Map Fallback ───────────────────────────────────────
            self.logger.debug("🎯 5️⃣ Prüfe Artist-Map Fallback-Parsing...")
            parsed_by_artist_map = False
            if not _is_podcast_channel and (
                not youtube_parser_used or not youtube_parsed.get("song_title")
            ):
                if hasattr(self.artist_normalizer, "parse_youtube_title"):
                    artist_map_result = self.artist_normalizer.parse_youtube_title(
                        raw_title
                    )
                    if (
                        artist_map_result
                        and artist_map_result.get("title")
                        and artist_map_result.get("title") != raw_title
                    ):
                        youtube_parsed = {
                            "artist": artist_map_result.get("main_artist"),
                            "song_title": artist_map_result.get("title"),
                            "original_title": raw_title,
                        }
                        parsed_by_artist_map = True
                        self.processing_stats.artist_map_parsing_fallback += 1
                        self.logger.info(
                            f"🎯✅ Artist-Map Fallback: '{raw_title}' → "
                            f"Artist: '{artist_map_result.get('main_artist')}', "
                            f"Titel: '{artist_map_result.get('title')}'"
                        )

            # ── 5.5 Spezialkanal Pre-Check ───────────────────────────────────
            _special_channels_cfg = load_special_channels_merged(self.config)
            _channel_info = get_special_channel_info(
                _channel_for_special_detection, _special_channels_cfg
            )
            _is_special_channel_pre = bool(_channel_info)
            _pre_category = _channel_info[0] if _channel_info else None
            _canonical_channel_name = (
                _channel_info[1] if _channel_info else channel_name
            )

            if _is_special_channel_pre and dominant_artist:
                self.logger.info(
                    f"⭐ Spezialkanal erkannt – dominant_artist '{dominant_artist}' "
                    f"wird NICHT als Track-Künstler übernommen"
                )
                _effective_dominant = None
            else:
                _effective_dominant = dominant_artist

            # ── 5.6 Raw-Artist Bereinigung ───────────────────────────────────
            _effective_raw_artist = raw_artist
            _yt_has_artist = bool(
                youtube_parsed.get("artist") or youtube_parsed.get("all_artists")
            )

            if _yt_has_artist and raw_artist:
                _raw_l = raw_artist.strip().lower()
                _chan_l = _channel_for_special_detection.strip().lower()
                _uploader_l = (track_metadata.get("uploader") or "").strip().lower()
                _channel_l = channel_name.strip().lower() if channel_name else ""

                # raw_artist == Kanal-/Uploader-Name → kein echter Künstler-Tag
                if (
                    _raw_l == _chan_l
                    or (_chan_l and _raw_l in _chan_l)
                    or _raw_l == _uploader_l
                    or _raw_l == _channel_l
                ):
                    _effective_raw_artist = None
                    self.logger.debug(
                        f"🎤 [5.6] raw_artist '{raw_artist}' == uploader/channel "
                        f"→ ignoriert (YT-Parser liefert "
                        f"'{youtube_parsed.get('artist')}')"
                    )

            # ── 6. Artist-Bestimmung ─────────────────────────────────────────
            self.logger.info("🎤 6️⃣ Bestimme finalen Künstler...")
            if not _is_podcast_channel and youtube_parsed.get("all_artists"):
                _original_all = youtube_parsed.get("all_artists", [])
                _cleaned_all = []
                for a in _original_all:
                    main, feats = split_main_and_featuring(a)
                    if main and main not in _cleaned_all:
                        _cleaned_all.append(main)
                    for f in feats:
                        if f and f not in _cleaned_all:
                            _cleaned_all.append(f)
                if _cleaned_all != _original_all:
                    youtube_parsed["all_artists"] = _cleaned_all

            if not _is_podcast_channel and youtube_parsed.get("artist"):
                _raw_parsed_artist = youtube_parsed.get("artist")
                _cleaned_main, _cleaned_feat = split_main_and_featuring(
                    _raw_parsed_artist
                )
                if _cleaned_feat:
                    youtube_parsed["artist"] = _cleaned_main
                    for f in _cleaned_feat:
                        if f not in youtube_parsed.get("all_artists", []):
                            youtube_parsed.setdefault("all_artists", []).append(f)

            _all_parsed_artists = youtube_parsed.get("all_artists", [])
            _first_artist = None
            if not _is_podcast_channel and _all_parsed_artists:
                _first_artist = _all_parsed_artists[0].strip()

            final_artist, artist_source, feat_artists_from_determination = (
                self.artist_processor.determine_best_artist(
                    raw_artist=_effective_raw_artist,
                    parsed_artist=_first_artist or youtube_parsed.get("artist"),
                    dominant_artist=_effective_dominant,
                    channel_name=channel_name,
                )
            )
            if _first_artist:
                artist_source = "first_artist_from_title"

            self.logger.info(
                f"🎤✅ Finaler Künstler: '{final_artist}' (Quelle: {artist_source})"
            )
            if artist_source in ("normalized", "playlist_dominant"):
                self.processing_stats.successful_normalizations += 1
            if artist_source == "playlist_dominant":
                self.processing_stats.dominant_artist_used += 1

            # Feature-Split (ARTIST-001-Fix: Haupt-/Feature-Trennung kommt
            # jetzt bereits korrekt aus determine_best_artist() - VOR der
            # Normalisierung ermittelt, statt hier ein zweites Mal auf dem
            # bereits normalisierten (und dadurch ggf. abgeflachten)
            # final_artist-String zu raten.)
            if not _is_podcast_channel:
                feat_artists_raw = feat_artists_from_determination
                if feat_artists_raw:
                    feat_artists = list(
                        dict.fromkeys(
                            fa_clean.strip()
                            for fa in feat_artists_raw
                            for fa_clean, _ in [split_main_and_featuring(fa)]
                            if fa_clean
                            and fa_clean.strip().lower() != final_artist.strip().lower()
                        )
                    )
                else:
                    feat_artists = []
            else:
                feat_artists = []

            if (
                _all_parsed_artists
                and not feat_artists
                and len(_all_parsed_artists) > 1
            ):
                _remaining = list(
                    dict.fromkeys(
                        a_clean.strip()
                        for a in _all_parsed_artists
                        if a.strip().lower() != final_artist.strip().lower()
                        for a_clean, _ in [split_main_and_featuring(a)]
                        if a_clean
                        and a_clean.strip().lower() != final_artist.strip().lower()
                    )
                )
                if _remaining:
                    feat_artists = _remaining

            # ── 7. Titel-Bereinigung ─────────────────────────────────────────
            self.logger.info(f"🎵 7️⃣ Bestimme finalen Titel...")
            if _is_podcast_channel:
                clean_title = raw_title.strip()
            else:
                parsed_song_title = youtube_parsed.get("song_title")
                if parsed_song_title and len(parsed_song_title.strip()) >= 3:
                    clean_title = parsed_song_title.strip()
                else:
                    clean_title = self.title_cleaner.light_title_cleanup(
                        raw_title, final_artist
                    )

            search_title_for_genre = self.title_cleaner.build_search_title(
                parsed_title=youtube_parsed.get("song_title"),
                original_title=raw_title,
                final_artist=final_artist,
            )

            # ── 8. Duplikat-Erkennung ────────────────────────────────────────
            title_key = f"{final_artist}|{clean_title}".lower()
            is_duplicate = title_key in self.processed_titles
            if is_duplicate:
                self.processing_stats.duplicate_tracks += 1
                self.logger.warning(f"🔄 Duplikat: {final_artist} - {clean_title}")
            self.processed_titles.add(title_key)

            # ── 9. Genre ─────────────────────────────────────────────────────────────
            self.logger.info("🏷️ 9️⃣ Bestimme Genre...")
            genres_result = await self._determine_genre_with_stats(
                track_metadata=track_metadata,
                artist_name=final_artist,
                channel_name=channel_name,
                canonical_channel_name=_canonical_channel_name,
                is_special_channel=_is_special_channel_pre,
                feat_artists=feat_artists,
                clean_title=search_title_for_genre,
            )

            # ── DEBUG 9: genres_result untersuchen ───────────────────────────────────
            self.logger.info(f"[DEBUG 9] genres_result type: {type(genres_result)}")

            self.logger.info(
                f"[DEBUG 9] genres_result.__dict__ = "
                f"{getattr(genres_result, '__dict__', genres_result)}"
            )

            self.logger.info(
                f"[DEBUG 9] genres_result.mb_ids = "
                f"{getattr(genres_result, 'mb_ids', None)}"
            )

            # ── 9b. MBIDs aus Genre-Pipeline übernehmen ─────────────────────────────
            _mb_ids_from_genre = getattr(genres_result, "mb_ids", None) or {}

            self.logger.info(f"[DEBUG 9b] _mb_ids_from_genre = {_mb_ids_from_genre}")

            if _mb_ids_from_genre:
                self.logger.info(
                    f"[DEBUG 9b] verfügbare Keys: {list(_mb_ids_from_genre.keys())}"
                )

                _id_mapping = {
                    "recording_id": "musicbrainz_recording_id",
                    "release_id": "musicbrainz_release_id",
                    "release_group_id": "musicbrainz_release_group_id",
                    "artist_id": "musicbrainz_artist_id",
                    "isrc": "isrc",
                }
                _ids_written = []
                for src_key, dst_key in _id_mapping.items():
                    val = _mb_ids_from_genre.get(src_key)
                    if val and not track_metadata.get(dst_key):
                        track_metadata[dst_key] = val
                        _ids_written.append(src_key)
                if _ids_written:
                    self.logger.info(
                        f"🔖 [MB-IDs] Aus Genre-Pipeline übernommen: {_ids_written}"
                    )
                    self.logger.info(
                        f"[DEBUG 9b] track_metadata nach Übernahme:\n"
                        f"  recording_id = {track_metadata.get('musicbrainz_recording_id', '—')[:16] if track_metadata.get('musicbrainz_recording_id') else '—'}...\n"
                        f"  release_id   = {track_metadata.get('musicbrainz_release_id', '—')[:16] if track_metadata.get('musicbrainz_release_id') else '—'}...\n"
                        f"  release_group= {track_metadata.get('musicbrainz_release_group_id', '—')[:16] if track_metadata.get('musicbrainz_release_group_id') else '—'}...\n"
                        f"  artist_id    = {track_metadata.get('musicbrainz_artist_id', '—')[:16] if track_metadata.get('musicbrainz_artist_id') else '—'}..."
                    )

            # ── 10. Lyrics ───────────────────────────────────────────────────
            self.logger.info("📜 1️⃣0️⃣ Suche nach Lyrics...")
            lyrics, lyrics_source = (
                await self.lyrics_processor.fetch_lyrics_with_fallback(
                    artist=final_artist,
                    title=clean_title,
                    fallback_artists=feat_artists or [],
                )
            )
            if lyrics:
                self.processing_stats.lyrics_found += 1

            # ── 11a. MB-IDs vorab holen (für Cover) ──────────────────────────
            
            _mb_album_prefetch: Optional[Dict[str, Any]] = None
            _ids_already_known = False  # Default; wird ggf. unten überschrieben
            if not _is_special_channel_pre:
                _ids_already_known = bool(
                    track_metadata.get("musicbrainz_recording_id")
                    or track_metadata.get("musicbrainz_release_id")
                    or track_metadata.get("musicbrainz_release_group_id")
                )
                if _ids_already_known:
                    # IDs kamen aus der Genre-Pipeline → MB-Call überspringen
                    self.logger.info(
                        "🔖 1️⃣1️⃣a MB-IDs bereits aus Genre-Pipeline vorhanden "
                        "→ überspringe zweiten MusicBrainz-Aufruf"
                    )
                    
                else:
                    self.logger.debug(
                        "🔖 1️⃣1️⃣a Hole MB-IDs vorab (noch keine IDs bekannt)..."
                    )
                    _mb_album_prefetch = (
                        await self.album_processor.fetch_album_from_musicbrainz(
                            artist=final_artist,
                            title=search_title_for_genre,
                        )
                    )
                    self.logger.info(
                        f"[DEBUG ALBUM PREFETCH] Rückgabe:\n{_mb_album_prefetch}"
                    )

                    if _mb_album_prefetch:
                        self.logger.info(
                            f"[DEBUG ALBUM PREFETCH] Keys: {list(_mb_album_prefetch.keys())}"
                        )
                    if _mb_album_prefetch:
                        
                        def _pick(*keys):
                            for k in keys:
                                v = _mb_album_prefetch.get(k)
                                if v:
                                    return v
                            return None

                        _rec_id = _pick(
                            "recording_id", "mbid", "musicbrainz_recording_id"
                        )
                        _art_id = _pick("artist_id", "musicbrainz_artist_id")
                        _rel_id = _pick("release_id", "musicbrainz_release_id")
                        _rg_id = _pick(
                            "release_group_id", "musicbrainz_release_group_id"
                        )
                        _isrc = _pick("isrc")

                        track_metadata["musicbrainz_recording_id"] = _rec_id
                        track_metadata["musicbrainz_artist_id"] = _art_id
                        track_metadata["musicbrainz_release_id"] = _rel_id
                        track_metadata["musicbrainz_release_group_id"] = _rg_id
                        track_metadata["isrc"] = _isrc

                        _filled = sum(
                            1 for x in [_rec_id, _art_id, _rel_id, _rg_id] if x
                        )
                        self.logger.info(
                            f"🔖 1️⃣1️⃣a {_filled}/4 MB-IDs in track_metadata geschrieben "
                            f"(rg={(_rg_id or '')[:8] or '–'} artist={(_art_id or '')[:8] or '–'})"
                        )
                        if _rg_id:
                            self.logger.info(
                                f"🎨 Release-Group ID für Fanart.tv Album: {_rg_id[:8]}..."
                            )
                        if _art_id:
                            self.logger.info(
                                f"🎤 Artist ID für Fanart.tv Artist: {_art_id[:8]}..."
                            )

            # ── 11b. Cover-Art ───────────────────────────────────────────────
            self.logger.info("🖼️ 1️⃣1️⃣b Lade Cover-Art...")
            cover_art = track_metadata.get("cover_art")
            cover_source = None

            if cover_art:
                self.processing_stats.cover_art_found += 1
                cover_source = "embedded"
            else:
                
                def _get_mb_id(tm_key: str, prefetch_key: str) -> Optional[str]:
                    return track_metadata.get(tm_key) or (
                        _mb_album_prefetch.get(prefetch_key)
                        if _mb_album_prefetch
                        else None
                    )

                _cover_release_id = _get_mb_id("musicbrainz_release_id", "release_id")
                _cover_release_group_id = _get_mb_id(
                    "musicbrainz_release_group_id", "release_group_id"
                )
                _cover_artist_mbid = _get_mb_id("musicbrainz_artist_id", "artist_id")

                _mb_id_count = sum(
                    1
                    for x in [
                        _cover_release_id,
                        _cover_release_group_id,
                        _cover_artist_mbid,
                    ]
                    if x
                )
                if _mb_id_count:
                    self.logger.info(
                        f"🔖 [COVER] {_mb_id_count}/3 MB-IDs für Cover verfügbar "
                        f"(release={(_cover_release_id or '')[:8] or '–'} "
                        f"rg={(_cover_release_group_id or '')[:8] or '–'})"
                    )
                else:
                    self.logger.debug("🔖 [COVER] Keine MB-IDs → nur YouTube/API-Suche")

                cover_art, cover_source = self.cover_processor.get_cover_art(
                    video_id=video_id,
                    release_id=_cover_release_id,
                    release_group_mbid=_cover_release_group_id,
                    artist_mbid=_cover_artist_mbid,
                    artist_name=final_artist,
                    track_title=clean_title,
                )
                if cover_art:
                    self.processing_stats.cover_art_found += 1
                    self.logger.info(
                        f"🖼️✅ Cover-Art geladen: {clean_title} (Quelle: {cover_source})"
                    )

            # ── 12. Album/Jahr ───────────────────────────────────────────────
            self.logger.info("💿 1️⃣2️⃣ Bestimme Album & Jahr...")
            album_info = self.album_processor.determine_album_info(
                track_metadata=track_metadata,
                playlist_metadata=playlist_metadata,
                final_artist=final_artist,
            )

            # ── 13. Track-Nummer ─────────────────────────────────────────────
            track_number = self.album_processor.determine_track_number(
                track_metadata=track_metadata,
                playlist_metadata=playlist_metadata,
            )

            # ── 14. Dateipfad-Prüfung ────────────────────────────────────────
            source_filepath_str = track_metadata.get("filepath")
            if not source_filepath_str:
                raise ValueError(
                    "❌ Kritischer Schlüssel 'filepath' fehlt in den Metadaten."
                )
            original_path = Path(source_filepath_str)
            if not original_path.exists():
                raise FileNotFoundError(
                    f"❌ Quelldatei nicht gefunden: {original_path}"
                )

            is_single_download = playlist_metadata is None

            # ── 15. Spezialkanal-Logik ───────────────────────────────────────
            is_special_channel = _is_special_channel_pre
            category = _pre_category
            artist_for_filename = final_artist
            artist_for_metadata = final_artist

            if is_special_channel:
                album_info["album_artist"] = _canonical_channel_name
                album_info["album"] = _canonical_channel_name
                if category and category.lower() == "podcast":
                    _playlist_name = (
                        track_metadata.get("playlist_name")
                        or track_metadata.get("playlist_album")
                        or _canonical_channel_name
                    )
                    artist_for_filename = _canonical_channel_name
                    artist_for_metadata = _canonical_channel_name
                    final_artist = _canonical_channel_name
                    album_info["album_artist"] = _canonical_channel_name
                    album_info["album"] = _playlist_name

            elif is_single_download:
                
                _mb_album = _mb_album_prefetch
                if _mb_album is None and _ids_already_known:
                    
                    _mb_album = (
                        await self.album_processor.fetch_album_from_musicbrainz(
                            artist=final_artist,
                            title=search_title_for_genre,
                        )
                        if not track_metadata.get("album")
                        else None
                    )
                if _mb_album and _mb_album.get("album"):
                    album_info["album"] = _mb_album["album"]
                    album_info["year"] = _mb_album.get("year") or album_info.get("year")
                    self.logger.info(
                        f"💿 MusicBrainz Album: {_mb_album['album']!r} ({album_info['year']})"
                    )

                single_album_template = getattr(
                    self.config, "SINGLE_ALBUM_TEMPLATE", "{title} - Single"
                )
                album_info["album"] = single_album_template.format(
                    title=clean_title,
                    artist=final_artist,
                    year=album_info.get("year") or "",
                )
                album_info["album_artist"] = final_artist
                self.logger.info(f"🎯 [SINGLE-MODE] Album: {album_info['album']!r}")

            # --- 15b. Loudness-Normalisierung ---
            self.logger.info("🔊 1️⃣5️⃣b Normalisiere Lautheit (FFmpeg loudnorm)...")
            try:
                from utils.audio_enhancer import AudioEnhancer

                _content_type = (
                    "podcast"
                    if (category and category.lower() == "podcast")
                    else "music"
                )
                _target_lufs = AudioEnhancer.get_target_lufs(_content_type)

                _loudness_ok = AudioEnhancer.normalize_loudness(
                    str(original_path),
                    target_lufs=_target_lufs,
                )
                if _loudness_ok:
                    self.logger.info(
                        f"🔊✅ Loudness normalisiert auf {_target_lufs} LUFS "
                        f"({_content_type}): {original_path.name}"
                    )
                else:
                    self.logger.warning(
                        f"🔊⚠️ Loudness-Normalisierung fehlgeschlagen (nicht kritisch): "
                        f"{original_path.name}"
                    )
            except ImportError:
                self.logger.debug(
                    "🔊 AudioEnhancer nicht verfügbar – Loudness-Normalisierung übersprungen"
                )
            except Exception as _loud_err:
                self.logger.warning(
                    f"🔊⚠️ Loudness-Normalisierung Fehler (nicht kritisch): {_loud_err}"
                )

            # ── 16. Datei verschieben ────────────────────────────────────────
            self.logger.info("📂 1️⃣6️⃣ Verschiebe Datei in die Bibliothek...")
            library_path = filename_fixer.move_to_library(
                source_path=original_path,
                artist=artist_for_filename,
                album=album_info.get("album"),
                title=clean_title,
                year=album_info.get("year"),
                track_number=track_number,
                is_single=is_single_download,
                uploader=_canonical_channel_name,
            )

            # ── 17. Metadaten schreiben ──────────────────────────────────────
            self.logger.info("📝 1️⃣7️⃣ Schreibe Metadaten-Tags...")
            self.tag_writer.write_tags(
                target_path=library_path,
                artist=artist_for_metadata,
                album_info=album_info,
                title=clean_title,
                track_number=track_number,
                genres_result=genres_result,
                lyrics=lyrics,
                cover_art=cover_art,
                feat_artists=feat_artists,
                mb_ids={
                    "recording_id": track_metadata.get("musicbrainz_recording_id"),
                    "artist_id": track_metadata.get("musicbrainz_artist_id"),
                    "release_id": track_metadata.get("musicbrainz_release_id"),
                    "release_group_id": track_metadata.get(
                        "musicbrainz_release_group_id"
                    ),
                    "isrc": track_metadata.get("isrc"),
                },
            )

            # ── 18. Ergebnis erstellen ───────────────────────────────────────
            result = MetadataResult(
                success=True,
                title=clean_title,
                artist=artist_for_metadata,
                album=album_info.get("album"),
                album_artist=album_info.get("album_artist"),
                year=album_info.get("year"),
                track_number=track_number,
                lyrics=lyrics,
                lyrics_source=lyrics_source,
                cover_art=cover_art,
                cover_embedded=bool(cover_art),
                genres=(
                    {
                        "primary": genres_result.primary,
                        "secondary": genres_result.secondary,
                    }
                    if genres_result and genres_result.primary
                    else None
                ),
                genre_source=genres_result.source if genres_result else None,
                filepath=original_path,
                library_path=library_path,
                original_metadata=track_metadata,
                artist_source=artist_source,
                title_cleaned=clean_title != raw_title,
                is_duplicate=is_duplicate,
                from_cache=False,
                # MusicBrainz IDs – aus track_metadata übernehmen (wurden in
                # Schritt 9b und/oder 11a befüllt)
                mb_recording_id=track_metadata.get("musicbrainz_recording_id"),
                mb_artist_id=track_metadata.get("musicbrainz_artist_id"),
                mb_release_id=track_metadata.get("musicbrainz_release_id"),
                mb_release_group_id=track_metadata.get("musicbrainz_release_group_id"),
                mb_isrc=track_metadata.get("isrc"),
            )
            _mb_count = sum(
                1
                for f in [
                    result.mb_recording_id,
                    result.mb_artist_id,
                    result.mb_release_id,
                    result.mb_release_group_id,
                ]
                if f
            )
            if _mb_count:
                self.logger.info(
                    f"🔖 MetadataResult enthält {_mb_count}/4 MusicBrainz-IDs "
                    f"(recording={( result.mb_recording_id or '')[:8] or '–'})"
                )

            # ── 19. Cache speichern ──────────────────────────────────────────
            self.cache_handler.store(result, dominant_artist, cover_source=cover_source)

            # ── 19b. Auto-Learning ───────────────────────────────────────────
            if genres_result and genres_result.primary:
                genre_source = getattr(genres_result, "source", "unknown")
                auto_learn_disabled = getattr(
                    genres_result, "auto_learn_disabled", False
                )
                if (
                    genre_source not in ("none", "unknown")
                    and not auto_learn_disabled
                    and not self.auto_learn_manager._is_genre_already_learned(
                        final_artist
                    )
                ):
                    genre_info = self.auto_learn_manager.create_genre_info_from_result(
                        genres_result
                    )
                    try:
                        await self.auto_learn_manager.learn_genre(
                            canonical_name=final_artist,
                            genre_result=genre_info,
                            raw_name=(
                                track_metadata.get("uploader")
                                or track_metadata.get("artist")
                                or final_artist
                            ),
                        )
                    except Exception as _learn_err:
                        self.logger.warning(
                            f"⚠️ Genre-Learning fehlgeschlagen: {_learn_err}"
                        )

            _learn_sources = {
                "youtube_parsed",
                "raw_metadata",
                "channel_fallback",
                "first_artist_from_title",
            }
            # AUTOLEARN-001: _is_podcast_channel prueft nur eine hartcodierte
            # 2-Kanal-Liste. download_utils.py hatte zusaetzlich einen externen,
            # redundanten learn_artist()-Aufruf mit einer breiteren Pruefung
            # ueber die vollstaendige special_channel.yaml-Konfiguration
            # (get_special_category/load_special_channels_merged) - dieser
            # externe Aufruf verhinderte fuer SEINEN eigenen zweiten Versuch
            # das Lernen bei Sonderkanaelen ausserhalb der 2 hartcodierten
            # Namen, liess die Luecke im internen Aufruf hier aber bestehen.
            # Erweitert die Ausschlussmenge (nur zusaetzlich einschraenkend,
            # nie lockernd) um dieselbe breite Pruefung.
            _is_special_channel_for_learning = _is_podcast_channel or bool(
                get_special_category(
                    _channel_for_special_detection,
                    load_special_channels_merged(self.config),
                )
            )
            if artist_source in _learn_sources and not _is_special_channel_for_learning:
                try:
                    await self.auto_learn_manager.learn_artist(
                        raw_name=track_metadata.get("uploader")
                        or track_metadata.get("artist")
                        or "",
                        canonical_name=artist_for_metadata,
                        source=artist_source,
                        channel_name=track_metadata.get("channel", "")
                        or track_metadata.get("uploader", ""),
                    )
                except Exception as _learn_err:
                    self.logger.warning(
                        f"⚠️ Artist-Learning fehlgeschlagen: {_learn_err}"
                    )

            # --- 20. Abschluss ---
            self.logger.info(
                f"🎉 2️⃣0️⃣ Track erfolgreich verarbeitet: '{artist_for_metadata}' - '{clean_title}'"
            )
            return result

        except Exception as e:
            self.logger.error(
                f"💥 Fehler bei Metadatenverarbeitung: {e}", exc_info=True
            )
            # ARCH-005 (Temp-Cleanup) Strategie C: raeumt die konkret
            # gescheiterte Download-Datei gezielt auf, statt sie fuer immer
            # in Config.DOWNLOAD_DIR liegen zu lassen (vorher: kein
            # einziger Cleanup-Aufruf in der gesamten Pipeline). No-op,
            # falls original_path None ist, bereits verschoben wurde
            # (move_to_library() lief schon) oder ausserhalb DOWNLOAD_DIR
            # liegt.
            cleanup_single_download_artifact(
                original_path, getattr(self.config, "DOWNLOAD_DIR", None), self.logger
            )
            return MetadataResult(
                success=False,
                title=track_metadata.get("title", "Fehler"),
                artist="Unbekannt",
                error=str(e),
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Genre-Bestimmung mit Statistik (delegiert an GenreProcessor)
    # ─────────────────────────────────────────────────────────────────────────

    async def _determine_genre_with_stats(
        self,
        track_metadata: Dict[str, Any],
        artist_name: str,
        channel_name: str,
        canonical_channel_name=None,
        is_special_channel: bool = False,
        feat_artists=None,
        clean_title: str = None,
    ):
        # Lazy-Init MB/LFM Clients
        if self._mb_client is None:
            from services.clients.musicbrainz_client import MusicBrainzClient

            self._mb_client = MusicBrainzClient()

        if self._lfm_client is None:
            from services.clients.lastfm_client import LastFMClient

            self._lfm_client = LastFMClient()

        result = await self.genre_processor.determine_genre_with_fallbacks(
            track_metadata=track_metadata,
            artist_name=artist_name,
            channel_name=channel_name,
            canonical_channel_name=canonical_channel_name,
            is_special_channel=is_special_channel,
            feat_artists=feat_artists,
            clean_title=clean_title,
            mb_client=self._mb_client,
            lfm_client=self._lfm_client,
        )

        if result and (
            result.primary or (hasattr(result, "secondary") and result.secondary)
        ):
            self.processing_stats.successful_genre_mappings += 1

        return result

    async def _fetch_album_info_from_musicbrainz(
        self, artist: str, title: str
    ) -> Optional[Dict[str, Any]]:
        """Delegiert an AlbumProcessor."""
        return await self.album_processor.fetch_album_from_musicbrainz(artist, title)

    # ─────────────────────────────────────────────────────────────────────────
    # Delegate-Methoden (für Abwärtskompatibilität)
    # ─────────────────────────────────────────────────────────────────────────

    def _clean_track_title_enhanced(
        self,
        original_title: str,
        parsed_title: Optional[str],
        parsed_artist: Optional[str],
        final_artist: str,
        was_parsed_by_artist_map: bool = False,
        dominant_artist: Optional[str] = None,
        channel_name: Optional[str] = None,
    ) -> str:
        return self.title_cleaner.clean_track_title_enhanced(
            original_title=original_title,
            parsed_title=parsed_title,
            parsed_artist=parsed_artist,
            final_artist=final_artist,
            was_parsed_by_artist_map=was_parsed_by_artist_map,
            dominant_artist=dominant_artist,
            channel_name=channel_name,
        )

    def _build_search_title(
        self,
        parsed_title: Optional[str],
        original_title: str,
        final_artist: str,
    ) -> str:
        return self.title_cleaner.build_search_title(
            parsed_title=parsed_title,
            original_title=original_title,
            final_artist=final_artist,
        )

    def _should_remove_leading_fragment(
        self,
        leading: str,
        rest: str,
        final_artist: str,
        parsed_artist: Optional[str],
        channel_name: Optional[str],
    ) -> bool:
        return self.title_cleaner.should_remove_leading_fragment(
            leading=leading,
            rest=rest,
            final_artist=final_artist,
            parsed_artist=parsed_artist,
            channel_name=channel_name,
        )

    def _apply_title_cleanup_rules(self, title: str) -> str:
        return self.title_cleaner.apply_title_cleanup_rules(title)

    def _remove_artist_from_title(self, title: str, artist: str) -> str:
        return self.title_cleaner.remove_artist_from_title(title, artist)

    def _check_metadata_cache(
        self,
        track_metadata: Dict,
        dominant_artist: Optional[str],
        final_artist: Optional[str] = None,
        clean_title: Optional[str] = None,
    ) -> Optional[MetadataResult]:
        return self.cache_handler.check(
            track_metadata=track_metadata,
            dominant_artist=dominant_artist,
            final_artist=final_artist,
            clean_title=clean_title,
        )

    def _store_in_metadata_cache(
        self, result, dominant_artist, cover_source: str = None
    ) -> None:
        self.cache_handler.store(result, dominant_artist, cover_source=cover_source)

    def _determine_best_artist_corrected(
        self,
        raw_artist: str,
        parsed_artist: str,
        dominant_artist: str,
        channel_name: str,
    ) -> Tuple[str, str, List[str]]:
        return self.artist_processor.determine_best_artist(
            raw_artist=raw_artist,
            parsed_artist=parsed_artist,
            dominant_artist=dominant_artist,
            channel_name=channel_name,
        )

    def _find_known_artist_from_list(self, all_artists: List[str]) -> Optional[str]:
        return self.artist_processor.find_known_artist_from_list(all_artists)

    def _clean_artist_before_normalization(self, artist: str) -> str:
        return self.artist_processor.clean_artist_before_normalization(artist)

    def _prioritize_genres(
        self, tags: List[str], artist_name: Optional[str] = None
    ) -> Tuple[str, List[str]]:
        return self.genre_processor.prioritize_genres(tags, artist_name=artist_name)

    def _normalize_genre_name(self, genre: str) -> str:
        return self.genre_processor.normalize_genre_name(genre)

    def _determine_album_info(
        self,
        track_metadata: Dict,
        playlist_metadata: Optional[Dict],
        final_artist: str,
    ) -> Dict[str, Any]:
        return self.album_processor.determine_album_info(
            track_metadata=track_metadata,
            playlist_metadata=playlist_metadata,
            final_artist=final_artist,
        )

    def _determine_track_number(
        self, track_metadata: Dict, playlist_metadata: Optional[Dict]
    ) -> Optional[int]:
        return self.album_processor.determine_track_number(
            track_metadata=track_metadata,
            playlist_metadata=playlist_metadata,
        )

    def _extract_year_from_string(self, text: str) -> Optional[int]:
        return self.album_processor.extract_year_from_string(text)

    # ─────────────────────────────────────────────────────────────────────────
    # Config-Hilfsmethode
    # ─────────────────────────────────────────────────────────────────────────

    def _get_default_config(self):
        class DefaultConfig:
            LIBRARY_DIR = Path("./music_library")
            ARTIST_OVERRIDE_FILE = Path("./artist_overrides.json")
            GENRE_MAPPING_DIR = "mapping"
            METADATA_CACHE_DIR = "metadata_cache"
            ENHANCED_METADATA_PROCESSING = True
            FANART_API_KEY = ""

        return DefaultConfig()
