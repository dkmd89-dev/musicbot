# tests/test_library_health_findings.py
# -*- coding: utf-8 -*-
"""Persistentes Findings-Review-System (services/library_health/findings.py)."""

import json

import pytest

from services.library_health.findings import (
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    STATUS_RESOLVED_BY_SCAN,
    Finding,
    FindingsRegistry,
    FindingsRegistryError,
    annotate_issues_with_findings,
    build_findings_summary,
    generate_finding_id,
)


def _issue(code, severity="WARNING", scope="file", **kwargs):
    base = {
        "issue_code": code,
        "severity": severity,
        "scope": scope,
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


# ─────────────────────────────────────────────────────────────────────────
# Finding-ID
# ─────────────────────────────────────────────────────────────────────────


class TestGenerateFindingId:
    def test_identical_issue_produces_identical_id(self):
        issue = _issue(
            "ALBUM_TRACK_GAP", scope="album", artist="2Pac", album="Album X"
        )
        assert generate_finding_id(issue) == generate_finding_id(dict(issue))

    def test_field_order_in_dict_does_not_affect_id(self):
        issue_a = _issue(
            "ALBUM_TRACK_GAP", scope="album", artist="2Pac", album="Album X"
        )
        # Gleiche Werte, aber ein Dict mit anderer Einfuegereihenfolge -
        # in Python 3.7+ dicts sind Insertion-Order-abhaengig fuer die
        # Iteration, generate_finding_id() darf davon nicht abhaengen.
        issue_b = dict(reversed(list(issue_a.items())))
        assert generate_finding_id(issue_a) == generate_finding_id(issue_b)

    def test_different_artist_produces_different_id(self):
        a = _issue("ALBUM_TRACK_GAP", scope="album", artist="Artist A", album="Album X")
        b = _issue("ALBUM_TRACK_GAP", scope="album", artist="Artist B", album="Album X")
        assert generate_finding_id(a) != generate_finding_id(b)

    def test_different_code_produces_different_id(self):
        a = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")
        b = _issue("ARTWORK_MISSING", scope="album", artist="X", album="Y")
        assert generate_finding_id(a) != generate_finding_id(b)

    def test_case_and_whitespace_variation_does_not_change_id(self):
        a = _issue("ALBUM_TRACK_GAP", scope="album", artist="2Pac", album="Album X")
        b = _issue("ALBUM_TRACK_GAP", scope="album", artist="  2PAC  ", album="album x")
        assert generate_finding_id(a) == generate_finding_id(b)

    def test_file_scope_prefers_artist_and_title_over_path(self):
        """Eine reine Umbenennung (z.B. durch eine spaetere Reparatur)
        darf die Identitaet nicht aendern, wenn Artist+Titel gleich
        bleiben (Aufgaben-Abschnitt 6)."""
        a = _issue(
            "ARTWORK_MISSING", scope="file", artist="X", title="Y",
            path="X/Album/01 - Y.m4a",
        )
        b = _issue(
            "ARTWORK_MISSING", scope="file", artist="X", title="Y",
            path="X/Album (Renamed)/01 - Y.m4a",
        )
        assert generate_finding_id(a) == generate_finding_id(b)

    def test_file_scope_falls_back_to_path_when_artist_or_title_missing(self):
        """META_ARTIST_MISSING hat per Definition KEINEN Artist - hier
        bleibt der Pfad die einzig verbleibende Identitaet."""
        a = _issue("META_ARTIST_MISSING", scope="file", path="Unbekannt/01.m4a")
        b = _issue("META_ARTIST_MISSING", scope="file", path="Unbekannt/02.m4a")
        assert generate_finding_id(a) != generate_finding_id(b)

    def test_album_scope_uses_artist_and_album(self):
        a = _issue("ALBUM_NAME_INCONSISTENT", scope="album", artist="X", album="Y")
        b = _issue("ALBUM_NAME_INCONSISTENT", scope="album", artist="X", album="Z")
        assert generate_finding_id(a) != generate_finding_id(b)

    def test_unicode_identity_fields_work(self):
        a = _issue(
            "ALBUM_TRACK_GAP", scope="album", artist="Café Müller", album="Öl-Ärger",
        )
        b = _issue(
            "ALBUM_TRACK_GAP", scope="album", artist="Café Müller", album="Öl-Ärger",
        )
        assert generate_finding_id(a) == generate_finding_id(b)
        assert isinstance(generate_finding_id(a), str) and len(generate_finding_id(a)) > 0

    def test_returns_string(self):
        assert isinstance(generate_finding_id(_issue("ARTWORK_MISSING")), str)


# ─────────────────────────────────────────────────────────────────────────
# Lifecycle: neues Finding, Review, Persistenz
# ─────────────────────────────────────────────────────────────────────────


class TestFindingLifecycleBasics:
    def test_new_finding_is_open(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        finding = registry.get(generate_finding_id(issue))
        assert finding.status == STATUS_OPEN
        assert finding.first_seen == "2026-01-01T00:00:00Z"
        assert finding.last_seen == "2026-01-01T00:00:00Z"
        assert finding.occurrences == 1

    def test_review_to_resolved(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_RESOLVED, note="Cover ergänzt")
        finding = registry.get(fid)
        assert finding.status == STATUS_RESOLVED
        assert finding.review_note == "Cover ergänzt"
        assert finding.resolved_at is not None

    def test_review_to_false_positive(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_FALSE_POSITIVE, note="Absichtlich")
        assert registry.get(fid).status == STATUS_FALSE_POSITIVE

    def test_review_unknown_finding_id_raises(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        with pytest.raises(KeyError):
            registry.review_finding("does-not-exist", STATUS_RESOLVED)

    def test_review_rejects_open_as_target_status(self, tmp_path):
        """OPEN ist kein gueltiges Review-Ergebnis - es ist der Default-/
        Reopen-Zustand, kein bewusst gesetztes Review-Ziel."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        with pytest.raises(ValueError):
            registry.review_finding(fid, STATUS_OPEN)

    def test_note_is_persisted(self, tmp_path):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_RESOLVED, note="Sehr spezifische Notiz 42")
        registry.save()

        reloaded = FindingsRegistry(path)
        assert reloaded.get(fid).review_note == "Sehr spezifische Notiz 42"


class TestFindingsPersistence:
    def test_save_then_reload_preserves_status(self, tmp_path):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_RESOLVED, note="ok", reviewed_by="tester")
        registry.save()

        # Simuliert einen Prozess-Neustart: komplett neue Instanz.
        reloaded = FindingsRegistry(path)
        finding = reloaded.get(fid)
        assert finding is not None
        assert finding.status == STATUS_RESOLVED
        assert finding.reviewed_by == "tester"

    def test_missing_registry_file_creates_empty_registry(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "does_not_exist.json")
        assert registry.all() == []

    def test_empty_registry_file_is_valid(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        registry = FindingsRegistry(path)
        assert registry.all() == []

    def test_corrupt_json_raises_and_does_not_overwrite(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json at all", encoding="utf-8")
        with pytest.raises(FindingsRegistryError):
            FindingsRegistry(path)
        # Datei muss unangetastet bleiben - kein stiller Reset.
        assert path.read_text(encoding="utf-8") == "{not valid json at all"

    def test_unexpected_schema_raises(self, tmp_path):
        path = tmp_path / "wrong_schema.json"
        path.write_text(json.dumps({"not_findings": []}), encoding="utf-8")
        with pytest.raises(FindingsRegistryError):
            FindingsRegistry(path)

    def test_registry_is_written_outside_provided_path_parent_untouched(self, tmp_path):
        """Reine Absicherung: save() erzeugt keine weiteren Dateien im
        selben Verzeichnis außer der Zieldatei (keine liegen gebliebenen
        .tmp-Dateien nach einem sauberen Lauf)."""
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        registry.merge_scan_issues(
            [_issue("ARTWORK_MISSING", path="a.m4a")], scanned_at="2026-01-01T00:00:00Z"
        )
        registry.save()
        files = sorted(p.name for p in tmp_path.iterdir())
        assert files == ["findings.json"]

    def test_unicode_in_all_identity_fields_round_trips(self, tmp_path):
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issue = _issue(
            "ALBUM_TRACK_GAP", scope="album",
            artist="Björk Ähnlichkeitsklub", album="Ünïcödé Ålbüm 🎵",
            message="Lücke bei Track 3 – ätzend",
        )
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        registry.save()

        reloaded = FindingsRegistry(path)
        fid = generate_finding_id(issue)
        finding = reloaded.get(fid)
        assert finding.artist == "Björk Ähnlichkeitsklub"
        assert finding.album == "Ünïcödé Ålbüm 🎵"
        assert "ätzend" in finding.message


# ─────────────────────────────────────────────────────────────────────────
# Merge über mehrere Scans (Kernstück: Reopen/False-Positive-Stabilität)
# ─────────────────────────────────────────────────────────────────────────


class TestMergeAcrossScans:
    def test_repeated_scan_stays_open(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        registry.merge_scan_issues([issue], scanned_at="2026-01-02T00:00:00Z")
        fid = generate_finding_id(issue)
        finding = registry.get(fid)
        assert finding.status == STATUS_OPEN
        assert finding.occurrences == 2
        assert finding.last_seen == "2026-01-02T00:00:00Z"
        assert finding.first_seen == "2026-01-01T00:00:00Z"

    def test_false_positive_stays_false_positive_when_redetected(self, tmp_path):
        """Kernanforderung Aufgaben-Abschnitt 8: FALSE_POSITIVE bleibt
        FALSE_POSITIVE, wenn dasselbe Finding erneut erkannt wird - wird
        NICHT als offener Befund behandelt."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Y")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_FALSE_POSITIVE, note="Absicht")

        registry.merge_scan_issues([issue], scanned_at="2026-01-02T00:00:00Z")
        finding = registry.get(fid)
        assert finding.status == STATUS_FALSE_POSITIVE
        assert finding.review_note == "Absicht"
        assert finding not in registry.get_open_findings()

    def test_resolved_finding_not_redetected_keeps_history(self, tmp_path):
        """Aufgaben-Abschnitt 8: verschwindet ein Finding nach RESOLVED,
        bleibt der historische Eintrag erhalten (kein Loeschen)."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_RESOLVED, note="Cover ergänzt")

        # Scan 2: Datei nicht mehr im Issue-Strom (Cover wurde ergaenzt).
        registry.merge_scan_issues([], scanned_at="2026-01-02T00:00:00Z")

        finding = registry.get(fid)
        assert finding is not None, "Historischer Eintrag darf nicht verschwinden"
        assert finding.status == STATUS_RESOLVED
        assert finding.present_in_latest_scan is False

    def test_open_finding_not_redetected_becomes_resolved_by_scan(self, tmp_path):
        """Aufgaben-Abschnitt 9: OPEN + nicht mehr erkannt darf NICHT
        stillschweigend zu RESOLVED werden, sondern zu einem eigenen,
        klar dokumentierten technischen Zwischenzustand."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)

        registry.merge_scan_issues([], scanned_at="2026-01-02T00:00:00Z")
        finding = registry.get(fid)
        assert finding.status == STATUS_RESOLVED_BY_SCAN
        assert finding.status != STATUS_RESOLVED
        assert finding.present_in_latest_scan is False

    def test_reopened_when_resolved_finding_reappears(self, tmp_path):
        """Aufgaben-Abschnitt 18: RESOLVED, dann erneut erkannt -> OPEN,
        nicht dauerhaft RESOLVED angezeigt."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_RESOLVED, note="Cover ergänzt")

        registry.merge_scan_issues([issue], scanned_at="2026-01-02T00:00:00Z")
        finding = registry.get(fid)
        assert finding.status == STATUS_OPEN
        assert finding.reopened_at == "2026-01-02T00:00:00Z"
        assert finding in registry.get_open_findings()
        statuses = [h.status for h in finding.history]
        assert statuses == [STATUS_OPEN, STATUS_RESOLVED, STATUS_OPEN]

    def test_resolved_by_scan_finding_reopens_when_redetected(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)

        registry.merge_scan_issues([], scanned_at="2026-01-02T00:00:00Z")
        assert registry.get(fid).status == STATUS_RESOLVED_BY_SCAN

        registry.merge_scan_issues([issue], scanned_at="2026-01-03T00:00:00Z")
        assert registry.get(fid).status == STATUS_OPEN

    def test_new_finding_created_when_identity_changes(self, tmp_path):
        """Aufgaben-Abschnitt 19: aendern sich die Identitaetsdaten
        wirklich, muss ein NEUES Finding entstehen koennen - keine
        pauschale 'FALSE_POSITIVE fuer immer'-Regel."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue_v1 = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Album V1")
        registry.merge_scan_issues([issue_v1], scanned_at="2026-01-01T00:00:00Z")
        fid_v1 = generate_finding_id(issue_v1)
        registry.review_finding(fid_v1, STATUS_FALSE_POSITIVE)

        issue_v2 = _issue("ALBUM_TRACK_GAP", scope="album", artist="X", album="Album V2 (Umbenannt)")
        registry.merge_scan_issues([issue_v2], scanned_at="2026-01-02T00:00:00Z")
        fid_v2 = generate_finding_id(issue_v2)

        assert fid_v1 != fid_v2
        assert registry.get(fid_v2).status == STATUS_OPEN

    def test_merge_summary_counts(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        a = _issue("ARTWORK_MISSING", path="a.m4a")
        b = _issue("ARTWORK_MISSING", path="b.m4a")
        result1 = registry.merge_scan_issues([a, b], scanned_at="2026-01-01T00:00:00Z")
        assert result1 == {
            "created": 2, "reopened": 0, "resolved_by_scan": 0, "total_in_registry": 2,
        }

        fid_a = generate_finding_id(a)
        registry.review_finding(fid_a, STATUS_RESOLVED)
        result2 = registry.merge_scan_issues([a], scanned_at="2026-01-02T00:00:00Z")
        # a: RESOLVED -> erneut erkannt -> reopened; b: nicht mehr erkannt -> resolved_by_scan
        assert result2 == {
            "created": 0, "reopened": 1, "resolved_by_scan": 1, "total_in_registry": 2,
        }


# ─────────────────────────────────────────────────────────────────────────
# Health Score bleibt unberuehrt (Aufgaben-Abschnitt 16)
# ─────────────────────────────────────────────────────────────────────────


class TestReviewDoesNotTouchHealthScore:
    def test_review_finding_has_no_score_attribute_or_side_effect(self, tmp_path):
        """Die Findings-Registry kennt gar keinen Score-Begriff - ein
        Review kann ihn technisch nicht beeinflussen. Score-Berechnung
        (scoring.py) und Findings-Registry sind vollstaendig getrennte
        Module ohne gegenseitige Importe."""
        import services.library_health.findings as findings_module
        import services.library_health.scoring as scoring_module

        assert "scoring" not in dir(findings_module)
        assert "score" not in [f.name for f in Finding.__dataclass_fields__.values()]
        # Keine Modul-Abhaengigkeit in irgendeine Richtung.
        assert not hasattr(scoring_module, "FindingsRegistry")


# ─────────────────────────────────────────────────────────────────────────
# annotate_issues_with_findings() / build_findings_summary()
# ─────────────────────────────────────────────────────────────────────────


class TestAnnotateIssuesWithFindings:
    def test_open_issue_gets_open_status(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        annotated = annotate_issues_with_findings([issue], registry)
        assert annotated[0]["finding_status"] == STATUS_OPEN
        assert annotated[0]["finding_id"] == generate_finding_id(issue)

    def test_does_not_mutate_original_issue_dict(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        annotate_issues_with_findings([issue], registry)
        assert "finding_status" not in issue

    def test_reviewed_issue_carries_status_and_note(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="a.m4a")
        registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
        fid = generate_finding_id(issue)
        registry.review_finding(fid, STATUS_FALSE_POSITIVE, note="Absicht")

        annotated = annotate_issues_with_findings([issue], registry)
        assert annotated[0]["finding_status"] == STATUS_FALSE_POSITIVE
        assert annotated[0]["finding_review_note"] == "Absicht"

    def test_unknown_issue_without_registry_entry_defaults_to_open(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue = _issue("ARTWORK_MISSING", path="never_merged.m4a")
        annotated = annotate_issues_with_findings([issue], registry)
        assert annotated[0]["finding_status"] == STATUS_OPEN


class TestBuildFindingsSummary:
    def test_counts_by_status(self):
        annotated = [
            {"finding_status": STATUS_OPEN},
            {"finding_status": STATUS_OPEN},
            {"finding_status": STATUS_RESOLVED},
            {"finding_status": STATUS_FALSE_POSITIVE},
        ]
        summary = build_findings_summary(annotated)
        assert summary == {
            "total_detected": 4, "open": 2, "resolved": 1, "false_positive": 1,
        }

    def test_empty_list(self):
        assert build_findings_summary([]) == {
            "total_detected": 0, "open": 0, "resolved": 0, "false_positive": 0,
        }


# ─────────────────────────────────────────────────────────────────────────
# Determinismus
# ─────────────────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_report_produces_same_finding_ids_every_time(self):
        issue = _issue(
            "ALBUM_TRACK_GAP", scope="album", artist="X", album="Y",
            related_files=["b.m4a", "a.m4a"],
        )
        ids = {generate_finding_id(issue) for _ in range(20)}
        assert len(ids) == 1

    def test_merge_and_save_is_deterministic_json_content(self, tmp_path):
        issues = [
            _issue("ARTWORK_MISSING", path="a.m4a"),
            _issue("ARTWORK_MISSING", path="b.m4a"),
        ]
        path1 = tmp_path / "r1.json"
        reg1 = FindingsRegistry(path1)
        reg1.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        reg1.save()

        path2 = tmp_path / "r2.json"
        reg2 = FindingsRegistry(path2)
        reg2.merge_scan_issues(list(reversed(issues)), scanned_at="2026-01-01T00:00:00Z")
        reg2.save()

        assert path1.read_text(encoding="utf-8") == path2.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# Kategorie-Gruppierung + Batch-Review ("Library Health Review", Abschnitt 4/5/8/10)
# ─────────────────────────────────────────────────────────────────────────

from services.library_health.findings import (  # noqa: E402
    batch_review_category,
    group_open_findings_by_category,
)


class TestGroupOpenFindingsByCategory:
    def test_groups_by_issue_code(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [
            _issue("ARTWORK_MISSING", path="a.m4a"),
            _issue("ARTWORK_MISSING", path="b.m4a"),
            _issue("ARTWORK_MISSING", path="c.m4a"),
        ]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        groups = group_open_findings_by_category(registry)
        assert len(groups) == 1
        assert groups[0].code == "ARTWORK_MISSING"
        assert groups[0].open_count == 3

    def test_severity_order_critical_error_warning_suspected_info(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [
            _issue("META_ISRC_MISSING", "INFO", path="i.m4a"),
            _issue(
                "DUPLICATE_SUSPECTED", "INFO", scope="library",
                artist="X", title="Y", confidence="album_context_risk",
            ),
            _issue("ARTWORK_MISSING", "WARNING", path="w.m4a"),
            _issue("META_ARTIST_MISSING", "ERROR", path="e.m4a"),
            _issue("AUDIO_NO_STREAM", "CRITICAL", path="c.m4a"),
        ]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        groups = group_open_findings_by_category(registry)
        tiers = [g.tier for g in groups]
        assert tiers == ["CRITICAL", "ERROR", "WARNING", "SUSPECTED", "INFO"]

    def test_same_tier_sorted_alphabetically_by_code(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [
            _issue("LYRICS_EMPTY", "WARNING", path="a.m4a"),
            _issue("ARTWORK_MISSING", "WARNING", path="b.m4a"),
            _issue("GENRE_EMPTY", "WARNING", path="c.m4a"),
        ]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        groups = group_open_findings_by_category(registry)
        codes = [g.code for g in groups]
        assert codes == sorted(codes)

    def test_deterministic_repeated_grouping(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [
            _issue("ARTWORK_MISSING", "WARNING", path="a.m4a"),
            _issue("LYRICS_EMPTY", "WARNING", path="b.m4a"),
        ]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        first = [(g.code, g.open_count) for g in group_open_findings_by_category(registry)]
        second = [(g.code, g.open_count) for g in group_open_findings_by_category(registry)]
        assert first == second

    def test_resolved_and_false_positive_excluded_from_categories(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issue_a = _issue("ARTWORK_MISSING", path="a.m4a")
        issue_b = _issue("ARTWORK_MISSING", path="b.m4a")
        registry.merge_scan_issues([issue_a, issue_b], scanned_at="2026-01-01T00:00:00Z")
        fid_a = generate_finding_id(issue_a)
        registry.review_finding(fid_a, STATUS_RESOLVED)

        groups = group_open_findings_by_category(registry)
        assert groups[0].open_count == 1

    def test_no_open_findings_returns_empty_list(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        assert group_open_findings_by_category(registry) == []

    def test_dynamic_counts_not_hardcoded(self, tmp_path):
        """Abschnitt 4: Counts MUESSEN dynamisch aus dem Registry-Zustand
        stammen - unterschiedliche Datenlagen ergeben unterschiedliche,
        korrekte Counts (kein fest verdrahteter Wert)."""
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [_issue("ARTWORK_MISSING", path=f"f{i}.m4a") for i in range(37)]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")
        groups = group_open_findings_by_category(registry)
        assert groups[0].open_count == 37


class TestBatchReviewCategory:
    def test_batch_marks_only_open_findings_of_category_as_false_positive(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [_issue("ARTWORK_MISSING", path=f"f{i}.m4a") for i in range(5)]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")

        changed = batch_review_category(
            registry, "ARTWORK_MISSING", STATUS_FALSE_POSITIVE, note="Batch-Notiz",
            reviewed_by="tester",
        )
        assert len(changed) == 5
        for issue in issues:
            fid = generate_finding_id(issue)
            finding = registry.get(fid)
            assert finding.status == STATUS_FALSE_POSITIVE
            assert finding.review_note == "Batch-Notiz"
            assert finding.reviewed_by == "tester"

    def test_batch_does_not_touch_other_categories(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        artwork_issue = _issue("ARTWORK_MISSING", path="a.m4a")
        lyrics_issue = _issue("LYRICS_EMPTY", "WARNING", path="b.m4a")
        registry.merge_scan_issues([artwork_issue, lyrics_issue], scanned_at="2026-01-01T00:00:00Z")

        batch_review_category(registry, "ARTWORK_MISSING", STATUS_FALSE_POSITIVE)

        fid_lyrics = generate_finding_id(lyrics_issue)
        assert registry.get(fid_lyrics).status == STATUS_OPEN

    def test_batch_does_not_touch_already_resolved_or_false_positive(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        already_resolved = _issue("ARTWORK_MISSING", path="a.m4a")
        already_fp = _issue("ARTWORK_MISSING", path="b.m4a")
        still_open = _issue("ARTWORK_MISSING", path="c.m4a")
        registry.merge_scan_issues(
            [already_resolved, already_fp, still_open], scanned_at="2026-01-01T00:00:00Z"
        )
        registry.review_finding(generate_finding_id(already_resolved), STATUS_RESOLVED)
        registry.review_finding(generate_finding_id(already_fp), STATUS_FALSE_POSITIVE)

        changed = batch_review_category(registry, "ARTWORK_MISSING", STATUS_FALSE_POSITIVE)

        assert len(changed) == 1
        assert registry.get(generate_finding_id(already_resolved)).status == STATUS_RESOLVED
        assert registry.get(generate_finding_id(already_fp)).status == STATUS_FALSE_POSITIVE

    def test_batch_large_category_hundreds_of_findings(self, tmp_path):
        registry = FindingsRegistry(tmp_path / "findings.json")
        issues = [_issue("META_ISRC_MISSING", "INFO", path=f"f{i}.m4a") for i in range(400)]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")

        changed = batch_review_category(registry, "META_ISRC_MISSING", STATUS_FALSE_POSITIVE)
        assert len(changed) == 400
        assert group_open_findings_by_category(registry) == []

    def test_batch_single_save_call_is_enough_for_persistence(self, tmp_path):
        """Abschnitt 10: EINE Persistenzoperation fuer die gesamte
        Kategorie statt einer pro Finding."""
        path = tmp_path / "findings.json"
        registry = FindingsRegistry(path)
        issues = [_issue("ARTWORK_MISSING", path=f"f{i}.m4a") for i in range(10)]
        registry.merge_scan_issues(issues, scanned_at="2026-01-01T00:00:00Z")

        batch_review_category(registry, "ARTWORK_MISSING", STATUS_FALSE_POSITIVE)
        registry.save()

        reloaded = FindingsRegistry(path)
        for issue in issues:
            assert reloaded.get(generate_finding_id(issue)).status == STATUS_FALSE_POSITIVE
