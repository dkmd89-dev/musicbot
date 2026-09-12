# tests/test_menu_actions_download.py
# -*- coding: utf-8 -*-
"""
Characterization/Regressionstests für handlers/menu/actions/download.py
(ARCH-024/P-2, Actions Extraction) - 1:1 verschoben aus
RichMenuSystem's Download-Control-Center und
RichMenuHandler._process_url()/handle_url_message() u. a.

Diese Module wurden bereits ausführlich in
tests/test_rich_menu_download_control_center.py,
tests/test_rich_menu_handler.py (TestCreateDownloadHandler,
TestHandleUrlMessage) und tests/test_download_concurrency_semaphore.py
charakterisiert (jetzt gegen die neuen Modulpfade gepatcht) - hier nur
ergänzende Direkttests der jetzt eigenständigen Funktionen.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from handlers.menu.actions import download as dl_actions


def _make_update(user_id: int = 111):
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=user_id)
    update.effective_chat = Mock(id=999)
    return update


def test_dl_progress_bar_bounds():
    assert dl_actions._dl_progress_bar(0, 6) == "░░░░░░░░░░ 0/6"
    assert dl_actions._dl_progress_bar(6, 6) == "██████████ 6/6"
    assert dl_actions._dl_progress_bar(0, 0) == "░░░░░░░░░░ 0/0"


@pytest.mark.asyncio
async def test_handle_download_menu_no_active_download():
    update = _make_update()
    await dl_actions.handle_download_menu(update, Mock(), None)
    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Downloads" in text


@pytest.mark.asyncio
async def test_control_callback_unknown_shows_message():
    update = _make_update()
    await dl_actions.handle_download_control_callback(
        update, Mock(), "dl:unknown", None, None, None, Mock()
    )
    update.callback_query.edit_message_text.assert_awaited_once_with("⚠️ Unbekannte Aktion.")


@pytest.mark.asyncio
async def test_handle_download_retry_invalid_position():
    update = _make_update()
    query = AsyncMock()
    await dl_actions.handle_download_retry(
        update, Mock(), query, 999, "dl:retry:notanumber", Mock(), Mock()
    )
    query.edit_message_text.assert_awaited_once_with("⚠️ Ungültiger Verlaufseintrag.")


@pytest.mark.asyncio
async def test_handle_download_retry_missing_callback():
    update = _make_update()
    query = AsyncMock()
    download_history = Mock()
    download_history.get_entry_by_position.return_value = Mock(url="http://x", title="X")
    await dl_actions.handle_download_retry(
        update, Mock(), query, 999, "dl:retry:0", download_history, None
    )
    query.edit_message_text.assert_awaited_once_with("⚠️ Erneuter Download aktuell nicht möglich.")


@pytest.mark.asyncio
async def test_create_download_handler_missing_duplicate_detector():
    result = dl_actions.create_download_handler(
        _make_update(), Mock(), None, Mock(), Mock(), Mock(), Mock(), Mock()
    )
    assert result is None


@pytest.mark.asyncio
async def test_process_url_no_handler_replies_error():
    update = _make_update()
    update.message = AsyncMock()
    create_handler_callback = Mock(return_value=None)
    await dl_actions.process_url(update, Mock(), "http://x", create_handler_callback, Mock())
    update.message.reply_text.assert_awaited_once_with(
        "❌ Download-Dienst nicht verfügbar. Bitte versuche es später erneut."
    )


@pytest.mark.asyncio
async def test_handle_url_message_delegates_without_state():
    update = _make_update()
    update.message = Mock(text="http://x")
    process_url_callback = AsyncMock()
    await dl_actions.handle_url_message(update, Mock(), {}, process_url_callback)
    process_url_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_url_message_clears_state_after_processing():
    update = _make_update()
    update.message = Mock(text="http://x")
    user_states = {111: "awaiting_single_url"}
    process_url_callback = AsyncMock()
    await dl_actions.handle_url_message(update, Mock(), user_states, process_url_callback)
    assert 111 not in user_states


def test_retry_update_adapter_copies_identity_fields():
    source = Mock()
    source.effective_user = "user"
    source.effective_chat = "chat"
    source.update_id = 42
    adapter = dl_actions._RetryUpdateAdapter(source, "http://retry-url")
    assert adapter.effective_user == "user"
    assert adapter.effective_chat == "chat"
    assert adapter.update_id == 42
    assert adapter.message.text == "http://retry-url"
