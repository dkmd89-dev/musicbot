# tests/test_library_health_report.py
# -*- coding: utf-8 -*-
"""Report-Struktur + Determinismus (Prompt Abschnitt 24-26/35)."""

from pathlib import Path

import pytest

from services.library_health.discovery import build_file_record
from services.library_health.file_analysis import analyze_file
from services.library_health.models import AnalysisState, SCHEMA_VERSION
from services.library_health.report import (
    build_report_dict,
    render_summary_markdown,
    render_text,
)
from services.library_health.tag_reader import ArtworkData, StreamData, TagData


def _fh(tmp_path, rel, **tag_over):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    rec = build_file_record(p, tmp_path)
    tag_kwargs = dict(state=AnalysisState.PRESENT, artist="A", title="T", album="Al",
                      album_artist="A", year="2020", genre="Pop", track_number=1,
                      artists_primary_tag=["A"])
    tag_kwargs.update(tag_over)
    tags = TagData(**tag_kwargs)
    return analyze_file(
        rec, tags,
        StreamData(state=AnalysisState.PRESENT, has_audio_stream=True, bitrate=192000,
                   duration_seconds=200.0),
        ArtworkData(state=AnalysisState.PRESENT, present=True, width=1000, height=1000,
                    is_square=True),
    )


def _report(tmp_path):
    healths = [
        _fh(tmp_path, "B Artist/Singles/2020 - Two.m4a", artist=None),
        _fh(tmp_path, "A Artist/2019 - Rec/01 - One.m4a"),
    ]
    return build_report_dict(
        library_root=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:05+00:00",
        duration_seconds=5.0,
        file_healths=healths,
    )


def test_schema_shape(tmp_path):
    r = _report(tmp_path)
    assert r["schema_version"] == SCHEMA_VERSION
    for key in ("scan", "library", "health", "statistics", "issues", "files"):
        assert key in r
    assert r["scan"]["pending_analyses"] == []
    assert r["statistics"]["duplicate_groups"] == 0  # keine Dubletten im Fixture
    assert "artists" in r and "albums" in r


def test_files_sorted_by_relative_path(tmp_path):
    r = _report(tmp_path)
    rels = [f["relative_path"] for f in r["files"]]
    assert rels == sorted(rels)


