# tests/test_bot_runtime_snapshot.py
# -*- coding: utf-8 -*-
"""
E1 — services/bot_runtime_snapshot.py: Bereinigung (Datenschutz, CLAUDE.md
§12), Schreiben/Lesen, Zustände available/stale/missing/corrupt.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services import bot_runtime_snapshot as brs


class _Cfg:
    def __init__(self, data_dir):
        self.DATA_DIR = data_dir


def _raw_record(**overrides):
    record = {
        "id": "EXC_20260928_101010_000001",
        "timestamp": "2026-09-28T10:10:10",
        "type": "ValueError",
        "category": "validation",
        "severity": "medium",
        "message": "kaputt",
        "context": {
            "module": "download_handler",
            "telegram_update": {"user": {"id": 4711, "username": "robin"}, "text_preview": "geheimer Text"},
            "user_id": 4711,
            "chat_id": 4711,
        },
        "stack_trace": ['File "/mnt/128ssd/musicbot/x.py", line 1'],
        "thread_id": 1,
        "thread_name": "MainThread",
    }
    record.update(overrides)
    return record


# ── Bereinigung ──────────────────────────────────────────────────────────


def test_sanitize_keeps_only_allowed_fields():
    sanitized = brs.sanitize_exception_record(_raw_record())

    assert set(sanitized) == {"id", "timestamp", "type", "category", "severity", "module", "message"}
    assert sanitized["module"] == "download_handler"
    dumped = json.dumps(sanitized)
    for forbidden in ("4711", "robin", "geheimer Text", "x.py", "MainThread", "telegram_update"):
        assert forbidden not in dumped


def test_sanitize_redacts_secrets_in_message():
    sanitized = brs.sanitize_exception_record(
        _raw_record(message="Login fehlgeschlagen password=hunter2 token=abc123")
    )

    assert "hunter2" not in sanitized["message"]
    assert "abc123" not in sanitized["message"]
    assert "[REDACTED]" in sanitized["message"]


def test_sanitize_redacts_telegram_bot_token_form():
    sanitized = brs.sanitize_exception_record(
        _raw_record(message="HTTP 401 für 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ")
    )

    assert "AAHdqTcv" not in sanitized["message"]


def test_sanitize_truncates_long_messages():
    sanitized = brs.sanitize_exception_record(_raw_record(message="x" * 1000))

    assert len(sanitized["message"]) == brs.MAX_MESSAGE_LENGTH + 1
    assert sanitized["message"].endswith("…")


def test_sanitize_without_context():
    sanitized = brs.sanitize_exception_record(_raw_record(context=None))

    assert sanitized["module"] is None


# ── Schreiben / Lesen ────────────────────────────────────────────────────


def test_missing_snapshot(tmp_path):
    result = brs.read_bot_runtime_snapshot(_Cfg(tmp_path))

    assert result["status"] == "missing"
    assert result["snapshot"] is None


def test_write_then_read_available(tmp_path):
    cfg = _Cfg(tmp_path)
    path = brs.write_bot_runtime_snapshot(
        cfg, {"duplicates": {"total_checks": 3}}, bot_started_at="2026-09-28T08:00:00+00:00"
    )

    result = brs.read_bot_runtime_snapshot(cfg)

    assert path == tmp_path / "bot_runtime_snapshot.json"
    assert result["status"] == "available"
    snap = result["snapshot"]
    assert snap["schema_version"] == brs.SNAPSHOT_SCHEMA_VERSION
    assert snap["bot_started_at"] == "2026-09-28T08:00:00+00:00"
    assert snap["interval_seconds"] == 60
    assert snap["sections"] == {"duplicates": {"total_checks": 3}}
    assert result["age_seconds"] < 5


def test_stale_after_three_intervals(tmp_path):
    cfg = _Cfg(tmp_path)
    brs.write_bot_runtime_snapshot(cfg, {}, bot_started_at="x")

    later = datetime.now(timezone.utc) + timedelta(seconds=brs.STALE_AFTER_SECONDS + 1)
    result = brs.read_bot_runtime_snapshot(cfg, now=later)

    assert result["status"] == "stale"
    assert result["snapshot"] is not None
    assert result["message"]


@pytest.mark.parametrize("content", ["{kaputt", json.dumps({"generated_at": "2026-09-28T10:00:00+00:00"})])
def test_corrupt_snapshot(tmp_path, content):
    (tmp_path / "bot_runtime_snapshot.json").write_text(content, encoding="utf-8")

    result = brs.read_bot_runtime_snapshot(_Cfg(tmp_path))

    assert result["status"] == "corrupt"
    assert result["snapshot"] is None


def test_write_failure_is_not_raised(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")

    assert brs.write_bot_runtime_snapshot(_Cfg(blocker), {}, bot_started_at="x") is None


def test_non_json_values_are_serialized_as_strings(tmp_path):
    cfg = _Cfg(tmp_path)
    brs.write_bot_runtime_snapshot(cfg, {"errors": {"last_reset": datetime(2026, 9, 28)}}, bot_started_at="x")

    snap = brs.read_bot_runtime_snapshot(cfg)["snapshot"]

    assert snap["sections"]["errors"]["last_reset"] == "2026-09-28 00:00:00"
