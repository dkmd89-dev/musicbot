# tests/test_menu_actions_admin_operations.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für
handlers/menu/actions/admin_operations.py (ARCH-024/P-2, Actions
Extraction) - 1:1 verschoben aus RichMenuSystem._handle_backup_*/
_handle_restart_*/_handle_maintenance_* und
RichMenuHandler._handle_navidrome_scan.

Der Navidrome-Scan selbst ist bereits ausführlich in
tests/test_rich_menu_handler.py::TestHandleNavidromeScan (jetzt gegen
handlers.menu.actions.admin_operations.NavidromeScanTrigger gepatcht)
und tests/test_menu_router_characterization.py::
TestAdminNavidromeRealRegistry abgedeckt - hier nur Backup/Restart/
Maintenance ergänzt.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import admin_operations as ops_actions


def _make_update(user_id: int = 111):
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=user_id)
    return update


@pytest.mark.asyncio
async def test_backup_main_delegates():
    update = _make_update()
    handler = Mock()
    handler.show_main_menu = AsyncMock()
    await ops_actions.handle_backup_main(update, Mock(), handler)
    handler.show_main_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_backup_main_fallback_without_handler():
    update = _make_update()
    await ops_actions.handle_backup_main(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Backup-Handler" in update.callback_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_backup_callback_delete_confirm_prefix():
    update = _make_update()
    handler = Mock()
    handler.confirm_delete = AsyncMock()
    await ops_actions.handle_backup_callback(
        update, Mock(), "backup_delete_confirm_foo.zip", handler, Mock()
    )
    handler.confirm_delete.assert_awaited_once()
    args, _ = handler.confirm_delete.call_args
    assert args[2] == "foo.zip"


@pytest.mark.asyncio
async def test_restart_show_no_handler():
    update = _make_update()
    await ops_actions.handle_restart_show(update, Mock(), None)
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Restart-Handler nicht verfügbar", show_alert=True
    )


@pytest.mark.asyncio
async def test_restart_callback_denies_non_admin():
    update = _make_update()
    is_admin_check = Mock(return_value=False)
    handler = Mock()
    await ops_actions.handle_restart_callback(
        update, Mock(), "restart:show", handler, is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


@pytest.mark.asyncio
async def test_maintenance_show_denies_non_admin():
    update = _make_update()
    is_admin_check = Mock(return_value=False)
    await ops_actions.handle_maintenance_show(update, Mock(), is_admin_check, Mock())
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


@pytest.mark.asyncio
async def test_maintenance_show_renders_active_status():
    update = _make_update()
    is_admin_check = Mock(return_value=True)
    store = Mock()
    store.is_active.return_value = True
    await ops_actions.handle_maintenance_show(update, Mock(), is_admin_check, store)
    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "AKTIV" in text


@pytest.mark.asyncio
async def test_maintenance_callback_toggle_flips_state_and_reshows():
    update = _make_update(user_id=1)
    is_admin_check = Mock(return_value=True)
    store = Mock()
    store.is_active.return_value = False
    logger = Mock()
    await ops_actions.handle_maintenance_callback(
        update, Mock(), "maint:toggle", is_admin_check, store, logger
    )
    store.set_active.assert_called_once_with(True, changed_by_user_id=1)
    logger.warning.assert_called_once()
    # handle_maintenance_show wurde intern erneut aufgerufen -> edit_message_text
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_maintenance_callback_missing_store():
    update = _make_update()
    is_admin_check = Mock(return_value=True)
    await ops_actions.handle_maintenance_callback(
        update, Mock(), "maint:show", is_admin_check, None, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Wartungsmodus-Speicher nicht verfügbar", show_alert=True
    )
