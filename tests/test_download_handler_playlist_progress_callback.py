"""
Regressionstests fuer klassen/download_handler.py::_on_playlist_progress()
- vorher 0 Tests (neue Methode).

Playlist-Progress-State 2026-09-02 (Nutzer-Wunsch): _on_playlist_progress()
ist der Telegram-seitige Gegenpart zu ProgressTracker (services/downloader/
progress_tracker.py, telegram-frei) - erhaelt den Tracker als reinen
Zustand und baut daraus die mehrzeilige Playlist-Fortschrittsmeldung
(Fortschrittsbalken + "⬇️ Aktuell"/"✅ Abgeschlossen"-Sektionen). Wird als
status_callback an YoutubeDownloader uebergeben (services/downloader/
downloader.py) - siehe tests/test_youtube_downloader_telegram_decoupling.py
fuer die Weiterleitung dorthin, tests/test_playlist_progress_callback.py
fuer den Aufruf-Kontrollfluss in _process_playlist_download().

DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht
ihn bewusst (etabliertes Muster, siehe
tests/test_download_handler_send_report_message.py), da
_on_playlist_progress() nur self.status_msg/self.logger tatsaechlich
verwendet.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import TelegramError

from klassen.download_handler import DownloadHandler
from services.downloader.progress_tracker import ProgressTracker


def run_async(coro):
    return asyncio.run(coro)


def make_handler(status_msg=None):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.status_msg = status_msg
    return handler


def make_status_msg():
    msg = Mock()
    msg.edit_text = AsyncMock()
    return msg


def make_tracker(total_items=3, current_item="", completed_items=None):
    tracker = ProgressTracker(total_items=total_items)
    tracker.current_item = current_item
    tracker.completed_items = list(completed_items or [])
    tracker.processed_items = len(tracker.completed_items)
    return tracker


class TestOnPlaylistProgress:
    def test_does_nothing_when_no_status_msg(self):
        handler = make_handler(status_msg=None)
        tracker = make_tracker()

        run_async(handler._on_playlist_progress(tracker))
        # Kein Crash, kein Versand-Versuch (nichts zu pruefen, da kein Mock
        # vorhanden - der reine Nicht-Absturz ist die Assertion).

    def test_shows_current_item_section(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        tracker = make_tracker(current_item="03 - Trackname")

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "⬇️ Aktuell" in sent
        assert "03 - Trackname" in sent

    def test_shows_completed_items_section(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        tracker = make_tracker(
            current_item="03 - Track C",
            completed_items=["01 - Track A", "02 - Track B"],
        )

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "✅ Abgeschlossen" in sent
        assert "01 - Track A" in sent
        assert "02 - Track B" in sent

    def test_omits_current_section_when_no_current_item(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        tracker = make_tracker(current_item="", completed_items=["01 - Track A"])

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "⬇️ Aktuell" not in sent

    def test_omits_completed_section_when_nothing_completed_yet(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        tracker = make_tracker(current_item="01 - Track A", completed_items=[])

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "✅ Abgeschlossen" not in sent

    def test_shows_step_3_of_6_header_matching_existing_pipeline_steps(self):
        """Die Kopfzeile bleibt der bestehende Schritt-3/6-Fortschrittsbalken
        (Audio-Download) - unabhaengig von der Anzahl Tracks in der
        Playlist, konsistent mit den anderen 5 Pipeline-Schritten."""
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        tracker = make_tracker(total_items=20, current_item="01 - X")

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "3/6" in sent
        assert "Audio-Download" in sent

    def test_truncates_completed_items_to_last_eight_with_indicator(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)
        completed = [f"{i:02d} - Track {i}" for i in range(1, 11)]  # 10 Stueck
        tracker = make_tracker(
            total_items=12, current_item="11 - Track 11", completed_items=completed
        )

        run_async(handler._on_playlist_progress(tracker))

        sent = status_msg.edit_text.call_args[0][0]
        assert "01 - Track 1" not in sent  # zu alt, nicht mehr gezeigt
        assert "10 - Track 10" in sent      # letztes vor "Aktuell"
        assert "2 weitere" in sent

    def test_telegram_error_is_caught_not_raised(self):
        status_msg = make_status_msg()
        status_msg.edit_text.side_effect = TelegramError("boom")
        handler = make_handler(status_msg)
        tracker = make_tracker(current_item="01 - X")

        run_async(handler._on_playlist_progress(tracker))  # darf nicht raisen

        handler.logger.warning.assert_called_once()

    def test_message_is_not_modified_error_is_silently_ignored(self):
        status_msg = make_status_msg()
        status_msg.edit_text.side_effect = TelegramError("Message is not modified")
        handler = make_handler(status_msg)
        tracker = make_tracker(current_item="01 - X")

        run_async(handler._on_playlist_progress(tracker))

        handler.logger.warning.assert_not_called()
