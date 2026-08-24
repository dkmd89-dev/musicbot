#!/usr/bin/env python3
"""Unit tests für Metadata-Module (TitleCleaner, ArtistProcessor, etc.)"""

import sys
import unittest
from pathlib import Path

# Füge Projekt-Root zum Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.metadata.title_cleaner import TitleCleaner
from services.metadata.artist_processor import ArtistProcessor
from utils.artist_map import ArtistNormalizer, ArtistConfig


class TestTitleCleaner(unittest.TestCase):
    """Test-Suite für TitleCleaner"""
    
    def setUp(self):
        self.cleaner = TitleCleaner()
    
    def test_clean_youtube_title_basic(self):
        """Standard YouTube Titel mit Artist"""
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Song Title - Artist Name (Official Video)",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Artist Name",
            was_parsed_by_artist_map=False
        )
        # Erwartet: "Song Title" (Artist wird entfernt)
        self.assertEqual(result, "Song Title")
    
    def test_clean_youtube_title_without_artist(self):
        """YouTube Titel ohne Artist-Angabe"""
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Song Title (Official Music Video)",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Artist Name",
            was_parsed_by_artist_map=False
        )
        self.assertEqual(result, "Song Title")
    
    def test_clean_title_with_feat(self):
        """Titel mit Featuring"""
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Song Title (feat. Guest Artist)",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Main Artist",
            was_parsed_by_artist_map=False
        )
        self.assertEqual(result, "Song Title")

    def test_clean_title_with_ft_substring_word_is_not_mangled(self):
        """
        Regressionstest fuer ARTISTNORM-002: das feat/ft-Cleanup-Pattern
        matchte vorher "ft" als reinen Teilstring ohne Wortgrenzen - ein
        Titel wie "Wir trafen Kraftklub gestern" haette alles ab dem "ft" in
        "Kraftklub" bis zum Titelende geloescht. final_artist ist hier
        bewusst neutral gehalten (nicht im Titel enthalten), um den Effekt
        isoliert von remove_artist_from_title() zu pruefen.
        """
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Wir trafen Kraftklub gestern",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Reporter XY",
            was_parsed_by_artist_map=False
        )
        self.assertEqual(result, "Wir trafen Kraftklub gestern")

    def test_clean_title_with_explicit(self):
        """Titel mit (explicit) Markierung"""
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Song Title (explicit)",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Artist",
            was_parsed_by_artist_map=False
        )
        self.assertEqual(result, "Song Title")
    
    def test_clean_title_with_brackets(self):
        """Titel mit eckigen Klammern"""
        result = self.cleaner.clean_track_title_enhanced(
            original_title="Song Title [Official Video]",
            parsed_title=None,
            parsed_artist=None,
            final_artist="Artist",
            was_parsed_by_artist_map=False
        )
        self.assertEqual(result, "Song Title")
    
    def test_apply_cleanup_rules(self):
        """Direkter Test der Cleanup-Regeln"""
        test_cases = [
            ("Song Title - Artist (Official Video)", "Song Title - Artist"),
            ("Song Title (Official Music Video)", "Song Title"),
            ("Song Title [Official Video]", "Song Title"),
            ("Song Title (explicit) [HD]", "Song Title"),
            ("Song Title | Official Video", "Song Title"),
            ("Song Title - Topic", "Song Title"),
        ]
        for input_title, expected in test_cases:
            with self.subTest(input_title=input_title):
                result = self.cleaner.apply_title_cleanup_rules(input_title)
                self.assertEqual(result, expected)


