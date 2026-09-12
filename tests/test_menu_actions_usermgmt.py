# tests/test_menu_actions_usermgmt.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/usermgmt.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_usermgmt_callback und
RichMenuHandler._handle_user_management_wrapper.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import usermgmt as usermgmt_actions


def _make_update(user_id: int = 111):
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=user_id)
    return update


@pytest.mark.asyncio
async def test_callback_no_handler():
    update = _make_update()
    await usermgmt_actions.handle_usermgmt_callback(update, Mock(), "usermgmt_stats", None, Mock())
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ UserManagement-Handler nicht verfügbar"
    )


@pytest.mark.asyncio
async def test_callback_add_user_sets_workflow():
    update = _make_update()
    handler = Mock()
    context = Mock()
    context.user_data = {"pending_user_id": "x", "target_user_id": "y"}
    await usermgmt_actions.handle_usermgmt_callback(
        update, context, "usermgmt_add_user", handler, Mock()
    )
    assert context.user_data["workflow"] == "add_user_id"
    assert "pending_user_id" not in context.user_data
    assert "target_user_id" not in context.user_data


@pytest.mark.asyncio
async def test_callback_list_delegates_with_page():
    update = _make_update()
    handler = Mock()
    handler.show_user_management_menu = AsyncMock()
    await usermgmt_actions.handle_usermgmt_callback(
        update, Mock(), "usermgmt_list_3", handler, Mock()
    )
    handler.show_user_management_menu.assert_awaited_once()
    args, _ = handler.show_user_management_menu.call_args
    assert args[2] == 3


@pytest.mark.asyncio
async def test_callback_stats_routes_via_routing_map():
    update = _make_update()
    handler = Mock()
    handler.show_statistics = AsyncMock()
    await usermgmt_actions.handle_usermgmt_callback(
        update, Mock(), "usermgmt_stats", handler, Mock()
    )
    handler.show_statistics.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_search_uses_closure_over_query():
    update = _make_update()
    handler = Mock()
    await usermgmt_actions.handle_usermgmt_callback(
        update, Mock(), "usermgmt_search", handler, Mock()
    )
    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Benutzer suchen" in text


@pytest.mark.asyncio
async def test_callback_unknown_shows_not_implemented():
    update = _make_update()
    handler = Mock()
    await usermgmt_actions.handle_usermgmt_callback(
        update, Mock(), "usermgmt_totally_unknown", handler, Mock()
    )
    update.callback_query.answer.assert_awaited_with("⚠️ Funktion nicht implementiert")


@pytest.mark.asyncio
async def test_wrapper_denies_non_admin():
    update = _make_update(user_id=999)
    config = Mock(OWNER_USER_ID=1, ADMIN_USER_IDS=[])
    await usermgmt_actions.handle_user_management_wrapper(
        update, Mock(), config, Mock(), Mock(), Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⛔ Keine Berechtigung")


@pytest.mark.asyncio
async def test_wrapper_admin_reaches_handler():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1, ADMIN_USER_IDS=[])
    handler = Mock()
    handler.show_user_management_menu = AsyncMock()
    await usermgmt_actions.handle_user_management_wrapper(
        update, Mock(), config, handler, Mock(), Mock()
    )
    handler.show_user_management_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrapper_exception_uses_error_handler():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1, ADMIN_USER_IDS=[])
    handler = Mock()
    handler.show_user_management_menu = AsyncMock(side_effect=RuntimeError("x"))
    error_handler = Mock()
    error_handler.handle_callback_error = AsyncMock()
    await usermgmt_actions.handle_user_management_wrapper(
        update, Mock(), config, handler, error_handler, Mock()
    )
    error_handler.handle_callback_error.assert_awaited_once()
