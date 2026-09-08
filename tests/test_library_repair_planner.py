# tests/test_library_repair_planner.py
# -*- coding: utf-8 -*-
"""Repair Planner — Issue → Repair Action Klassifikation (Prompt Abschnitt 20)."""

import pytest

from services.library_health.issues import ALL_CODES
from services.library_repair.planner import (
    REGISTRY,
    filter_plan,
    plan_repairs,
    registry_covers_all_health_codes,
)
from services.library_repair.models import RepairLevel


def _report(*issues, root="/lib", score=95.0):
    return {
        "library": {"root": root},
        "health": {"score": score},
        "issues": list(issues),
    }


def _issue(code, **over):
    base = {"issue_code": code, "severity": "INFO", "scope": "file",
            "path": "A/Singles/2020 - x.m4a", "artist": "A", "album": None,
            "title": "x", "message": "m", "related_files": []}
    base.update(over)
    return base


# ── Registry-Vollstaendigkeit ───────────────────────────────────────────

def test_every_health_code_has_a_repair_mapping():
    ok, missing = registry_covers_all_health_codes()
    assert ok, f"Kein Repair-Mapping fuer: {sorted(missing)}"


def test_registry_has_no_stale_codes():
    stale = set(REGISTRY) - set(ALL_CODES)
    assert not stale, f"Repair-Mapping fuer nicht existierenden Health-Code: {sorted(stale)}"


# ── Issue → Action ──────────────────────────────────────────────────────

def test_genre_delimiter_is_safe_automatic():
    plan = plan_repairs(_report(_issue("GENRE_DELIMITER_INCONSISTENT")))
    c = plan.candidates[0]
    assert c.level is RepairLevel.SAFE_AUTOMATIC
    assert c.requires_approval is False
    assert c.is_destructive is False


def test_missing_recording_id_is_external():
    plan = plan_repairs(_report(_issue("META_MB_RECORDING_MISSING")))
    c = plan.candidates[0]
    assert c.level is RepairLevel.EXTERNAL_METADATA
    assert c.requires_external is True
    assert c.requires_approval is True


def test_exact_duplicate_is_destructive_and_needs_approval():
    plan = plan_repairs(_report(_issue("DUPLICATE_EXACT", scope="library", path=None)))
    c = plan.candidates[0]
    assert c.level is RepairLevel.DUPLICATE
    assert c.is_destructive is True
    assert c.requires_approval is True


def test_suspected_duplicate_is_manual_review():
    plan = plan_repairs(_report(_issue("DUPLICATE_SUSPECTED", scope="library", path=None)))
    assert plan.candidates[0].level is RepairLevel.MANUAL_REVIEW


def test_album_genre_inconsistent_is_not_repairable():
    plan = plan_repairs(_report(_issue("ALBUM_GENRE_INCONSISTENT", scope="album")))
    c = plan.candidates[0]
    assert c.level is RepairLevel.NOT_REPAIRABLE
    assert c not in plan.actionable()


def test_unknown_issue_code_yields_no_candidate():
    plan = plan_repairs(_report(_issue("TOTALLY_MADE_UP_CODE")))
    assert plan.candidates == []
    assert "TOTALLY_MADE_UP_CODE" in plan.unmapped_issue_codes


def test_structure_and_audio_route_to_manual_review():
    for code in ("STRUCTURE_INVALID_PATH", "AUDIO_CORRUPT", "ALBUM_TRACK_GAP",
                 "ARTIST_NAME_VARIANTS"):
        plan = plan_repairs(_report(_issue(code)))
        assert plan.candidates[0].level is RepairLevel.MANUAL_REVIEW, code


# ── Production-Audit 2026-09-08: vormals tote EXTERNAL_METADATA-Codes ──

def test_no_registry_entry_claims_reprocess_artist_metadata_script():
    """Production-Audit 2026-09-08: der automatisierte Repair-Pfad ruft
    NIE scripts/reprocess_artist_metadata.py auf (weder als Subprozess
    noch sonst), sondern track_reprocessor.process_file() in-process.
    Kein Registry-Eintrag darf das Skript als reuses_component behaupten -
    das waere ein irrefuehrendes Signal ueber den tatsaechlichen
    Ausfuehrungspfad."""
    misleading = [s.issue_code for s in REGISTRY.values()
                  if "reprocess_artist_metadata.py" in s.reuses_component]
    assert misleading == []


