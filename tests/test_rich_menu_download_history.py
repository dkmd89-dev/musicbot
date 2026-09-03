"""
Download-Verlauf + "🔁 Erneut versuchen" (docs/FINDINGS_INDEX.md,
"Download-Verlauf/Erneut-versuchen, persistenter Speicher" - Folgeschritt
des Download-Control-Centers, siehe test_rich_menu_download_control_center.py).

Deckt NUR die Menü-/Callback-Dispatch-Logik ab (RichMenuSystem, reine
Telegram-Formatierung/-Routing) - der zugrundeliegende
DownloadHistoryStore hat eigene, isolierte Tests in
tests/test_download_history_store.py. Die Verlaufs-Schreibaufrufe in
klassen/download_handler.py haben ihre eigenen Tests in
tests/test_download_handler_history_recording.py.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem
from services.downloader.download_history import DownloadHistoryStore


@pytest.fixture
def config():
    class MockConfig:
        OWNER_USER_ID = 12345
        ADMIN_USER_IDS = [12345]
        SESSION_TIMEOUT = 300
        MAX_CONCURRENT_SESSIONS = 100

    return MockConfig()


@pytest.fixture
def history_store(tmp_path):
    return DownloadHistoryStore(cache_dir=str(tmp_path / "download_history"))


@pytest.fixture
def menu_system(config, history_store):
    system = RichMenuSystem(config)
    system.initialize_menu_structure()
    system.set_download_history(history_store)
    return system


@pytest.fixture
def mock_update():
    update = Mock()
    update.effective_user.id = 999
    update.effective_chat.id = 999
    update.update_id = 4242
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    return asyncio.run(coro)


def last_text(mock_update):
    return mock_update.callback_query.edit_message_text.call_args.args[0]


def last_keyboard(mock_update):
    markup = mock_update.callback_query.edit_message_text.call_args.kwargs.get(
        "reply_markup"
    )
    return markup.inline_keyboard if markup else []


def last_keyboard_texts(mock_update):
    return [btn.text for row in last_keyboard(mock_update) for btn in row]


def _add(store, chat_id=999, url="https://youtu.be/X", title="Song", artist="Artist", status="success"):
    store.add_entry(chat_id, url=url, title=title, artist=artist, status=status)


class TestDlHistoryEmptyState:
    def test_no_entries_shows_placeholder_message(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Noch keine Downloads" in last_text(mock_update)

    def test_no_history_store_configured_shows_empty_state_not_crash(
        self, config, mock_update, mock_context
    ):
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        # set_download_history() bewusst NICHT aufgerufen.
        mock_update.callback_query.data = "dl:history"

        run_async(system.handle_callback(mock_update, mock_context))

        assert "Noch keine Downloads" in last_text(mock_update)

    def test_empty_state_has_back_button_only(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        texts = last_keyboard_texts(mock_update)
        assert any("Zurück" in t for t in texts)
        assert len(texts) == 1


class TestDlHistoryWithEntries:
    def test_entry_title_and_artist_shown(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, title="Mein Song", artist="Mein Artist")
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert "Mein Song" in text
        assert "Mein Artist" in text

    def test_newest_entry_listed_first(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, title="Alter Song")
        _add(history_store, title="Neuer Song")
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert text.index("Neuer Song") < text.index("Alter Song")

    def test_status_icons_reflect_entry_status(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, title="Erfolg", status="success")
        _add(history_store, title="Fehlschlag", status="failed")
        _add(history_store, title="Abbruch", status="cancelled")
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert "✅" in text
        assert "❌" in text
        assert "🛑" in text

    def test_each_entry_gets_a_retry_button(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, title="Track A")
        _add(history_store, title="Track B")
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        texts = last_keyboard_texts(mock_update)
        retry_buttons = [t for t in texts if t.startswith("🔁")]
        assert len(retry_buttons) == 2

    def test_only_entries_for_this_chat_are_shown(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, chat_id=999, title="Mein Track")
        _add(history_store, chat_id=111, title="Fremder Track")
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert "Mein Track" in text
        assert "Fremder Track" not in text


class TestDlRetry:
    def test_retry_calls_injected_callback_with_stored_url(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, url="https://youtu.be/RETRY_ME", title="Retry-Track")
        retry_callback = AsyncMock()
        menu_system.set_url_retry_callback(retry_callback)
        mock_update.callback_query.data = "dl:retry:0"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        retry_callback.assert_awaited_once()
        called_update, called_context, called_url = retry_callback.call_args.args
        assert called_url == "https://youtu.be/RETRY_ME"
        assert called_update.message.text == "https://youtu.be/RETRY_ME"
        assert called_context is mock_context

    def test_retry_update_adapter_reuses_real_effective_user_and_chat(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, url="https://youtu.be/X")
        retry_callback = AsyncMock()
        menu_system.set_url_retry_callback(retry_callback)
        mock_update.callback_query.data = "dl:retry:0"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        called_update = retry_callback.call_args.args[0]
        assert called_update.effective_user is mock_update.effective_user
        assert called_update.effective_chat is mock_update.effective_chat
        assert called_update.update_id == mock_update.update_id

    def test_retry_message_reply_text_bound_to_callback_query_message(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, url="https://youtu.be/X")
        retry_callback = AsyncMock()
        menu_system.set_url_retry_callback(retry_callback)
        mock_update.callback_query.data = "dl:retry:0"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        called_update = retry_callback.call_args.args[0]
        assert called_update.message.reply_text is mock_update.callback_query.message.reply_text

    def test_out_of_range_position_shows_error_not_crash(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, title="Einziger")
        mock_update.callback_query.data = "dl:retry:5"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "nicht mehr verfügbar" in last_text(mock_update)

    def test_no_history_store_shows_error_not_crash(
        self, config, mock_update, mock_context
    ):
        system = RichMenuSystem(config)
        system.initialize_menu_structure()
        system.set_url_retry_callback(AsyncMock())
        mock_update.callback_query.data = "dl:retry:0"

        run_async(system.handle_callback(mock_update, mock_context))

        assert "nicht verfügbar" in last_text(mock_update)

    def test_no_retry_callback_configured_shows_error_not_crash(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, url="https://youtu.be/X")
        # set_url_retry_callback() bewusst NICHT aufgerufen.
        mock_update.callback_query.data = "dl:retry:0"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "nicht möglich" in last_text(mock_update)

    def test_malformed_callback_data_shows_error_not_crash(
        self, menu_system, history_store, mock_update, mock_context
    ):
        _add(history_store, url="https://youtu.be/X")
        mock_update.callback_query.data = "dl:retry:not-a-number"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Ungültiger" in last_text(mock_update)
