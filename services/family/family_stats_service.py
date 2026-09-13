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

MASTER PHASE B (Family Statistics Attribution, Identity & UX
Optimization): `generate_family_stats()`/`get_champion()`/
`generate_listening_times()`/`generate_monthly_trend()` liefen bisher
über ein Rolling-N-Day-Window (`_PERIOD_DAYS = {"week":7,"month":30,
"year":365}`, entfernt) statt echter Kalenderperioden, und gruppierten
Songs/Artists nur über den rohen Titel-/Artist-String (Kollisionsrisiko,
keine Member-Attribution). Bewusst KEINE zweite Statistik-Engine: diese
Klasse hält jetzt eine interne `StatisticsCalculator`-Instanz
(Komposition, dieselbe `PlayHistoryRepository`-Quelle) und nutzt deren
kanonische Bausteine wieder - `_calendar_period_bounds()`,
`_parse_history_entries()` (Instanzmethoden), `_identity_key()`/
`_split_artists()` (statisch) - statt eigene Kalender-/Identity-/
Split-Logik zu duplizieren. `StatisticsCalculator` selbst bleibt dabei
unverändert und wird für die persönliche Statistik weiterhin 1:1 wie
bisher verwendet.

`generate_family_timeline()` bleibt in dieser Phase BEWUSST unverändert:
sie ist bereits kalenderbasiert (eigene, seit F2 etablierte Logik) und
ist keine der 6 F2-Menüfunktionen, die dieser Auftrag umfasst - sie ist
stattdessen eine geteilte Abhängigkeit von F4
(`family_challenge_service.py`s `family_top_artist_today`/
`family_top_song_today`). Ohne konkrete Regression bleibt sie unangetastet
(Master-Prompt: "F3/F4 nicht verändern, außer eine konkrete Regression
oder gemeinsame Dependency erfordert eine minimale Anpassung" - hier
liegt weder eine Regression noch ein Änderungsbedarf vor). Sie verwendet
deshalb weiterhin ihre eigene `_load_all_entries()`/`_FamilyEntry`-
Infrastruktur, komplett unverändert.

Artist-Case-Normalisierung (Abschnitt 9 des Master-Prompts) ist eine
FAMILIEN-SPEZIFISCHE Erweiterung ohne Pendant in der Personal-Statistics-
Domain (dort bleibt `top_artists_split` bewusst case-sensitiv, siehe
StatisticsCalculator._split_artists()-Docstring) - deshalb hier lokal
implementiert (casefold-Schlüssel für die Aggregation, häufigste
Original-Schreibweise als deterministischer Anzeigewert), NICHT in
`_split_artists()` selbst (das bliebe sonst eine zweite, abweichende
Regel gegenüber der Personal-Statistics-Verwendung derselben Methode).

Hörzeit-Hinweis: `duration` wird von PlayHistoryPoller unverändert aus
Navidrome übernommen und ist in der Praxis überwiegend `null`
(clientabhängig, siehe services/statistik/play_history_poller.py). Jede
hier zurückgegebene "listening_seconds"-Summe wird deshalb IMMER von
einem "listening_seconds_reliable"-Flag begleitet - True nur, wenn im
betrachteten Zeitraum tatsächlich mindestens ein numerischer
Duration-Wert vorhanden war. Aufrufer (Handler) dürfen die Sekunden-Summe
nicht anzeigen, ohne dieses Flag zu prüfen. Aus demselben Grund heißt die
Funktion bewusst weiterhin "Hör-Aktivität", nicht "Hörzeit" (Abschnitt 20)
- sie misst Wiedergabe-ZEITPUNKTE (Stunde/Wochentag), keine echte Hördauer.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from logger import get_module_logger

from config import Config
from services.family.family_service import FamilyService
from services.statistik.play_history_repository import PlayHistoryRepository
from services.statistik.statistics_calculator import StatisticsCalculator


