# -*- coding: utf-8 -*-
"""M2 (2026-09-29): services/mapping_admin.py — Genre-Alias-Verwaltung."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma


def _seed(tmp_path: Path, mapping: dict) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "genre_aliases.yaml").write_text(
        yaml.safe_dump(
            {ma.MAPPING_ROOT_KEY_GENRE_ALIASES: mapping},
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )
    return mdir


def _read(tmp_path: Path) -> dict:
    raw = yaml.safe_load((tmp_path / "mapping" / "genre_aliases.yaml").read_text(encoding="utf-8"))
    return raw[ma.MAPPING_ROOT_KEY_GENRE_ALIASES]


# ── Liste + Einzeleintrag ─────────────────────────────────────────────


def test_list_returns_sorted_entries(tmp_path):
    mdir = _seed(tmp_path, {"b-alias": "Rock", "a-alias": "Pop"})
    entries = ma.list_genre_aliases(mdir)
    assert [e.key for e in entries] == ["a-alias", "b-alias"]


def test_get_missing_alias_returns_none_plus_etag(tmp_path):
    mdir = _seed(tmp_path, {"existiert": "Pop"})
    entry, etag = ma.get_genre_alias("nicht-da", mdir)
    assert entry is None
    assert isinstance(etag, str) and len(etag) == 16


def test_get_alias_case_insensitive(tmp_path):
    mdir = _seed(tmp_path, {"DeutschRap": "Deutschrap"})
    entry, etag = ma.get_genre_alias("deutschrap", mdir)
    assert entry is not None
    assert entry.key == "DeutschRap"
    assert entry.canonical == "Deutschrap"


# ── Preview ───────────────────────────────────────────────────────────


def test_plan_create_new_alias(tmp_path):
    mdir = _seed(tmp_path, {})
    plan = ma.plan_genre_alias_update("german rap", "Deutschrap", mdir)
    assert plan.change == "create"
    assert plan.key == "german rap"
    assert plan.canonical == "Deutschrap"
    assert plan.canonical_changed is True


def test_plan_unchanged(tmp_path):
    mdir = _seed(tmp_path, {"german rap": "Deutschrap"})
    plan = ma.plan_genre_alias_update("german rap", "Deutschrap", mdir)
    assert plan.change == "unchanged"
    assert plan.canonical_changed is False


def test_plan_update_canonical(tmp_path):
    mdir = _seed(tmp_path, {"german rap": "Deutschrap"})
    plan = ma.plan_genre_alias_update("german rap", "Hip Hop", mdir)
    assert plan.change == "update"
    assert plan.canonical_changed is True
    assert plan.canonical == "Hip Hop"


def test_plan_invalid_canonical_raises(tmp_path):
    mdir = _seed(tmp_path, {})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_alias_update("neu", "", mdir)


def test_plan_invalid_alias_raises(tmp_path):
    mdir = _seed(tmp_path, {})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_alias_update("", "Pop", mdir)


def test_plan_case_insensitive_keeps_original_key(tmp_path):
    mdir = _seed(tmp_path, {"DeutschRap": "Deutschrap"})
    plan = ma.plan_genre_alias_update("deutschrap", "Hip Hop", mdir)
    assert plan.change == "update"
    assert plan.key == "DeutschRap"  # Originalkey bleibt


# ── Apply ─────────────────────────────────────────────────────────────


def test_apply_create_writes_atomic(tmp_path):
    mdir = _seed(tmp_path, {})
    _, etag = ma.get_genre_alias("neu", mdir)
    plan, result = ma.apply_genre_alias_update(
        "neu", "Pop", mdir, expected_etag=etag,
    )
    assert result.written is True
    raw = _read(tmp_path)
    assert raw["neu"] == "Pop"


def test_apply_update_keeps_original_key(tmp_path):
    mdir = _seed(tmp_path, {"DeutschRap": "Deutschrap"})
    _, etag = ma.get_genre_alias("deutschrap", mdir)
    _, result = ma.apply_genre_alias_update(
        "deutschrap", "Hip Hop", mdir, expected_etag=etag,
    )
    assert result.written is True
    raw = _read(tmp_path)
    assert "DeutschRap" in raw
    assert raw["DeutschRap"] == "Hip Hop"


def test_apply_conflict_raises(tmp_path):
    mdir = _seed(tmp_path, {"existiert": "Pop"})
    with pytest.raises(ma.MappingConflictError):
        ma.apply_genre_alias_update(
            "existiert", "Rock", mdir, expected_etag="deadbeefdeadbeef",
        )


def test_apply_unchanged_no_write(tmp_path):
    mdir = _seed(tmp_path, {"existiert": "Pop"})
    _, etag = ma.get_genre_alias("existiert", mdir)
    _, result = ma.apply_genre_alias_update(
        "existiert", "Pop", mdir, expected_etag=etag,
    )
    assert result.written is False
    assert result.unchanged is True


def test_apply_missing_file_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    with pytest.raises(ma.MappingUnavailableError):
        ma.plan_genre_alias_update("neu", "Pop", mdir)


def test_etag_covers_canonical_value(tmp_path):
    """Etag muss sich aendern, wenn nur der canonical-Wert eines anderen
    Eintrags geaendert wird (Mapping-weiter Etag)."""
    mdir = _seed(tmp_path, {"a": "Pop", "b": "Rock"})
    _, etag1 = ma.get_genre_alias("a", mdir)
    ma.apply_genre_alias_update("b", "Metal", mdir, expected_etag=etag1)
    _, etag2 = ma.get_genre_alias("a", mdir)
    assert etag2 != etag1


def test_roundtrip_create_read_update(tmp_path):
    mdir = _seed(tmp_path, {})
    _, etag = ma.get_genre_alias("neu", mdir)
    ma.apply_genre_alias_update("neu", "Pop", mdir, expected_etag=etag)
    entry, etag2 = ma.get_genre_alias("neu", mdir)
    assert entry.canonical == "Pop"
    _, result = ma.apply_genre_alias_update("neu", "Rock", mdir, expected_etag=etag2)
    assert result.written is True
