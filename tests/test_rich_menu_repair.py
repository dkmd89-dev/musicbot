# tests/test_rich_menu_repair.py
# -*- coding: utf-8 -*-
"""
Repair-MusicBot-Menüpunkt ("🛠️ Repair MusicBot", repair:start/analyze/
proposals/preview/confirm/execute/history/stats) - Menü-/Callback-
Dispatch-Logik in RichMenuSystem (Admin-Gating + Routing an den echten
RepairMusicBotHandler).

Deckt NUR die Dispatch-/Gating-Ebene ab - die eigentliche Handler-Logik
hat eigene Tests in tests/test_repair_musicbot_handler.py. Testmuster
analog zu tests/test_rich_menu_review.py.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem
from handlers.repair_musicbot_handler import RepairMusicBotHandler


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def repair_handler():
    return RepairMusicBotHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(repair_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_repair_handler(repair_handler)
    return system


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.data = None
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


class TestMenuItemRegistration:
    def test_admin_repair_musicbot_is_child_of_library_group(self, menu_system):
        item = menu_system.menu_registry["admin_repair_musicbot"]
        library_group = menu_system.menu_registry["admin_group_library"]
        assert item in library_group.children
        assert item.callback_data == "repair:start"


class TestRepairDispatchGating:
    @pytest.mark.parametrize(
        "callback_data",
        [
            "repair:start", "repair:analyze", "repair:proposals", "repair:preview",
            "repair:confirm", "repair:execute", "repair:history", "repair:stats",
        ],
    )
    def test_non_admin_rejected_on_every_subaction(
        self, menu_system, mock_context, callback_data
    ):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = callback_data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    def test_owner_can_open_start(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "repair:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_admin_can_open_start(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "repair:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_missing_repair_handler_shows_not_available(self, mock_context):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "repair:start"
        run_async(system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⚠️ Repair-Handler nicht verfügbar", show_alert=True
        )

    def test_unknown_repair_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "repair:totally_unknown"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Repair-Callback")
