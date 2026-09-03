"""
Bot-Wartungsmodus (docs/MusicBot_TELEGRAM_MENU_SYSTEM.md, Ein-/Ausschalten
über Telegram-Inline-Buttons): Tests für den gemeinsamen Gate-Check
handlers/menu/maintenance_gate.py::is_blocked_by_maintenance(), isoliert
von RichMenuHandler/RichMenuSystem.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.maintenance_gate import is_blocked_by_maintenance


def run_async(coro):
    return asyncio.run(coro)


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [111, 222]


def make_update(user_id, *, as_callback=False):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    if as_callback:
        update.message = None
        update.callback_query = Mock()
        update.callback_query.answer = AsyncMock()
    else:
        update.callback_query = None
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def maintenance_store():
    store = Mock()
    store.is_active = Mock(return_value=True)
    return store


class TestMaintenanceInactive:
    def test_never_blocks_when_inactive(self, maintenance_store):
        maintenance_store.is_active.return_value = False
        update = make_update(999, as_callback=False)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=maintenance_store,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is False
        update.message.reply_text.assert_not_called()


class TestMaintenanceActiveNonAdmin:
    def test_blocks_non_admin_text_message(self, maintenance_store):
        update = make_update(999, as_callback=False)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=maintenance_store,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is True
        update.message.reply_text.assert_awaited_once()
        assert "Wartungsmodus" in update.message.reply_text.call_args.args[0]

    def test_blocks_non_admin_callback_query(self, maintenance_store):
        update = make_update(999, as_callback=True)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=maintenance_store,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is True
        update.callback_query.answer.assert_awaited_once()
        kwargs = update.callback_query.answer.call_args.kwargs
        assert kwargs.get("show_alert") is True


class TestMaintenanceActiveAdminBypass:
    def test_owner_is_never_blocked(self, maintenance_store):
        update = make_update(111, as_callback=False)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=maintenance_store,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is False
        update.message.reply_text.assert_not_called()

    def test_admin_is_never_blocked(self, maintenance_store):
        update = make_update(222, as_callback=False)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=maintenance_store,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is False


class TestMissingStore:
    def test_no_store_never_blocks(self):
        """Bestehende Tests bypassen __init__() (object.__new__(), etabliertes
        Muster dieser Session) und setzen maintenance_store nie - No-op statt
        AttributeError."""
        update = make_update(999, as_callback=False)

        blocked = run_async(
            is_blocked_by_maintenance(
                update,
                Mock(),
                maintenance_store=None,
                config=FakeConfig(),
                logger=Mock(),
            )
        )

        assert blocked is False
        update.message.reply_text.assert_not_called()
