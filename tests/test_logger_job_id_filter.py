# -*- coding: utf-8 -*-
"""D.12b.2: _JobIdFilter setzt record.job_id immer; ColoredFormatter
rendert das Praefix konditional (kein Doppel-Praefix)."""
from __future__ import annotations

import logging

from logger import ColoredFormatter, _JobIdFilter
from services.jobs.job_context import bind_job


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="my_module", level=logging.INFO, pathname="x", lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_filter_sets_dash_without_job():
    rec = _record("hi")
    _JobIdFilter().filter(rec)
    assert rec.job_id == "-"


def test_filter_sets_first_8_chars():
    rec = _record("hi")
    with bind_job("abcdef1234567890"):
        _JobIdFilter().filter(rec)
    assert rec.job_id == "abcdef12"


def test_formatter_renders_prefix_when_job_present():
    fmt = ColoredFormatter(use_colors=False, use_emojis=False)
    rec = _record("Nachricht")
    with bind_job("abcdef12"):
        _JobIdFilter().filter(rec)
    out = fmt.format(rec)
    assert "[JOB abcdef12]" in out
    assert out.endswith("Nachricht")


def test_formatter_skips_prefix_if_message_already_has_it():
    fmt = ColoredFormatter(use_colors=False, use_emojis=False)
    rec = _record("[JOB abcdef12] Gestartet")
    with bind_job("abcdef12"):
        _JobIdFilter().filter(rec)
    out = fmt.format(rec)
    assert out.count("[JOB abcdef12]") == 1


def test_formatter_no_prefix_without_job():
    fmt = ColoredFormatter(use_colors=False, use_emojis=False)
    rec = _record("Nachricht")
    _JobIdFilter().filter(rec)
    out = fmt.format(rec)
    assert "[JOB " not in out
