# tests/test_reprocessing_menu_handler.py
# -*- coding: utf-8 -*-
"""
Tests fuer handlers/menu/reprocessing_menu_handler.py::ReprocessingMenuHandler.

services/metadata/reprocessing_runner.py (list_available_artist_dirs()/
run_reprocessing()) ist hier durchgehend gemockt - dessen eigene, echte
Subprozess-Integration hat eigene Tests in tests/test_reprocessing_runner.py
(CLAUDE.md Abschnitt 8: externe/teure Aufrufe nicht in jedem Unit-Test
wiederholen).
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.reprocessing_menu_handler import ReprocessingMenuHandler
from services.metadata.reprocessing_runner import ReprocessingRunResult


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [222]


OWNER_ID = 111
ADMIN_ID = 222
OTHER_ID = 999


@pytest.fixture
def handler():
    return ReprocessingMenuHandler(FakeConfig(), logger_factory=lambda name: Mock())


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.edit_text = AsyncMock()
    return update


def _mock_context():
    return Mock()


def run_async(coro):
    return asyncio.run(coro)


def last_show_text(update):
    return update.callback_query.edit_message_text.call_args.args[0]


def last_show_keyboard_texts(update):
    markup = update.callback_query.edit_message_text.call_args.kwargs.get(
        "reply_markup"
    )
    if markup is None:
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


# ─────────────────────────────────────────────────────────────────────────
# show_artist_list()
# ─────────────────────────────────────────────────────────────────────────


class TestShowArtistListOwnerGating:
    def test_non_owner_is_rejected(self, handler):
        update = _mock_update(OTHER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Foo"],
        ):
            run_async(handler.show_artist_list(update, _mock_context()))

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True
        update.callback_query.edit_message_text.assert_not_called()

    def test_admin_but_not_owner_is_also_rejected(self, handler):
        """Bewusste Nutzer-Entscheidung: nur Owner, nicht Owner+Admin (im
        Unterschied zum Wartungsmodus)."""
        update = _mock_update(ADMIN_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Foo"],
        ):
            run_async(handler.show_artist_list(update, _mock_context()))

        update.callback_query.edit_message_text.assert_not_called()

    def test_owner_sees_artist_list(self, handler):
        update = _mock_update(OWNER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha", "Beta"],
        ):
            run_async(handler.show_artist_list(update, _mock_context()))

        texts = last_show_keyboard_texts(update)
        assert any("Alpha" in t for t in texts)
        assert any("Beta" in t for t in texts)


class TestShowArtistListEmptyState:
    def test_empty_list_shows_hint_instead_of_buttons(self, handler):
        update = _mock_update(OWNER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=[],
        ):
            run_async(handler.show_artist_list(update, _mock_context()))

        assert "Keine Artist-Verzeichnisse" in last_show_text(update)


# ─────────────────────────────────────────────────────────────────────────
# handle_pick() / handle_live()
# ─────────────────────────────────────────────────────────────────────────


class TestHandlePickAndLive:
    def test_pick_with_stale_index_shows_list_again(self, handler):
        update = _mock_update(OWNER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha"],
        ):
            run_async(handler.handle_pick(update, _mock_context(), idx=5))

        # answer() wird zweimal aufgerufen: einmal der Stale-Index-Hinweis
        # (mit Alert), danach nochmal implizit durch den Fallback auf
        # show_artist_list() (ohne Alert, normales Owner-Passthrough).
        first_call = update.callback_query.answer.call_args_list[0]
        assert first_call.kwargs.get("show_alert") is True
        # show_artist_list() wurde als Fallback aufgerufen
        assert "Metadata-Reprocessing" in last_show_text(update)

    def test_non_owner_pick_is_rejected(self, handler):
        update = _mock_update(OTHER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha"],
        ):
            run_async(handler.handle_pick(update, _mock_context(), idx=0))

        update.callback_query.message.edit_text.assert_not_called()

    def test_pick_delegates_to_start_run_with_dry_run_true(self, handler):
        """handle_pick() loest den Index gegen die Artist-Liste auf und
        delegiert an _start_run() - dessen eigene Hintergrund-Task-Mechanik
        (asyncio.create_task, analog zu rich_menu_handler.py::
        _process_url()) wird bewusst NICHT hier nochmal durchgespielt,
        sondern separat ueber die direkten _run_and_report()-Tests unten
        abgedeckt. Ein asyncio.run()-pro-Test-Aufbau kann einen per
        create_task() gestarteten Hintergrund-Task nicht zuverlaessig zu
        Ende laufen lassen, bevor die Event-Loop beim Verlassen von
        asyncio.run() wieder geschlossen wird."""
        update = _mock_update(OWNER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha"],
        ), patch.object(
            handler, "_start_run", AsyncMock()
        ) as mocked_start_run:
            run_async(handler.handle_pick(update, _mock_context(), idx=0))

        mocked_start_run.assert_called_once()
        assert mocked_start_run.call_args.args[1] == "Alpha"
        assert mocked_start_run.call_args.kwargs.get("dry_run") is True

    def test_live_delegates_to_start_run_with_dry_run_false(self, handler):
        update = _mock_update(OWNER_ID)

        with patch(
            "handlers.menu.reprocessing_menu_handler.list_available_artist_dirs",
            return_value=["Alpha"],
        ), patch.object(
            handler, "_start_run", AsyncMock()
        ) as mocked_start_run:
            run_async(handler.handle_live(update, _mock_context(), idx=0))

        mocked_start_run.assert_called_once()
        assert mocked_start_run.call_args.kwargs.get("dry_run") is False


# ─────────────────────────────────────────────────────────────────────────
# _run_and_report() / _format_result() - Nachrichteninhalt nach Abschluss
# ─────────────────────────────────────────────────────────────────────────


class TestRunAndReportMessageContent:
    def test_successful_dry_run_shows_live_button(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        fake_result = ReprocessingRunResult(
            exit_code=0,
            summary={
                "files_processed": 3, "changed": 2, "unchanged": 1,
                "unresolved": 0, "errors": 0, "overall": "PASS",
                "auto_learn_artists": ["Feat X"], "auto_learn_genres": ["Y"],
                "log": "/tmp/x.log",
            },
            log_path="/tmp/x.log",
        )

        with patch(
            "handlers.menu.reprocessing_menu_handler.run_reprocessing",
            AsyncMock(return_value=fake_result),
        ):
            run_async(handler._run_and_report(message, "Alpha", True, idx=0))

        text = message.edit_text.call_args.args[0]
        assert "abgeschlossen" in text
        assert "Alpha" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        button_texts = [b.text for row in keyboard.inline_keyboard for b in row]
        assert any("LIVE" in t for t in button_texts)

    def test_successful_live_run_shows_no_live_button(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        fake_result = ReprocessingRunResult(
            exit_code=0,
            summary={
                "files_processed": 1, "changed": 1, "unchanged": 0,
                "unresolved": 0, "errors": 0, "overall": "PASS",
                "auto_learn_artists": [], "auto_learn_genres": [], "log": "/tmp/x.log",
            },
            log_path="/tmp/x.log",
        )

        with patch(
            "handlers.menu.reprocessing_menu_handler.run_reprocessing",
            AsyncMock(return_value=fake_result),
        ):
            run_async(handler._run_and_report(message, "Alpha", False, idx=0))

        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        button_texts = [b.text for row in keyboard.inline_keyboard for b in row]
        assert not any("LIVE" in t for t in button_texts)

    def test_failed_run_shows_error_and_back_button_only(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        fake_result = ReprocessingRunResult(
            exit_code=1,
            summary=None,
            log_path=None,
            error_message="Input existiert nicht",
        )

        with patch(
            "handlers.menu.reprocessing_menu_handler.run_reprocessing",
            AsyncMock(return_value=fake_result),
        ):
            run_async(handler._run_and_report(message, "Alpha", True, idx=0))

        text = message.edit_text.call_args.args[0]
        assert "fehlgeschlagen" in text
        assert "Input existiert nicht" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        button_texts = [b.text for row in keyboard.inline_keyboard for b in row]
        assert not any("LIVE" in t for t in button_texts)

    def test_unexpected_exception_during_run_is_reported_not_raised(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()

        with patch(
            "handlers.menu.reprocessing_menu_handler.run_reprocessing",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            run_async(handler._run_and_report(message, "Alpha", True, idx=0))

        text = message.edit_text.call_args.args[0]
        assert "Unerwarteter Fehler" in text
        assert "boom" in text

    def test_artist_name_is_html_escaped(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        fake_result = ReprocessingRunResult(
            exit_code=0,
            summary={
                "files_processed": 1, "changed": 1, "unchanged": 0,
                "unresolved": 0, "errors": 0, "overall": "PASS",
                "auto_learn_artists": [], "auto_learn_genres": [], "log": "/x.log",
            },
            log_path="/x.log",
        )

        with patch(
            "handlers.menu.reprocessing_menu_handler.run_reprocessing",
            AsyncMock(return_value=fake_result),
        ):
            run_async(
                handler._run_and_report(message, "<script>Alpha</script>", True, idx=0)
            )

        text = message.edit_text.call_args.args[0]
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


# ─────────────────────────────────────────────────────────────────────────
# add_done_callback()-Sicherheitsnetz
# ─────────────────────────────────────────────────────────────────────────


class TestLogBackgroundTaskException:
    def test_logs_unexpected_exception_without_raising(self, handler):
        async def boom():
            raise RuntimeError("unerwartet")

        async def _drive():
            task = asyncio.create_task(boom())
            await asyncio.sleep(0)
            try:
                await task
            except RuntimeError:
                pass
            handler._log_background_task_exception(task)

        run_async(_drive())
        assert handler.logger.error.called

    def test_cancelled_task_is_ignored(self, handler):
        async def _drive():
            task = asyncio.create_task(asyncio.sleep(10))
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            handler._log_background_task_exception(task)

        run_async(_drive())
        assert not handler.logger.error.called
