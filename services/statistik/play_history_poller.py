# services/statistik/play_history_poller.py
# -*- coding: utf-8 -*-
"""
PlayHistoryPoller – Hintergrund-Polling gegen Navidrome, um "now playing"
in den Wiedergabeverlauf zu übernehmen.

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich das periodische Abfragen von NavidromeAPI.get_now_playing()
    und Übergabe neuer Einträge an das PlayHistoryRepository.
  - KEINE Statistik-Berechnung, KEIN Chart-Rendering.

Dependency Injection:
  - `navidrome_api` und `repository` werden injiziert (kein Singleton-Zugriff,
    keine eigene Konstruktion externer Abhängigkeiten).

Extrahiert aus services/statistik_service.py (ARCH-003, P-6) - 1:1
übernommene Logik, keine Verhaltensänderung.
"""

import asyncio
from datetime import datetime
from typing import Optional

from logger import get_module_logger

from services.statistik.play_history_repository import PlayHistoryRepository


class PlayHistoryPoller:
    """Pollt Navidrome periodisch und schreibt neue Wiedergaben in die History."""

    def __init__(self, navidrome_api, repository: PlayHistoryRepository, logger=None):
        self.api = navidrome_api
        self.repository = repository
        self.logger = logger or get_module_logger("PlayHistoryPoller")
        self._polling_task: Optional[asyncio.Task] = None

    def start_polling(self):
        if self._polling_task and not self._polling_task.done():
            self.logger.warning("Polling-Task läuft bereits.")
            return

        self.logger.info("Starte Hintergrund-Task für History-Updates...")
        self._polling_task = asyncio.create_task(self._run_history_updater())

    async def stop_polling(self):
        if self._polling_task and not self._polling_task.done():
            self.logger.info("Stoppe Hintergrund-Task...")
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                self.logger.info("Hintergrund-Task erfolgreich gestoppt.")
        self._polling_task = None

    async def _run_history_updater(self):
        from config import Config

        interval_seconds = Config.PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN * 60

        if interval_seconds < 60:
            self.logger.warning(
                f"Polling-Intervall ({interval_seconds}s) ist sehr kurz. "
                "Setze auf 60s, um Ratenbegrenzungen zu vermeiden."
            )
            interval_seconds = 60

        self.logger.info(
            f"🔄 History Updater gestartet. Intervall: {interval_seconds} Sekunden."
        )

        await asyncio.sleep(10)

        while True:
            try:
                self.logger.debug("Polling: Rufe update_play_history auf...")
                await self.update_play_history()
                self.logger.debug(
                    f"Polling: Warte {interval_seconds}s bis zur nächsten Aktualisierung."
                )

            except Exception as e:
                self.logger.error(f"❌ Fehler im History Updater: {e}", exc_info=True)

            await asyncio.sleep(interval_seconds)

    async def update_play_history(self) -> bool:
        """
        Ruft ALLE aktuell gespielten Titel ab und fügt sie dem
        jeweiligen Benutzer-Wiedergabeverlauf hinzu.
        """
        try:
            self.logger.debug(
                "🔄 Starte Aktualisierung des Wiedergabeverlaufs (für alle Benutzer)..."
            )

            all_now_playing_data = await self.api.get_now_playing()

            if not all_now_playing_data:
                self.logger.debug(
                    "⏸️ Keine aktuellen Wiedergabedaten von Navidrome erhalten."
                )
                return False

            new_entries_added = False

            for play_data in all_now_playing_data:
                song_info = play_data.get("song")
                navidrome_username = play_data.get("user")

                if (
                    not song_info
                    or not navidrome_username
                    or navidrome_username == "Unbekannter Nutzer"
                ):
                    self.logger.warning(
                        f"Überspringe Eintrag ohne Song oder Benutzer: {play_data}"
                    )
                    continue

                history_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "tracks": [
                        {
                            "title": song_info.get("title", "N/A"),
                            "artist": song_info.get("artist", "N/A"),
                            "album": song_info.get("album", "N/A"),
                            "id": song_info.get("id", "N/A"),
                            "duration": song_info.get("duration", None),
                            "player": play_data.get("player", "N/A"),
                            "username": navidrome_username,
                        }
                    ],
                }

                history = self.repository.load(navidrome_username)

                if history:
                    last_entry = history[-1]
                    if "tracks" in last_entry and last_entry["tracks"]:
                        last_song_id = last_entry["tracks"][0].get("id")
                        current_song_id = song_info.get("id")
                        if last_song_id == current_song_id:
                            self.logger.debug(
                                f"Song '{song_info.get('title')}' spielt bei '{navidrome_username}' noch, "
                                "kein neuer Eintrag."
                            )
                            continue

                history.append(history_entry)
                self.repository.save(history, navidrome_username)

                self.repository.cleanup_old_entries(navidrome_username)

                song_title = history_entry["tracks"][0]["title"]
                artist_name = history_entry["tracks"][0]["artist"]
                self.logger.info(
                    f"✅ '{song_title}' von '{artist_name}' zum Verlauf von "
                    f"'{navidrome_username}' hinzugefügt."
                )
                new_entries_added = True

            return new_entries_added

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Aktualisieren des Wiedergabeverlaufs: {e}",
                exc_info=True,
            )
            return False
