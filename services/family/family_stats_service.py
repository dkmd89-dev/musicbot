# services/family/family_stats_service.py
# -*- coding: utf-8 -*-
"""
FamilyStatsService – aggregiert die bestehende Play-History mehrerer
Familienmitglieder zu Familien-Statistiken (Phase F2, Family Hub).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Aggregation von bereits vorhandenen Play-History-Daten
    (via injiziertes PlayHistoryRepository, services/statistik/) über die
    Navidrome-User einer Familie (via injiziertes FamilyService).
  - KEINE eigene Persistenz, KEIN externer API-Zugriff, KEIN
    Chart-Rendering, KEINE Telegram-Objekte.

WICHTIG (Master-Prompt, "Wichtige Datenregel"): ausschließlich PLAY-Daten
(Navidrome-Wiedergabeverlauf). Downloads werden hier NICHT einbezogen -
Downloads und Plays bleiben konzeptionell getrennt.

Bewusst KEINE zweite Statistik-Engine: die Aggregation nutzt exakt
dieselbe Rohdatenquelle wie StatisticsCalculator
(services/statistik/statistics_calculator.py) - PlayHistoryRepository.load()
- nur über mehrere Navidrome-User hinweg summiert statt für einen
einzelnen. StatisticsCalculator selbst bleibt unverändert und wird für
die persönliche Statistik weiterhin 1:1 wie bisher verwendet.

Hörzeit-Hinweis: `duration` wird von PlayHistoryPoller unverändert aus
Navidrome übernommen und ist in der Praxis überwiegend `null`
(clientabhängig, siehe services/statistik/play_history_poller.py). Jede
hier zurückgegebene "listening_seconds"-Summe wird deshalb IMMER von
einem "listening_seconds_reliable"-Flag begleitet - True nur, wenn im
betrachteten Zeitraum tatsächlich mindestens ein numerischer
Duration-Wert vorhanden war. Aufrufer (Handler) dürfen die Sekunden-Summe
nicht anzeigen, ohne dieses Flag zu prüfen.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from logger import get_module_logger

from config import Config
from services.family.family_service import FamilyService
from services.statistik.play_history_repository import PlayHistoryRepository

# Rollierende Zeiträume - identisch zu StatisticsCalculator.generate_stats(),
# damit "Familien-Statistik (Monat)" und "Meine Statistik (Monat)" denselben
# Zeitraumbegriff verwenden.
_PERIOD_DAYS = {"week": 7, "month": 30, "year": 365}


class _FamilyEntry:
    """Ein einzelner Play-History-Eintrag, angereichert um Mitgliedskontext."""

    __slots__ = ("telegram_id", "display_name", "entry_time", "track")

    def __init__(self, telegram_id, display_name, entry_time, track):
        self.telegram_id = telegram_id
        self.display_name = display_name
        self.entry_time = entry_time
        self.track = track


class FamilyStatsService:
    """Aggregiert Play-History mehrerer Familienmitglieder zu Familien-Statistiken."""

    def __init__(
        self,
        family_service: Optional[FamilyService] = None,
        repository: Optional[PlayHistoryRepository] = None,
        logger_factory=None,
    ):
        self.logger = (logger_factory or get_module_logger)("FamilyStatsService")
        self.family_service = family_service or FamilyService()
        self.repository = repository or PlayHistoryRepository(
            Config.PLAY_HISTORY_FILE, logger=get_module_logger("PlayHistoryRepository")
        )

    # ─────────────────────────────────────────────────────────────────
    # Interne Hilfsfunktionen
    # ─────────────────────────────────────────────────────────────────

    def _load_all_entries(self, family_id: str) -> List[_FamilyEntry]:
        """Lädt und parst die Play-History ALLER aktiven Mitglieder einer Familie."""
        members = self.family_service.get_members(family_id, active_only=True)
        entries: List[_FamilyEntry] = []

        for telegram_id, member in members.items():
            navidrome_user = member.get("navidrome_user")
            if not navidrome_user:
                continue

            display_name = member.get("display_name", navidrome_user)
            history = self.repository.load(navidrome_user)

            for entry in history:
                try:
                    entry_time = datetime.fromisoformat(entry.get("timestamp"))
                except (ValueError, TypeError):
                    self.logger.warning(
                        f"Ungültiger Timestamp im Verlauf von '{navidrome_user}': "
                        f"{entry.get('timestamp')}"
                    )
                    continue

                tracks = entry.get("tracks")
                if not tracks:
                    continue

                entries.append(
                    _FamilyEntry(telegram_id, display_name, entry_time, tracks[0])
                )

        return entries

    @staticmethod
    def _cutoff_for_period(period: str) -> datetime:
        days = _PERIOD_DAYS.get(period, 30)
        return datetime.now() - timedelta(days=days)

    # ─────────────────────────────────────────────────────────────────
    # 1. Familien-Gesamtstatistik + 2. Statistik pro Mitglied
    # ─────────────────────────────────────────────────────────────────

    def generate_family_stats(
        self, family_id: str, period: str = "month"
    ) -> Optional[Dict[str, Any]]:
        """
        Familien-Gesamtstatistik für einen rollierenden Zeitraum
        ("week"/"month"/"year", Standard "month" wie StatisticsCalculator).

        Returns:
            None, wenn die Familie unbekannt ist oder im Zeitraum keine
            Wiedergaben vorliegen. Sonst ein Dict mit total_plays,
            top_artists/top_songs (10)/top_albums (5), per_member (Plays
            je Mitglied) sowie listening_seconds/listening_seconds_reliable.
        """
        entries = self._load_all_entries(family_id)
        if not entries:
            return None

        cutoff = self._cutoff_for_period(period)
        artist_counts: Dict[str, int] = defaultdict(int)
        song_counts: Dict[str, int] = defaultdict(int)
        album_counts: Dict[str, int] = defaultdict(int)
        per_member: Dict[str, Dict[str, Any]] = {}
        listening_seconds = 0
        listening_seconds_reliable = False
        total_plays = 0

        for entry in entries:
            if entry.entry_time < cutoff:
                continue

            total_plays += 1
            artist_counts[entry.track.get("artist", "Unbekannt")] += 1
            song_counts[entry.track.get("title", "Unbekannt")] += 1
            album_counts[entry.track.get("album", "Unbekannt")] += 1

            member_bucket = per_member.setdefault(
                entry.telegram_id,
                {"display_name": entry.display_name, "plays": 0},
            )
            member_bucket["plays"] += 1

            duration = entry.track.get("duration")
            if isinstance(duration, (int, float)):
                listening_seconds += duration
                listening_seconds_reliable = True

        if total_plays == 0:
            return None

        return {
            "period": period,
            "total_plays": total_plays,
            "top_artists": sorted(
                artist_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:10],
            "top_songs": sorted(
                song_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:10],
            "top_albums": sorted(
                album_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:5],
            "per_member": per_member,
            "listening_seconds": listening_seconds,
            "listening_seconds_reliable": listening_seconds_reliable,
        }

    # ─────────────────────────────────────────────────────────────────
    # 8. Musik-Champion (ausschließlich anhand PLAYS)
    # ─────────────────────────────────────────────────────────────────

    def get_champion(
        self, family_id: str, period: str = "month"
    ) -> Optional[Tuple[str, str, int]]:
        """
        Ermittelt das Familienmitglied mit den meisten Plays im Zeitraum.

        Returns:
            (telegram_id, display_name, plays) oder None, wenn keine
            Wiedergaben im Zeitraum vorliegen. Zählt ausschließlich Plays,
            NICHT Downloads (Master-Prompt: "Downloads und Plays müssen
            konzeptionell getrennt bleiben").
        """
        stats = self.generate_family_stats(family_id, period)
        if not stats or not stats["per_member"]:
            return None

        champion_id, champion_data = max(
            stats["per_member"].items(), key=lambda kv: kv[1]["plays"]
        )
        return champion_id, champion_data["display_name"], champion_data["plays"]

    # ─────────────────────────────────────────────────────────────────
    # 5. Familien Music Timeline (kalenderbasiert, wie StatisticsCalculator)
    # ─────────────────────────────────────────────────────────────────

    def generate_family_timeline(self, family_id: str) -> Optional[Dict[str, Any]]:
        """
        Familien-Timeline (Heute/Diese Woche/Dieser Monat), kalenderbasiert
        - identisches Zeitraumkonzept wie
        StatisticsCalculator.generate_timeline_stats(), nur über alle
        aktiven Familienmitglieder aggregiert.
        """
        entries = self._load_all_entries(family_id)
        if not entries:
            return None

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        period_bounds = {"today": today_start, "week": week_start, "month": month_start}
        periods_result: Dict[str, Any] = {}

        for period_name, start_bound in period_bounds.items():
            track_count = 0
            artist_counts: Dict[str, int] = defaultdict(int)
            song_counts: Dict[str, int] = defaultdict(int)
            per_member_counts: Dict[str, int] = defaultdict(int)

            for entry in entries:
                if entry.entry_time < start_bound:
                    continue
                track_count += 1
                artist_counts[entry.track.get("artist", "Unbekannt")] += 1
                song_counts[entry.track.get("title", "Unbekannt")] += 1
                per_member_counts[entry.display_name] += 1

            top_artist = max(artist_counts.items(), key=lambda kv: kv[1], default=None)
            top_song = max(song_counts.items(), key=lambda kv: kv[1], default=None)

            periods_result[period_name] = {
                "track_count": track_count,
                "top_artist": top_artist,
                "top_song": top_song,
                "per_member": dict(per_member_counts),
            }

        return {"family_id": family_id, "periods": periods_result}

    # ─────────────────────────────────────────────────────────────────
    # 6. Hörzeiten (Stunde/Wochentag) - auf PLAY-COUNT, nicht Dauer,
    #    basierend (siehe Klassen-Docstring: duration ist unzuverlässig).
    # ─────────────────────────────────────────────────────────────────

    def generate_listening_times(
        self, family_id: str, period: str = "month"
    ) -> Optional[Dict[str, Any]]:
        """
        Verteilung der Wiedergaben nach Tagesstunde (0-23) und Wochentag
        (0=Montag..6=Sonntag) im gewählten rollierenden Zeitraum.

        Basiert bewusst auf der Anzahl Wiedergaben (Play-Timestamps), NICHT
        auf `duration` - siehe Klassen-Docstring zur Unzuverlässigkeit der
        Dauerangabe in der realen Play-History.
        """
        entries = self._load_all_entries(family_id)
        if not entries:
            return None

        cutoff = self._cutoff_for_period(period)
        by_hour: Dict[int, int] = {h: 0 for h in range(24)}
        by_weekday: Dict[int, int] = {d: 0 for d in range(7)}
        total = 0

        for entry in entries:
            if entry.entry_time < cutoff:
                continue
            total += 1
            by_hour[entry.entry_time.hour] += 1
            by_weekday[entry.entry_time.weekday()] += 1

        if total == 0:
            return None

        return {
            "period": period,
            "total_plays": total,
            "by_hour": by_hour,
            "by_weekday": by_weekday,
        }

    # ─────────────────────────────────────────────────────────────────
    # 7. Monatsentwicklung (Plays pro Kalendermonat)
    # ─────────────────────────────────────────────────────────────────

    def generate_monthly_trend(
        self, family_id: str, months: int = 6
    ) -> Optional[Dict[str, Any]]:
        """
        Plays pro Kalendermonat für die letzten `months` Monate
        (chronologisch aufsteigend, älteste zuerst).

        Explizit KEINE Hörzeit pro Monat (siehe Klassen-Docstring -
        `duration` ist in der realen Play-History nicht zuverlässig
        verfügbar; ein "Hörzeit pro Monat"-Wert wäre irreführend).
        """
        entries = self._load_all_entries(family_id)
        if not entries:
            return None

        now = datetime.now()
        month_keys: List[str] = []
        cursor = now.replace(day=1)
        for _ in range(months):
            month_keys.append(cursor.strftime("%Y-%m"))
            # ein Monat zurück
            prev_last_day = cursor - timedelta(days=1)
            cursor = prev_last_day.replace(day=1)
        month_keys.reverse()

        counts: Dict[str, int] = {key: 0 for key in month_keys}
        for entry in entries:
            key = entry.entry_time.strftime("%Y-%m")
            if key in counts:
                counts[key] += 1

        if sum(counts.values()) == 0:
            return None

        return {
            "months": month_keys,
            "plays_by_month": counts,
        }
