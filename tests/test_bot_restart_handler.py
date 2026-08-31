"""
Unit-Tests für BotRestartHandler (handlers/admin/bot_restart_handler.py)
— vorher 0 Tests, gefunden über die systematische Ungetestet-Prüfung.
Live/aktiv verdrahtet in RichMenuHandler.initialize().

POST-ARCH-009 P-1: die eigentliche systemctl-Prozesssteuerung
(_trigger_restart()) wurde nach utils/bot_restart_trigger.py ausgelagert
(siehe docs/archive/post-arch/MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md). Diese Datei
testet nur noch, DASS BotRestartHandler den Neustart korrekt an
BotRestartTrigger.trigger_restart() delegiert (via call_later); die
subprocess.run()-Charakterisierung selbst liegt jetzt in
tests/test_bot_restart_trigger.py.

Sicherheitscharakterisierung (kein Bug): cancel_restart() prueft _is_admin
selbst NICHT, im Gegensatz zu show_restart_confirm()/execute_restart().
Verifiziert als harmlos: _handle_restart_callback() in rich_menu_system.py
ist der EINZIGE Aufrufpfad fuer alle drei restart:*-Callbacks und macht
bereits VOR dem Dispatch eine eigene _is_admin_check()-Pruefung - cancel_
restart() kann nie ohne vorherige Admin-Pruefung erreicht werden.
"""

from unittest.mock import AsyncMock, Mock, patch
import asyncio

import pytest

from handlers.admin.bot_restart_handler import BotRestartHandler, _PRE_RESTART_DELAY
from utils.bot_restart_trigger import BotRestartTrigger


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]


@pytest.fixture
def handler():
    return BotRestartHandler(MockConfig(), logger_factory=lambda name: Mock())


def make_update(user_id: int):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestIsAdmin:
    def test_owner_is_admin(self, handler):
        assert handler._is_admin(MockConfig.OWNER_USER_ID) is True

    def test_configured_admin_is_admin(self, handler):
        assert handler._is_admin(67890) is True

    def test_unknown_user_is_not_admin(self, handler):
        assert handler._is_admin(999999) is False


class TestShowRestartConfirm:
    def test_admin_sees_confirmation_dialog_with_html(self, handler):
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        asyncio.run(handler.show_restart_confirm(update, context))

        update.callback_query.answer.assert_called_once()
        kwargs = update.callback_query.edit_message_text.call_args
        assert kwargs.kwargs["parse_mode"] == "HTML"
        assert "reply_markup" in kwargs.kwargs
        text = kwargs.args[0]
        assert "Bot neu starten" in text
        assert handler.service_name in text

    def test_non_admin_is_rejected_with_alert(self, handler):
        update = make_update(999999)
        context = make_context()

        asyncio.run(handler.show_restart_confirm(update, context))

        update.callback_query.answer.assert_called_once_with(
            "⛔ Keine Berechtigung", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()


class TestExecuteRestart:
    def test_admin_triggers_status_message_and_schedules_restart(self, handler):
        update = make_update(MockConfig.OWNER_USER_ID)
        context = make_context()

        fake_loop = Mock()
        with patch("asyncio.get_event_loop", return_value=fake_loop):
            asyncio.run(handler.execute_restart(update, context))

        update.callback_query.edit_message_text.assert_called_once()
        text, kwargs = (
            update.callback_query.edit_message_text.call_args.args[0],
            update.callback_query.edit_message_text.call_args.kwargs,
        )
        assert kwargs["parse_mode"] == "HTML"
        assert "neu gestartet" in text

        fake_loop.call_later.assert_called_once_with(
            _PRE_RESTART_DELAY,
            BotRestartTrigger.trigger_restart,
            handler.service_name,
        )

    def test_non_admin_is_rejected_and_restart_not_scheduled(self, handler):
        update = make_update(999999)
        context = make_context()

        fake_loop = Mock()
        with patch("asyncio.get_event_loop", return_value=fake_loop):
            asyncio.run(handler.execute_restart(update, context))

        update.callback_query.answer.assert_called_once_with(
            "⛔ Keine Berechtigung", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()
        fake_loop.call_later.assert_not_called()


class TestCancelRestart:
    def test_shows_cancelled_message_regardless_of_admin_status(self, handler):
        """
        Charakterisiert bewusst: cancel_restart() prueft _is_admin selbst
        nicht (siehe Modul-Docstring dieser Testdatei fuer die Begruendung,
        warum das ueber den Dispatcher in rich_menu_system.py trotzdem
        sicher ist).
        """
        update = make_update(999999)
        context = make_context()

        asyncio.run(handler.cancel_restart(update, context))

        update.callback_query.answer.assert_called_once_with("✅ Neustart abgebrochen")
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "abgebrochen" in text
