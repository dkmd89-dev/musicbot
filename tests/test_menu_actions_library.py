# tests/test_menu_actions_library.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/library.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_reprocessing_*/_handle_doctor_*/_handle_review_*/
_handle_repair_*.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import library as lib_actions


def _make_update(user_id: int = 111):
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=user_id)
    return update


# ---- Reprocessing (Owner-only) ----


@pytest.mark.asyncio
async def test_reprocessing_callback_denies_non_owner():
    update = _make_update(user_id=999)
    config = Mock(OWNER_USER_ID=1)
    await lib_actions.handle_reprocessing_callback(
        update, Mock(), "reprocess:show", Mock(), config, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


@pytest.mark.asyncio
async def test_reprocessing_callback_allows_owner_show():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1)
    handler = Mock()
    handler.show_artist_list = AsyncMock()
    await lib_actions.handle_reprocessing_callback(
        update, Mock(), "reprocess:show", handler, config, Mock()
    )
    handler.show_artist_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_reprocessing_callback_pick_parses_index():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1)
    handler = Mock()
    handler.handle_pick = AsyncMock()
    await lib_actions.handle_reprocessing_callback(
        update, Mock(), "reprocess:pick:3", handler, config, Mock()
    )
    handler.handle_pick.assert_awaited_once()
    args, _ = handler.handle_pick.call_args
    assert args[2] == 3


@pytest.mark.asyncio
async def test_reprocessing_callback_invalid_index_shows_alert():
    update = _make_update(user_id=1)
    config = Mock(OWNER_USER_ID=1)
    handler = Mock()
    await lib_actions.handle_reprocessing_callback(
        update, Mock(), "reprocess:pick:notanumber", handler, config, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Ungültiger Callback", show_alert=True
    )


# ---- Doctor (admin-gated, via is_admin_check callable) ----


@pytest.mark.asyncio
async def test_doctor_callback_denies_non_admin():
    update = _make_update()
    is_admin_check = Mock(return_value=False)
    await lib_actions.handle_doctor_callback(
        update, Mock(), "doctor:scan", Mock(), is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


@pytest.mark.asyncio
async def test_doctor_callback_scan_delegates_for_admin():
    update = _make_update()
    handler = Mock()
    handler.handle_scan = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_doctor_callback(
        update, Mock(), "doctor:scan", handler, is_admin_check, Mock()
    )
    handler.handle_scan.assert_awaited_once()


@pytest.mark.asyncio
async def test_doctor_scan_entry_uses_fallback_when_missing():
    update = _make_update()
    await lib_actions.handle_doctor_scan(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Doctor-Handler" in update.callback_query.edit_message_text.call_args[0][0]


# ---- Review (admin-gated, sub-routing by parts[1]) ----


@pytest.mark.asyncio
async def test_review_callback_severity_routes_correctly():
    update = _make_update()
    handler = Mock()
    handler.handle_severity = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_review_callback(
        update, Mock(), "review:severity:HIGH", handler, is_admin_check, Mock()
    )
    handler.handle_severity.assert_awaited_once()
    args, _ = handler.handle_severity.call_args
    assert args[2] == "HIGH"


@pytest.mark.asyncio
async def test_review_callback_denies_non_admin():
    update = _make_update()
    is_admin_check = Mock(return_value=False)
    await lib_actions.handle_review_callback(
        update, Mock(), "review:start", Mock(), is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


# ---- Repair (admin-gated, dict-based routing) ----


@pytest.mark.asyncio
async def test_repair_callback_execute_routes_correctly():
    update = _make_update()
    handler = Mock()
    handler.handle_execute = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_repair_callback(
        update, Mock(), "repair:execute", handler, is_admin_check, Mock()
    )
    handler.handle_execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_repair_callback_unknown_shows_message():
    update = _make_update()
    handler = Mock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_repair_callback(
        update, Mock(), "repair:unknown", handler, is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⚠️ Unbekannter Repair-Callback")
