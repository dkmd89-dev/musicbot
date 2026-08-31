"""
Regressionstests fuer klassen/download_handler.py::_process_single_download_result()

Nach der Spotify-Entfernung (siehe
docs/archive/arch/MusicBot_ARCH-020_Download_Pipeline_Characterization.md, Abschnitt
"Spotify-Entfernung") ist diese Methode ein reiner Guard/Pass-Through fuer
YouTube-Ergebnisse: die Schritte D (Podcast-Episodennummer-Korrektur), E
(playlist_metadata fuer Podcasts) und G (EnhancedMetadataProcessor-Aufruf +
Feld-Uebersetzung) existierten ausschliesslich fuer den Spotify-Pfad und
wurden mitentfernt - process_single_track() wird von dieser Methode nicht
mehr aufgerufen. Punkte A (Playlist-Wrapper-Schutz), B
(Already-Processed-Schutz) und C (filepath-Fallback) bleiben als generische
YouTube-Infrastruktur bestehen.

DownloadHandler hat einen schweren Konstruktor (Update-Objekt, Config,
DuplicateHandler, ...) - object.__new__() umgeht ihn bewusst, da
_process_single_download_result() nur self.logger/
self.enhanced_metadata_processor/self.filename_fixer tatsaechlich
verwendet (etabliertes Muster dieser Session, siehe
test_progress_tracker.py/BUG-009).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
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

    def test_library_path_and_filepath_both_set_is_not_processed(self):
        """
        Charakterisiert die Kehrseite des Vertrags: sobald BEIDE Felder
        gesetzt sind, greift der Explizit-Guard (Punkt B) NICHT - aber da
        Punkt G (process_single_track-Aufruf) mit der Spotify-Entfernung
        entfernt wurde, gibt es dahinter ohnehin keine reale Verarbeitung
        mehr. Das Ergebnis wird unveraendert durchgereicht.
        """
        handler = make_handler()
        raw = {
            "success": True,
            "title": "T",
            "library_path": "/library/Artist/Album/01 T.m4a",
            "filepath": "/tmp/raw.m4a",
        }

        result = run_async(handler._process_single_download_result(raw))

        assert result is raw
        handler.enhanced_metadata_processor.process_single_track.assert_not_called()

    def test_no_library_path_is_not_processed(self):
        """
        Vor der Spotify-Entfernung loeste das Fehlen von library_path echte
        Metadaten-Verarbeitung aus (Spotify-Ergebnisse hatten nie
        library_path gesetzt). Ohne Punkt G ruft die Methode
        process_single_track() unter keinen Umstaenden mehr auf.
        """
        handler = make_handler()
        raw = {"filepath": "/tmp/raw.m4a", "title": "T"}

        result = run_async(handler._process_single_download_result(raw))

        assert result is raw
        handler.enhanced_metadata_processor.process_single_track.assert_not_called()
