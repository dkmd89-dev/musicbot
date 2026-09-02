"""
Unit-Tests für ActiveDownloadRegistry (services/downloader/active_downloads.py)
— neu für das Telegram Download-Control-Center (2026-09-02).

Deckt reinen Zustand ab (register/unregister/get/is_active,
cancel_event-Thread-Sicherheit) - keine Telegram-/yt-dlp-Abhängigkeit.
"""

import threading
from unittest.mock import Mock

from services.downloader.active_downloads import ActiveDownload, ActiveDownloadRegistry


def make_registry():
    return ActiveDownloadRegistry(logger_factory=lambda name: Mock())


class TestRegister:
    def test_register_returns_active_download_with_given_fields(self):
        registry = make_registry()

        entry = registry.register(chat_id=42, url="https://youtu.be/x", download_type="single")

        assert entry.chat_id == 42
        assert entry.url == "https://youtu.be/x"
        assert entry.download_type == "single"
        assert entry.cancelled is False

    def test_register_makes_chat_active(self):
        registry = make_registry()
        registry.register(chat_id=42, url="u", download_type="single")

        assert registry.is_active(42) is True

    def test_different_chat_ids_are_independent(self):
        registry = make_registry()
        registry.register(chat_id=1, url="u1", download_type="single")

        assert registry.is_active(2) is False

    def test_register_replaces_existing_entry_for_same_chat(self):
        registry = make_registry()
        first = registry.register(chat_id=1, url="old", download_type="single")
        second = registry.register(chat_id=1, url="new", download_type="playlist")

        assert registry.get(1) is second
        assert registry.get(1).url == "new"
        assert registry.get(1) is not first


class TestUnregister:
    def test_unregister_makes_chat_inactive(self):
        registry = make_registry()
        registry.register(chat_id=1, url="u", download_type="single")

        registry.unregister(1)

        assert registry.is_active(1) is False
        assert registry.get(1) is None

    def test_unregister_unknown_chat_does_not_raise(self):
        registry = make_registry()
        registry.unregister(999)  # darf nicht raisen


class TestGetAndIsActive:
    def test_get_returns_none_for_unknown_chat(self):
        registry = make_registry()
        assert registry.get(123) is None

    def test_is_active_false_for_unknown_chat(self):
        registry = make_registry()
        assert registry.is_active(123) is False


class TestActiveDownloadCancelEvent:
    def test_cancel_event_starts_unset(self):
        entry = ActiveDownload(chat_id=1, url="u", download_type="single")
        assert entry.is_cancel_requested() is False

    def test_request_cancel_sets_event(self):
        entry = ActiveDownload(chat_id=1, url="u", download_type="single")
        entry.request_cancel()
        assert entry.is_cancel_requested() is True

    def test_cancel_event_is_thread_safe_signal(self):
        """Der eigentliche Anwendungsfall: request_cancel() aus einem
        Thread, is_cancel_requested() aus einem anderen (simuliert
        Event-Loop-Thread vs. yt-dlp-progress_hooks-Executor-Thread)."""
        entry = ActiveDownload(chat_id=1, url="u", download_type="single")
        observed = []

        def worker():
            entry.cancel_event.wait(timeout=2)
            observed.append(entry.is_cancel_requested())

        t = threading.Thread(target=worker)
        t.start()
        entry.request_cancel()
        t.join(timeout=2)

        assert observed == [True]

    def test_each_active_download_gets_its_own_tracker(self):
        """default_factory=ProgressTracker - jede Instanz braucht ihren
        eigenen Tracker, keinen geteilten Default-Zustand (klassischer
        Mutable-Default-Fallstrick, hier per field(default_factory=...)
        bereits korrekt vermieden - Regressionsanker)."""
        a = ActiveDownload(chat_id=1, url="u", download_type="single")
        b = ActiveDownload(chat_id=2, url="u", download_type="single")

        a.tracker.mark_completed("Track 1")

        assert a.tracker is not b.tracker
        assert b.tracker.completed_items == []
