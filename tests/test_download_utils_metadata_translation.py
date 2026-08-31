"""
Regressionstests fuer die Rohdaten->track_metadata->process_single_track()->
Ergebnis-Dict-Uebersetzung in services/downloader/download_utils.py
(_process_track_metadata fuer YT-Playlist-Tracks, _process_single_download
fuer YT-Single-Downloads) — vorher 0 Tests fuer diese beiden Funktionen.

ARCH-004/P-3, Schritt 2: sichert das AKTUELLE Verhalten (inkl. der in
docs/archive/arch/MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md Abschnitt 6
dokumentierten Feld-Inkonsistenzen, z.B. track_number/playlist_album werden
im Single-Download-Pfad NIE aus enhanced_result uebernommen, nur
Dataclass-Defaults) VOR der geplanten Extraktion einer gemeinsamen
Integrationsschicht (Option B) ab. Diese Tests duerfen sich nach der
Extraktion NICHT aendern - genau das ist der Beweis fuer
Verhaltensgleichheit.

Update 2026-08-23 (ARCH-004 Section 7, Entscheidungsbericht FIX NOW/DEFER):
zwei der urspruenglich dokumentierten Inkonsistenzen (is_duplicate im
Single-Pfad, library_path-Stringifizierung im Playlist-Pfad bei None)
wurden als sichtbare bzw. potenziell fehlertraechtige Bugs bewusst gefixt.
Die zugehoerigen Tests wurden auf das neue, korrigierte Verhalten
aktualisiert.

Regel 7: externe Abhaengigkeiten (EnhancedMetadataProcessor,
DownloadExecutor, CacheManager) werden gemockt.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services.downloader.download_utils import (
    _process_single_download,
    _process_track_metadata,
)
from services.metadata.models import MetadataResult


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


def make_enhanced_processor(metadata_result=None):
    processor = Mock()
    processor.enhanced_metadata_processor = Mock()
    processor.enhanced_metadata_processor.process_single_track = AsyncMock(
        return_value=metadata_result or make_metadata_result()
    )
    processor.session_stats = {
        "total_processed": 0,
        "cache_hits": 0,
        "failed_downloads": 0,
    }
    return processor


# ─────────────────────────────────────────────────────────────────────────
# _process_track_metadata (YT-Playlist)
# ─────────────────────────────────────────────────────────────────────────


class TestProcessTrackMetadataPlaylist:
    def test_success_maps_fields_from_metadata_result(self):
        metadata_result = make_metadata_result()
        enhanced_processor = make_enhanced_processor(metadata_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "Raw Title", "uploader": "Raw Uploader"},
                downloaded_file="/tmp/downloaded_raw.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Playlist Album",
                dominant_artist="Dominant Artist",
                playlist_year=1999,
                track_idx=3,
                playlist_channel=None,
            )
        )

        assert result["success"] is True
        assert result["title"] == "Clean Title"
        assert result["artist"] == "Clean Artist"
        assert result["genre_source"] == "musicbrainz"
        assert result["lyrics_available"] is True
        assert result["is_duplicate"] is True  # aus enhanced_result uebernommen

    def test_year_uses_playlist_year_not_metadata_result_year(self):
        """
        Dokumentiertes, bewusstes Verhalten (ARCH-004 Abschnitt 6): der
        Playlist-Pfad ignoriert enhanced_result.year zugunsten des vorab
        bestimmten, einheitlichen playlist_year.
        """
        metadata_result = make_metadata_result(year=2021)
        enhanced_processor = make_enhanced_processor(metadata_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=1985,
                track_idx=1,
            )
        )

        assert result["year"] == 1985

    def test_track_number_uses_loop_index_not_metadata_result(self):
        """
        Dokumentiertes, bewusstes Verhalten: track_number kommt aus dem
        Schleifen-Index track_idx, nicht aus enhanced_result.track_number.
        """
        metadata_result = make_metadata_result(track_number=999)
        enhanced_processor = make_enhanced_processor(metadata_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=5,
            )
        )

        assert result["track_number"] == 5

    def test_playlist_album_is_set(self):
        enhanced_processor = make_enhanced_processor()

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="My Playlist",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["playlist_album"] == "My Playlist"

    def test_none_library_path_stays_none_not_stringified(self):
        """
        Gefixt (2026-08-23, ARCH-004 Section 7, FIX NOW): der Playlist-Pfad
        stringifiziert library_path jetzt bedingt wie der Single-Pfad - bei
        None bleibt es None statt zum truthy-String "None" zu werden (der
        z.B. cache_manager.py faelschlich einen Path("None") erzeugen liess).
        """
        metadata_result = make_metadata_result(library_path=None)
        enhanced_processor = make_enhanced_processor(metadata_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["library_path"] is None

    def test_no_lyrics_raw_text_or_filepath_key_in_result(self):
        """
        DownloadResult.to_dict() kennt kein "lyrics"/"filepath"-Feld -
        echt fehlend im Ergebnis-Dict (ARCH-004 Abschnitt 6).
        """
        enhanced_processor = make_enhanced_processor()

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert "lyrics" not in result
        assert "filepath" not in result

    def test_renamed_due_to_conflict_is_propagated(self):
        """
        P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 2):
        renamed_due_to_conflict aus dem MetadataResult (gesetzt von
        move_to_library() bei einer Zieldateinamens-Kollision) muss bis ins
        Ergebnis-Dict durchgereicht werden - der darauf wartende Cleanup in
        klassen/download_handler.py::handle_youtube_links() liest genau
        dieses Feld.
        """
        metadata_result = make_metadata_result(renamed_due_to_conflict=True)
        enhanced_processor = make_enhanced_processor(metadata_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["renamed_due_to_conflict"] is True

    def test_renamed_due_to_conflict_defaults_to_false(self):
        enhanced_processor = make_enhanced_processor()

        result = run_async(
            _process_track_metadata(
                track_info={"title": "T"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["renamed_due_to_conflict"] is False

    def test_metadata_failure_returns_error_result(self):
        failed_result = make_metadata_result(success=False, error="Boom")
        enhanced_processor = make_enhanced_processor(failed_result)

        result = run_async(
            _process_track_metadata(
                track_info={"title": "Original Title"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["success"] is False
        assert result["error"] == "Boom"
        assert result["title"] == "Original Title"

    def test_exception_during_processing_returns_error_result(self):
        enhanced_processor = make_enhanced_processor()
        enhanced_processor.enhanced_metadata_processor.process_single_track = AsyncMock(
            side_effect=RuntimeError("kaputt")
        )

        result = run_async(
            _process_track_metadata(
                track_info={"title": "Original Title"},
                downloaded_file="/tmp/x.m4a",
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
                album_name="Album",
                dominant_artist=None,
                playlist_year=2000,
                track_idx=1,
            )
        )

        assert result["success"] is False
        assert "kaputt" in result["error"]


# ─────────────────────────────────────────────────────────────────────────
# _process_single_download (YT-Single)
# ─────────────────────────────────────────────────────────────────────────


def make_enhanced_processor_for_single(tmp_path, metadata_result=None, cached=None):
    processor = make_enhanced_processor(metadata_result)
    processor.cache_manager = Mock()
    processor.cache_manager.lookup_single_track = Mock(return_value=cached)

    downloaded_file = tmp_path / "song.m4a"
    downloaded_file.write_bytes(b"x" * 100)

    processor.download_executor = Mock()
    processor.download_executor.extract_info_async = AsyncMock(
        return_value={"id": "abc123"}
    )
    processor.download_executor.find_downloaded_file = Mock(
        return_value=str(downloaded_file)
    )
    return processor


class TestProcessSingleDownloadCacheHit:
    def test_cache_hit_returns_cached_result_without_download(self, tmp_path):
        cached = {"success": True, "title": "Cached Title", "artist": "Cached Artist"}
        enhanced_processor = make_enhanced_processor_for_single(tmp_path, cached=cached)

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "Cached Title", "artist": "Cached Artist"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["title"] == "Cached Title"
        enhanced_processor.download_executor.extract_info_async.assert_not_called()


class TestProcessSingleDownloadCacheMiss:
    def test_success_maps_fields_from_metadata_result(self, tmp_path):
        metadata_result = make_metadata_result()
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, metadata_result
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "Raw Title", "uploader": "Raw Uploader"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["success"] is True
        assert result["title"] == "Clean Title"
        assert result["year"] == 2021  # hier IM GEGENSATZ zum Playlist-Pfad
        # aus enhanced_result uebernommen

    def test_none_library_path_stays_none_not_stringified(self, tmp_path):
        """
        Gegenstueck zu test_none_library_path_is_stringified_to_literal_none
        im Playlist-Pfad: der Single-Pfad prueft library_path VOR dem
        str()-Aufruf - None bleibt None, wird NICHT zum String "None".
        """
        metadata_result = make_metadata_result(library_path=None)
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, metadata_result
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "T"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["library_path"] is None

    def test_renamed_due_to_conflict_is_propagated(self, tmp_path):
        """
        P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 2), Gegenstueck
        zum Playlist-Test: auch im Single-Download-Pfad muss
        renamed_due_to_conflict aus dem MetadataResult durchgereicht werden.
        """
        metadata_result = make_metadata_result(renamed_due_to_conflict=True)
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, metadata_result
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "T"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["renamed_due_to_conflict"] is True

    def test_track_number_and_playlist_album_are_always_default(self, tmp_path):
        """
        Dokumentierte Inkonsistenz (ARCH-004 Abschnitt 6): track_number/
        playlist_album werden im Single-Pfad NIE aus enhanced_result
        uebernommen - nur die DownloadResult-Dataclass-Defaults.
        """
        metadata_result = make_metadata_result(track_number=42)
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, metadata_result
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "T"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["track_number"] is None
        assert result["playlist_album"] is None

    def test_is_duplicate_is_taken_from_metadata_result(self, tmp_path):
        """
        Gefixt (2026-08-23, ARCH-004 Section 7, FIX NOW): is_duplicate wird
        im Single-Pfad jetzt aus enhanced_result.is_duplicate uebernommen -
        vorher blieb es immer False, was im Telegram-Report faelschlich
        "kein Duplikat" anzeigte.
        """
        metadata_result = make_metadata_result(is_duplicate=True)
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, metadata_result
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=abc",
                video_info={"title": "T"},
                ydl_opts={},
                enhanced_processor=enhanced_processor,
                filename_fixer=Mock(),
            )
        )

        assert result["is_duplicate"] is True

    def test_metadata_failure_raises_download_error(self, tmp_path):
        from services.downloader.errors import DownloadError

        failed_result = make_metadata_result(success=False, error="Boom")
        enhanced_processor = make_enhanced_processor_for_single(
            tmp_path, failed_result
        )

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=abc",
                    video_info={"title": "T"},
                    ydl_opts={},
                    enhanced_processor=enhanced_processor,
                    filename_fixer=Mock(),
                )
            )

    def test_download_file_not_found_raises_download_error(self, tmp_path):
        from services.downloader.errors import DownloadError

        enhanced_processor = make_enhanced_processor_for_single(tmp_path)
        enhanced_processor.download_executor.find_downloaded_file = Mock(
            return_value=None
        )

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=abc",
                    video_info={"title": "T"},
                    ydl_opts={},
                    enhanced_processor=enhanced_processor,
                    filename_fixer=Mock(),
                )
            )
