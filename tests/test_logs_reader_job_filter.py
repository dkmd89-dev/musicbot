# -*- coding: utf-8 -*-
"""D.12b.2: Reader extrahiert [JOB <8hex>] aus der Message (beide
Positionen) und filtert per job_id — ohne Migration alter Log-Zeilen."""
from __future__ import annotations

from pathlib import Path

from services.logs.reader import read_logs


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_line_with_job_right_after_component(tmp_path):
    _write(tmp_path / "bot.log", [
        "10:00:00 ℹ️ [MODULE] [JOB abcdef12] Nachricht",
    ])
    e = read_logs(tmp_path, source="bot.log", limit=10)["entries"][0]
    assert e.job_id == "abcdef12"
    assert e.message == "Nachricht"


def test_parse_line_job_registry_style(tmp_path):
    """JobRegistry schreibt das Token mitten in die Message (mit Emoji)."""
    _write(tmp_path / "bot.log", [
        "10:00:00 ℹ️ [JOBREGISTRY] 🧩 [JOB abcdef12] Download gestartet",
    ])
    e = read_logs(tmp_path, source="bot.log", limit=10)["entries"][0]
    assert e.job_id == "abcdef12"
    assert "Download gestartet" in e.message
    assert "[JOB " not in e.message


def test_parse_line_without_job(tmp_path):
    _write(tmp_path / "bot.log", ["10:00:00 ℹ️ [MODULE] Nachricht"])
    e = read_logs(tmp_path, source="bot.log", limit=10)["entries"][0]
    assert e.job_id is None
    assert e.message == "Nachricht"


def test_job_id_filter_selects_matching_lines(tmp_path):
    _write(tmp_path / "bot.log", [
        "10:00:00 ℹ️ [MODULE] [JOB abcdef12] eins",
        "10:00:01 ℹ️ [MODULE] [JOB fedcba98] zwei",
        "10:00:02 ℹ️ [MODULE] ohne job",
    ])
    body = read_logs(tmp_path, source="bot.log", job_id="abcdef12", limit=10)
    assert body["total_matched"] == 1
    assert body["entries"][0].message == "eins"


def test_job_id_filter_case_insensitive(tmp_path):
    _write(tmp_path / "bot.log", ["10:00:00 ℹ️ [MODULE] [JOB abcdef12] x"])
    body = read_logs(tmp_path, source="bot.log", job_id="ABCDEF12", limit=10)
    assert body["total_matched"] == 1


def test_historical_lines_still_parse(tmp_path):
    _write(tmp_path / "bot.log", [
        "10:00:00 ℹ️ [YOUTUBEDOWNLOADER] alter Eintrag",
        "10:00:01 ℹ️ [MODULE] [JOB abcdef12] neuer Eintrag",
    ])
    body = read_logs(tmp_path, source="bot.log", limit=10)
    assert body["total_matched"] == 2
    assert {e.job_id for e in body["entries"]} == {None, "abcdef12"}
