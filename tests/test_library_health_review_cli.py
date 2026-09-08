# tests/test_library_health_review_cli.py
# -*- coding: utf-8 -*-
"""scripts/library_health_review.py — kategoriebasierte interaktive CLI
über FindingsRegistry (Aufgabe 'Library Health Review', Abschnitt 3-14)."""

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
def registry_with_two_categories(tmp_path):
    """ALBUM_TRACK_GAP (WARNING, 1 Finding) und ARTWORK_MISSING (WARNING,
    1 Finding) - zwei getrennte Kategorien, je ein Finding, damit
    Kategorie-Reihenfolge deterministisch alphabetisch ist
    (ALBUM_TRACK_GAP < ARTWORK_MISSING)."""
    path = tmp_path / "findings.json"
    registry = FindingsRegistry(path)
    issue_a = _issue("ALBUM_TRACK_GAP", artist="Artist A", album="Album A")
    issue_b = _issue("ARTWORK_MISSING", scope="file", path="Artist B/Album B/01.m4a")
    registry.merge_scan_issues([issue_a, issue_b], scanned_at="2026-01-01T00:00:00Z")
    registry.save()
    return path, issue_a, issue_b


@pytest.fixture
def registry_with_large_category(tmp_path):
    path = tmp_path / "findings.json"
    registry = FindingsRegistry(path)
    issues = [
        _issue("META_ISRC_MISSING", "INFO", scope="file", path=f"f{i}.m4a")
        for i in range(300)
    ]
    registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
    registry.save()
    return path, issues


