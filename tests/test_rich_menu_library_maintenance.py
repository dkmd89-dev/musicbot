# tests/test_rich_menu_library_maintenance.py
# -*- coding: utf-8 -*-
"""
Library-Wartung-Menüpunkt ("🧹 Library-Wartung",
libmaint:start/artists/pick/action/confirm/execute) - Menü-/Callback-
Dispatch-Logik in RichMenuSystem (Admin-Gating + Routing an den echten
LibraryMaintenanceHandler, ARCH-032 Phase 4).

Deckt NUR die Dispatch-/Gating-Ebene ab - die eigentliche Handler-Logik
hat eigene Tests in tests/test_library_maintenance_handler.py. Testmuster
analog zu tests/test_rich_menu_repair.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.library_maintenance_handler import LibraryMaintenanceHandler
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
def maintenance_handler():
    return LibraryMaintenanceHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(maintenance_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_library_maintenance_handler(maintenance_handler)
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
    return asyncio.run(coro)


class TestMenuItemRegistration:
    def test_admin_library_maintenance_is_child_of_library_group(self, menu_system):
        item = menu_system.menu_registry["admin_library_maintenance"]
        library_group = menu_system.menu_registry["admin_group_library"]
        assert item in library_group.children
        assert item.callback_data == "libmaint:start"

    def test_does_not_collide_with_bot_maintenance_mode_prefix(self, menu_system):
        """libmaint: (Library-Wartung) und maint: (Bot-Wartungsmodus) sind
        bewusst unterschiedliche Praefixe - Kollisionsschutz."""
        item = menu_system.menu_registry["admin_library_maintenance"]
        assert not item.callback_data.startswith("maint:")
        assert item.callback_data.startswith("libmaint:")


class TestLibraryMaintenanceDispatchGating:
    @pytest.mark.parametrize(
        "callback_data",
        [
            "libmaint:start", "libmaint:artists", "libmaint:pick:0",
            "libmaint:action:artist-casing:0", "libmaint:confirm:artist-casing:0",
            "libmaint:execute:artist-casing:0",
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
        update.callback_query.data = "libmaint:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_admin_can_open_start(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "libmaint:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_missing_maintenance_handler_shows_not_available(self, mock_context):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:start"
        run_async(system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⚠️ Library-Wartung-Handler nicht verfügbar", show_alert=True
        )

    def test_unknown_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:totally_unknown"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Library-Wartung-Callback")

    def test_malformed_pick_index_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:pick:not-a-number"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Ungültiger Callback", show_alert=True)

    def test_unknown_action_in_preview_callback_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "libmaint:action:totally-unknown-action:0"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannte Aktion", show_alert=True)
