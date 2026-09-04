# tests/test_library_repair_replaygain_repairs.py
# -*- coding: utf-8 -*-
"""Reine ReplayGain-Berechnung fuer den Loudness-Executor."""

import pytest

from services.library_repair.replaygain_repairs import (
    GAIN_ATOM, PEAK_ATOM, TARGET_LUFS,
    compute_replaygain, effective_lufs, parse_gain_db,
)


def test_target_is_minus_16():
    assert TARGET_LUFS == -16.0


@pytest.mark.parametrize("lufs,expected_gain", [
    (-11.2, "-4.80 dB"),
    (-9.0, "-7.00 dB"),
    (-23.0, "7.00 dB"),
])
def test_compute_gain(lufs, expected_gain):
    w = compute_replaygain(lufs, true_peak_dbtp=-1.0)
    assert w[GAIN_ATOM] == [expected_gain]
    assert w[PEAK_ATOM][0].count(".") == 1


@pytest.mark.parametrize("lufs", [-16.0, -16.9, -15.1, None])
def test_compute_returns_none_when_on_target_or_unmeasured(lufs):
    assert compute_replaygain(lufs) is None


def test_peak_linear_from_dbtp():
    # 0 dBTP -> 1.0 ; +6 dBTP -> ~2.0 ; fehlend -> 1.0
    assert compute_replaygain(-9.0, 0.0)[PEAK_ATOM] == ["1.000000"]
    assert float(compute_replaygain(-9.0, 6.0)[PEAK_ATOM][0]) == pytest.approx(1.9953, abs=1e-3)
    assert compute_replaygain(-9.0, None)[PEAK_ATOM] == ["1.000000"]


@pytest.mark.parametrize("v,expected", [
    ("-4.80 dB", -4.8), ("-4.8", -4.8), ("3", 3.0), ("  6.02 DB ", 6.02),
    (None, None), ("laut", None),
])
def test_parse_gain_db(v, expected):
    assert parse_gain_db(v) == expected


def test_effective_lufs():
    assert effective_lufs(-11.0, -5.0) == -16.0
    assert effective_lufs(-11.0, None) == -11.0
    assert effective_lufs(None, -5.0) is None
