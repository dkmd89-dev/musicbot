# tests/test_library_repair_disposition_matrix.py
# -*- coding: utf-8 -*-
"""
Library-Closure-Phase, Auftrag Abschnitt 4/5/32 — vollstaendige, eindeutige
Health-Code -> Disposition -> Executor-Abdeckung.

Ergaenzt tests/test_library_repair_planner.py (dort: jeder Code hat GENAU
EIN Repair-Mapping) um die Grob-Disposition und die Executor-Zuordnung:

  - jeder ALL_CODES-Eintrag hat genau eine Disposition
    (AUTO_REPAIR / MANUAL_REVIEW / UNREPAIRABLE),
  - jeder AUTO_REPAIR-Code wird von genau einer ausfuehrenden Komponente
    bearbeitet (ein executor.py-Codeset ODER dem angedockten
    resolve_duplicates.py-Subprozess),
  - kein Executor-Codeset traegt einen Code, der nicht AUTO_REPAIR ist
    (keine stale Executor-Eintraege),
  - jeder MANUAL_REVIEW-/UNREPAIRABLE-Code hat einen dokumentierten Grund
    (nicht-leeres expected_change).

Snapshot-Doku: docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md
"""

from services.library_health.issues import ALL_CODES
from services.library_repair import executor
from services.library_repair.models import RepairLevel
from services.library_repair.planner import (
    DISPOSITION_AUTO_REPAIR,
    DISPOSITION_MANUAL_REVIEW,
    DISPOSITION_UNREPAIRABLE,
    REGISTRY,
    disposition_for_code,
    disposition_for_level,
)

# ── Ausfuehrende Komponenten ────────────────────────────────────────────
# In-Process-Executoren (executor.py). Jeder Wert ist das Issue-Code-Set,
# das die jeweilige apply_*-Funktion tatsaechlich bearbeitet.
_EXECUTOR_CODE_SETS: dict[str, frozenset] = {
    "apply_level1": executor.L1_TAG_CODES,
    "apply_level1_rename": executor.L1_RENAME_CODES,
    "apply_cover_repairs": executor.COVER_ISSUE_CODES,
    "apply_album_cover_unify": executor.ALBUM_COVER_CODES,
    "apply_external_metadata": executor.EXTERNAL_MB_CODES,
    "apply_level2": executor.L2_CODES,
    "apply_replaygain": executor.LOUDNESS_ISSUE_CODES,
}

# AUTO_REPAIR, aber ueber den angedockten, bereits gehaerteten
# scripts/resolve_duplicates.py-Subprozess statt eines executor.py-Codesets
# (docs/LIBRARY_REPAIR.md §6d — `library_repair.py --allow-delete --artist`).
_DUPLICATE_DOCKED_CODES = frozenset({"DUPLICATE_EXACT", "DUPLICATE_RECORDING"})

_ALL_DISPOSITIONS = {
    DISPOSITION_AUTO_REPAIR,
    DISPOSITION_MANUAL_REVIEW,
    DISPOSITION_UNREPAIRABLE,
}


def _codes_with_disposition(disposition: str) -> set[str]:
    return {c for c in ALL_CODES if disposition_for_code(c) == disposition}


# ── Disposition: vollstaendig + eindeutig ───────────────────────────────


def test_every_health_code_has_exactly_one_known_disposition():
    for code in ALL_CODES:
        disposition = disposition_for_code(code)
        assert disposition in _ALL_DISPOSITIONS, (
            f"{code}: Disposition {disposition!r} ist keine der drei "
            f"dokumentierten ({sorted(_ALL_DISPOSITIONS)})"
        )


def test_disposition_is_pure_rollup_of_the_planner_level():
    """Die Disposition wird ausschliesslich aus RepairSpec.level abgeleitet —
    keine zweite, separat gepflegte Klassifikation (Auftrag Abschnitt 3:
    library_health/planner bleibt die technische Wahrheit)."""
    for code in ALL_CODES:
        spec = REGISTRY[code]
        assert disposition_for_code(code) == disposition_for_level(spec.level)


