# downloader.py

from logger import get_module_logger
from services.downloader.download_utils import (
    enhanced_download_with_retry,
)
from config import Config
from cookie_handler import CookieHandler
from utils.filenamefixer import FilenameFixerTool
from services.downloader.download_utils import EnhancedDownloadProcessor


class YoutubeDownloader:
    def __init__(
        self,
        update,
        config: Config,
        cookie_handler: CookieHandler,
        # ... andere Parameter
    ):
        self.update = update
        self.config = config
        self.cookie_handler = cookie_handler

        self._logger_factory = get_module_logger
        self.logger = self._logger_factory("YoutubeDownloader")

        self.enhanced_download_processor = EnhancedDownloadProcessor(
            config=self.config,
            logger_factory=self._logger_factory,
        )
        self.filename_fixer = FilenameFixerTool(
            config, logger_factory=self._logger_factory
        )
        self.logger.info("YoutubeDownloader initialisiert")

    async def download_audio(self, url: str):
        """
        Lädt ein Video oder eine Playlist herunter und stellt sicher,
        dass das Ergebnis im m4a-Format vorliegt.
        """
        self.logger.info("1️⃣ 📥 Starte Download-Prozess...")
        try:
            self.logger.info(
                f"4️⃣ ⏬ Starte `enhanced_download_with_retry` für URL: {url}"
            )
            download_result = await enhanced_download_with_retry(
                url=url,
                chat_id=self.update.effective_chat.id,
                update_id=self.update.update_id,
                logger_factory=self._logger_factory,
            )

            self.logger.info(
                "5️⃣ 📦 Download abgeschlossen – extrahiere Ergebnis und Statistiken"
            )
            if not download_result or not download_result.get("success"):
                error_message = download_result.get("error", "Unbekannter Fehler.")
                self.logger.error(f"❌ Download fehlgeschlagen: {error_message}")
                return {"success": False, "error": error_message}

            processor = download_result.get("processor_instance")
            processing_stats = (
                processor.get_processing_statistics() if processor else {}
            )
            if processor:
                self.logger.info("📊 Verarbeitungsstatistiken erfolgreich extrahiert.")
            else:
                self.logger.warning(
                    "⚠️ Prozessor-Instanz nicht gefunden, keine Statistiken."
                )

            # ✅ KORRIGIERT: Das finale Ergebnisobjekt wird um die Track-Infos erweitert
            final_result = {
                "success": True,
                "type": download_result.get("type"),
                "processing_stats": processing_stats,
            }

            if download_result.get("type") == "playlist":
                tracks = download_result.get("tracks", [])
                final_result["tracks"] = tracks
                final_result["title"] = download_result.get(
                    "playlist_title", "Playlist"
                )  # Titel für Handler
                self.logger.info(
                    f"✅ Playlist-Download mit {len(tracks)} Tracks abgeschlossen."
                )
            else:
                track_info = download_result.get("track_info", {})
                final_result["track_info"] = track_info

                # 1. Füge alle Track-Infos zur final_result hinzu
                # Dadurch werden alle Basis-Schlüssel kopiert, auch der evtl. unsaubere 'cover_embedded'-Schlüssel
                final_result.update(track_info)  # <-- MUSS HIER STEHEN

                # 2. ÜBERSCHREIBE den 'cover_embedded'-Wert mit dem normalisierten, klaren Boolean
                cover_status = track_info.get("cover_embedded") or track_info.get(
                    "cover_found", False
                )
                final_result["cover_embedded"] = bool(
                    cover_status
                )  # <-- MUSS HIER STEHEN

                self.logger.info(
                    f"✅ Single-Download abgeschlossen. Finaler Cover-Status: {final_result['cover_embedded']}"
                )
                # Die Zeile `self.logger.info(f"✅ Single-Download abgeschlossen.")` ist redundant und kann entfallen.

            self.logger.info(
                "6️⃣ Übergabe des vollständigen Ergebnisses an den `DownloadHandler`"
            )
            return final_result

        except Exception as e:
            self.logger.error(
                f"💥 Kritischer Fehler in `download_audio()`: {e}", exc_info=True
            )
            raise