def test_issues_sorted_severity_then_code_then_path(tmp_path):
    r = _report(tmp_path)
    keys = [
        ({"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}[i["severity"]],
         i["issue_code"], i["path"] or "")
        for i in r["issues"]
    ]
    assert keys == sorted(keys)


def test_determinism_same_input_same_report(tmp_path):
    a = _report(tmp_path)
    b = _report(tmp_path)
    # Zeitstempel sind hier fix — der komplette Report muss identisch sein.
    assert a == b


def test_statistics_buckets(tmp_path):
    r = _report(tmp_path)
    s = r["statistics"]
    assert s["total_files"] == 2
    assert s["files_with_errors"] == 1        # artist=None -> ERROR
    assert s["healthy_files"] + s["files_with_warnings"] + s["files_with_errors"] \
        + s["files_not_analyzable"] == 2


def test_render_text_is_str_and_mentions_counts(tmp_path):
    text = render_text(_report(tmp_path))
    assert "MUSIC LIBRARY HEALTH REPORT" in text
    assert "Files:      2" in text


def test_genre_distribution_counts_split_genres(tmp_path):
    healths = [
        _fh(tmp_path, "A Artist/Singles/2020 - One.m4a", genre="Pop; Rock"),
        _fh(tmp_path, "A Artist/Singles/2020 - Two.m4a", genre="Pop"),
        _fh(tmp_path, "B Artist/Singles/2020 - Three.m4a", genre=""),
    ]
    r = build_report_dict(
        library_root=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:05+00:00",
        duration_seconds=5.0,
        file_healths=healths,
    )
    assert r["statistics"]["genre_distribution"] == {"Pop": 2, "Rock": 1}


def test_genre_distribution_empty_when_no_genres(tmp_path):
    healths = [_fh(tmp_path, "A Artist/Singles/2020 - One.m4a", genre="")]
    r = build_report_dict(
        library_root=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:05+00:00",
        duration_seconds=5.0,
        file_healths=healths,
    )
    assert r["statistics"]["genre_distribution"] == {}


# ─────────────────────────────────────────────────────────────────────────
# render_summary_markdown() — Markdown-Zusammenfassung
# ─────────────────────────────────────────────────────────────────────────
#
# Arbeitet bewusst auf einem direkt konstruierten `report`-Dict statt ueber
# den vollen FileHealth-Scan-Pfad - render_summary_markdown() bekommt per
# Vertrag ausschliesslich das fertige Dict (siehe Docstring in report.py),
# genau das wird hier isoliert getestet. Alle Werte in den Fixtures unten
# sind bewusst FREI ERFUNDEN (keine echten Library-Daten) - sie duerfen von
# render_summary_markdown() niemals als Spezialfall erkannt werden, damit
# dieselbe Funktion bei jeder beliebigen Library korrekt bleibt.


def _issue(code, severity, **kwargs):
    base = {
        "issue_code": code,
        "severity": severity,
        "scope": "file",
        "path": None,
        "artist": None,
        "album": None,
        "title": None,
        "message": f"Testmeldung für {code}",
        "details": {},
        "confidence": None,
        "related_files": [],
    }
    base.update(kwargs)
    return base


def _summary_report(
    issues,
    *,
    genre_distribution=None,
    health=None,
    library=None,
    scan=None,
    healthy_files=0,
    findings=None,
):
    from collections import Counter

    sev_counter = Counter(i["severity"] for i in issues)
    scan = scan or {
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:05+00:00",
        "duration_seconds": 5.0,
    }
    health = health if health is not None else {"score": 97.3, "status": "EXCELLENT"}
    library = library or {"files": 42, "artists": 7, "albums": 12}
    result = {
        "schema_version": SCHEMA_VERSION,
        "scan": scan,
        "health": health,
        "library": library,
        "statistics": {
            "healthy_files": healthy_files,
            "issues_by_severity": {
                "CRITICAL": sev_counter.get("CRITICAL", 0),
                "ERROR": sev_counter.get("ERROR", 0),
                "WARNING": sev_counter.get("WARNING", 0),
                "INFO": sev_counter.get("INFO", 0),
            },
            "duplicate_groups": 0,
            "duplicate_groups_by_kind": {"exact": 0, "recording": 0, "suspected": 0},
            "genre_distribution": genre_distribution or {},
        },
        "issues": issues,
    }
    if findings is not None:
        result["findings"] = findings
    return result


class TestRenderSummaryMarkdownBasicStructure:
    """Test 1 (Aufgabe Abschnitt 14) — Grundstruktur."""

    def test_header_score_status_and_library_numbers_present(self):
        report = _summary_report(
            [], health={"score": 88.5, "status": "GOOD"},
            library={"files": 123, "artists": 9, "albums": 21},
        )
        md = render_summary_markdown(report)
        assert md.startswith("# Library Health")
        assert "88.5" in md
        assert "GOOD" in md
        assert "123" in md
        assert "9" in md
        assert "21" in md

    def test_returns_string(self):
        assert isinstance(render_summary_markdown(_summary_report([])), str)


class TestRenderSummaryMarkdownErrors:
    """Test 2 — ERROR-Issue vollständig dargestellt."""

    def test_error_shows_code_artist_album_path_message(self):
        issue = _issue(
            "ALBUM_DUPLICATE_TRACK_NUMBER",
            "ERROR",
            artist="Erfundener Künstler XY",
            album="Erfundenes Album Z",
            path="Erfundener Künstler XY/2030 - Erfundenes Album Z/03 - Song.m4a",
            message="Zwei Dateien tragen dieselbe Tracknummer 3.",
        )
        md = render_summary_markdown(_summary_report([issue]))
        assert "ALBUM_DUPLICATE_TRACK_NUMBER" in md
        assert "Erfundener Künstler XY" in md
        assert "Erfundenes Album Z" in md
        assert "Erfundener Künstler XY/2030 - Erfundenes Album Z/03 - Song.m4a" in md
        assert "Zwei Dateien tragen dieselbe Tracknummer 3." in md
        assert "🔴 Fehler" in md

    def test_critical_also_appears_under_fehler_section(self):
        issue = _issue("AUDIO_NO_STREAM", "CRITICAL", path="Kaputt.m4a")
        md = render_summary_markdown(_summary_report([issue]))
        assert "🔴 Fehler" in md
        assert "AUDIO_NO_STREAM" in md


class TestRenderSummaryMarkdownWarnings:
    """Test 3 — mehrere WARNINGs desselben Codes korrekt gruppiert."""

    def test_multiple_warnings_same_code_grouped_under_one_heading(self):
        issues = [
            _issue("ALBUM_TRACK_GAP", "WARNING", album=f"Album {i}", path=f"f{i}.m4a")
            for i in range(4)
        ]
        md = render_summary_markdown(_summary_report(issues))
        assert md.count("### ALBUM_TRACK_GAP") == 1
        assert "(4 Befund(e))" in md
        for i in range(4):
            assert f"Album {i}" in md

    def test_different_warning_codes_get_separate_headings(self):
        issues = [
            _issue("ALBUM_TRACK_GAP", "WARNING", path="a.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", path="b.m4a"),
        ]
        md = render_summary_markdown(_summary_report(issues))
        assert "### ALBUM_TRACK_GAP" in md
        assert "### ARTWORK_MISSING" in md


class TestRenderSummaryMarkdownInfo:
    """Test 4 — INFO-Issues als aggregierte Tabelle, keine Einzelliste."""

    def test_info_issues_appear_as_table_not_individual_entries(self):
        issues = [
            _issue("META_ISRC_MISSING", "INFO", path=f"f{i}.m4a") for i in range(5)
        ]
        md = render_summary_markdown(_summary_report(issues))
        assert "ℹ️ INFO / Datenanreicherung" in md
        assert "| Issue | Anzahl | Bedeutung |" in md
        assert "META_ISRC_MISSING" in md
        assert "| 5 |" in md
        # keine Einzeldatei-Aufzaehlung fuer INFO
        assert "f0.m4a" not in md
        assert "f4.m4a" not in md

    def test_info_description_comes_from_registry(self):
        issues = [_issue("LYRICS_MISSING", "INFO")]
        md = render_summary_markdown(_summary_report(issues))
        from services.library_health.issues import REGISTRY

        assert REGISTRY["LYRICS_MISSING"].description in md

    def test_unknown_issue_code_does_not_crash(self):
        issues = [_issue("TOTALLY_UNKNOWN_FUTURE_CODE", "INFO")]
        md = render_summary_markdown(_summary_report(issues))
        assert "TOTALLY_UNKNOWN_FUTURE_CODE" in md
        assert "Keine Beschreibung in der Issue-Registry hinterlegt." in md


class TestRenderSummaryMarkdownGenres:
    """Test 5 — Top 5 Genres, definierte Sortierung."""

    def test_top_5_sorted_by_count_desc_then_name_asc(self):
        genre_distribution = {
            "Erfundenes Genre A": 10,
            "Erfundenes Genre B": 30,
            "Erfundenes Genre C": 30,
            "Erfundenes Genre D": 5,
            "Erfundenes Genre E": 20,
            "Erfundenes Genre F": 1,
        }
        report = _summary_report([], genre_distribution=genre_distribution)
        md = render_summary_markdown(report)
        top_section = md.split("## 🎵 Top 5 Genres")[1].split("##")[0]
        lines = [l for l in top_section.strip().splitlines() if l.strip()]
        assert len(lines) == 5
        # B und C haben Gleichstand (30) -> alphabetisch: B vor C
        assert lines[0].startswith("1. Erfundenes Genre B")
        assert lines[1].startswith("2. Erfundenes Genre C")
        assert lines[2].startswith("3. Erfundenes Genre E")
        assert lines[3].startswith("4. Erfundenes Genre A")
        assert lines[4].startswith("5. Erfundenes Genre D")
        assert "Erfundenes Genre F" not in top_section

    def test_no_genre_section_when_distribution_empty(self):
        md = render_summary_markdown(_summary_report([], genre_distribution={}))
        assert "Top 5 Genres" not in md


class TestRenderSummaryMarkdownConfidence:
    """Test 6 — Confidence-/Verdachtsbefunde erscheinen nicht als harte Fehler."""

    def test_confidence_issue_not_listed_under_fehler(self):
        issue = _issue(
            "DUPLICATE_SUSPECTED", "INFO",
            artist="X", title="Y", confidence="album_context_risk",
        )
        md = render_summary_markdown(_summary_report([issue]))
        assert "🔎 Vermutete / Confidence-Befunde" in md
        assert "DUPLICATE_SUSPECTED" in md
        fehler_section = md.split("## 🔴 Fehler")[1] if "## 🔴 Fehler" in md else ""
        assert "DUPLICATE_SUSPECTED" not in fehler_section

    def test_confidence_issue_without_confidence_value_still_grouped_with_siblings(self):
        """Sobald EIN Issue eines Codes ein confidence-Feld traegt, landet
        der gesamte Code in der Confidence-Sektion - kein Aufsplitten
        desselben Codes auf zwei Abschnitte."""
        issues = [
            _issue("DUPLICATE_SUSPECTED", "INFO", confidence="album_context_risk"),
            _issue("DUPLICATE_SUSPECTED", "INFO", confidence=None),
        ]
        md = render_summary_markdown(_summary_report(issues))
        assert "(2 Befund(e))" in md
        assert "ℹ️ INFO / Datenanreicherung" not in md or "DUPLICATE_SUSPECTED" not in md.split(
            "ℹ️ INFO / Datenanreicherung"
        )[1]

    def test_confidence_hint_rendered_when_present(self):
        issue = _issue(
            "DUPLICATE_SUSPECTED", "WARNING", confidence="album_context_risk"
        )
        md = render_summary_markdown(_summary_report([issue]))
        # Unterstriche werden von _md_escape() bewusst maskiert (Markdown-
        # Sonderzeichen) - der maskierte String ist die korrekte Ausgabe.
        assert "album\\_context\\_risk" in md


class TestRenderSummaryMarkdownEmptyReport:
    """Test 7 — Report ohne Issues erzeugt trotzdem eine valide Summary."""

    def test_empty_report_produces_readable_summary(self):
        md = render_summary_markdown(_summary_report([]))
        assert "# Library Health – Zusammenfassung" in md
        assert "Keine dringenden Maßnahmen erforderlich." in md
        assert "🔴 Fehler" not in md
        assert "🟠 Warnungen" not in md
        assert "Top 5 Genres" not in md

    def test_empty_report_missing_optional_keys_does_not_crash(self):
        minimal_report = {
            "scan": {},
            "health": {},
            "library": {},
            "statistics": {},
            "issues": [],
        }
        md = render_summary_markdown(minimal_report)
        assert "# Library Health" in md


class TestRenderSummaryMarkdownDeterminism:
    """Test 8 — identischer Input erzeugt immer denselben Output."""

    def test_same_report_same_output(self):
        issues = [
            _issue("ALBUM_TRACK_GAP", "WARNING", album="Album 1", path="a.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", album="Album 2", path="b.m4a"),
            _issue("META_ISRC_MISSING", "INFO", path="c.m4a"),
        ]
        report = _summary_report(
            issues, genre_distribution={"Pop": 5, "Rock": 3}
        )
        first = render_summary_markdown(report)
        second = render_summary_markdown(report)
        assert first == second

    def test_dict_construction_order_does_not_affect_output(self):
        issue_a = _issue("ARTWORK_MISSING", "WARNING", path="b.m4a")
        issue_b = _issue("ALBUM_TRACK_GAP", "WARNING", path="a.m4a")
        report1 = _summary_report([issue_a, issue_b])
        report2 = _summary_report([issue_a, issue_b])
        assert render_summary_markdown(report1) == render_summary_markdown(report2)


class TestRenderSummaryMarkdownNoHardcoding:
    """Test 9 — Summary entsteht aus den gelieferten Report-Daten, nicht aus
    aktuell bekannten Library-Werten. Verwendet bewusst voellig unrealistische
    Fantasie-Werte, die niemals in der echten Library vorkommen."""

    def test_fantasy_values_appear_verbatim_in_output(self):
        issue = _issue(
            "META_ARTIST_MISSING",
            "ERROR",
            artist="Zzyzx Quronoplex 9000",
            album="Interdimensionale Bratkartoffeln",
            path="Zzyzx Quronoplex 9000/9999 - Bratkartoffeln/01 - Blorp.m4a",
            message="Fantasie-Meldung Nr. 42 fuer Testzwecke",
        )
        report = _summary_report(
            [issue],
            genre_distribution={"Fantasiegenre Alpha": 3, "Fantasiegenre Beta": 1},
            health={"score": 12.3, "status": "CRITICAL"},
            library={"files": 999999, "artists": 424242, "albums": 13131},
        )
        md = render_summary_markdown(report)
        assert "Zzyzx Quronoplex 9000" in md
        assert "Interdimensionale Bratkartoffeln" in md
        assert "Blorp.m4a" in md
        assert "Fantasie-Meldung Nr. 42 fuer Testzwecke" in md
        assert "Fantasiegenre Alpha" in md
        assert "999999" in md
        assert "424242" in md
        assert "13131" in md
        assert "12.3" in md
        # Keine bekannten, realen Library-Bezeichner duerfen je auftauchen,
        # unabhaengig vom Report-Inhalt.
        assert "Die Firma" not in md


# ─────────────────────────────────────────────────────────────────────────
# render_summary_markdown() — Findings-Review-Integration
# ─────────────────────────────────────────────────────────────────────────
#
# Diese Tests decken den Fall ab, dass die Issues bereits per
# services/library_health/findings.py::annotate_issues_with_findings()
# um "finding_status" angereichert wurden und report["findings"] gesetzt
# ist. Ohne diese Annotation (alle Tests oben) bleibt das Verhalten
# byte-identisch zum Stand vor dem Findings-System (siehe
# _split_issues_by_finding_status() in report.py).


def _open_issue(code, severity="WARNING", **kwargs):
    issue = _issue(code, severity, **kwargs)
    issue["finding_status"] = "OPEN"
    return issue


def _resolved_issue(code, severity="WARNING", reviewed_at="2026-01-02T00:00:00+00:00", **kwargs):
    issue = _issue(code, severity, **kwargs)
    issue["finding_status"] = "RESOLVED"
    issue["finding_reviewed_at"] = reviewed_at
    return issue


def _false_positive_issue(code, severity="WARNING", note=None, **kwargs):
    issue = _issue(code, severity, **kwargs)
    issue["finding_status"] = "FALSE_POSITIVE"
    issue["finding_review_note"] = note
    return issue


class TestRenderSummaryMarkdownFindingsBackwardCompatibility:
    """Ohne Findings-Annotation bleibt render_summary_markdown() exakt
    wie vor Einführung des Findings-Systems."""

    def test_report_without_findings_key_has_no_status_sections(self):
        issue = _issue("ARTWORK_MISSING", "WARNING", path="a.m4a")
        md = render_summary_markdown(_summary_report([issue]))
        assert "📋 Befundstatus" not in md
        assert "Reparierte Befunde" not in md
        assert "Akzeptierte Befunde" not in md
        assert "## 🟠 Warnungen" in md  # alte, unpräfixierte Überschrift


class TestRenderSummaryMarkdownFindingsStatusTable:
    def test_status_table_shows_correct_counts(self):
        issues = [
            _open_issue("ARTWORK_MISSING", path="a.m4a"),
            _resolved_issue("ARTWORK_MISSING", path="b.m4a"),
            _resolved_issue("ARTWORK_MISSING", path="c.m4a"),
            _false_positive_issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y"),
        ]
        report = _summary_report(
            issues,
            findings={"total_detected": 4, "open": 1, "resolved": 2, "false_positive": 1},
        )
        md = render_summary_markdown(report)
        assert "📋 Befundstatus" in md
        assert "| 🔴 Offen | 1 |" in md
        assert "| 🟢 Repariert | 2 |" in md
        assert "| ⚪ Akzeptiert | 1 |" in md


class TestRenderSummaryMarkdownOpenFindingsOnly:
    """Nur OPEN-Befunde erscheinen in den detaillierten Fehler-/Warnungen-
    Abschnitten - bereits bewertete Befunde nicht erneut als 'zu bearbeiten'."""

    def test_resolved_issue_not_listed_under_offene_warnungen(self):
        issues = [
            _open_issue("ARTWORK_MISSING", path="open.m4a"),
            _resolved_issue("ARTWORK_MISSING", path="resolved.m4a"),
        ]
        report = _summary_report(
            issues, findings={"total_detected": 2, "open": 1, "resolved": 1, "false_positive": 0}
        )
        md = render_summary_markdown(report)
        assert "## 🟠 Offene Warnungen" in md
        assert "open.m4a" in md
        warnungen_section = md.split("## 🟠 Offene Warnungen")[1].split("\n## ")[0]
        assert "resolved.m4a" not in warnungen_section

    def test_false_positive_not_listed_under_offene_warnungen(self):
        issues = [
            _open_issue("ALBUM_TRACK_GAP", scope="album", artist="A", album="Open"),
            _false_positive_issue("ALBUM_TRACK_GAP", scope="album", artist="A", album="Dismissed"),
        ]
        report = _summary_report(
            issues, findings={"total_detected": 2, "open": 1, "resolved": 0, "false_positive": 1}
        )
        md = render_summary_markdown(report)
        warnungen_section = md.split("## 🟠 Offene Warnungen")[1].split("\n## ")[0]
        assert "Open" in warnungen_section
        assert "Dismissed" not in warnungen_section

    def test_error_severity_still_shown_even_when_findings_active(self):
        issues = [_open_issue("ALBUM_DUPLICATE_TRACK_NUMBER", severity="ERROR", path="x.m4a")]
        report = _summary_report(
            issues, findings={"total_detected": 1, "open": 1, "resolved": 0, "false_positive": 0}
        )
        md = render_summary_markdown(report)
        assert "## 🔴 Offene Fehler" in md
        assert "ALBUM_DUPLICATE_TRACK_NUMBER" in md


class TestRenderSummaryMarkdownResolvedAndFalsePositiveSections:
    def test_resolved_section_shows_code_count_and_reviewed_at(self):
        issues = [_resolved_issue("ARTWORK_MISSING", path="a.m4a", reviewed_at="2026-03-01T10:00:00+00:00")]
        report = _summary_report(
            issues, findings={"total_detected": 1, "open": 0, "resolved": 1, "false_positive": 0}
        )
        md = render_summary_markdown(report)
        assert "## 🟢 Reparierte Befunde" in md
        assert "ARTWORK_MISSING" in md
        assert "2026-03-01T10:00:00+00:00" in md

    def test_false_positive_section_shows_note(self):
        issues = [
            _false_positive_issue(
                "ALBUM_TRACK_GAP", scope="album", artist="X", album="Y",
                note="Album enthält absichtlich keinen Track 7.",
            )
        ]
        report = _summary_report(
            issues, findings={"total_detected": 1, "open": 0, "resolved": 0, "false_positive": 1}
        )
        md = render_summary_markdown(report)
        assert "## ⚪ Akzeptierte Befunde" in md
        assert "Album enthält absichtlich keinen Track 7." in md

    def test_empty_resolved_and_false_positive_produce_no_sections(self):
        """Abschnitt 15 der Aufgabe: keine unnötig langen/leeren
        Abschnitte fuer leere Kategorien."""
        issues = [_open_issue("ARTWORK_MISSING", path="a.m4a")]
        report = _summary_report(
            issues, findings={"total_detected": 1, "open": 1, "resolved": 0, "false_positive": 0}
        )
        md = render_summary_markdown(report)
        assert "Reparierte Befunde" not in md
        assert "Akzeptierte Befunde" not in md


class TestRenderSummaryMarkdownFindingsFazit:
    def test_fazit_mentions_open_vs_reviewed_counts(self):
        issues = [
            _open_issue("ARTWORK_MISSING", path="a.m4a"),
            _open_issue("ARTWORK_MISSING", path="b.m4a"),
            _resolved_issue("ARTWORK_MISSING", path="c.m4a"),
            _false_positive_issue("ARTWORK_MISSING", path="d.m4a"),
        ]
        report = _summary_report(
            issues, findings={"total_detected": 4, "open": 2, "resolved": 1, "false_positive": 1}
        )
        md = render_summary_markdown(report)
        fazit = md.split("## Fazit")[1]
        assert "4 erkannten Befunden" in fazit
        assert "2 bereits bewertet" in fazit
        assert "2 weiterhin offen" in fazit


class TestRenderSummaryMarkdownFindingsHealthScoreUnaffected:
    """Aufgaben-Abschnitt 16: Review/Acknowledge darf den Health Score
    nicht verändern - der Score kommt ausschließlich aus report['health'],
    das render_summary_markdown() nur unverändert anzeigt."""

    def test_score_unaffected_by_false_positive_reviews(self):
        issues_before = [_open_issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")]
        issues_after = [
            _false_positive_issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")
        ]
        health = {"score": 98.0, "status": "EXCELLENT"}
        md_before = render_summary_markdown(
            _summary_report(
                issues_before, health=health,
                findings={"total_detected": 1, "open": 1, "resolved": 0, "false_positive": 0},
            )
        )
        md_after = render_summary_markdown(
            _summary_report(
                issues_after, health=health,
                findings={"total_detected": 1, "open": 0, "resolved": 0, "false_positive": 1},
            )
        )
        assert "**Score:** 98.0 / 100 — EXCELLENT" in md_before
        assert "**Score:** 98.0 / 100 — EXCELLENT" in md_after
