# services/statistik_service.py

import json
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

import matplotlib.pyplot as plt

from api.navidrome_api import NavidromeAPI
from config import Config
from logger import get_module_logger


class StatistikService:
    """
    Dieser Service kümmert sich um die Erfassung, Speicherung und Analyse von
    Wiedergabestatistiken.

    NEU: Statistiken werden pro Navidrome-Benutzer gespeichert.
    """

    # Verzeichnis für Diagramme
    CHARTS_DIR = Config.STATS_DIR

    # Basis-Verzeichnis für Benutzer-Verlaufsdateien
    USER_HISTORY_DIR = Config.PLAY_HISTORY_FILE

    def __init__(self):
        """
        Initialisiert den Service und stellt die notwendigen Verzeichnisse sicher.
        """
        self.logger = get_module_logger("statistik")
        self.CHARTS_DIR.mkdir(exist_ok=True)
        self.USER_HISTORY_DIR.mkdir(exist_ok=True)

        self.api = NavidromeAPI()
        self._polling_task: Optional[asyncio.Task] = None

        self.logger.info(
            "📊 StatistikService erfolgreich initialisiert (Benutzerspezifischer Modus)"
        )

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
                await self.update_play_history()  # Diese Methode wurde stark geändert
                self.logger.debug(
                    f"Polling: Warte {interval_seconds}s bis zur nächsten Aktualisierung."
                )

            except Exception as e:
                self.logger.error(f"❌ Fehler im History Updater: {e}", exc_info=True)

            await asyncio.sleep(interval_seconds)

    def _sanitize_filename(self, username: str) -> str:
        """Bereinigt einen Benutzernamen für die Verwendung als Dateiname."""
        # Entfernt ungültige Zeichen
        return re.sub(r"[^\w\-_\. ]", "_", username)

    def _get_history_file_for_user(self, navidrome_username: str) -> Path:
        """
        Gibt den Pfad zur Verlaufsdatei für einen bestimmten Navidrome-Benutzer zurück.
        """
        safe_username = self._sanitize_filename(navidrome_username)
        return self.USER_HISTORY_DIR / f"play_history_{safe_username}.json"

    def _load_history(self, navidrome_username: str) -> List[Dict[str, Any]]:
        """
        Lädt den Wiedergabeverlauf für einen bestimmten Benutzer.
        """
        history_file = self._get_history_file_for_user(navidrome_username)

        if not history_file.exists():
            self.logger.debug(
                f"📄 Verlaufsdatei für '{navidrome_username}' existiert noch nicht."
            )
            return []

        try:
            if history_file.stat().st_size == 0:
                self.logger.debug(
                    f"📖 Verlaufsdatei für '{navidrome_username}' ist leer."
                )
                return []

            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
                self.logger.debug(
                    f"📖 Verlauf für '{navidrome_username}' geladen: {len(history)} Einträge"
                )
                return history

        except (json.JSONDecodeError, IOError, FileNotFoundError) as e:
            self.logger.error(
                f"❌ Konnte Verlaufsdatei ({history_file}) nicht laden: {e}",
                exc_info=True,
            )
            try:
                corrupt_file = history_file.with_suffix(
                    f".json.corrupt.{datetime.now().isoformat().replace(':', '-')}"
                )
                history_file.rename(corrupt_file)
                self.logger.warning(
                    f"Datei {history_file} war korrupt und wurde nach {corrupt_file} verschoben."
                )
            except Exception as move_e:
                self.logger.error(f"Konnte korrupte Datei nicht verschieben: {move_e}")
            return []

    def _save_history(self, history: List[Dict[str, Any]], navidrome_username: str):
        """
        Speichert den Wiedergabeverlauf für einen bestimmten Benutzer.
        """
        history_file = self._get_history_file_for_user(navidrome_username)

        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            self.logger.debug(
                f"💾 Verlauf für '{navidrome_username}' gespeichert: {len(history)} Einträge"
            )

        except IOError as e:
            self.logger.error(
                f"❌ Konnte Verlaufsdatei ({history_file}) nicht speichern: {e}",
                exc_info=True,
            )

    def _cleanup_old_entries(self, navidrome_username: str):
        """
        Entfernt alte Einträge für einen bestimmten Benutzer.
        """
        history = self._load_history(navidrome_username)
        if not history:
            return

        retention_days = Config.PLAY_HISTORY_RETENTION_DAYS
        cutoff = datetime.now() - timedelta(days=retention_days)

        cleaned_history = [
            entry
            for entry in history
            if datetime.fromisoformat(entry.get("timestamp", "1970-01-01T00:00:00"))
            >= cutoff
        ]

        removed_count = len(history) - len(cleaned_history)
        if removed_count > 0:
            self._save_history(cleaned_history, navidrome_username)
            self.logger.info(
                f"🗑️ {removed_count} alte Einträge für '{navidrome_username}' entfernt "
                f"(älter als {retention_days} Tage)."
            )

    # KERNLOGIK (Jetzt benutzerspezifisch)

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

                history = self._load_history(navidrome_username)

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
                self._save_history(history, navidrome_username)

                self._cleanup_old_entries(navidrome_username)

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

    def generate_stats(
        self, period: str = "month", navidrome_username: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generiert Wiedergabestatistiken für einen bestimmten Zeitraum
        für einen bestimmten Navidrome-Benutzer.
        """
        if not navidrome_username:
            self.logger.error(
                "❌ generate_stats ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        self.logger.debug(
            f"📈 Starte Statistik-Generierung für '{navidrome_username}' (Zeitraum: {period})"
        )
        history = self._load_history(navidrome_username)

        if not history:
            self.logger.warning(
                f"⚠️ Keine Verlaufsdaten für '{navidrome_username}' verfügbar."
            )
            return None

        period_map = {"week": 7, "month": 30, "year": 365}
        days = period_map.get(period, 30)
        cutoff = datetime.now() - timedelta(days=days)

        artist_counts = defaultdict(int)
        song_counts = defaultdict(int)
        album_counts = defaultdict(int)
        total_plays_in_period = 0

        for entry in history:
            try:
                entry_time = datetime.fromisoformat(entry.get("timestamp"))
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Ungültiger Timestamp im Verlauf von '{navidrome_username}': {entry.get('timestamp')}"
                )
                continue

            if entry_time < cutoff:
                continue

            total_plays_in_period += 1

            if "tracks" in entry and entry["tracks"]:
                track_info = entry["tracks"][0]
                artist_counts[track_info.get("artist", "Unbekannt")] += 1
                song_counts[track_info.get("title", "Unbekannt")] += 1
                album_counts[track_info.get("album", "Unbekannt")] += 1

        if total_plays_in_period == 0:
            self.logger.info(
                f"ℹ️ Keine Wiedergaben im Zeitraum '{period}' für '{navidrome_username}' gefunden."
            )
            return None

        stats_result = {
            "period": period,
            "total_plays": total_plays_in_period,
            "top_artists": sorted(
                artist_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
            "top_songs": sorted(song_counts.items(), key=lambda x: x[1], reverse=True)[
                :10
            ],
            "top_albums": sorted(
                album_counts.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "navidrome_username": navidrome_username,
        }

        self.logger.info(
            f"✅ Statistiken für '{navidrome_username}' ({period}) generiert: "
            f"{stats_result['total_plays']} Wiedergaben."
        )

        return stats_result

    def get_last_played_song(
        self, navidrome_username: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Gibt den zuletzt gespielten Song für einen bestimmten Navidrome-Benutzer zurück.
        """
        if not navidrome_username:
            self.logger.error(
                "❌ get_last_played_song ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        history = self._load_history(navidrome_username)
        if not history:
            self.logger.debug(
                f"📭 Keine Verlaufsdaten für '{navidrome_username}' verfügbar."
            )
            return None

        last_entry = history[-1]
        timestamp = last_entry.get("timestamp")

        if "tracks" in last_entry and last_entry["tracks"]:
            last_song = last_entry["tracks"][0].copy()
            last_song["timestamp"] = timestamp

            self.logger.debug(
                f"🔍 Letzter Song für '{navidrome_username}': '{last_song.get('title')}'"
            )
            return last_song

        self.logger.debug(
            f"⚠️ Letzter Verlaufseintrag für '{navidrome_username}' enthält keine Tracks."
        )
        return None

    def create_chart(
        self, stats: Dict[str, Any], chart_type: str = "songs"
    ) -> Optional[Path]:
        """
        Erstellt ein horizontales Balkendiagramm (unverändert,
        nutzt die übergebenen 'stats').
        """

        username = stats.get("navidrome_username", "allgemein")
        safe_username = self._sanitize_filename(username)

        self.logger.debug(
            f"🎨 Starte Diagramm-Erstellung für: {chart_type} ({stats['period']}) für '{username}'"
        )

        data_key = f"top_{chart_type}"
        if chart_type == "artists":
            data_key = "top_artists"
        elif chart_type == "songs":
            data_key = "top_songs"

        data = stats.get(data_key, [])
        if not data:
            self.logger.warning(
                f"⚠️ Keine Daten für Diagramm-Typ '{chart_type}' (key: {data_key}) verfügbar."
            )
            return None

        labels = [item[0] for item in data][::-1]
        values = [item[1] for item in data][::-1]

        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(10, 7))

        color = "skyblue" if chart_type == "songs" else "lightgreen"
        bars = ax.barh(labels, values, color=color)

        for bar in bars:
            ax.text(
                bar.get_width() + 0.1,
                bar.get_y() + bar.get_height() / 2,
                f"{bar.get_width()}",
                va="center",
                color="white",
                fontsize=9,
            )

        ax.set_xlabel("Wiedergaben", color="white")
        title_type = "Künstler" if chart_type == "artists" else "Songs"
        ax.set_title(
            f"Top {len(labels)} {title_type} ({stats['period'].capitalize()}) - {username}",
            color="white",
        )

        plt.setp(ax.get_yticklabels(), color="white", rotation=0)
        ax.set_xlim(right=max(values) * 1.1)

        filepath = (
            self.CHARTS_DIR / f"top_{chart_type}_{stats['period']}_{safe_username}.png"
        )
        plt.tight_layout()

        try:
            plt.savefig(filepath, dpi=100)
            self.logger.info(f"✅ Diagramm erfolgreich erstellt: {filepath}")
            return filepath

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Speichern des Diagramms: {e}", exc_info=True
            )
            return None

        finally:
            plt.close(fig)

    def get_play_count_by_artist(
        self, artist_name: str, navidrome_username: str = None, period: str = "month"
    ) -> int:
        """
        Gibt die Anzahl der Wiedergaben für einen bestimmten Künstler zurück.

        Args:
            artist_name (str): Name des Künstlers
            navidrome_username (str): Navidrome-Benutzername (erforderlich)
            period (str): Zeitraum für die Auswertung

        Returns:
            int: Anzahl der Wiedergaben

        🔍 Verwendungszweck:
        - 📊 Spezifische Künstler-Statistiken
        - 🎯 Personalisierte Auswertungen
        """
        if not navidrome_username:
            self.logger.error(
                "❌ get_play_count_by_artist ohne navidrome_username aufgerufen. Abbruch."
            )
            return 0

        self.logger.debug(
            f"🔍 Zähle Wiedergaben für Künstler '{artist_name}' bei '{navidrome_username}' ({period})"
        )
        stats = self.generate_stats(period, navidrome_username)

        if not stats or "top_artists" not in stats:
            self.logger.debug(
                f"ℹ️ Keine Statistikdaten für '{navidrome_username}' ({period}) verfügbar."
            )
            return 0

        for artist, count in stats["top_artists"]:
            if artist.lower() == artist_name.lower():
                self.logger.debug(
                    f"🎵 Künstler '{artist_name}' hat {count} Wiedergaben bei '{navidrome_username}' im Zeitraum '{period}'"
                )
                return count

        self.logger.debug(
            f"ℹ️ Künstler '{artist_name}' nicht in Top-Liste für '{navidrome_username}' ({period}) gefunden (könnte 0 Plays haben)."
        )
        return 0

    def export_stats_to_json(
        self, navidrome_username: str = None, period: str = "month"
    ) -> Optional[Path]:
        """
        Exportiert die Statistiken als JSON-Datei.

        Args:
            navidrome_username (str): Navidrome-Benutzername (erforderlich)
            period (str): Zeitraum für die Statistiken

        Returns:
            Optional[Path]: Pfad zur exportierten JSON-Datei oder None bei Fehler

        💾 Export-Funktionen:
        - 📄 Vollständige Statistiken im JSON-Format
        - 🔗 Kompatibel mit anderen Analyse-Tools
        """
        if not navidrome_username:
            self.logger.error(
                "❌ export_stats_to_json ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        stats = self.generate_stats(period, navidrome_username)
        if not stats:
            self.logger.warning(
                f"⚠️ Keine Statistiken für '{navidrome_username}' zum Export verfügbar (Zeitraum: {period})"
            )
            return None

        safe_username = self._sanitize_filename(navidrome_username)
        export_file = (
            self.CHARTS_DIR
            / f"statistics_{period}_{safe_username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        try:
            self.CHARTS_DIR.mkdir(exist_ok=True)

            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)

            self.logger.info(
                f"📤 Statistiken für '{navidrome_username}' erfolgreich exportiert: {export_file}"
            )
            return export_file

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Export der Statistiken für '{navidrome_username}': {e}",
                exc_info=True,
            )
            return None
