# tests/test_download_pipeline_core.py
# -*- coding: utf-8 -*-
"""
services/downloader/download_pipeline_core.py — direkte Unit-Tests der
Telegram-freien Bausteine (Client Consolidation Phase D/E, Move aus
klassen/download_handler.py). Ergänzt die bereits bestehende, indirekte
Abdeckung über DownloadHandler (tests/test_download_handler_*.py) um
direkte Tests der Modulfunktionen selbst - das ist jetzt die Schnittstelle,
die ein künftiger Control-Center-Download-Job aufruft.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import services.downloader.download_pipeline_core as core
from services.downloader.download_history import DownloadHistoryStore


def run_async(coro):
    return asyncio.run(coro)


def make_logger():
    return Mock()


class TestProcessSingleDownloadResult:
    def test_playlist_wrapper_is_passed_through_unchanged(self):
        result = {"type": "playlist", "tracks": []}
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out is result

    def test_already_processed_result_is_passed_through(self):
        result = {"library_path": "/x/y.m4a"}
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out == result

    def test_filepath_fallback_from_filename(self):
        result = {"filename": "/x/song.m4a"}
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out["filepath"] == "/x/song.m4a"

    def test_filepath_fallback_from_requested_downloads(self):
        result = {"requested_downloads": [{"filepath": "/x/req.m4a"}]}
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out["filepath"] == "/x/req.m4a"

    def test_title_fallback_replaces_playlist_placeholder(self):
        result = {"title": "Playlist", "fulltitle": "Echter Titel"}
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out["title"] == "Echter Titel"

    def test_unexpected_exception_returns_result_unchanged(self):
        class Explosive(dict):
            def get(self, *a, **kw):
                if a and a[0] == "type":
                    raise RuntimeError("boom")
                return super().get(*a, **kw)

        result = Explosive({"title": "X"})
        out = run_async(core.process_single_download_result(result, make_logger()))
        assert out is result


class TestProbeArtistTitleForDuplicateCheck:
    def _make_downloader(self, extract_info_result):
        downloader = Mock()
        executor = downloader.enhanced_download_processor.download_executor
        executor.build_ydl_opts = Mock(return_value={})
        executor.extract_info_async = AsyncMock(return_value=extract_info_result)
        return downloader, executor

    def test_returns_uploader_and_title_on_success(self):
        downloader, _ = self._make_downloader(
            {"uploader": "Der Artist", "title": "Der Song"}
        )
        artist, title = run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader, Mock(), "https://youtube.com/watch?v=x", make_logger()
            )
        )
        assert artist == "Der Artist"
        assert title == "Der Song"

    def test_falls_back_to_channel_when_no_uploader(self):
        downloader, _ = self._make_downloader({"channel": "Kanal", "title": "T"})
        artist, _ = run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader, Mock(), "https://youtube.com/watch?v=x", make_logger()
            )
        )
        assert artist == "Kanal"

    def test_playlist_entries_yield_none_none(self):
        downloader, _ = self._make_downloader({"entries": [{}]})
        artist, title = run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader, Mock(), "https://youtube.com/playlist?list=x", make_logger()
            )
        )
        assert (artist, title) == (None, None)

    def test_empty_info_yields_none_none(self):
        downloader, _ = self._make_downloader(None)
        artist, title = run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader, Mock(), "https://youtube.com/watch?v=x", make_logger()
            )
        )
        assert (artist, title) == (None, None)

    def test_exception_is_caught_and_yields_none_none(self):
        downloader = Mock()
        downloader.enhanced_download_processor.download_executor.build_ydl_opts = Mock(
            side_effect=RuntimeError("boom")
        )
        artist, title = run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader, Mock(), "https://youtube.com/watch?v=x", make_logger()
            )
        )
        assert (artist, title) == (None, None)

    def test_mix_url_forces_noplaylist_and_disables_cache(self):
        downloader, executor = self._make_downloader({"title": "T", "uploader": "A"})
        run_async(
            core.probe_artist_title_for_duplicate_check(
                downloader,
                Mock(),
                "https://youtube.com/watch?v=x&list=RDabc",
                make_logger(),
            )
        )
        called_opts = executor.extract_info_async.call_args.args[1]
        assert called_opts.get("noplaylist") is True
        assert executor.extract_info_async.call_args.kwargs["use_cache"] is False


class TestCheckDuplicatesBeforeDownload:
    def test_delegates_to_detector_with_probed_artist_title(self):
        downloader = Mock()
        executor = downloader.enhanced_download_processor.download_executor
        executor.build_ydl_opts = Mock(return_value={})
        executor.extract_info_async = AsyncMock(
            return_value={"uploader": "A", "title": "T"}
        )
        detector = Mock()
        detector.check_for_duplicates = Mock(return_value=(True, Mock(), "url"))

        result = run_async(
            core.check_duplicates_before_download(
                detector, downloader, Mock(), "https://youtube.com/watch?v=x", make_logger()
            )
        )

        detector.check_for_duplicates.assert_called_once_with(
            url="https://youtube.com/watch?v=x", raw_artist="A", raw_title="T"
        )
        assert result[0] is True


class TestRecordHistoryEntry:
    def test_writes_entry_when_history_and_chat_id_present(self, tmp_path):
        store = DownloadHistoryStore(cache_dir=str(tmp_path))
        core.record_history_entry(
            store,
            123,
            url="https://x",
            title="T",
            artist="A",
            status="success",
            logger=make_logger(),
        )
        entries = store.get_recent(123)
        assert len(entries) == 1
        assert entries[0].status == "success"

    def test_noop_when_history_is_none(self):
        core.record_history_entry(
            None, 123, url="x", title="t", artist="a", status="success", logger=make_logger()
        )  # darf nicht werfen

    def test_noop_when_chat_id_is_none(self, tmp_path):
        store = DownloadHistoryStore(cache_dir=str(tmp_path))
        core.record_history_entry(
            store, None, url="x", title="t", artist="a", status="success", logger=make_logger()
        )
        assert store.get_all_recent() == []

    def test_broken_store_logs_warning_but_does_not_raise(self):
        store = Mock()
        store.add_entry = Mock(side_effect=RuntimeError("disk full"))
        logger = make_logger()
        core.record_history_entry(
            store, 123, url="x", title="t", artist="a", status="success", logger=logger
        )
        logger.warning.assert_called_once()


class TestRegisterSingleTrackDuplicate:
    def test_registers_when_artist_and_title_present(self):
        detector = Mock()
        core.register_single_track_duplicate(
            detector,
            url="https://x",
            artist="Artist",
            title="Title",
            path="/lib/x.m4a",
            album="Album",
            year=2024,
            logger=make_logger(),
        )
        detector.register_download.assert_called_once()
        kwargs = detector.register_download.call_args.kwargs
        assert kwargs["artist"] == "Artist"
        assert kwargs["file_path"] == Path("/lib/x.m4a")

    @pytest.mark.parametrize("placeholder", ["?", "Unbekannt", "Unknown Artist"])
    def test_skips_placeholder_artist(self, placeholder):
        detector = Mock()
        core.register_single_track_duplicate(
            detector,
            url="https://x",
            artist=placeholder,
            title="Title",
            path=None,
            album=None,
            year=None,
            logger=make_logger(),
        )
        detector.register_download.assert_not_called()

    def test_exception_is_caught_and_logged(self):
        detector = Mock()
        detector.register_download = Mock(side_effect=RuntimeError("boom"))
        logger = make_logger()
        core.register_single_track_duplicate(
            detector,
            url="https://x",
            artist="Artist",
            title="Title",
            path=None,
            album=None,
            year=None,
            logger=logger,
        )
        logger.error.assert_called_once()


class TestRegisterPlaylistTrackDuplicates:
    def test_registers_each_successful_track_and_writes_history(self, tmp_path):
        store = DownloadHistoryStore(cache_dir=str(tmp_path))
        detector = Mock()
        tracks = [
            {"success": True, "artist": "A1", "title": "T1", "url": "u1"},
            {"success": True, "artist": "A2", "title": "T2", "url": "u2"},
            {"success": False, "artist": "A3", "title": "T3"},
        ]
        core.register_playlist_track_duplicates(detector, store, 42, tracks, make_logger())

        assert detector.register_download.call_count == 2
        assert len(store.get_recent(42)) == 2

    def test_conflict_track_deletes_file_and_does_not_register(self, tmp_path):
        conflict_file = tmp_path / "dup.m4a"
        conflict_file.write_text("x")
        detector = Mock()
        tracks = [
            {
                "success": True,
                "artist": "A",
                "title": "T",
                "renamed_due_to_conflict": True,
                "library_path": str(conflict_file),
            }
        ]
        core.register_playlist_track_duplicates(detector, None, 1, tracks, make_logger())

        detector.register_download.assert_not_called()
        assert not conflict_file.exists()

    def test_placeholder_artist_track_is_skipped(self):
        detector = Mock()
        tracks = [{"success": True, "artist": "?", "title": "T"}]
        core.register_playlist_track_duplicates(detector, None, 1, tracks, make_logger())
        detector.register_download.assert_not_called()


class TestResolveFileConflictAsDuplicate:
    def test_deletes_existing_file_and_builds_entry(self, tmp_path):
        conflict_file = tmp_path / "song (1).m4a"
        conflict_file.write_text("x")
        res = {
            "title": "Song",
            "artist": "Artist",
            "library_path": str(conflict_file),
        }
        entry = core.resolve_file_conflict_as_duplicate(res, "https://x", make_logger())

        assert not conflict_file.exists()
        assert entry.title == "Song"
        assert entry.artist == "Artist"
        assert "(1)" not in str(entry.file_path)

    def test_missing_file_does_not_raise(self, tmp_path):
        res = {
            "title": "Song",
            "artist": "Artist",
            "library_path": str(tmp_path / "nonexistent.m4a"),
        }
        entry = core.resolve_file_conflict_as_duplicate(res, "https://x", make_logger())
        assert entry.url == "https://x"
