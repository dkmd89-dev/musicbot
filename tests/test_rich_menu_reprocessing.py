# tests/test_rich_menu_reprocessing.py
# -*- coding: utf-8 -*-
"""
Metadata-Reprocessing-Menüpunkt ("🔧 Reprocessing", reprocess:show/
reprocess:pick:<idx>/reprocess:live:<idx>) - Menü-/Callback-Dispatch-Logik
in RichMenuSystem (Owner-Gating + Routing an den echten
ReprocessingMenuHandler).

Deckt NUR die Dispatch-/Gating-Ebene ab (RichMenuSystem) - die eigentliche
Handler-Logik hat eigene Tests in tests/test_reprocessing_menu_handler.py,
die Subprozess-Orchestrierung eigene Tests in
tests/test_reprocessing_runner.py. Testmuster analog zu
tests/test_rich_menu_maintenance_mode.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.reprocessing_menu_handler import ReprocessingMenuHandler
from handlers.menu.rich_menu_system import RichMenuSystem


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def reprocessing_handler():
    return ReprocessingMenuHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(reprocessing_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_reprocessing_handler(reprocessing_handler)
    return system


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.edit_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    return asyncio.run(coro)


def last_text(update):
    return update.callback_query.edit_message_text.call_args.args[0]


class TestReprocessingShowOwnerGating:
    def test_owner_sees_artist_list(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "reprocess:show"

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha"],
        ):
            run_async(menu_system.handle_callback(update, mock_context))

        assert "Metadata-Reprocessing" in last_text(update)

    def test_admin_but_not_owner_is_rejected(self, menu_system, mock_context):
        """Nutzer-Entscheidung: nur Owner, nicht Owner+Admin - im
        Unterschied zum Wartungsmodus (dort maint: fuer Admins offen)."""
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "reprocess:show"

        run_async(menu_system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True
        update.callback_query.edit_message_text.assert_not_called()

    def test_other_user_is_rejected(self, menu_system, mock_context):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "reprocess:show"

        run_async(menu_system.handle_callback(update, mock_context))

        update.callback_query.edit_message_text.assert_not_called()


class TestReprocessingPickAndLiveRouting:
    def test_pick_routes_to_handler_with_parsed_index(
        self, menu_system, reprocessing_handler, mock_context
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "reprocess:pick:3"

        with patch.object(
            reprocessing_handler, "handle_pick", AsyncMock()
        ) as mocked_pick:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_pick.assert_awaited_once_with(update, mock_context, 3)

    def test_live_routes_to_handler_with_parsed_index(
        self, menu_system, reprocessing_handler, mock_context
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "reprocess:live:7"

        with patch.object(
            reprocessing_handler, "handle_live", AsyncMock()
        ) as mocked_live:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_live.assert_awaited_once_with(update, mock_context, 7)

    def test_pick_with_non_numeric_index_is_rejected_cleanly(
        self, menu_system, reprocessing_handler, mock_context
    ):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "reprocess:pick:not_a_number"

        with patch.object(
            reprocessing_handler, "handle_pick", AsyncMock()
        ) as mocked_pick:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_pick.assert_not_awaited()
        update.callback_query.answer.assert_awaited_once()

    def test_non_owner_pick_never_reaches_handler(
        self, menu_system, reprocessing_handler, mock_context
    ):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "reprocess:pick:0"

        with patch.object(
            reprocessing_handler, "handle_pick", AsyncMock()
        ) as mocked_pick:
            run_async(menu_system.handle_callback(update, mock_context))

        mocked_pick.assert_not_awaited()


class TestReprocessingHandlerNotAvailable:
    def test_show_without_reprocessing_handler_reports_unavailable(
        self, mock_context
    ):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        # set_reprocessing_handler() bewusst NICHT aufgerufen.
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "reprocess:show"

        run_async(system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once()
