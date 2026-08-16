# -*- coding: utf-8 -*-
# yt_music_bot/utils/artist_map.py
"""
Modul zur Normalisierung von Künstlernamen für Musikdaten aus YouTube.

Features:
- Lädt Künstler aus Bibliotheksverzeichnis
- Unterstützt manuelle Overrides per JSON
- Erweitert automatisch mit neuen Künstlern
- Robustes Handling von Kollaborationen
- Konsistente Namensnormalisierung
- YouTube-Titel-Parsing mit Artist-Extraktion
- Umfangreiches Logging mit Emojis
"""

import re
import json
import string
import unicodedata
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional, Pattern
from dataclasses import dataclass
import logging
import tempfile
import shutil
from datetime import datetime

# 🔥 NEU: Erweitertes Logging importieren
from enhanced_logging import get_module_logger

logger = get_module_logger("artist_map")

# 🔹 Immer zuerst versuchen, die echte Config zu laden
try:
    from config import Config  # Produktionsbetrieb

    logger.debug("🔧 Config erfolgreich aus Produktionsumgebung geladen")
except ImportError:
    # 🔹 Fallback nur für Standalone-Tests gedacht
    class Config:
        LIBRARY_DIR = Path("./temp_music_library")
        ARTIST_OVERRIDE_FILE = Path("./temp_artist_overrides.json")

    logger.warning("⚠️ Fallback-Config verwendet - nur für Tests geeignet")


@dataclass
class ArtistConfig:
    """Konfiguration für Artist Normalisierung"""

    library_dir: Path = Config.LIBRARY_DIR
    override_file: Path = Config.ARTIST_OVERRIDE_FILE
    collab_separators: set[str] = frozenset(
        {" x ", " & ", ", ", " with ", " feat. ", " ft. ", " vs. "}
    )
    replace_patterns: dict[str, str] | None = None


