# tests/test_library_repair_tag_repairs.py
# -*- coding: utf-8 -*-
"""Level-1 Tag-Reparatur-Funktionen (pure). Prompt Abschnitt 6/20."""

import pytest

from services.library_repair import tag_repairs as tr


# ── Genre-Delimiter ─────────────────────────────────────────────────────

def test_genre_delimiter_slash_to_semicolon():
    assert tr.repair_genre_delimiter("Pop / Rock / Indie") == "Pop; Rock; Indie"


def test_genre_delimiter_no_change_when_already_correct():
    assert tr.repair_genre_delimiter("Pop; Rock") is None


def test_genre_delimiter_no_change_for_single_genre():
    assert tr.repair_genre_delimiter("Pop") is None


def test_genre_delimiter_none_and_empty():
    assert tr.repair_genre_delimiter(None) is None
    assert tr.repair_genre_delimiter("") is None


def test_genre_delimiter_mixed_separators_not_touched():
    # enthält bereits '; ' -> nicht eindeutig, nichts tun
    assert tr.repair_genre_delimiter("Pop; Rock / Indie") is None


# ── Multi-Artist ────────────────────────────────────────────────────────

def test_multi_artist_split_joined_primary():
    res = tr.repair_multi_artist(["makko & toobrokeforfiji"], [])
    assert res == (["makko", "toobrokeforfiji"], ["makko", "toobrokeforfiji"])


def test_multi_artist_align_primary_to_freeform():
    res = tr.repair_multi_artist(["makko feat. toobrokeforfiji"], ["makko", "toobrokeforfiji"])
    assert res == (["makko", "toobrokeforfiji"], ["makko", "toobrokeforfiji"])


def test_multi_artist_dedupe():
    res = tr.repair_multi_artist(["A", "a"], ["A", "a"])
    assert res == (["A"], ["A"])


def test_multi_artist_dedupe_within_freeform_only():
    res = tr.repair_multi_artist(["A"], ["A", "A"])
    assert res == (["A"], ["A"])


def test_multi_artist_already_canonical_returns_none():
    assert tr.repair_multi_artist(["A", "B"], ["A", "B"]) is None


def test_multi_artist_single_clean_artist_returns_none():
    assert tr.repair_multi_artist(["A"], []) is None
    assert tr.repair_multi_artist(["01099"], ["01099"]) is None


def test_multi_artist_empty_returns_none():
    assert tr.repair_multi_artist([], []) is None


def test_split_joined_artist_variants():
    assert tr.split_joined_artist("A & B") == ["A", "B"]
    assert tr.split_joined_artist("A, B, C") == ["A", "B", "C"]
    assert tr.split_joined_artist("A feat. B & C") == ["A", "B", "C"]
    assert tr.split_joined_artist("Solo") == ["Solo"]


# ── Album-Artist ────────────────────────────────────────────────────────

def test_album_artist_from_primary():
    assert tr.repair_album_artist(None, ["makko", "X"]) == "makko"


def test_album_artist_uses_directory_artist_when_given():
    assert tr.repair_album_artist("wrong", ["makko"], directory_artist="makko") == "makko"


def test_album_artist_no_change_when_already_correct():
    assert tr.repair_album_artist("makko", ["makko"]) is None


def test_album_artist_none_when_nothing_derivable():
    assert tr.repair_album_artist(None, []) is None
