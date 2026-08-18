"""
Characterization-Tests fuer handlers/menu/rich_menu_system.py
(RichMenuSystem) ueber den bereits in tests/test_rich_menu_access_control.py
(SEC-003) abgedeckten Ausschnitt hinaus - MenuItem/MenuSession-Datenklassen,
Access-Level-Ermittlung, Session-Verwaltung, Menü-Rendering.

Beim Lesen aufgefallene, nicht-kritische Befunde (charakterisiert, nicht
gefixt):

- _get_user_access_level() erkennt in der Cache-basierten Rollen-Pruefung
  nur "ADMIN"/"MODERATOR"/"USER", NICHT "OWNER". Ein per set_user_role()
  (seit SEC-005 nur vom echten Owner vergebbar) mit role="owner"
  markierter Nutzer, der NICHT zusaetzlich in Config.OWNER_USER_ID/
  ADMIN_USER_IDS steht, faellt auf AccessLevel.USER zurueck statt OWNER.
  Niedrige Prioritaet: AccessLevel/is_accessible() steuert laut dem
  SEC-003-Fund selbst nur, welche Buttons GERENDERT werden (reine
  Client-Anzeige) - die tatsaechliche Autorisierung in handle_callback()
  laeuft ueber das unabhaengige _is_admin_check() (Config.OWNER_USER_ID/
  ADMIN_USER_IDS), das von diesem Cache-Detail nicht betroffen ist.

- Der "🗑️ Cleanup"-Button in enhanced_status_handler.py sendet
  callback_data="status_storage_cleanup", aber _handle_status_callback()'s
  routing_map kennt diesen Callback nicht - er faellt auf den generischen
  "Funktion nicht implementiert"-Zweig. Der Button ist also aktuell ein
  Dead End (kein Sicherheitsproblem, im Gegenteil: die in der SEC-003-
  Doku erwaehnte "destruktive Cleanup-Aktion" ist dadurch faktisch inert).
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import (
    AccessLevel,
    MenuItem,
    MenuSession,
    MenuState,
    RichMenuSystem,
)


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


@pytest.fixture
def menu_system():
    system = RichMenuSystem(MockConfig())
    system.initialize_menu_structure()
    return system


def make_update(user_id: int):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.delete = AsyncMock()
    return update


def make_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


class TestMenuItem:
    def test_callback_data_auto_generated_from_id(self):
        item = MenuItem(id="foo", title="Foo")
        assert item.callback_data == "menu:foo"

    def test_explicit_callback_data_not_overwritten(self):
        item = MenuItem(id="foo", title="Foo", callback_data="custom_cb")
        assert item.callback_data == "custom_cb"

    def test_is_accessible_allows_equal_or_higher_level(self):
        item = MenuItem(id="x", title="X", access_level=AccessLevel.ADMIN)
        assert item.is_accessible(AccessLevel.ADMIN) is True
        assert item.is_accessible(AccessLevel.OWNER) is True

    def test_is_accessible_denies_lower_level(self):
        item = MenuItem(id="x", title="X", access_level=AccessLevel.ADMIN)
        assert item.is_accessible(AccessLevel.USER) is False

    def test_add_child_sets_parent_link(self):
        parent = MenuItem(id="parent", title="Parent")
        child = MenuItem(id="child", title="Child")
        parent.add_child(child)
        assert child.parent is parent
        assert child in parent.children

    def test_get_breadcrumb_follows_parent_chain(self):
        root = MenuItem(id="root", title="Root")
        mid = MenuItem(id="mid", title="Mid")
        leaf = MenuItem(id="leaf", title="Leaf")
        root.add_child(mid)
        mid.add_child(leaf)

        assert leaf.get_breadcrumb() == ["Root", "Mid", "Leaf"]

    def test_has_children_reflects_child_list(self):
        item = MenuItem(id="x", title="X")
        assert item.has_children() is False
        item.add_child(MenuItem(id="y", title="Y"))
        assert item.has_children() is True


class TestMenuSession:
    def test_not_expired_within_timeout(self):
        session = MenuSession(user_id=1)
        assert session.is_expired(timeout=300) is False

    def test_expired_after_timeout(self):
        session = MenuSession(user_id=1)
        session.last_activity = datetime.now() - timedelta(seconds=400)
        assert session.is_expired(timeout=300) is True

    def test_navigate_to_pushes_current_menu_to_history(self):
        session = MenuSession(user_id=1)
        first = MenuItem(id="first", title="First")
        second = MenuItem(id="second", title="Second")

        session.navigate_to(first)
        session.navigate_to(second)

        assert session.current_menu is second
        assert session.history == ["first"]

    def test_go_back_pops_history(self):
        session = MenuSession(user_id=1)
        session.navigate_to(MenuItem(id="a", title="A"))
        session.navigate_to(MenuItem(id="b", title="B"))

        assert session.go_back() == "a"
        assert session.go_back() is None

    def test_update_activity_refreshes_timestamp(self):
        session = MenuSession(user_id=1)
        session.last_activity = datetime.now() - timedelta(seconds=100)
        session.update_activity()
        assert session.is_expired(timeout=300) is False


class TestGetUserAccessLevel:
    def test_owner_from_config_gets_owner_level(self, menu_system):
        assert (
            menu_system._get_user_access_level(MockConfig.OWNER_USER_ID)
            == AccessLevel.OWNER
        )

    def test_admin_from_config_gets_admin_level(self, menu_system):
        assert menu_system._get_user_access_level(67890) == AccessLevel.ADMIN

    def test_unknown_user_gets_user_level(self, menu_system):
        assert menu_system._get_user_access_level(99999) == AccessLevel.USER

    def test_role_from_user_mgmt_cache_is_used_when_available(self, menu_system):
        fake_user_mgmt = Mock()
        fake_user_mgmt.user_data_cache = {"55555": {"role": "moderator"}}
        menu_system.set_user_mgmt_handler(fake_user_mgmt)

        assert menu_system._get_user_access_level(55555) == AccessLevel.MODERATOR

    def test_data_role_owner_is_not_recognized_as_owner_level(self, menu_system):
        """
        Charakterisiert eine bestehende Inkonsistenz: role="owner" im
        UserManagement-Cache wird NICHT als AccessLevel.OWNER erkannt
        (nur ADMIN/MODERATOR/USER werden geprueft) - faellt auf USER
        zurueck, wenn die User-ID nicht zusaetzlich in
        Config.OWNER_USER_ID/ADMIN_USER_IDS steht. Niedrige Prioritaet,
        da AccessLevel nur Button-Rendering steuert, siehe Modul-Docstring.
        """
        fake_user_mgmt = Mock()
        fake_user_mgmt.user_data_cache = {"55555": {"role": "owner"}}
        menu_system.set_user_mgmt_handler(fake_user_mgmt)

        assert menu_system._get_user_access_level(55555) == AccessLevel.USER


class TestGetSession:
    def test_creates_new_session_for_unknown_user(self, menu_system):
        session = menu_system.get_session(42)
        assert session.user_id == 42
        assert 42 in menu_system.sessions

    def test_returns_same_session_on_repeated_calls(self, menu_system):
        session1 = menu_system.get_session(42)
        session2 = menu_system.get_session(42)
        assert session1 is session2

    def test_expired_session_is_replaced_with_fresh_one(self, menu_system):
        session1 = menu_system.get_session(42)
        session1.navigate_to(MenuItem(id="somewhere", title="Somewhere"))
        session1.last_activity = datetime.now() - timedelta(seconds=999)

        session2 = menu_system.get_session(42)

        assert session2 is not session1
        assert session2.current_menu is None

    def test_get_session_updates_activity_timestamp(self, menu_system):
        session = menu_system.get_session(42)
        session.last_activity = datetime.now() - timedelta(seconds=100)
        menu_system.get_session(42)
        assert session.is_expired(timeout=300) is False


class TestCleanupExpiredSessions:
    def test_removes_only_expired_sessions(self, menu_system):
        fresh = menu_system.get_session(1)
        expired = menu_system.get_session(2)
        expired.last_activity = datetime.now() - timedelta(seconds=999)

        removed_count = menu_system.cleanup_expired_sessions()

        assert removed_count == 1
        assert 1 in menu_system.sessions
        assert 2 not in menu_system.sessions


class TestRenderMenu:
    def test_only_accessible_items_are_rendered(self, menu_system):
        parent = MenuItem(id="parent", title="Parent")
        visible = MenuItem(id="visible", title="Visible", access_level=AccessLevel.USER)
        hidden = MenuItem(id="hidden", title="Hidden", access_level=AccessLevel.ADMIN)
        parent.add_child(visible)
        parent.add_child(hidden)

        markup = menu_system.render_menu(parent, user_level=AccessLevel.USER)
        all_callback_data = [
            btn.callback_data for row in markup.inline_keyboard for btn in row
        ]

        assert "menu:visible" in all_callback_data
        assert "menu:hidden" not in all_callback_data

    def test_inactive_items_are_not_rendered(self, menu_system):
        parent = MenuItem(id="parent", title="Parent")
        active = MenuItem(id="active", title="Active")
        inactive = MenuItem(id="inactive", title="Inactive", is_active=False)
        parent.add_child(active)
        parent.add_child(inactive)

        markup = menu_system.render_menu(parent, user_level=AccessLevel.OWNER)
        all_callback_data = [
            btn.callback_data for row in markup.inline_keyboard for btn in row
        ]

        assert "menu:active" in all_callback_data
        assert "menu:inactive" not in all_callback_data

    def test_root_menu_gets_close_button_not_back(self, menu_system):
        root = MenuItem(id="main", title="Main")
        markup = menu_system.render_menu(root, user_level=AccessLevel.USER)
        all_callback_data = [
            btn.callback_data for row in markup.inline_keyboard for btn in row
        ]
        assert "menu:close" in all_callback_data
        assert "menu:back" not in all_callback_data

    def test_submenu_gets_back_and_home_buttons(self, menu_system):
        root = MenuItem(id="main", title="Main")
        sub = MenuItem(id="sub", title="Sub")
        root.add_child(sub)

        markup = menu_system.render_menu(sub, user_level=AccessLevel.USER)
        all_callback_data = [
            btn.callback_data for row in markup.inline_keyboard for btn in row
        ]
        assert "menu:back" in all_callback_data
        assert "menu:main" in all_callback_data


class TestBackAndClose:
    def test_close_removes_session_and_deletes_message(self, menu_system):
        menu_system.get_session(42)
        update = make_update(42)
        context = make_context()

        asyncio.run(menu_system._handle_close(update, context))

        assert 42 not in menu_system.sessions
        update.callback_query.message.delete.assert_called_once()

    def test_back_without_history_goes_to_main(self, menu_system):
        update = make_update(42)
        context = make_context()

        asyncio.run(menu_system._handle_back(update, context))

        # show_menu() ruft edit_message_text auf - kein Crash bedeutet
        # main wurde als Fallback gefunden und gerendert.
        update.callback_query.edit_message_text.assert_called()


class TestStatusStorageCleanupIsUnrouted:
    """Dokumentiert den in enhanced_status_handler.py gerenderten, aber in
    _handle_status_callback() nicht gemappten Cleanup-Button."""

    def test_status_storage_cleanup_falls_through_to_not_implemented(
        self, menu_system
    ):
        fake_status_handler = Mock()
        fake_status_handler.show_storage_status = AsyncMock()
        menu_system.set_status_handler(fake_status_handler)

        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        asyncio.run(
            menu_system._handle_status_callback(
                update, context, "status_storage_cleanup"
            )
        )

        message = update.callback_query.answer.call_args[0][0]
        assert "nicht implementiert" in message
        fake_status_handler.show_storage_status.assert_not_called()


class TestAddChildMenuItem:
    """
    Tests fuer add_child_menu_item() (ARCH-001-Folge-Fix): ersetzt den
    direkten Zugriff auf menu_registry, den RichMenuHandler._register_
    system_handlers() vorher fuer den dynamisch angehaengten
    "Navidrome Scan"-Menuepunkt genutzt hat.
    """

    def test_item_becomes_child_of_parent_and_is_registered(self, menu_system):
        new_item = MenuItem(
            id="admin_navidrome",
            title="Navidrome Scan",
            emoji="🔄",
            access_level=AccessLevel.ADMIN,
        )

        result = menu_system.add_child_menu_item("admin", new_item)

        assert result is True
        assert menu_system.menu_registry["admin_navidrome"] is new_item
        admin_menu = menu_system.menu_registry["admin"]
        assert new_item in admin_menu.children
        assert new_item.parent is admin_menu

    def test_unknown_parent_id_returns_false_and_does_not_register(self, menu_system):
        new_item = MenuItem(id="orphan", title="Orphan")

        result = menu_system.add_child_menu_item("does_not_exist", new_item)

        assert result is False
        assert "orphan" not in menu_system.menu_registry
