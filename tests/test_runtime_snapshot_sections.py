# tests/test_runtime_snapshot_sections.py
# -*- coding: utf-8 -*-
"""
E1 — Snapshot-Abschnitte aus dem Bot-Prozess:
EnhancedErrorHandler.export_snapshot_section() und
DuplicateDetector.snapshot_section(). Echte Produktionsklassen.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from handlers.enhanced_error_handler import EnhancedErrorHandler
from services.bot_runtime_snapshot import MAX_RECENT_ERRORS
from services.duplicate.detector import DuplicateDetector
from tests.test_enhanced_error_handler import FakeConfig


def _record(handler, message, module="download_handler"):
    try:
        raise ValueError(message)
    except ValueError as e:
        handler.exception_monitor.record_exception(
            e,
            {
                "module": module,
                "telegram_update": {"user": {"id": 4711, "username": "robin"}},
                "user_id": 4711,
            },
        )


def test_error_section_contains_stats_and_sanitized_recent():
    handler = EnhancedErrorHandler(FakeConfig())
    _record(handler, "erster Fehler")
    _record(handler, "zweiter Fehler password=hunter2")

    section = handler.export_snapshot_section()

    assert section["stats"]["total_exceptions"] == 2
    assert section["stats"]["by_type"] == {"ValueError": 2}
    assert section["stats"]["by_module"] == {"download_handler": 2}
    assert [e["message"] for e in section["recent"]][0].startswith("zweiter Fehler")  # neueste zuerst
    dumped = json.dumps(section, default=str)
    for forbidden in ("4711", "robin", "hunter2", "telegram_update", "stack_trace", "Traceback"):
        assert forbidden not in dumped
    assert isinstance(section["performance"]["last_reset"], str)


def test_error_section_limits_recent_entries():
    handler = EnhancedErrorHandler(FakeConfig())
    for i in range(MAX_RECENT_ERRORS + 10):
        _record(handler, f"Fehler {i}")

    section = handler.export_snapshot_section()

    assert len(section["recent"]) == MAX_RECENT_ERRORS
    assert section["recent"][0]["message"] == f"Fehler {MAX_RECENT_ERRORS + 9}"


def test_error_section_does_not_change_state():
    handler = EnhancedErrorHandler(FakeConfig())
    _record(handler, "Fehler")
    before = handler.exception_monitor.get_statistics()["total_exceptions"]

    handler.export_snapshot_section()

    assert handler.exception_monitor.get_statistics()["total_exceptions"] == before
    assert len(handler.exception_monitor.exception_history) == 1


class _DupConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        mapping_dest = tmp_path / "mapping"
        shutil.copytree(Path(__file__).resolve().parent.parent / "mapping", mapping_dest)
        self.GENRE_MAPPING_DIR = mapping_dest


def test_duplicate_section_reports_session_counters(tmp_path):
    detector = DuplicateDetector(_DupConfig(tmp_path))
    url = "https://www.youtube.com/watch?v=AAA111"
    detector.check_for_duplicates(url)
    detector.register_download(url, "Artist", "Song")
    detector.check_for_duplicates(url)

    section = detector.snapshot_section()

    assert set(section) == {
        "total_checks", "url_duplicates_found", "content_duplicates_found",
        "new_entries_added", "duplicates_skipped", "duplicate_rate", "savings_percentage",
    }
    assert section["total_checks"] == 2
    assert section["url_duplicates_found"] == 1
    assert section["duplicate_rate"] == 50.0
