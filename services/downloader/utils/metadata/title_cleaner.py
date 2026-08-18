# services/downloader/utils/metadata/title_cleaner.py
# -*- coding: utf-8 -*-

import re
from typing import Optional

from logger import get_module_logger


class TitleCleaner:
    """
    Verantwortlich für Titel-Bereinigung von YouTube-Titeln.
    Kapselt alle Regex-basierten Cleanup-Regeln sowie Heuristiken zum
    Entfernen von Artist-Präfixen, führenden Fragmenten und Marketing-Suffixen.
    """

    def __init__(self, logger=None):
        self.logger = logger or get_module_logger("TitleCleaner")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    def clean_track_title_enhanced(
        self,
        original_title: str,
        parsed_title: Optional[str],
        parsed_artist: Optional[str],
        final_artist: str,
        was_parsed_by_artist_map: bool = False,
        dominant_artist: Optional[str] = None,
        channel_name: Optional[str] = None,
    ) -> str:
        """
        Bereinigt einen YouTube-Titel vollständig.

        Reihenfolge:
          1. Nutze geparsten Titel (YouTube-Parser oder Artist-Map) wenn vorhanden
          2. Entferne führendes Fragment (Artist-Präfix)
          3. Entferne Artist-Namen aus dem Titel
          4. Wende allgemeine Cleanup-Regeln an
        """
        self.logger.debug(f"🎵 Starte Titel-Bereinigung für: {original_title}")

        title_to_clean = original_title
        if parsed_title and parsed_title.strip():
            stripped_parsed = parsed_title.strip()
            if len(stripped_parsed) >= 6 and not stripped_parsed.endswith("..."):
                source = "Artist-Map" if was_parsed_by_artist_map else "YouTube-Parser"
                self.logger.debug(
                    f"🎵 Nutze vor-geparsten Titel von {source}: {parsed_title}"
                )
                title_to_clean = stripped_parsed
            else:
                self.logger.debug(
                    f"🎵 Parsed-Titel zu kurz oder gekürzt, verwende original_title"
                )

        if " by " not in title_to_clean.lower():
            try:
                patterns = [
                    r"^(.{1,50}?)\s*[-–—:|]\s*(.+)",
                    r"^(.{1,50}?)\s+[-–—]\s+(.+)",
                ]
                for pattern in patterns:
                    match = re.match(pattern, title_to_clean)
                    if match:
                        leading = match.group(1).strip()
                        rest = match.group(2).strip()
                        should_remove_leading = self.should_remove_leading_fragment(
                            leading, rest, final_artist, parsed_artist, channel_name
                        )
                        if should_remove_leading:
                            self.logger.debug(
                                f"🎵 Entferne führendes Fragment: '{leading}' -> '{rest}'"
                            )
                            title_to_clean = rest
                            break
            except Exception as e:
                self.logger.debug(f"🎵 Fehler in führender Fragment-Heuristik: {e}")

        if final_artist:
            title_to_clean = self.remove_artist_from_title(title_to_clean, final_artist)
        if parsed_artist and parsed_artist != final_artist:
            title_to_clean = self.remove_artist_from_title(
                title_to_clean, parsed_artist
            )

        cleaned_title = self.apply_title_cleanup_rules(title_to_clean)

        if len(cleaned_title.strip()) < 2:
            self.logger.warning(
                "🎵 Titel-Bereinigung ergab zu kurzes Ergebnis, nutze Original"
            )
            cleaned_title = self.apply_title_cleanup_rules(original_title.strip())

        return cleaned_title.strip()

    def light_title_cleanup(self, title: str, artist: str) -> str:
        """
        Minimale Titel-Bereinigung für Fälle ohne YouTube-Parser-Ergebnis.
        Entfernt NUR offensichtliche YouTube-Suffixe und Artist-Präfixe.

        Diese Methode ist deutlich konservativer als clean_track_title_enhanced()
        und verändert den Titel kaum.

        Args:
            title: Originaler Titel
            artist: Künstlername (für Präfix-Entfernung)

        Returns:
            Bereinigter Titel
        """
        if not title:
            return ""

        cleaned = title.strip()

        # Nur die häufigsten YouTube-Suffixe entfernen
        cleaned = re.sub(
            r"\s*\(?\s*(?:official\s+)?(?:music\s+)?video\s*\)?\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        cleaned = re.sub(
            r"\s*\(?\s*audio\s*\)?\s*$", "", cleaned, flags=re.IGNORECASE
        ).strip()

        cleaned = re.sub(
            r"\s*\[(?:official|music|video|audio)\]\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        cleaned = re.sub(
            r"\s*\(?\s*lyric\s*video\s*\)?\s*$", "", cleaned, flags=re.IGNORECASE
        ).strip()

        # Artist-Präfix entfernen (z.B. "Ariana Grande - ")
        if artist:
            escaped_artist = re.escape(artist)
            cleaned = re.sub(
                rf"^{escaped_artist}\s*[-–—:|]\s*", "", cleaned, flags=re.IGNORECASE
            ).strip()

        # Mehrfache Leerzeichen normalisieren
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned if cleaned else title

    def build_search_title(
        self,
        parsed_title: Optional[str],
        original_title: str,
        final_artist: str,
    ) -> str:
        """
        Erzeugt einen bereinigten Such-Titel für externe Genre-APIs.
        Entfernt Versions-Klammern (UK Version, Remastered, etc.) aber
        NICHT den eigentlichen Songtitel.
        """
        base = (parsed_title or original_title or "").strip()

        version_patterns = [
            r"\s*\([^)]*\b(?:version|edit|mix|remaster(?:ed)?)\b[^)]*\)",
            r"\s*\([^)]*\b(?:uk|us|de|au|nz)\s+version\b[^)]*\)",
            r"\s*\(\s*\d{4}\s*(?:remaster|version)?\s*\)",
            r"\s*\[[^\]]*\b(?:version|edit|mix)\b[^\]]*\]",
        ]
        search = base
        for p in version_patterns:
            search = re.sub(p, "", search, flags=re.IGNORECASE).strip()

        if final_artist:
            esc = re.escape(final_artist)
            search = re.sub(
                rf"^{esc}\s*[-–—:]\s*", "", search, flags=re.IGNORECASE
            ).strip()

        search = re.sub(r"\s+", " ", search).strip()
        return (
            search
            if len(search) >= 2
            else (parsed_title or original_title or "").strip()
        )

    def should_remove_leading_fragment(
        self,
        leading: str,
        rest: str,
        final_artist: str,
        parsed_artist: Optional[str],
        channel_name: Optional[str],
    ) -> bool:
        """
        Entscheidet ob ein führendes Fragment (vor Trennzeichen) entfernt werden soll.
        Gibt True zurück wenn das Fragment ein Artist-Name oder kurzes Prefix ist.
        """
        if not leading or len(rest.strip()) < 3:
            return False

        leading_lower = leading.lower().strip()

        if final_artist and leading_lower == final_artist.lower():
            return True
        if parsed_artist and leading_lower == parsed_artist.lower():
            return True

        if channel_name:
            channel_primary = channel_name.split(" - ")[0].strip()
            if leading_lower == channel_primary.lower():
                return True

        for artist in [final_artist, parsed_artist]:
            if artist and len(artist) > 3:
                artist_lower = artist.lower()
                if leading_lower in artist_lower or artist_lower in leading_lower:
                    return True

        if len(leading.split()) <= 2 and len(leading) <= 25:
            if not any(char.isdigit() for char in leading):
                return True

        return False

    def remove_artist_from_title(self, title: str, artist: str) -> str:
        """
        Entfernt den Artist-Namen aus dem Titel wenn er als Präfix vorkommt.
        Berücksichtigt Trennzeichen wie -, –, —, :, |.
        """
        if not artist or not title or len(title.strip()) <= 3:
            return title

        escaped_artist = re.escape(artist)
        patterns = [
            rf"^{escaped_artist}\s*[-–—:|]\s*",
            rf"\b{escaped_artist}\b",
        ]

        for pattern in patterns:
            new_title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
            if new_title != title and len(new_title.strip()) >= 3:
                self.logger.debug(
                    f"🎵 Artist-Pattern entfernt: '{title}' -> '{new_title}'"
                )
                return new_title.strip()

        return title

    def apply_title_cleanup_rules(self, title: str) -> str:
        """
        Wendet alle Cleanup-Regeln auf einen Titel an:
        - Entfernt Marketing-Suffixe (Official Video, HD, etc.)
        - Entfernt Feature-Verweise
        - Entfernt Jahresangaben am Ende
        - Bereinigt übrig gebliebene Klammern/Trennzeichen
        """
        if not title:
            return ""

        cleanup_patterns = [
            (r"\s*\(Free\s+Download\)\s*", ""),
            (r"\s*\[Free\s+Download\]\s*", ""),
            # Streaming/Film-Placements
            (r"\s*\(\s*as\s+featured\s+in\b[^)]*\)", ""),
            (r"\s*\(\s*featured\s+in\b[^)]*\)", ""),
            (r"\s*\(\s*from\s+the\s+(?:movie|film|series|show|soundtrack)[^)]*\)", ""),
            (r"\s*\(\s*from\s+['\"].+?['\"][^)]*\)", ""),
            # Soundtrack-Hinweise
            (
                r"\s*\(?\s*original\s+motion\s+picture\s+soundtrack\s*\)?",
                "",
                re.IGNORECASE,
            ),
            (r"\s*\(\s*(?:soundtrack|score)\s+version\s*\)", ""),
            (r"\s*\(\s*(?:movie|film|tv|series)\s+version\s*\)", ""),
            # Edit/Version-Hinweise
            (
                r"\s*\(\s*(?:radio|single|club|extended|album)\s+(?:version|edit|mix)\s*\)",
                "",
            ),
            (r"\s*\(\s*edit\s*\)", ""),
            # Official Video mit Suffix
            (r"\s*\(\s*official\s+video\s*-[^)]+\)", ""),
            (r"\[.*?\]", ""),
            (r"\s*\(?\s*offiziell(?:es|er|em|en)?\s*(?:musik\s*)?video\s*\)?", ""),
            (r"\s*\(?\s*offiziell(?:es|er|em|en)?\s*\)?", ""),
            (r"\s+-\s+offiziell(?:es|er|em|en)?\s*(?:musik\s*)?video\s*$", ""),
            # Allgemeine Official/Video-Tags
            (
                r"\(?\s*(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo)"
                r"(?:\s+(?:official|music|lyric|video|audio|live|version|remaster|hd|4k|vevo))*"
                r"\s*\)?",
                "",
                re.IGNORECASE,
            ),
            # ARTISTNORM-002: \b-Wortgrenzen verhindern Fehltreffer in
            # Woertern, die "ft"/"feat" nur als Teilstring enthalten (z.B.
            # "trifft" -> vorher wurde alles ab dem Teilstring-Treffer bis
            # zum Titelende geloescht, siehe docs/MusicBot_ENGINEERING_BASELINE.md).
            (r"\s*[-–—]?\s*\b(?:feat\b\.?|ft\b\.?|featuring\b)\s+[^(\[\n]+", ""),
            (r"\s*\(?\s*\d{4}\s*\)?\s*$", ""),
            (r"\s*[-–—:|]\s*(?:official|music|video|audio|lyric|hd|4k).*?$", ""),
            (r"\s*\([^)]*$", ""),
            (r"\s*\[[^\]]*$", ""),
        ]

        cleaned = title
        for item in cleanup_patterns:
            old_cleaned = cleaned
            if len(item) == 3:
                pattern, replacement, flag = item
                cleaned = re.sub(pattern, replacement, cleaned, flags=flag).strip()
            else:
                pattern, replacement = item
                cleaned = re.sub(
                    pattern, replacement, cleaned, flags=re.IGNORECASE
                ).strip()
            if cleaned != old_cleaned:
                self.logger.debug(
                    f"🎵 Pattern angewendet: '{old_cleaned}' -> '{cleaned}'"
                )

        cleaned = re.sub(r"\s+", " ", cleaned.strip())
        cleaned = re.sub(r"^[-–—\s]+|[-–—\s]+$", "", cleaned)
        cleaned = re.sub(r"\s*\(\s*\)\s*", " ", cleaned).strip()
        cleaned = re.sub(r"\s*\[\s*\]\s*", " ", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()