def test_every_repair_level_is_classified():
    for level in RepairLevel:
        assert disposition_for_level(level) in _ALL_DISPOSITIONS, (
            f"RepairLevel.{level.name} ist keiner Grob-Disposition zugeordnet"
        )


def test_disposition_partition_sizes_snapshot():
    """Change-Detector (analog test_library_repair_planner.py
    ::test_plan_counts_and_determinism): 53 Codes, aufgeteilt in
    29 AUTO_REPAIR / 22 MANUAL_REVIEW / 2 UNREPAIRABLE. Aendert sich diese
    Verteilung, muss die Coverage-Matrix-Doku mit angepasst werden."""
    assert len(ALL_CODES) == 53
    assert len(_codes_with_disposition(DISPOSITION_AUTO_REPAIR)) == 29
    assert len(_codes_with_disposition(DISPOSITION_MANUAL_REVIEW)) == 22
    assert len(_codes_with_disposition(DISPOSITION_UNREPAIRABLE)) == 2


# ── AUTO_REPAIR: genau eine ausfuehrende Komponente ─────────────────────


def test_every_auto_repair_code_has_exactly_one_executor():
    auto = _codes_with_disposition(DISPOSITION_AUTO_REPAIR)
    for code in auto:
        hits = [name for name, codes in _EXECUTOR_CODE_SETS.items() if code in codes]
        if code in _DUPLICATE_DOCKED_CODES:
            hits.append("resolve_duplicates.py (--allow-delete)")
        assert len(hits) == 1, (
            f"{code}: erwartet genau eine ausfuehrende Komponente, gefunden {hits}"
        )


def test_executor_code_sets_are_pairwise_disjoint():
    names = list(_EXECUTOR_CODE_SETS)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            overlap = _EXECUTOR_CODE_SETS[a] & _EXECUTOR_CODE_SETS[b]
            assert not overlap, f"{a} und {b} teilen sich Codes: {sorted(overlap)}"


def test_no_executor_code_set_contains_a_non_auto_repair_code():
    auto = _codes_with_disposition(DISPOSITION_AUTO_REPAIR)
    for name, codes in _EXECUTOR_CODE_SETS.items():
        unknown = set(codes) - set(ALL_CODES)
        assert not unknown, f"{name}: Code(s) nicht in ALL_CODES: {sorted(unknown)}"
        not_auto = set(codes) - auto
        assert not not_auto, (
            f"{name}: Code(s) nicht als AUTO_REPAIR eingestuft: {sorted(not_auto)}"
        )


def test_union_of_all_executors_covers_exactly_the_auto_repair_codes():
    covered: set[str] = set(_DUPLICATE_DOCKED_CODES)
    for codes in _EXECUTOR_CODE_SETS.values():
        covered |= set(codes)
    assert covered == _codes_with_disposition(DISPOSITION_AUTO_REPAIR)


def test_duplicate_docked_codes_route_to_the_duplicate_level():
    for code in _DUPLICATE_DOCKED_CODES:
        assert REGISTRY[code].level is RepairLevel.DUPLICATE
        assert REGISTRY[code].is_destructive is True


# ── MANUAL_REVIEW / UNREPAIRABLE: dokumentierter Grund ──────────────────


def test_manual_review_and_unrepairable_codes_document_a_reason():
    for code in _codes_with_disposition(DISPOSITION_MANUAL_REVIEW) | _codes_with_disposition(
        DISPOSITION_UNREPAIRABLE
    ):
        spec = REGISTRY[code]
        assert spec.expected_change.strip(), (
            f"{code}: {spec.level.name} ohne dokumentierten Grund (expected_change leer)"
        )


def test_unrepairable_codes_have_no_executor():
    non_auto = _codes_with_disposition(DISPOSITION_MANUAL_REVIEW) | _codes_with_disposition(
        DISPOSITION_UNREPAIRABLE
    )
    all_executor_codes: set[str] = set(_DUPLICATE_DOCKED_CODES)
    for codes in _EXECUTOR_CODE_SETS.values():
        all_executor_codes |= set(codes)
    assert not (non_auto & all_executor_codes), (
        f"Nicht-AUTO_REPAIR-Code in einem Executor-Set: "
        f"{sorted(non_auto & all_executor_codes)}"
    )
