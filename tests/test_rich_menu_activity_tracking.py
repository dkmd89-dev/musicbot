"""
BotStatusTracker-Funktionslücke (docs/audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md):
Tests für den 7. Einstiegspunkt, RichMenuSystem.handle_callback(), der
jetzt record_activity() aufruft. Die 6 Einstiegspunkte auf RichMenuHandler
haben eigene Tests in tests/test_rich_menu_handler_activity_tracking.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem


@pytest.fixture
def config():
    class MockConfig:
        OWNER_USER_ID = 12345
        ADMIN_USER_IDS = [12345]
        SESSION_TIMEOUT = 300
        MAX_CONCURRENT_SESSIONS = 100

    return MockConfig()


@pytest.fixture
def menu_system(config):
    system = RichMenuSystem(config)
    system.initialize_menu_structure()
    system.status_handler = Mock()
    return system


def _mock_update(user_id, callback_data):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.data = callback_data
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    return asyncio.run(coro)


class TestHandleCallbackRecordsActivity:
    def test_records_activity_with_full_callback_data(self, menu_system, mock_context):
        update = _mock_update(999, "menu:download")

        run_async(menu_system.handle_callback(update, mock_context))

        menu_system.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            999, "callback:menu:download"
        )

    def test_records_activity_for_dl_prefix(self, menu_system, mock_context):
        update = _mock_update(999, "dl:new")

        run_async(menu_system.handle_callback(update, mock_context))

        menu_system.status_handler.bot_tracker.record_user_activity.assert_called_once_with(
            999, "callback:dl:new"
        )


class TestActivityNotRecordedWhenBlockedByMaintenance:
    def test_blocked_non_admin_does_not_record_activity(self, menu_system, mock_context):
        from services.bot_maintenance import MaintenanceModeStore

        menu_system.maintenance_store = Mock()
        menu_system.maintenance_store.is_active.return_value = True
        update = _mock_update(999, "menu:download")  # nicht Admin

        run_async(menu_system.handle_callback(update, mock_context))

        menu_system.status_handler.bot_tracker.record_user_activity.assert_not_called()


class TestMissingStatusHandlerDoesNotCrash:
    def test_handle_callback_without_status_handler(self, config, mock_context):
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        # status_handler bewusst NICHT gesetzt.
        update = _mock_update(999, "menu:download")

        # Darf nicht raisen.
        run_async(system.handle_callback(update, mock_context))
