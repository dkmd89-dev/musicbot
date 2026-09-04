# tests/test_library_repair_loudness_repairs.py
# -*- coding: utf-8 -*-
"""Reine Entscheidungslogik des Loudness-Executors."""

import pytest

from services.library_repair.loudness_repairs import (
    NORMALIZE, SKIP, TARGET_LUFS, decide_loudness_action, verify_normalized,
)


@pytest.mark.parametrize("lufs,expected", [
    (-16.0, SKIP),
    (-16.7, SKIP),      # innerhalb FIX_TOLERANCE_DB (1.0)
    (-15.2, SKIP),
    (-9.4, NORMALIZE),  # deutlich zu laut
    (-23.0, NORMALIZE), # deutlich zu leise
    (None, SKIP),       # keine Messung -> nicht raten
])
def test_decide(lufs, expected):
    action, why = decide_loudness_action(lufs)
    assert action == expected
    assert why


def test_decide_target_is_minus_16():
    assert TARGET_LUFS == -16.0


def test_verify_ok_when_on_target_and_duration_stable():
    ok, why = verify_normalized(-16.2, 180.0, 180.05)
    assert ok and "-16.2" in why


def test_verify_fails_when_still_off_target():
    ok, why = verify_normalized(-12.0, 180.0, 180.0)
    assert not ok and "daneben" in why


def test_verify_fails_when_duration_jumped():
    ok, why = verify_normalized(-16.1, 180.0, 184.0)
    assert not ok and "Laufzeit" in why


def test_verify_fails_when_not_measurable():
    ok, why = verify_normalized(None, 180.0, 180.0)
    assert not ok


def test_verify_tolerates_missing_durations():
    ok, _ = verify_normalized(-16.1, None, None)
    assert ok
