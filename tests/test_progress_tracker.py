"""
Unit-Tests für ProgressTracker (services/downloader/utils/progress_tracker.py)
— vorher 0 Tests, gefunden über die systematische Ungetestet-Prüfung.

Live genutzt: klassen/download_handler.py und services/downloader/utils/
download_utils.py instanziieren ProgressTracker, mutieren danach aber nur
noch das status_message-Attribut direkt von aussen. Die eigentlichen
Methoden (update_progress/set_current_item) sowie die Modul-Funktionen
progress_hook()/track_performance() haben KEINE Aufrufer im Repo -
charakterisiert, nicht entfernt (funktionieren korrekt, könnten künftig
genutzt werden, kein Grund zur Annahme dass sie tot bleiben sollen).

Regressionstest fuer einen dabei gefundenen, aktuell unerreichbaren aber
echten Bug: EnhancedDownloadProcessor.cleanup() (download_utils.py) rief
self.tracker.cleanup() auf, obwohl ProgressTracker gar keine cleanup()-
Methode hatte - waere ein AttributeError gewesen, sobald init_tracker()
(der einzige Pfad der self.tracker setzt) jemals tatsaechlich aufgerufen
wird (aktuell: nirgends). Fix: ProgressTracker.cleanup() als No-Op
ergaenzt (die Klasse haelt keine eigenen freizugebenden Ressourcen).
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from services.downloader.utils.progress_tracker import (
    ProgressTracker,
    progress_hook,
    track_performance,
)


def make_update():
    update = Mock()
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    return update


class TestProgressTrackerConstruction:
    def test_defaults(self):
        tracker = ProgressTracker(make_update())
        assert tracker.total_items == 1
        assert tracker.processed_items == 0
        assert tracker.current_item == ""

    def test_custom_total_items_and_status_message(self):
        update = make_update()
        status_msg = Mock()
        tracker = ProgressTracker(update, total_items=10, status_message=status_msg)
        assert tracker.total_items == 10
        assert tracker.status_message is status_msg


class TestUpdateProgress:
    """
    update_progress() sendet nur, wenn seit last_update_time mehr als
    update_interval (5s) vergangen ist ODER der letzte Item erreicht wurde
    (processed_items == total_items). Bei total_items > 1 sendet der ERSTE
    Aufruf daher NICHT automatisch, solange keine 5 echten Sekunden
    vergangen sind - charakterisiert per last_update_time-Manipulation
    statt echtem time.sleep().
    """

    def test_no_message_sent_before_interval_elapses_and_not_final_item(self):
        update = make_update()
        tracker = ProgressTracker(update, total_items=5)

        asyncio.run(tracker.update_progress())

        update.message.reply_text.assert_not_called()
        assert tracker.processed_items == 1

    def test_sends_generated_message_once_interval_has_elapsed(self):
        update = make_update()
        tracker = ProgressTracker(update, total_items=5)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        asyncio.run(tracker.update_progress())

        update.message.reply_text.assert_called_once()
        sent = update.message.reply_text.call_args[0][0]
        assert "1/5" in sent

    def test_custom_message_is_used_verbatim_once_interval_has_elapsed(self):
        update = make_update()
        tracker = ProgressTracker(update, total_items=5)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        asyncio.run(tracker.update_progress("Custom status"))

        update.message.reply_text.assert_called_once_with("Custom status")

    def test_rapid_successive_updates_are_throttled(self):
        """
        Nach einem erfolgreichen Update wird last_update_time aktualisiert -
        ein zweiter Aufruf direkt danach (kein vergangener Zeitraum) sendet
        keine weitere Nachricht, solange nicht auch total_items erreicht ist.
        """
        update = make_update()
        tracker = ProgressTracker(update, total_items=10)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        asyncio.run(tracker.update_progress())  # sendet (Intervall abgelaufen)
        asyncio.run(tracker.update_progress())  # gedrosselt, kein Intervall vergangen

        assert update.message.reply_text.call_count == 1
        assert tracker.processed_items == 2

    def test_final_item_always_sends_regardless_of_throttle(self):
        update = make_update()
        tracker = ProgressTracker(update, total_items=1)

        asyncio.run(tracker.update_progress())

        update.message.reply_text.assert_called_once()

    def test_current_item_is_included_in_generated_message(self):
        update = make_update()
        tracker = ProgressTracker(update, total_items=3)
        tracker.set_current_item("Song A")
        # Throttle umgehen: letzte Aktualisierung in die Vergangenheit setzen.
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        asyncio.run(tracker.update_progress())

        sent = update.message.reply_text.call_args[0][0]
        assert "Song A" in sent

    def test_exception_during_send_is_caught_not_raised(self):
        update = make_update()
        update.message.reply_text = AsyncMock(side_effect=RuntimeError("boom"))
        tracker = ProgressTracker(update, total_items=1)

        asyncio.run(tracker.update_progress())  # darf nicht raisen


class TestSetCurrentItem:
    def test_updates_current_item_attribute(self):
        tracker = ProgressTracker(make_update())
        tracker.set_current_item("Track 3")
        assert tracker.current_item == "Track 3"


class TestCleanup:
    def test_cleanup_does_not_raise(self):
        tracker = ProgressTracker(make_update())
        tracker.cleanup()  # darf nicht raisen, keine Rueckgabe erwartet


class TestProgressHook:
    def test_finished_status_logs_info(self):
        tracker = ProgressTracker(make_update())
        logger = Mock()
        progress_hook(tracker, {"status": "finished", "filename": "song.mp3"}, logger_factory=lambda name: logger)
        logger.info.assert_called_once()

    def test_error_status_logs_error(self):
        tracker = ProgressTracker(make_update())
        logger = Mock()
        progress_hook(
            tracker,
            {"status": "error", "filename": "song.mp3", "error": "network"},
            logger_factory=lambda name: logger,
        )
        logger.error.assert_called_once()

    def test_unknown_status_logs_nothing(self):
        tracker = ProgressTracker(make_update())
        logger = Mock()
        progress_hook(
            tracker, {"status": "downloading", "filename": "song.mp3"}, logger_factory=lambda name: logger
        )
        logger.info.assert_not_called()
        logger.error.assert_not_called()


class TestTrackPerformance:
    def test_wraps_async_function_and_returns_its_result(self):
        logger = Mock()

        async def sample():
            return 42

        wrapped = track_performance(sample, logger_factory=lambda name: logger)
        result = asyncio.run(wrapped())

        assert result == 42
        logger.info.assert_called_once()


class TestEnhancedDownloadProcessorCleanupRegression:
    """
    Regressionstest fuer den Fund: EnhancedDownloadProcessor.cleanup()
    (services/downloader/utils/download_utils.py) ruft self.tracker.cleanup()
    auf - vor dem Fix haette das mit AttributeError gecrasht, sobald
    self.tracker ein ProgressTracker ist (aktuell unerreichbar, da
    init_tracker() nirgends aufgerufen wird - aber ein echter Bug, sollte
    sich das aendern). object.__new__() umgeht die schwere SingletonMixin-
    _do_init()-Initialisierung, die hier nicht gebraucht wird.
    """

    def test_cleanup_does_not_crash_when_tracker_is_a_real_progress_tracker(self):
        from services.downloader.utils.download_utils import EnhancedDownloadProcessor

        proc = object.__new__(EnhancedDownloadProcessor)
        proc.logger = Mock()
        proc.metadata_cache = Mock()
        proc.tracker = ProgressTracker(make_update())

        proc.cleanup()  # darf nicht raisen

        proc.metadata_cache.cleanup.assert_called_once()
