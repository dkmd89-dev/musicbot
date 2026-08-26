"""
P1-Fund (Post-Baseline-v4 Health & Risk Audit, Finding 1):
klassen/download_handler.py::_check_duplicates_before_download() rief
DuplicateDetector.check_for_duplicates() produktiv bisher ausschliesslich
mit url= auf - die Content-/Parser-/Library-Fallback-Ebenen in
DuplicateDetector (services/duplicate/detector.py) waren dadurch vor dem
eigentlichen Download nie erreichbar (z.B. dieselbe Aufnahme unter einer
anderen Video-ID erneut hochgeladen, aber unter neuer URL).

Fix: ein leichtgewichtiger yt-dlp-Vorab-Abruf (download=False) ermittelt
Artist/Titel VOR dem Duplikat-Check und reicht sie an check_for_duplicates()
durch. Schlaegt der Abruf fehl oder ist die URL eine Playlist (kein
einzelner Songtitel), bleibt die bisherige URL-only-Pruefung unveraendert
aktiv - nichts wird blockiert.

DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht
ihn bewusst (etabliertes Muster dieser Session, siehe
test_download_handler_youtube_pipeline_failure_reporting.py).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler


def run_async(coro):
    return asyncio.run(coro)


def make_handler(extract_info_result=None, extract_info_side_effect=None):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.config = Mock()

    handler.duplicate_detector = Mock()
    handler.duplicate_detector.check_for_duplicates = Mock(
        return_value=(False, None, "none")
    )

    download_executor = Mock()
    download_executor.build_ydl_opts = Mock(return_value={})
    if extract_info_side_effect is not None:
        download_executor.extract_info_async = AsyncMock(
            side_effect=extract_info_side_effect
        )
    else:
        download_executor.extract_info_async = AsyncMock(
            return_value=extract_info_result
        )

    handler.downloader = Mock()
    handler.downloader.enhanced_download_processor = Mock()
    handler.downloader.enhanced_download_processor.download_executor = download_executor

    return handler


class TestProbeArtistTitle:
    def test_returns_uploader_and_title_from_successful_probe(self):
        handler = make_handler(
            extract_info_result={"title": "Song Title", "uploader": "Some Channel"}
        )

        raw_artist, raw_title = run_async(
            handler._probe_artist_title_for_duplicate_check("https://youtube.com/watch?v=x")
        )

        assert raw_artist == "Some Channel"
        assert raw_title == "Song Title"

    def test_falls_back_to_channel_when_uploader_missing(self):
        handler = make_handler(
            extract_info_result={"title": "Song Title", "channel": "Channel Name"}
        )

        raw_artist, raw_title = run_async(
            handler._probe_artist_title_for_duplicate_check("https://youtube.com/watch?v=x")
        )

        assert raw_artist == "Channel Name"

    def test_playlist_result_with_entries_returns_none_none(self):
        handler = make_handler(
            extract_info_result={"title": "My Playlist", "entries": [{"title": "T1"}]}
        )

        raw_artist, raw_title = run_async(
            handler._probe_artist_title_for_duplicate_check("https://youtube.com/playlist?list=x")
        )

        assert (raw_artist, raw_title) == (None, None)

    def test_empty_info_returns_none_none(self):
        handler = make_handler(extract_info_result=None)

        raw_artist, raw_title = run_async(
            handler._probe_artist_title_for_duplicate_check("https://youtube.com/watch?v=x")
        )

        assert (raw_artist, raw_title) == (None, None)

    def test_extraction_failure_is_swallowed_and_returns_none_none(self):
        """
        Deterministischer Beweis: ein echter Fehler (nicht nur ein leerer
        Rueckgabewert) darf den Duplikat-Check nicht blockieren.
        """
        handler = make_handler(extract_info_side_effect=RuntimeError("yt-dlp boom"))

        raw_artist, raw_title = run_async(
            handler._probe_artist_title_for_duplicate_check("https://youtube.com/watch?v=x")
        )

        assert (raw_artist, raw_title) == (None, None)
        handler.logger.warning.assert_called_once()


class TestCheckDuplicatesBeforeDownloadPassesProbeResult:
    def test_probed_artist_and_title_are_passed_to_check_for_duplicates(self):
        handler = make_handler(
            extract_info_result={"title": "Song Title", "uploader": "Some Channel"}
        )

        run_async(
            handler._check_duplicates_before_download("https://youtube.com/watch?v=x")
        )

        handler.duplicate_detector.check_for_duplicates.assert_called_once_with(
            url="https://youtube.com/watch?v=x",
            raw_artist="Some Channel",
            raw_title="Song Title",
        )

    def test_failed_probe_still_calls_check_for_duplicates_with_none_values(self):
        handler = make_handler(extract_info_side_effect=RuntimeError("boom"))

        run_async(
            handler._check_duplicates_before_download("https://youtube.com/watch?v=x")
        )

        handler.duplicate_detector.check_for_duplicates.assert_called_once_with(
            url="https://youtube.com/watch?v=x",
            raw_artist=None,
            raw_title=None,
        )
