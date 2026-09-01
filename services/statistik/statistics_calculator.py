# services/statistik/statistics_calculator.py
# -*- coding: utf-8 -*-
"""
StatisticsCalculator – reine Business-Logik zur Auswertung des
Wiedergabeverlaufs (Top-Artists/Songs/Albums, letzter Song, JSON-Export).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Berechnung/Aufbereitung von Statistiken aus bereits
    geladenen Verlaufsdaten (via injiziertes PlayHistoryRepository).
  - KEIN Datei-Schreiben von Rohdaten, KEIN externer API-Zugriff,
    KEIN Chart-Rendering.

Extrahiert aus services/statistik_service.py (ARCH-003, P-6) - 1:1
übernommene Logik, keine Verhaltensänderung.
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Union

from logger import get_module_logger

from services.statistik.play_history_repository import PlayHistoryRepository


class StatisticsCalculator:
    """Berechnet Wiedergabestatistiken aus dem persistierten Verlauf."""

    def __init__(
        self,
        repository: PlayHistoryRepository,
        export_dir: Union[str, Path],
        logger=None,
    ):
        self.repository = repository
        self.export_dir = Path(export_dir)
        self.logger = logger or get_module_logger("StatisticsCalculator")

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
        history = self.repository.load(navidrome_username)

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

        history = self.repository.load(navidrome_username)
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

    def get_play_count_by_artist(
        self, artist_name: str, navidrome_username: str = None, period: str = "month"
    ) -> int:
        """Gibt die Anzahl der Wiedergaben für einen bestimmten Künstler zurück."""
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
        """Exportiert die Statistiken als JSON-Datei."""
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

        safe_username = self.repository.sanitize_username(navidrome_username)
        export_file = (
            self.export_dir
            / f"statistics_{period}_{safe_username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        # Baseline v5/v6 Technical Debt: vorher direktes open(export_file, "w")
        # - ein Prozessabbruch/Fehler waehrend json.dump() konnte eine
        # unvollstaendige/korrupte Export-Datei hinterlassen (export_file
        # selbst ist dank des Sekunden-Zeitstempels im Dateinamen immer neu,
        # ueberschreibt also keinen vorherigen Export - das Risiko betrifft
        # nur diese eine, gerade erst erzeugte Datei). Jetzt: write-tmp +
        # atomarer os.replace(), analog zu DuplicateCache._write_json_atomic()/
        # MetadataCache.store().
        tmp_file = export_file.with_name(f"{export_file.name}.tmp_{int(time.time() * 1000)}")
        try:
            self.export_dir.mkdir(exist_ok=True)

            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp_file, export_file)

            self.logger.info(
                f"📤 Statistiken für '{navidrome_username}' erfolgreich exportiert: {export_file}"
            )
            return export_file

        except Exception as e:
            self.logger.error(
                f"❌ Fehler beim Export der Statistiken für '{navidrome_username}': {e}",
                exc_info=True,
            )
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass
            return None
