# tests/test_library_repair_cli_maintenance.py
# -*- coding: utf-8 -*-
"""scripts/library_repair.py --maintenance-action (ARCH-032 Phase 3D) —
loest scripts/fix_artist_casing.py/remove_legacy_genre_atom.py/
set_genre.py ab. Echte, isolierte m4a-Testdateien (nie die
Produktions-Library, ARCH-032 Auftrag §21); Config.DATA_DIR/
GENRE_MAPPING_DIR werden auf tmp_path umgeleitet."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from mutagen.mp4 import MP4, MP4FreeForm

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "library_repair.py"

_spec = importlib.util.spec_from_file_location("library_repair_cli_maint", MODULE_PATH)
lr = importlib.util.module_from_spec(_spec)
sys.modules["library_repair_cli_maint"] = lr
_spec.loader.exec_module(lr)

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _m4a(path: Path, *, genre=None, artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )
    a = MP4(path)
    a["©nam"] = ["T"]
    if genre:
        a["©gen"] = [genre]
    if artist:
        a["©ART"] = artist if isinstance(artist, list) else [artist]
    a.save()


def _set_legacy_genre(path: Path, value: str) -> None:
    a = MP4(path)
    a["----:com.apple.iTunes:GENRE"] = [MP4FreeForm(value.encode("utf-8"))]
    a.save()


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    monkeypatch.setattr(lr.Config, "DATA_DIR", data_dir)
    monkeypatch.setattr(lr.Config, "GENRE_MAPPING_DIR", mapping_dir)
    return {"data_dir": data_dir, "mapping_dir": mapping_dir}


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


class TestArgumentValidation:
    def test_missing_target_selector_is_rejected(self, lib, env):
        lib.mkdir()
        exit_code = lr.main(["--maintenance-action", "artist-casing", "--library", str(lib)])
        assert exit_code == 2

    def test_unknown_artist_dir_produces_no_targets(self, lib, env):
        lib.mkdir()
        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--artist", "DoesNotExist",
            "--library", str(lib),
        ])
        assert exit_code == 2


@requires_ffmpeg
class TestArtistCasingCLI:
    def test_dry_run_default_writes_nothing(self, lib, env):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (env["mapping_dir"] / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--artist", "Bausa",
            "--library", str(lib),
        ])
        assert exit_code == 0
        assert MP4(p).tags["©ART"] == ["bausa"]

    def test_apply_writes_corrected_casing(self, lib, env):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (env["mapping_dir"] / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--artist", "Bausa",
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags["©ART"] == ["Bausa"]
        assert (env["data_dir"] / "library_repair_journal.jsonl").exists()

    def test_missing_casing_map_is_rejected(self, lib, env):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        # kein artist_overrides.json / case_preserve.yaml angelegt

        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--artist", "Bausa",
            "--library", str(lib),
        ])
        assert exit_code == 2

    def test_all_scans_whole_library(self, lib, env):
        p1 = lib / "Bausa" / "Singles" / "a.m4a"
        p2 = lib / "Filow" / "Singles" / "b.m4a"
        _m4a(p1, artist=["bausa"])
        _m4a(p2, artist=["Filow"])
        (env["mapping_dir"] / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--all",
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p1).tags["©ART"] == ["Bausa"]
        assert MP4(p2).tags["©ART"] == ["Filow"]  # unveraendert, kein Mapping-Treffer

    def test_path_targets_single_file(self, lib, env):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (env["mapping_dir"] / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        exit_code = lr.main([
            "--maintenance-action", "artist-casing", "--path", str(p),
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags["©ART"] == ["Bausa"]


@requires_ffmpeg
class TestLegacyGenreCleanupCLI:
    def test_apply_removes_legacy_atom(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p, genre="Pop")
        _set_legacy_genre(p, "Pop")

        exit_code = lr.main([
            "--maintenance-action", "legacy-genre-cleanup", "--artist", "Filow",
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags.get("----:com.apple.iTunes:GENRE") is None


@requires_ffmpeg
class TestSetGenreCLI:
    def test_manual_genre_requires_dash_dash_genre_or_mapping(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--library", str(lib),
        ])
        assert exit_code == 2

    def test_apply_with_manual_genre(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--genre", "Deutschrap; Trap", "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags["©gen"] == ["Deutschrap; Trap"]

    def test_apply_from_mapping(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        (env["mapping_dir"] / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {"filow": {"primary": "Deutschrap"}}}),
            encoding="utf-8",
        )
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--from-mapping", "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags["©gen"] == ["Deutschrap"]

    def test_from_mapping_unknown_artist_is_rejected(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        (env["mapping_dir"] / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {}}), encoding="utf-8"
        )
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--from-mapping", "--library", str(lib),
        ])
        assert exit_code == 2

    def test_only_if_missing_skips_existing_genre(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p, genre="Existing")
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--genre", "Pop", "--only-if-missing", "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        assert MP4(p).tags["©gen"] == ["Existing"]

    def test_update_manual_mapping_writes_yaml(self, lib, env):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        (env["mapping_dir"] / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {}}), encoding="utf-8"
        )
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--genre", "Deutschrap; Trap", "--update-manual-mapping",
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0
        data = yaml.safe_load((env["mapping_dir"] / "artist_genre.yaml").read_text())
        assert data["ARTIST_GENRE_MAP"]["filow"]["primary"] == "Deutschrap"
        assert data["ARTIST_GENRE_MAP"]["filow"]["secondary"] == ["Trap"]

    def test_update_manual_mapping_with_from_mapping_is_rejected(self, lib, env, capsys):
        """--from-mapping + --update-manual-mapping ist redundant (das
        Mapping kommt ja bereits von dort) - identische Regel wie im
        abgeloesten scripts/set_genre.py."""
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        (env["mapping_dir"] / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {"filow": {"primary": "Deutschrap"}}}),
            encoding="utf-8",
        )
        exit_code = lr.main([
            "--maintenance-action", "set-genre", "--artist", "Filow",
            "--from-mapping", "--update-manual-mapping",
            "--library", str(lib), "--apply",
        ])
        assert exit_code == 0  # Tag-Write selbst gelingt, nur Mapping-Update wird uebersprungen
        out = capsys.readouterr().out
        assert "--update-manual-mapping erfordert" in out
