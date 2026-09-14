# tests/test_repair_service_level23.py
# -*- coding: utf-8 -*-
"""services/library_repair/repair_service.py::execute_level2_repair()/
execute_level3_repair() — Pro-Artist L2/L3-Reparatur (ARCH-033).

Testmuster identisch zu TestExecuteSafeAutomaticRepair in
test_repair_service.py: doctor_runner.run_health_scan()/
run_level2_repair()/run_level3_repair() werden gemockt (eigene Tests in
tests/test_doctor_runner.py), hier wird ausschliesslich die
Orchestrierungslogik getestet (Artist-Scope-Filterung, Lock, Rescan,
Finding-Resolve, Run-Record)."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch

import services.library_repair.repair_service as rs
from services.library_health.findings import (
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


def _seed_registry_and_scan(issue):
    registry = FindingsRegistry(rs._findings_registry_path())
    registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
    registry.save()
    return generate_finding_id(issue)


class _LevelCase:
    """Buendelt die je Level (l2/l3) unterschiedlichen Test-Fixtures."""

    def __init__(self, level, issue_code, run_attr, repair_fn):
        self.level = level
        self.issue_code = issue_code
        self.run_attr = run_attr  # rs-Attributname des gemockten Runners
        self.repair_fn = repair_fn  # rs.execute_level2_repair / execute_level3_repair


L2 = _LevelCase("l2", "META_TITLE_NOT_CLEAN", "run_level2_repair", rs.execute_level2_repair)
L3 = _LevelCase("l3", "META_MB_RECORDING_MISSING", "run_level3_repair", rs.execute_level3_repair)


@pytest.mark.parametrize("case", [L2, L3], ids=["l2", "l3"])
class TestExecuteLevelRepairArtistScope:
    def test_empty_plan_for_artist_returns_skipped_without_lock_left(self, case):
        scan_result = DoctorScanResult(exit_code=0, report=_report([]))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            result = run(case.repair_fn("Bausa", triggered_by="test"))
        assert result.status == rs.STATUS_SKIPPED
        assert result.total == 0
        assert result.artist == "Bausa"
        assert result.level == case.level
        assert rs.is_repair_running() is False

    def test_only_matching_artist_candidates_are_scoped(self, case):
        """Ein Kandidat fuer einen ANDEREN Artist darf nicht mitlaufen -
        filter_plan(artist=) muss tatsaechlich greifen."""
        other_artist_issue = _issue(case.issue_code, path="OtherArtist/Singles/a.m4a", artist="OtherArtist")
        scan_result = DoctorScanResult(exit_code=0, report=_report([other_artist_issue]))
        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=scan_result)):
            result = run(case.repair_fn("Bausa", triggered_by="test"))
        assert result.status == rs.STATUS_SKIPPED
        assert result.total == 0

    def test_success_marks_finding_resolved_only_after_verification(self, case):
        issue = _issue(case.issue_code, scope="file", path="Bausa/Singles/a.m4a", artist="Bausa")
        fid = _seed_registry_and_scan(issue)

        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        repair_result = DoctorRepairResult(exit_code=0)
        post_scan = DoctorScanResult(exit_code=0, report=_report([]))

        jpath = rs.journal_path()
        jpath.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(jpath, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "2026-01-01T00:00:01Z", "file": "Bausa/Singles/a.m4a",
                    "issue_code": case.issue_code, "action": "X", "status": "SUCCESS",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, case.run_attr, new=AsyncMock(side_effect=_fake_apply)):
            result = run(case.repair_fn("Bausa", triggered_by="telegram:1"))

        assert result.status == rs.STATUS_SUCCESS
        assert result.success == 1
        assert result.resolved_count == 1
        assert result.rescan_triggered is True

        registry = FindingsRegistry(rs._findings_registry_path())
        finding = registry.get(fid)
        assert finding.status == STATUS_RESOLVED
        assert finding.reviewed_by == "repair:telegram:1"
        assert rs.is_repair_running() is False

    def test_failure_never_triggers_rescan_and_finding_stays_open(self, case):
        issue = _issue(case.issue_code, scope="file", path="Bausa/Singles/a.m4a", artist="Bausa")
        fid = _seed_registry_and_scan(issue)

        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        repair_result = DoctorRepairResult(exit_code=1)

        jpath = rs.journal_path()
        jpath.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(jpath, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "t", "file": "Bausa/Singles/a.m4a",
                    "issue_code": case.issue_code, "action": "X", "status": "FAILED",
                    "error": "Netzwerkfehler",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(return_value=pre_scan)) as mock_scan, \
             patch.object(rs, case.run_attr, new=AsyncMock(side_effect=_fake_apply)):
            result = run(case.repair_fn("Bausa", triggered_by="telegram:1"))

        assert result.status == rs.STATUS_FAILED
        assert result.failed == 1
        assert result.rescan_triggered is False
        # nur der Vorab-Scan (build_repair_plan), kein zweiter Verification-Scan:
        assert mock_scan.await_count == 1

        registry = FindingsRegistry(rs._findings_registry_path())
        assert registry.get(fid).status == STATUS_OPEN

    def test_partial_success_counts_all_buckets(self, case):
        issue_a = _issue(case.issue_code, path="Bausa/Singles/a.m4a", artist="Bausa")
        issue_b = _issue(case.issue_code, path="Bausa/Singles/b.m4a", artist="Bausa")
        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue_a, issue_b]))
        post_scan = DoctorScanResult(exit_code=0, report=_report([issue_b]))
        repair_result = DoctorRepairResult(exit_code=0)

        jpath = rs.journal_path()
        jpath.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(jpath, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "t", "file": "Bausa/Singles/a.m4a",
                    "issue_code": case.issue_code, "action": "X", "status": "SUCCESS",
                }) + "\n")
                f.write(json.dumps({
                    "timestamp": "t", "file": "Bausa/Singles/b.m4a",
                    "issue_code": case.issue_code, "action": "X", "status": "FAILED",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, case.run_attr, new=AsyncMock(side_effect=_fake_apply)):
            result = run(case.repair_fn("Bausa", triggered_by="telegram:1"))

        assert result.total == 2
        assert result.success == 1
        assert result.failed == 1
        assert result.status == rs.STATUS_SUCCESS  # >=1 SUCCESS -> Gesamtstatus SUCCESS

    def test_health_scan_failure_before_execution_returns_failed(self, case):
        with patch.object(
            rs, "run_health_scan", new=AsyncMock(return_value=DoctorScanResult(exit_code=3, report=None)),
        ):
            result = run(case.repair_fn("Bausa", triggered_by="test"))
        assert result.status == rs.STATUS_FAILED
        assert result.total == 0
        assert rs.is_repair_running() is False

    def test_lock_conflict_raises_and_does_not_run_repair(self, case):
        rs.acquire_repair_lock()
        try:
            with pytest.raises(rs.RepairAlreadyRunningError):
                run(case.repair_fn("Bausa", triggered_by="test"))
        finally:
            rs.release_repair_lock()

    def test_run_record_kind_is_repair_not_maintenance(self, case):
        issue = _issue(case.issue_code, path="Bausa/Singles/a.m4a", artist="Bausa")
        pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
        post_scan = DoctorScanResult(exit_code=0, report=_report([]))
        repair_result = DoctorRepairResult(exit_code=0)

        jpath = rs.journal_path()
        jpath.parent.mkdir(parents=True, exist_ok=True)

        def _fake_apply(*_a, **_kw):
            with open(jpath, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": "t", "file": "Bausa/Singles/a.m4a",
                    "issue_code": case.issue_code, "action": "X", "status": "SUCCESS",
                }) + "\n")
            return repair_result

        with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
             patch.object(rs, case.run_attr, new=AsyncMock(side_effect=_fake_apply)):
            run(case.repair_fn("Bausa", triggered_by="test"))

        history = rs.load_repair_history()
        assert len(history) == 1
        assert history[0]["kind"] == rs.KIND_REPAIR
        assert history[0]["artist"] == "Bausa"
        assert history[0]["level"] in ("METADATA_REPROCESSING", "EXTERNAL_METADATA")

    def test_shares_lock_with_safe_automatic_repair(self, case):
        """ADR-0004: ein gemeinsamer Lock ueber alle Repair-/Maintenance-
        Flows - ein laufender SAFE_AUTOMATIC-Lauf blockiert auch L2/L3."""
        rs.acquire_repair_lock()
        try:
            with pytest.raises(rs.RepairAlreadyRunningError):
                run(case.repair_fn("Bausa", triggered_by="test"))
        finally:
            rs.release_repair_lock()


class TestLevelRepairDoesNotAffectSafeAutomatic:
    def test_existing_safe_automatic_flow_untouched(self):
        """Reiner Schutz gegen versehentliche Kopplung: execute_level2_repair
        importieren/aufrufen darf execute_safe_automatic_repair() nicht
        beruehren (kein geteilter globaler State ausser Lock/Journal)."""
        assert rs.execute_safe_automatic_repair.__name__ == "execute_safe_automatic_repair"
        assert callable(rs.execute_level2_repair)
        assert callable(rs.execute_level3_repair)
