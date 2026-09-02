#!/usr/bin/env python3
"""Unit tests für AutoLearnManager"""

import sys
import unittest
import tempfile
import yaml
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Füge Projekt-Root zum Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper


class TestAutoLearnManager(unittest.TestCase):
    """Test-Suite für AutoLearnManager"""
    
    def setUp(self):
        """Initialisiere Test-Umgebung"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mapping_dir = Path(self.temp_dir.name) / "mapping"
        self.mapping_dir.mkdir()
        
        # Mock Config
        self.config = Mock()
        self.config.GENRE_MAPPING_DIR = self.mapping_dir
        
        # ArtistNormalizer mit temporärem Verzeichnis
        artist_config = ArtistConfig(
            library_dir=Path(self.temp_dir.name) / "library",
            override_file=Path(self.temp_dir.name) / "artist_overrides.json"
        )
        self.artist_normalizer = ArtistNormalizer(artist_config)
        
        # GenreMapper
        self.genre_mapper = GenreMapper(mapping_dir=self.mapping_dir)
        
        # AutoLearnManager
        self.auto_learn = AutoLearnManager(
            config=self.config,
            artist_normalizer=self.artist_normalizer,
            genre_mapper=self.genre_mapper
        )
    
    def tearDown(self):
        """Räume Test-Umgebung auf"""
        self.temp_dir.cleanup()
    
    def test_is_non_artist_channel(self):
        """Erkennung von Non-Artist Channels"""
        test_cases = [
            ("Artist Name - Topic", True),
            ("Artist Name VEVO", True),
            ("Various Artists", True),
            ("Music Channel", True),
            ("Real Artist Name", False),
            ("Official Music", True),
            ("John Doe", False),
            ("Topic Channel", True),
        ]
        
        for channel, expected in test_cases:
            with self.subTest(channel=channel):
                result = self.auto_learn._is_non_artist_channel(channel)
                self.assertEqual(result, expected, f"Failed for {channel}")
    
    def test_is_artist_known_empty(self):
        """Keine bekannten Artists initial"""
        result = self.auto_learn._is_artist_known("Unknown Artist")
        self.assertFalse(result)
    
    def test_is_artist_known_from_auto_learned(self):
        """Artist aus auto_learned_artist_aliases.yaml erkennen
        (ARCH-022: vorher auto_learned_artists.yaml)"""
        auto_file = self.mapping_dir / "auto_learned_artist_aliases.yaml"
        auto_data = {
            "auto_learned": {
                "raw alias": "Canonical Artist"
            }
        }
        with open(auto_file, "w", encoding="utf-8") as f:
            yaml.dump(auto_data, f)
        
        self.assertTrue(self.auto_learn._is_artist_known("Canonical Artist"))
        self.assertTrue(self.auto_learn._is_artist_known("canonical artist"))
        self.assertTrue(self.auto_learn._is_artist_known("raw alias"))
    
    def test_is_genre_already_learned_empty(self):
        """Keine gelernten Genres initial"""
        result = self.auto_learn._is_genre_already_learned("Test Artist")
        self.assertFalse(result)
    
    def test_is_genre_already_learned_from_manual(self):
        """Genre aus manueller YAML erkennen"""
        manual_file = self.mapping_dir / "artist_genre.yaml"
        manual_data = {
            "ARTIST_GENRE_MAP": {
                "Manual Artist": {
                    "primary": "Rock",
                    "secondary": ["Alternative"]
                }
            }
        }
        with open(manual_file, "w", encoding="utf-8") as f:
            yaml.dump(manual_data, f)
        
        result = self.auto_learn._is_genre_already_learned("Manual Artist")
        self.assertTrue(result)
    
    def test_is_genre_already_learned_case_insensitive(self):
        """Case-insensitive Suche"""
        manual_file = self.mapping_dir / "artist_genre.yaml"
        manual_data = {
            "ARTIST_GENRE_MAP": {
                "Manual Artist": {
                    "primary": "Rock",
                    "secondary": []
                }
            }
        }
        with open(manual_file, "w", encoding="utf-8") as f:
            yaml.dump(manual_data, f)
        
        self.assertTrue(self.auto_learn._is_genre_already_learned("manual artist"))
        self.assertTrue(self.auto_learn._is_genre_already_learned("MANUAL ARTIST"))
    
    def test_load_auto_learned_artists_empty(self):
        """Leere auto_learned_artist_aliases.yaml"""
        result = self.auto_learn._load_auto_learned_artists()
        self.assertEqual(result, {})

    def test_load_auto_learned_artists_with_data(self):
        """auto_learned_artist_aliases.yaml mit Daten (ARCH-022: vorher
        auto_learned_artists.yaml)"""
        auto_file = self.mapping_dir / "auto_learned_artist_aliases.yaml"
        test_data = {
            "auto_learned": {
                "alias1": "Artist1",
                "alias2": "Artist2"
            }
        }
        with open(auto_file, "w", encoding="utf-8") as f:
            yaml.dump(test_data, f)
        
        result = self.auto_learn._load_auto_learned_artists()
        self.assertEqual(result, test_data["auto_learned"])
    
    def test_load_auto_learned_genres_empty(self):
        """Leere auto_learned_genre.yaml"""
        result = self.auto_learn._load_auto_learned_genres()
        self.assertEqual(result, {})
    
    def test_load_auto_learned_genres_with_data(self):
        """auto_learned_genre.yaml mit Daten"""
        genre_file = self.mapping_dir / "auto_learned_genre.yaml"
        test_data = {
            "ARTIST_GENRE_MAP": {
                "Artist1": {"primary": "Rock", "secondary": []}
            }
        }
        with open(genre_file, "w", encoding="utf-8") as f:
            yaml.dump(test_data, f)
        
        result = self.auto_learn._load_auto_learned_genres()
        self.assertEqual(result, test_data["ARTIST_GENRE_MAP"])


class TestAutoLearnAsync(unittest.TestCase):
    """Async-Tests für AutoLearnManager"""
    
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mapping_dir = Path(self.temp_dir.name) / "mapping"
        self.mapping_dir.mkdir()
        
        self.config = Mock()
        self.config.GENRE_MAPPING_DIR = self.mapping_dir
        
        artist_config = ArtistConfig(
            library_dir=Path(self.temp_dir.name) / "library",
            override_file=Path(self.temp_dir.name) / "artist_overrides.json"
        )
        self.artist_normalizer = ArtistNormalizer(artist_config)
        self.genre_mapper = GenreMapper(mapping_dir=self.mapping_dir)
        
        self.auto_learn = AutoLearnManager(
            config=self.config,
            artist_normalizer=self.artist_normalizer,
            genre_mapper=self.genre_mapper
        )
    
    def tearDown(self):
        self.temp_dir.cleanup()
    
    def run_async(self, coro):
        """Helper um async Tests auszuführen"""
        return asyncio.run(coro)
    
    def test_learn_artist_valid_source(self):
        async def test():
            with patch.object(self.auto_learn, '_is_artist_known', return_value=False):
                result = await self.auto_learn.learn_artist(
                    raw_name="raw artist name",
                    canonical_name="Canonical Artist",
                    source="youtube_parsed",
                    channel_name="Some Channel"
                )
                return result
        
        result = self.run_async(test())
        self.assertTrue(result)
    
    def test_learn_artist_invalid_source(self):
        async def test():
            result = await self.auto_learn.learn_artist(
                raw_name="raw name",
                canonical_name="Canonical",
                source="manual_override",
                channel_name="Channel"
            )
            return result
        
        result = self.run_async(test())
        self.assertFalse(result)
    
    def test_learn_artist_same_as_canonical(self):
        """
        Identitaets-Mapping (raw_name == canonical_name) ist laut Docstring
        von learn_artist() KEIN Alias, sondern eine Bestaetigung eines
        bekannten Kuenstlers - das geht nach known_artists.yaml (nicht
        auto_learned_artist_aliases.yaml) und liefert bei erfolgreichem Schreiben
        True, kein No-Op/False (STALE-TEST-Fix, vorher fehlerhafte Erwartung).
        """
        async def test():
            result = await self.auto_learn.learn_artist(
                raw_name="Same Name",
                canonical_name="Same Name",
                source="youtube_parsed",
                channel_name="Channel"
            )
            return result

        result = self.run_async(test())
        self.assertTrue(result)

        known_file = self.mapping_dir / "known_artists.yaml"
        self.assertTrue(known_file.exists())
        with open(known_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIn("Same Name", data["known_artists"])
    
    def test_learn_genre_new(self):
        async def test():
            with patch.object(self.auto_learn, '_is_genre_already_learned', return_value=False):
                class GenreInfo:
                    primary = "Electronic"
                    secondary = ["House", "Techno"]
                    source = "lastfm"
                    raw_tags = ["electronic", "house", "techno"]
                
                result = await self.auto_learn.learn_genre(
                    canonical_name="New Artist",
                    genre_result=GenreInfo(),
                    raw_name="new artist"
                )
                return result
        
        result = self.run_async(test())
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
