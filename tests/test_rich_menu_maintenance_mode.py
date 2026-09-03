"""
Bot-Wartungsmodus (docs/MusicBot_TELEGRAM_MENU_SYSTEM.md, Ein-/Ausschalten
über Telegram-Inline-Buttons) - Menü-/Callback-Dispatch-Logik in
RichMenuSystem ("🛠️ Wartungsmodus", maint:show/maint:toggle).

Deckt NUR die Menü-/Callback-Dispatch-Logik ab (RichMenuSystem, reine
Telegram-Formatierung/-Routing + Admin-Gating) - der zugrundeliegende
MaintenanceModeStore hat eigene, isolierte Tests in
tests/test_bot_maintenance_store.py, der gemeinsame Gate-Check eigene
Tests in tests/test_maintenance_gate.py.

Testmuster analog zu tests/test_rich_menu_download_control_center.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem
from services.bot_maintenance import MaintenanceModeStore


@pytest.fixture
def config():
    class MockConfig:
        OWNER_USER_ID = 12345
        ADMIN_USER_IDS = [12345]
        SESSION_TIMEOUT = 300
        MAX_CONCURRENT_SESSIONS = 100

    return MockConfig()


@pytest.fixture
def maintenance_store(tmp_path):
    return MaintenanceModeStore(state_file=str(tmp_path / "maintenance_mode.json"))


@pytest.fixture
def menu_system(config, maintenance_store):
    system = RichMenuSystem(config)
    system.initialize_menu_structure()
    system.set_maintenance_store(maintenance_store)
    return system


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
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


def last_keyboard_texts(update):
    markup = update.callback_query.edit_message_text.call_args.kwargs.get(
        "reply_markup"
    )
    if markup is None:
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


ADMIN_ID = 12345
NON_ADMIN_ID = 999


class TestMaintenanceShowAdminGating:
    def test_admin_sees_status(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:show"

        run_async(menu_system.handle_callback(update, mock_context))

        assert "Wartungsmodus" in last_text(update)

    def test_non_admin_is_rejected_without_seeing_status(
        self, menu_system, mock_context
    ):
        update = _mock_update(NON_ADMIN_ID)
        update.callback_query.data = "maint:show"

        run_async(menu_system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True
        update.callback_query.edit_message_text.assert_not_called()


class TestMaintenanceShowInitialState:
    def test_inactive_by_default_shows_activate_button(
        self, menu_system, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:show"

        run_async(menu_system.handle_callback(update, mock_context))

        assert "Inaktiv" in last_text(update)
        assert any(
            "aktivieren" in t for t in last_keyboard_texts(update)
        )


class TestMaintenanceToggle:
    def test_toggle_activates_and_persists(
        self, menu_system, maintenance_store, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:toggle"

        run_async(menu_system.handle_callback(update, mock_context))

        assert maintenance_store.is_active() is True
        assert "AKTIV" in last_text(update)
        assert any("beenden" in t for t in last_keyboard_texts(update))

    def test_toggle_twice_deactivates_again(
        self, menu_system, maintenance_store, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:toggle"

        run_async(menu_system.handle_callback(update, mock_context))
        run_async(menu_system.handle_callback(update, mock_context))

        assert maintenance_store.is_active() is False
        assert "Inaktiv" in last_text(update)

    def test_toggle_records_who_changed_it(
        self, menu_system, maintenance_store, mock_context
    ):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:toggle"

        run_async(menu_system.handle_callback(update, mock_context))

        assert maintenance_store.get_state().changed_by_user_id == ADMIN_ID

    def test_non_admin_cannot_toggle(self, menu_system, maintenance_store, mock_context):
        update = _mock_update(NON_ADMIN_ID)
        update.callback_query.data = "maint:toggle"

        run_async(menu_system.handle_callback(update, mock_context))

        assert maintenance_store.is_active() is False
        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True


class TestMaintenanceNoStoreConfigured:
    def test_show_via_callback_dispatcher_without_store_does_not_crash(
        self, config, mock_context
    ):
        """Pfad ueber handle_callback() (z.B. "Zurueck"-Navigation) - der
        "kein Store"-Check in _handle_maintenance_callback() greift hier
        VOR der show/toggle-Unterscheidung, meldet also ueber query.answer()
        statt edit_message_text()."""
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        # set_maintenance_store() bewusst NICHT aufgerufen.
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:show"

        run_async(system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once()
        assert "nicht verfügbar" in update.callback_query.answer.call_args.args[0]
        update.callback_query.edit_message_text.assert_not_called()

    def test_show_via_direct_menu_item_handler_without_store_does_not_crash(
        self, config, mock_context
    ):
        """Pfad ueber den MenuItem-Handler direkt (echter Menue-Klick auf
        "🛠️ Wartungsmodus") - hier greift _handle_maintenance_show()s
        eigener "kein Store"-Check, meldet ueber edit_message_text()."""
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        update = _mock_update(ADMIN_ID)

        run_async(system._handle_maintenance_show(update, mock_context))

        assert "nicht verfügbar" in last_text(update)

    def test_toggle_without_store_does_not_crash(self, config, mock_context):
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "maint:toggle"

        run_async(system.handle_callback(update, mock_context))

        update.callback_query.answer.assert_awaited_once()
        assert "nicht verfügbar" in update.callback_query.answer.call_args.args[0]


class TestMaintenanceMenuItemRegistered:
    def test_admin_menu_lists_maintenance_item(self, menu_system, mock_context):
        update = _mock_update(ADMIN_ID)
        update.callback_query.data = "menu:admin"

        run_async(menu_system.handle_callback(update, mock_context))

        assert any("Wartungsmodus" in t for t in last_keyboard_texts(update))
