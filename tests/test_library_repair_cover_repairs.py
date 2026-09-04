# tests/test_library_repair_cover_repairs.py
# -*- coding: utf-8 -*-
"""Cover-Reparatur-Entscheidung (pure). Prompt Abschnitt 9."""

import pytest

from services.library_repair import cover_repairs as cr


def _decide(code, **kw):
    base = dict(current_present=True, current_state="PRESENT",
               current_w=300, current_h=300, candidate_w=1000, candidate_h=1000)
    base.update(kw)
    return cr.decide_cover_action(code, **base)


# ── ADD (missing/invalid) ──────────────────────────────────────────────

def test_missing_gets_cover_added():
    action, _ = _decide("ARTWORK_MISSING", current_present=False,
                        current_state="MISSING", current_w=None, current_h=None)
    assert action == cr.ADD


def test_invalid_gets_replaced():
    action, _ = _decide("ARTWORK_INVALID", current_state="INVALID",
                        current_w=None, current_h=None)
    assert action == cr.ADD


def test_missing_skips_when_no_candidate():
    action, why = _decide("ARTWORK_MISSING", current_present=False,
                          candidate_w=None, candidate_h=None)
    assert action == cr.SKIP and "kein" in why.lower()


# ── nie mit schlechterem Cover ueberschreiben ──────────────────────────

def test_never_replace_with_too_small_candidate():
    action, _ = _decide("ARTWORK_LOW_RESOLUTION", candidate_w=350, candidate_h=350)
    assert action == cr.SKIP


def test_never_replace_with_non_square_candidate():
    action, _ = _decide("ARTWORK_NON_SQUARE", candidate_w=1200, candidate_h=800)
    assert action == cr.SKIP


def test_missing_skips_non_square_candidate():
    action, _ = _decide("ARTWORK_MISSING", current_present=False,
                        candidate_w=1200, candidate_h=675)
    assert action == cr.SKIP


# ── LOW_RESOLUTION nur bei spuerbarem Zugewinn ─────────────────────────

def test_low_res_replaced_only_if_clearly_bigger():
    assert _decide("ARTWORK_LOW_RESOLUTION", current_w=300, current_h=300,
                   candidate_w=1000, candidate_h=1000)[0] == cr.REPLACE
    # 300 -> 450 ist zu wenig Zugewinn
    assert _decide("ARTWORK_LOW_RESOLUTION", current_w=300, current_h=300,
                   candidate_w=450, candidate_h=450)[0] == cr.SKIP


# ── NON_SQUARE nur ohne Aufloesungsverlust ────────────────────────────

def test_non_square_replaced_by_square_without_res_loss():
    assert _decide("ARTWORK_NON_SQUARE", current_w=1200, current_h=1000,
                   candidate_w=1000, candidate_h=1000)[0] == cr.REPLACE
    # quadratisch, aber kleiner als die kurze Kante des aktuellen -> SKIP
    assert _decide("ARTWORK_NON_SQUARE", current_w=1200, current_h=1000,
                   candidate_w=800, candidate_h=800)[0] == cr.SKIP


def test_handled_codes_frozenset():
    assert "ARTWORK_MISSING" in cr.HANDLED_ISSUE_CODES
    assert "ALBUM_COVER_INCONSISTENT" not in cr.HANDLED_ISSUE_CODES
