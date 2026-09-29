# -*- coding: utf-8 -*-
"""M4 (2026-09-29): Genre-Filter-Verwaltung (Liste statt Entry)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma


def _seed(tmp_path: Path, values: list) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    payload = dict(IGNORE_SECONDARY=list(values))
    (mdir / "genre_filters.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return mdir


def _read(tmp_path: Path) -> list:
    raw = yaml.safe_load((tmp_path / "mapping" / "genre_filters.yaml").read_text(encoding="utf-8"))
    return raw["IGNORE_SECONDARY"]


# ── GET ───────────────────────────────────────────────────────────────


def test_get_state_returns_values_and_etag(tmp_path):
    mdir = _seed(tmp_path, ["rock", "indie", "pop"])
    values, etag, warnings = ma.get_genre_filter_state(mdir)
    assert values == ["rock", "indie", "pop"]
    assert isinstance(etag, str) and len(etag) == 16
    assert warnings == []


def test_get_state_normalizes_case_and_strips(tmp_path):
    mdir = _seed(tmp_path, ["Rock", "  Indie  ", "POP"])
    values, etag, warnings = ma.get_genre_filter_state(mdir)
    assert values == ["rock", "indie", "pop"]


def test_get_state_deduplicates_with_warning(tmp_path):
    mdir = _seed(tmp_path, ["rock", "Rock", "ROCK", "indie"])
    values, etag, warnings = ma.get_genre_filter_state(mdir)
    assert values == ["rock", "indie"]
    assert any("Duplikate" in w for w in warnings)


def test_get_state_order_matters_for_etag(tmp_path):
    """["rock","indie"] und ["indie","rock"] haben verschiedene Etags."""
    mdir_a = _seed(tmp_path / "a", ["rock", "indie"])
    mdir_b = _seed(tmp_path / "b", ["indie", "rock"])
    _, etag_a, _ = ma.get_genre_filter_state(mdir_a)
    _, etag_b, _ = ma.get_genre_filter_state(mdir_b)
    assert etag_a != etag_b


def test_get_state_missing_file_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    with pytest.raises(ma.MappingUnavailableError):
        ma.get_genre_filter_state(mdir)


def test_get_state_wrong_type_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    (mdir / "genre_filters.yaml").write_text(
        yaml.safe_dump(dict(IGNORE_SECONDARY="not-a-list")),
        encoding="utf-8",
    )
    with pytest.raises(ma.MappingUnavailableError):
        ma.get_genre_filter_state(mdir)


# ── Preview ───────────────────────────────────────────────────────────


def test_plan_unchanged(tmp_path):
    mdir = _seed(tmp_path, ["rock", "indie"])
    plan = ma.plan_genre_filter_update(["rock", "indie"], mdir)
    assert plan.change == "unchanged"
    assert plan.added == []
    assert plan.removed == []


def test_plan_add(tmp_path):
    mdir = _seed(tmp_path, ["rock"])
    plan = ma.plan_genre_filter_update(["rock", "indie"], mdir)
    assert plan.change == "update"
    assert plan.added == ["indie"]
    assert plan.removed == []


def test_plan_remove(tmp_path):
    mdir = _seed(tmp_path, ["rock", "indie"])
    plan = ma.plan_genre_filter_update(["rock"], mdir)
    assert plan.change == "update"
    assert plan.added == []
    assert plan.removed == ["indie"]


def test_plan_case_insensitive_diff(tmp_path):
    """'ROCK' im Input entspricht 'rock' in der Datei — kein added/removed."""
    mdir = _seed(tmp_path, ["rock"])
    plan = ma.plan_genre_filter_update(["ROCK"], mdir)
    assert plan.added == []
    assert plan.removed == []
    assert plan.values == ["rock"]


def test_plan_invalid_empty_raises(tmp_path):
    mdir = _seed(tmp_path, [])
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_filter_update(["", "rock"], mdir)


def test_plan_invalid_non_list_raises(tmp_path):
    mdir = _seed(tmp_path, [])
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_filter_update("not-a-list", mdir)


def test_plan_invalid_too_long_raises(tmp_path):
    mdir = _seed(tmp_path, [])
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_genre_filter_update(["x" * 101], mdir)


# ── Apply ─────────────────────────────────────────────────────────────


def test_apply_writes_and_returns_new_etag(tmp_path):
    mdir = _seed(tmp_path, ["rock"])
    _, etag, _ = ma.get_genre_filter_state(mdir)
    _, result = ma.apply_genre_filter_update(["rock", "indie"], mdir, expected_etag=etag)
    assert result.written is True
    assert result.unchanged is False
    assert result.values == ["rock", "indie"]
    assert _read(tmp_path) == ["rock", "indie"]


def test_apply_unchanged_no_write(tmp_path):
    mdir = _seed(tmp_path, ["rock", "indie"])
    _, etag, _ = ma.get_genre_filter_state(mdir)
    _, result = ma.apply_genre_filter_update(["rock", "indie"], mdir, expected_etag=etag)
    assert result.written is False
    assert result.unchanged is True


def test_apply_conflict_raises(tmp_path):
    mdir = _seed(tmp_path, ["rock"])
    with pytest.raises(ma.MappingConflictError):
        ma.apply_genre_filter_update(["indie"], mdir, expected_etag="deadbeefdeadbeef")


def test_apply_normalizes_new_entries(tmp_path):
    mdir = _seed(tmp_path, [])
    _, etag, _ = ma.get_genre_filter_state(mdir)
    ma.apply_genre_filter_update(["  Rock  ", "INDIE"], mdir, expected_etag=etag)
    assert _read(tmp_path) == ["rock", "indie"]


def test_apply_writes_duplicates_removed(tmp_path):
    """Legacy-Duplikate in der Datei werden bei PUT bereinigt."""
    mdir = _seed(tmp_path, ["rock", "Rock", "ROCK", "indie"])
    _, etag, warnings = ma.get_genre_filter_state(mdir)
    # Etag basiert auf der normalisierten Sicht -> dieselbe wie ohne Dupes
    mdir_clean = _seed(tmp_path / "clean", ["rock", "indie"])
    _, etag_clean, _ = ma.get_genre_filter_state(mdir_clean)
    assert etag == etag_clean

    _, result = ma.apply_genre_filter_update(["rock", "indie"], mdir, expected_etag=etag)
    assert result.written is True
    assert _read(tmp_path) == ["rock", "indie"]


def test_list_shim_returns_values(tmp_path):
    mdir = _seed(tmp_path, ["rock", "indie"])
    assert ma.list_genre_filters(mdir) == ["rock", "indie"]