class _FamilyEntry:
    """Ein einzelner Play-History-Eintrag, angereichert um Mitgliedskontext.

    Ausschließlich von generate_family_timeline()/_load_all_entries()
    verwendet (siehe Klassen-Docstring - diese Methode bleibt bewusst
    unverändert, eigene Infrastruktur)."""

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
        # Komposition statt zweiter Implementierung (siehe Klassen-Docstring):
        # `export_dir` wird von FamilyStatsService nie genutzt (kein
        # export_stats_to_json()-Aufruf hier), aber vom Konstruktor
        # verlangt - Config.STATS_DIR ist dieselbe Konstante, die auch
        # StatistikService dafür verwendet.
        self._calculator = StatisticsCalculator(
            self.repository,
            export_dir=Config.STATS_DIR,
            logger=get_module_logger("StatisticsCalculator"),
        )

    # ─────────────────────────────────────────────────────────────────
    # Interne Hilfsfunktionen (kanonische Kalender-/Parsing-Wiederverwendung)
    # ─────────────────────────────────────────────────────────────────

    def _load_member_period_entries(
        self,
        family_id: str,
        period_start: datetime,
        period_end: datetime,
        now: Optional[datetime] = None,
    ) -> List[Tuple[str, str, datetime, Dict[str, Any]]]:
        """Liefert (telegram_id, display_name, entry_time, track) für alle
        aktiven Mitglieder, deren Wiedergabe in [period_start, period_end)
        liegt. Nutzt StatisticsCalculator._parse_history_entries() (kanonische
        Zukunfts-Timestamp-Filterung + Sortierung, siehe dessen Docstring) -
        keine zweite Parsing-Logik."""
        members = self.family_service.get_members(family_id, active_only=True)
        result: List[Tuple[str, str, datetime, Dict[str, Any]]] = []

        for telegram_id, member in members.items():
            navidrome_user = member.get("navidrome_user")
            if not navidrome_user:
                continue
            display_name = member.get("display_name", navidrome_user)
            history = self.repository.load(navidrome_user)
            parsed = self._calculator._parse_history_entries(
                history, navidrome_user, now=now
            )
            for entry_time, track in parsed:
                if period_start <= entry_time < period_end:
                    result.append((telegram_id, display_name, entry_time, track))

        return result

    def _load_all_member_entries(
        self, family_id: str, now: Optional[datetime] = None
    ) -> List[Tuple[str, str, datetime, Dict[str, Any]]]:
        """Wie _load_member_period_entries(), aber OHNE Periodenfilter -
        Grundlage für generate_monthly_trend(), das über mehrere
        Kalendermonate bucket-t statt eine einzelne Periode zu filtern."""
        members = self.family_service.get_members(family_id, active_only=True)
        result: List[Tuple[str, str, datetime, Dict[str, Any]]] = []

        for telegram_id, member in members.items():
            navidrome_user = member.get("navidrome_user")
            if not navidrome_user:
                continue
            display_name = member.get("display_name", navidrome_user)
            history = self.repository.load(navidrome_user)
            parsed = self._calculator._parse_history_entries(
                history, navidrome_user, now=now
            )
            result.extend(
                (telegram_id, display_name, entry_time, track)
                for entry_time, track in parsed
            )

        return result

    def _load_all_entries(self, family_id: str) -> List[_FamilyEntry]:
        """NUR für generate_family_timeline() (siehe Klassen-Docstring) -
        bewusst unverändert gegenüber dem Vor-Phase-B-Stand, eigene,
        unabhängige Parsing-Infrastruktur (kein Zukunfts-Timestamp-Filter,
        keine Kalender-/Identity-Wiederverwendung)."""
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

    # ─────────────────────────────────────────────────────────────────
    # 1. Familien-Gesamtstatistik + 2. Statistik pro Mitglied
    # ─────────────────────────────────────────────────────────────────

    def generate_family_stats(
        self, family_id: str, period: str = "month", now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Familien-Gesamtstatistik für eine ECHTE Kalenderperiode
        ("week"/"month"/"year" - identische Semantik zu
        StatisticsCalculator._calendar_period_bounds()). `now` optional
        injizierbar für deterministische Tests.

        Returns:
            None, wenn die Familie unbekannt ist oder im Zeitraum keine
            Wiedergaben vorliegen (identische Semantik zum Vor-Phase-B-
            Stand - anders als die Personal-Statistics-"leere Perioden"-UX
            wurde dieses Verhalten hier NICHT geändert, da dieser Auftrag
            keine Anpassung der None-Semantik verlangt). Sonst ein Dict mit
            `period_start`/`period_end`, `total_plays`, `top_songs`/
            `top_artists` (je bis zu 10, jetzt strukturierte Dicts mit
            echter Member-Attribution statt (name, count)-Tupeln),
            `per_member` (unverändertes Format) sowie
            `listening_seconds`/`listening_seconds_reliable`.

            `top_songs`-Eintrag: {"title", "artists" (roher, unveränderter
            Artist-String), "total_plays", "members": [{"telegram_id",
            "display_name", "plays"}, ...] absteigend nach plays sortiert}.
            Song-Identity über StatisticsCalculator._identity_key()
            (Artist+Titel) - verschiedene Artists mit gleichem Songtitel
            werden nicht vermischt.

            `top_artists`-Eintrag: {"artist" (deterministischer
            Anzeigewert), "total_plays", "members": [...]}. Artist-Identity
            über StatisticsCalculator._split_artists() (Multi-Artist-
            Aufsplittung) + zusätzliche, familien-spezifische
            Case-insensitive-Aggregation (siehe Klassen-Docstring) - ein
            Play mit "A • B" zählt für beide Artists, die Summe der
            top_artists-Play-Counts kann daher > total_plays sein
            (identisch zur Personal-Statistics-Semantik).

            KEIN Cross-Member-Deduplication: jeder reale Play zählt separat
            (Abschnitt 11).
        """
        period_start, period_end = self._calculator._calendar_period_bounds(
            period, now=now
        )
        entries = self._load_member_period_entries(
            family_id, period_start, period_end, now=now
        )
        if not entries:
            return None

        total_plays = 0
        song_buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        artist_buckets: Dict[str, Dict[str, Any]] = {}
        per_member: Dict[str, Dict[str, Any]] = {}
        listening_seconds = 0
        listening_seconds_reliable = False

        for telegram_id, display_name, entry_time, track in entries:
            total_plays += 1

            member_bucket = per_member.setdefault(
                telegram_id, {"display_name": display_name, "plays": 0}
            )
            member_bucket["plays"] += 1

            artist_raw = track.get("artist") or "Unbekannt"
            title = track.get("title") or "Unbekannt"

            song_key = StatisticsCalculator._identity_key(track, "title")
            song_entry = song_buckets.setdefault(
                song_key,
                {"title": title, "artists": artist_raw, "total_plays": 0, "members": {}},
            )
            song_entry["total_plays"] += 1
            song_member = song_entry["members"].setdefault(
                telegram_id, {"display_name": display_name, "plays": 0}
            )
            song_member["plays"] += 1

            for split_artist in StatisticsCalculator._split_artists(artist_raw):
                casefold_key = split_artist.casefold()
                artist_entry = artist_buckets.setdefault(
                    casefold_key,
                    {"total_plays": 0, "members": {}, "_display_candidates": {}},
                )
                artist_entry["total_plays"] += 1
                candidates = artist_entry["_display_candidates"]
                candidates[split_artist] = candidates.get(split_artist, 0) + 1
                artist_member = artist_entry["members"].setdefault(
                    telegram_id, {"display_name": display_name, "plays": 0}
                )
                artist_member["plays"] += 1

            duration = track.get("duration")
            if isinstance(duration, (int, float)):
                listening_seconds += duration
                listening_seconds_reliable = True

        if total_plays == 0:
            return None

        def _sorted_members(members_dict: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            return sorted(
                members_dict.values(), key=lambda m: (-m["plays"], m["display_name"])
            )

        top_songs = sorted(
            song_buckets.values(), key=lambda s: s["total_plays"], reverse=True
        )[:10]
        top_songs = [
            {
                "title": s["title"],
                "artists": s["artists"],
                "total_plays": s["total_plays"],
                "members": _sorted_members(s["members"]),
            }
            for s in top_songs
        ]

        top_artists = []
        for bucket in artist_buckets.values():
            # Deterministischer Anzeigewert: häufigste Original-
            # Schreibweise, Ties -> zuerst gesehen (dict-Iteration bewahrt
            # Einfügereihenfolge, max() liefert bei Gleichstand den ersten
            # Treffer - identisches Muster wie generate_year_stats()'
            # strongest_month, siehe StatisticsCalculator-Docstring).
            display = max(
                bucket["_display_candidates"].items(), key=lambda kv: kv[1]
            )[0]
            top_artists.append(
                {
                    "artist": display,
                    "total_plays": bucket["total_plays"],
                    "members": _sorted_members(bucket["members"]),
                }
            )
        top_artists.sort(key=lambda a: a["total_plays"], reverse=True)
        top_artists = top_artists[:10]

        return {
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "total_plays": total_plays,
            "top_songs": top_songs,
            "top_artists": top_artists,
            "per_member": per_member,
            "listening_seconds": listening_seconds,
            "listening_seconds_reliable": listening_seconds_reliable,
        }

    # ─────────────────────────────────────────────────────────────────
    # 8. Musik-Champion (ausschließlich anhand PLAYS)
    # ─────────────────────────────────────────────────────────────────

    def get_champion(
        self, family_id: str, period: str = "month", now: Optional[datetime] = None
    ) -> Optional[Tuple[str, str, int]]:
        """
        Ermittelt das Familienmitglied mit den meisten Plays im Zeitraum.

        Returns:
            (telegram_id, display_name, plays) oder None, wenn keine
            Wiedergaben im Zeitraum vorliegen. Zählt ausschließlich Plays,
            NICHT Downloads (Master-Prompt: "Downloads und Plays müssen
            konzeptionell getrennt bleiben"). Baut auf generate_family_stats()'
            `per_member` auf (Abschnitt 19: keine separate
            Champion-Berechnungslogik).
        """
        stats = self.generate_family_stats(family_id, period, now=now)
        if not stats or not stats["per_member"]:
            return None

        champion_id, champion_data = max(
            stats["per_member"].items(), key=lambda kv: kv[1]["plays"]
        )
        return champion_id, champion_data["display_name"], champion_data["plays"]

    # ─────────────────────────────────────────────────────────────────
    # 5. Familien Music Timeline (kalenderbasiert, wie StatisticsCalculator)
    #
    # BEWUSST UNVERÄNDERT in MASTER PHASE B - siehe Klassen-Docstring:
    # bereits kalenderbasiert, kein Teil der 6 F2-Menüfunktionen, geteilte
    # F4-Abhängigkeit ohne konkrete Regression.
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
    # 6. Hör-Aktivität (Stunde/Wochentag) - auf PLAY-COUNT, nicht Dauer,
    #    basierend (siehe Klassen-Docstring: duration ist unzuverlässig).
    # ─────────────────────────────────────────────────────────────────

    def generate_listening_times(
        self, family_id: str, period: str = "month", now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Verteilung der Wiedergaben nach Tagesstunde (0-23) und Wochentag
        (0=Montag..6=Sonntag) in der gewählten ECHTEN Kalenderperiode
        (nicht mehr rollierend, siehe Klassen-Docstring). `now` optional
        injizierbar für deterministische Tests.

        Basiert bewusst auf der Anzahl Wiedergaben (Play-Timestamps), NICHT
        auf `duration` - siehe Klassen-Docstring zur Unzuverlässigkeit der
        Dauerangabe in der realen Play-History.
        """
        period_start, period_end = self._calculator._calendar_period_bounds(
            period, now=now
        )
        entries = self._load_member_period_entries(
            family_id, period_start, period_end, now=now
        )
        if not entries:
            return None

        by_hour: Dict[int, int] = {h: 0 for h in range(24)}
        by_weekday: Dict[int, int] = {d: 0 for d in range(7)}
        total = 0

        for _telegram_id, _display_name, entry_time, _track in entries:
            total += 1
            by_hour[entry_time.hour] += 1
            by_weekday[entry_time.weekday()] += 1

        return {
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "total_plays": total,
            "by_hour": by_hour,
            "by_weekday": by_weekday,
        }

    # ─────────────────────────────────────────────────────────────────
    # 7. Monatsentwicklung (Plays pro Kalendermonat)
    # ─────────────────────────────────────────────────────────────────

    def generate_monthly_trend(
        self, family_id: str, months: int = 6, now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Plays pro Kalendermonat für die letzten `months` Monate
        (chronologisch aufsteigend, älteste zuerst). `now` optional
        injizierbar für deterministische Tests.

        Explizit KEINE Hörzeit pro Monat (siehe Klassen-Docstring -
        `duration` ist in der realen Play-History nicht zuverlässig
        verfügbar; ein "Hörzeit pro Monat"-Wert wäre irreführend).
        """
        entries = self._load_all_member_entries(family_id, now=now)
        if not entries:
            return None

        now = now or datetime.now()
        month_keys: List[str] = []
        cursor = now.replace(day=1)
        for _ in range(months):
            month_keys.append(cursor.strftime("%Y-%m"))
            # ein Monat zurück
            prev_last_day = cursor - timedelta(days=1)
            cursor = prev_last_day.replace(day=1)
        month_keys.reverse()

        counts: Dict[str, int] = {key: 0 for key in month_keys}
        for _telegram_id, _display_name, entry_time, _track in entries:
            key = entry_time.strftime("%Y-%m")
            if key in counts:
                counts[key] += 1

        if sum(counts.values()) == 0:
            return None

        return {
            "months": month_keys,
            "plays_by_month": counts,
        }
