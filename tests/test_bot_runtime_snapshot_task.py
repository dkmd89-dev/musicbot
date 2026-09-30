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


# ── B3: Mapping-Dateistand im Snapshot ───────────────────────────────────


def test_collect_includes_mapping_file_hashes_when_recorded(tmp_path):
    b = _make_bot(tmp_path)
    b._mapping_hashes_at_start = {"genre_aliases.yaml": "abc", "genre_filters.yaml": None}

    sections = b._collect_runtime_snapshot_sections()

    assert sections["mapping_files"] == {
        "hashes": {"genre_aliases.yaml": "abc", "genre_filters.yaml": None},
        "hashed_at": "2026-09-28T08:00:00+00:00",
    }


def test_collect_omits_mapping_section_when_hashing_failed(tmp_path):
    b = _make_bot(tmp_path)
    b._mapping_hashes_at_start = None

    assert "mapping_files" not in b._collect_runtime_snapshot_sections()


def test_record_mapping_files_hashes_the_configured_mapping_dir(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    (mdir / "genre_aliases.yaml").write_text("GENRE_ALIASES: {}\n", encoding="utf-8")
    b = _make_bot(tmp_path)
    b.config.GENRE_MAPPING_DIR = mdir

    b._record_mapping_files_at_start()

    assert b._mapping_hashes_at_start["genre_aliases.yaml"] and b._mapping_hashes_at_start["genre_filters.yaml"] is None


def test_record_mapping_files_failure_is_logged_and_not_raised(tmp_path, monkeypatch):
    b = _make_bot(tmp_path)
    b.config.GENRE_MAPPING_DIR = tmp_path
    monkeypatch.setattr(bot_module.mapping_runtime_state, "hash_mapping_files", lambda d: (_ for _ in ()).throw(RuntimeError("boom")))

    b._record_mapping_files_at_start()

    assert b._mapping_hashes_at_start is None
    b.logger.warning.assert_called()


def test_written_snapshot_roundtrips_into_runtime_state(tmp_path):
    from services import mapping_admin as ma
    from services import mapping_runtime_state as mrs

    mdir = tmp_path / "mapping"
    mdir.mkdir()
    for filename in ma.mapping_file_names().values():
        (mdir / filename).write_text("KEY: 1\n", encoding="utf-8")
    b = _make_bot(tmp_path)
    b.config.GENRE_MAPPING_DIR = mdir
    b._record_mapping_files_at_start()
    asyncio.run(b._write_runtime_snapshot())

    result = mrs.evaluate(mdir, brs.read_bot_runtime_snapshot(b.config))
    assert {s.state for s in result.statuses} == {"applied"} and result.bot_running is True

    (mdir / "genre_aliases.yaml").write_text("KEY: 2\n", encoding="utf-8")   # nach dem Start gespeichert
    result = mrs.evaluate(mdir, brs.read_bot_runtime_snapshot(b.config))
    assert {s.mapping_id: s.state for s in result.statuses}["genre-aliases"] == "pending_restart"
