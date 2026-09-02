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
    """
    services/-Schicht: haelt bewusst KEIN Telegram-Update-Objekt (siehe
    docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md) - chat_id/
    update_id werden als einfache Werte entgegengenommen, exakt wie von
    enhanced_download_with_retry() (download_utils.py) und dem
    DownloadCoordinator-Protocol (download/interfaces.py) bereits
    erwartet. Der Aufrufer (klassen/download_handler.py, oberhalb der
    services/-Schicht) extrahiert diese Werte aus dem eigenen
    Telegram-Update-Objekt.
    """

    def __init__(
        self,
        chat_id: int,
        update_id: int,
        config: Config,
        cookie_handler: CookieHandler,
        duplicate_detector=None,
        status_callback=None,
        active_download=None,
        # ... andere Parameter
    ):
        self.chat_id = chat_id
        self.update_id = update_id
        self.config = config
        self.cookie_handler = cookie_handler
        # Live-Fund 2026-09-02: wird nur fuer die Pro-Track-Duplikatpruefung
        # innerhalb von Playlist-Downloads gebraucht (siehe
        # _process_playlist_download() in download_utils.py) - optional,
        # damit Aufrufer ohne eigenen DuplicateDetector (z.B. isolierte
        # Tests) unveraendert funktionieren.
        self.duplicate_detector = duplicate_detector
        # Playlist-Progress-State 2026-09-02 (Nutzer-Wunsch): optionaler
        # async Callable, wird von _process_playlist_download() pro Track
        # mit dem ProgressTracker (reiner Zustand, siehe dort) aufgerufen -
        # bleibt bewusst ein opakes Callable ohne Telegram-Typ in dieser
        # Schicht (services/), exakt wie duplicate_detector oben. Der
        # Aufrufer (klassen/download_handler.py) uebergibt eine an sich
        # selbst gebundene Methode, die dort die Telegram-Formatierung und
        # den eigentlichen Versand uebernimmt.
        self.status_callback = status_callback
        # Download-Control-Center 2026-09-02: optional ein
        # services.downloader.active_downloads.ActiveDownload - liefert
        # den geteilten ProgressTracker sowie das cancel_event fuer den
        # ❌ Abbrechen-Button. Bleibt wie duplicate_detector/status_callback
        # ein opakes Objekt ohne Telegram-Typ in dieser Schicht.
        self.active_download = active_download

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
                chat_id=self.chat_id,
                update_id=self.update_id,
                logger_factory=self._logger_factory,
                duplicate_detector=self.duplicate_detector,
                status_callback=self.status_callback,
                active_download=self.active_download,
            )

            self.logger.info(
                "5️⃣ 📦 Download abgeschlossen – extrahiere Ergebnis und Statistiken"
            )
            if not download_result or not download_result.get("success"):
                # docs/FINDINGS_INDEX.md: "if not download_result" faengt
                # download_result=None zwar ab, das direkt folgende
                # .get(...) im selben Zweig tat das vorher nicht -
                # AttributeError statt eines sauberen Fehler-Dicts. In der
                # Praxis liefert enhanced_download_with_retry() laut
                # eigenem Vertrag (docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md)
                # nie None, daher kein akuter Produktionsfehler bisher -
                # trotzdem ein sauberer Guard statt eines impliziten
                # Vertrauens auf diese Garantie.
                error_message = (
                    download_result.get("error", "Unbekannter Fehler.")
                    if download_result
                    else "Unbekannter Fehler."
                )
                cancelled = bool(download_result.get("cancelled")) if download_result else False
                if cancelled:
                    self.logger.info("🛑 Download abgebrochen (Nutzeranfrage)")
                else:
                    self.logger.error(f"❌ Download fehlgeschlagen: {error_message}")
                return {"success": False, "error": error_message, "cancelled": cancelled}

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
                "duration_seconds": download_result.get("duration_seconds"),
                "cancelled": bool(download_result.get("cancelled")),
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
