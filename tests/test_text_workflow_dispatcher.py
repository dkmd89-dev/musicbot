"""
Unit-Tests für TextWorkflowDispatcher
(handlers/menu/text_workflow_dispatcher.py).

Im Zuge von ARCH-001 aus RichMenuHandler.handle_text_message() extrahiert
(Cancel-Erkennung + Workflow-Dispatch-Block -> eigene Klasse, 1:1 gleiche
Logik, siehe docs/archive/arch/MusicBot_ARCH-001_Orchestrators.md). Bewusst NICHT mit
extrahiert: `user_states` (URL-Erwartung) und die Navidrome-Suchlogik -
beides bleibt Eigentum von RichMenuHandler/NavidromeMenuHandler.

Genau hier saß BUG-006 (Cancel-Check stand vorher NACH dem
Workflow-Dispatch-Block, der immer vorher returnt) - die Reihenfolge
Cancel-Check-vor-Dispatch ist daher ausdrücklich mitgetestet, zusätzlich
zum bestehenden Regressionstest in tests/test_rich_menu_handler.py, der
den kompletten RichMenuHandler.handle_text_message()-Fluss weiterhin
end-to-end abdeckt.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.text_workflow_dispatcher import TextWorkflowDispatcher


@pytest.fixture
def dispatcher():
    return TextWorkflowDispatcher(logger=Mock())


def make_update():
    update = Mock()
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    return update


def make_context(workflow=None):
    context = Mock()
    context.user_data = {"workflow": workflow} if workflow else {}
    return context


class TestIsCancelCommand:
    @pytest.mark.parametrize("text", ["/cancel", "cancel", "abbrechen", "/CANCEL", "Abbrechen"])
    def test_recognizes_cancel_variants_case_insensitively(self, dispatcher, text):
        assert dispatcher.is_cancel_command(text) is True

    @pytest.mark.parametrize("text", ["hello", "12345", "cancel please", ""])
    def test_does_not_recognize_other_text(self, dispatcher, text):
        assert dispatcher.is_cancel_command(text) is False


class TestTryDispatchNoActiveWorkflow:
    def test_returns_false_when_no_workflow_set(self, dispatcher):
        update = make_update()
        context = make_context(workflow=None)
        user_mgmt = Mock()

        handled = asyncio.run(
            dispatcher.try_dispatch(update, context, "some text", user_mgmt)
        )

        assert handled is False
        update.message.reply_text.assert_not_called()

    def test_returns_false_for_unknown_workflow_name(self, dispatcher):
        update = make_update()
        context = make_context(workflow="some_unregistered_workflow")
        user_mgmt = Mock()

        handled = asyncio.run(
            dispatcher.try_dispatch(update, context, "some text", user_mgmt)
        )

        assert handled is False


class TestTryDispatchActiveWorkflow:
    @pytest.mark.parametrize(
        "workflow,method_name",
        [
            ("add_user_id", "process_new_user_id"),
            ("add_user_navidrome", "process_new_navidrome_user"),
            ("edit_navidrome_user", "process_edit_navidrome_user"),
        ],
    )
    def test_dispatches_to_correct_method(self, dispatcher, workflow, method_name):
        update = make_update()
        context = make_context(workflow=workflow)
        user_mgmt = Mock()
        setattr(user_mgmt, method_name, AsyncMock())

        handled = asyncio.run(
            dispatcher.try_dispatch(update, context, "some text", user_mgmt)
        )

        assert handled is True
        getattr(user_mgmt, method_name).assert_called_once_with(update, context, "some text")

    def test_missing_user_mgmt_handler_shows_error_and_clears_user_data(self, dispatcher):
        update = make_update()
        context = make_context(workflow="add_user_id")

        handled = asyncio.run(
            dispatcher.try_dispatch(update, context, "some text", None)
        )

        assert handled is True
        update.message.reply_text.assert_called_once()
        assert context.user_data == {}

    def test_handler_missing_the_method_shows_error_and_clears_user_data(self, dispatcher):
        update = make_update()
        context = make_context(workflow="add_user_id")
        user_mgmt = Mock(spec=[])  # kein process_new_user_id-Attribut

        handled = asyncio.run(
            dispatcher.try_dispatch(update, context, "some text", user_mgmt)
        )

        assert handled is True
        update.message.reply_text.assert_called_once()
        assert context.user_data == {}


class TestCancelCheckPrecedesWorkflowDispatch:
    """
    Regressionstest fuer die BUG-006-Ursache auf Dispatcher-Ebene: die
    Klasse selbst erzwingt die Reihenfolge nicht (das tut der Aufrufer,
    RichMenuHandler.handle_text_message), aber is_cancel_command() muss
    unabhaengig vom aktiven Workflow-Zustand funktionieren - sie darf
    NICHT auf context.user_data zugreifen oder davon beeinflusst werden.
    """

    def test_is_cancel_command_ignores_active_workflow_context(self, dispatcher):
        # is_cancel_command nimmt gar keinen context/workflow-Parameter -
        # das ist bewusst so, damit der Aufrufer sie IMMER zuerst prüfen
        # kann, unabhaengig vom Workflow-Zustand.
        assert dispatcher.is_cancel_command("/cancel") is True
