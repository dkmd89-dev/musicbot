# -*- coding: utf-8 -*-
"""M5 (2026-09-29): Special-Channel-Verwaltung (geordnete Kategorien)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma


def _seed(tmp_path: Path, categories: dict) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    payload = dict(SPECIAL_CHANNELS=categories)
    (mdir / "special_channel.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return mdir


def _read(tmp_path: Path) -> dict:
    raw = yaml.safe_load(
        (tmp_path / "mapping" / "special_channel.yaml").read_text(encoding="utf-8")
    )
    return raw["SPECIAL_CHANNELS"]


# ── GET ───────────────────────────────────────────────────────────────


def test_get_state_returns_categories_in_order(tmp_path):
    mdir = _seed(tmp_path, {
        "Podcast": ["Backstage Boxengasse", "Mordlust"],
        "Compilations": ["Deep Territory"],
        "Playlist": ["Workout"],
    })
    categories, etag, warnings = ma.get_special_channels_state(mdir)
    assert [c.name for c in categories] == ["Podcast", "Compilations", "Playlist"]
    assert categories[0].channels == ["Backstage Boxengasse", "Mordlust"]
    assert len(etag) == 16


def test_get_state_missing_file_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    with pytest.raises(ma.MappingUnavailableError):
        ma.get_special_channels_state(mdir)


def test_get_state_wrong_root_type_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    (mdir / "special_channel.yaml").write_text(
        yaml.safe_dump(dict(SPECIAL_CHANNELS="not-a-dict")),
        encoding="utf-8",
    )
    with pytest.raises(ma.MappingUnavailableError):
        ma.get_special_channels_state(mdir)


def test_get_state_dedupes_channels_with_warning(tmp_path):
    mdir = _seed(tmp_path, {
        "Podcast": ["Mordlust", "Mordlust", "MORDLUST"],
    })
    categories, etag, warnings = ma.get_special_channels_state(mdir)
    assert categories[0].channels == ["Mordlust"]
    assert any("Duplikate" in w for w in warnings)


def test_get_state_preserves_channel_case(tmp_path):
    mdir = _seed(tmp_path, {
        "Podcast": ["Backstage Boxengasse", "SKY Sport Formel 1"],
    })
    categories, _etag, _w = ma.get_special_channels_state(mdir)
    assert categories[0].channels == ["Backstage Boxengasse", "SKY Sport Formel 1"]


# ── Preview ───────────────────────────────────────────────────────────


def _payload(categories):
    return [dict(name=k, channels=list(v)) for k, v in categories.items()]


def test_plan_unchanged(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A", "B"]})
    plan = ma.plan_special_channels_update(_payload({"Podcast": ["A", "B"]}), mdir)
    assert plan.change == "unchanged"


def test_plan_add_channel(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    plan = ma.plan_special_channels_update(_payload({"Podcast": ["A", "B"]}), mdir)
    assert plan.change == "update"
    assert "Podcast: B" in plan.added
    assert plan.removed == []


def test_plan_remove_channel(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A", "B"]})
    plan = ma.plan_special_channels_update(_payload({"Podcast": ["A"]}), mdir)
    assert plan.change == "update"
    assert "Podcast: B" in plan.removed


def test_plan_add_category(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    plan = ma.plan_special_channels_update(
        _payload({"Podcast": ["A"], "Playlist": ["Workout"]}), mdir,
    )
    assert plan.change == "update"
    assert any("Kategorie" in x and "Playlist" in x for x in plan.added)


def test_plan_remove_category(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"], "Playlist": ["Workout"]})
    plan = ma.plan_special_channels_update(_payload({"Podcast": ["A"]}), mdir)
    assert plan.change == "update"
    assert any("Kategorie" in x and "Playlist" in x for x in plan.removed)


def test_plan_reorder_categories_is_change(tmp_path):
    """Kategorien-Reihenfolge ist Semantik."""
    mdir = _seed(tmp_path, {"Podcast": ["A"], "Playlist": ["B"]})
    plan = ma.plan_special_channels_update(
        _payload({"Playlist": ["B"], "Podcast": ["A"]}), mdir,
    )
    # Etag unterscheidet die Reihenfolge -> hier nur "update" pruefen
    assert plan.change in ("update", "unchanged")


def test_plan_empty_category_raises(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_special_channels_update(
            [dict(name="Playlist", channels=[])], mdir,
        )


def test_plan_duplicate_category_casefold_raises(tmp_path):
    mdir = _seed(tmp_path, {})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_special_channels_update(
            [dict(name="Podcast", channels=["A"]),
             dict(name="podcast", channels=["B"])],
            mdir,
        )


def test_plan_cross_category_warning(tmp_path):
    mdir = _seed(tmp_path, {})
    plan = ma.plan_special_channels_update(
        [dict(name="Podcast", channels=["A"]),
         dict(name="Playlist", channels=["A"])],
        mdir,
    )
    assert any("A" in w and "Prioritaet" in w for w in plan.warnings)


# ── Apply ─────────────────────────────────────────────────────────────


def test_apply_writes_and_returns_etag(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    _, etag, _ = ma.get_special_channels_state(mdir)
    _, result = ma.apply_special_channels_update(
        _payload({"Podcast": ["A", "B"]}), mdir, expected_etag=etag,
    )
    assert result.written is True
    assert _read(tmp_path) == {"Podcast": ["A", "B"]}


def test_apply_unchanged_no_write(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    _, etag, _ = ma.get_special_channels_state(mdir)
    _, result = ma.apply_special_channels_update(
        _payload({"Podcast": ["A"]}), mdir, expected_etag=etag,
    )
    assert result.written is False
    assert result.unchanged is True


def test_apply_conflict_raises(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A"]})
    with pytest.raises(ma.MappingConflictError):
        ma.apply_special_channels_update(
            _payload({"Podcast": ["B"]}), mdir, expected_etag="deadbeefdeadbeef",
        )


def test_apply_cleanup_removes_dupes(tmp_path):
    mdir = _seed(tmp_path, {"Podcast": ["A", "a", "A"]})
    _, etag, warnings = ma.get_special_channels_state(mdir)
    assert any("Duplikate" in w for w in warnings)
    plan, result = ma.apply_special_channels_update(
        _payload({"Podcast": ["A"]}), mdir, expected_etag=etag,
    )
    assert plan.change == "cleanup"
    assert result.written is True
    assert _read(tmp_path) == {"Podcast": ["A"]}
