"""
Regressionstests fuer klassen/download_handler.py::_process_single_download_result()
— vorher 0 Tests. Das ist die Integrationsstelle, die fuer Spotify-Tracks
die eigentliche Metadaten-Anreicherung via EnhancedMetadataProcessor
uebernimmt (und fuer bereits verarbeitete YouTube-Ergebnisse als No-Op-
Passthrough dient, siehe "Already-Processed-Schutz" unten).

ARCH-004/P-3, Schritt 2: sichert das AKTUELLE Verhalten (inkl. der in
docs/MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md Abschnitt 6
dokumentierten Feld-Inkonsistenzen ggue. den YT-Pfaden, z.B.
enhanced_processor_ref/is_duplicate fehlen hier komplett) VOR der geplanten
Extraktion einer gemeinsamen Integrationsschicht (Option B) ab.

DownloadHandler hat einen schweren Konstruktor (Update-Objekt, Config,
DuplicateHandler, ...) - object.__new__() umgeht ihn bewusst, da
_process_single_download_result() nur self.logger/
self.enhanced_metadata_processor/self.filename_fixer tatsaechlich
verwendet (etabliertes Muster dieser Session, siehe
test_progress_tracker.py/BUG-009).

Update 2026-08-24 (ARCH-003 P-1): self.file_utils entfernt (FileUtils war
totes Gewicht, siehe docs/MusicBot_ARCH-003_Services_Phase1_Analyse.md).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
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


def make_handler(metadata_result=None):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.enhanced_metadata_processor = Mock()
    handler.enhanced_metadata_processor.process_single_track = AsyncMock(
        return_value=metadata_result or make_metadata_result()
    )
    handler.filename_fixer = Mock()
    return handler


# ─────────────────────────────────────────────────────────────────────────
# Schritt A: Playlist-Wrapper-Schutz
# ─────────────────────────────────────────────────────────────────────────


class TestPlaylistWrapperGuard:
    def test_playlist_type_result_is_returned_unprocessed(self):
        handler = make_handler()
        raw = {"type": "playlist", "tracks": []}

        result = run_async(handler._process_single_download_result(raw))

        assert result is raw
        handler.enhanced_metadata_processor.process_single_track.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# Schritt B: Already-Processed-Schutz (kritischer, fragiler Vertrag -
# ARCH-004 Abschnitt 3.2 - hier NUR charakterisiert, nicht veraendert)
# ─────────────────────────────────────────────────────────────────────────


class TestAlreadyProcessedGuard:
    def test_library_path_set_and_no_filepath_skips_reprocessing(self):
        """
        Das ist der fragile, implizite Vertrag: ein bereits durch die
        YouTube-Pipeline verarbeitetes DownloadResult-Dict hat
        library_path gesetzt und (strukturell bedingt) nie ein
        filepath-Feld -> wird hier als "schon fertig" erkannt.
        """
        handler = make_handler()
        already_done = {
            "success": True,
            "title": "Already Done",
            "library_path": "/library/Artist/Album/01 Already Done.m4a",
        }

        result = run_async(handler._process_single_download_result(already_done))

        assert result is already_done
        handler.enhanced_metadata_processor.process_single_track.assert_not_called()

    def test_library_path_and_filepath_both_set_is_reprocessed(self):
        """
        Charakterisiert die Kehrseite des fragilen Vertrags: sobald BEIDE
        Felder gesetzt sind, greift der Schutz NICHT - process_single_track
        wird trotz vorhandenem library_path erneut aufgerufen.
        """
        handler = make_handler()
        raw = {
            "success": True,
            "title": "T",
            "library_path": "/library/Artist/Album/01 T.m4a",
            "filepath": "/tmp/raw.m4a",
        }

        run_async(handler._process_single_download_result(raw))

        handler.enhanced_metadata_processor.process_single_track.assert_called_once()

    def test_no_library_path_triggers_processing(self):
        handler = make_handler()
        raw = {"filepath": "/tmp/raw.m4a", "title": "T"}

        run_async(handler._process_single_download_result(raw))

        handler.enhanced_metadata_processor.process_single_track.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# Schritt G: Feld-Uebersetzung (Spotify-Normalfall)
# ─────────────────────────────────────────────────────────────────────────


class TestFieldTranslation:
    def test_success_maps_fields_from_metadata_result(self):
        metadata_result = make_metadata_result()
        handler = make_handler(metadata_result)
        raw = {"filepath": "/tmp/raw.m4a", "title": "Raw", "source": "spotify_no_api_embed"}

        result = run_async(handler._process_single_download_result(raw))

        assert result["title"] == "Clean Title"
        assert result["artist"] == "Clean Artist"
        assert result["track_number"] == 7  # anders als YT-Single: ECHT uebernommen
        assert result["lyrics"] == "la la la"  # echt vorhanden, anders als bei YT
        assert result["from_cache"] is False

    def test_original_extra_fields_are_preserved_via_spread(self):
        """
        Spotify-spezifische Zusatzfelder (is_podcast/podcast_name/source)
        bleiben erhalten, da das Ergebnis ein freies {**result, ...}-Dict
        ist statt eines DownloadResult mit festem Feld-Satz.
        """
        handler = make_handler()
        raw = {
            "filepath": "/tmp/raw.m4a",
            "title": "Raw",
            "source": "spotify_no_api_embed",
            "is_podcast": False,
        }

        result = run_async(handler._process_single_download_result(raw))

        assert result["source"] == "spotify_no_api_embed"
        assert result["is_podcast"] is False

    def test_enhanced_processor_ref_key_is_absent(self):
        """
        Dokumentierte Inkonsistenz (ARCH-004 Abschnitt 6): anders als bei
        beiden YT-Pfaden gibt es hier keinen enhanced_processor_ref-Schluessel.
        """
        handler = make_handler()
        raw = {"filepath": "/tmp/raw.m4a", "title": "T"}

        result = run_async(handler._process_single_download_result(raw))

        assert "enhanced_processor_ref" not in result

    def test_is_duplicate_key_is_absent_when_not_in_raw_input(self):
        """
        Dokumentierte Inkonsistenz: is_duplicate wird nicht aus
        metadata_result uebernommen und war im Spotify-track_info-Rohformat
        nie vorhanden.
        """
        metadata_result = make_metadata_result(is_duplicate=True)
        handler = make_handler(metadata_result)
        raw = {"filepath": "/tmp/raw.m4a", "title": "T"}

        result = run_async(handler._process_single_download_result(raw))

        assert "is_duplicate" not in result

    def test_album_and_year_fall_back_to_raw_input_when_metadata_result_empty(self):
        metadata_result = make_metadata_result(album=None, year=None)
        handler = make_handler(metadata_result)
        raw = {"filepath": "/tmp/raw.m4a", "title": "T", "album": "Raw Album", "year": 2015}

        result = run_async(handler._process_single_download_result(raw))

        assert result["album"] == "Raw Album"
        assert result["year"] == 2015

    def test_metadata_failure_returns_original_result_unchanged(self):
        failed_result = make_metadata_result(success=False, error="Boom")
        handler = make_handler(failed_result)
        raw = {"filepath": "/tmp/raw.m4a", "title": "Original"}

        result = run_async(handler._process_single_download_result(raw))

        assert result is raw
        assert result["title"] == "Original"

    def test_exception_during_processing_returns_original_result(self):
        handler = make_handler()
        handler.enhanced_metadata_processor.process_single_track = AsyncMock(
            side_effect=RuntimeError("kaputt")
        )
        raw = {"filepath": "/tmp/raw.m4a", "title": "Original"}

        result = run_async(handler._process_single_download_result(raw))

        assert result is raw


# ─────────────────────────────────────────────────────────────────────────
# Schritt D: Podcast-Episodennummer-Korrektur (Spotify-spezifisch)
# ─────────────────────────────────────────────────────────────────────────


class TestPodcastEpisodeNumberCorrection:
    def test_episode_number_artist_replaced_by_uploader(self):
        handler = make_handler()
        raw = {
            "filepath": "/tmp/raw.m4a",
            "title": "T",
            "artist": "12/2024",
            "uploader": "Real Podcast Channel",
        }

        run_async(handler._process_single_download_result(raw))

        call_kwargs = handler.enhanced_metadata_processor.process_single_track.call_args.kwargs
        assert call_kwargs["track_metadata"]["artist"] == "Real Podcast Channel"

    def test_unknown_artist_replaced_by_channel(self):
        handler = make_handler()
        raw = {
            "filepath": "/tmp/raw.m4a",
            "title": "T",
            "artist": "Unbekannt",
            "channel": "Some Channel",
        }

        run_async(handler._process_single_download_result(raw))

        call_kwargs = handler.enhanced_metadata_processor.process_single_track.call_args.kwargs
        assert call_kwargs["track_metadata"]["artist"] == "Some Channel"

    def test_normal_artist_is_not_touched(self):
        handler = make_handler()
        raw = {"filepath": "/tmp/raw.m4a", "title": "T", "artist": "Real Artist"}

        run_async(handler._process_single_download_result(raw))

        call_kwargs = handler.enhanced_metadata_processor.process_single_track.call_args.kwargs
        assert call_kwargs["track_metadata"]["artist"] == "Real Artist"


# ─────────────────────────────────────────────────────────────────────────
# Schritt E: playlist_metadata-Aufbau fuer Podcasts (Spotify-spezifisch)
# ─────────────────────────────────────────────────────────────────────────


class TestPodcastPlaylistMetadata:
    def test_podcast_track_builds_playlist_metadata(self):
        handler = make_handler()
        raw = {
            "filepath": "/tmp/raw.m4a",
            "title": "Episode 1",
            "is_podcast": True,
            "podcast_name": "My Podcast",
        }

        run_async(handler._process_single_download_result(raw))

        call_kwargs = handler.enhanced_metadata_processor.process_single_track.call_args.kwargs
        pm = call_kwargs["playlist_metadata"]
        assert pm["album_artist"] == "My Podcast"
        assert pm["playlist_channel"] == "My Podcast"

    def test_non_podcast_track_has_no_playlist_metadata(self):
        handler = make_handler()
        raw = {"filepath": "/tmp/raw.m4a", "title": "T", "is_podcast": False}

        run_async(handler._process_single_download_result(raw))

        call_kwargs = handler.enhanced_metadata_processor.process_single_track.call_args.kwargs
        assert call_kwargs["playlist_metadata"] is None
