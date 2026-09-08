# tests/test_repair_service.py
# -*- coding: utf-8 -*-
"""services/library_repair/repair_service.py — Orchestrierung von Plan,
Preview, Ausführung (SAFE_AUTOMATIC), Verification, History und
Statistik. Der Health-Scan/Repair-Subprozess selbst (doctor_runner.py)
wird gemockt (bereits eigene Tests in tests/test_doctor_runner.py) -
hier wird ausschließlich die Orchestrierungslogik getestet."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

import services.library_repair.repair_service as rs
from services.library_health.findings import (
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    FindingsRegistry,
    generate_finding_id,
)
from services.library_repair.doctor_runner import DoctorRepairResult, DoctorScanResult


def run(coro):
    return asyncio.run(coro)


def _issue(code, severity="WARNING", scope="file", **kwargs):
    base = {
        "issue_code": code, "severity": severity, "scope": scope, "path": None,
        "artist": None, "album": None, "title": None, "message": f"msg {code}",
        "details": {}, "confidence": None, "related_files": [],
    }
    base.update(kwargs)
    return base


def _report(issues, *, score=95.0, status="EXCELLENT"):
    return {
        "schema_version": "1.0",
        "scan": {"started_at": "t0", "completed_at": "t1", "duration_seconds": 1.0},
        "library": {"root": "/lib", "files": len(issues), "artists": 1, "albums": 1},
        "health": {"score": score, "status": status},
        "statistics": {},
        "issues": issues,
    }


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.Config, "DATA_DIR", tmp_path)
    yield tmp_path


class TestBuildRepairPlan:
    def test_filters_out_resolved_and_false_positive_issues(self):
        issues = [
            _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a"),
            {**_issue("META_ALBUM_ARTIST_MISSING", scope="file", path="b.m4a"),
             "finding_status": STATUS_RESOLVED},
            {**_issue("META_ALBUM_ARTIST_MISSING", scope="file", path="c.m4a"),
             "finding_status": STATUS_FALSE_POSITIVE},
        ]
        scan_result = DoctorScanResult(exit_code=0, report=_report(issues))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())

        paths = {c.path for c in plan.candidates}
        assert paths == {"a.m4a"}

    def test_raises_on_failed_scan(self):
        scan_result = DoctorScanResult(exit_code=3, report=None, error_message="boom")
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            with pytest.raises(rs.HealthScanFailedError):
                run(rs.build_repair_plan())

    def test_issue_without_finding_status_treated_as_open(self):
        """Rueckwaertskompatibilitaet: ein Report ohne Findings-Integration
        (kein 'finding_status'-Feld) gilt als offen, nicht als
        ausgeschlossen."""
        issues = [_issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a")]
        assert "finding_status" not in issues[0]
        scan_result = DoctorScanResult(exit_code=0, report=_report(issues))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())
        assert len(plan.candidates) == 1

    def test_empty_plan_when_no_issues(self):
        scan_result = DoctorScanResult(exit_code=0, report=_report([]))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())
        assert plan.candidates == []


class TestSafeAutomaticCandidatesAndPreview:
    def test_only_safe_automatic_level_included(self):
        issues = [
            _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a"),  # SAFE_AUTOMATIC
            _issue("ARTWORK_MISSING", scope="file", path="b.m4a"),  # COVER
            _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y"),  # MANUAL_REVIEW
        ]
        scan_result = DoctorScanResult(exit_code=0, report=_report(issues))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())
        safe = rs.get_safe_automatic_candidates(plan)
        assert len(safe) == 1
        assert safe[0].path == "a.m4a"

    def test_preview_is_read_only_and_lists_files_and_components(self, tmp_path):
        issues = [_issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a")]
        scan_result = DoctorScanResult(exit_code=0, report=_report(issues))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())
        safe = rs.get_safe_automatic_candidates(plan)

        before = list(tmp_path.iterdir())
        preview = rs.build_preview(safe)

        assert preview.read_only is True
        assert preview.affected_files == ["a.m4a"]
        assert preview.candidate_count == 1
        assert "TagWriter" in preview.executor_components
        assert list(tmp_path.iterdir()) == before  # keine Datei entstanden

    def test_empty_candidates_preview(self):
        preview = rs.build_preview([])
        assert preview.candidate_count == 0
        assert preview.affected_files == []


class TestConcurrencyLock:
    def test_second_acquire_raises(self):
        rs.acquire_repair_lock()
        try:
            with pytest.raises(rs.RepairAlreadyRunningError):
                rs.acquire_repair_lock()
        finally:
            rs.release_repair_lock()

    def test_release_allows_new_acquire(self):
        rs.acquire_repair_lock()
        rs.release_repair_lock()
        rs.acquire_repair_lock()  # darf nicht erneut raisen
        rs.release_repair_lock()

    def test_is_repair_running_reflects_lock_state(self):
        assert rs.is_repair_running() is False
        rs.acquire_repair_lock()
        assert rs.is_repair_running() is True
        rs.release_repair_lock()
        assert rs.is_repair_running() is False

    def test_execute_raises_when_already_locked_without_running_scan(self):
        rs.acquire_repair_lock()
        try:
            with patch.object(
                rs, "run_health_scan", new=AsyncMock(side_effect=AssertionError("darf nicht aufgerufen werden"))
            ):
                with pytest.raises(rs.RepairAlreadyRunningError):
                    run(rs.execute_safe_automatic_repair(triggered_by="test"))
        finally:
            rs.release_repair_lock()


class TestExecuteSafeAutomaticRepair:
    def _seed_registry_and_scan(self, tmp_path, issue):
        registry = FindingsRegistry(rs._findings_registry_path())
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        registry.save()
        return generate_finding_id(issue)

    def test_empty_plan_returns_skipped_without_lock_left(self, tmp_path):
        scan_result = DoctorScanResult(exit_code=0, report=_report([]))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            result = run(rs.execute_safe_automatic_repair(triggered_by="test"))
        assert result.status == rs.STATUS_SKIPPED
        assert result.candidates_total == 0
        assert rs.is_repair_running() is False

    def test_success_marks_finding_resolved_only_after_verification(self, tmp_path):
        issue = _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a", artist="X")
        fid = self._seed_registry_and_scan(tmp_path, issue)

        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        repair_result = DoctorRepairResult(exit_code=0)
        # Verification-Scan: Finding nicht mehr erkannt -> tatsaechlich behoben.
        post_scan = DoctorScanResult(exit_code=0, report=_report([]))

        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "2026-01-01T00:00:01Z", "file": "a.m4a",
                    "issue_code": "META_ALBUM_ARTIST_MISSING", "action": "MULTI_ARTIST_SPLIT",
                    "status": "SUCCESS",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, "run_safe_automatic_repair", new=AsyncMock(side_effect=_fake_apply)):
            result = run(rs.execute_safe_automatic_repair(triggered_by="telegram:1"))

        assert result.status == rs.STATUS_SUCCESS
        assert result.resolved_count == 1
        assert result.status_counts.get("SUCCESS") == 1

        registry = FindingsRegistry(rs._findings_registry_path())
        finding = registry.get(fid)
        assert finding.status == STATUS_RESOLVED
        assert finding.reviewed_by == "repair:telegram:1"
        assert rs.is_repair_running() is False

    def test_never_sets_false_positive_even_on_failure(self, tmp_path):
        issue = _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a", artist="X")
        fid = self._seed_registry_and_scan(tmp_path, issue)

        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        repair_result = DoctorRepairResult(exit_code=1)
        # Verification: Finding weiterhin erkannt (Reparatur schlug fehl) -
        # annotiert wie es die echte CLI (annotate_issues_with_findings())
        # vor der Rueckgabe tun wuerde.
        annotated_issue = {**issue, "finding_id": fid, "finding_status": STATUS_OPEN}
        post_scan = DoctorScanResult(exit_code=0, report=_report([annotated_issue]))

        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "2026-01-01T00:00:01Z", "file": "a.m4a",
                    "issue_code": "META_ALBUM_ARTIST_MISSING", "action": "MULTI_ARTIST_SPLIT",
                    "status": "FAILED", "error": "Verifikation fehlgeschlagen",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, "run_safe_automatic_repair", new=AsyncMock(side_effect=_fake_apply)):
            result = run(rs.execute_safe_automatic_repair(triggered_by="telegram:1"))

        assert result.status == rs.STATUS_FAILED
        assert result.resolved_count == 0

        registry = FindingsRegistry(rs._findings_registry_path())
        finding = registry.get(fid)
        assert finding.status == STATUS_OPEN
        assert finding.status != STATUS_FALSE_POSITIVE

    def test_skipped_journal_entry_does_not_resolve_finding(self, tmp_path):
        issue = _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a", artist="X")
        fid = self._seed_registry_and_scan(tmp_path, issue)

        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        repair_result = DoctorRepairResult(exit_code=0)
        annotated_issue = {**issue, "finding_id": fid, "finding_status": STATUS_OPEN}
        post_scan = DoctorScanResult(exit_code=0, report=_report([annotated_issue]))

        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "t", "file": "a.m4a",
                    "issue_code": "META_ALBUM_ARTIST_MISSING", "action": "MULTI_ARTIST_SPLIT",
                    "status": "SKIPPED", "reason": "nichts zu tun",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, "run_safe_automatic_repair", new=AsyncMock(side_effect=_fake_apply)):
            result = run(rs.execute_safe_automatic_repair(triggered_by="telegram:1"))

        assert result.status == rs.STATUS_SKIPPED
        registry = FindingsRegistry(rs._findings_registry_path())
        assert registry.get(fid).status == STATUS_OPEN

    def test_health_scan_failure_before_execution_returns_failed(self, tmp_path):
        scan_result = DoctorScanResult(exit_code=3, report=None, error_message="boom")
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            result = run(rs.execute_safe_automatic_repair(triggered_by="test"))
        assert result.status == rs.STATUS_FAILED
        assert "boom" in result.error_message
        assert rs.is_repair_running() is False

    def test_stale_plan_is_always_freshly_rebuilt_before_execution(self, tmp_path):
        """Abschnitt 41: execute_* baut IMMER einen frischen Plan direkt
        vor der Ausfuehrung - ein vorher an anderer Stelle erzeugter Plan
        wird nie wiederverwendet, kann also strukturell nie 'stale' sein."""
        issue = _issue("META_ALBUM_ARTIST_MISSING", scope="file", path="a.m4a", artist="X")
        self._seed_registry_and_scan(tmp_path, issue)

        scan_calls = []

        async def _tracking_scan(*a, **kw):
            scan_calls.append(1)
            if len(scan_calls) == 1:
                return DoctorScanResult(exit_code=0, report=_report([issue]))
            return DoctorScanResult(exit_code=0, report=_report([]))

        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"file": "a.m4a", "status": "SUCCESS"}) + "\n")
            return DoctorRepairResult(exit_code=0)

        with patch.object(rs, "run_health_scan", new=_tracking_scan), \
             patch.object(rs, "run_safe_automatic_repair", new=AsyncMock(side_effect=_fake_apply)):
            run(rs.execute_safe_automatic_repair(triggered_by="test"))

        # 1x fuer den frischen Plan direkt vor der Ausfuehrung, 1x fuer
        # die Verification danach.
        assert len(scan_calls) == 2


class TestJournalWindowReading:
    def test_reads_only_entries_within_offset_window(self, tmp_path):
        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(json.dumps({"file": "before.m4a", "status": "SUCCESS"}) + "\n")
        offset_before = journal_path.stat().st_size
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"file": "during.m4a", "status": "SUCCESS"}) + "\n")
        offset_after = journal_path.stat().st_size
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"file": "after.m4a", "status": "SUCCESS"}) + "\n")

        entries = rs._read_journal_window(offset_before, offset_after)
        assert [e["file"] for e in entries] == ["during.m4a"]

    def test_missing_journal_returns_empty(self, tmp_path):
        assert rs._read_journal_window(0, 100) == []

    def test_corrupt_line_is_skipped_not_raised(self, tmp_path):
        journal_path = rs._journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text("{not valid json}\n" + json.dumps({"file": "ok.m4a", "status": "SUCCESS"}) + "\n")
        entries = rs._read_journal_window(0, journal_path.stat().st_size)
        assert [e["file"] for e in entries] == ["ok.m4a"]


class TestRepairHistoryAndStatistics:
    def test_history_empty_when_no_runs(self):
        assert rs.load_repair_history() == []

    def test_history_returns_newest_first(self):
        rs._append_run_record({"repair_id": "1", "started_at": "2026-01-01T00:00:00Z"})
        rs._append_run_record({"repair_id": "2", "started_at": "2026-01-02T00:00:00Z"})
        history = rs.load_repair_history()
        assert [h["repair_id"] for h in history] == ["2", "1"]

    def test_history_limit(self):
        for i in range(5):
            rs._append_run_record({"repair_id": str(i)})
        assert len(rs.load_repair_history(limit=2)) == 2

    def test_corrupt_runs_index_does_not_raise(self, tmp_path):
        rs._runs_index_path().parent.mkdir(parents=True, exist_ok=True)
        rs._runs_index_path().write_text("{not valid json", encoding="utf-8")
        assert rs.load_repair_history() == []

    def test_statistics_are_dynamic_not_hardcoded(self):
        rs._append_run_record({
            "repair_id": "1", "status_counts": {"SUCCESS": 3, "FAILED": 1},
            "issue_codes": ["ARTWORK_MISSING"],
        })
        rs._append_run_record({
            "repair_id": "2", "status_counts": {"SUCCESS": 2, "SKIPPED": 1},
            "issue_codes": ["ARTWORK_MISSING", "META_GENRE_MISSING"],
        })
        stats = rs.compute_repair_statistics()
        assert stats["total_runs"] == 2
        assert stats["success"] == 5
        assert stats["failed"] == 1
        assert stats["skipped"] == 1
        assert stats["total"] == 7
        assert stats["most_common_issue_codes"][0] == ("ARTWORK_MISSING", 2)

    def test_statistics_empty_history(self):
        stats = rs.compute_repair_statistics()
        assert stats == {
            "total_runs": 0, "total": 0, "success": 0, "failed": 0,
            "skipped": 0, "most_common_issue_codes": [],
        }


class TestUnicodeSupport:
    def test_candidate_with_unicode_artist_album_generates_stable_id(self, tmp_path):
        issue = _issue(
            "META_ALBUM_ARTIST_MISSING", scope="file", path="Björk/Ünïcödé Ålbüm/01.m4a",
            artist="Björk Ähnlichkeitsklub", album="Ünïcödé Ålbüm 🎵",
        )
        scan_result = DoctorScanResult(exit_code=0, report=_report([issue]))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            plan = run(rs.build_repair_plan())
        safe = rs.get_safe_automatic_candidates(plan)
        assert len(safe) == 1
        fid = generate_finding_id(rs._candidate_to_issue_dict(safe[0]))
        assert isinstance(fid, str) and len(fid) > 0
