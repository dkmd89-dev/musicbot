# tests/test_library_repair_cli_duplicate.py
# -*- coding: utf-8 -*-
"""scripts/library_repair.py --allow-delete: dockt an resolve_duplicates.py
an (kein eigener Loesch-Code) - hier nur der CLI-Wiring-Teil getestet,
subprocess.run() wird gemockt (kein echter Subprozess-Start, keine
Library-Beruehrung)."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "library_repair.py"

_spec = importlib.util.spec_from_file_location("library_repair_cli", MODULE_PATH)
lr = importlib.util.module_from_spec(_spec)
sys.modules["library_repair_cli"] = lr
_spec.loader.exec_module(lr)


@pytest.fixture
def fake_library(tmp_path):
    lib = tmp_path / "library"
    (lib / "SomeArtist").mkdir(parents=True)
    return lib


def test_allow_delete_without_artist_is_rejected(fake_library):
    with patch("sys.stderr"):
        exit_code = lr.main(["--allow-delete", "--library", str(fake_library)])
    assert exit_code == 2


def test_allow_delete_unknown_artist_dir_is_rejected(fake_library):
    with patch("sys.stderr"):
        exit_code = lr.main([
            "--allow-delete", "--artist", "DoesNotExist", "--library", str(fake_library),
        ])
    assert exit_code == 2


def test_allow_delete_dry_run_invokes_resolve_duplicates_without_execute(fake_library):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        exit_code = lr.main([
            "--allow-delete", "--artist", "SomeArtist", "--dry-run",
            "--library", str(fake_library),
        ])
    assert exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert str(lr.RESOLVE_DUPLICATES_SCRIPT) in cmd
    assert "--path" in cmd and str(fake_library / "SomeArtist") in cmd
    assert "--execute" not in cmd
    assert "--confirm-production-execute" not in cmd


def test_allow_delete_execute_passes_confirm_flag(fake_library):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        exit_code = lr.main([
            "--allow-delete", "--artist", "SomeArtist", "--library", str(fake_library),
        ])
    assert exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "--execute" in cmd
    assert "--confirm-production-execute" in cmd
    assert str(fake_library / "SomeArtist") in cmd


def test_allow_delete_scope_is_never_whole_library_root(fake_library):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        lr.main(["--allow-delete", "--artist", "SomeArtist", "--library", str(fake_library)])
    cmd = mock_run.call_args[0][0]
    path_arg = cmd[cmd.index("--path") + 1]
    assert path_arg == str(fake_library / "SomeArtist")
    assert path_arg != str(fake_library)


def test_allow_delete_forwards_backup_dir(fake_library, tmp_path):
    backup_dir = tmp_path / "custom_backups"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        lr.main([
            "--allow-delete", "--artist", "SomeArtist", "--dry-run",
            "--library", str(fake_library), "--backup-dir", str(backup_dir),
        ])
    cmd = mock_run.call_args[0][0]
    assert "--backup-dir" in cmd
    assert str(backup_dir) in cmd


def test_allow_delete_exit_code_propagates_from_subprocess(fake_library):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=3)
        exit_code = lr.main([
            "--allow-delete", "--artist", "SomeArtist", "--dry-run",
            "--library", str(fake_library),
        ])
    assert exit_code == 3
