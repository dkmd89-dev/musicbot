# services/metadata/album_processor.py
# -*- coding: utf-8 -*-

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from logger import get_module_logger


class AlbumProcessor:
    """
    Verantwortlich für Album-Informationen, Track-Nummern und Jahr-Extraktion.
    Optional mit MusicBrainz-Client für erweiterte Album-Suche.
    """

    def __init__(self, logger=None, mb_client=None):
        self.logger = logger or get_module_logger("AlbumProcessor")
        self._mb_client = mb_client

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def determine_album_info(
        self,
        track_metadata: Dict,
        playlist_metadata: Optional[Dict],
        final_artist: str,
    ) -> Dict[str, Any]:
        """
        Bestimmt Album-Name, Album-Artist und Jahr aus Track- und Playlist-Metadaten.
        Priorität: playlist_metadata > track_metadata > upload_date.
        Gibt Dict mit keys: album, album_artist, year zurück.
        """
        self.logger.debug("💿 Album-Informationen bestimmen...")
        album_info: Dict[str, Any] = {
            "album": None,
            "album_artist": final_artist,
            "year": None,
        }

        album_candidates = [
            playlist_metadata.get("album") if playlist_metadata else None,
            track_metadata.get("album"),
            (
                track_metadata.get("playlist_title")
                if track_metadata.get("is_playlist_track")
                else None
            ),
        ]

        for candidate in album_candidates:
            if candidate and len(str(candidate).strip()) > 1:
                album_info["album"] = str(candidate).strip()
                break

        year_candidates = [
            playlist_metadata.get("year") if playlist_metadata else None,
            track_metadata.get("year"),
            track_metadata.get("release_year"),
            self.extract_year_from_string(track_metadata.get("upload_date", "")),
        ]

        for year in year_candidates:
            if year and isinstance(year, (int, str)):
                try:
                    year_int = int(year)
                    if 1950 <= year_int <= datetime.now().year:
                        album_info["year"] = year_int
                        break
                except (ValueError, TypeError):
                    continue

        if playlist_metadata and playlist_metadata.get("album_artist"):
            album_info["album_artist"] = playlist_metadata["album_artist"]

        if album_info["year"] is None:
            album_info["year"] = datetime.now().year
            self.logger.debug("💿 Kein Jahr gefunden, verwende aktuelles Jahr.")

        self.logger.debug(f"💿✅ Album-Info: {album_info}")
        return album_info

    def determine_track_number(
        self,
        track_metadata: Dict,
        playlist_metadata: Optional[Dict],
    ) -> Optional[int]:
        """
        Bestimmt die Track-Nummer aus Playlist- oder Track-Metadaten.
        Akzeptiert Werte zwischen 1 und 999.
        """
        self.logger.debug("🔢 Track-Nummer bestimmen...")
        candidates = [
            playlist_metadata.get("track_number") if playlist_metadata else None,
            track_metadata.get("track_number"),
            track_metadata.get("playlist_position"),
        ]

        for candidate in candidates:
            if candidate and isinstance(candidate, (int, str)):
                try:
                    track_num = int(candidate)
                    if 1 <= track_num <= 999:
                        self.logger.debug(f"🔢✅ Track-Nummer: {track_num}")
                        return track_num
                except (ValueError, TypeError):
                    continue

        self.logger.debug("🔢❌ Keine Track-Nummer gefunden.")
        return None

    def extract_year_from_string(self, text: str) -> Optional[int]:
        """
        Extrahiert eine vierstellige Jahreszahl (1950–heute) aus einem String.
        Nützlich für upload_date im Format YYYYMMDD.
        """
        if not text:
            return None
        year_match = re.search(r"(19|20)\d{2}", str(text))
        if year_match:
            year = int(year_match.group())
            if 1950 <= year <= datetime.now().year:
                return year
        return None

    async def fetch_album_from_musicbrainz(
        self,
        artist: str,
        title: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Holt Album-Name und Jahr von MusicBrainz für einen Track.
        Gibt None zurück wenn kein Ergebnis oder ein Fehler auftritt.
        Lazy-initialisiert den MusicBrainz-Client falls nicht gesetzt.
        """
        try:
            if self._mb_client is None:
                from services.clients.musicbrainz_client import MusicBrainzClient
                self._mb_client = MusicBrainzClient()

            self.logger.debug(f"💿 MusicBrainz Album-Suche: {artist!r} - {title!r}")
            mb_data = await self._mb_client.fetch_metadata(title, artist)

            if not mb_data:
                return None

            album = mb_data.get("album") or mb_data.get("release")
            year = mb_data.get("year") or mb_data.get("release_year")

            if album and len(album.strip()) > 1:
                return {"album": album.strip(), "year": year}
            return None

        except Exception as e:
            self.logger.debug(f"💿 MusicBrainz Album-Suche fehlgeschlagen: {e}")
            return None
