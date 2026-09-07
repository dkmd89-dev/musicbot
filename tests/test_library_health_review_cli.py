# tests/test_library_health_review_cli.py
# -*- coding: utf-8 -*-
"""scripts/library_health_review.py — dünne interaktive CLI über
FindingsRegistry (Aufgabe 'Persistentes Findings-Review-System',
Abschnitt 10/11/25)."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.library_health_review as review_cli  # noqa: E402
from services.library_health.findings import (  # noqa: E402
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    FindingsRegistry,
    generate_finding_id,
)


def _issue(code, severity="WARNING", scope="album", **kwargs):
    base = {
        "issue_code": code, "severity": severity, "scope": scope, "path": None,
        "artist": None, "album": None, "title": None, "message": f"msg {code}",
        "details": {}, "confidence": None, "related_files": [],
    }
    base.update(kwargs)
    return base


@pytest.fixture
def registry_with_two_open_findings(tmp_path):
    path = tmp_path / "findings.json"
    registry = FindingsRegistry(path)
    issue_a = _issue("ALBUM_TRACK_GAP", artist="Artist A", album="Album A")
    issue_b = _issue("ARTWORK_MISSING", scope="file", path="Artist B/Album B/01.m4a")
    registry.merge_scan_issues([issue_a, issue_b], scanned_at="2026-01-01T00:00:00Z")
    registry.save()
    return path, issue_a, issue_b


class TestReviewCliResolveAndFalsePositive:
    def test_resolve_and_false_positive_are_persisted(
        self, registry_with_two_open_findings, monkeypatch, capsys
    ):
        path, issue_a, issue_b = registry_with_two_open_findings
        answers = iter(["r", "Album A wurde korrigiert", "f", "Absichtlich so"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        exit_code = review_cli.main(["--registry", str(path), "--reviewer", "unit-test"])
        assert exit_code == 0

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        fid_b = generate_finding_id(issue_b)
        assert registry.get(fid_a).status == STATUS_RESOLVED
        assert registry.get(fid_a).review_note == "Album A wurde korrigiert"
        assert registry.get(fid_a).reviewed_by == "unit-test"
        assert registry.get(fid_b).status == STATUS_FALSE_POSITIVE
        assert registry.get(fid_b).review_note == "Absichtlich so"

        out = capsys.readouterr().out
        assert "2 offene(r) Befund(e)" in out
        assert "Fertig. 2 von 2 Befund(en) bewertet." in out

    def test_skip_leaves_finding_open(self, registry_with_two_open_findings, monkeypatch):
        path, issue_a, issue_b = registry_with_two_open_findings
        answers = iter(["s", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).status == STATUS_OPEN

    def test_quit_stops_early_but_keeps_prior_reviews(
        self, registry_with_two_open_findings, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_open_findings
        answers = iter(["r", "erledigt", "q"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        fid_b = generate_finding_id(issue_b)
        assert registry.get(fid_a).status == STATUS_RESOLVED
        assert registry.get(fid_b).status == STATUS_OPEN

    def test_empty_note_is_stored_as_none(self, registry_with_two_open_findings, monkeypatch):
        path, issue_a, issue_b = registry_with_two_open_findings
        answers = iter(["r", "", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).review_note is None


class TestReviewCliNoOpenFindings:
    def test_no_open_findings_prints_message_and_exits_zero(self, tmp_path, capsys):
        path = tmp_path / "findings.json"
        FindingsRegistry(path).save()

        exit_code = review_cli.main(["--registry", str(path)])
        assert exit_code == 0
        assert "Keine offenen Befunde" in capsys.readouterr().out


class TestReviewCliCorruptRegistry:
    def test_corrupt_registry_reported_and_not_overwritten(self, tmp_path, capsys):
        path = tmp_path / "findings.json"
        path.write_text("{not valid json", encoding="utf-8")

        exit_code = review_cli.main(["--registry", str(path)])
        assert exit_code == 2
        assert path.read_text(encoding="utf-8") == "{not valid json"


class TestReviewCliDefaultReviewer:
    def test_default_reviewer_is_cli_prefixed(self, registry_with_two_open_findings, monkeypatch):
        path, issue_a, _ = registry_with_two_open_findings
        answers = iter(["r", "note", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        monkeypatch.setattr("getpass.getuser", lambda: "robin")

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).reviewed_by == "cli:robin"
