# services/downloader/utils/metadata_utils.py - Erweiterte Version

from pathlib import Path
import shutil
from mutagen.easyid3 import EasyID3
from mutagen.mp4 import MP4
import asyncio
from typing import Optional, Dict, Any

from config import Config
from enhanced_logging import get_module_logger  # NUR DAS!
from services.downloader.utils.error_handler import FileProcessingError
from services.downloader.utils.file_utils import FileUtils
from utils.filenamefixer import FilenameFixerTool
from metadata import process_metadata, write_metadata
from utils.helpers import sanitize_filename
from services.downloader.utils.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)

# Logger für dieses Modul - MIT KORREKTEM NAMEN!
logger = get_module_logger("MetadataProcessor")


class MetadataProcessor:
    def __init__(self):
        self.enhanced_processor = EnhancedMetadataProcessor()

    async def process_single_track(
        self,
        track_metadata: Dict[str, Any],
        file_utils: FileUtils,
        filename_fixer: FilenameFixerTool,
        playlist_metadata: Optional[Dict] = None,
        dominant_artist: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Wrapper für Kompatibilität mit bestehendem Code"""

        result = await self.enhanced_processor.process_single_track(
            track_metadata=track_metadata,
            file_utils=file_utils,
            filename_fixer=filename_fixer,
            playlist_metadata=playlist_metadata,
            dominant_artist=dominant_artist,
        )

        # Konvertiere zu kompatiblem Format
        return {
            "success": result.success,
            "title": result.title,
            "artist": result.artist,
            "album": result.album,
            "album_artist": result.album_artist,
            "year": result.year,
            "track_number": result.track_number,
            "genres": result.genres,
            "final_path": str(result.filepath) if result.filepath else None,
            "library_path": str(result.library_path) if result.library_path else None,
            "error": result.error,
        }

    async def process_and_write_metadata(
        self, source_path: Path, dest_path: Path, metadata: dict
    ) -> None:
        """Verschiebt Datei & schreibt Metadaten."""
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(dest_path))
            await write_metadata(str(dest_path), metadata, str(dest_path))
        except Exception as e:
            logger.error(
                f"❌ Fehler beim Verschieben oder Schreiben von Metadaten: {e}"
            )
            raise FileProcessingError(
                f"Fehler beim Verschieben oder Schreiben von Metadaten: {e}"
            )

    async def _write_fallback_metadata(
        self,
        file_path: Path,
        info: dict,
        metadata: dict,
        is_playlist_track: bool = False,
    ) -> dict:
        """🩹 Erweiterte Fallback-Metadaten schreiben mit Playlist-Support"""
        logger.info(f"🩹 Starte erweiterten Fallback-Prozess für: {file_path.name}")

        try:
            fallback_title = metadata.get("title") or info.get(
                "title", "Unbekannter Titel"
            )
            fallback_artist = (
                metadata.get("artist")
                or info.get("artist")
                or info.get("uploader", "Unbekannter Künstler")
            )

            # 🆕 NEU: Erweiterte Fallback-Metadaten
            meta_to_write = {
                "title": fallback_title,
                "artist": fallback_artist,
                "album": metadata.get("album", fallback_title),
                "album_artist": metadata.get("album_artist", fallback_artist),
                "year": metadata.get("year"),
                "track_number": metadata.get("track_number", 1),
                "main_genre": metadata.get("main_genre", "Unknown"),
            }

            if not meta_to_write["year"] and info.get("upload_date"):
                meta_to_write["year"] = int(info["upload_date"][:4])

            suffix = file_path.suffix.lower()

            logger.info(f"✏️ Schreibe Fallback-Metadaten für Dateityp: {suffix}")
            logger.debug(f"📋 Fallback-Daten: {meta_to_write}")

            # Mutagen schreiben
            if suffix in [".m4a", ".mp4"]:
                audio = MP4(str(file_path))
                if meta_to_write["title"]:
                    audio["©nam"] = meta_to_write["title"]
                if meta_to_write["artist"]:
                    audio["©ART"] = meta_to_write["artist"]
                if meta_to_write["album"]:
                    audio["©alb"] = meta_to_write["album"]
                if meta_to_write["album_artist"]:
                    audio["aART"] = meta_to_write["album_artist"]
                if meta_to_write["year"]:
                    audio["©day"] = str(meta_to_write["year"])
                if meta_to_write["track_number"]:
                    audio["trkn"] = [(int(meta_to_write["track_number"]), 0)]
                if meta_to_write["main_genre"]:
                    audio["©gen"] = meta_to_write["main_genre"]
                audio.save()

            elif suffix == ".mp3":
                audio = EasyID3(str(file_path))
                if meta_to_write["title"]:
                    audio["title"] = meta_to_write["title"]
                if meta_to_write["artist"]:
                    audio["artist"] = meta_to_write["artist"]
                if meta_to_write["album"]:
                    audio["album"] = meta_to_write["album"]
                if meta_to_write["album_artist"]:
                    audio["albumartist"] = meta_to_write["album_artist"]
                if meta_to_write["year"]:
                    audio["date"] = str(meta_to_write["year"])
                if meta_to_write["track_number"]:
                    audio["tracknumber"] = str(meta_to_write["track_number"])
                if meta_to_write["main_genre"]:
                    audio["genre"] = meta_to_write["main_genre"]
                audio.save()

            logger.info("✔️ Fallback-Metadaten erfolgreich geschrieben.")

            # 🆕 NEU: Erweiterte Rückgabe mit Playlist-Kontext
            return {
                "success": True,
                "final_path": str(file_path),
                "title": meta_to_write["title"],
                "artist": meta_to_write["artist"],
                "album": meta_to_write["album"],
                "album_artist": meta_to_write["album_artist"],
                "track_number": meta_to_write["track_number"],
                "year": meta_to_write["year"],
                "genres": metadata.get("genres", []),
                "main_genre": meta_to_write.get("main_genre", "Unknown"),
                "is_single": not is_playlist_track,
                "is_playlist_track": is_playlist_track,
                "fallback_used": True,
            }

        except Exception as e:
            logger.error(
                f"❌ Schwerwiegender Fehler beim Schreiben von Fallback-Metadaten: {e}"
            )
            return {
                "success": False,
                "error": str(e),
                "final_path": str(file_path),
                "is_single": not is_playlist_track,
                "is_playlist_track": is_playlist_track,
                "fallback_used": True,
            }
