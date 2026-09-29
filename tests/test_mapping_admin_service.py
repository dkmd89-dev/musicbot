# -*- coding: utf-8 -*-
"""M1 (2026-09-29): services/mapping_admin.py — Channel-Genre-Verwaltung."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma

FFMPEG = shutil.which("ffmpeg")  # nur damit einheitliches Skip-Muster möglich; hier nicht gebraucht


def _seed(tmp_path: Path, mapping: dict) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "channel_genre.yaml").write_text(
        yaml.safe_dump({ma.MAPPING_ROOT_KEY_CHANNEL_GENRE: mapping}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return mdir


def _read(tmp_path: Path) -> dict:
    raw = yaml.safe_load((tmp_path / "mapping" / "channel_genre.yaml").read_text(encoding="utf-8"))
    return raw[ma.MAPPING_ROOT_KEY_CHANNEL_GENRE]


# ── Liste + Einzeleintrag ───────────────────────────────────────────────


def test_list_returns_sorted_entries(tmp_path):
    mdir = _seed(tmp_path, {
        "Beta": {"primary": "Pop", "secondary": ["Dance"], "description": None},
        "alpha": {"primary": "Rock", "secondary": [], "description": "desc"},
    })
    entries = ma.list_channel_genres(mdir)
    assert [e.key for e in entries] == ["alpha", "Beta"]


def test_get_channel_genre_missing_key(tmp_path):
    mdir = _seed(tmp_path, {"existiert": {"primary": "Pop", "secondary": []}})
    entry, etag = ma.get_channel_genre("nicht-vorhanden", mdir)
    assert entry is None
    assert isinstance(etag, str) and len(etag) == 16


def test_get_channel_genre_case_insensitive_lookup(tmp_path):
    mdir = _seed(tmp_path, {"Kontor.TV": {"primary": "Electronic", "secondary": ["Dance"]}})
    entry, etag = ma.get_channel_genre("kontor.tv", mdir)
    assert entry is not None
    assert entry.key == "Kontor.TV"


# ── Preview ─────────────────────────────────────────────────────────────


def test_plan_create(tmp_path):
    mdir = _seed(tmp_path, {})
    plan = ma.plan_channel_genre_update("NeuerKanal", "Pop", ["Dance"], None, mdir)
    assert plan.change == "create"
    assert plan.existing is None
    assert plan.added == ["Dance"]
    assert plan.removed == []
    assert plan.primary_changed is True


def test_plan_unchanged(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": ["Dance"]}})
    plan = ma.plan_channel_genre_update("K", "Pop", ["Dance"], None, mdir)
    assert plan.change == "unchanged"


def test_plan_update_primary(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": ["Dance"]}})
    plan = ma.plan_channel_genre_update("K", "Rock", ["Dance"], None, mdir)
    assert plan.change == "update"
    assert plan.primary_changed is True
    assert plan.added == []
    assert plan.removed == []


def test_plan_update_secondary_added_removed(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": ["Dance", "Old"]}})
    plan = ma.plan_channel_genre_update("K", "Pop", ["Dance", "New"], None, mdir)
    assert plan.change == "update"
    assert plan.added == ["New"]
    assert plan.removed == ["Old"]


def test_plan_invalid_primary_raises(tmp_path):
    mdir = _seed(tmp_path, {})
    with pytest.raises(ma.MappingInvalidInputError):
        ma.plan_channel_genre_update("K", "", [], None, mdir)


def test_plan_secondary_dedup_and_warning(tmp_path):
    mdir = _seed(tmp_path, {})
    plan = ma.plan_channel_genre_update("K", "Pop", ["Dance", "dance", "POP"], None, mdir)
    assert plan.secondary == ["Dance"]
    assert any("Primary" in w for w in plan.warnings)
    assert any("doppelt" in w for w in plan.warnings)


# ── Apply ──────────────────────────────────────────────────────────────


def test_apply_create_writes_atomic(tmp_path):
    mdir = _seed(tmp_path, {})
    _, etag = ma.get_channel_genre("K", mdir)
    plan, result = ma.apply_channel_genre_update("K", "Pop", ["Dance"], "desc", mdir, expected_etag=etag)
    assert result.written is True
    assert result.unchanged is False
    raw = _read(tmp_path)
    assert raw["k"]["primary"] == "Pop"
    assert raw["k"]["secondary"] == ["Dance"]
    assert raw["k"]["description"] == "desc"
    assert plan.change == "create"


def test_apply_update_existing(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": ["Dance"]}})
    _, etag = ma.get_channel_genre("K", mdir)
    _, result = ma.apply_channel_genre_update("K", "Rock", ["Dance"], None, mdir, expected_etag=etag)
    assert result.written is True
    raw = _read(tmp_path)
    assert raw["K"]["primary"] == "Rock"


def test_apply_conflict_raises(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": []}})
    with pytest.raises(ma.MappingConflictError):
        ma.apply_channel_genre_update("K", "Rock", [], None, mdir, expected_etag="deadbeef")


def test_apply_unchanged_does_not_write(tmp_path):
    mdir = _seed(tmp_path, {"K": {"primary": "Pop", "secondary": ["Dance"], "description": None}})
    _, etag = ma.get_channel_genre("K", mdir)
    _, result = ma.apply_channel_genre_update("K", "Pop", ["Dance"], None, mdir, expected_etag=etag)
    assert result.written is False
    assert result.unchanged is True


def test_apply_missing_file_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    with pytest.raises(ma.MappingUnavailableError):
        ma.plan_channel_genre_update("K", "Pop", [], None, mdir)


def test_apply_corrupt_yaml_raises(tmp_path):
    mdir = tmp_path / "mapping"
    mdir.mkdir(parents=True)
    (mdir / "channel_genre.yaml").write_text("--- : [unbalanced", encoding="utf-8")
    with pytest.raises(ma.MappingUnavailableError):
        ma.plan_channel_genre_update("K", "Pop", [], None, mdir)


def test_unknown_mapping_id_raises(tmp_path):
    with pytest.raises(ma.MappingUnknownIdError):
        ma._get_descriptor("nicht-vorhanden")


def test_roundtrip_create_read_update(tmp_path):
    mdir = _seed(tmp_path, {})
    _, etag = ma.get_channel_genre("K", mdir)
    ma.apply_channel_genre_update("K", "Pop", ["Dance"], None, mdir, expected_etag=etag)
    entry, etag2 = ma.get_channel_genre("K", mdir)
    assert entry is not None
    assert entry.primary == "Pop"
    assert etag2 != etag
    _, result = ma.apply_channel_genre_update("K", "Rock", ["Dance"], None, mdir, expected_etag=etag2)
    assert result.written is True


def test_etag_changes_when_other_entry_added(tmp_path):
    """Create-Fall-Schutz: der Etag gilt für die ganze Datei — wenn ein
    anderer Eintrag zwischenzeitlich angelegt wird, ändert sich der Etag."""
    mdir = _seed(tmp_path, {})
    _, etag_before = ma.get_channel_genre("K", mdir)
    ma.apply_channel_genre_update("Anderer", "Pop", [], None, mdir, expected_etag=etag_before)
    _, etag_after = ma.get_channel_genre("K", mdir)
    assert etag_after != etag_before
