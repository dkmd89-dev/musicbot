"""
Download-Control-Center 2026-09-02 (Nutzer-Vorgabe): handlers/menu/
rich_menu_system.py::RichMenuSystem - "📥 Downloads" als echtes
Steuerzentrum (dl:*-Callbacks) statt der bisherigen statischen
2-Optionen-Liste.

Deckt NUR das Menü/die Callback-Dispatch-Logik ab (RichMenuSystem, reine
Telegram-Formatierung/-Routing) - die zugrundeliegende
ActiveDownloadRegistry/ActiveDownload hat eigene, isolierte Tests in
tests/test_active_download_registry.py. Die Registrierung/Deregistrierung
in klassen/download_handler.py hat ihre eigenen Tests in
tests/test_download_handler_active_download_lifecycle.py.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from handlers.menu.rich_menu_system import RichMenuSystem, _dl_progress_bar
from services.downloader.active_downloads import ActiveDownloadRegistry


@pytest.fixture
def config():
    class MockConfig:
        OWNER_USER_ID = 12345
        ADMIN_USER_IDS = [12345]
        SESSION_TIMEOUT = 300
        MAX_CONCURRENT_SESSIONS = 100

    return MockConfig()


@pytest.fixture
def menu_system(config):
    system = RichMenuSystem(config)
    system.initialize_menu_structure()
    system.set_active_downloads(ActiveDownloadRegistry(logger_factory=lambda n: Mock()))
    return system


@pytest.fixture
def mock_update():
    update = Mock()
    update.effective_user.id = 999  # bewusst KEIN Admin - siehe TestNotAdminGated
    update.effective_chat.id = 999
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = AsyncMock()
    return context


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


def last_text(mock_update):
    return mock_update.callback_query.edit_message_text.call_args.args[0]


def last_keyboard_texts(mock_update):
    """Extrahiert alle Button-Texte der zuletzt gesendeten Tastatur."""
    markup = mock_update.callback_query.edit_message_text.call_args.kwargs.get(
        "reply_markup"
    )
    if markup is None:
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


class TestDownloadMenuShell:
    def test_shows_downloads_heading(self, menu_system, mock_update, mock_context):
        mock_update.callback_query.data = "menu:download"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Downloads" in last_text(mock_update)

    def test_cancel_button_hidden_when_no_active_download(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "menu:download"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert not any("Abbrechen" in t for t in last_keyboard_texts(mock_update))

    def test_cancel_button_shown_when_download_active(
        self, menu_system, mock_update, mock_context
    ):
        menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="single"
        )
        mock_update.callback_query.data = "menu:download"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert any("Abbrechen" in t for t in last_keyboard_texts(mock_update))

    def test_always_shows_active_downloads_and_history_buttons(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "menu:download"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        texts = last_keyboard_texts(mock_update)
        assert any("Neuer Download" in t for t in texts)
        assert any("Aktive Downloads" in t for t in texts)
        assert any("Download-Verlauf" in t for t in texts)
        assert any("Hauptmenü" in t for t in texts)


class TestDlNew:
    def test_shows_prompt_to_send_a_link(self, menu_system, mock_update, mock_context):
        mock_update.callback_query.data = "dl:new"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "YouTube-Link" in last_text(mock_update)


class TestDlActive:
    def test_no_active_download_shows_idle_message(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:active"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "kein Download" in last_text(mock_update)

    def test_active_download_shows_title_and_progress_bar(
        self, menu_system, mock_update, mock_context
    ):
        active = menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="playlist"
        )
        active.title = "Zartmann – schönhauser EP"
        active.tracker.total_items = 6
        active.tracker.set_current_item("03 - Trackname")
        active.tracker.mark_completed("01 - Track 1")
        active.tracker.mark_completed("02 - Track 2")
        mock_update.callback_query.data = "dl:active"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert "Zartmann – schönhauser EP" in text
        assert "2/6" in text
        assert "⬇️ Aktuell" in text
        assert "03 - Trackname" in text
        assert "✅ Abgeschlossen" in text
        assert "01 - Track 1" in text
        assert "02 - Track 2" in text
        assert "⏳ Noch 4 Tracks" in text

    def test_active_download_shows_cancel_and_details_buttons(
        self, menu_system, mock_update, mock_context
    ):
        menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="single"
        )
        mock_update.callback_query.data = "dl:active"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        texts = last_keyboard_texts(mock_update)
        assert any("Download abbrechen" in t for t in texts)
        assert any("Details" in t for t in texts)

    def test_fully_completed_tracker_shows_no_remaining_line(
        self, menu_system, mock_update, mock_context
    ):
        active = menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="single"
        )
        active.tracker.total_items = 1
        active.tracker.mark_completed("Song")
        mock_update.callback_query.data = "dl:active"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Noch" not in last_text(mock_update)


class TestDlCancel:
    def test_no_active_download_shows_info_message(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:cancel"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Kein aktiver Download" in last_text(mock_update)

    def test_active_download_is_marked_cancel_requested(
        self, menu_system, mock_update, mock_context
    ):
        active = menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="single"
        )
        mock_update.callback_query.data = "dl:cancel"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert active.is_cancel_requested() is True
        assert "Abbruch angefordert" in last_text(mock_update)

    def test_cancel_does_not_affect_other_chats(
        self, menu_system, mock_update, mock_context
    ):
        other = menu_system.active_downloads.register(
            chat_id=111, url="https://youtu.be/other", download_type="single"
        )
        mock_update.callback_query.data = "dl:cancel"  # chat_id=999, kein eigener Download

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert other.is_cancel_requested() is False


class TestDlDetails:
    def test_no_active_download_shows_info_message(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:details"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Kein aktiver Download" in last_text(mock_update)

    def test_shows_url_and_elapsed_time(self, menu_system, mock_update, mock_context):
        active = menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/xyz", download_type="single"
        )
        active.title = "Some Title"
        mock_update.callback_query.data = "dl:details"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        text = last_text(mock_update)
        assert "https://youtu.be/xyz" in text
        assert "Some Title" in text
        assert "Laufzeit" in text


class TestDlHistory:
    def test_shows_placeholder(self, menu_system, mock_update, mock_context):
        mock_update.callback_query.data = "dl:history"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Download-Verlauf" in last_text(mock_update)


class TestDlMenuBackNavigation:
    def test_dl_menu_rerenders_the_shell(self, menu_system, mock_update, mock_context):
        mock_update.callback_query.data = "dl:menu"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Downloads" in last_text(mock_update)


class TestUnknownDlCallback:
    def test_does_not_crash_and_shows_warning(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "dl:totally_unknown"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "Unbekannte Aktion" in last_text(mock_update)


class TestNotAdminGated:
    """dl: ist bewusst NICHT in _ADMIN_ONLY_PREFIXES (im Gegensatz zu
    dup:/backup_/status_/logger_/usermgmt_) - jeder Nutzer darf seine
    eigenen Downloads steuern. mock_update.effective_user.id=999 ist in
    dieser Testdatei bewusst KEIN Admin (config.ADMIN_USER_IDS=[12345])."""

    def test_non_admin_can_open_download_menu(
        self, menu_system, mock_update, mock_context
    ):
        mock_update.callback_query.data = "menu:download"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "⛔" not in last_text(mock_update)
        assert "Downloads" in last_text(mock_update)

    def test_non_admin_can_cancel(self, menu_system, mock_update, mock_context):
        menu_system.active_downloads.register(
            chat_id=999, url="https://youtu.be/x", download_type="single"
        )
        mock_update.callback_query.data = "dl:cancel"

        run_async(menu_system.handle_callback(mock_update, mock_context))

        assert "⛔" not in last_text(mock_update)


class TestDlProgressBar:
    def test_zero_of_n_is_empty_bar(self):
        assert _dl_progress_bar(0, 6) == "░░░░░░░░░░ 0/6"

    def test_full_bar_at_completion(self):
        assert _dl_progress_bar(6, 6) == "██████████ 6/6"

    def test_partial_progress(self):
        bar = _dl_progress_bar(3, 6)
        assert bar.endswith("3/6")
        assert bar.count("█") == 5  # round(10 * 3/6) = 5

    def test_zero_total_does_not_divide_by_zero(self):
        assert _dl_progress_bar(0, 0) == "░░░░░░░░░░ 0/0"
