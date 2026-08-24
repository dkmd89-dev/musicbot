"""
Unit-Tests für ProgressTracker (services/downloader/utils/progress_tracker.py)
— vorher 0 Tests, gefunden über die systematische Ungetestet-Prüfung.

ARCH-007/P-2 (2026-08-24): update_progress() wurde zu
compute_progress_message() - berechnet den Fortschrittstext weiterhin nach
derselben Drossel-/ETA-Logik, sendet ihn aber nicht mehr selbst (services/
hat keine Telegram-Abhängigkeit mehr). Der update-Konstruktorparameter
entfiel ersatzlos, da der sendende Pfad bereits vorher 0 Aufrufer im
Produktionscode hatte (klassen/download_handler.py mutierte nur noch das
inzwischen ebenfalls entfernte status_message-Attribut, ohne
update_progress()/set_current_item() je aufzurufen). Tests wurden auf
Rückgabewert-Assertions statt Telegram-Mock-Assertions umgestellt.

set_current_item() sowie die Modul-Funktionen progress_hook()/
track_performance() haben weiterhin KEINE Aufrufer im Repo -
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
from unittest.mock import Mock

import pytest

from services.downloader.utils.progress_tracker import (
    ProgressTracker,
    progress_hook,
    track_performance,
)


class TestProgressTrackerConstruction:
    def test_defaults(self):
        tracker = ProgressTracker()
        assert tracker.total_items == 1
        assert tracker.processed_items == 0
        assert tracker.current_item == ""

    def test_custom_total_items(self):
        tracker = ProgressTracker(total_items=10)
        assert tracker.total_items == 10


class TestComputeProgressMessage:
    """
    compute_progress_message() gibt nur einen Text zurueck, wenn seit
    last_update_time mehr als update_interval (5s) vergangen ist ODER der
    letzte Item erreicht wurde (processed_items == total_items), sonst
    None. Bei total_items > 1 liefert der ERSTE Aufruf daher automatisch
    None, solange keine 5 echten Sekunden vergangen sind - charakterisiert
    per last_update_time-Manipulation statt echtem time.sleep().
    """

    def test_no_message_before_interval_elapses_and_not_final_item(self):
        tracker = ProgressTracker(total_items=5)

        result = tracker.compute_progress_message()

        assert result is None
        assert tracker.processed_items == 1

    def test_returns_generated_message_once_interval_has_elapsed(self):
        tracker = ProgressTracker(total_items=5)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        result = tracker.compute_progress_message()

        assert result is not None
        assert "1/5" in result

    def test_custom_message_is_returned_verbatim_once_interval_has_elapsed(self):
        tracker = ProgressTracker(total_items=5)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        result = tracker.compute_progress_message("Custom status")

        assert result == "Custom status"

    def test_rapid_successive_calls_are_throttled(self):
        """
        Nach einem erfolgreichen Aufruf wird last_update_time aktualisiert -
        ein zweiter Aufruf direkt danach (kein vergangener Zeitraum) liefert
        None, solange nicht auch total_items erreicht ist.
        """
        tracker = ProgressTracker(total_items=10)
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        first = tracker.compute_progress_message()  # Intervall abgelaufen
        second = tracker.compute_progress_message()  # gedrosselt

        assert first is not None
        assert second is None
        assert tracker.processed_items == 2

    def test_final_item_always_returns_message_regardless_of_throttle(self):
        tracker = ProgressTracker(total_items=1)

        result = tracker.compute_progress_message()

        assert result is not None

    def test_current_item_is_included_in_generated_message(self):
        tracker = ProgressTracker(total_items=3)
        tracker.set_current_item("Song A")
        # Throttle umgehen: letzte Aktualisierung in die Vergangenheit setzen.
        tracker.last_update_time = datetime.now() - timedelta(seconds=10)

        result = tracker.compute_progress_message()

        assert "Song A" in result


class TestSetCurrentItem:
    def test_updates_current_item_attribute(self):
        tracker = ProgressTracker()
        tracker.set_current_item("Track 3")
        assert tracker.current_item == "Track 3"


class TestCleanup:
    def test_cleanup_does_not_raise(self):
        tracker = ProgressTracker()
        tracker.cleanup()  # darf nicht raisen, keine Rueckgabe erwartet


class TestProgressHook:
    def test_finished_status_logs_info(self):
        tracker = ProgressTracker()
        logger = Mock()
        progress_hook(tracker, {"status": "finished", "filename": "song.mp3"}, logger_factory=lambda name: logger)
        logger.info.assert_called_once()

    def test_error_status_logs_error(self):
        tracker = ProgressTracker()
        logger = Mock()
        progress_hook(
            tracker,
            {"status": "error", "filename": "song.mp3", "error": "network"},
            logger_factory=lambda name: logger,
        )
        logger.error.assert_called_once()

    def test_unknown_status_logs_nothing(self):
        tracker = ProgressTracker()
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
        proc.tracker = ProgressTracker()

        proc.cleanup()  # darf nicht raisen

        proc.metadata_cache.cleanup.assert_called_once()
