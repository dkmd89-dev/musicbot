"""
Regressionstest fuer: Config.MAX_PLAYLIST_ITEMS war definiert, wurde aber
nirgends in der Playlist-Pipeline gelesen. Eine Playlist mit tausenden
Eintraegen wurde bisher komplett unbegrenzt verarbeitet (unbegrenzter
Speicher-/Bandbreiten-/Zeitverbrauch pro Telegram-Anfrage).

_process_playlist_download() (services/downloader/download_utils.py)
kuerzt `entries` jetzt auf MAX_PLAYLIST_ITEMS, bevor irgendetwas mit den
Eintraegen gemacht wird - insbesondere bevor sie an
PlaylistProcessor.process_playlist_metadata() weitergereicht werden.

Der Rest der Pipeline (Channel-Routing, Jahr-Aufloesung, Track-Loop,
Statistik) wird komplett gemockt, da hier ausschliesslich die
Trunkierungs-Entscheidung getestet wird, nicht die restliche Orchestrierung.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from services.downloader.download_utils import _process_playlist_download


def _make_mocked_processor(max_playlist_items):
    processor = MagicMock()
    processor.config.MAX_PLAYLIST_ITEMS = max_playlist_items
    processor.playlist_processor.process_playlist_metadata.return_value = {
        "tracks": [],
        "dominant_artist": None,
        "album": "Playlist",
    }
    processor.channel_router.resolve_dominant_artist.return_value = (None, None)
    processor.year_resolver.resolve_playlist_year.return_value = None
    processor.session_stats = {}
    return processor


class TestMaxPlaylistItemsEnforced:
    def test_playlist_over_limit_is_truncated_before_processing(self):
        entries = [{"title": f"Track {i}"} for i in range(10)]
        playlist_info = {"entries": entries, "title": "Big Playlist"}
        processor = _make_mocked_processor(max_playlist_items=3)

        asyncio.run(
            _process_playlist_download(
                playlist_info=playlist_info,
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        call_args = processor.playlist_processor.process_playlist_metadata.call_args
        passed_entries = call_args[0][0]
        assert len(passed_entries) == 3
        assert passed_entries == entries[:3]

    def test_playlist_within_limit_is_not_truncated(self):
        entries = [{"title": f"Track {i}"} for i in range(5)]
        playlist_info = {"entries": entries, "title": "Small Playlist"}
        processor = _make_mocked_processor(max_playlist_items=50)

        asyncio.run(
            _process_playlist_download(
                playlist_info=playlist_info,
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        call_args = processor.playlist_processor.process_playlist_metadata.call_args
        passed_entries = call_args[0][0]
        assert len(passed_entries) == 5

    def test_no_max_playlist_items_configured_means_no_truncation(self):
        entries = [{"title": f"Track {i}"} for i in range(10)]
        playlist_info = {"entries": entries, "title": "Unbounded Playlist"}
        processor = _make_mocked_processor(max_playlist_items=None)

        asyncio.run(
            _process_playlist_download(
                playlist_info=playlist_info,
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        call_args = processor.playlist_processor.process_playlist_metadata.call_args
        passed_entries = call_args[0][0]
        assert len(passed_entries) == 10
