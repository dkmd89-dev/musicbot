"""
Bot-Wartungsmodus (docs/MusicBot_TELEGRAM_MENU_SYSTEM.md, Ein-/Ausschalten
über Telegram-Inline-Buttons) - end-to-end über die 6 Einstiegspunkte auf
RichMenuHandler (handle_start_command/handle_menu_command/handle_help/
handle_help_callback/handle_url_message/handle_text_message).

Der 7. Einstiegspunkt (RichMenuSystem.handle_callback(), deckt ~9
Callback-Präfixe zentral ab) hat eigene Tests in
tests/test_rich_menu_maintenance_mode.py.

Nutzt dieselbe _make_handler(tmp_path)-Konstruktion wie
tests/test_rich_menu_handler.py (echter RichMenuHandler, Path()-Patching
für data/user_data.json + data/maintenance_mode.json) - der Gate-Check
selbst hat eigene, isolierte Tests in tests/test_maintenance_gate.py.
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
    return handler


def run_async(coro):
    return asyncio.run(coro)


def _mock_update(user_id, *, text="/start", as_callback=False):
    """as_callback=False (Standard): Command-/Text-Nachricht - message
    gesetzt, callback_query bewusst None (sonst nimmt is_blocked_by_
    maintenance() faelschlich den callback_query-Zweig, siehe deren
    if/elif). as_callback=True: umgekehrt fuer handle_help_callback()."""
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


NON_ADMIN_ID = 999
ADMIN_ID = 12345


class TestEachEntryPointRespectsMaintenanceMode:
    """Fuer jeden der 6 Einstiegspunkte: bei aktivem Wartungsmodus und
    Nicht-Admin muss die Wartungsmeldung erscheinen UND die eigentliche
    Handler-Logik darf NICHT laufen (verifiziert per Ausbleiben ihres
    ueblichen Nebeneffekts/Log-Aufrufs, wo sinnvoll messbar)."""

    def test_handle_start_command_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID)

        run_async(handler.handle_start_command(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" in update.message.reply_text.call_args.args[0]

    def test_handle_menu_command_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID)

        run_async(handler.handle_menu_command(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        handler.menu_system.show_menu.assert_not_called()

    def test_handle_help_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID)

        run_async(handler.handle_help(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" in update.message.reply_text.call_args.args[0]

    def test_handle_help_callback_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID, as_callback=True)

        run_async(handler.handle_help_callback(update, Mock()))

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True

    def test_handle_url_message_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID, text="https://youtu.be/abc123")

        run_async(handler.handle_url_message(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" in update.message.reply_text.call_args.args[0]

    def test_handle_text_message_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(NON_ADMIN_ID, text="Hallo Bot")

        run_async(handler.handle_text_message(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" in update.message.reply_text.call_args.args[0]


class TestAdminBypassesMaintenanceMode:
    def test_admin_start_command_not_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(ADMIN_ID)

        run_async(handler.handle_start_command(update, Mock()))

        # Wurde NICHT mit der Wartungsmeldung beantwortet - die reale
        # Start-Begruessung (laenger, mit Keyboard) lief stattdessen durch.
        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" not in update.message.reply_text.call_args.args[0]

    def test_admin_menu_command_not_blocked(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.maintenance_store.set_active(True, changed_by_user_id=ADMIN_ID)
        update = _mock_update(ADMIN_ID)
        handler.menu_system.show_menu = AsyncMock()

        run_async(handler.handle_menu_command(update, Mock()))

        handler.menu_system.show_menu.assert_awaited_once()


class TestMaintenanceInactiveDoesNotBlockAnyone:
    def test_non_admin_start_command_works_normally_when_inactive(self, tmp_path):
        handler = _make_handler(tmp_path)
        # set_active() bewusst NICHT aufgerufen - Default ist inaktiv.
        update = _mock_update(NON_ADMIN_ID)

        run_async(handler.handle_start_command(update, Mock()))

        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" not in update.message.reply_text.call_args.args[0]
