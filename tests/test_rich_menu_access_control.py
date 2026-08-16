"""
Regressionstest fuer eine kritische, in Phase 3 gefundene Sicherheitsluecke
(SEC-003, siehe docs/MusicBot_ENGINEERING_BASELINE.md):

RichMenuSystem.handle_callback() (handlers/menu/rich_menu_system.py)
dispatchte callback_data rein nach String-Praefix an die jeweiligen
Handler-Dispatcher (usermgmt_, backup_, logger_, dup:) - OHNE jede
Berechtigungspruefung. Telegram callback_data ist ein von jedem Client
frei sendbarer String, nicht an tatsaechlich gerenderte Buttons gebunden
(is_accessible() in render_menu() blendet Buttons nur aus, das ist reine
Client-Anzeige, keine Autorisierung). Jeder Nutzer, der den Bot anschreiben
kann, konnte sich z.B. per "usermgmt_set_role_<eigene_id>_owner" selbst
zum Owner machen (handlers/admin/user_management_handler.py's set_user_role()
hatte selbst ebenfalls keinerlei Admin-Check), oder Backups loeschen, das
globale Log-Level aendern (hebelt den SEC-001-Schutz aus) oder den
Duplicate-Cache leeren.

Fix: zentrale Admin-Pruefung in handle_callback() vor dem Praefix-Dispatch
fuer die vier betroffenen Praefixe (erradmin:/restart: hatten bereits eigene
Checks in ihren Dispatchern).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


NON_ADMIN_USER_ID = 99999
ADMIN_USER_ID = 67890


@pytest.fixture
def menu_system():
    system = RichMenuSystem(MockConfig())
    system.initialize_menu_structure()
    return system


def make_update(user_id: int, callback_data: str):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    return update


def make_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


ADMIN_ONLY_CALLBACKS = [
    "usermgmt_set_role_99999_owner",
    "usermgmt_list_0",
    "backup_delete_confirm_somefile",
    "backup_main",
    "logger_main_menu",
    "dup:clear_cache_execute",
]


class TestAdminOnlyCallbacksRejectNonAdmin:
    @pytest.mark.parametrize("callback_data", ADMIN_ONLY_CALLBACKS)
    def test_non_admin_is_rejected_with_permission_denied(
        self, menu_system, callback_data
    ):
        update = make_update(NON_ADMIN_USER_ID, callback_data)
        context = make_context()

        asyncio.run(menu_system.handle_callback(update, context))

        update.callback_query.answer.assert_called_once()
        _args, kwargs = update.callback_query.answer.call_args
        message = _args[0] if _args else kwargs.get("text", "")
        assert "Berechtigung" in message
        assert kwargs.get("show_alert") is True

    @pytest.mark.parametrize("callback_data", ADMIN_ONLY_CALLBACKS)
    def test_admin_is_not_rejected(self, menu_system, callback_data):
        update = make_update(ADMIN_USER_ID, callback_data)
        context = make_context()

        asyncio.run(menu_system.handle_callback(update, context))

        # Handler ist in diesem Test nicht angebunden (bleibt None), daher
        # kommt keine echte Aktion zustande - aber die Antwort darf NICHT
        # die Berechtigungs-Ablehnung sein, das beweist, dass der Admin die
        # zentrale Pruefung passiert hat.
        update.callback_query.answer.assert_called_once()
        _args, kwargs = update.callback_query.answer.call_args
        message = _args[0] if _args else kwargs.get("text", "")
        assert "Berechtigung" not in message


class TestSelfPromotionIsBlocked:
    """Der konkrete, urspruenglich gefundene Angriffspfad: ein Nicht-Admin
    versucht sich selbst zum Owner zu machen."""

    def test_set_user_role_is_never_called_for_non_admin(self, menu_system):
        from handlers.admin.user_management_handler import UserManagementHandler

        fake_user_mgmt_handler = Mock(spec=UserManagementHandler)
        fake_user_mgmt_handler.set_user_role = AsyncMock()
        menu_system.set_user_mgmt_handler(fake_user_mgmt_handler)

        update = make_update(
            NON_ADMIN_USER_ID,
            f"usermgmt_set_role_{NON_ADMIN_USER_ID}_owner",
        )
        context = make_context()

        asyncio.run(menu_system.handle_callback(update, context))

        fake_user_mgmt_handler.set_user_role.assert_not_called()


class TestNonAdminPrefixesAreNotAffected:
    """Sanity-Check: die neue zentrale Pruefung darf nur die vier
    tatsaechlich betroffenen Praefixe blockieren, nicht regulaere
    Menue-Navigation fuer normale Nutzer."""

    def test_regular_menu_navigation_is_not_blocked_for_non_admin(
        self, menu_system
    ):
        update = make_update(NON_ADMIN_USER_ID, "menu:main")
        context = make_context()

        asyncio.run(menu_system.handle_callback(update, context))

        assert update.callback_query.answer.call_count >= 1
        for call in update.callback_query.answer.call_args_list:
            args, kwargs = call
            message = args[0] if args else kwargs.get("text", "")
            assert "Berechtigung" not in message
