"""
PL-01 (docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md,
Kurzliste): services/downloader/download/download_executor.py::
download_single_track() besitzt eine echte Retry-Schleife
(`for attempt in range(1, max_retries + 1)`), der einzige Produktions-
Aufrufer in services/downloader/download_utils.py::_process_playlist_download()
uebergab bisher jedoch keinen max_retries-Wert - der Funktions-Default
max_retries=1 (kein Retry) griff dadurch fuer jeden Playlist-Track, waehrend
Single-Downloads ueber enhanced_download_with_retry() bereits 3 Versuche
erhalten (Top-Level-Retry).

Fachliche Entscheidung (explizit freigegeben): Playlist-Tracks sollen
kuenftig denselben festen Retry-Wert wie der Single-Pfad erhalten (3
Versuche) - kein neuer Config-Wert, keine neue Abstraktion, nur der
Call-Site-Parameter.

Fix: services/downloader/download_utils.py::_process_playlist_download()
uebergibt jetzt max_retries=3 an download_single_track(). Die Retry-
Schleife und retry_backoff_seconds-Logik in download_single_track() selbst
sowie DL-06s progress_hooks-basiertes Pro-Attempt-Cleanup bleiben
unveraendert (bereits vollstaendig fuer max_retries>1 ausgelegt und
getestet, siehe tests/test_download_executor_playlist_track_cleanup.py).

Nutzt dasselbe Mock-enhanced_processor-Muster wie
tests/test_download_utils_playlist_cancellation.py (Regel 7).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from services.downloader import download_utils
from services.downloader.download_utils import _process_playlist_download


def run_async(coro):
    return asyncio.run(coro)


def make_processor():
    processor = Mock()
    processor.playlist_processor = Mock()
    processor.channel_router = Mock()
    processor.channel_router.resolve_dominant_artist = Mock(
        return_value=(None, "Dom Artist")
    )
    processor.year_resolver = Mock()
    processor.year_resolver.resolve_playlist_year = Mock(return_value=2024)
    processor.session_stats = {
        "total_processed": 0,
        "successful_downloads": 0,
        "failed_downloads": 0,
        "cache_hits": 0,
        "lyrics_found": 0,
        "dominant_artists_detected": 0,
        "artist_map_fallbacks": 0,
        "title_cleanups": 0,
    }
    processor.cache_manager = Mock()
    processor.cache_manager.lookup_playlist_track = Mock(return_value=None)
    processor.download_executor = Mock()
    processor.download_executor.download_single_track = AsyncMock(
        return_value="/fake/dl/T1.m4a"
    )
    processor.config = Mock()
    processor.config.DOWNLOAD_DIR = "/fake/downloads"
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.enhanced_metadata_processor = Mock()
    processor.enhanced_metadata_processor.get_processing_statistics = Mock(
        return_value={}
    )
    return processor


async def _fake_process_track_metadata(*, track_info, **_):
    return {
        "success": True,
        "title": track_info["title"],
        "artist": track_info["artist"],
        "url": track_info["url"],
        "library_path": f"/fake/lib/{track_info['title']}.mp3",
        "renamed_due_to_conflict": False,
    }


class TestPlaylistTrackRetryIsActivated:
    def test_download_single_track_is_called_with_max_retries_three(
        self, monkeypatch
    ):
        tracks_info = [
            {"title": "T1", "artist": "A1", "url": "https://www.youtube.com/watch?v=T1"}
        ]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        monkeypatch.setattr(
            download_utils, "_process_track_metadata", _fake_process_track_metadata
        )

        run_async(
            _process_playlist_download(
                playlist_info={"title": "PL", "uploader": "U", "entries": [0]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=Mock(),
            )
        )

        call_kwargs = processor.download_executor.download_single_track.call_args.kwargs
        assert call_kwargs.get("max_retries") == 3

    def test_successful_playlist_track_download_regression_unaffected(
        self, monkeypatch
    ):
        """Regressionsschutz: der Erfolgspfad (Rueckgabewert, Track-
        Ergebnis) bleibt durch die zusaetzliche max_retries-Uebergabe
        unveraendert."""
        tracks_info = [
            {"title": "T1", "artist": "A1", "url": "https://www.youtube.com/watch?v=T1"}
        ]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        monkeypatch.setattr(
            download_utils, "_process_track_metadata", _fake_process_track_metadata
        )

        results = run_async(
            _process_playlist_download(
                playlist_info={"title": "PL", "uploader": "U", "entries": [0]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=Mock(),
            )
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["title"] == "T1"
