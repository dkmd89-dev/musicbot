"""
Regressionstest fuer einen in Phase 3 gefundenen Path-Traversal-Bug (SEC-003,
siehe docs/archive/MusicBot_ENGINEERING_BASELINE.md), Teil desselben Fundes wie die
fehlende Admin-Pruefung in RichMenuSystem.handle_callback():

EnhancedLoggerMenuHandler.show_log_file_detail() baute file_path = log_dir /
filename aus unvalidiertem callback_data-Inhalt (logger_file_detail_<filename>).
Ein ".."-Pfad oder ein absoluter Pfad als filename (Path.__truediv__ verwirft
bei einem absoluten rechten Operanden den linken Teil komplett) liess beliebige
lesbare Dateien auf dem Host-Dateisystem einsehen - kombiniert mit der
(ebenfalls in Phase 3 gefundenen und gefixten) fehlenden Admin-Pruefung fuer
logger_-Callbacks war das ohne jede Berechtigung erreichbar.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.enhanced_logger_menu_handler import EnhancedLoggerMenuHandler


class FakeConfig:
    def __init__(self, log_dir):
        self.LOG_DIR = str(log_dir)


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    (d / "bot.log").write_text("2026-08-16 INFO some log line\n", encoding="utf-8")
    return d


@pytest.fixture
def handler(log_dir):
    return EnhancedLoggerMenuHandler(FakeConfig(log_dir))


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _sent_text(mock_edit_message_text: AsyncMock) -> str:
    args, kwargs = mock_edit_message_text.call_args
    return args[0] if args else kwargs.get("text", "")


class TestPathTraversalBlocked:
    def test_legitimate_log_file_is_still_readable(self, handler):
        update = make_update()

        asyncio.run(
            handler.show_log_file_detail(update, Mock(), "bot.log")
        )

        text = _sent_text(update.callback_query.edit_message_text)
        assert "Ungültiger Dateiname" not in text
        assert "nicht gefunden" not in text

    def test_double_dot_traversal_is_rejected(self, handler, tmp_path):
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("top secret host content", encoding="utf-8")
        update = make_update()

        asyncio.run(
            handler.show_log_file_detail(update, Mock(), "../secret.txt")
        )

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Ungültiger Dateiname" in text
        assert "top secret host content" not in text

    def test_absolute_path_is_rejected(self, handler, tmp_path):
        secret_file = tmp_path / "secret_absolute.txt"
        secret_file.write_text("another host secret", encoding="utf-8")
        update = make_update()

        asyncio.run(
            handler.show_log_file_detail(update, Mock(), str(secret_file))
        )

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Ungültiger Dateiname" in text
        assert "another host secret" not in text

    def test_etc_passwd_style_traversal_is_rejected(self, handler):
        update = make_update()

        asyncio.run(
            handler.show_log_file_detail(update, Mock(), "../../../../etc/passwd")
        )

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Ungültiger Dateiname" in text
