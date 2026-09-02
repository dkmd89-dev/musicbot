"""
Download-Control-Center 2026-09-02: _process_playlist_download() prüft
active_download.is_cancel_requested() vor JEDEM Track (Soft-Cancel -
startet keine weiteren Tracks mehr) und behandelt ein während eines
Tracks geworfenes DownloadCancelledError (Hard-Cancel, via progress_hooks-
Hook - siehe download.download_executor.py) separat von einem generischen
Fehler: die Schleife bricht komplett ab statt zum nächsten Track
weiterzugehen.

Nutzt das ECHTE ActiveDownload/ActiveDownloadRegistry (kein Mock) - reine,
leichtgewichtige Datenklassen ohne externe Abhängigkeiten, siehe
services/downloader/active_downloads.py.
"""

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.downloader.active_downloads import ActiveDownload
from services.downloader.download_utils import _process_playlist_download
from services.downloader.errors import DownloadCancelledError


def _make_mocked_processor(n_tracks=3):
    processor = MagicMock()
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.playlist_processor.process_playlist_metadata.return_value = {
        "tracks": [
            {"title": f"Song {i}", "artist": "Artist", "webpage_url": f"https://youtu.be/{i:011d}"}
            for i in range(1, n_tracks + 1)
        ],
        "dominant_artist": None,
        "album": "Test Album",
    }
    processor.channel_router.resolve_dominant_artist.return_value = (None, None)
    processor.year_resolver.resolve_playlist_year.return_value = None
    processor.session_stats = defaultdict(int)
    processor.cache_manager.lookup_playlist_track.return_value = None
    return processor


def make_active_download(url="https://youtube.com/playlist?list=x"):
    return ActiveDownload(chat_id=1, url=url, download_type="playlist")


class TestSoftCancelBetweenTracks:
    def test_cancel_requested_before_start_skips_all_tracks(self):
        processor = _make_mocked_processor(n_tracks=3)
        processor.download_executor.download_single_track = AsyncMock(return_value=None)
        active_download = make_active_download()
        active_download.request_cancel()

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        assert results == []
        processor.download_executor.download_single_track.assert_not_called()

    def test_cancel_requested_between_tracks_stops_further_starts(self):
        processor = _make_mocked_processor(n_tracks=3)
        active_download = make_active_download()

        async def fake_download(**kwargs):
            # Simuliert: waehrend Track 1 lief, hat der Nutzer auf
            # Abbrechen geklickt (Cancel-Anfrage kommt von "aussen", nicht
            # aus dem Hook selbst) - Track 1 beendet noch normal.
            active_download.request_cancel()
            return None

        processor.download_executor.download_single_track = AsyncMock(
            side_effect=fake_download
        )

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        assert processor.download_executor.download_single_track.call_count == 1
        assert len(results) == 1


class TestHardCancelDuringTrack:
    def test_download_cancelled_error_stops_loop_immediately(self):
        processor = _make_mocked_processor(n_tracks=3)
        active_download = make_active_download()
        processor.download_executor.download_single_track = AsyncMock(
            side_effect=DownloadCancelledError()
        )

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        # Nur Track 1 wurde ueberhaupt versucht (Abbruch waehrend dessen
        # Downloads) - Track 2/3 werden NICHT mehr gestartet.
        assert processor.download_executor.download_single_track.call_count == 1
        assert len(results) == 1
        assert results[0]["success"] is False

    def test_active_download_marked_cancelled(self):
        processor = _make_mocked_processor(n_tracks=2)
        active_download = make_active_download()
        processor.download_executor.download_single_track = AsyncMock(
            side_effect=DownloadCancelledError()
        )

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        assert active_download.cancelled is True

    def test_third_track_of_unaffected_playlist_is_not_marked_cancelled(self):
        """Regressionsschutz: ein normaler, generischer Fehler (nicht
        DownloadCancelledError) darf active_download.cancelled NICHT
        setzen und die Schleife nicht abbrechen - bestehendes
        Fehlerverhalten (naechster Track wird trotzdem versucht) bleibt
        unveraendert."""
        processor = _make_mocked_processor(n_tracks=2)
        active_download = make_active_download()
        processor.download_executor.download_single_track = AsyncMock(
            side_effect=RuntimeError("normaler Netzwerkfehler")
        )

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        assert active_download.cancelled is False
        assert processor.download_executor.download_single_track.call_count == 2


class TestSharedTrackerIsUsedWhenActiveDownloadGiven:
    def test_uses_active_download_tracker_not_a_new_one(self):
        processor = _make_mocked_processor(n_tracks=2)
        processor.download_executor.download_single_track = AsyncMock(return_value=None)
        active_download = make_active_download()
        original_tracker = active_download.tracker

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                active_download=active_download,
            )
        )

        assert active_download.tracker is original_tracker
        assert active_download.tracker.total_items == 2
        assert active_download.tracker.processed_items == 2

    def test_without_active_download_a_local_tracker_is_still_created(self):
        """Regressionsschutz: Aufrufer ohne ActiveDownload (z.B. isolierte
        Tests) duerfen nicht crashen - lokaler Tracker wie bisher."""
        processor = _make_mocked_processor(n_tracks=1)
        processor.download_executor.download_single_track = AsyncMock(return_value=None)

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        assert len(results) == 1
