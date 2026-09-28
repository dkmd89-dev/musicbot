# tests/test_step_context.py
# -*- coding: utf-8 -*-
"""
D.12c — services/jobs/step_context.py: task-lokaler Schritt-Melder.

Kernanforderung: EnhancedMetadataProcessor ist ein Singleton, im
CC-Prozess laufen mehrere Download-Jobs parallel - Schritte zweier Jobs
dürfen sich nicht vermischen (contextvars pro asyncio-Task).
"""

from __future__ import annotations

import asyncio

from services.jobs.step_context import report_step, step_reporter


def test_report_step_without_reporter_is_noop():
    report_step("ohne Melder")  # darf nichts tun und nicht werfen


def test_reporter_receives_steps_and_is_reset_after_scope():
    received = []
    with step_reporter(received.append):
        report_step("A")
        report_step("B")
    report_step("nach dem Scope")
    assert received == ["A", "B"]


def test_failing_reporter_is_swallowed():
    def boom(_msg):
        raise RuntimeError("kaputt")

    with step_reporter(boom):
        report_step("A")  # darf die Pipeline nie unterbrechen


def test_parallel_tasks_are_isolated():
    async def job(name, received):
        with step_reporter(received.append):
            for i in range(3):
                report_step(f"{name}-{i}")
                await asyncio.sleep(0)

    async def main():
        a, b = [], []
        await asyncio.gather(job("a", a), job("b", b))
        return a, b

    a, b = asyncio.run(main())
    assert a == ["a-0", "a-1", "a-2"]
    assert b == ["b-0", "b-1", "b-2"]


def test_reporter_propagates_into_to_thread():
    received = []

    async def main():
        with step_reporter(received.append):
            await asyncio.to_thread(report_step, "im Thread")

    asyncio.run(main())
    assert received == ["im Thread"]