class ArtistNormalizer:
    """Hauptklasse für Künstlernamen-Normalisierung und YouTube-Titel-Parsing"""

    def __init__(self, config: ArtistConfig):
        self.config = config
        self.overrides: Dict[str, str] = {}
        self.library_artists: Set[str] = set()
        self.compiled_rules: List[Tuple[Pattern, str]] = []
        self.artist_patterns: List[Tuple[str, str]] = []  # Für YouTube-Parsing

        self._initialize()

    def _initialize(self):
        self._load_resources()
        self._compile_rules()
        self._build_artist_patterns()

        logger.info(
            f"✅ ArtistNormalizer erfolgreich initialisiert! "
            f"{len(self.overrides)} Overrides, "
            f"{len(self.library_artists)} Library-Künstler, "
            f"{len(self.artist_patterns)} Artist-Patterns, "
            f"{len(self.compiled_rules)} Normalisierungsregeln kompiliert"
        )

    def _load_resources(self):
        self.library_artists = self._load_library_artists()
        self.overrides = self._load_overrides()

    def _load_library_artists(self) -> Set[str]:
        """
        📁 Lädt Künstlernamen aus den Unterverzeichnissen der Musikbibliothek.
        """
        logger.info(f"🔍 Lade Künstlernamen aus Bibliothek: {self.config.library_dir}")
        if not self.config.library_dir.is_dir():
            logger.warning("⚠️ Bibliothek-Verzeichnis nicht gefunden, überspringe.")
            return set()

        artists = {d.name for d in self.config.library_dir.iterdir() if d.is_dir()}
        logger.info(f"✅ {len(artists)} Künstler aus Bibliothek geladen.")
        return artists

    def _load_overrides(self) -> Dict[str, str]:
        """
        📄 Lädt die manuellen Overrides aus einer JSON-Datei.
        """
        logger.info(f"🔍 Lade Artist-Overrides aus: {self.config.override_file}")
        if not self.config.override_file.is_file():
            logger.warning("⚠️ Override-Datei nicht gefunden, starte ohne Overrides.")
            return {}

        try:
            with open(self.config.override_file, "r", encoding="utf-8") as f:
                overrides = json.load(f)
                logger.info(f"✅ {len(overrides)} Overrides geladen.")
                return {self._normalize_key(k): v for k, v in overrides.items()}
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"❌ Fehler beim Laden der Override-Datei: {e}", exc_info=True)
            return {}

    def _compile_rules(self):
        """
        ⚙️ Kompiliert reguläre Ausdrücke für die Normalisierung von Titel-Tags.
        """
        self.compiled_rules = [
            (re.compile(r"\(?official (music )?video\)?", re.I), ""),
            (re.compile(r"\(?lyrics? video\)?", re.I), ""),
            (re.compile(r"\(?audio\)?", re.I), ""),
            (re.compile(r"\(?visualizer\)?", re.I), ""),
            (re.compile(r"\[.*?\]", re.I), ""),
            (re.compile(r"\(?feat\.?.*? ft\.?.*?\)"), ""),
        ]
        logger.debug("⚙️ Normalisierungsregeln kompiliert.")

    def _build_artist_patterns(self):
        """
        🛠️ Erstellt reguläre Ausdrücke aus Overrides und Bibliothek-Künstlern.
        """
        all_artists = self.library_artists.union(set(self.overrides.values()))
        escaped_artists = [
            re.escape(a) for a in sorted(list(all_artists), key=len, reverse=True)
        ]
        if not escaped_artists:
            return

        artist_pattern = "|".join(escaped_artists)
        separator_pattern = "|".join(
            [re.escape(s) for s in self.config.collab_separators]
        )

        # NEU: Zusätzliche Muster für die saubere Artist-Extraktion aus Titel
        self.artist_patterns = [
            (rf"({artist_pattern})(?:{separator_pattern}|\s?)(.*)", r"\1", "start"),
            (
                rf"(.*)(?:{separator_pattern}|\s?)\s?({artist_pattern})(.*)",
                r"\2",
                "end",
            ),
        ]
        logger.info(f"✅ {len(all_artists)} Artist-Patterns für Parsing erstellt.")

    def normalize_name(self, name: str) -> str:
        """
        ✨ Normalisiert einen Künstlernamen. Priorisiert Overrides, dann Standard-Normalisierung.
        """
        logger.debug(f"✨ Normalisiere: '{name}'")

        # 1. Override prüfen
        override = self._get_override(name)
        if override:
            logger.info(f"➡️ Override gefunden: '{name}' → '{override}'")
            return override

        # 2. Standard-Normalisierung
        normalized = self._standard_normalization(name)
        return normalized

    def parse_artist_from_title(
        self, title: str, fallback_artist: str
    ) -> Tuple[str, str]:
        """
        🔍 Extrahiert Artist und bereinigten Titel aus einem YouTube-Titel.
        """
        cleaned_title = self.clean_youtube_title(title)
        best_artist = fallback_artist

        # 1. Check for artists in the title using collaboration separators
        for pattern_str, replacement_str, position in self.artist_patterns:
            match = re.search(pattern_str, title, re.IGNORECASE)
            if match:
                extracted_artist = match.group(2).strip()
                if extracted_artist:
                    cleaned_title = re.sub(
                        pattern_str, replacement_str, title, flags=re.IGNORECASE
                    ).strip()
                    best_artist = self.normalize_name(extracted_artist)
                    logger.info(f"✅ Artist aus Titel extrahiert: '{best_artist}'")
                    break

        # 2. Check for artists from YouTube tags in the fallback artist
        if fallback_artist:
            # Check if fallback artist is a normalized library artist
            normalized_fallback = self.normalize_name(fallback_artist)
            if (
                normalized_fallback in self.library_artists
                or normalized_fallback in self.overrides.values()
            ):
                best_artist = normalized_fallback
                logger.info(f"✅ Fallback-Artist als gültig erkannt: '{best_artist}'")

        # Ensure a final check if artist from title is in library/overrides
        if best_artist != fallback_artist:
            final_normalized_artist = self.normalize_name(best_artist)
            if (
                final_normalized_artist in self.library_artists
                or final_normalized_artist in self.overrides.values()
            ):
                best_artist = final_normalized_artist
            else:
                best_artist = (
                    fallback_artist  # Fallback if extracted artist is not valid
                )

        return best_artist, cleaned_title

    def clean_youtube_title(self, title: str) -> str:
        """
        🧹 Entfernt unerwünschte Tags aus dem YouTube-Titel.
        """
        cleaned_title = title
        for pattern, replacement in self.compiled_rules:
            cleaned_title = pattern.sub(replacement, cleaned_title)

        # Zusätzliche Bereinigung
        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
        cleaned_title = cleaned_title.strip(" -")
        return cleaned_title

    def _get_override(self, name: str) -> Optional[str]:
        """
        🎯 Sucht einen Override-Namen.
        """
        normalized_key = self._normalize_key(name)
        result = self.overrides.get(normalized_key)
        if result:
            logger.debug(f"🎯 Override gefunden für '{name}': '{result}'")
            return result

        logger.debug(f"📋 Kein Override gefunden für: '{name}'")
        return None

    def _normalize_key(self, key: str) -> str:
        """🔑 Normalisiert Schlüssel für Override-Lookup"""
        normalized = key.lower().strip()
        logger.debug(f"🔑 Key normalisiert: '{key}' → '{normalized}'")
        return normalized

    def _standard_normalization(self, name: str) -> str:
        """✨ Standard-Normalisierung: Kapitalisierung von Wörtern"""
        logger.debug(f"✨ Starte Standard-Normalisierung für: '{name}'")

        capitalized_word_groups = []
        words = name.split(" ")

        logger.debug(f"   📝 Zu verarbeitende Wörter: {words}")

        for word in words:
            if not word:
                continue

            # Bindestriche in Wörtern behandeln
            if "-" in word:
                parts = word.split("-")
                capitalized_parts = [p.capitalize() for p in parts if p]
                capitalized_word = "-".join(capitalized_parts)
                logger.debug(
                    f"      Wort mit Bindestrich: '{word}' → '{capitalized_word}'"
                )
            else:
                capitalized_word = word.capitalize()
                logger.debug(f"      Einfaches Wort: '{word}' → '{capitalized_word}'")

            capitalized_word_groups.append(capitalized_word)

        result = " ".join(capitalized_word_groups)
        logger.debug(f"🏁 Standard-Normalisierung abgeschlossen: '{name}' → '{result}'")
        return result


