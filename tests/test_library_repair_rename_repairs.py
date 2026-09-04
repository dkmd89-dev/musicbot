# tests/test_library_repair_rename_repairs.py
# -*- coding: utf-8 -*-
"""Level-1 Dateinamen-Reparatur-Funktionen (pure). Prompt Abschnitt 6/7/14."""

import pytest

from services.library_repair import rename_repairs as rr


# ── FILENAME_SUSPICIOUS ─────────────────────────────────────────────────

def test_suspicious_collapses_double_space():
    assert rr.repair_suspicious_filename("2021 -  Song", ".m4a") == "2021 - Song.m4a"


def test_suspicious_strips_trailing_space():
    assert rr.repair_suspicious_filename("2021 - Song ", ".m4a") == "2021 - Song.m4a"


def test_suspicious_no_change_returns_none():
    assert rr.repair_suspicious_filename("2021 - Song", ".m4a") is None


# ── FILENAME_TITLE_MISMATCH ─────────────────────────────────────────────

def _mismatch(stem, title, **kw):
    base = dict(stem=stem, extension=".m4a", title=title, library_section="music")
    base.update(kw)
    return rr.repair_filename_title_mismatch(**base)


def test_removes_trailing_producer_credit_keeps_year_prefix():
    assert _mismatch("2020 - Gelb prod. Xarbeats", "Gelb") == "2020 - Gelb.m4a"


def test_removes_trailing_feat_credit_keeps_track_prefix():
    assert _mismatch("09 - ENEMIES prod. @VVSMelody", "Enemies") == "09 - Enemies.m4a"


def test_does_not_rewrite_year_prefix_to_track_number():
    # realer Finalaudit-Fehler: '2025 - ...' darf NICHT '01 - ...' werden
    assert _mismatch("2025 - Weihnachtslied 2025 prod. Barré", "Weihnachtslied 2025") \
        == "2025 - Weihnachtslied 2025.m4a"


def test_removes_closed_parenthetical_cruft():
    assert _mismatch("01 - Song (Radio Version)", "Song") == "01 - Song.m4a"


def test_leading_extra_plus_truncation_is_left_for_manual_review():
    assert _mismatch("01 - MAKKO 7er STOCK (Dir.", "7er Stock") is None


def test_typo_in_tag_is_not_propagated_to_filename():
    assert _mismatch("01 - Weihnachtslied 2020", "Weihnachtlied 2020") is None


def test_stem_without_prefix_still_strips_cruft():
    assert _mismatch("Some Name prod. X", "Some Name") == "Some Name.m4a"


def test_title_with_illegal_chars_is_skipped():
    assert _mismatch("2020 - Fcked Up", "F*cked Up") is None


def test_compilation_section_is_skipped():
    assert _mismatch("Artist - Song extra", "Song",
                     library_section="compilations") is None


def test_no_change_when_already_matching():
    assert _mismatch("2020 - Song", "Song") is None
