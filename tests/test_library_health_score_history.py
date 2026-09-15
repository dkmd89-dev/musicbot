# tests/test_library_health_score_history.py
# -*- coding: utf-8 -*-
"""
services/library_health/score_history.py — Health-Score-Verlauf
(Chat-Charakterisierung 2026-09-15). Reine Datei-Logik (append/read),
kein Scan, keine Library-Berührung - alle Tests arbeiten auf tmp_path.
"""

import json

from services.library_health.score_history import (
    append_score_history,
    read_score_history,
)


def _report(score=90.0, status="GOOD", issues=None, files=10, completed_at="2026-09-15T10:00:00"):
    return {
        "scan": {"completed_at": completed_at},
        "health": {"score": score, "status": status},
        "issues": issues or [],
        "library": {"files": files},
    }


class TestAppendScoreHistory:
    def test_creates_file_with_one_line(self, tmp_path):
        p = tmp_path / "history.jsonl"
        append_score_history(_report(), path=p)

        assert p.exists()
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_entry_contains_expected_fields(self, tmp_path):
        p = tmp_path / "history.jsonl"
        append_score_history(
            _report(score=77.5, status="FAIR", issues=[{"a": 1}, {"b": 2}], files=42,
                    completed_at="2026-09-15T12:30:00"),
            path=p,
        )

        entry = json.loads(p.read_text(encoding="utf-8").strip())
        assert entry == {
            "timestamp": "2026-09-15T12:30:00",
            "score": 77.5,
            "status": "FAIR",
            "total_issues": 2,
            "total_files": 42,
        }

    def test_multiple_appends_produce_multiple_lines_in_order(self, tmp_path):
        p = tmp_path / "history.jsonl"
        append_score_history(_report(score=70.0, completed_at="2026-09-01T00:00:00"), path=p)
        append_score_history(_report(score=80.0, completed_at="2026-09-02T00:00:00"), path=p)
        append_score_history(_report(score=75.0, completed_at="2026-09-03T00:00:00"), path=p)

        entries = read_score_history(path=p)
        assert [e["score"] for e in entries] == [70.0, 80.0, 75.0]

    def test_none_score_is_stored_as_none_not_zero(self, tmp_path):
        """UNSCORED-Reports (z.B. 0 Dateien) liefern score=None - kein
        kuenstlicher 0-Wert, der als 'sehr schlecht' missverstanden
        werden koennte."""
        p = tmp_path / "history.jsonl"
        append_score_history(_report(score=None, status="UNSCORED"), path=p)

        entry = read_score_history(path=p)[0]
        assert entry["score"] is None

    def test_creates_parent_directory_if_missing(self, tmp_path):
        p = tmp_path / "nested" / "dir" / "history.jsonl"
        append_score_history(_report(), path=p)
        assert p.exists()


class TestReadScoreHistory:
    def test_missing_file_returns_empty_list(self, tmp_path):
        assert read_score_history(path=tmp_path / "does_not_exist.jsonl") == []

    def test_chronological_order_preserved(self, tmp_path):
        p = tmp_path / "history.jsonl"
        for i, score in enumerate([10.0, 20.0, 30.0]):
            append_score_history(
                _report(score=score, completed_at=f"2026-09-0{i+1}T00:00:00"), path=p,
            )

        entries = read_score_history(path=p)
        assert [e["timestamp"] for e in entries] == [
            "2026-09-01T00:00:00", "2026-09-02T00:00:00", "2026-09-03T00:00:00",
        ]

    def test_limit_returns_only_last_n_newest(self, tmp_path):
        p = tmp_path / "history.jsonl"
        for i in range(5):
            append_score_history(_report(score=float(i)), path=p)

        entries = read_score_history(path=p, limit=2)
        assert [e["score"] for e in entries] == [3.0, 4.0]

    def test_corrupt_line_is_skipped_not_fatal(self, tmp_path):
        p = tmp_path / "history.jsonl"
        append_score_history(_report(score=1.0), path=p)
        with open(p, "a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        append_score_history(_report(score=2.0), path=p)

        entries = read_score_history(path=p)
        assert [e["score"] for e in entries] == [1.0, 2.0]

    def test_blank_lines_are_skipped(self, tmp_path):
        p = tmp_path / "history.jsonl"
        p.write_text("\n\n", encoding="utf-8")
        append_score_history(_report(score=5.0), path=p)

        entries = read_score_history(path=p)
        assert [e["score"] for e in entries] == [5.0]
