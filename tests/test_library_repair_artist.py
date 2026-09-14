# tests/test_library_repair_artist.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance — Artist-Domain-Logik (ARCH-032 Phase 1).

Characterization-Tests: dieselben Eingaben/Ergebnisse wie
scripts/fix_artist_casing.py (Vor-Migration), siehe Docstring-Beispiele
dort ("miksu" -> "Miksu & Macloud" wird bewusst NICHT angewendet - keine
Namens-Erweiterung, nur reines Casing).
"""

import json

import pytest
import yaml

from services.library_repair.artist import load_casing_map, normalize_values


# ── load_casing_map() ────────────────────────────────────────────────────


def test_load_casing_map_from_case_preserve_yaml(tmp_path):
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "case_preserve.yaml").write_text(
        yaml.safe_dump({"case_preserve": {"makko": "makko"}}), encoding="utf-8"
    )

    m = load_casing_map(mapping_dir)
    assert m == {"makko": "makko"}


def test_load_casing_map_from_artist_overrides_json(tmp_path):
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"Bausa": "Bausa"}), encoding="utf-8"
    )

    m = load_casing_map(mapping_dir)
    assert m == {"bausa": "Bausa"}


def test_load_casing_map_overrides_wins_over_case_preserve(tmp_path):
    """artist_overrides.json ueberschreibt case_preserve.yaml bei
    identischem casefold-Key (Reihenfolge aus dem Original-Script)."""
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "case_preserve.yaml").write_text(
        yaml.safe_dump({"case_preserve": {"BAUSA": "BAUSA"}}), encoding="utf-8"
    )
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"bausa": "Bausa"}), encoding="utf-8"
    )

    m = load_casing_map(mapping_dir)
    assert m == {"bausa": "Bausa"}


def test_load_casing_map_filters_non_case_only_entries(tmp_path):
    """Namens-Erweiterungen (key.casefold() != value.casefold()) werden
    NICHT als Casing-Mapping uebernommen - das ist Aufgabe des
    ArtistIdentityResolver, nicht dieses Moduls (ARCH-031 B.1)."""
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "artist_overrides.json").write_text(
        json.dumps({"miksu": "Miksu & Macloud", "bausa": "Bausa"}), encoding="utf-8"
    )

    m = load_casing_map(mapping_dir)
    assert m == {"bausa": "Bausa"}
    assert "miksu" not in m


def test_load_casing_map_missing_files_returns_empty(tmp_path):
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    assert load_casing_map(mapping_dir) == {}


def test_load_casing_map_empty_files_returns_empty(tmp_path):
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "case_preserve.yaml").write_text("", encoding="utf-8")
    (mapping_dir / "artist_overrides.json").write_text("{}", encoding="utf-8")
    assert load_casing_map(mapping_dir) == {}


# ── normalize_values() ───────────────────────────────────────────────────


def test_normalize_values_applies_case_only_match():
    casing_map = {"bausa": "Bausa"}
    new, changes = normalize_values(["bausa"], casing_map)
    assert new == ["Bausa"]
    assert changes == [("bausa", "Bausa")]


def test_normalize_values_no_change_when_already_correct():
    casing_map = {"bausa": "Bausa"}
    new, changes = normalize_values(["Bausa"], casing_map)
    assert new == ["Bausa"]
    assert changes == []


def test_normalize_values_unknown_artist_untouched():
    casing_map = {"bausa": "Bausa"}
    new, changes = normalize_values(["Unknown Artist"], casing_map)
    assert new == ["Unknown Artist"]
    assert changes == []


def test_normalize_values_multi_artist_list():
    casing_map = {"bausa": "Bausa", "makko": "makko"}
    new, changes = normalize_values(["bausa", "toobrokeforfiji"], casing_map)
    assert new == ["Bausa", "toobrokeforfiji"]
    assert changes == [("bausa", "Bausa")]


def test_normalize_values_empty_list():
    assert normalize_values([], {"bausa": "Bausa"}) == ([], [])


def test_normalize_values_handles_bytes_values():
    """ARTISTS-Freeform-Atome kommen von mutagen teils als bytes."""
    casing_map = {"bausa": "Bausa"}
    new, changes = normalize_values([b"bausa"], casing_map)
    assert new == ["Bausa"]
    assert changes == [("bausa", "Bausa")]
