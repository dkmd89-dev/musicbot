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

Statistics Menu UX & Architecture Optimization (Nutzer-Audit): generate_stats()
lief bisher über ein Rolling-N-Day-Window ("week"=7/"month"=30/"year"=365
Tage ab jetzt) statt echter Kalenderperioden - behoben, siehe
_calendar_period_bounds(). Song-/Album-Gruppierung lief bisher nur über
den Titel/Albumnamen (Kollisionsrisiko bei gleichnamigen Tracks
verschiedener Künstler) - behoben, siehe _track_identity().
"""

import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from logger import get_module_logger

from services.statistik.play_history_repository import PlayHistoryRepository

# Statistics Menu UX & Architecture Optimization: gültige Kalenderperioden
# für _calendar_period_bounds()/generate_stats() ("today" zusätzlich für
# generate_timeline_stats()).
_CALENDAR_PERIODS = ("today", "week", "month", "year")

# Statistics UX & Architecture (v Final): kanonische Quelle für deutsche
# Monatsnamen - wird sowohl vom Calculator selbst (generate_year_stats()'
# monthly_plays/highlights.strongest_month.name) als auch von
# handlers/mugge_statistik_handler.py (_format_period_label()) verwendet.
# EINE Quelle statt einer zweiten, potenziell abweichenden Konstante im
# Handler (siehe Master-Prompt Abschnitt 17).
GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

# Statistics UX & Architecture (v Final), Abschnitt 5: Artist-Strings
# werden NUR an " • " und " & " gesplittet (nicht an "/", ",", "feat.",
# "ft.") - siehe StatisticsCalculator._split_artists()-Docstring.
_ARTIST_SPLIT_RE = re.compile(r" • | & ")


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

    # ─────────────────────────────────────────────────────────────────
    # Kalenderlogik (Statistics Menu UX & Architecture Optimization):
    # EINZIGE Stelle im Projekt, die Kalenderperioden-Grenzen berechnet -
    # sowohl generate_stats() (week/month/year) als auch
    # generate_timeline_stats() (today/week/month) verwenden ausschließlich
    # diese Methode. Keine verstreuten/abweichenden Zeitberechnungen mehr.
    #
    # Bewusst naives, lokales datetime.now() (kein tzinfo) - konsistent mit
    # dem gesamten übrigen Projekt (kein TZ-Handling irgendwo, siehe
    # config.py und die F5-Charakterisierung im Family Hub). Montag ist
    # Wochenbeginn (datetime.weekday(): Montag=0). Kein Rolling-Window mehr
    # (vorheriges Verhalten: period_map={"week":7,"month":30,"year":365} +
    # "now - timedelta(days=…)" - das war ein reines Rolling-N-Day-Window,
    # keine Kalenderperiode, siehe Nutzer-Audit "Statistics Menu UX &
    # Architecture Optimization").
    # ─────────────────────────────────────────────────────────────────
    def _calendar_period_bounds(
        self, period: str, now: Optional[datetime] = None
    ) -> Tuple[datetime, datetime]:
        """Liefert (start, end) für die AKTUELLE Kalenderperiode - `end`
        ist exklusiv (Beginn der nächsten Periode). `now` optional
        injizierbar für deterministische Tests (Default: echtes
        datetime.now())."""
        if period not in _CALENDAR_PERIODS:
            raise ValueError(
                f"Unbekannte Kalenderperiode: {period!r} (erlaubt: {_CALENDAR_PERIODS})"
            )

        now = now or datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if period == "today":
            return today_start, today_start + timedelta(days=1)

        if period == "week":
            start = today_start - timedelta(days=today_start.weekday())  # Montag
            return start, start + timedelta(days=7)

        if period == "month":
            start = today_start.replace(day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end

        # period == "year"
        start = today_start.replace(month=1, day=1)
        return start, start.replace(year=start.year + 1)

    def _parse_history_entries(
        self,
        history: List[Dict[str, Any]],
        navidrome_username: str,
        now: Optional[datetime] = None,
    ) -> List[Tuple[datetime, Dict[str, Any]]]:
        """Parst die Roh-History EINMAL zu einer zeitlich sortierten Liste
        (entry_time, erster Track) - gemeinsame Datengrundlage für
        generate_stats() und generate_timeline_stats() (keine mehrfache
        Datei-/Parsing-Arbeit pro Aufruf, Phase 11 des Audits).

        Ungültige Timestamps werden übersprungen (geloggt, kein Crash).
        Timestamps mit einem KALENDERTAG nach `now` werden ebenfalls
        übersprungen und geloggt - reale History-Einträge werden
        ausschließlich beim tatsächlichen Abspielzeitpunkt geschrieben
        (PlayHistoryPoller), ein auf einen späteren Tag datierter Eintrag
        deutet auf korrupte/manipulierte Daten hin und darf keine
        Kalenderperiode künstlich befüllen.

        Bewusst tagesgenau (`.date()`), NICHT sekundengenau: für die
        Kalenderperioden-Zuordnung (today/week/month/year) macht die
        Uhrzeit innerhalb desselben Tages keinen Unterschied - ein
        sekundengenauer Vergleich gegen das exakte `datetime.now()`
        würde bereits einen legitimen, "heute Mittag" datierten Eintrag
        fälschlich verwerfen, wenn der Aufruf zufällig vormittags
        stattfindet (Regression, per Nutzer-Testlauf gefunden -
        `tests/test_family_challenge_service.py::_play_entry()` baut
        Test-Einträge bewusst mit fester Stunde 12:00, unabhängig von
        der tatsächlichen Ausführungszeit).
        """
        now = now or datetime.now()
        today = now.date()
        parsed: List[Tuple[datetime, Dict[str, Any]]] = []

        for entry in history:
            try:
                entry_time = datetime.fromisoformat(entry.get("timestamp"))
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Ungültiger Timestamp im Verlauf von '{navidrome_username}': "
                    f"{entry.get('timestamp')}"
                )
                continue

            if entry_time.date() > today:
                self.logger.warning(
                    f"Zukunfts-Timestamp im Verlauf von '{navidrome_username}' "
                    f"übersprungen: {entry_time.isoformat()}"
                )
                continue

            if "tracks" in entry and entry["tracks"]:
                parsed.append((entry_time, entry["tracks"][0]))

        parsed.sort(key=lambda pair: pair[0])
        return parsed

    @staticmethod
    def _identity_key(track: Dict[str, Any], field: str) -> Tuple[str, str]:
        """Kollisionssichere INTERNE Gruppierungs-ID für `field`
        ("title"/"album") - immer mit Artist kombiniert (Phase 10 des
        Audits: "Artist A – Song X" und "Artist B – Song X" dürfen nicht
        als derselbe Track/dasselbe Album gelten und ihre Play-Counts
        nicht vermischt werden). Das im Track-Dict bereits vorhandene
        Navidrome-`id`-Feld (siehe play_history_poller.py) identifiziert
        zwar den konkreten Song eindeutig, eignet sich aber nicht als
        Gruppierungsschlüssel über verschiedene Wiedergaben desselben
        Songs hinweg (kann pro Wiedergabe variieren) - Artist+Feld bleibt
        daher der Gruppierungsschlüssel (keine neue ID-Infrastruktur,
        Master-Prompt Phase 10).

        NUR zur Gruppierung/Zählung - die nach außen sichtbaren Werte
        (top_songs/top_albums/most_replayed_track/top_album) bleiben
        bewusst der reine Klartext-Feldwert ohne Artist-Suffix: ein Live-
        Regressionstest zeigte, dass
        services/family/family_challenge_service.py (Family-Challenge-
        Typ "own_top_song_today") `most_replayed_track[0]` wörtlich mit
        einer Nutzer-Texteingabe vergleicht - diese Phase darf laut
        Auftrag keine Familien-Code-Datei anfassen, das externe
        Datenformat muss also unverändert (reiner Titel/Albumname)
        bleiben. Zwei kollidierende Einträge erscheinen dadurch bewusst
        als zwei separate Zeilen mit demselben sichtbaren Namen, aber
        korrekt getrennten Play-Counts, statt fälschlich zu einer
        Zeile vermischt zu werden."""
        # `or "Unbekannt"` statt nur .get(..., "Unbekannt"): faengt auch
        # einen vorhandenen, aber leeren/None-Feldwert ab (nicht nur den
        # fehlenden Schluessel) - Statistics UX & Architecture (v Final)
        # Abschnitt 10: "Wenn ein Song keinen verwertbaren Artist-Namen
        # besitzt: Unbekannt", konsistent an dieser EINEN Stelle statt
        # dupliziert im Renderer.
        return (track.get("artist") or "Unbekannt", track.get(field) or "Unbekannt")

    @staticmethod
    def _split_artists(artist: str) -> List[str]:
        """
        Zerlegt einen kombinierten Artist-String in einzelne Artists
        (Statistics UX & Architecture v Final, Abschnitt 5) - NUR für
        `top_artists_split`/`total_artists`, NICHT für `top_artists`
        (das bleibt unverändert kombiniert-String-basiert, siehe
        generate_stats()-Docstring).

        Splittet AUSSCHLIESSLICH an " • " und " & " (siehe
        _ARTIST_SPLIT_RE). Bewusst NICHT an "/", ",", "feat.", "ft." -
        das sind keine Multi-Artist-Trenner in den vorliegenden Daten
        (z. B. "Miksu/Macloud" ist ein einzelnes Kollab-Projekt, "Artist
        feat. Artist" bleibt eine primäre Artist-Angabe mit Feature-
        Hinweis). Muss VOR jeder Ranking-/Aggregations-Auswahl (Top-5)
        angewendet werden, nicht danach auf bereits gekürzte Strings.

        Ein einzelner Play kann dadurch mehreren Artists gutgeschrieben
        werden - die Summe der `top_artists_split`-Play-Counts kann daher
        größer als `total_plays` sein (das ist beabsichtigt, keine
        Inkonsistenz).

        Akzeptierter Grenzfall (siehe docs/FINDINGS_INDEX.md): ein
        Bandname, der selbst " & " enthält (z. B. "Simon & Garfunkel"),
        wird fälschlich in zwei Artists zerlegt - bewusst nicht
        behoben, siehe `test_split_artists_breaks_ampersand_band_names()`
        in tests/test_statistics_calculator.py.
        """
        if not artist or not artist.strip():
            return ["Unbekannt"]
        parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(artist) if p.strip()]
        return parts if parts else ["Unbekannt"]

    def generate_stats(
        self,
        period: str = "month",
        navidrome_username: str = None,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generiert Wiedergabestatistiken für eine ECHTE Kalenderperiode
        ("week"/"month"/"year" - Montag als Wochenbeginn, 1. als
        Monatsbeginn, 1.1. als Jahresbeginn) für einen bestimmten
        Navidrome-Benutzer. Kein Rolling-Window mehr (siehe
        _calendar_period_bounds()-Docstring).

        `now` optional injizierbar für deterministische Tests.

        Statistics Menu UX & Output Optimization: `top_albums` entfernt
        (einziger Konsument war die Rückblick-Anzeige, die Alben nicht
        mehr zeigt - siehe mugge_statistik_handler.py). `top_songs`
        zeigt jetzt "Titel — Artist" statt reinem Titel (im Gegensatz zu
        generate_timeline_stats()' most_replayed_track NICHT durch
        services/family/family_challenge_service.py eingeschränkt, siehe
        _identity_key()-Docstring - dort geprüft, hier kein Konflikt).

        Rückgabe-Semantik bei leerem Ergebnis: `None` nur noch, wenn für
        `navidrome_username` überhaupt KEINE Verlaufsdaten existieren
        (Account hat noch nie etwas abgespielt). Existiert Verlauf, aber
        keiner der Einträge fällt in die angefragte Periode (z. B. 0
        Plays in der aktuellen Kalenderwoche), wird stattdessen ein
        gültiges Dict mit `total_plays=0` und leeren Top-Listen
        zurückgegeben - `period_start`/`period_end` bleiben dabei gesetzt,
        damit der Aufrufer eine periodenbezogene "noch keine Wiedergaben"-
        Meldung anzeigen kann, statt einer generischen Fehlermeldung.

        Statistics UX & Architecture (v Final): zwei ADDITIVE, strukturierte
        Felder ergänzt - `top_artists`/`top_songs` bleiben dabei semantisch
        UNVERÄNDERT (bestehende Consumer, z. B. get_play_count_by_artist(),
        weiterhin unangetastet):
          - `top_songs_detailed`: List[(title, artists, count)] - `artists`
            ist der vollständige, unveränderte Artist-Roh-String (keine
            Aufsplittung, keine "title — artist"-Kombination zum späteren
            Reparsen - siehe Master-Prompt Abschnitt 4).
          - `top_artists_split`: wie `top_artists`, aber mit
            _split_artists() VOR der Aggregation angewendet - ein Play mit
            "A • B" zählt für BEIDE Artists, die Summe kann daher >
            total_plays sein (siehe _split_artists()-Docstring).
        """
        if not navidrome_username:
            self.logger.error(
                "❌ generate_stats ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        if period not in ("week", "month", "year"):
            self.logger.warning(
                f"⚠️ Unbekannte Periode '{period}' für generate_stats() - "
                "verwende 'month'."
            )
            period = "month"

        self.logger.debug(
            f"📈 Starte Statistik-Generierung für '{navidrome_username}' (Zeitraum: {period})"
        )
        history = self.repository.load(navidrome_username)

        if not history:
            self.logger.warning(
                f"⚠️ Keine Verlaufsdaten für '{navidrome_username}' verfügbar."
            )
            return None

        period_start, period_end = self._calendar_period_bounds(period, now=now)
        parsed_entries = self._parse_history_entries(
            history, navidrome_username, now=now
        )

        artist_counts: Dict[str, int] = defaultdict(int)
        artist_split_counts: Dict[str, int] = defaultdict(int)
        song_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        total_plays_in_period = 0

        for entry_time, track_info in parsed_entries:
            if not (period_start <= entry_time < period_end):
                continue

            total_plays_in_period += 1
            artist_raw = track_info.get("artist") or "Unbekannt"
            artist_counts[artist_raw] += 1
            song_counts[self._identity_key(track_info, "title")] += 1
            for split_artist in self._split_artists(artist_raw):
                artist_split_counts[split_artist] += 1

        top_songs_ranked = sorted(song_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_artists_split_ranked = sorted(
            artist_split_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]

        stats_result = {
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "total_plays": total_plays_in_period,
            "top_artists": sorted(
                artist_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
            # (artist, title) -> "Titel — Artist" für die Anzeige.
            "top_songs": [
                (f"{title} — {artist}", count)
                for (artist, title), count in top_songs_ranked
            ],
            # (title, artists, count) - keine String-Kombination, siehe
            # Docstring oben.
            "top_songs_detailed": [
                (title, artist, count)
                for (artist, title), count in top_songs_ranked
            ],
            "top_artists_split": top_artists_split_ranked,
            "navidrome_username": navidrome_username,
        }

        if total_plays_in_period == 0:
            self.logger.info(
                f"ℹ️ Keine Wiedergaben im Zeitraum '{period}' für '{navidrome_username}' gefunden."
            )
        else:
            self.logger.info(
                f"✅ Statistiken für '{navidrome_username}' ({period}) generiert: "
                f"{stats_result['total_plays']} Wiedergaben."
            )

        return stats_result

    def generate_timeline_stats(
        self, navidrome_username: str = None, now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Erstellt eine Music-Timeline-Übersicht (Heute / Diese Woche /
        Diesen Monat) mit Track-Anzahl, Hörzeit, Top-Artist, Top-Album,
        meistgespieltem Track und Anzahl neuer Tracks je Zeitraum.

        Zeiträume sind KALENDERBASIERT (nicht rollierend, siehe
        _calendar_period_bounds()):
          - "today": ab lokaler Mitternacht des aktuellen Tages
          - "week":  ab Montag 00:00 der aktuellen Kalenderwoche
          - "month": ab dem 1. des aktuellen Kalendermonats

        `now` optional injizierbar für deterministische Tests.

        Music Timeline Consistency & UX: `top_artist` wird über
        _split_artists() ermittelt - identische Aggregationslogik wie
        generate_stats()' top_artists_split, damit Timeline und
        Wochen-/Monats-/Jahresrückblick für denselben Zeitraum garantiert
        dieselbe Top-Artist-Zahl zeigen (siehe
        TestTimelineConsistencyWithPeriodReview). `top_album`/
        `most_replayed_track` bleiben unverändert unsplitted/Klartext
        (Family-Challenge-Kompatibilität, siehe _identity_key()-Docstring).

        Feature-Hinweis (History.txt, "Music Timeline"): Der dort
        skizzierte Genre-Zeitverlauf ("Jan Hip-Hop, Feb Pop, ...") ist
        mit dem aktuellen Datenmodell NICHT umsetzbar, da weder
        PlayHistoryPoller noch NavidromeAPI ein "genre"-Feld im
        Wiedergabeverlauf erfassen. Bewusst ausgeklammert statt mit
        Platzhalter-/Fake-Daten zu füllen. TODO: bei Bedarf Genre-Erfassung
        separat ergänzen (Poller + Datenmodell), dann hier nachziehen.

        Returns:
            Optional[Dict[str, Any]]: {
                "navidrome_username": str,
                "periods": {
                    "today": {..., "period_start": datetime},
                    "week": {..., "period_start": datetime},
                    "month": {..., "period_start": datetime},
                }
            } oder None, wenn keine (gültige) Historie vorhanden ist.
        """
        if not navidrome_username:
            self.logger.error(
                "❌ generate_timeline_stats ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        history = self.repository.load(navidrome_username)
        if not history:
            self.logger.warning(
                f"⚠️ Keine Verlaufsdaten für '{navidrome_username}' verfügbar (Timeline)."
            )
            return None

        # Music Timeline Consistency & UX: period_end zusätzlich zu
        # period_start festgehalten (beide bereits von
        # _calendar_period_bounds() berechnet, vorher wurde nur [0]
        # verwendet) - ermöglicht dem Renderer einen echten Datumsbereich
        # für "Diese Woche" (siehe handle_music_timeline()), ohne
        # _calendar_period_bounds() selbst anzufassen.
        period_bounds_full = {
            period_name: self._calendar_period_bounds(period_name, now=now)
            for period_name in ("today", "week", "month")
        }
        period_bounds = {
            period_name: bounds[0] for period_name, bounds in period_bounds_full.items()
        }

        parsed_entries = self._parse_history_entries(
            history, navidrome_username, now=now
        )

        if not parsed_entries:
            self.logger.info(
                f"ℹ️ Keine gültigen Verlaufseinträge für '{navidrome_username}' (Timeline)."
            )
            return None

        # Erstes Auftreten je Track-Identität (Artist+Titel, siehe
        # _identity_key()) über die GESAMTE Historie - Grundlage für
        # "neue Musik" je Zeitraum. Titel-only würde "Artist A - Song X"
        # und "Artist B - Song X" faelschlich als denselben Track
        # behandeln (Phase 10 des Audits).
        first_seen: Dict[Tuple[str, str], datetime] = {}
        for entry_time, track in parsed_entries:
            key = self._identity_key(track, "title")
            if key not in first_seen:
                first_seen[key] = entry_time

        periods_result: Dict[str, Any] = {}

        for period_name, start_bound in period_bounds.items():
            track_count = 0
            listening_seconds = 0
            artist_counts: Dict[str, int] = defaultdict(int)
            album_counts: Dict[Tuple[str, str], int] = defaultdict(int)
            song_counts: Dict[Tuple[str, str], int] = defaultdict(int)
            new_track_keys: set = set()

            for entry_time, track in parsed_entries:
                if entry_time < start_bound:
                    continue

                track_count += 1
                duration = track.get("duration")
                if isinstance(duration, (int, float)):
                    listening_seconds += duration

                key = self._identity_key(track, "title")
                for split_artist in self._split_artists(track.get("artist") or "Unbekannt"):
                    artist_counts[split_artist] += 1
                album_counts[self._identity_key(track, "album")] += 1
                song_counts[key] += 1

                if first_seen.get(key, start_bound) >= start_bound:
                    new_track_keys.add(key)

            # Music Timeline Consistency & UX: top_artist wird seit dieser
            # Phase über dieselben gesplitteten Artist-Identitäten wie
            # generate_stats()' top_artists_split ermittelt (siehe
            # _split_artists()-Aufruf oben) - vorher zählte ein Play mit
            # "A • B • C" als EIN Combo-Artist, wodurch Timeline und
            # Wochen-/Monatsrückblick für denselben Zeitraum
            # unterschiedliche Top-Artist-Zahlen zeigen konnten (echte
            # Inkonsistenz, siehe Nutzer-Audit). top_album/most_replayed_track
            # bleiben BEWUSST unverändert titel-/albumname-basiert (kein
            # Split) - most_replayed_track wird von
            # services/family/family_challenge_service.py wörtlich mit
            # einer Nutzer-Texteingabe verglichen (siehe
            # _identity_key()-Docstring), dieser Vertrag darf durch diese
            # Phase nicht verändert werden.
            top_artist = max(artist_counts.items(), key=lambda x: x[1], default=None)
            top_album_raw = max(album_counts.items(), key=lambda x: x[1], default=None)
            most_replayed_raw = max(song_counts.items(), key=lambda x: x[1], default=None)
            # (artist, album)/(artist, title) -> reiner Name für die
            # Anzeige (siehe _identity_key()-Docstring).
            top_album = (top_album_raw[0][1], top_album_raw[1]) if top_album_raw else None
            most_replayed = (
                (most_replayed_raw[0][1], most_replayed_raw[1])
                if most_replayed_raw
                else None
            )

            periods_result[period_name] = {
                "period_start": start_bound,
                "period_end": period_bounds_full[period_name][1],
                "track_count": track_count,
                "listening_seconds": listening_seconds,
                "top_artist": top_artist,
                "top_album": top_album,
                "most_replayed_track": most_replayed,
                "new_track_count": len(new_track_keys),
            }

        self.logger.info(
            f"✅ Timeline-Statistik für '{navidrome_username}' erstellt "
            f"(heute: {periods_result['today']['track_count']}, "
            f"woche: {periods_result['week']['track_count']}, "
            f"monat: {periods_result['month']['track_count']})"
        )

        return {
            "navidrome_username": navidrome_username,
            "periods": periods_result,
        }

    def generate_year_stats(
        self, navidrome_username: str = None, now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Statistics UX & Architecture (v Final), Abschnitt 14: eigener
        Jahres-Datensatz (KPIs, Monatsaktivität, Jahres-Highlight) - KEIN
        paralleler Business-Logic-Calculator, sondern eine weitere Methode
        auf DERSELBEN Klasse, die dieselbe Kalender-/Parsing-/Identity-
        Infrastruktur wiederverwendet (_calendar_period_bounds(),
        _parse_history_entries(), _identity_key(), _split_artists()).

        `period_start`/`period_end` folgen exakt derselben Konvention wie
        generate_stats() (1.1. 00:00 - 1.1. Folgejahr 00:00, exklusiv,
        siehe _calendar_period_bounds()) - keine zweite Zeitraum-Definition.

        `total_songs`/`total_artists`/`total_albums` werden aus der
        VOLLSTÄNDIGEN Jahres-History bestimmt (nicht aus den Top-10/Top-5-
        Listen abgeleitet):
          - total_songs: Anzahl eindeutiger _identity_key("title")
          - total_artists: Anzahl eindeutiger, gesplitteter Artist-Namen
            (_split_artists(), dieselben Regeln wie top_artists_split)
          - total_albums: Anzahl eindeutiger _identity_key("album")

        `monthly_plays` enthält IMMER genau 12 Einträge (Januar-Dezember,
        fehlende Monate 0), aus demselben Durchlauf über parsed_entries
        wie `total_plays` berechnet - die Invariante
        `sum(plays for _, plays in monthly_plays) == total_plays` ist
        dadurch strukturell garantiert (keine zweite Datenquelle, siehe
        Master-Prompt Abschnitt 16.1).

        `highlights` enthält in v1 AUSSCHLIESSLICH `strongest_month`
        (Monat mit den meisten Plays, bei Gleichstand der chronologisch
        erste - `max()` über eine in Jan-Dez-Reihenfolge iterierte Liste
        liefert bereits den ersten Treffer bei Ties). `delta_pct` ist
        `None` bei < 3 aktiven Monaten oder `total_plays == 0`, sonst ein
        nicht-negativer, gerundeter Prozentwert über dem Monatsdurchschnitt
        (structural garantiert nicht-negativ, da der stärkste Monat per
        Definition >= Durchschnitt liegt). KEINE weiteren Highlights
        (kein top_artist/top_song-Alias auf Ranking-Daten - das
        Datenmodell bleibt frei von Ranking-Duplikaten, siehe Abschnitt 18).

        `None` nur, wenn für `navidrome_username` überhaupt keine
        Verlaufsdaten existieren (identische Semantik zu generate_stats()).
        """
        if not navidrome_username:
            self.logger.error(
                "❌ generate_year_stats ohne navidrome_username aufgerufen. Abbruch."
            )
            return None

        history = self.repository.load(navidrome_username)
        if not history:
            self.logger.warning(
                f"⚠️ Keine Verlaufsdaten für '{navidrome_username}' verfügbar (Jahr)."
            )
            return None

        period_start, period_end = self._calendar_period_bounds("year", now=now)
        parsed_entries = self._parse_history_entries(
            history, navidrome_username, now=now
        )

        song_identities_seen: set = set()
        album_identities_seen: set = set()
        artist_identities_seen: set = set()
        song_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        artist_split_counts: Dict[str, int] = defaultdict(int)
        monthly_counts: List[int] = [0] * 12
        total_plays = 0

        for entry_time, track_info in parsed_entries:
            if not (period_start <= entry_time < period_end):
                continue

            total_plays += 1
            monthly_counts[entry_time.month - 1] += 1

            song_key = self._identity_key(track_info, "title")
            song_identities_seen.add(song_key)
            song_counts[song_key] += 1

            album_identities_seen.add(self._identity_key(track_info, "album"))

            for split_artist in self._split_artists(
                track_info.get("artist") or "Unbekannt"
            ):
                artist_identities_seen.add(split_artist)
                artist_split_counts[split_artist] += 1

        top_songs_ranked = sorted(
            song_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]
        top_artists_split_ranked = sorted(
            artist_split_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]

        monthly_plays = [
            (GERMAN_MONTHS[i], monthly_counts[i]) for i in range(12)
        ]

        # Chronologisch erster Treffer bei Gleichstand (Abschnitt 19):
        # max() über eine Jan->Dez geordnete Sequenz liefert bereits den
        # ersten Index mit dem Maximalwert, kein zusätzlicher Tie-Break
        # nötig.
        strongest_idx = max(range(12), key=lambda i: monthly_counts[i])
        active_months = sum(1 for c in monthly_counts if c > 0)
        average_monthly_plays = total_plays / 12
        if active_months >= 3 and average_monthly_plays > 0:
            delta_pct = round(
                (monthly_counts[strongest_idx] - average_monthly_plays)
                / average_monthly_plays
                * 100
            )
        else:
            delta_pct = None

        year_stats = {
            "year": period_start.year,
            "period_start": period_start,
            "period_end": period_end,
            "total_plays": total_plays,
            "total_songs": len(song_identities_seen),
            "total_artists": len(artist_identities_seen),
            "total_albums": len(album_identities_seen),
            "monthly_plays": monthly_plays,
            "highlights": {
                "strongest_month": {
                    "name": GERMAN_MONTHS[strongest_idx],
                    "plays": monthly_counts[strongest_idx],
                    "delta_pct": delta_pct,
                },
            },
            "top_songs_detailed": [
                (title, artist, count)
                for (artist, title), count in top_songs_ranked
            ],
            "top_artists_split": top_artists_split_ranked,
            "navidrome_username": navidrome_username,
        }

        self.logger.info(
            f"✅ Jahresstatistik für '{navidrome_username}' ({year_stats['year']}) "
            f"generiert: {total_plays} Wiedergaben, "
            f"{year_stats['total_songs']} Songs, {year_stats['total_artists']} Artists."
        )

        return year_stats

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
