"""
Unit-Tests für CacheManager (services/downloader/download/cache_manager.py)
— vorher 0 Tests, live in EnhancedDownloadProcessor._do_init() verdrahtet
(download_utils.py), gefunden über die systematische Ungetestet-Prüfung.

Regressionstest fuer BUG-011: lookup_playlist_track()s Stufe 2 (ArtistMap-
Parsing-Fallback) rief parsed.get("main_artist")/parsed["main_artist"] auf
das Ergebnis von ArtistNormalizer.parse_youtube_title() auf - das liefert
aber ParseResult (ein Dataclass, KEIN Dict). .get()/[...] warfen dadurch
IMMER AttributeError/TypeError, vom umschliessenden except still auf
Debug-Level abgefangen - Stufe 2 hat nie funktioniert. Die Tests hier
nutzen bewusst das ECHTE ParseResult-Dataclass (nicht nur einen Mock mit
.get()), um den exakten Bug-Mechanismus reproduzierbar zu machen.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from services.downloader.download.cache_manager import CacheManager
from utils.artist_map import ParseResult


def make_cache_manager(metadata_cache=None, artist_normalizer=None):
    return CacheManager(
        metadata_cache=metadata_cache or Mock(),
        artist_normalizer=artist_normalizer,
        logger=Mock(),
    )


class TestLookupPlaylistTrackStage1:
    def test_stage1_hit_with_existing_file(self, tmp_path):
        cached_file = tmp_path / "song.mp3"
        cached_file.write_bytes(b"x")
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "Cached Title",
            "artist": "Cached Artist",
            "library_path": str(cached_file),
            "genres": ["Hip Hop"],
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        result = manager.lookup_playlist_track(
            track_info={"artist": "Cached Artist", "title": "Cached Title"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is not None
        assert result["success"] is True
        assert result["library_path"] == str(cached_file)
        assert result["from_cache"] is True
        metadata_cache.get.assert_called_once_with("Cached Artist", "Cached Title")

    def test_stage1_hit_carries_over_cover_and_loudness_flags(self, tmp_path):
        """
        Live-Fund 2026-09-02 (Nutzer-Report): _build_result() gab
        cover_embedded/loudness_normalized bisher gar nicht zurueck - ein
        Playlist-Cache-Treffer zeigte in der Telegram-Abschlussmeldung
        dadurch faelschlich "Cover fehlt"/"Loudness fehlt" fuer genau
        diesen Track, obwohl beides beim urspruenglichen Download (das
        den Cache-Eintrag erzeugte) tatsaechlich vorhanden war.
        """
        cached_file = tmp_path / "song.mp3"
        cached_file.write_bytes(b"x")
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "Cached Title",
            "artist": "Cached Artist",
            "library_path": str(cached_file),
            "genres": ["Hip Hop"],
            "cover_embedded": True,
            "loudness_normalized": True,
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        result = manager.lookup_playlist_track(
            track_info={"artist": "Cached Artist", "title": "Cached Title"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result["cover_embedded"] is True
        assert result["loudness_normalized"] is True

    def test_stage1_hit_missing_flags_in_old_cache_entry_default_to_false(self, tmp_path):
        """Rueckwaertskompatibilitaet: ein aelterer Cache-Eintrag ohne diese
        Felder (vor der Ergaenzung in services/metadata/cache.py) darf
        nicht crashen, sondern liefert False."""
        cached_file = tmp_path / "song.mp3"
        cached_file.write_bytes(b"x")
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "Cached Title",
            "artist": "Cached Artist",
            "library_path": str(cached_file),
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        result = manager.lookup_playlist_track(
            track_info={"artist": "Cached Artist", "title": "Cached Title"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result["cover_embedded"] is False
        assert result["loudness_normalized"] is False

    def test_stage1_hit_but_file_missing_falls_through(self, tmp_path):
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "T",
            "artist": "A",
            "library_path": str(tmp_path / "does_not_exist.mp3"),
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        result = manager.lookup_playlist_track(
            track_info={"artist": "A", "title": "T"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is None

    def test_dominant_artist_takes_priority_over_track_artist(self, tmp_path):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        manager = make_cache_manager(metadata_cache=metadata_cache)

        manager.lookup_playlist_track(
            track_info={"artist": "Track Artist", "title": "T"},
            dominant_artist="Dominant Artist",
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        metadata_cache.get.assert_called_once_with("Dominant Artist", "T")


class TestLookupPlaylistTrackStage2Bug011Regression:
    def test_stage2_hit_via_real_parse_result_dataclass(self, tmp_path):
        """
        BUG-011-Regressionstest: parse_youtube_title() liefert ein echtes
        ParseResult-Dataclass (kein Dict) - vor dem Fix waere hier ein
        AttributeError geworfen und still verschluckt worden, Stufe 2
        haette IMMER None geliefert statt eines Cache-Treffers.
        """
        cached_file = tmp_path / "song.mp3"
        cached_file.write_bytes(b"x")

        metadata_cache = Mock()
        # Stufe 1: Miss. Stufe 2 (alt_artist/alt_title): Hit.
        metadata_cache.get.side_effect = lambda artist, title: (
            {
                "title": "Alt Title",
                "artist": "Alt Artist",
                "library_path": str(cached_file),
            }
            if (artist, title) == ("Alt Artist", "Alt Title")
            else None
        )

        artist_normalizer = Mock()
        artist_normalizer.parse_youtube_title.return_value = ParseResult(
            original_title="Original YT Title",
            artists=["Alt Artist"],
            featuring=[],
            main_artist="Alt Artist",
            title="Alt Title",
            artist_string="Alt Artist",
        )

        manager = make_cache_manager(
            metadata_cache=metadata_cache, artist_normalizer=artist_normalizer
        )

        result = manager.lookup_playlist_track(
            track_info={
                "artist": "Raw Artist",
                "title": "Raw Title",
                "original_youtube_title": "Original YT Title",
            },
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=3,
        )

        assert result is not None
        assert result["success"] is True
        assert result["library_path"] == str(cached_file)
        assert result["artist_source"] == "artist_map_cache"
        assert result["title_cleaned"] is True

    def test_stage2_skipped_when_artist_normalizer_missing(self):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        manager = make_cache_manager(metadata_cache=metadata_cache, artist_normalizer=None)

        result = manager.lookup_playlist_track(
            track_info={"artist": "A", "title": "T", "original_youtube_title": "X"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is None

    def test_stage2_skipped_when_no_search_title_available(self):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        artist_normalizer = Mock()
        manager = make_cache_manager(
            metadata_cache=metadata_cache, artist_normalizer=artist_normalizer
        )

        result = manager.lookup_playlist_track(
            track_info={"artist": "A", "title": ""},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is None
        artist_normalizer.parse_youtube_title.assert_not_called()

    def test_stage2_parse_result_without_main_artist_is_a_miss(self):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        artist_normalizer = Mock()
        artist_normalizer.parse_youtube_title.return_value = ParseResult(
            original_title="X",
            artists=[],
            featuring=[],
            main_artist=None,
            title="X",
            artist_string=None,
        )
        manager = make_cache_manager(
            metadata_cache=metadata_cache, artist_normalizer=artist_normalizer
        )

        result = manager.lookup_playlist_track(
            track_info={"artist": "A", "title": "T", "original_youtube_title": "X"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is None

    def test_stage2_exception_is_caught_not_raised(self):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        artist_normalizer = Mock()
        artist_normalizer.parse_youtube_title.side_effect = RuntimeError("boom")
        manager = make_cache_manager(
            metadata_cache=metadata_cache, artist_normalizer=artist_normalizer
        )

        result = manager.lookup_playlist_track(
            track_info={"artist": "A", "title": "T", "original_youtube_title": "X"},
            dominant_artist=None,
            album_name="Album",
            playlist_year=2024,
            track_idx=1,
        )

        assert result is None  # darf nicht raisen


class TestLookupSingleTrack:
    def test_hit_with_existing_file(self, tmp_path):
        cached_file = tmp_path / "song.mp3"
        cached_file.write_bytes(b"x")
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "T",
            "artist": "A",
            "library_path": str(cached_file),
            "lyrics": "some lyrics",
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        result = manager.lookup_single_track("A", "T")

        assert result["success"] is True
        assert result["from_cache"] is True
        assert result["lyrics_available"] is True

    def test_miss_returns_none(self):
        metadata_cache = Mock()
        metadata_cache.get.return_value = None
        manager = make_cache_manager(metadata_cache=metadata_cache)

        assert manager.lookup_single_track("A", "T") is None

    def test_hit_but_file_missing_returns_none(self, tmp_path):
        metadata_cache = Mock()
        metadata_cache.get.return_value = {
            "title": "T",
            "artist": "A",
            "library_path": str(tmp_path / "gone.mp3"),
        }
        manager = make_cache_manager(metadata_cache=metadata_cache)

        assert manager.lookup_single_track("A", "T") is None
