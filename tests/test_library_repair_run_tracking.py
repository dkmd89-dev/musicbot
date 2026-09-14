# tests/test_library_repair_run_tracking.py
# -*- coding: utf-8 -*-
"""
services/library_repair/run_tracking.py — Extraktions-Regressionstest
(ARCH-032 Phase 3, ADR-0004). Charakterisiert das bestehende Verhalten
(Lock/Journal-Fenster/Run-Index/History/Statistik), das zuvor in
repair_service.py lag — reiner Move, dieselbe Semantik erwartet."""

import json

import pytest

import services.library_repair.run_tracking as rt


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rt.Config, "DATA_DIR", tmp_path)
    yield tmp_path


class TestPaths:
    def test_journal_path_under_data_dir(self, isolated_data_dir):
        assert rt.journal_path() == isolated_data_dir / rt.JOURNAL_FILENAME

    def test_runs_index_path_under_data_dir(self, isolated_data_dir):
        assert rt.runs_index_path() == isolated_data_dir / rt.RUNS_INDEX_FILENAME

    def test_lock_path_under_data_dir(self, isolated_data_dir):
        assert rt.lock_path() == isolated_data_dir / rt.LOCK_FILENAME


class TestLock:
    def test_acquire_creates_lock_file(self):
        rt.acquire_repair_lock()
        assert rt.lock_path().exists()
        assert rt.is_repair_running() is True
        rt.release_repair_lock()

    def test_release_removes_lock_file(self):
        rt.acquire_repair_lock()
        rt.release_repair_lock()
        assert rt.is_repair_running() is False

    def test_release_without_prior_acquire_is_noop(self):
        rt.release_repair_lock()  # darf nicht werfen
        assert rt.is_repair_running() is False

    def test_second_acquire_while_held_raises(self):
        """Charakterisiert bestehendes Verhalten: kein Warten ohne
        Timeout, kein stiller Fehler - sofortiger, definierter Fehler."""
        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                rt.acquire_repair_lock()
        finally:
            rt.release_repair_lock()

    def test_acquire_after_release_succeeds_again(self):
        rt.acquire_repair_lock()
        rt.release_repair_lock()
        rt.acquire_repair_lock()  # darf nicht werfen
        assert rt.is_repair_running() is True
        rt.release_repair_lock()

    def test_lock_file_contains_pid_and_timestamp(self):
        rt.acquire_repair_lock()
        content = rt.lock_path().read_text(encoding="utf-8")
        assert "|" in content
        pid_part, _, ts_part = content.partition("|")
        assert pid_part.isdigit()
        assert ts_part  # ISO-Timestamp, nicht leer
        rt.release_repair_lock()


class TestJournalWindow:
    def test_empty_when_journal_missing(self):
        assert rt.read_journal_window(0, 100) == []

    def test_empty_when_offset_after_not_greater(self):
        rt.journal_path().parent.mkdir(parents=True, exist_ok=True)
        rt.journal_path().write_text('{"a": 1}\n', encoding="utf-8")
        assert rt.read_journal_window(5, 5) == []

    def test_reads_entries_in_window(self):
        rt.journal_path().parent.mkdir(parents=True, exist_ok=True)
        line1 = json.dumps({"a": 1}) + "\n"
        rt.journal_path().write_text(line1, encoding="utf-8")
        offset_before = 0
        offset_after = rt.journal_path().stat().st_size

        line2 = json.dumps({"a": 2}) + "\n"
        with open(rt.journal_path(), "a", encoding="utf-8") as f:
            f.write(line2)

        entries = rt.read_journal_window(offset_before, offset_after)
        assert entries == [{"a": 1}]

    def test_skips_malformed_lines(self):
        rt.journal_path().parent.mkdir(parents=True, exist_ok=True)
        rt.journal_path().write_text("not json\n" + json.dumps({"a": 1}) + "\n", encoding="utf-8")
        entries = rt.read_journal_window(0, rt.journal_path().stat().st_size)
        assert entries == [{"a": 1}]


