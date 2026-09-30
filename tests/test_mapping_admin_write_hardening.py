# -*- coding: utf-8 -*-
"""
Schreib-Haertung der Mapping-Administration: atomarer Write mit eindeutigem
tmp-Namen, fsync, Aufraeumen bei Fehler, erhaltene Dateirechte und eine
Cross-Process-Sperre gegen gleichzeitige Schreiber (Bot- und Control-Center-
Prozess). Alle fuenf Mapping-Typen laufen ueber denselben Schreibpfad.
"""
from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma
from utils.file_lock import cross_process_lock


def _seed(tmp_path: Path) -> Path:
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    (mdir / "genre_aliases.yaml").write_text(
        yaml.safe_dump({"GENRE_ALIASES": {"rnb": "R&B"}}, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    return mdir


def _etag(mdir: Path) -> str:
    return ma.get_mapping_entry(ma.MAPPING_ID_GENRE_ALIASES, "__probe__", mdir)[1]


def _save(mdir: Path, key: str = "neo soulish", canonical: str = "Neo Soul"):
    return ma.apply_mapping_update(
        ma.MAPPING_ID_GENRE_ALIASES, key, {"canonical": canonical}, mdir, _etag(mdir),
    )


def _read(mdir: Path) -> dict:
    return yaml.safe_load((mdir / "genre_aliases.yaml").read_text(encoding="utf-8"))["GENRE_ALIASES"]


def _leftovers(mdir: Path) -> list:
    return sorted(p.name for p in mdir.iterdir() if p.suffix == ".tmp" or p.name.endswith(".tmp"))


# ── Atomarer Write ───────────────────────────────────────────────────────


def test_write_uses_unique_tmp_name_and_leaves_foreign_tmp_untouched(tmp_path):
    mdir = _seed(tmp_path)
    stale = mdir / "genre_aliases.yaml.tmp"
    stale.write_text("STALE", encoding="utf-8")  # z. B. Rest eines abgestuerzten Schreibers

    _save(mdir)

    assert _read(mdir)["neo soulish"] == "Neo Soul"
    assert stale.read_text(encoding="utf-8") == "STALE"


def test_write_fsyncs_file_and_directory(tmp_path, monkeypatch):
    mdir = _seed(tmp_path)
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(os.fstat(fd).st_mode), real_fsync(fd))[1])

    _save(mdir)

    modes = [stat.S_ISDIR(m) for m in synced]
    assert True in modes and False in modes  # Datei UND Verzeichnis


def test_failed_replace_leaves_original_intact_and_no_tmp(tmp_path, monkeypatch):
    mdir = _seed(tmp_path)
    before = (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")
    etag = _etag(mdir)

    def boom(src, dst):
        raise OSError("Platte voll")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "x", {"canonical": "Y"}, mdir, etag)

    assert (mdir / "genre_aliases.yaml").read_text(encoding="utf-8") == before
    assert _leftovers(mdir) == []


def test_failed_write_leaves_no_tmp(tmp_path, monkeypatch):
    mdir = _seed(tmp_path)
    etag = _etag(mdir)

    def boom(fd):
        raise OSError("fsync fehlgeschlagen")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "x", {"canonical": "Y"}, mdir, etag)

    assert _leftovers(mdir) == []
    assert _read(mdir) == {"rnb": "R&B"}


def test_existing_file_mode_is_preserved(tmp_path):
    mdir = _seed(tmp_path)
    path = mdir / "genre_aliases.yaml"
    path.chmod(0o640)

    _save(mdir)

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


# ── Alle Schreibpfade nutzen die Haertung ────────────────────────────────


def test_list_and_category_writers_use_the_same_hardened_path(tmp_path, monkeypatch):
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    (mdir / "genre_filters.yaml").write_text(yaml.safe_dump({"IGNORE_SECONDARY": ["rock"]}), encoding="utf-8")
    (mdir / "special_channel.yaml").write_text(
        yaml.safe_dump({"SPECIAL_CHANNELS": {"Podcast": ["A"]}}), encoding="utf-8",
    )
    (mdir / "special_channel.yaml.tmp").write_text("STALE", encoding="utf-8")
    (mdir / "genre_filters.yaml.tmp").write_text("STALE", encoding="utf-8")

    f_etag = ma.get_genre_filter_state(mdir)[1]
    ma.apply_genre_filter_update(["rock", "indie"], mdir, expected_etag=f_etag)
    s_etag = ma.get_special_channels_state(mdir)[1]
    ma.apply_special_channels_update([{"name": "Podcast", "channels": ["A", "B"]}], mdir, expected_etag=s_etag)

    assert (mdir / "special_channel.yaml.tmp").read_text(encoding="utf-8") == "STALE"
    assert (mdir / "genre_filters.yaml.tmp").read_text(encoding="utf-8") == "STALE"
    assert ma.list_genre_filters(mdir) == ["rock", "indie"]


# ── Cross-Process-Sperre ─────────────────────────────────────────────────


def _blocked_until_released(mdir: Path, apply_fn) -> None:
    held, release, done = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def holder():
        with cross_process_lock(mdir / "genre_aliases.yaml"):
            held.set()
            release.wait(10)

    def writer():
        try:
            apply_fn()
        except Exception as e:  # pragma: no cover - Fehlerpfad wird unten geprueft
            errors.append(e)
        finally:
            done.set()

    t_hold = threading.Thread(target=holder)
    t_hold.start()
    assert held.wait(5)
    t_write = threading.Thread(target=writer)
    t_write.start()

    time.sleep(0.4)
    assert not done.is_set(), "Schreiber ist trotz gehaltener Cross-Process-Sperre durchgelaufen"
    release.set()
    assert done.wait(10)
    t_hold.join(); t_write.join()
    assert errors == []


def test_writer_waits_for_cross_process_lock_on_the_mapping_file(tmp_path):
    mdir = _seed(tmp_path)
    etag = _etag(mdir)

    _blocked_until_released(
        mdir,
        lambda: ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "neo soulish", {"canonical": "Neo Soul"}, mdir, etag),
    )

    assert _read(mdir)["neo soulish"] == "Neo Soul"


def test_second_writer_with_stale_etag_gets_conflict_and_does_not_overwrite(tmp_path):
    mdir = _seed(tmp_path)
    etag = _etag(mdir)
    ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "a", {"canonical": "A1"}, mdir, etag)

    with pytest.raises(ma.MappingConflictError):
        ma.apply_mapping_update(ma.MAPPING_ID_GENRE_ALIASES, "b", {"canonical": "B1"}, mdir, etag)

    assert _read(mdir) == {"rnb": "R&B", "a": "A1"}


def test_lock_file_is_ignored_by_git():
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "mapping/*.lock" in ignore
