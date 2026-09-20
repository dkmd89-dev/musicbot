# tests/test_job_registry.py
# -*- coding: utf-8 -*-
"""
services/jobs/job_registry.py — Vertical Slice "Jobs-Grundgerüst" (Phase 1:
nur Infrastruktur, siehe Modul-Docstring dort).

Reine In-Memory-Logik, kein I/O, kein FastAPI-Bezug — Tests laufen direkt
gegen die Produktionsklasse (CLAUDE.md Abschnitt 7).
"""

from __future__ import annotations

from services.jobs.job_registry import JobRegistry
from services.jobs.models import JobStatus


def test_create_returns_pending_job_with_unique_id():
    registry = JobRegistry()
    job1 = registry.create(kind="demo_progress", initiator="1")
    job2 = registry.create(kind="demo_progress", initiator="1")

    assert job1.status == JobStatus.PENDING
    assert job1.progress == 0.0
    assert job1.job_id != job2.job_id


def test_get_returns_none_for_unknown_id():
    registry = JobRegistry()
    assert registry.get("does-not-exist") is None


def test_get_returns_created_job():
    registry = JobRegistry()
    job = registry.create(kind="demo_progress", initiator="42")
    assert registry.get(job.job_id) is job


def test_list_returns_newest_first():
    registry = JobRegistry()
    job1 = registry.create(kind="demo_progress", initiator="1")
    job1.created_at = "2026-01-01T00:00:00+00:00"
    job2 = registry.create(kind="demo_progress", initiator="1")
    job2.created_at = "2026-01-02T00:00:00+00:00"

    jobs = registry.list()

    assert [j.job_id for j in jobs] == [job2.job_id, job1.job_id]


def test_list_respects_limit():
    registry = JobRegistry()
    for _ in range(5):
        registry.create(kind="demo_progress", initiator="1")

    assert len(registry.list(limit=2)) == 2


class TestLifecycleTransitions:
    def test_mark_running_sets_status_and_started_at(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.mark_running(job.job_id)

        updated = registry.get(job.job_id)
        assert updated.status == JobStatus.RUNNING
        assert updated.started_at is not None

    def test_update_progress_sets_progress_and_message(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.update_progress(job.job_id, 42.0, "Schritt 2/5")

        updated = registry.get(job.job_id)
        assert updated.progress == 42.0
        assert updated.message == "Schritt 2/5"

    def test_update_progress_keeps_previous_message_when_not_given(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.update_progress(job.job_id, 10.0, "Erster Schritt")
        registry.update_progress(job.job_id, 20.0)

        assert registry.get(job.job_id).message == "Erster Schritt"

    def test_mark_succeeded_sets_status_progress_result_finished_at(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.mark_succeeded(job.job_id, result={"steps_completed": 5})

        updated = registry.get(job.job_id)
        assert updated.status == JobStatus.SUCCEEDED
        assert updated.progress == 100.0
        assert updated.result == {"steps_completed": 5}
        assert updated.finished_at is not None

    def test_mark_failed_sets_status_error_finished_at(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.mark_failed(job.job_id, "kaputt")

        updated = registry.get(job.job_id)
        assert updated.status == JobStatus.FAILED
        assert updated.error == "kaputt"
        assert updated.finished_at is not None

    def test_mark_failed_accepts_optional_diagnostic_result(self):
        """Nachtrag Phase 2 (Repair-Execution): ein fehlgeschlagener Job
        kann trotzdem Diagnosedaten liefern (z. B. Subprozess-stdout)."""
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.mark_failed(job.job_id, "Exit-Code 1", result={"stdout_tail": "..."})

        updated = registry.get(job.job_id)
        assert updated.result == {"stdout_tail": "..."}

    def test_mark_cancelled_sets_status_and_finished_at(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.mark_cancelled(job.job_id)

        updated = registry.get(job.job_id)
        assert updated.status == JobStatus.CANCELLED
        assert updated.finished_at is not None

    def test_lifecycle_methods_on_unknown_id_do_not_raise(self):
        registry = JobRegistry()
        # Kein Job existiert - alle Methoden muessen still bleiben statt
        # KeyError zu werfen (z.B. bei einem Race zwischen list() und
        # einer parallelen Cleanup-Operation, die es hier noch nicht gibt,
        # aber die Robustheit soll von Anfang an gelten).
        registry.mark_running("nope")
        registry.update_progress("nope", 5.0)
        registry.mark_succeeded("nope")
        registry.mark_failed("nope", "x")
        registry.mark_cancelled("nope")


class TestCancellation:
    def test_request_cancel_returns_true_for_known_job(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        assert registry.request_cancel(job.job_id) is True

    def test_request_cancel_returns_false_for_unknown_job(self):
        registry = JobRegistry()
        assert registry.request_cancel("does-not-exist") is False

    def test_is_cancel_requested_false_by_default(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        assert registry.is_cancel_requested(job.job_id) is False

    def test_is_cancel_requested_true_after_request_cancel(self):
        registry = JobRegistry()
        job = registry.create(kind="demo_progress", initiator="1")
        registry.request_cancel(job.job_id)
        assert registry.is_cancel_requested(job.job_id) is True

    def test_is_cancel_requested_false_for_unknown_job(self):
        registry = JobRegistry()
        assert registry.is_cancel_requested("does-not-exist") is False
