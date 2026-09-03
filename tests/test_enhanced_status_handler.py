"""
Characterization-Tests fuer handlers/enhanced_status_handler.py
(EnhancedStatusHandler, 870 Zeilen, vorher 0 Tests).

Kein neuer Sicherheits-/Logikbug gefunden, aber ein systemisches
Unvollstaendigkeits-Muster: von 18 im Status-Menue (dieses File) als
Buttons gerenderten "status_*"-callback_data-Werten sind in
RichMenuSystem._handle_status_callback()s routing_map nur 7 tatsaechlich
verdrahtet:

  Verdrahtet:      status_menu, status_system, status_bot,
                    status_services, status_performance, status_storage,
                    status_refresh
  NICHT verdrahtet: status_bot_handlers, status_bot_logs,
                    status_performance_history, status_performance_reset,
                    status_services_check, status_services_detail,
                    status_storage_cleanup (siehe bereits TEST-011),
                    status_storage_detail, status_system_detail,
                    status_system_history, status_trends, status_users

Alle 11 nicht verdrahteten Buttons fallen auf den generischen
"Funktion nicht implementiert"-Zweig zurueck (kein Crash, keine
Sicherheitsauswirkung - reine unfertige Feature-Entwicklung). Bewusst
nur dokumentiert/charakterisiert statt hier 11 neue Handler-Methoden zu
implementieren (kein mechanischer Bugfix, sondern Funktionsumfang).
"""

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.enhanced_status_handler import BotStatusTracker, EnhancedStatusHandler, SystemMonitor


class FakeConfig:
    BASE_DIR = Path("/tmp")
    LIBRARY_DIR = Path("/tmp/nonexistent_library")
    DOWNLOAD_DIR = Path("/tmp/nonexistent_downloads")
    DATA_DIR = Path("/tmp/nonexistent_data")
    LOG_DIR = Path("/tmp/nonexistent_logs")


class TestSystemMonitor:
    def test_get_system_metrics_returns_expected_top_level_keys(self):
        monitor = SystemMonitor(FakeConfig())
        metrics = monitor.get_system_metrics()

        assert set(metrics.keys()) >= {"cpu", "memory", "disk", "network", "process"}

    def test_get_uptime_formats_correctly(self):
        monitor = SystemMonitor(FakeConfig())
        uptime = monitor.get_uptime()

        assert uptime["days"] == 0
        assert "formatted" in uptime
        assert uptime["total_seconds"] >= 0

    def test_record_operation_increments_counter(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_operation("download")
        monitor.record_operation("download")
        monitor.record_operation("search")

        stats = monitor.get_performance_stats()
        assert stats["operation_breakdown"]["download"] == 2
        assert stats["operation_breakdown"]["search"] == 1
        assert stats["total_operations"] == 3

    def test_record_error_increments_counter(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_error("timeout")

        stats = monitor.get_performance_stats()
        assert stats["total_errors"] == 1
        assert stats["error_rate"] == 100.0  # 1 error / 1 total_operations(0->max(0,1)=1)

    def test_reset_statistics_clears_counters(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_operation("download")
        monitor.record_error("timeout")

        monitor.reset_statistics()

        stats = monitor.get_performance_stats()
        assert stats["total_operations"] == 0
        assert stats["total_errors"] == 0


class TestBotStatusTracker:
    def test_update_handler_status_stores_status(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_handler_status("download_handler", "active")

        overview = tracker.get_handler_overview()
        assert overview["total_handlers"] == 1
        assert overview["active_handlers"] == 1
        assert overview["handlers"]["download_handler"]["status"] == "active"

    def test_update_service_status_only_for_known_services(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_service_status("navidrome", "healthy")
        tracker.update_service_status("totally_unknown_service", "healthy")

        overview = tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "healthy"
        assert "totally_unknown_service" not in overview["services"]
        assert overview["healthy_services"] == 1

    def test_record_user_activity_tracks_unique_active_users(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.record_user_activity(111, "download")
        tracker.record_user_activity(111, "search")
        tracker.record_user_activity(222, "download")

        activity = tracker.get_user_activity()
        assert activity["active_users"] == 2
        assert activity["total_recorded_activities"] == 3

    def test_user_activity_history_respects_recent_20_limit(self):
        tracker = BotStatusTracker(FakeConfig())
        for i in range(25):
            tracker.record_user_activity(i, "download")

        activity = tracker.get_user_activity()
        assert len(activity["recent_activities"]) == 20
        assert activity["total_recorded_activities"] == 25


class TestFormatBytes:
    def test_bytes_stay_as_bytes(self):
        handler = EnhancedStatusHandler(FakeConfig())
        assert handler.format_bytes(500) == "500.00 B"

    def test_megabytes_are_converted(self):
        handler = EnhancedStatusHandler(FakeConfig())
        result = handler.format_bytes(5 * 1024 * 1024)
        assert result.endswith("MB")


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestShowStorageStatus:
    def test_missing_directory_is_reported_not_found(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Nicht gefunden" in text

    def test_existing_directory_reports_size(self, tmp_path):
        class ConfigWithRealDir(FakeConfig):
            LIBRARY_DIR = tmp_path

        (tmp_path / "song.mp3").write_bytes(b"x" * 1024)

        handler = EnhancedStatusHandler(ConfigWithRealDir())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "GB" in text


class TestUnroutedStatusButtonsAreDocumented:
    """
    Statischer Abgleich: extrahiert alle in enhanced_status_handler.py
    gerenderten "status_*"-callback_data-Werte und vergleicht sie gegen
    die tatsaechlich in RichMenuSystem._handle_status_callback() verdrahtete
    Liste - schuetzt davor, dass sich die Diskrepanz unbemerkt vergroessert
    oder (bei zukuenftiger Verdrahtung) diese Charakterisierung veraltet,
    ohne dass es auffaellt.
    """

    ROUTED_STATUS_CALLBACKS = {
        "status_menu",
        "status_system",
        "status_bot",
        "status_services",
        "status_performance",
        "status_storage",
        "status_refresh",
    }

    def test_known_unrouted_buttons_are_still_unrouted(self):
        source = Path("handlers/menu/rich_menu_system.py").read_text(encoding="utf-8")
        # Groben Ausschnitt der routing_map in _handle_status_callback holen
        start = source.index("async def _handle_status_callback")
        end = source.index("async def _handle_backup_callback")
        section = source[start:end]

        rendered = set(
            re.findall(r'callback_data="(status_[a-z_]+)"',
                       Path("handlers/enhanced_status_handler.py").read_text(encoding="utf-8"))
        )
        routed = set(re.findall(r'"(status_[a-z_]+)":', section))

        assert routed == self.ROUTED_STATUS_CALLBACKS
        unrouted = rendered - routed
        # Mindestens diese bereits bekannten Buttons muessen weiterhin
        # unrouted sein - schlaegt fehl, sobald jemand sie verdrahtet,
        # als Erinnerung, diese Charakterisierung zu aktualisieren.
        assert {
            "status_storage_cleanup",
            "status_system_detail",
            "status_performance_reset",
        }.issubset(unrouted)
