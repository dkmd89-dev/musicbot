"""
Playlist-Prioritaet (Nutzer-Wunsch 2026-09-02): _process_playlist_download()
ruft duplicate_detector.resolve_playlist_single_conflict() jetzt VOR dem
Cache-Check auf (siehe Docstring dort und in
services/duplicate/detector.py::resolve_playlist_single_conflict()).

Diese Tests decken NUR die Aufrufstelle/den Kontrollfluss in
download_utils.py ab (Reihenfolge, Guard-Bedingungen) - die eigentliche
Konflikt-/Loesch-Logik hat eigene, isolierte Tests in
tests/test_duplicate_detector_playlist_singles_priority.py.
"""

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.downloader.download_utils import _process_playlist_download


def _make_mocked_processor():
    processor = MagicMock()
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.playlist_processor.process_playlist_metadata.return_value = {
        "tracks": [
            {
                "title": "Wie du manchmal fehlst",
                "artist": "Zartmann",
                "webpage_url": "https://youtu.be/AAAAAAAAAAA",
            },
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


class TestSinglesPriorityPreCheck:
    def test_resolve_playlist_single_conflict_called_before_cache_check(self):
        processor = _make_mocked_processor()
        duplicate_detector = MagicMock()
        duplicate_detector.check_for_duplicates.return_value = (False, None, "none")

        call_order = []
        duplicate_detector.resolve_playlist_single_conflict.side_effect = (
            lambda *a, **k: call_order.append("resolve_conflict")
        )
        processor.cache_manager.lookup_playlist_track.side_effect = (
            lambda **k: call_order.append("cache_check") or None
        )

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                duplicate_detector=duplicate_detector,
            )
        )

        duplicate_detector.resolve_playlist_single_conflict.assert_called_once_with(
            "Zartmann", "Wie du manchmal fehlst"
        )
        assert call_order == ["resolve_conflict", "cache_check"]

    def test_not_called_when_artist_or_title_unknown(self):
        processor = _make_mocked_processor()
        processor.playlist_processor.process_playlist_metadata.return_value = {
            "tracks": [{"title": "?", "artist": "?"}],
            "dominant_artist": None,
            "album": "Test Album",
        }
        duplicate_detector = MagicMock()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                duplicate_detector=duplicate_detector,
            )
        )

        duplicate_detector.resolve_playlist_single_conflict.assert_not_called()

    def test_not_called_when_no_duplicate_detector(self):
        """Regressionsschutz: duplicate_detector=None (Default) darf keinen
        AttributeError ausloesen - exakt das bisherige Verhalten ohne
        Detector."""
        processor = _make_mocked_processor()

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        assert len(results) == 1

    def test_deleted_singles_file_lets_cache_hit_correctly_miss(self, tmp_path):
        """End-to-End innerhalb dieses Moduls: resolve_playlist_single_conflict()
        loescht die Datei tatsaechlich -> CacheManager.lookup_playlist_track()
        (hier ueber ein Fake mit echter Existenzpruefung simuliert) sieht sie
        danach korrekt als fehlend und liefert MISS, der Track erreicht also
        den normalen Download-Pfad statt des alten Cache-Kurzschlusses."""
        processor = _make_mocked_processor()
        singles_file = tmp_path / "wie du manchmal fehlst.m4a"
        singles_file.write_bytes(b"x")

        duplicate_detector = MagicMock()

        def _resolve(artist, title):
            if singles_file.exists():
                singles_file.unlink()
            return singles_file

        duplicate_detector.resolve_playlist_single_conflict.side_effect = _resolve
        duplicate_detector.check_for_duplicates.return_value = (False, None, "none")

        def _cache_lookup(**kwargs):
            # Spiegelt CacheManager.lookup_playlist_track()s reales
            # Existenz-Gate (services/downloader/download/cache_manager.py):
            # ein Cache-Eintrag zaehlt nur als Treffer, wenn die Datei noch
            # da ist.
            return None if not singles_file.exists() else {"library_path": str(singles_file)}

        processor.cache_manager.lookup_playlist_track.side_effect = _cache_lookup

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                duplicate_detector=duplicate_detector,
            )
        )

        # Cache-Treffer wurde NICHT verwendet (Datei war zum Zeitpunkt des
        # Cache-Checks bereits geloescht) -> Track erreichte den
        # Download-Pfad.
        assert processor.download_executor.download_single_track.call_count == 1
