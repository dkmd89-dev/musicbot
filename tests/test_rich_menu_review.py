# tests/test_rich_menu_review.py
# -*- coding: utf-8 -*-
"""
Library-Health-Review-Menüpunkt ("🔎 Library Health Review",
review:start/severity/category/edit/resolve/fp/skip/quit/batchconfirm/
batchyes) - Menü-/Callback-Dispatch-Logik in RichMenuSystem (Admin-Gating
+ Routing an den echten LibraryHealthReviewHandler).

Deckt NUR die Dispatch-/Gating-Ebene ab (RichMenuSystem) - die eigentliche
Handler-Logik hat eigene Tests in tests/test_library_health_review_handler.py.
Testmuster analog zu tests/test_rich_menu_doctor.py.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from handlers.library_health_review_handler import LibraryHealthReviewHandler
from handlers.menu.rich_menu_system import RichMenuSystem


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100
    DATA_DIR = "/tmp/does-not-matter-for-dispatch-tests"


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def review_handler():
    return LibraryHealthReviewHandler(FakeConfig(), logger_factory=lambda name: Mock())


@pytest.fixture
def menu_system(review_handler):
    system = RichMenuSystem(FakeConfig())
    system.initialize_menu_structure()
    system.set_review_handler(review_handler)
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
    context.user_data = {}
    return context


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


class TestMenuItemRegistration:
    def test_admin_library_health_review_is_child_of_library_group(self, menu_system):
        item = menu_system.menu_registry["admin_library_health_review"]
        library_group = menu_system.menu_registry["admin_group_library"]
        assert item in library_group.children
        assert item.callback_data == "review:start"


class TestReviewDispatchGating:
    def test_owner_can_open_review(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "review:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_admin_can_open_review(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "review:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    def test_non_admin_is_rejected(self, menu_system, mock_context):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "review:start"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()

    def test_non_admin_rejected_on_severity_callback(self, menu_system, mock_context):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "review:severity:WARNING"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    def test_non_admin_rejected_on_single_action_callback(self, menu_system, mock_context):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = "review:resolve:abcdef1234567890"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    def test_missing_review_handler_shows_not_available(self, mock_context):
        system = RichMenuSystem(FakeConfig())
        system.initialize_menu_structure()
        # bewusst KEIN set_review_handler() aufgerufen
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "review:start"
        run_async(system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⚠️ Review-Handler nicht verfügbar", show_alert=True
        )

    def test_unknown_review_subaction_answers_gracefully(self, menu_system, mock_context):
        update = _mock_update(OWNER_ID)
        update.callback_query.data = "review:totally_unknown_action:x"
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_any_call("⚠️ Unbekannter Review-Callback")


class TestAcceptedFindingsDispatch:
    @pytest.mark.parametrize("data", [
        "review:accepted",
        "review:acccode:ARTWORK_MISSING",
        "review:accshow:abcdef1234567890",
        "review:unaccept:abcdef1234567890",
    ])
    def test_admin_routes_to_handler(self, menu_system, mock_context, data):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.edit_message_text.assert_called()

    @pytest.mark.parametrize("data", [
        "review:accepted",
        "review:acccode:ARTWORK_MISSING",
        "review:accshow:abcdef1234567890",
        "review:unaccept:abcdef1234567890",
    ])
    def test_non_admin_rejected(self, menu_system, mock_context, data):
        update = _mock_update(OTHER_ID)
        update.callback_query.data = data
        run_async(menu_system.handle_callback(update, mock_context))
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()
