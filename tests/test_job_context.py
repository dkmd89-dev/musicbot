# -*- coding: utf-8 -*-
"""D.12b.2: Regression fuer services/jobs/job_context.py."""
from __future__ import annotations

import asyncio

from services.jobs.job_context import bind_job, get_current_job_id


def test_default_is_none():
    assert get_current_job_id() is None


def test_bind_job_sets_and_resets():
    with bind_job("abc12345"):
        assert get_current_job_id() == "abc12345"
    assert get_current_job_id() is None


def test_nested_bind_job_restores_previous():
    with bind_job("outer"):
        with bind_job("inner"):
            assert get_current_job_id() == "inner"
        assert get_current_job_id() == "outer"
    assert get_current_job_id() is None


def test_bind_job_none_is_valid():
    with bind_job("something"):
        with bind_job(None):
            assert get_current_job_id() is None
        assert get_current_job_id() == "something"


def test_asyncio_task_isolation():
    async def scenario():
        results = {}

        async def worker(name: str, jid: str):
            with bind_job(jid):
                await asyncio.sleep(0.01)
                results[name] = get_current_job_id()

        await asyncio.gather(worker("a", "aaaaaaaa"), worker("b", "bbbbbbbb"))
        return results

    assert asyncio.run(scenario()) == {"a": "aaaaaaaa", "b": "bbbbbbbb"}
