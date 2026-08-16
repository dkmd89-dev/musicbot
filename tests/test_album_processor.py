#!/usr/bin/env python3
"""Unit tests für AlbumProcessor"""
from datetime import datetime
import unittest

import pytest

from services.downloader.utils.metadata.album_processor import AlbumProcessor

class TestAlbumProcessor(unittest.TestCase):
    def test_extract_year_from_string(self):
        processor = AlbumProcessor()
        self.assertEqual(processor.extract_year_from_string("2024"), 2024)
        self.assertEqual(processor.extract_year_from_string("24.05.2024"), 2024)
        self.assertIsNone(processor.extract_year_from_string("no year"))

if __name__ == '__main__':
    unittest.main()


# ─────────────────────────────────────────────────────────────────────────
# Characterization-Tests fuer determine_album_info / determine_track_number
# (Phase 1 Engineering Baseline - diese Entry-Points waren bislang nur
# indirekt ueber extract_year_from_string abgedeckt).
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def processor():
    return AlbumProcessor()


class TestDetermineAlbumInfo:
    def test_playlist_album_has_priority_over_track_album(self, processor):
        info = processor.determine_album_info(
            track_metadata={"album": "Track Album"},
            playlist_metadata={"album": "Playlist Album"},
            final_artist="Some Artist",
        )
        assert info["album"] == "Playlist Album"

    def test_falls_back_to_track_album_without_playlist(self, processor):
        info = processor.determine_album_info(
            track_metadata={"album": "Track Album"},
            playlist_metadata=None,
            final_artist="Some Artist",
        )
        assert info["album"] == "Track Album"

    def test_no_album_anywhere_stays_none(self, processor):
        info = processor.determine_album_info(
            track_metadata={}, playlist_metadata=None, final_artist="Some Artist"
        )
        assert info["album"] is None

    def test_year_priority_playlist_over_track_over_upload_date(self, processor):
        info = processor.determine_album_info(
            track_metadata={"year": 2010, "upload_date": "20200101"},
            playlist_metadata={"year": 2005},
            final_artist="Some Artist",
        )
        assert info["year"] == 2005

    def test_year_extracted_from_upload_date_as_last_resort(self, processor):
        info = processor.determine_album_info(
            track_metadata={"upload_date": "20200615"},
            playlist_metadata=None,
            final_artist="Some Artist",
        )
        assert info["year"] == 2020

    def test_year_out_of_range_is_ignored_and_defaults_to_current_year(
        self, processor
    ):
        info = processor.determine_album_info(
            track_metadata={"year": 1900},
            playlist_metadata=None,
            final_artist="Some Artist",
        )
        assert info["year"] == datetime.now().year

    def test_default_album_artist_is_final_artist(self, processor):
        info = processor.determine_album_info(
            track_metadata={}, playlist_metadata=None, final_artist="Final Artist"
        )
        assert info["album_artist"] == "Final Artist"

    def test_playlist_album_artist_overrides_final_artist(self, processor):
        info = processor.determine_album_info(
            track_metadata={},
            playlist_metadata={"album_artist": "Various Artists"},
            final_artist="Final Artist",
        )
        assert info["album_artist"] == "Various Artists"


class TestDetermineTrackNumber:
    def test_playlist_track_number_has_priority(self, processor):
        track_num = processor.determine_track_number(
            track_metadata={"track_number": 3},
            playlist_metadata={"track_number": 1},
        )
        assert track_num == 1

    def test_falls_back_to_track_metadata_track_number(self, processor):
        track_num = processor.determine_track_number(
            track_metadata={"track_number": 5}, playlist_metadata=None
        )
        assert track_num == 5

    def test_falls_back_to_playlist_position(self, processor):
        track_num = processor.determine_track_number(
            track_metadata={"playlist_position": 7}, playlist_metadata=None
        )
        assert track_num == 7

    def test_out_of_range_track_number_is_ignored(self, processor):
        track_num = processor.determine_track_number(
            track_metadata={"track_number": 1000}, playlist_metadata=None
        )
        assert track_num is None

    def test_no_candidates_returns_none(self, processor):
        track_num = processor.determine_track_number(
            track_metadata={}, playlist_metadata=None
        )
        assert track_num is None
