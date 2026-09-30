# -*- coding: utf-8 -*-
"""
Backup/Restore der Mapping-Administration (Service-Ebene).

Vor jedem Schreiben wird die bisherige Datei als Version abgelegt; ein Restore
ist ein normaler, Etag-geschuetzter Write, der die gewaehlte Version
unveraendert (inklusive Kommentaren) zurueckschreibt und dabei selbst wieder
eine Version anlegt. Versions-IDs kommen nur aus der Liste, nie als Pfad.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma
from services import mapping_backups as mb
from services import mapping_restore as mr

ALIASES_TEXT = "# Aliase\nGENRE_ALIASES:\n  rnb: R&B  # klassisch\n"


@pytest.fixture
def dirs(tmp_path):
    mdir = tmp_path / "mapping"
    bdir = tmp_path / "data" / "mapping_backups"
    mdir.mkdir()
    (mdir / "genre_aliases.yaml").write_text(ALIASES_TEXT, encoding="utf-8")
    return mdir, bdir


def _etag(mdir: Path) -> str:
    return ma.get_mapping_entry(ma.MAPPING_ID_GENRE_ALIASES, "__probe__", mdir)[1]


def _save(mdir, bdir, key, canonical):
    return ma.apply_mapping_update(
        ma.MAPPING_ID_GENRE_ALIASES, key, {"canonical": canonical}, mdir, _etag(mdir), backup_dir=bdir,
    )


def _text(mdir: Path) -> str:
    return (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")


# ── Backup vor jedem Schreiben ───────────────────────────────────────────


def test_write_stores_previous_file_verbatim_as_version(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "neo soulish", "Neo Soul")

    versions = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)

    assert len(versions) == 1
    assert mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, versions[0].version_id) == ALIASES_TEXT
    assert "neo soulish" in _text(mdir)  # neue Datei ist geschrieben
    assert "# Aliase" not in _text(mdir)  # Kommentar ging beim Rewrite verloren, lebt aber in der Version


def test_unchanged_write_creates_no_version(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "rnb", "R&B")  # identischer Inhalt

    assert mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES) == []


def test_versions_are_listed_newest_first_and_pruned_to_limit(dirs):
    mdir, bdir = dirs
    for n in range(mb.MAX_BACKUPS_PER_MAPPING + 3):
        _save(mdir, bdir, f"alias {n:02d}", f"Genre {n:02d}")

    versions = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)

    assert len(versions) == mb.MAX_BACKUPS_PER_MAPPING
    ids = [v.version_id for v in versions]
    assert ids == sorted(ids, reverse=True)
    newest = mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, ids[0])
    assert f"alias {mb.MAX_BACKUPS_PER_MAPPING + 1:02d}" in newest  # Stand direkt vor dem letzten Write


def test_failed_backup_aborts_the_write(dirs, tmp_path):
    mdir, _ = dirs
    blocker = tmp_path / "kein_verzeichnis"
    blocker.write_text("x", encoding="utf-8")  # Backup-Wurzel ist eine Datei -> mkdir scheitert
    etag = _etag(mdir)

    with pytest.raises(ma.MappingBackupError):
        ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "x", {"canonical": "Y"}, mdir, etag, backup_dir=blocker / "b")

    assert _text(mdir) == ALIASES_TEXT


def test_list_ignores_foreign_files(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "a", "A1")
    folder = bdir / ma.MAPPING_ID_GENRE_ALIASES
    (folder / "notizen.txt").write_text("x", encoding="utf-8")
    (folder / "20260101T000000_000000Z.yaml.tmp").write_text("x", encoding="utf-8")

    assert len(mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)) == 1


@pytest.mark.parametrize("bad", ["../etc/passwd", "..", "", "20260101", "20260101T000000_000000Z/../x", "x" * 300])
def test_version_id_is_never_used_as_a_path(dirs, bad):
    _, bdir = dirs
    with pytest.raises(mb.BackupNotFoundError):
        mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, bad)


def test_unknown_but_well_formed_version_is_not_found(dirs):
    _, bdir = dirs
    with pytest.raises(mb.BackupNotFoundError):
        mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, "20260101T000000_000000Z")


# ── Restore ──────────────────────────────────────────────────────────────


def test_restore_preview_lists_added_removed_and_changed(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "neo soulish", "Neo Soul")  # Version 1 = Ausgang (nur rnb)
    _save(mdir, bdir, "rnb", "Rhythm and Blues")
    v = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)[-1]  # aeltester Stand: nur rnb -> R&B

    plan = mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir)

    assert plan.change == "update"
    assert any("neo soulish" in r for r in plan.removed)          # verschwindet
    assert any("rnb" in c and "Rhythm and Blues" in c and "R&B" in c for c in plan.changed)
    assert plan.added == []
    assert plan.etag == _etag(mdir)


def test_restore_writes_version_verbatim_including_comments_and_creates_backup(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "neo soulish", "Neo Soul")
    v = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)[0]
    before_restore = _text(mdir)
    plan = mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir)

    _, result = mr.apply_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir, expected_etag=plan.etag)

    assert result.written is True
    assert _text(mdir) == ALIASES_TEXT
    assert result.new_etag == _etag(mdir)
    newest = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)[0]
    assert mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, newest.version_id) == before_restore  # Restore ist selbst umkehrbar


def test_restore_with_stale_etag_is_conflict_and_changes_nothing(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "a", "A1")
    v = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)[0]
    stale = mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir).etag
    _save(mdir, bdir, "b", "B1")  # zwischenzeitliche Aenderung
    current = _text(mdir)

    with pytest.raises(ma.MappingConflictError):
        mr.apply_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir, expected_etag=stale)

    assert _text(mdir) == current


def test_restoring_identical_text_is_unchanged_and_creates_no_version(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "a", "A1")
    v = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)[0]
    plan = mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir)
    mr.apply_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir, expected_etag=plan.etag)
    count = len(mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES))

    plan2 = mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir)
    _, result = mr.apply_restore(ma.MAPPING_ID_GENRE_ALIASES, v.version_id, mdir, bdir, expected_etag=plan2.etag)

    assert plan2.change == "unchanged" and result.written is False
    assert len(mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)) == count


def test_corrupt_version_is_refused_and_file_unchanged(dirs):
    mdir, bdir = dirs
    _save(mdir, bdir, "a", "A1")
    folder = bdir / ma.MAPPING_ID_GENRE_ALIASES
    bad_id = "20200101T000000_000000Z"
    (folder / f"{bad_id}.yaml").write_text("GENRE_ALIASES: [kaputt: :", encoding="utf-8")
    current = _text(mdir)

    with pytest.raises(ma.MappingInvalidInputError):
        mr.plan_restore(ma.MAPPING_ID_GENRE_ALIASES, bad_id, mdir, bdir)

    assert _text(mdir) == current


def test_unknown_mapping_id_is_rejected(dirs):
    mdir, bdir = dirs
    with pytest.raises(ma.MappingUnknownIdError):
        mr.plan_restore("../evil", "20260101T000000_000000Z", mdir, bdir)
    with pytest.raises(ma.MappingUnknownIdError):
        mb_list = mr.list_backup_versions("nicht-in-allowlist", bdir)


# ── Filter und Spezialkanaele ────────────────────────────────────────────


def test_filters_and_special_channels_are_backed_up_and_restorable(tmp_path):
    mdir, bdir = tmp_path / "mapping", tmp_path / "bk"
    mdir.mkdir()
    (mdir / "genre_filters.yaml").write_text("# Filter\nIGNORE_SECONDARY:\n- rock\n- indie\n", encoding="utf-8")
    (mdir / "special_channel.yaml").write_text(
        "# Prioritaet\nSPECIAL_CHANNELS:\n  Podcast:\n  - A\n  Playlist:\n  - B\n", encoding="utf-8",
    )
    ma.apply_genre_filter_update(["rock"], mdir, expected_etag=ma.get_genre_filter_state(mdir)[1], backup_dir=bdir)
    ma.apply_special_channels_update(
        [{"name": "Playlist", "channels": ["B"]}, {"name": "Podcast", "channels": ["A"]}], mdir,
        expected_etag=ma.get_special_channels_state(mdir)[1], backup_dir=bdir,
    )

    fv = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_FILTERS)[0]
    fplan = mr.plan_restore(ma.MAPPING_ID_GENRE_FILTERS, fv.version_id, mdir, bdir)
    assert fplan.added == ["indie: indie"] or any("indie" in a for a in fplan.added)
    mr.apply_restore(ma.MAPPING_ID_GENRE_FILTERS, fv.version_id, mdir, bdir, expected_etag=fplan.etag)
    assert ma.list_genre_filters(mdir) == ["rock", "indie"]

    sv = mb.list_versions(bdir, ma.MAPPING_ID_SPECIAL_CHANNELS)[0]
    splan = mr.plan_restore(ma.MAPPING_ID_SPECIAL_CHANNELS, sv.version_id, mdir, bdir)
    assert any("Podcast" in c for c in splan.changed)  # Prioritaet (Position) aendert sich
    mr.apply_restore(ma.MAPPING_ID_SPECIAL_CHANNELS, sv.version_id, mdir, bdir, expected_etag=splan.etag)
    assert [c.name for c in ma.list_special_channel_categories(mdir)] == ["Podcast", "Playlist"]
    assert "# Prioritaet" in (mdir / "special_channel.yaml").read_text(encoding="utf-8")
