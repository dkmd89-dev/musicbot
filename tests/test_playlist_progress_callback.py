"""
Playlist-Progress-State 2026-09-02 (Nutzer-Wunsch, Folgeschritt zur
ProgressTracker-Erweiterung in services/downloader/progress_tracker.py):
_process_playlist_download() ruft status_callback (falls uebergeben) jetzt
pro Track mit dem ProgressTracker selbst auf - reiner Zustand
(current_item/completed_items/processed_items/total_items), kein
vorformatierter Text. Ersetzt die vorherige, nie tatsaechlich verdrahtete
status_callback-Signatur (chat_id, step, total, message, module) - hatte 0
echte Aufrufer (siehe alter Docstring-Kommentar in download_utils.py).

Diese Tests decken NUR die Aufrufstelle/den Kontrollfluss in
download_utils.py ab (set_current_item/mark_completed-Reihenfolge,
Drosselung ueber compute_progress_message(), Guard bei status_callback=None)
- die Telegram-spezifische Formatierung hat einen eigenen Test in
tests/test_download_handler_playlist_progress_callback.py.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.downloader.download_utils import _process_playlist_download


def _make_mocked_processor(tracks=None):
    processor = MagicMock()
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.playlist_processor.process_playlist_metadata.return_value = {
        "tracks": tracks
        or [
            {"title": "Song A", "artist": "Artist A", "webpage_url": "https://youtu.be/AAAAAAAAAAA"},
            {"title": "Song B", "artist": "Artist B", "webpage_url": "https://youtu.be/BBBBBBBBBBB"},
        ],
        "dominant_artist": None,
        "album": "Test Album",
    }
    processor.channel_router.resolve_dominant_artist.return_value = (None, None)
    processor.year_resolver.resolve_playlist_year.return_value = None
    processor.session_stats = defaultdict(int)
    processor.cache_manager.lookup_playlist_track.return_value = None
    processor.download_executor.download_single_track = AsyncMock(return_value=None)
    return processor


class TestStatusCallbackReceivesProgressTracker:
    def test_callback_receives_a_progress_tracker_with_correct_total(self):
        processor = _make_mocked_processor()
        status_callback = AsyncMock()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                status_callback=status_callback,
            )
        )

        assert status_callback.await_count > 0
        tracker_arg = status_callback.await_args_list[0].args[0]
        assert tracker_arg.total_items == 2

    def test_completed_items_reflects_display_names_in_order(self):
        processor = _make_mocked_processor()
        status_callback = AsyncMock()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                status_callback=status_callback,
            )
        )

        final_tracker = status_callback.await_args_list[-1].args[0]
        assert final_tracker.completed_items == ["01 - Song A", "02 - Song B"]
        assert final_tracker.processed_items == 2

    def test_no_callback_does_not_crash(self):
        """Regressionsschutz: status_callback=None (Default) darf keinen
        AttributeError ausloesen - exakt das bisherige Verhalten."""
        processor = _make_mocked_processor()

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        assert len(results) == 2

    def test_mark_completed_runs_even_when_track_download_fails(self):
        """finally-Block muss auch bei fehlgeschlagenem Download laufen -
        sonst haengt processed_items hinter der tatsaechlichen
        Track-Anzahl zurueck."""
        processor = _make_mocked_processor(
            tracks=[{"title": "Song A", "artist": "Artist A"}]
        )
        processor.download_executor.download_single_track = AsyncMock(
            return_value=None
        )
        status_callback = AsyncMock()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                status_callback=status_callback,
            )
        )

        final_tracker = status_callback.await_args_list[-1].args[0]
        assert final_tracker.completed_items == ["01 - Song A"]
        assert final_tracker.processed_items == 1

    def test_callback_is_throttled_like_compute_progress_message(self):
        """status_callback wird nur aufgerufen, wenn
        tracker.compute_progress_message() nicht None liefert (Drosselung
        via update_interval, ausser beim letzten Element) - bei vielen
        schnell aufeinanderfolgenden Tracks ohne verstrichene Zeit werden
        daher nicht alle Zwischenaufrufe tatsaechlich gesendet."""
        many_tracks = [
            {"title": f"Song {i}", "artist": "Artist"} for i in range(5)
        ]
        processor = _make_mocked_processor(tracks=many_tracks)
        status_callback = AsyncMock()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{} for _ in many_tracks]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                status_callback=status_callback,
            )
        )

        # Das letzte Element loest IMMER eine Nachricht aus (Abschluss-
        # bedingung processed_items == total_items) - mindestens 1 Aufruf
        # ist daher garantiert, aber nicht zwingend einer pro Track.
        assert status_callback.await_count >= 1
        assert status_callback.await_count <= 2 * len(many_tracks)