class TestCategoryGrouping:
    def test_categories_shown_with_open_count(
        self, registry_with_two_categories, monkeypatch, capsys
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["s", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        out = capsys.readouterr().out
        assert "ALBUM_TRACK_GAP (1 Befund(e))" in out
        assert "ARTWORK_MISSING (1 Befund(e))" in out
        assert "2 offene(r) Befund(e) in 2 Kategorie(n)" in out

    def test_resolved_and_false_positive_findings_never_offered_again(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        registry = FindingsRegistry(path)
        registry.review_finding(generate_finding_id(issue_a), STATUS_RESOLVED)
        registry.review_finding(generate_finding_id(issue_b), STATUS_FALSE_POSITIVE)
        registry.save()

        called = {"count": 0}

        def _fail_if_called(*_):
            called["count"] += 1
            return "s"

        monkeypatch.setattr("builtins.input", _fail_if_called)
        exit_code = review_cli.main(["--registry", str(path)])
        assert exit_code == 0
        assert called["count"] == 0  # keine Kategorie mehr zu bearbeiten


class TestCategoryActionY:
    def test_y_resolves_single_finding_in_category(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        # Kategorie 1 (ALBUM_TRACK_GAP): Y -> R -> Notiz; Kategorie 2: S
        answers = iter(["y", "r", "behoben", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).status == STATUS_RESOLVED
        assert registry.get(fid_a).review_note == "behoben"

    def test_y_false_positive_for_single_finding(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "f", "absicht", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).status == STATUS_FALSE_POSITIVE

    def test_skip_within_single_review_changes_nothing(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "s", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).status == STATUS_OPEN

    def test_quit_within_single_review_ends_entire_session(
        self, registry_with_two_categories, monkeypatch
    ):
        """Q im Einzelreview beendet den GESAMTEN Review, nicht nur die
        aktuelle Kategorie - die zweite Kategorie darf nicht mehr
        abgefragt werden."""
        path, issue_a, issue_b = registry_with_two_categories
        prompts = []

        def _record(prompt=""):
            prompts.append(prompt)
            if len(prompts) == 1:
                return "y"
            if len(prompts) == 2:
                return "q"
            raise AssertionError("Nach Q darf keine weitere Eingabe angefragt werden")

        monkeypatch.setattr("builtins.input", _record)

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_b = generate_finding_id(issue_b)
        assert registry.get(fid_b).status == STATUS_OPEN


class TestCategoryActionFBatch:
    def test_batch_false_positive_requires_confirmation(
        self, registry_with_large_category, monkeypatch, capsys
    ):
        path, issues = registry_with_large_category
        answers = iter(["f", "n"])  # F waehlen, dann Bestaetigung ABLEHNEN
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        for issue in issues:
            assert registry.get(generate_finding_id(issue)).status == STATUS_OPEN
        assert "ACHTUNG" in capsys.readouterr().out

    def test_batch_false_positive_confirmed_marks_all_open(
        self, registry_with_large_category, monkeypatch, capsys
    ):
        path, issues = registry_with_large_category
        answers = iter(["f", "y"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        for issue in issues:
            assert registry.get(generate_finding_id(issue)).status == STATUS_FALSE_POSITIVE
        out = capsys.readouterr().out
        assert "300 Findings als FALSE_POSITIVE markiert" in out

    def test_batch_confirmation_negative_does_not_touch_registry_file(
        self, registry_with_large_category, monkeypatch
    ):
        path, issues = registry_with_large_category
        before = path.read_text(encoding="utf-8")
        answers = iter(["f", "n"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        assert path.read_text(encoding="utf-8") == before

    def test_batch_only_affects_currently_open_findings_of_that_category(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        already_resolved = _issue("ARTWORK_MISSING", scope="file", path="a.m4a")
        still_open = _issue("ARTWORK_MISSING", scope="file", path="b.m4a")
        registry.merge_scan_issues(
            [already_resolved, still_open], scanned_at="2026-01-01T00:00:00Z"
        )
        registry.review_finding(generate_finding_id(already_resolved), STATUS_RESOLVED)
        registry.save()

        answers = iter(["f", "y"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        review_cli.main(["--registry", str(path)])

        reloaded = FindingsRegistry(path)
        assert reloaded.get(generate_finding_id(already_resolved)).status == STATUS_RESOLVED
        assert reloaded.get(generate_finding_id(still_open)).status == STATUS_FALSE_POSITIVE


class TestCategoryActionSkip:
    def test_skip_category_changes_nothing_and_moves_on(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["s", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        assert registry.get(generate_finding_id(issue_a)).status == STATUS_OPEN
        assert registry.get(generate_finding_id(issue_b)).status == STATUS_OPEN
        assert len(registry.get_open_findings()) == 2


class TestMixedStatusAndMultipleCategories:
    def test_mixed_resolve_batch_and_skip_across_categories(self, tmp_path, monkeypatch):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issue_gap = _issue("ALBUM_TRACK_GAP", artist="A", album="B")
        issue_artwork = [
            _issue("ARTWORK_MISSING", scope="file", path=f"f{i}.m4a") for i in range(3)
        ]
        issue_lyrics = _issue("LYRICS_EMPTY", scope="file", path="l.m4a")
        registry.merge_scan_issues(
            [issue_gap, *issue_artwork, issue_lyrics], scanned_at="2026-01-01T00:00:00Z"
        )
        registry.save()

        # Reihenfolge alphabetisch: ALBUM_TRACK_GAP, ARTWORK_MISSING, LYRICS_EMPTY
        answers = iter(["y", "r", "", "f", "y", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        reloaded = FindingsRegistry(path)
        assert reloaded.get(generate_finding_id(issue_gap)).status == STATUS_RESOLVED
        for issue in issue_artwork:
            assert reloaded.get(generate_finding_id(issue)).status == STATUS_FALSE_POSITIVE
        assert reloaded.get(generate_finding_id(issue_lyrics)).status == STATUS_OPEN


class TestReviewCliSummary:
    def test_summary_reports_dynamic_counts(
        self, registry_with_two_categories, monkeypatch, capsys
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "r", "", "y", "f", ""])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        out = capsys.readouterr().out
        assert "Bearbeitet:      2" in out
        assert "Resolved:        1" in out
        assert "False Positive:  1" in out
        assert "Skipped:         0" in out
        assert "Offene Findings: 0" in out


class TestReviewCliHealthScoreUnaffected:
    def test_review_actions_never_touch_health_report(
        self, registry_with_two_categories, monkeypatch
    ):
        """Die Findings-Registry kennt keinen Score-Begriff - Review kann
        ihn technisch nicht beeinflussen (siehe auch
        tests/test_library_health_findings.py::TestReviewDoesNotTouchHealthScore)."""
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "r", "", "y", "f", ""])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        review_cli.main(["--registry", str(path)])

        from services.library_health.findings import Finding

        assert "score" not in [f.name for f in Finding.__dataclass_fields__.values()]


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
    def test_default_reviewer_is_cli_prefixed(
        self, registry_with_two_categories, monkeypatch
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "r", "note", "s"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        monkeypatch.setattr("getpass.getuser", lambda: "robin")

        review_cli.main(["--registry", str(path)])

        registry = FindingsRegistry(path)
        fid_a = generate_finding_id(issue_a)
        assert registry.get(fid_a).reviewed_by == "cli:robin"


class TestReviewCliUnicode:
    def test_unicode_artist_album_title_displayed_and_persisted(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issue = _issue(
            "ALBUM_TRACK_GAP", artist="Björk Ähnlichkeitsklub",
            album="Ünïcödé Ålbüm 🎵",
        )
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        registry.save()

        answers = iter(["y", "r", "Ätzende Notiz mit Umlauten äöü"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        review_cli.main(["--registry", str(path)])

        out = capsys.readouterr().out
        assert "Björk Ähnlichkeitsklub" in out
        assert "Ünïcödé Ålbüm 🎵" in out

        reloaded = FindingsRegistry(path)
        finding = reloaded.get(generate_finding_id(issue))
        assert finding.status == STATUS_RESOLVED
        assert finding.review_note == "Ätzende Notiz mit Umlauten äöü"


class TestReviewCliRepetition:
    def test_running_review_twice_does_not_reoffer_resolved_findings(
        self, registry_with_two_categories, monkeypatch, capsys
    ):
        path, issue_a, issue_b = registry_with_two_categories
        answers = iter(["y", "r", "", "y", "f", ""])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        review_cli.main(["--registry", str(path)])

        # Zweiter Lauf: keine offenen Findings mehr, keine Eingabe noetig.
        def _fail(*_):
            raise AssertionError("Keine Eingabe erwartet - keine offenen Befunde mehr")

        monkeypatch.setattr("builtins.input", _fail)
        exit_code = review_cli.main(["--registry", str(path)])
        assert exit_code == 0
        assert "Keine offenen Befunde" in capsys.readouterr().out
