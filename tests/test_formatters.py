"""
Unit-Tests für ProgressFormatter (services/downloader/download/formatters.py)
— vorher 0 Tests, gefunden über die systematische Ungetestet-Prüfung.

Live genutzt in services/downloader/download_utils.py für ASCII-
Logging (bar/track_header/track_result_block/stats_table werden dort
aufgerufen). playlist_start()/single_track_header() haben aktuell keine
Aufrufer - reine, zustandslose Formatierungsmethoden ohne Seiteneffekte,
bewusst trotzdem vollständig mitgetestet statt entfernt.
"""

from services.downloader.download.formatters import ProgressFormatter


class TestBar:
    def test_zero_progress(self):
        result = ProgressFormatter.bar(0, 10, width=10)
        assert result == ".......... 0/10"

    def test_full_progress(self):
        result = ProgressFormatter.bar(10, 10, width=10)
        assert result == "########## 10/10"

    def test_half_progress(self):
        result = ProgressFormatter.bar(5, 10, width=10)
        assert result == "#####..... 5/10"

    def test_zero_total_does_not_divide_by_zero(self):
        result = ProgressFormatter.bar(0, 0)
        assert "0/0" in result

    def test_default_width_is_twelve(self):
        result = ProgressFormatter.bar(6, 12)
        bar_part = result.split(" ")[0]
        assert len(bar_part) == 12


class TestTrackHeader:
    def test_includes_artist_and_title(self):
        result = ProgressFormatter.track_header(1, 5, "Some Song", "Some Artist")
        assert "Some Artist - Some Song" in result
        assert "TRACK 01/05" in result

    def test_without_artist_only_shows_title(self):
        result = ProgressFormatter.track_header(1, 5, "Some Song")
        assert "'Some Song'" in result
        assert " - Some Song" not in result


class TestTrackResultBlock:
    def test_success_shows_ok_marker(self):
        result = ProgressFormatter.track_result_block(
            1, {"success": True, "artist": "A", "title": "T"}
        )
        assert "[OK]" in result
        assert "[FAIL]" not in result

    def test_failure_shows_fail_marker(self):
        result = ProgressFormatter.track_result_block(1, {"success": False})
        assert "[FAIL]" in result

    def test_flags_are_included_when_present(self):
        result = ProgressFormatter.track_result_block(
            1,
            {
                "success": True,
                "lyrics_available": True,
                "cover_embedded": True,
                "from_cache": True,
                "is_duplicate": True,
            },
        )
        assert "LYRICS" in result
        assert "COVER" in result
        assert "CACHE" in result
        assert "DUP" in result

    def test_artist_source_flags(self):
        fallback = ProgressFormatter.track_result_block(
            1, {"success": True, "artist_source": "artist_map_fallback"}
        )
        assert "ARTIST-MAP" in fallback

        parsed = ProgressFormatter.track_result_block(
            1, {"success": True, "artist_source": "youtube_parsed"}
        )
        assert "YT-PARSER" in parsed

    def test_no_flags_when_nothing_set(self):
        result = ProgressFormatter.track_result_block(1, {"success": True})
        assert "Flags:" not in result

    def test_missing_keys_fall_back_to_placeholder(self):
        result = ProgressFormatter.track_result_block(1, {})
        assert "?" in result


class TestStatsTable:
    def test_includes_all_core_numbers(self):
        result = ProgressFormatter.stats_table(
            session={
                "successful_downloads": 8,
                "failed_downloads": 2,
                "lyrics_found": 5,
                "artist_map_fallbacks": 1,
            },
            final={
                "duplicate_tracks": 3,
                "youtube_parser_used": 4,
                "successful_normalizations": 7,
                "successful_genre_mappings": 6,
            },
            cache_hits=9,
            total=10,
        )
        assert "Total tracks      : 10" in result
        assert "Successful        : 8" in result
        assert "Failed            : 2" in result
        assert "Cache hits        : 9" in result

    def test_missing_optional_keys_default_to_zero(self):
        result = ProgressFormatter.stats_table(
            session={}, final={}, cache_hits=0, total=0
        )
        assert "Lyrics found      : 0" in result


class TestPlaylistStart:
    def test_includes_title_uploader_and_track_count(self):
        result = ProgressFormatter.playlist_start(
            {"title": "My Playlist", "uploader": "Some Channel", "entries": [1, 2, 3]}
        )
        assert "My Playlist" in result
        assert "Some Channel" in result
        assert "Tracks   : 3" in result

    def test_missing_keys_use_placeholders(self):
        result = ProgressFormatter.playlist_start({})
        assert "?" in result
        assert "Tracks   : 0" in result


class TestSingleTrackHeader:
    def test_includes_all_fields(self):
        result = ProgressFormatter.single_track_header("Title", "Artist", "abc123")
        assert "Title" in result
        assert "Artist" in result
        assert "abc123" in result
