# tests/test_logs_reader.py
# -*- coding: utf-8 -*-
"""
services/logs/reader.py — Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS".

Testet die reale Produktionsfunktion gegen echte, temporäre Logdateien
im tatsächlichen logger.py-Format (ANSI-Codes + Emoji, siehe
logger.py::ColoredFormatter), nie gegen die echte Produktions-Logdatei
(reine Lesefunktion wäre zwar unbedenklich, aber die genauen Zeilen
ändern sich laufend — Tests brauchen deterministische Fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.logs.reader import list_log_sources, read_logs


def _line(time: str, level_emoji: str, component: str, message: str, module_emoji: str = "") -> str:
    """Baut eine Zeile im echten logger.py-Format nach (inkl. ANSI-
    Farbcodes, siehe logger.py::ColoredFormatter.format())."""
    module_part = f"\x1b[36m{module_emoji} [{component}]\x1b[0m" if module_emoji else f"[{component}]"
    return f"{time} \x1b[37m{level_emoji}\x1b[0m {module_part} {message}"


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path


def _write(log_dir: Path, name: str, lines: list[str]) -> Path:
    path = log_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────────
# list_log_sources() — Discovery ueber das gesamte Log-Verzeichnis,
# identisch zur bereits etablierten Discovery in
# handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler
# (log_dir.glob("*.log*")).
# ─────────────────────────────────────────────────────────────────────────


def test_list_log_sources_returns_only_existing_files(log_dir):
    _write(log_dir, "bot.log", [_line("10:00:00", "ℹ️", "MAIN", "hi")])

    assert list_log_sources(log_dir) == ["bot.log"]


def test_list_log_sources_includes_rotated_backups(log_dir):
    _write(log_dir, "bot.log", ["current"])
    _write(log_dir, "bot.log.1", ["rotated 1"])
    _write(log_dir, "bot.log.2", ["rotated 2"])

    assert list_log_sources(log_dir) == ["bot.log", "bot.log.1", "bot.log.2"]


def test_list_log_sources_includes_other_module_log_files(log_dir):
    """Anders als eine reine bot.log-Rotationskette: auch separate
    Modul-Dateien (setup_module_logging(), propagate=False) sind
    sichtbar - sonst waeren deren Inhalte im Web nie einsehbar."""
    _write(log_dir, "bot.log", ["current"])
    _write(log_dir, "autolearnmanager.log", ["modul-spezifisch"])

    assert list_log_sources(log_dir) == ["autolearnmanager.log", "bot.log"]


def test_list_log_sources_ignores_non_log_files(log_dir):
    _write(log_dir, "bot.log", ["current"])
    (log_dir / "notes.txt").write_text("irrelevant", encoding="utf-8")

    assert list_log_sources(log_dir) == ["bot.log"]


def test_list_log_sources_empty_when_dir_missing(log_dir):
    missing_dir = log_dir / "does-not-exist"

    assert list_log_sources(missing_dir) == []


# ─────────────────────────────────────────────────────────────────────────
# read_logs() — Parsing/Reihenfolge/Filter
# ─────────────────────────────────────────────────────────────────────────


def test_read_logs_parses_time_level_component_message(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "erste Nachricht"),
    ])

    body = read_logs(log_dir, limit=10)

    assert body["source"] == "bot.log"
    assert body["total_matched"] == 1
    entry = body["entries"][0]
    assert entry.time == "10:00:00"
    assert entry.level == "INFO"
    assert entry.component == "MAIN"
    assert entry.message == "erste Nachricht"


def test_read_logs_defaults_to_bot_log_when_present(log_dir):
    """default_source (bot.log) gewinnt gegen die erste alphabetische
    Datei, wenn beide existieren."""
    _write(log_dir, "autolearnmanager.log", ["modul"])
    _write(log_dir, "bot.log", [_line("10:00:00", "ℹ️", "MAIN", "root")])

    body = read_logs(log_dir, limit=10)

    assert body["source"] == "bot.log"


def test_read_logs_falls_back_to_first_available_when_default_missing(log_dir):
    _write(log_dir, "autolearnmanager.log", ["modul-zeile"])

    body = read_logs(log_dir, limit=10)

    assert body["source"] == "autolearnmanager.log"


def test_read_logs_returns_newest_first(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "eins"),
        _line("10:00:01", "ℹ️", "MAIN", "zwei"),
        _line("10:00:02", "ℹ️", "MAIN", "drei"),
    ])

    body = read_logs(log_dir, limit=10)

    assert [e.message for e in body["entries"]] == ["drei", "zwei", "eins"]


def test_read_logs_handles_module_emoji_before_bracket(log_dir):
    """Reale Zeilen haben oft ZUSAETZLICH zum Level-Emoji ein Modul-
    Emoji direkt vor der eckigen Klammer (logger.py::MODULE_EMOJIS)."""
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "TELEGRAM_BOT", "Bot laeuft", module_emoji="📞"),
    ])

    body = read_logs(log_dir, limit=10)

    assert body["entries"][0].component == "TELEGRAM_BOT"
    assert body["entries"][0].message == "Bot laeuft"


def test_read_logs_handles_lines_without_module_emoji(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "keine Modul-Emoji-Zuordnung"),
    ])

    body = read_logs(log_dir, limit=10)

    assert body["entries"][0].component == "MAIN"


def test_read_logs_treats_non_matching_lines_as_unstructured_entries(log_dir):
    """Exception-Tracebacks (logger.py haengt sie mehrzeilig ohne
    Header an) sowie Zeilen aus abweichenden Modul-Formaten bleiben
    durchsuchbar, aber ohne level/component."""
    _write(log_dir, "bot.log", [
        _line("10:00:00", "❌", "MAIN", "Fehler aufgetreten"),
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
    ])

    body = read_logs(log_dir, limit=10)

    assert body["total_matched"] == 3
    traceback_entries = [e for e in body["entries"] if e.level is None]
    assert len(traceback_entries) == 2
    assert any("Traceback" in e.message for e in traceback_entries)


def test_read_logs_filters_by_level(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "info"),
        _line("10:00:01", "❌", "MAIN", "error"),
        _line("10:00:02", "⚠️", "MAIN", "warning"),
    ])

    body = read_logs(log_dir, level="ERROR", limit=10)

    assert body["total_matched"] == 1
    assert body["entries"][0].message == "error"


def test_read_logs_filters_by_component_case_insensitive(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "DOWNLOADHANDLER", "a"),
        _line("10:00:01", "ℹ️", "TELEGRAM_BOT", "b"),
    ])

    body = read_logs(log_dir, component="downloadhandler", limit=10)

    assert body["total_matched"] == 1
    assert body["entries"][0].message == "a"


def test_read_logs_filters_by_search_substring(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "Download gestartet fuer Song X"),
        _line("10:00:01", "ℹ️", "MAIN", "etwas ganz anderes"),
    ])

    body = read_logs(log_dir, search="Song X", limit=10)

    assert body["total_matched"] == 1
    assert "Song X" in body["entries"][0].message


def test_read_logs_respects_limit_but_reports_full_total_matched(log_dir):
    lines = [_line(f"10:00:{i:02d}", "ℹ️", "MAIN", f"Nachricht {i}") for i in range(20)]
    _write(log_dir, "bot.log", lines)

    body = read_logs(log_dir, limit=5)

    assert len(body["entries"]) == 5
    assert body["total_matched"] == 20
    assert body["limit"] == 5


def test_read_logs_selects_explicit_source(log_dir):
    _write(log_dir, "bot.log", [_line("10:00:00", "ℹ️", "MAIN", "aktuell")])
    _write(log_dir, "bot.log.1", [_line("09:00:00", "ℹ️", "MAIN", "rotiert")])

    body = read_logs(log_dir, source="bot.log.1", limit=10)

    assert body["source"] == "bot.log.1"
    assert body["entries"][0].message == "rotiert"


def test_read_logs_selects_explicit_module_source(log_dir):
    _write(log_dir, "bot.log", ["root"])
    _write(log_dir, "autolearnmanager.log", ["modul-zeile"])

    body = read_logs(log_dir, source="autolearnmanager.log", limit=10)

    assert body["source"] == "autolearnmanager.log"
    assert body["entries"][0].message == "modul-zeile"


def test_read_logs_unknown_source_returns_empty_not_an_error(log_dir):
    _write(log_dir, "bot.log", [_line("10:00:00", "ℹ️", "MAIN", "x")])

    body = read_logs(log_dir, source="../../../etc/passwd", limit=10)

    assert body["entries"] == []
    assert body["total_matched"] == 0


def test_read_logs_missing_dir_returns_empty_not_an_error(log_dir):
    missing_dir = log_dir / "does-not-exist"

    body = read_logs(missing_dir, limit=10)

    assert body["entries"] == []
    assert body["available_sources"] == []


# ─────────────────────────────────────────────────────────────────────────
# Security: Path-Traversal (SEC-003-Praezedenzfall) + ANSI-Bereinigung +
# defensive Secret-Redaktion
# ─────────────────────────────────────────────────────────────────────────


def test_read_logs_rejects_path_outside_log_dir_even_if_whitelist_bypassed(log_dir, tmp_path, monkeypatch):
    """Zweite Verteidigungslinie (identisch zum bereits gefixten
    SEC-003-Bug in EnhancedLoggerMenuHandler): selbst wenn `source`
    irgendwie in die Whitelist geraten wuerde, verhindert der
    resolve()/is_relative_to()-Check das Verlassen von log_dir."""
    import services.logs.reader as reader_module

    secret_file = tmp_path.parent / "outside-secret.log"
    secret_file.write_text("geheim", encoding="utf-8")

    monkeypatch.setattr(
        reader_module, "list_log_sources", lambda _dir: ["../outside-secret.log"]
    )

    body = read_logs(log_dir, source="../outside-secret.log", limit=10)

    assert body["entries"] == []
    assert body["source"] == ""


def test_read_logs_strips_ansi_color_codes(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "farbige Nachricht", module_emoji="📞"),
    ])

    body = read_logs(log_dir, limit=10)

    assert "\x1b[" not in body["entries"][0].message
    assert "\x1b[" not in (body["entries"][0].component or "")


@pytest.mark.parametrize("secret_text", [
    "token=abcdef123456",
    "password=hunter2",
    "api_key=sk-xxxxxxxxxx",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx",
    "123456789:AAExampleFakeTelegramBotTokenPlaceholder",
])
def test_read_logs_redacts_obvious_secret_patterns(log_dir, secret_text):
    """Defensive Zusatz-Redaktion (CLAUDE.md Abschnitt 12 P0) - greift
    unabhaengig davon, ob eine Zeile eigentlich niemals ein Secret
    enthalten sollte."""
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", f"Wert war {secret_text} Ende"),
    ])

    body = read_logs(log_dir, limit=10)

    assert secret_text not in body["entries"][0].message
    assert "[REDACTED]" in body["entries"][0].message


def test_read_logs_does_not_redact_ordinary_messages(log_dir):
    _write(log_dir, "bot.log", [
        _line("10:00:00", "ℹ️", "MAIN", "Download gestartet fuer Artist X - Song Y"),
    ])

    body = read_logs(log_dir, limit=10)

    assert body["entries"][0].message == "Download gestartet fuer Artist X - Song Y"
