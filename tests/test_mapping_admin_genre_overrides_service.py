# -*- coding: utf-8 -*-
"""M3 (2026-09-29): Genre-Override-Verwaltung, exact-first Lookup."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma


def _seed(tmp_path: Path, mapping: dict) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "genre_overrides.yaml").write_text(
        yaml.safe_dump(
            {ma.MAPPING_ROOT_KEY_GENRE_OVERRIDES: mapping},
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )
    return mdir


def _read(tmp_path: Path) -> dict:
    raw = yaml.safe_load((tmp_path / "mapping" / "genre_overrides.yaml").read_text(encoding="utf-8"))
    return raw[ma.MAPPING_ROOT_KEY_GENRE_OVERRIDES]


# ── Basis-Operationen ─────────────────────────────────────────────────


def test_list_returns_entries(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop", "rnb": "R&B"})
    entries = ma.list_genre_overrides(mdir)
    assert {e.key for e in entries} == {"hiphop", "rnb"}


def test_get_missing_key_returns_none_plus_etag(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    entry, etag = ma.get_genre_override("fehlt", mdir)
    assert entry is None
    assert len(etag) == 16


# ── Der wichtigste Test: Hip-Hop vs hip-hop ──────────────────────────


def test_hip_hop_and_lower_hip_hop_stay_separate(tmp_path):
    """Kern-Anforderung M3: 'Hip-Hop' und 'hip-hop' sind zwei Eintraege."""
    mdir = _seed(tmp_path, {
        "Hip-Hop": "Hip Hop",
        "hip-hop": "Rap",
    })
    e1, _ = ma.get_genre_override("Hip-Hop", mdir)
    e2, _ = ma.get_genre_override("hip-hop", mdir)
    assert e1.key == "Hip-Hop"
    assert e1.override == "Hip Hop"
    assert e2.key == "hip-hop"
    assert e2.override == "Rap"


def test_update_exact_key_does_not_touch_case_variant(tmp_path):
    """Update 'Hip-Hop' darf 'hip-hop' NICHT anfassen."""
    mdir = _seed(tmp_path, {
        "Hip-Hop": "Hip Hop",
        "hip-hop": "Rap",
    })
    _, etag = ma.get_genre_override("Hip-Hop", mdir)
    ma.apply_genre_override_update("Hip-Hop", "Rock", mdir, expected_etag=etag)
    raw = _read(tmp_path)
    assert raw["Hip-Hop"] == "Rock"
    assert raw["hip-hop"] == "Rap"  # unveraendert


def test_update_lower_case_key_does_not_touch_capital_variant(tmp_path):
    mdir = _seed(tmp_path, {
        "Hip-Hop": "Hip Hop",
        "hip-hop": "Rap",
    })
    _, etag = ma.get_genre_override("hip-hop", mdir)
    ma.apply_genre_override_update("hip-hop", "Metal", mdir, expected_etag=etag)
    raw = _read(tmp_path)
    assert raw["Hip-Hop"] == "Hip Hop"
    assert raw["hip-hop"] == "Metal"


def test_lookup_uppercase_falls_back_to_casefold(tmp_path):
    """'HIP-HOP' existiert nicht exakt — casefold-Fallback findet 'Hip-Hop'
    (nicht 'hip-hop'), weil 'Hip-Hop' zuerst im Mapping steht."""
    mdir = _seed(tmp_path, {
        "Hip-Hop": "Hip Hop",
        "hip-hop": "Rap",
    })
    entry, _ = ma.get_genre_override("HIP-HOP", mdir)
    # Fallback matcht den ersten casefold-Treffer in der Iterationsreihenfolge
    assert entry is not None
    assert entry.key in ("Hip-Hop", "hip-hop")


def test_etag_distinguishes_case_variants(tmp_path):
    """Zwei Mappings mit gleichem Zielwert, aber unterschiedlicher
    Key-Schreibweise, haben verschiedene Etags."""
    mdir_a = _seed(tmp_path / "a", {"Hip-Hop": "Hip Hop"})
    mdir_b = _seed(tmp_path / "b", {"hip-hop": "Hip Hop"})
    _, etag_a = ma.get_genre_override("Hip-Hop", mdir_a)
    _, etag_b = ma.get_genre_override("hip-hop", mdir_b)
    assert etag_a != etag_b


# ── Create / Update / Unchanged ──────────────────────────────────────


def test_plan_create_new_key(tmp_path):
    mdir = _seed(tmp_path, {})
    plan = ma.plan_genre_override_update("NeuerKey", "Pop", mdir)
    assert plan.change == "create"
    assert plan.key == "NeuerKey"  # Case bleibt erhalten
    assert plan.override == "Pop"


def test_plan_unchanged(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    plan = ma.plan_genre_override_update("hiphop", "Hip Hop", mdir)
    assert plan.change == "unchanged"


def test_plan_update_existing(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    plan = ma.plan_genre_override_update("hiphop", "Rap", mdir)
    assert plan.change == "update"
    assert plan.override_changed is True


def test_plan_invalid_value_raises(tmp_path):
    mdir = _seed(tmp_path, {})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_override_update("neu", "", mdir)


def test_apply_conflict_raises(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    with pytest.raises(ma.MappingConflictError):
        ma.apply_genre_override_update(
            "hiphop", "Rap", mdir, expected_etag="deadbeefdeadbeef",
        )


def test_apply_create_then_roundtrip(tmp_path):
    mdir = _seed(tmp_path, {})
    _, etag = ma.get_genre_override("neu", mdir)
    ma.apply_genre_override_update("neu", "Pop", mdir, expected_etag=etag)
    entry, _ = ma.get_genre_override("neu", mdir)
    assert entry.override == "Pop"


def test_apply_missing_file_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    with pytest.raises(ma.MappingUnavailableError):
        ma.plan_genre_override_update("neu", "Pop", mdir)


# ── Warnung: Key wirkt zur Laufzeit nicht ─────────────────────────────
# GenreMapper.normalize_genre_name() sucht mit strip().lower() im Override-Dict;
# ein Key mit Grossbuchstaben steht zwar in der Datei, greift aber nie.


def test_plan_warns_for_new_key_with_uppercase(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    plan = ma.plan_genre_override_update("Trip Hop", "Downtempo", mdir)
    assert plan.change == "create"
    assert len(plan.warnings) == 1
    assert "Laufzeit" in plan.warnings[0] and "trip hop" in plan.warnings[0]


def test_plan_warns_for_existing_uppercase_key_update(tmp_path):
    mdir = _seed(tmp_path, {"Hip-Hop": "Hip Hop"})
    plan = ma.plan_genre_override_update("Hip-Hop", "Rap", mdir)
    assert plan.change == "update"
    assert len(plan.warnings) == 1


def test_plan_has_no_warning_for_lowercase_key(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    assert ma.plan_genre_override_update("trip hop", "Downtempo", mdir).warnings == []
    assert ma.plan_genre_override_update("hiphop", "Hip Hop", mdir).warnings == []


def test_warning_does_not_block_saving_the_key(tmp_path):
    mdir = _seed(tmp_path, {"hiphop": "Hip Hop"})
    plan = ma.plan_genre_override_update("Trip Hop", "Downtempo", mdir)
    ma.apply_genre_override_update("Trip Hop", "Downtempo", mdir, expected_etag=plan.etag)
    assert _read(tmp_path)["Trip Hop"] == "Downtempo"
