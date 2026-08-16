# -*- coding: utf-8 -*-
# yt_music_bot/utils/mapping/test_genre_map.py

import sys
from pathlib import Path

# Füge das übergeordnete Verzeichnis zum Python-Pfad hinzu, um genre_map.py zu importieren
sys.path.append(str(Path(__file__).parent.parent))

from utils.genre_map import GenreMapper

# Erstelle eine globale Instanz der Klasse für alle Tests
mapper = GenreMapper(mapping_dir=str(Path(__file__).parent.name))


def test_regex_matching():
    """Testet die direkte Erkennung via Regex."""
    genre = mapper.determine_genre(
        raw_genre="Some German Deutschrap Song",
        artist_name="Unknown Artist",
        channel_name="Some Channel",
    )
    assert genre == "Deutschrap"


def test_exact_channel_fallback():
    """Testet den Fallback auf einen exakten Kanalnamen."""
    genre = mapper.determine_genre(
        raw_genre=None, artist_name="Ein Künstler", channel_name="kontor.tv"
    )
    assert genre == "Electronic"


def test_fuzzy_channel_fallback():
    """Testet den Fallback auf einen Kanalnamen mit Tippfehler (Fuzzy-Matching)."""
    genre = mapper.determine_genre(
        raw_genre=None, artist_name="Ein Künstler", channel_name="lofi grl"
    )
    assert genre == "Lo-Fi"


def test_artist_fallback_primary_genre():
    """Testet den Fallback auf einen Künstler."""
    genre = mapper.determine_genre(
        raw_genre="some stuff", artist_name="kygo", channel_name="Ein VLOG Kanal"
    )
    assert genre == "Chill House"


def test_artist_fallback_fuzzy_match():
    """Testet den Fallback auf einen Künstler mit anderer Schreibweise (Fuzzy-Matching)."""
    genre = mapper.determine_genre(
        raw_genre=None, artist_name="boehse onkelz", channel_name=None
    )
    assert genre == "Rock"


def test_no_match_returns_none():
    """Testet den Fall, wenn kein Genre gefunden wird."""
    genre = mapper.determine_genre(
        raw_genre=None,
        artist_name="Ganz Unbekannter Interpret",
        channel_name="Seltsamer Kanal",
    )
    assert genre is None


def test_hierarchy_mapping():
    """Testet die korrekte Zuordnung eines Sub-Genres zu einem Haupt-Genre."""
    main_genre = mapper.get_main_genre("Deep House")
    assert main_genre == "Deep House"


def test_new_artist_match():
    """Testet den Fallback für einen neuen Künstler wie Sarah Connor."""
    genre = mapper.determine_genre(
        raw_genre=None, artist_name="Sarah Connor", channel_name=None
    )
    assert genre == "Pop"
