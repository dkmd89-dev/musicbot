"""
Live-Fund 2026-09-02 (Nutzer-Report): _probe_artist_title_for_duplicate_check()
(klassen/download_handler.py) liefert fuer Playlist-URLs bewusst (None, None)
zurueck, weil yt-dlp fuer eine Playlist ein "entries"-Ergebnis statt eines
einzelnen Titels liefert - check_for_duplicates() prueft fuer Playlists
dadurch bisher NUR die URL-Ebene der Playlist selbst, nie Artist/Titel der
einzelnen darin enthaltenen Tracks.

Konkret beobachtet: "Zartmann - schoenhauser" existierte bereits als Single
(Zartmann/Singles/2025 - schoenhauser.m4a, Duplicate-Cache-Eintrag
vorhanden), wurde aber beim Download der Playlist "schoenhauser EP" erneut
heruntergeladen und unter Zartmann/2025 - schoenhauser EP/03 - schoenhauser.m4a
abgelegt - der alte Duplicate-Cache-Eintrag wurde dabei durch den neuen
(identischer Content-Hash fuer Artist+Titel) stillschweigend ueberschrieben.

Fix: _process_playlist_download() nimmt jetzt optional einen
duplicate_detector entgegen und ruft vor JEDEM Track-Download
check_for_duplicates(url, raw_artist, raw_title) mit dem eigenen
Artist/Titel dieses Tracks auf (nicht der Playlist als Ganzes). Bei einem
Treffer wird der Track uebersprungen (kein Download, kein Ueberschreiben
des bestehenden Cache-Eintrags) und als DownloadResult(success=False,
is_duplicate=True, ...) ins Ergebnis aufgenommen - _register_playlist_track_
duplicates() (klassen/download_handler.py) registriert ohnehin nur
success=True-Eintraege, uebergeht ihn also korrekt.

duplicate_detector ist bewusst optional (Default None) - Aufrufer ohne
eigenen DuplicateDetector (z.B. andere isolierte Tests wie
test_playlist_max_items.py) sind unveraendert, exakt das bisherige
Verhalten.
"""

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.downloader.download_utils import _process_playlist_download
from services.duplicate.detector import DuplicateEntry
from datetime import datetime


def _make_mocked_processor():
    processor = MagicMock()
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.playlist_processor.process_playlist_metadata.return_value = {
        "tracks": [
            {
                "title": "Song A",
                "artist": "Artist A",
                "webpage_url": "https://youtu.be/AAAAAAAAAAA",
            },
            {
                "title": "Song B",
                "artist": "Artist B",
                "webpage_url": "https://youtu.be/BBBBBBBBBBB",
            },
        ],
        "dominant_artist": None,
        "album": "Test Album",
    }
    processor.channel_router.resolve_dominant_artist.return_value = (None, None)
    processor.year_resolver.resolve_playlist_year.return_value = None
    processor.session_stats = defaultdict(int)
    processor.cache_manager.lookup_playlist_track.return_value = None
    # Track A soll den Download-Pfad erreichen, dort aber sauber als
    # "Download fehlgeschlagen" enden - haelt den Test fokussiert auf die
    # Duplikat-Entscheidung, ohne _process_track_metadata() mitmocken zu
    # muessen.
    processor.download_executor.download_single_track = AsyncMock(
        return_value=None
    )
    return processor


class TestPlaylistPerTrackDuplicateCheck:
    def test_duplicate_track_is_skipped_without_downloading(self):
        processor = _make_mocked_processor()
        duplicate_entry = DuplicateEntry(
            artist="Artist B",
            title="Song B",
            url="https://youtu.be/OLD_URL",
            file_path="/library/Artist B/Singles/2025 - Song B.m4a",
            download_date=datetime.now(),
        )
        duplicate_detector = MagicMock()
        duplicate_detector.check_for_duplicates.side_effect = (
            lambda url, raw_artist, raw_title: (
                (True, duplicate_entry, "content")
                if raw_artist == "Artist B"
                else (False, None, "none")
            )
        )

        results = asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
                duplicate_detector=duplicate_detector,
            )
        )

        # Track B: Duplikat erkannt -> kein Download-Aufruf fuer diesen Track.
        download_calls = processor.download_executor.download_single_track.call_args_list
        assert len(download_calls) == 1
        assert download_calls[0].kwargs["track_info"]["artist"] == "Artist A"

        # Ergebnis fuer Track B ist als Duplikat markiert, nicht als Erfolg.
        track_b_result = next(r for r in results if r["title"] == "Song B")
        assert track_b_result["success"] is False
        assert track_b_result["is_duplicate"] is True

    def test_no_duplicate_detector_preserves_previous_behavior(self):
        """Regressionsschutz: duplicate_detector=None (Default, z.B. andere
        bestehende Tests wie test_playlist_max_items.py) darf die
        Duplikat-Pruefung nicht erzwingen - beide Tracks werden weiterhin
        unveraendert zum Download versucht."""
        processor = _make_mocked_processor()

        asyncio.run(
            _process_playlist_download(
                playlist_info={"entries": [{}, {}]},
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=MagicMock(),
            )
        )

        download_calls = processor.download_executor.download_single_track.call_args_list
        assert len(download_calls) == 2

    def test_duplicate_check_is_skipped_for_tracks_with_unknown_artist_or_title(self):
        """Platzhalter-Werte ("?") duerfen nicht als echter Artist/Titel an
        check_for_duplicates() weitergereicht werden - sonst koennte ein
        einzelner unbekannter Track faelschlich als Duplikat eines anderen
        unbekannten Tracks erkannt werden."""
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

        duplicate_detector.check_for_duplicates.assert_not_called()
        assert processor.download_executor.download_single_track.call_count == 1
