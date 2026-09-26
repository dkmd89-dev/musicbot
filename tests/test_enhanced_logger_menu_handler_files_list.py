# tests/test_enhanced_logger_menu_handler_files_list.py
# -*- coding: utf-8 -*-
"""
CC-LOGGER-L7 — Regressionstests für show_log_files_list()/
show_log_files_stats(), nachdem Discovery/Sortierung/Aggregation auf
services/logger_admin.py::list_log_files()/get_log_file_stats()
(identisch zu Control Center) umgestellt wurden.

Nutzerentscheidung (CC-LOGGER-L7): Sortierung wechselt bewusst von
"nach Dateigröße absteigend" auf "nach mtime, neueste zuerst"; rotierte
Logs (*.log.1, ...) werden jetzt ebenfalls gelistet/gezählt. Dafür gab
es vor der Migration keinen Test.
"""

import asyncio
import time
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
    return d


@pytest.fixture
def handler(log_dir):
    h = EnhancedLoggerMenuHandler(FakeConfig(log_dir))
    # Der Handler schreibt beim Init sein eigenes
    # enhanced_logger_handler.log in denselben log_dir - fuer diese
    # Datei-Listen-/Statistik-Tests ein irrelevanter Fixture-Nebeneffekt,
    # der die erwarteten Dateizahlen verfaelschen wuerde. Unlink genuegt
    # (der offene FileHandler schreibt auf POSIX klaglos weiter in den
    # jetzt namenlosen Inode, taucht aber nicht mehr in log_dir auf).
    own_log = log_dir / "enhanced_logger_handler.log"
    if own_log.exists():
        own_log.unlink()
    return h


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _sent_text(update) -> str:
    args, kwargs = update.callback_query.edit_message_text.call_args
    return args[0] if args else kwargs.get("text", "")


class TestShowLogFilesListSorting:
    def test_sorted_by_mtime_newest_first_not_by_size(self, handler, log_dir):
        # "small.log" ist klein, aber die zuletzt geaenderte Datei -
        # unter der alten Sortierung (Groesse absteigend) waere sie
        # zuletzt gelistet worden.
        (log_dir / "big.log").write_text("x" * 5000, encoding="utf-8")
        time.sleep(0.01)
        (log_dir / "small.log").write_text("x", encoding="utf-8")

        update = make_update()
        asyncio.run(handler.show_log_files_list(update, Mock()))

        text = _sent_text(update)
        assert text.index("small.log") < text.index("big.log")

    def test_rotated_logs_are_now_included(self, handler, log_dir):
        (log_dir / "bot.log").write_text("current", encoding="utf-8")
        (log_dir / "bot.log.1").write_text("rotated", encoding="utf-8")

        update = make_update()
        asyncio.run(handler.show_log_files_list(update, Mock()))

        text = _sent_text(update)
        assert "bot.log.1" in text
        assert "bot.log" in text
        assert "Gesamt: 2 Dateien" in text

    def test_missing_log_dir_shows_distinct_message(self, handler, log_dir):
        missing_dir = log_dir / "does_not_exist"
        handler.config.LOG_DIR = str(missing_dir)

        update = make_update()
        asyncio.run(handler.show_log_files_list(update, Mock()))

        text = _sent_text(update)
        assert "Log-Verzeichnis nicht gefunden" in text

    def test_empty_existing_dir_shows_no_files_message(self, handler, log_dir):
        update = make_update()
        asyncio.run(handler.show_log_files_list(update, Mock()))

        text = _sent_text(update)
        assert "Keine Log-Dateien gefunden" in text


class TestShowLogFilesStats:
    def test_reports_largest_and_oldest_file(self, handler, log_dir):
        (log_dir / "old.log").write_text("x", encoding="utf-8")
        time.sleep(0.01)
        (log_dir / "new.log").write_text("x" * 5000, encoding="utf-8")

        update = make_update()
        asyncio.run(handler.show_log_files_stats(update, Mock()))

        text = _sent_text(update)
        assert "Anzahl Dateien: 2" in text
        assert "Größte Datei: new.log" in text
        assert "Älteste Datei: old.log" in text

    def test_missing_log_dir_shows_distinct_message(self, handler, log_dir):
        missing_dir = log_dir / "does_not_exist"
        handler.config.LOG_DIR = str(missing_dir)

        update = make_update()
        asyncio.run(handler.show_log_files_stats(update, Mock()))

        text = _sent_text(update)
        assert "Log-Verzeichnis nicht gefunden" in text
