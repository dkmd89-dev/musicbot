# tests/test_library_repair_replaygain_repairs.py
# -*- coding: utf-8 -*-
"""Reine ReplayGain-Entscheidungslogik fuer den Loudness-Executor."""

import pytest

from services.library_repair.replaygain_repairs import (
    CLEAR, GAIN_ATOM, PEAK_ATOM, SET, TARGET_LUFS,
    compute_replaygain, effective_lufs, parse_gain_db,
)


def test_target_is_minus_16():
    assert TARGET_LUFS == -16.0


@pytest.mark.parametrize("lufs,expected_gain", [
    (-11.2, "-4.80 dB"),
    (-9.0, "-7.00 dB"),
    (-23.0, "7.00 dB"),
])
def test_set_when_no_tag_and_off_target(lufs, expected_gain):
    act, w = compute_replaygain(lufs, true_peak_dbtp=-1.0)
    assert act == SET
    assert w[GAIN_ATOM] == [expected_gain]
    assert w[PEAK_ATOM][0].count(".") == 1


@pytest.mark.parametrize("lufs", [-16.0, -16.9, -15.1, None])
def test_none_when_on_target_and_no_tag(lufs):
    assert compute_replaygain(lufs) == (None, None)


def test_none_when_existing_tag_already_correct():
    # -11 LUFS, Tag -5 dB -> effektiv -16 -> passt
    assert compute_replaygain(-11.0, existing_gain_db=-5.0) == (None, None)


def test_set_overwrites_wrong_existing_tag():
    # -9.4 LUFS, Tag -2 dB -> effektiv -11.4 -> daneben -> neuen Gain -6.60
    act, w = compute_replaygain(-9.4, -1.0, existing_gain_db=-2.0)
    assert act == SET
    assert w[GAIN_ATOM] == ["-6.60 dB"]


def test_clear_when_file_on_target_but_stale_tag():
    # Datei bei -16.03, Tag -4.26 -> Datei ok, Tag irrefuehrend -> CLEAR
    act, w = compute_replaygain(-16.03, -4.0, existing_gain_db=-4.26)
    assert act == CLEAR and w is None


def test_no_clear_when_on_target_and_no_tag():
    assert compute_replaygain(-16.03, existing_gain_db=None) == (None, None)


def test_peak_linear_from_dbtp():
    assert compute_replaygain(-9.0, 0.0)[1][PEAK_ATOM] == ["1.000000"]
    assert float(compute_replaygain(-9.0, 6.0)[1][PEAK_ATOM][0]) == pytest.approx(1.9953, abs=1e-3)
    assert compute_replaygain(-9.0, None)[1][PEAK_ATOM] == ["1.000000"]


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
