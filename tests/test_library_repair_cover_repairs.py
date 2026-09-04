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
    assert "ALBUM_COVER_INCONSISTENT" in cr.ALBUM_ISSUE_CODES


# ── ALBUM_COVER_INCONSISTENT ───────────────────────────────────────────

def _cv(present=True, w=1000, h=1000, sha="x", decodable=True):
    return {"present": present, "w": w, "h": h, "sha256": sha, "decodable": decodable}


def test_pick_album_cover_largest_square():
    covers = [_cv(w=300, h=300, sha="a"), _cv(w=1400, h=1400, sha="b"),
              _cv(w=1200, h=800, sha="c")]  # c non-square
    assert cr.pick_album_cover(covers) == 1


def test_pick_album_cover_none_when_no_usable():
    covers = [_cv(present=False), _cv(w=1200, h=675, sha="wide"),
              _cv(present=True, decodable=False)]
    assert cr.pick_album_cover(covers) is None


def test_pick_album_cover_deterministic_tiebreak():
    covers = [_cv(w=1000, h=1000, sha="zzz"), _cv(w=1000, h=1000, sha="aaa")]
    # gleiche Groesse/Flaeche -> hoeherer sha256 gewinnt (stabil)
    assert cr.pick_album_cover(covers) == 0


def test_should_unify_replaces_smaller_track():
    action, _ = cr.should_unify_track(_cv(w=300, h=300, sha="small"),
                                      {"w": 1400, "h": 1400, "sha256": "big"})
    assert action == cr.REPLACE


def test_should_unify_skips_already_matching():
    action, _ = cr.should_unify_track(_cv(sha="big"), {"w": 1400, "h": 1400, "sha256": "big"})
    assert action == cr.SKIP


def test_should_unify_never_downscales():
    action, _ = cr.should_unify_track(_cv(w=3000, h=3000, sha="huge"),
                                      {"w": 1000, "h": 1000, "sha256": "album"})
    assert action == cr.SKIP
