# tests/test_library_repair_genre.py
# -*- coding: utf-8 -*-
"""
Library-Maintenance — Genre-Domain-Logik (ARCH-032 Phase 1).

Characterization-Tests: dieselben Eingaben/Ergebnisse wie
scripts/set_genre.py / scripts/remove_legacy_genre_atom.py
(Vor-Migration).
"""

import yaml

import pytest

from services.library_repair.genre import (
    GenreDomainError,
    LegacyGenreDecision,
    decide_legacy_genre_removal,
    genre_from_mapping,
    known_artist_keys,
    normalize_genre_input,
    save_manual_genre_mapping,
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


# ── save_manual_genre_mapping() (Library Genre Management v2) ───────────


def test_save_manual_mapping_missing_file_raises_domain_error(tmp_path):
    with pytest.raises(GenreDomainError):
        save_manual_genre_mapping("Metallica", "Heavy Metal", tmp_path, dry_run=True)


def test_save_manual_mapping_dry_run_does_not_write(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {})

    result = save_manual_genre_mapping("Metallica", "Heavy Metal", tmp_path, dry_run=True)

    assert result.dry_run is True
    assert result.written is False
    assert result.unchanged is False
    assert result.artist_key == "metallica"
    assert result.primary == "Heavy Metal"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "metallica" not in (data.get("ARTIST_GENRE_MAP") or {})


def test_save_manual_mapping_writes_new_entry(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {})

    result = save_manual_genre_mapping("Metallica", "Heavy Metal; Thrash Metal", tmp_path, dry_run=False)

    assert result.written is True
    assert result.unchanged is False
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    entry = data["ARTIST_GENRE_MAP"]["metallica"]
    assert entry["primary"] == "Heavy Metal"
    assert entry["secondary"] == ["Thrash Metal"]


def test_save_manual_mapping_case_insensitive_key(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {})

    save_manual_genre_mapping("METALLICA", "Rock", tmp_path, dry_run=False)

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "metallica" in data["ARTIST_GENRE_MAP"]


def test_save_manual_mapping_identical_entry_is_unchanged_no_write(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {
        "metallica": {"primary": "Rock", "secondary": [], "description": "x"},
    })
    before_mtime = p.stat().st_mtime_ns

    result = save_manual_genre_mapping("Metallica", "Rock", tmp_path, dry_run=False)

    assert result.unchanged is True
    assert result.written is False
    assert p.stat().st_mtime_ns == before_mtime


def test_save_manual_mapping_preserves_existing_description(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {
        "metallica": {"primary": "Rock", "secondary": [], "description": "Custom note"},
    })

    save_manual_genre_mapping("Metallica", "Heavy Metal", tmp_path, dry_run=False)

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["ARTIST_GENRE_MAP"]["metallica"]["description"] == "Custom note"


def test_save_manual_mapping_updates_existing_entry(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {
        "metallica": {"primary": "Rock", "secondary": [], "description": "x"},
    })

    result = save_manual_genre_mapping("Metallica", "Heavy Metal", tmp_path, dry_run=False)

    assert result.written is True
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["ARTIST_GENRE_MAP"]["metallica"]["primary"] == "Heavy Metal"


def test_save_manual_mapping_does_not_touch_other_artists(tmp_path):
    p = tmp_path / "artist_genre.yaml"
    _write_artist_genre_yaml(p, {
        "bausa": {"primary": "Deutschrap", "secondary": [], "description": "x"},
    })

    save_manual_genre_mapping("Metallica", "Rock", tmp_path, dry_run=False)

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["ARTIST_GENRE_MAP"]["bausa"]["primary"] == "Deutschrap"