class TestRunIndex:
    def test_load_returns_empty_when_missing(self):
        assert rt.load_runs_index() == {"runs": []}

    def test_append_and_load(self):
        rt.append_run_record({"repair_id": "1"})
        rt.append_run_record({"repair_id": "2"})
        runs = rt.load_runs_index()["runs"]
        assert [r["repair_id"] for r in runs] == ["1", "2"]

    def test_load_recovers_from_corrupt_json(self):
        rt.runs_index_path().parent.mkdir(parents=True, exist_ok=True)
        rt.runs_index_path().write_text("{not valid json", encoding="utf-8")
        assert rt.load_runs_index() == {"runs": []}

    def test_history_is_newest_first(self):
        rt.append_run_record({"repair_id": "1"})
        rt.append_run_record({"repair_id": "2"})
        history = rt.load_repair_history()
        assert [r["repair_id"] for r in history] == ["2", "1"]

    def test_history_respects_limit(self):
        for i in range(5):
            rt.append_run_record({"repair_id": str(i)})
        assert len(rt.load_repair_history(limit=2)) == 2

    def test_write_json_atomic_leaves_no_tmp_file_on_success(self, isolated_data_dir):
        target = isolated_data_dir / "out.json"
        rt.write_json_atomic(target, {"a": 1})
        assert target.exists()
        assert list(isolated_data_dir.glob(".*.tmp_*")) == []


class TestKindField:
    def test_append_run_record_preserves_kind_field(self):
        rt.append_run_record({"repair_id": "1", "kind": rt.KIND_MAINTENANCE})
        runs = rt.load_runs_index()["runs"]
        assert runs[0]["kind"] == rt.KIND_MAINTENANCE

    def test_legacy_record_without_kind_field_still_loads(self):
        """Alte Run-Records ohne 'kind'-Feld bleiben lesbar (ADR-0004:
        additiv, keine erzwungene Migration bestehender Dateien)."""
        rt.append_run_record({"repair_id": "legacy-1"})
        runs = rt.load_runs_index()["runs"]
        assert "kind" not in runs[0]
        history = rt.load_repair_history()
        assert history[0]["repair_id"] == "legacy-1"


class TestStatistics:
    def test_empty_history(self):
        stats = rt.compute_repair_statistics()
        assert stats == {
            "total_runs": 0, "total": 0, "success": 0, "failed": 0,
            "skipped": 0, "most_common_issue_codes": [],
        }

    def test_aggregates_status_counts_across_runs(self):
        rt.append_run_record({
            "repair_id": "1",
            "status_counts": {"SUCCESS": 2, "FAILED": 1},
            "issue_codes": ["GENRE_DELIMITER_INCONSISTENT"],
        })
        rt.append_run_record({
            "repair_id": "2",
            "status_counts": {"SUCCESS": 1},
            "issue_codes": ["GENRE_DELIMITER_INCONSISTENT"],
        })
        stats = rt.compute_repair_statistics()
        assert stats["total_runs"] == 2
        assert stats["success"] == 3
        assert stats["failed"] == 1
        assert stats["most_common_issue_codes"] == [("GENRE_DELIMITER_INCONSISTENT", 2)]

    def test_aggregates_across_both_kinds(self):
        """Statistik summiert ueber BEIDE Flows (Finding-Repair +
        Maintenance) - kein Split nach kind in dieser Phase (ARCH-031 B.6)."""
        rt.append_run_record({
            "repair_id": "1", "kind": rt.KIND_REPAIR,
            "status_counts": {"SUCCESS": 1},
        })
        rt.append_run_record({
            "repair_id": "2", "kind": rt.KIND_MAINTENANCE,
            "status_counts": {"SUCCESS": 1},
        })
        stats = rt.compute_repair_statistics()
        assert stats["total_runs"] == 2
        assert stats["success"] == 2
