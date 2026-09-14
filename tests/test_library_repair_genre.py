# tests/test_library_repair_genre.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance — Genre-Domain-Logik (ARCH-032 Phase 1).

Characterization-Tests: dieselben Eingaben/Ergebnisse wie
scripts/set_genre.py / scripts/remove_legacy_genre_atom.py
(Vor-Migration).
"""

import yaml

from services.library_repair.genre import (
    LegacyGenreDecision,
    decide_legacy_genre_removal,
    genre_from_mapping,
    known_artist_keys,
    normalize_genre_input,
)
from utils.genre_map import GenreMapper


# ── normalize_genre_input() ──────────────────────────────────────────────


def test_normalize_genre_input_semicolon_passthrough():
    assert normalize_genre_input("Pop; Rock") == "Pop; Rock"


def test_normalize_genre_input_slash_separator():
    assert normalize_genre_input("Pop / Rock") == "Pop; Rock"


def test_normalize_genre_input_comma_separator():
    assert normalize_genre_input("Pop, Rock") == "Pop; Rock"


def test_normalize_genre_input_single_genre():
    assert normalize_genre_input("Pop") == "Pop"


def test_normalize_genre_input_strips_whitespace():
    assert normalize_genre_input(" Pop ;  Rock ") == "Pop; Rock"


def test_normalize_genre_input_empty_after_normalization():
    assert normalize_genre_input("  ;  ") == ""


# ── genre_from_mapping() ─────────────────────────────────────────────────


def _write_artist_genre_yaml(path, mapping: dict) -> None:
    path.write_text(
        yaml.safe_dump({"ARTIST_GENRE_MAP": mapping}, allow_unicode=True),
        encoding="utf-8",
    )


def test_genre_from_mapping_primary_and_secondary(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(
        p, {"filow": {"primary": "Deutschrap", "secondary": ["Hip Hop"]}}
    )
    assert genre_from_mapping("Filow", p) == "Deutschrap; Hip Hop"


def test_genre_from_mapping_case_insensitive_lookup(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {"filow": {"primary": "Deutschrap"}})
    assert genre_from_mapping("FILOW", p) == "Deutschrap"


def test_genre_from_mapping_unknown_artist_returns_none(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {"filow": {"primary": "Deutschrap"}})
    assert genre_from_mapping("Unknown", p) is None


def test_genre_from_mapping_missing_file_returns_none(tmp_path):
    assert genre_from_mapping("Filow", tmp_path / "does_not_exist.yaml") is None


def test_genre_from_mapping_dedupes_repeated_values(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(
        p, {"filow": {"primary": "Deutschrap", "secondary": ["Deutschrap", "Hip Hop"]}}
    )
    assert genre_from_mapping("Filow", p) == "Deutschrap; Hip Hop"


def test_genre_from_mapping_empty_entry_returns_none(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {"filow": {}})
    assert genre_from_mapping("Filow", p) is None


# ── known_artist_keys() ───────────────────────────────────────────────────


def test_known_artist_keys_sorted(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(
        p, {"zeeba": {"primary": "Pop"}, "aymen": {"primary": "Deutschrap"}}
    )
    assert known_artist_keys(p) == ["aymen", "zeeba"]


def test_known_artist_keys_missing_file_returns_empty(tmp_path):
    assert known_artist_keys(tmp_path / "does_not_exist.yaml") == []


# ── decide_legacy_genre_removal() ─────────────────────────────────────────


def test_legacy_removal_no_legacy_atom():
    d = decide_legacy_genre_removal(None, ["Pop"])
    assert d == LegacyGenreDecision(should_remove=False, reason="kein Legacy-Atom")


def test_legacy_removal_no_canonical_atom_blocks_removal():
    d = decide_legacy_genre_removal(["Pop; Rock"], None)
    assert d.should_remove is False
    assert d.reason == "kein ©gen vorhanden (würde Information verlieren)"


def test_legacy_removal_empty_canonical_blocks_removal():
    d = decide_legacy_genre_removal(["Pop; Rock"], [])
    assert d.should_remove is False


def test_legacy_removal_matching_content():
    d = decide_legacy_genre_removal(["Pop; Rock"], ["Pop; Rock"])
    assert d.should_remove is True
    assert d.content_mismatch is False
    assert d.legacy_text == "Pop; Rock"
    assert d.canonical_text == "Pop; Rock"


def test_legacy_removal_content_mismatch_does_not_block():
    """Inhaltliche Abweichung wird nur markiert, blockiert die Entfernung
    NICHT (unveraendertes Originalverhalten aus
    scripts/remove_legacy_genre_atom.py)."""
    d = decide_legacy_genre_removal(["Pop, Rock"], ["Hip Hop"])
    assert d.should_remove is True
    assert d.content_mismatch is True


def test_legacy_removal_normalizes_separators_for_comparison():
    """', ' und ' / ' im Legacy-Wert werden fuer den Vergleich auf '; '
    normalisiert - identischer Inhalt nach Normalisierung -> kein
    Mismatch."""
    d = decide_legacy_genre_removal(["Pop, Rock"], ["Pop; Rock"])
    assert d.should_remove is True
    assert d.content_mismatch is False


def test_legacy_removal_handles_bytes_values():
    d = decide_legacy_genre_removal([b"Pop; Rock"], ["Pop; Rock"])
    assert d.should_remove is True
    assert d.legacy_text == "Pop; Rock"


# ── Cross-Consistency: genre_from_mapping() vs. GenreMapper Manual-Tier ──


def test_genre_from_mapping_matches_genre_mapper_manual_tier(config):
    """services.library_repair.genre.genre_from_mapping() und
    utils.genre_map.GenreMapper.determine_genre() (Manual-Tier) lesen
    dieselbe echte mapping/artist_genre.yaml (ARCH-031 B.2, bewusste
    Duplikation). Dieser Test faengt Schema-Drift zwischen beiden
    Lesepfaden ab - read-only gegen die echte Mapping-Datei, keine
    Library-/Produktionsdatei betroffen."""
    mapper = GenreMapper(str(config.GENRE_MAPPING_DIR))
    known = known_artist_keys(config.GENRE_MAPPING_DIR / "artist_genre.yaml")
    assert known, "artist_genre.yaml sollte mindestens einen Artist enthalten"

    test_artist = known[0]
    ours = genre_from_mapping(test_artist, config.GENRE_MAPPING_DIR / "artist_genre.yaml")
    theirs = mapper.determine_genre(artist_name=test_artist)

    assert ours is not None
    assert theirs is not None
    assert theirs.source == "artist_exact"
    expected = "; ".join(
        dict.fromkeys([theirs.primary, *theirs.secondary])
    )
    assert ours == expected