if __name__ == "__main__":
    """
    Ein einfacher Test-Block für die ArtistNormalizer-Klasse.
    Erstellt ein temporäres Verzeichnis und Testdateien, um das Modul isoliert zu prüfen.
    """
    print("🚀 Starte ArtistNormalizer-Tests...")
    temp_dir = Path(tempfile.mkdtemp())
    temp_library = temp_dir / "temp_music_library"
    temp_overrides = temp_dir / "temp_artist_overrides.json"
    temp_library.mkdir()

    # Temporäre Künstler-Verzeichnisse erstellen
    Path(temp_library / "Eminem").mkdir()
    Path(temp_library / "Rihanna").mkdir()
    Path(temp_library / "Linkin Park").mkdir()

    # Temporäre Override-Datei erstellen
    test_overrides = {
        "eminem": "Eminem",
        "linkin park": "Linkin Park",
        "ladygaga": "Lady Gaga",
        "linkin park vs. jay-z": "Linkin Park & Jay-Z",
        "jay-z": "Jay-Z",
    }
    with open(temp_overrides, "w", encoding="utf-8") as f:
        json.dump(test_overrides, f, indent=4)

    # Konfiguration für den Test
    test_config = ArtistConfig(library_dir=temp_library, override_file=temp_overrides)

    # ArtistNormalizer initialisieren
    normalizer = ArtistNormalizer(test_config)

    # Testfälle für die Normalisierung
    test_cases_normalization = {
        "eminem": "Eminem",
        "linkin park": "Linkin Park",
        "lady gaga": "Lady Gaga",  # Wird über Override gefunden
        "linkin park ft. jay-z": "Linkin Park & Jay-Z",  # Wird über Override gefunden
        "Eminem Feat. Rihanna": "Eminem Feat. Rihanna",  # Kollaboration, wird nicht normalisiert
        "Daft Punk": "Daft Punk",  # Nicht im Override, nur Standard-Normalisierung
    }

    print("\n📝 Teste Künstlernamen-Normalisierung...")
    for input_name, expected_name in test_cases_normalization.items():
        result = normalizer.normalize_name(input_name)
        status = "✅" if result == expected_name else "❌"
        print(f"{status} '{input_name}' -> '{result}' (Erwartet: '{expected_name}')")
        if result != expected_name:
            print(f"   ⚠️ Fehler: Normalisierungs-Test fehlgeschlagen!")

    # Testfälle für Titel-Parsing
    test_cases_parsing = {
        "Eminem - 'Lose Yourself' (Official Music Video)": ("Eminem", "Lose Yourself"),
        "Linkin Park vs. Jay-Z - Numb/Encore": ("Linkin Park & Jay-Z", "Numb/Encore"),
        "Lady Gaga - Poker Face (Audio)": ("Lady Gaga", "Poker Face"),
        "A Random Artist - A Song [Lyrics Video]": ("A Random Artist", "A Song"),
        "A Song": ("Default Artist", "A Song"),  # Fallback-Artist wird verwendet
        "feat. Jay-Z & Linkin Park - In the End": ("Jay-Z & Linkin Park", "In the End"),
    }

    print("\n📝 Teste Titel-Parsing...")
    for input_title, (expected_artist, expected_title) in test_cases_parsing.items():
        fallback_artist = "Default Artist"
        result_artist, result_title = normalizer.parse_artist_from_title(
            input_title, fallback_artist
        )

        status_artist = "✅" if result_artist == expected_artist else "❌"
        status_title = "✅" if result_title == expected_title else "❌"

        print(
            f"{status_artist} Artist: '{result_artist}' (Erwartet: '{expected_artist}')"
        )
        print(f"{status_title} Title:  '{result_title}' (Erwartet: '{expected_title}')")
        if result_artist != expected_artist or result_title != expected_title:
            print(f"   ⚠️ Fehler: Parsing-Test fehlgeschlagen!")

    # Aufräumen der temporären Dateien
    shutil.rmtree(temp_dir)
    print("\n✅ Aufräumarbeiten abgeschlossen.")
    print("🎉 ArtistNormalizer-Tests erfolgreich beendet!")

    """
    Ein einfacher Test-Block für die ArtistNormalizer-Klasse.
    Erstellt ein temporäres Verzeichnis und Testdateien, um das Modul isoliert zu prüfen.
    """
    print("🚀 Starte ArtistNormalizer-Tests...")
    temp_dir = Path(tempfile.mkdtemp())
    temp_library = temp_dir / "temp_music_library"
    temp_overrides = temp_dir / "temp_artist_overrides.json"
    temp_library.mkdir()

    # Temporäre Künstler-Verzeichnisse erstellen
    Path(temp_library / "Eminem").mkdir()
    Path(temp_library / "Rihanna").mkdir()
    Path(temp_library / "Linkin Park").mkdir()

    # Temporäre Override-Datei erstellen
    test_overrides = {
        "eminem": "Eminem",
        "linkin park": "Linkin Park",
        "ladygaga": "Lady Gaga",
        "linkin park vs. jay-z": "Linkin Park & Jay-Z",
        "jay-z": "Jay-Z",
    }
    with open(temp_overrides, "w", encoding="utf-8") as f:
        json.dump(test_overrides, f, indent=4)

    # Konfiguration für den Test
    test_config = ArtistConfig(library_dir=temp_library, override_file=temp_overrides)

    # ArtistNormalizer initialisieren
    normalizer = ArtistNormalizer(test_config)

    # Testfälle für die Normalisierung
    test_cases_normalization = {
        "eminem": "Eminem",
        "linkin park": "Linkin Park",
        "lady gaga": "Lady Gaga",  # Wird über Override gefunden
        "linkin park ft. jay-z": "Linkin Park & Jay-Z",  # Wird über Override gefunden
        "Eminem Feat. Rihanna": "Eminem Feat. Rihanna",  # Kollaboration, wird nicht normalisiert
        "Daft Punk": "Daft Punk",  # Nicht im Override, nur Standard-Normalisierung
    }

    print("\n📝 Teste Künstlernamen-Normalisierung...")
    for input_name, expected_name in test_cases_normalization.items():
        result = normalizer.normalize_name(input_name)
        status = "✅" if result == expected_name else "❌"
        print(f"{status} '{input_name}' -> '{result}' (Erwartet: '{expected_name}')")
        if result != expected_name:
            print(f"   ⚠️ Fehler: Normalisierungs-Test fehlgeschlagen!")

    # Testfälle für Titel-Parsing
    test_cases_parsing = {
        "Eminem - 'Lose Yourself' (Official Music Video)": ("Eminem", "Lose Yourself"),
        "Linkin Park vs. Jay-Z - Numb/Encore": ("Linkin Park & Jay-Z", "Numb/Encore"),
        "Lady Gaga - Poker Face (Audio)": ("Lady Gaga", "Poker Face"),
        "A Random Artist - A Song [Lyrics Video]": ("A Random Artist", "A Song"),
        "A Song": ("Default Artist", "A Song"),  # Fallback-Artist wird verwendet
        "feat. Jay-Z & Linkin Park - In the End": ("Jay-Z & Linkin Park", "In the End"),
    }

    print("\n📝 Teste Titel-Parsing...")
    for input_title, (expected_artist, expected_title) in test_cases_parsing.items():
        fallback_artist = "Default Artist"
        result_artist, result_title = normalizer.parse_artist_from_title(
            input_title, fallback_artist
        )

        status_artist = "✅" if result_artist == expected_artist else "❌"
        status_title = "✅" if result_title == expected_title else "❌"

        print(
            f"{status_artist} Artist: '{result_artist}' (Erwartet: '{expected_artist}')"
        )
        print(f"{status_title} Title:  '{result_title}' (Erwartet: '{expected_title}')")
        if result_artist != expected_artist or result_title != expected_title:
            print(f"   ⚠️ Fehler: Parsing-Test fehlgeschlagen!")

    # Aufräumen der temporären Dateien
    shutil.rmtree(temp_dir)
    print("\n✅ Aufräumarbeiten abgeschlossen.")
    print("🎉 ArtistNormalizer-Tests erfolgreich beendet!")
