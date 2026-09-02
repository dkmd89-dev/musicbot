"""
Download-Control-Center 2026-09-02: klassen/download_handler.py::
handle_youtube_links() registriert/deregistriert den aktiven Download bei
der geteilten ActiveDownloadRegistry (services/downloader/active_downloads.py)
und behandelt einen per ❌-Button abgebrochenen Download separat von einem
generischen Fehlschlag.

DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht
ihn bewusst (etabliertes Muster dieser Session, siehe
test_download_handler_youtube_pipeline_failure_reporting.py, dessen
make_handler()-Helper hier fast unveraendert uebernommen wird).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from klassen.download_handler import DownloadHandler
from services.downloader.active_downloads import ActiveDownloadRegistry
from services.downloader.download_result_reporter import DownloadResultReporter


def run_async(coro):
    return asyncio.run(coro)


def make_status_msg():
    msg = Mock()
    msg.edit_text = AsyncMock()
    return msg


def make_handler(download_audio_result, url="https://youtube.com/watch?v=abc123", active_downloads=None):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.config = Mock()
    handler.cookie_handler = Mock()
    handler.active_downloads = active_downloads
    handler.active_download = None

    status_msg = make_status_msg()

    handler.update = Mock()
    handler.update.message = Mock()
    handler.update.message.text = url
    handler.update.message.reply_text = AsyncMock(return_value=status_msg)
    handler.update.effective_chat = Mock(id=12345)
    handler.update.update_id = 1

    handler.duplicate_detector = Mock()
    handler.duplicate_detector.check_for_duplicates = Mock(
        return_value=(False, None, "none")
    )
    handler.duplicate_detector.register_download = Mock()
    handler.duplicate_detector.get_statistics = Mock(return_value={})

    handler.downloader = Mock()
    handler.downloader.download_audio = AsyncMock(return_value=download_audio_result)

    handler.result_reporter = DownloadResultReporter(logger=Mock())

    return handler, status_msg


class TestActiveDownloadRegistration:
    def test_registers_before_download_and_unregisters_on_success(self):
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        handler, _ = make_handler(
            {"success": True, "type": "single", "track_info": {}, "title": "T"},
            active_downloads=registry,
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert registry.is_active(12345) is False  # deregistriert nach Abschluss

    def test_unregisters_after_a_normal_failure(self):
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        handler, _ = make_handler(
            {"success": False, "error": "boom"}, active_downloads=registry
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert registry.is_active(12345) is False

    def test_unregisters_even_when_download_audio_raises(self):
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        handler, _ = make_handler({}, active_downloads=registry)
        handler.downloader.download_audio = AsyncMock(side_effect=RuntimeError("kaputt"))

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert registry.is_active(12345) is False

    def test_no_registry_does_not_crash(self):
        """Regressionsschutz: active_downloads=None (Default, z.B. Tests
        ohne Registry) - unveraendertes bisheriges Verhalten."""
        handler, status_msg = make_handler(
            {"success": True, "type": "single", "track_info": {}, "title": "T"},
            active_downloads=None,
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert status_msg.edit_text.await_count >= 1

    def test_existing_injected_downloader_mock_is_not_overwritten(self):
        """Regressionsanker: handle_youtube_links() darf handler.downloader
        (vom Test injizierter Mock) NICHT durch eine echte YoutubeDownloader-
        Instanz ersetzen - sonst wuerden alle bestehenden
        handler.downloader.download_audio-Mocks wirkungslos."""
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        handler, _ = make_handler(
            {"success": True, "type": "single", "track_info": {}, "title": "T"},
            active_downloads=registry,
        )
        injected_mock = handler.downloader

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert handler.downloader is injected_mock
        injected_mock.download_audio.assert_awaited_once()

    def test_download_type_heuristic_detects_playlist_url(self):
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        captured = {}
        orig_register = registry.register

        def spy_register(**kwargs):
            captured.update(kwargs)
            return orig_register(**kwargs)

        registry.register = spy_register
        handler, _ = make_handler(
            {"success": True, "type": "playlist", "tracks": []},
            url="https://youtube.com/playlist?list=PLxyz",
            active_downloads=registry,
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert captured["download_type"] == "playlist"

    def test_download_type_heuristic_detects_single_url(self):
        registry = ActiveDownloadRegistry(logger_factory=lambda n: Mock())
        captured = {}
        orig_register = registry.register

        def spy_register(**kwargs):
            captured.update(kwargs)
            return orig_register(**kwargs)

        registry.register = spy_register
        handler, _ = make_handler(
            {"success": True, "type": "single", "track_info": {}, "title": "T"},
            url="https://youtube.com/watch?v=abc123",
            active_downloads=registry,
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        assert captured["download_type"] == "single"


class TestCancelledDownloadHandling:
    def test_cancelled_single_download_shows_abort_message(self):
        handler, status_msg = make_handler(
            {"success": False, "error": "Download abgebrochen", "cancelled": True}
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "abgebrochen" in final_text.lower()
        assert "fehlgeschlagen" not in final_text.lower()

    def test_cancelled_playlist_with_zero_tracks_shows_abort_message(self):
        """Abbruch bevor auch nur ein Track fertig wurde - kein Grund, die
        normale Metadaten-/Zusammenfassungs-Pipeline fuer eine leere
        Track-Liste zu durchlaufen."""
        handler, status_msg = make_handler(
            {
                "success": True,
                "type": "playlist",
                "tracks": [],
                "cancelled": True,
            }
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "abgebrochen" in final_text.lower()

    def test_cancelled_playlist_with_partial_tracks_runs_normal_summary(self):
        """Mit bereits fertigen Tracks laeuft die normale Pipeline weiter -
        die Zusammenfassung selbst (DownloadResultReporter) macht den
        Abbruch sichtbar (siehe tests/test_download_result_reporter.py::
        TestBuildFinalSummaryMessageCancelled)."""
        handler, status_msg = make_handler(
            {
                "success": True,
                "type": "playlist",
                "tracks": [{"success": True, "title": "Track 1", "artist": "A"}],
                "cancelled": True,
            }
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "🛑 Download abgebrochen" in final_text

    def test_non_cancelled_success_never_shows_abort_message(self):
        handler, status_msg = make_handler(
            {"success": True, "type": "single", "track_info": {}, "title": "T"}
        )

        run_async(handler.handle_youtube_links(handler.update, Mock()))

        final_text = status_msg.edit_text.await_args.args[0]
        assert "abgebrochen" not in final_text.lower()
