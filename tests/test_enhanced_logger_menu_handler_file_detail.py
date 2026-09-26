# tests/test_enhanced_logger_menu_handler_file_detail.py
# -*- coding: utf-8 -*-
"""
CC-LOGGER-L7 — Regressionstests für den migrierten Inhalt von
EnhancedLoggerMenuHandler.show_log_file_detail() (Level-Verteilung +
Vorschau der letzten Zeilen), nachdem Datei-Zugriff und Level-Auswertung
auf services/logger_admin.py::get_log_file() (-> services/logs/reader.py
::read_logs()) umgestellt wurden, statt einer eigenen readlines()- und
naiven `if level in line`-Teilstring-Suche.

Dafür gab es vor der Migration keinen Test — tests/test_logger_menu_path_
traversal.py deckt ausschließlich den Sicherheitsaspekt ab.
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
    return d


@pytest.fixture
def handler(log_dir):
    return EnhancedLoggerMenuHandler(FakeConfig(log_dir))


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _sent_text(update) -> str:
    args, kwargs = update.callback_query.edit_message_text.call_args
    return args[0] if args else kwargs.get("text", "")


class TestShowLogFileDetailLevelDistribution:
    def test_counts_reflect_the_structured_level_field(self, handler, log_dir):
        (log_dir / "bot.log").write_text(
            "10:00:00 INFO [TESTMODULE] normal startup\n"
            "10:00:01 INFO [TESTMODULE] second info line\n"
            "10:00:02 ERROR [TESTMODULE] something failed\n",
            encoding="utf-8",
        )
        update = make_update()

        asyncio.run(handler.show_log_file_detail(update, Mock(), "bot.log"))

        text = _sent_text(update)
        assert "INFO: 2" in text
        assert "ERROR: 1" in text

    def test_naive_substring_misattribution_is_fixed(self, handler, log_dir):
        """Charakterisiert die eigentliche Verhaltensverbesserung dieser
        Migration: die vorherige `if level in line`-Teilstring-Suche
        haette diese WARNING-Zeile faelschlich als DEBUG gezaehlt, weil
        "DEBUG" zufaellig im Nachrichtentext vorkommt und in der
        Scan-Reihenfolge vor "WARNING" gecheckt wurde. Die strukturierte
        Level-Extraktion aus reader.py liest das echte Level-Feld aus
        dem Zeilenformat und ist von Nachrichtentext-Inhalt unabhaengig.
        """
        (log_dir / "bot.log").write_text(
            "10:00:00 WARNING [TESTMODULE] please DEBUG this carefully\n",
            encoding="utf-8",
        )
        update = make_update()

        asyncio.run(handler.show_log_file_detail(update, Mock(), "bot.log"))

        text = _sent_text(update)
        assert "WARNING: 1" in text
        assert "DEBUG: 1" not in text

    def test_preview_shows_last_five_lines_in_chronological_order(
        self, handler, log_dir
    ):
        lines = [f"10:00:{i:02d} INFO [TESTMODULE] line {i}" for i in range(7)]
        (log_dir / "bot.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        update = make_update()

        asyncio.run(handler.show_log_file_detail(update, Mock(), "bot.log"))

        text = _sent_text(update)
        preview_section = text.split("Letzte Einträge:")[1]
        # Die aeltesten zwei (line 0, line 1) duerfen NICHT in der
        # 5-Zeilen-Vorschau erscheinen ...
        assert "line 0" not in preview_section
        assert "line 1" not in preview_section
        # ... die letzten fuenf (line 2 - line 6) schon, in chronologischer
        # Reihenfolge (line 2 zuerst, line 6 zuletzt) - identisch zur
        # bisherigen Reihenfolge (lines[-5:], iteriert in Dateireihenfolge).
        assert preview_section.index("line 2") < preview_section.index("line 6")
        for i in range(2, 7):
            assert f"line {i}" in preview_section

    def test_unparseable_line_is_shown_as_raw_text_in_preview(
        self, handler, log_dir
    ):
        """Zeilen in einem nicht auswertbaren Fremdformat (siehe
        services/logs/reader.py-Docstring, z. B. AutoLearnManager mit
        vollem Datum statt HH:MM:SS) werden nicht verworfen, sondern
        unveraendert als Rohzeile in der Vorschau gezeigt."""
        (log_dir / "bot.log").write_text(
            "2026-08-16 12:00:00,000 - AutoLearnManager - INFO - custom format line\n",
            encoding="utf-8",
        )
        update = make_update()

        asyncio.run(handler.show_log_file_detail(update, Mock(), "bot.log"))

        text = _sent_text(update)
        assert "custom format line" in text