def test_year_missing_and_album_release_id_inconsistent_are_manual_review():
    """Production-Audit 2026-09-08: beide standen vorher auf
    EXTERNAL_METADATA, obwohl kein Executor sie je behandelt hat (kein
    Jahr-Fetch im Code; Release-ID-Vereinheitlichung wuerde bereits
    vorhandene Werte ueberschreiben muessen)."""
    for code in ("META_YEAR_MISSING", "ALBUM_RELEASE_ID_INCONSISTENT"):
        plan = plan_repairs(_report(_issue(code)))
        assert plan.candidates[0].level is RepairLevel.MANUAL_REVIEW, code
        assert plan.candidates[0] not in plan.actionable()


def test_filename_title_mismatch_signal_warns_about_skip_rate():
    """Production-Audit 2026-09-08: SAFE_AUTOMATIC/requires_approval=False
    fuer FILENAME_TITLE_MISMATCH bleibt korrekt (kein Audio-/Library-Risiko),
    aber die Plan-Vorschau muss transparent machen, dass die tatsaechliche
    Rename-Logik nur additive Abweichungen sicher aufloest (real >85%
    Skip-Rate) - sonst wirkt jedes SKIPPED wie ein Fehler statt wie
    erwartetes, konservatives Verhalten."""
    plan = plan_repairs(_report(_issue("FILENAME_TITLE_MISMATCH")))
    c = plan.candidates[0]
    assert c.level is RepairLevel.SAFE_AUTOMATIC
    assert c.requires_approval is False
    assert "SKIPPED" in c.expected_change


def test_genre_missing_and_genre_empty_are_metadata_reprocessing():
    """Production-Audit 2026-09-08: von EXTERNAL_METADATA nach
    METADATA_REPROCESSING verschoben — GenreProcessor laeuft bereits
    identisch zu GENRE_INVALID als Teil der vollen Pipeline."""
    for code in ("META_GENRE_MISSING", "GENRE_EMPTY"):
        plan = plan_repairs(_report(_issue(code)))
        c = plan.candidates[0]
        assert c.level is RepairLevel.METADATA_REPROCESSING, code
        assert c in plan.actionable()


# ── Plan-Aggregation ────────────────────────────────────────────────────

def test_plan_counts_and_determinism():
    r = _report(
        _issue("GENRE_DELIMITER_INCONSISTENT"),
        _issue("META_ISRC_MISSING"),
        _issue("DUPLICATE_SUSPECTED", scope="library", path=None),
        _issue("LOUDNESS_OFF_TARGET", path="A/Singles/2020 - y.m4a"),
    )
    a = plan_repairs(r).to_dict()
    b = plan_repairs(r).to_dict()
    assert a == b
    counts = a["counts_by_level"]
    assert counts.get("SAFE_AUTOMATIC") == 1
    assert counts.get("EXTERNAL_METADATA") == 1
    assert counts.get("LOUDNESS") == 1
    assert counts.get("MANUAL_REVIEW") == 1
    assert a["manual_review_total"] == 1
    assert a["actionable_total"] == 3


# ── Filter ──────────────────────────────────────────────────────────────

def test_filter_by_issue_and_severity_and_level():
    r = _report(
        _issue("META_ISRC_MISSING", severity="INFO"),
        _issue("META_ARTIST_MISSING", severity="ERROR", path="B/Singles/2020 - z.m4a", artist="B"),
        _issue("GENRE_DELIMITER_INCONSISTENT", severity="INFO"),
    )
    plan = plan_repairs(r)
    assert len(filter_plan(plan, issue_code="META_ISRC_MISSING").candidates) == 1
    assert len(filter_plan(plan, severity="ERROR").candidates) == 1
    assert len(filter_plan(plan, level="SAFE_AUTOMATIC").candidates) == 1
    assert len(filter_plan(plan, artist="B").candidates) == 1


def test_filter_by_artist_matches_path_prefix():
    r = _report(_issue("LOUDNESS_TAG_MISSING", path="01099/2023 - Blaue Stunden/01 - a.m4a",
                       artist=None))
    plan = filter_plan(plan_repairs(r), artist="01099")
    assert len(plan.candidates) == 1
