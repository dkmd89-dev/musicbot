# services/downloader/download/year_resolver.py
# -*- coding: utf-8 -*-
"""
YearResolver – zentrale Jahr-Bestimmungs-Logik für Playlists.

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich die Ermittlung eines "dominanten Jahres" für eine
    Playlist bzw. einzelne Track-Einträge.
  - KEIN Download, KEIN Caching, KEIN Channel-Routing.

Dependency Injection:
  - Keine externen Abhängigkeiten nötig (reine Logik auf Dicts/Strings).
  - Eigene Logger-Instanz via `get_module_logger`.

Quellen-Priorität (pro Track, Quelle 1):
  release_year → year → upload_date (YYYYMMDD) → title_regex (19xx/20xx)

Quellen-Priorität (Playlist-weit, `resolve_playlist_year`):
  1. Track-Einträge (dominantes Jahr via `determine_dominant_year_from_entries`)
  2. `processed_playlist["year"]` (PlaylistProcessor-Ergebnis)
  3. `playlist_info["upload_date"]`
  4. None

Log-Marker bleiben unverändert: [YEAR].
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from logger import get_module_logger


class YearResolver:
    """
    Bestimmt das (dominante) Jahr für eine Playlist bzw. für einzelne
    Track-Einträge anhand mehrerer Quellen mit fester Priorität.
    """

    # Regex für vierstellige Jahreszahlen 1950–2029, mit Wortgrenzen
    # bzw. Nicht-Ziffer-Umgebung – deckt sowohl Titel-Suche als auch
    # upload_date-Strings ab.
    YEAR_PATTERN = re.compile(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)")

    YEAR_MIN = 1950
    YEAR_MAX = 2035

    def __init__(self, logger=None, logger_factory=None):
        self.logger = logger or (logger_factory or get_module_logger)("YearResolver")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API – Playlist-weite Jahr-Bestimmung
    # ─────────────────────────────────────────────────────────────────────────

    def resolve_playlist_year(
        self,
        entries: List[Dict[str, Any]],
        processed_playlist: Dict[str, Any],
        playlist_info: Dict[str, Any],
    ) -> Optional[int]:
        """
        Bestimmt das dominante Jahr der Playlist aus 3 Quellen
        (Priorität absteigend):

          1. Einzel-Track-Felder (über `determine_dominant_year_from_entries`)
          2. PlaylistProcessor-Ergebnis (`processed_playlist["year"]`)
          3. `playlist_info["upload_date"]`

        Gibt `None` zurück, wenn keine Quelle ein gültiges Jahr liefert.
        """
        self.logger.info("📅 [YEAR] Bestimme dominantes Playlist-Jahr...")

        # ── Quelle 1: Track-Einträge ────────────────────────────────────────
        playlist_year = self.determine_dominant_year_from_entries(entries)
        if playlist_year:
            self.logger.info(f"✅ [YEAR] Quelle 1 (Track-Einträge): {playlist_year}")
            return playlist_year

        # ── Quelle 2: PlaylistProcessor-Ergebnis ────────────────────────────
        pp_year = processed_playlist.get("year")
        if pp_year:
            try:
                y = int(str(pp_year)[:4])
                if self.YEAR_MIN <= y <= self.YEAR_MAX:
                    self.logger.info(f"✅ [YEAR] Quelle 2 (PlaylistProcessor): {y}")
                    return y
            except (ValueError, TypeError):
                pass

        # ── Quelle 3: playlist_info["upload_date"] ──────────────────────────
        upload_date = playlist_info.get("upload_date", "")
        if upload_date:
            y = self._extract_year_from_text(str(upload_date))
            if y:
                self.logger.info(f"✅ [YEAR] Quelle 3 (playlist_info.upload_date): {y}")
                return y

        self.logger.warning(
            "⚠️ [YEAR] Kein dominantes Jahr gefunden in allen 3 Quellen → None"
        )
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API – Dominantes Jahr aus Track-Einträgen
    # ─────────────────────────────────────────────────────────────────────────

    def determine_dominant_year_from_entries(
        self, entries: List[Dict[str, Any]]
    ) -> Optional[int]:
        """
        Bestimmt das dominante Jahr aus Playlist-Einträgen.

        Quellen-Priorität je Track (erste erfolgreiche Quelle gewinnt):
          1. release_year  – explizites Release-Jahr
          2. year          – allgemeines Jahr-Feld
          3. upload_date   – YYYYMMDD (yt-dlp Format), erste 4 Zeichen
          4. title         – Regex-Suche nach 19xx/20xx

        Das häufigste Jahr wird zurückgegeben. Bei einer Dominanz von
        ≥30% wird dies explizit als "stark" geloggt, ansonsten als
        "schwach" – das Jahr wird in beiden Fällen verwendet.
        """
        if not entries:
            return None

        self.logger.info(
            f"📅 [YEAR] Analysiere {len(entries)} Track-Einträge auf dominantes Jahr..."
        )

        year_counts: Counter = Counter()
        source_counts: Counter = Counter()

        for entry in entries:
            found = False

            # Quelle 1 & 2: release_year, year
            for field in ("release_year", "year"):
                val = entry.get(field)
                if val:
                    try:
                        y = int(str(val).strip()[:4])
                        if self.YEAR_MIN <= y <= self.YEAR_MAX:
                            year_counts[y] += 1
                            source_counts[field] += 1
                            found = True
                            break
                    except (ValueError, TypeError):
                        pass

            # Quelle 3: upload_date
            if not found:
                upload_date = entry.get("upload_date", "")
                if upload_date and len(str(upload_date)) >= 4:
                    try:
                        y = int(str(upload_date)[:4])
                        if self.YEAR_MIN <= y <= self.YEAR_MAX:
                            year_counts[y] += 1
                            source_counts["upload_date"] += 1
                            found = True
                    except (ValueError, TypeError):
                        pass

            # Quelle 4: Titel-Regex
            if not found:
                title_src = entry.get("title", "")
                if title_src:
                    y = self._extract_year_from_text(title_src)
                    if y:
                        year_counts[y] += 1
                        source_counts["title_regex"] += 1

        if not year_counts:
            self.logger.warning(
                "⚠️ [YEAR] Keine gültigen Jahreszahlen in Tracks gefunden"
            )
            return None

        dominant_year, count = year_counts.most_common(1)[0]
        total = len(entries)
        dominance_ratio = count / total

        self.logger.info(
            f"📊 [YEAR] Jahr-Statistik (Top 3 von {len(year_counts)} Jahren):"
        )
        for yr, cnt in year_counts.most_common(3):
            self.logger.info(f"   📅 {yr}: {cnt}/{total} ({cnt/total*100:.1f}%)")
        self.logger.info(
            f"   Quellen: {dict(source_counts)}\n"
            f"   Dominanz: {dominant_year} bei {dominance_ratio:.1%}"
        )

        if dominance_ratio >= 0.3:
            self.logger.info(
                f"✅ [YEAR] Dominantes Jahr: {dominant_year} ({dominance_ratio:.1%})"
            )
        else:
            self.logger.info(
                f"⚠️ [YEAR] Schwache Dominanz ({dominance_ratio:.1%}), "
                f"verwende trotzdem: {dominant_year}"
            )

        return dominant_year

    # ─────────────────────────────────────────────────────────────────────────
    # Private Hilfsmethoden
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_year_from_text(self, text: str) -> Optional[int]:
        """
        Extrahiert eine vierstellige Jahreszahl (1950–2035) aus einem
        beliebigen String via Regex (`YEAR_PATTERN`).

        Funktioniert sowohl für Freitext-Titel ("Song (1987 Remaster)")
        als auch für `upload_date`-Strings im Format YYYYMMDD.
        """
        if not text:
            return None

        match = self.YEAR_PATTERN.search(text)
        if match:
            year = int(match.group())
            if self.YEAR_MIN <= year <= self.YEAR_MAX:
                return year

        return None