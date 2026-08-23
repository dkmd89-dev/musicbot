"""
Unit-Tests für services/downloader/utils/metadata_result_translator.py
— neue gemeinsame Integrationsschicht (ARCH-004, P-3, Option B).

Jede der drei Übersetzungsfunktionen wird hier isoliert gegen die exakten,
bereits per Regressionstest gesicherten Verhaltensweisen der drei
Original-Aufrufstellen geprüft (siehe
tests/test_download_utils_metadata_translation.py und
tests/test_download_handler_process_single_download_result.py für die
"vorher"-Baseline).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from services.downloader.utils.metadata_result_translator import (
    build_playlist_track_result,
    build_single_track_result,
    call_process_single_track,
    merge_metadata_result_into_dict,
)
from services.downloader.utils.metadata.models import MetadataResult


def run_async(coro):
    return asyncio.run(coro)


def make_metadata_result(**overrides):
    defaults = dict(
        success=True,
        title="Clean Title",
        artist="Clean Artist",
        album="Clean Album",
        album_artist="Clean Album Artist",
        year=2021,
        track_number=7,
        genres={"primary": "Hip Hop", "secondary": []},
        lyrics="la la la",
        lyrics_source="genius",
        cover_embedded=True,
        library_path="/library/Clean Artist/Clean Album/07 Clean Title.m4a",
        artist_source="youtube_parsed",
        genre_source="musicbrainz",
        title_cleaned=True,
        is_duplicate=True,
        from_cache=False,
        error=None,
        filepath="/tmp/downloaded_raw.m4a",
    )
    defaults.update(overrides)
    return MetadataResult(**defaults)


class TestCallProcessSingleTrack:
    def test_forwards_all_arguments(self):
        processor = Mock()
        processor.process_single_track = AsyncMock(return_value="RESULT")
        file_utils = Mock()
        filename_fixer = Mock()

        result = run_async(
            call_process_single_track(
                processor,
                track_metadata={"title": "T"},
                file_utils=file_utils,
                filename_fixer=filename_fixer,
                playlist_metadata={"album": "A"},
                dominant_artist="Dom",
            )
        )

        assert result == "RESULT"
        processor.process_single_track.assert_awaited_once_with(
            track_metadata={"title": "T"},
            file_utils=file_utils,
            filename_fixer=filename_fixer,
            playlist_metadata={"album": "A"},
            dominant_artist="Dom",
        )


class TestBuildPlaylistTrackResult:
    def test_year_uses_playlist_year_not_metadata_result(self):
        mr = make_metadata_result(year=2021)
        result = build_playlist_track_result(
            mr,
            playlist_year=1985,
            album_name="Album",
            track_idx=1,
            enhanced_processor_ref=Mock(),
        )
        assert result["year"] == 1985

    def test_track_number_uses_loop_index(self):
        mr = make_metadata_result(track_number=999)
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="Album", track_idx=5,
            enhanced_processor_ref=Mock(),
        )
        assert result["track_number"] == 5

    def test_playlist_album_is_set(self):
        mr = make_metadata_result()
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="My Playlist", track_idx=1,
            enhanced_processor_ref=Mock(),
        )
        assert result["playlist_album"] == "My Playlist"

    def test_is_duplicate_taken_from_metadata_result(self):
        mr = make_metadata_result(is_duplicate=True)
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="Album", track_idx=1,
            enhanced_processor_ref=Mock(),
        )
        assert result["is_duplicate"] is True

    def test_none_library_path_becomes_literal_none_string(self):
        mr = make_metadata_result(library_path=None)
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="Album", track_idx=1,
            enhanced_processor_ref=Mock(),
        )
        assert result["library_path"] == "None"

    def test_no_lyrics_or_filepath_key(self):
        mr = make_metadata_result()
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="Album", track_idx=1,
            enhanced_processor_ref=Mock(),
        )
        assert "lyrics" not in result
        assert "filepath" not in result

    def test_enhanced_processor_ref_carried_into_dict(self):
        mr = make_metadata_result()
        processor_ref = Mock()
        result = build_playlist_track_result(
            mr, playlist_year=2000, album_name="Album", track_idx=1,
            enhanced_processor_ref=processor_ref,
        )
        assert result["_enhanced_processor_ref"] is processor_ref


class TestBuildSingleTrackResult:
    def test_year_taken_from_metadata_result(self):
        mr = make_metadata_result(year=2021)
        result = build_single_track_result(mr, enhanced_processor_ref=Mock())
        assert result["year"] == 2021

    def test_track_number_and_playlist_album_stay_default(self):
        mr = make_metadata_result(track_number=42)
        result = build_single_track_result(mr, enhanced_processor_ref=Mock())
        assert result["track_number"] is None
        assert result["playlist_album"] is None

    def test_is_duplicate_always_false(self):
        mr = make_metadata_result(is_duplicate=True)
        result = build_single_track_result(mr, enhanced_processor_ref=Mock())
        assert result["is_duplicate"] is False

    def test_none_library_path_stays_none(self):
        mr = make_metadata_result(library_path=None)
        result = build_single_track_result(mr, enhanced_processor_ref=Mock())
        assert result["library_path"] is None


class TestMergeMetadataResultIntoDict:
    def test_success_maps_fields(self):
        mr = make_metadata_result()
        original = {"filepath": "/tmp/raw.m4a", "title": "Raw"}
        result = merge_metadata_result_into_dict(original, mr)
        assert result["title"] == "Clean Title"
        assert result["track_number"] == 7
        assert result["lyrics"] == "la la la"
        assert result["from_cache"] is False

    def test_original_extra_fields_preserved(self):
        mr = make_metadata_result()
        original = {
            "filepath": "/tmp/raw.m4a",
            "title": "Raw",
            "source": "spotify_no_api_embed",
            "is_podcast": False,
        }
        result = merge_metadata_result_into_dict(original, mr)
        assert result["source"] == "spotify_no_api_embed"
        assert result["is_podcast"] is False

    def test_no_enhanced_processor_ref_or_is_duplicate_key(self):
        mr = make_metadata_result(is_duplicate=True)
        original = {"filepath": "/tmp/raw.m4a", "title": "T"}
        result = merge_metadata_result_into_dict(original, mr)
        assert "enhanced_processor_ref" not in result
        assert "is_duplicate" not in result

    def test_album_and_year_fall_back_to_original(self):
        mr = make_metadata_result(album=None, year=None)
        original = {"filepath": "/tmp/raw.m4a", "title": "T", "album": "Raw Album", "year": 2015}
        result = merge_metadata_result_into_dict(original, mr)
        assert result["album"] == "Raw Album"
        assert result["year"] == 2015
