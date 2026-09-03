"""
BotStatusTracker-Funktionslücke (docs/audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md):
end-to-end über die 6 Einstiegspunkte auf RichMenuHandler, die jetzt
record_activity() aufrufen. Der 7. Einstiegspunkt
(RichMenuSystem.handle_callback()) hat eigene Tests in
tests/test_rich_menu_activity_tracking.py.

Nutzt dieselbe _make_handler(tmp_path)-Konstruktion wie
tests/test_rich_menu_handler_maintenance_gate.py.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.rich_menu_handler import RichMenuHandler


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


def _make_handler(tmp_path):
    user_data_file = tmp_path / "user_data.json"
    maintenance_state_file = tmp_path / "maintenance_mode.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        if p == "data/maintenance_mode.json":
            return maintenance_state_file
        return Path(p, *args, **kwargs)

    config = MockConfig()
    config.DOWNLOAD_HISTORY_DIR = tmp_path / "download_history"
    with patch("handlers.menu.rich_menu_handler.Path", side_effect=_fake_path):
        handler = RichMenuHandler(config)
    handler.menu_system = Mock()
    handler.status_handler = Mock()
    return handler


def run_async(coro):
    return asyncio.run(coro)


def _mock_update(user_id, *, text="/start", as_callback=False):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    if as_callback:
        update.message = None
        update.callback_query = Mock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = "help:main"
    else:
        update.callback_query = None
        update.message = Mock()
        update.message.text = text
        update.message.reply_text = AsyncMock()
    return update


USER_ID = 555


class TestEachEntryPointRecordsActivity:
    def test_handle_start_command_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        update = _mock_update(USER_ID)

        run_async(handler.handle_start_command(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "command:start"
        )

    def test_handle_menu_command_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.menu_system.show_menu = AsyncMock()
        update = _mock_update(USER_ID)

        run_async(handler.handle_menu_command(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "command:menu"
        )

    def test_handle_help_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        update = _mock_update(USER_ID)

        run_async(handler.handle_help(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "command:help"
        )

    def test_handle_help_callback_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        update = _mock_update(USER_ID, as_callback=True)

        run_async(handler.handle_help_callback(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "callback:help"
        )

    def test_handle_url_message_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        update = _mock_update(USER_ID, text="https://youtu.be/abc123")

        run_async(handler.handle_url_message(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "message:url"
        )

    def test_handle_text_message_records_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        update = _mock_update(USER_ID, text="Hallo Bot")

        run_async(handler.handle_text_message(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            USER_ID, "message:text"
        )


class TestActivityNotRecordedWhenBlockedByMaintenance:
    def test_blocked_non_admin_does_not_record_activity(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=12345)
        update = _mock_update(999)  # nicht in ADMIN_USER_IDS

        run_async(handler.handle_start_command(update, Mock()))

        handler.status_handler.bot_tracker.record_user_activity.assert_not_called()


class TestMissingStatusHandlerDoesNotCrash:
    def test_start_command_without_status_handler(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.status_handler = None
        update = _mock_update(USER_ID)

        # Darf nicht raisen.
        run_async(handler.handle_start_command(update, Mock()))


class TestRecordInitialHandlerStatuses:
    """Isolierter Test fuer _record_initial_handler_statuses() -
    initialize() selbst konstruiert viele echte Handler-Instanzen und
    ist daher nicht end-to-end unit-testbar; diese Methode wurde bewusst
    dafuer aus initialize() herausgezogen (siehe deren Docstring)."""

    def test_marks_present_handlers_active_and_missing_as_error(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.test_handler = Mock()
        handler.logger_handler = None  # simuliert fehlgeschlagene Konstruktion
        handler.stats_handler = Mock()
        handler.navidrome_handler = Mock()
        handler.user_mgmt_handler = Mock()
        handler.duplicate_handler = Mock()
        handler.backup_handler = Mock()
        handler.restart_handler = None  # simuliert fehlgeschlagene Konstruktion
        handler.metadata_processor = Mock()
        handler.reprocessing_handler = Mock()

        handler._record_initial_handler_statuses()

        calls = {
            c.args[0]: c.args[1]
            for c in handler.status_handler.bot_tracker.update_handler_status.call_args_list
        }
        assert calls["error_handler"] == "active"
        assert calls["logger_handler"] == "error"
        assert calls["restart_handler"] == "error"
        assert calls["metadata_processor"] == "active"
        assert calls["reprocessing_handler"] == "active"
        assert len(calls) == 11

    def test_missing_status_handler_is_noop(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.status_handler = None

        # Darf nicht raisen.
        handler._record_initial_handler_statuses()
