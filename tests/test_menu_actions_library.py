# tests/test_menu_actions_library.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/library.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem._handle_doctor_*/_handle_review_*/
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


# ---- Reprocessing: in CC-LIB-FINAL entfernt ----


def test_reprocessing_menu_actions_are_removed():
    """Regression: das Telegram-Reprocessing-Menue (reprocess:*) existiert
    nicht mehr — es haette die Metadaten-Neuableitung als Bedienweg
    angeboten."""
    assert not hasattr(lib_actions, "handle_reprocessing_show")
    assert not hasattr(lib_actions, "handle_reprocessing_callback")


# ---- L3 Pro-Artist-Reparatur (l23rep:*, L2 entfernt) ----


def _l23_handler():
    handler = Mock()
    for name in ("handle_l23_preview", "handle_l23_confirm_prompt", "handle_l23_execute"):
        setattr(handler, name, AsyncMock())
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("verb,method", [
    ("preview", "handle_l23_preview"),
    ("confirm", "handle_l23_confirm_prompt"),
    ("execute", "handle_l23_execute"),
])
async def test_l23rep_l3_callbacks_are_routed(verb, method):
    update = _make_update(user_id=1)
    handler = _l23_handler()
    await lib_actions.handle_l23rep_callback(
        update, Mock(), f"l23rep:{verb}:l3:4", handler, lambda uid: True, Mock()
    )
    getattr(handler, method).assert_awaited_once()
    assert getattr(handler, method).call_args.args[2:] == ("l3", 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["preview", "confirm", "execute"])
async def test_l23rep_stale_l2_callback_is_rejected_and_never_executes(verb):
    """Eine noch im Chat stehende Alt-Nachricht mit l23rep:*:l2:<idx>
    (vor CC-LIB-FINAL) darf nichts mehr ausloesen."""
    update = _make_update(user_id=1)
    handler = _l23_handler()
    await lib_actions.handle_l23rep_callback(
        update, Mock(), f"l23rep:{verb}:l2:0", handler, lambda uid: True, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⚠️ Ungültiges Level", show_alert=True)
    handler.handle_l23_preview.assert_not_awaited()
    handler.handle_l23_confirm_prompt.assert_not_awaited()
    handler.handle_l23_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_l23rep_denies_non_admin():
    update = _make_update(user_id=5)
    handler = _l23_handler()
    await lib_actions.handle_l23rep_callback(
        update, Mock(), "l23rep:execute:l3:0", handler, lambda uid: False, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⛔ Keine Berechtigung", show_alert=True)
    handler.handle_l23_execute.assert_not_awaited()


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
async def test_doctor_callback_score_history_delegates_for_admin():
    """Health-Score-Verlauf (Chat-Charakterisierung 2026-09-15) - identisches
    Routing-Muster wie doctor:scan."""
    update = _make_update()
    handler = Mock()
    handler.handle_score_history = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_doctor_callback(
        update, Mock(), "doctor:score_history", handler, is_admin_check, Mock()
    )
    handler.handle_score_history.assert_awaited_once()


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


# ---- Duplicate-Check (admin-gated, dict-based routing, Chat-Charakterisierung 2026-09-15) ----


@pytest.mark.asyncio
async def test_duplicate_check_callback_denies_non_admin():
    update = _make_update()
    is_admin_check = Mock(return_value=False)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:start", Mock(), is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⛔ Keine Berechtigung", show_alert=True
    )


@pytest.mark.asyncio
async def test_duplicate_check_callback_start_delegates_for_admin():
    update = _make_update()
    handler = Mock()
    handler.handle_start = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:start", handler, is_admin_check, Mock()
    )
    handler.handle_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_check_callback_artists_delegates_for_admin():
    update = _make_update()
    handler = Mock()
    handler.handle_artist_list = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:artists", handler, is_admin_check, Mock()
    )
    handler.handle_artist_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_check_callback_pick_routes_with_index():
    update = _make_update()
    context = Mock()
    handler = Mock()
    handler.handle_pick_artist = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, context, "dupcheck:pick:3", handler, is_admin_check, Mock()
    )
    handler.handle_pick_artist.assert_awaited_once_with(update, context, 3)


@pytest.mark.asyncio
async def test_duplicate_check_callback_pick_invalid_index_answers_error():
    update = _make_update()
    handler = Mock()
    handler.handle_pick_artist = AsyncMock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:pick:not-a-number", handler, is_admin_check, Mock()
    )
    handler.handle_pick_artist.assert_not_awaited()
    update.callback_query.answer.assert_awaited_once_with("⚠️ Ungültiger Callback", show_alert=True)


@pytest.mark.asyncio
async def test_duplicate_check_callback_unknown_shows_message():
    update = _make_update()
    handler = Mock()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:unknown", handler, is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with("⚠️ Unbekannter Duplikat-Check-Callback")


@pytest.mark.asyncio
async def test_duplicate_check_callback_no_handler_shows_message():
    update = _make_update()
    is_admin_check = Mock(return_value=True)
    await lib_actions.handle_duplicate_check_callback(
        update, Mock(), "dupcheck:start", None, is_admin_check, Mock()
    )
    update.callback_query.answer.assert_awaited_once_with(
        "⚠️ Duplikat-Check-Handler nicht verfügbar", show_alert=True
    )


@pytest.mark.asyncio
async def test_duplicate_check_start_entry_uses_fallback_when_missing():
    update = _make_update()
    await lib_actions.handle_duplicate_check_start(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Duplikat-Check-Handler" in update.callback_query.edit_message_text.call_args[0][0]