class TestArtistProcessor(unittest.TestCase):
    """Test-Suite für ArtistProcessor"""
    
    def setUp(self):
        # ArtistNormalizer mit temporären Pfaden (Path Objekte!)
        temp_dir = Path("/tmp/test_library")
        temp_dir.mkdir(exist_ok=True)
        
        artist_config = ArtistConfig(
            library_dir=temp_dir,  # Path Objekt!
            override_file=Path("/tmp/test_overrides.json")  # Path Objekt!
        )
        normalizer = ArtistNormalizer(artist_config)
        self.artist_processor = ArtistProcessor(artist_normalizer=normalizer)
    
    def test_determine_best_artist_with_dominant(self):
        """Dominant Artist hat Vorrang"""
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist="Raw Artist",
            parsed_artist="Parsed Artist",
            dominant_artist="Dominant Artist",
            channel_name="Channel"
        )
        self.assertEqual(result, "Dominant Artist")
        self.assertEqual(source, "playlist_dominant")
        self.assertEqual(feat_artists, [])

    def test_determine_best_artist_with_parsed(self):
        """Parsed Artist wenn kein Dominant"""
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist=None,
            parsed_artist="Parsed Artist",
            dominant_artist=None,
            channel_name="Channel"
        )
        self.assertEqual(result, "Parsed Artist")
        self.assertEqual(source, "youtube_parsed")
        self.assertEqual(feat_artists, [])

    def test_determine_best_artist_with_raw(self):
        """Raw Artist als Fallback"""
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist="Raw Artist",
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel"
        )
        self.assertEqual(result, "Raw Artist")
        self.assertEqual(source, "raw_metadata")
        self.assertEqual(feat_artists, [])

    def test_determine_best_artist_with_channel_fallback(self):
        """Channel Name als letzter Fallback"""
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist=None,
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel Only"
        )
        self.assertEqual(result, "Channel Only")
        self.assertEqual(source, "channel_fallback")
        self.assertEqual(feat_artists, [])

    def test_determine_best_artist_splits_main_from_feature_single_separator(self):
        """
        ARTIST-001-Fix: Haupt-/Feature-Trennung passiert VOR der
        Normalisierung, nicht danach - der Hauptartist bleibt korrekt,
        das Feature landet separat in feat_artists statt im Hauptartist-
        String verschmolzen zu werden.
        """
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist="1986zig feat. GReeeN",
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel"
        )
        self.assertEqual(result, "1986zig")
        self.assertEqual(feat_artists, ["GReeeN"])

    def test_determine_best_artist_keeps_compound_main_artist_with_mixed_separators(self):
        """
        Der eigentliche Bug-Fall: "GReeeN & 1986zig feat. Bausa" - vorher
        wurde "1986zig" faelschlich zum Feature degradiert, weil
        ArtistNormalizer.normalize() den kompletten String zu einer
        gleichrangigen Komma-Liste abflachte, BEVOR eine Haupt-/Feature-
        Trennung stattfand. Jetzt wird zuerst getrennt (main="GReeeN &
        1986zig", feat=["Bausa"]) und nur der Hauptteil normalisiert -
        "1986zig" bleibt Teil des Hauptartists, nicht Feature.
        """
        result, source, feat_artists = self.artist_processor.determine_best_artist(
            raw_artist="GReeeN & 1986zig feat. Bausa",
            parsed_artist=None,
            dominant_artist=None,
            channel_name="Channel"
        )
        self.assertIn("1986zig", result)
        self.assertNotIn("1986zig", [f.lower() for f in feat_artists])
        self.assertEqual([f.lower() for f in feat_artists], ["bausa"])
    
    def test_clean_artist_before_normalization(self):
        """Bereinigung von Artist-Namen"""
        test_cases = [
            ("Artist Name - Topic", "Artist Name"),
            ("Artist, Name", "Artist"),
            ("2024/2025", ""),
            ("Artist - Topic VE VO", "Artist"),
            ("Artist Name - Topic VE VO", "Artist Name"),
        ]
        for input_artist, expected in test_cases:
            with self.subTest(input_artist=input_artist):
                result = self.artist_processor.clean_artist_before_normalization(input_artist)
                self.assertEqual(result, expected)


class TestIntegration(unittest.TestCase):
    """Integrationstests zwischen Modulen"""
    
    def test_title_cleaner_with_artist_processor(self):
        """Integration: Titel-Bereinigung mit Artist-Bestimmung"""
        cleaner = TitleCleaner()
        
        # ArtistProcessor initialisieren
        temp_dir = Path("/tmp/test_library")
        temp_dir.mkdir(exist_ok=True)
        
        artist_config = ArtistConfig(
            library_dir=temp_dir,
            override_file=Path("/tmp/test_overrides.json")
        )
        normalizer = ArtistNormalizer(artist_config)
        artist_processor = ArtistProcessor(artist_normalizer=normalizer)
        
        # Simuliere einen kompletten Track
        original_title = "Shape of You - Ed Sheeran (Official Music Video)"
        
        # Bestimme Artist
        final_artist, source, _feat_artists = artist_processor.determine_best_artist(
            raw_artist="Ed Sheeran",
            parsed_artist=None,
            dominant_artist="Ed Sheeran",
            channel_name="Ed Sheeran"
        )
        self.assertEqual(final_artist, "Ed Sheeran")
        self.assertEqual(source, "playlist_dominant")
        
        # Bereinige Titel
        cleaned_title = cleaner.clean_track_title_enhanced(
            original_title=original_title,
            parsed_title=None,
            parsed_artist=None,
            final_artist=final_artist,
            was_parsed_by_artist_map=False
        )
        # Sollte "Shape of You" sein (ohne Artist und Suffix)
        self.assertEqual(cleaned_title, "Shape of You")


if __name__ == '__main__':
    # Führe Tests mit Detailausgabe aus
    unittest.main(verbosity=2)
