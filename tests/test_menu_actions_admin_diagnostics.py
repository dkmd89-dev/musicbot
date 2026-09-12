# tests/test_menu_actions_admin_diagnostics.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für
handlers/menu/actions/admin_diagnostics.py (ARCH-024/P-2, Actions
Extraction) - 1:1 verschoben aus RichMenuSystem._handle_logger_callback/
_handle_error_admin_callback/_handle_status_callback/_handle_status_menu
und RichMenuHandler._handle_view_logs.
"""

import pytest
from unittest.mock import AsyncMock, Mock, mock_open, patch

from handlers.menu.actions import admin_diagnostics as diag_actions


def _make_update(user_id: int = 111):
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=user_id)
    return update


@pytest.mark.asyncio
async def test_logger_callback_no_handler():
    update = _make_update()
    await diag_actions.handle_logger_callback(update, Mock(), "logger_main_menu", None, Mock())
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Logger-Handler nicht verfügbar"
    )


@pytest.mark.asyncio
async def test_logger_callback_known_route_delegates():
    update = _make_update()
    handler = Mock()
    handler.show_main_menu = AsyncMock()
    await diag_actions.handle_logger_callback(update, Mock(), "logger_main_menu", handler, Mock())
    handler.show_main_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_logger_callback_module_toggle_prefix():
    update = _make_update()
    handler = Mock()
    handler.toggle_module = AsyncMock()
    await diag_actions.handle_logger_callback(
        update, Mock(), "logger_module_toggle_downloader", handler, Mock()
    )
    handler.toggle_module.assert_awaited_once()
    args, _ = handler.toggle_module.call_args
    assert args[2] == "downloader"


@pytest.mark.asyncio
async def test_error_admin_callback_denies_non_admin():
    update = _make_update()
    interface = Mock()
    interface.is_admin.return_value = False
    await diag_actions.handle_error_admin_callback(
        update, Mock(), "erradmin:show_stats", interface, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⛔ Keine Berechtigung")


@pytest.mark.asyncio
async def test_error_admin_callback_delegates_for_admin():
    update = _make_update()
    interface = Mock()
    interface.is_admin.return_value = True
    interface.handle_error_stats_command = AsyncMock()
    await diag_actions.handle_error_admin_callback(
        update, Mock(), "erradmin:show_stats", interface, Mock()
    )
    interface.handle_error_stats_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_callback_unknown_shows_not_implemented():
    update = _make_update()
    handler = Mock()
    await diag_actions.handle_status_callback(update, Mock(), "status_unknown", handler, Mock())
    update.callback_query.answer.assert_awaited_with("⚠️ Funktion nicht implementiert")


@pytest.mark.asyncio
async def test_status_menu_wrapper_uses_fallback_when_missing():
    update = _make_update()
    fallback = AsyncMock()
    await diag_actions.handle_status_menu(update, Mock(), None, fallback)
    fallback.assert_awaited_once_with(update, "Status-Handler")


@pytest.mark.asyncio
async def test_view_logs_denies_non_admin():
    update = _make_update(user_id=999)
    config = Mock(OWNER_USER_ID=1, ADMIN_USER_IDS=[])
    await diag_actions.handle_view_logs(update, Mock(), config, Mock())
    update.callback_query.answer.assert_awaited_once_with("⛔ Keine Berechtigung")


@pytest.mark.asyncio
async def test_view_logs_missing_file_shows_not_found():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1, ADMIN_USER_IDS=[], LOG_FILE="/nonexistent/x.log")
    with patch("handlers.menu.actions.admin_diagnostics.Path") as mock_path_cls:
        mock_path_cls.return_value.exists.return_value = False
        await diag_actions.handle_view_logs(update, Mock(), config, Mock())
    update.callback_query.edit_message_text.assert_awaited_once_with(
        "📄 **System-Logs**\n\nLog-Datei nicht gefunden."
    )
