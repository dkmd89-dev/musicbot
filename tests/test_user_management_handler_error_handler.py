# tests/test_user_management_handler_error_handler.py
# -*- coding: utf-8 -*-
"""
Tests für die EnhancedErrorHandler-Integration in
handlers/admin/user_management_handler.py::UserManagementHandler.

Analog zum bereits etablierten Muster (navidrome_menu_handler.py,
duplicate_handler.py, enhanced_logger_menu_handler.py, test_menu_handler.py):
ist error_handler gesetzt (wird von handlers/menu/rich_menu_handler.py nach
der Konstruktion zugewiesen - self.user_mgmt_handler.error_handler =
self.error_handler), wird er STATT der bisherigen lokalen Fehlermeldung
aufgerufen; ohne error_handler bleibt das bisherige Verhalten unveraendert.

Von den insgesamt 7 except-Bloecken der Datei sind nur 3 fuer diese
Integration relevant - alle anderen sind entweder private I/O-Hilfsmethoden
ohne Update/Context (_load_users, _save_users), ein innerer
Cleanup-except (OSError beim Loeschen einer tmp-Datei) oder ein bewusst
spezifisches ValueError-UX (ungueltige User-ID-Eingabe, keine generische
Fehlerbehandlung).

Isolation: analog zu tests/test_user_management_handler.py wird Path()
waehrend der Konstruktion auf ein tmp_path-Verzeichnis gepatcht, damit KEIN
Test die reale data/user_data.json beruehrt.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.admin.user_management_handler import UserManagementHandler


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [111, 222]


def _make_handler(tmp_path, config=None):
    user_data_file = tmp_path / "user_data.json"

    def _fake_path(p, *args, **kwargs):
        if p == "data/user_data.json":
            return user_data_file
        return Path(p, *args, **kwargs)

    with patch(
        "handlers.admin.user_management_handler.Path", side_effect=_fake_path
    ):
        handler = UserManagementHandler(config or FakeConfig())
    return handler, user_data_file


def run_async(coro):
    return asyncio.run(coro)


def make_update(user_id: int = 111):
    update = Mock()
    update.effective_user.id = user_id
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    context = Mock()
    context.user_data = {}
    return context


class TestProcessNewUserIdErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.process_new_user_id(update, context, "555"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "usermgmt_add_user_step1"
        assert isinstance(call_args[3], RuntimeError)
        update.message.reply_text.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler.error_handler is None
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.process_new_user_id(update, context, "555"))

        text = update.message.reply_text.call_args[0][0]
        assert "interner Fehler" in text


class TestProcessNewNavidromeUserErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()
        context.user_data["pending_user_id"] = "555"

        run_async(handler.process_new_navidrome_user(update, context, "navuser"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "usermgmt_add_user_step2"
        assert isinstance(call_args[3], RuntimeError)
        update.message.reply_text.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler.error_handler is None
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()
        context.user_data["pending_user_id"] = "555"

        run_async(handler.process_new_navidrome_user(update, context, "navuser"))

        text = update.message.reply_text.call_args[0][0]
        assert "Fehler" in text


class TestProcessEditNavidromeUserErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()
        context.user_data["target_user_id"] = "555"

        run_async(handler.process_edit_navidrome_user(update, context, "navuser"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "usermgmt_edit_navidrome_user"
        assert isinstance(call_args[3], RuntimeError)
        update.message.reply_text.assert_not_called()

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler, _ = _make_handler(tmp_path)
        assert handler.error_handler is None
        handler._load_users = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()
        context.user_data["target_user_id"] = "555"

        run_async(handler.process_edit_navidrome_user(update, context, "navuser"))

        text = update.message.reply_text.call_args[0][0]
        assert "Fehler" in text
