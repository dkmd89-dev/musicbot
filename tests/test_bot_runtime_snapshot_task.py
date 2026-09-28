# tests/test_bot_runtime_snapshot_task.py
# -*- coding: utf-8 -*-
"""
E1 — bot.py::ExtendedBot: Sammeln/Schreiben des Bot-Runtime-Snapshots.
ExtendedBot wird ohne __init__ erzeugt (object.__new__), weil __init__
setup_enhanced_logging() aufruft und damit die Root-Handler der
Testsitzung ersetzen würde; nur die für E1 nötigen Attribute werden gesetzt.
"""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

import bot as bot_module
from handlers.enhanced_error_handler import EnhancedErrorHandler
from services import bot_runtime_snapshot as brs
from tests.test_enhanced_error_handler import FakeConfig


class _Cfg(FakeConfig):
    def __init__(self, data_dir):
        self.DATA_DIR = data_dir


def _make_bot(tmp_path, *, error_handler=None, detector=None):
    b = object.__new__(bot_module.ExtendedBot)
    b.config = _Cfg(tmp_path)
    b.logger = Mock()
    b.error_handler = error_handler
    b.rich_menu_handler = Mock(duplicate_detector=detector) if detector is not None else None
    b._shutdown_event = asyncio.Event()
    b._bot_started_at = "2026-09-28T08:00:00+00:00"
    b._runtime_snapshot_task = None
    return b


def _detector(stats=None):
    d = Mock()
    d.snapshot_section.return_value = stats or {"total_checks": 5}
    return d


def test_collect_contains_errors_and_duplicates(tmp_path):
    b = _make_bot(tmp_path, error_handler=EnhancedErrorHandler(FakeConfig()), detector=_detector())

    sections = b._collect_runtime_snapshot_sections()

    assert set(sections) == {"errors", "duplicates"}
    assert sections["duplicates"] == {"total_checks": 5}
    assert sections["errors"]["stats"]["total_exceptions"] == 0


def test_failing_section_does_not_block_others(tmp_path):
    broken = Mock()
    broken.export_snapshot_section.side_effect = RuntimeError("boom")
    b = _make_bot(tmp_path, error_handler=broken, detector=_detector())

    sections = b._collect_runtime_snapshot_sections()

    assert set(sections) == {"duplicates"}
    b.logger.warning.assert_called()


def test_without_components_writes_empty_sections(tmp_path):
    b = _make_bot(tmp_path)

    asyncio.run(b._write_runtime_snapshot())

    result = brs.read_bot_runtime_snapshot(b.config)
    assert result["status"] == "available"
    assert result["snapshot"]["sections"] == {}
    assert result["snapshot"]["bot_started_at"] == "2026-09-28T08:00:00+00:00"


def test_write_failure_does_not_raise(tmp_path, monkeypatch):
    b = _make_bot(tmp_path, detector=_detector())
    monkeypatch.setattr(brs, "write_bot_runtime_snapshot", Mock(side_effect=OSError("disk full")))

    asyncio.run(b._write_runtime_snapshot())

    b.logger.warning.assert_called()


def test_periodic_task_writes_immediately_and_stops_on_shutdown(tmp_path, monkeypatch):
    b = _make_bot(tmp_path, detector=_detector())
    monkeypatch.setattr(brs, "SNAPSHOT_INTERVAL_SECONDS", 3600)

    async def run():
        task = asyncio.create_task(b._periodic_runtime_snapshot())
        for _ in range(100):
            if brs.snapshot_path(b.config).exists():
                break
            await asyncio.sleep(0.01)
        b._shutdown_event.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())

    snap = brs.read_bot_runtime_snapshot(b.config)["snapshot"]
    assert snap["sections"]["duplicates"] == {"total_checks": 5}
