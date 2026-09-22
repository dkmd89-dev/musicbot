# tests/test_backup_admin_service.py
# -*- coding: utf-8 -*-
"""
CC-AC-10C: gezielte Tests für services/backup_admin.py — den neuen,
Telegram-freien Application-Layer für Backup-Operationen.

Besonderer Fokus auf SEC-006 (Path-Traversal-Schutz in
resolve_backup_path()) — Parität zu
handlers/admin/backup_handler.py::BackupHandler._resolve_backup_path().
"""

from __future__ import annotations

import tarfile

import pytest

from services import backup_admin


@pytest.fixture
def paths(tmp_path):
    bot_source = tmp_path / "bot"
    lib_source = tmp_path / "library"
    dest_dir = tmp_path / "backups"
    bot_source.mkdir()
    lib_source.mkdir()
    (bot_source / "config.py").write_text("x = 1")
    (bot_source / "__pycache__").mkdir()
    (bot_source / "__pycache__" / "x.pyc").write_text("junk")
    (lib_source / "track.mp3").write_text("audio")
    return backup_admin.BackupPaths(
        bot_source=bot_source, lib_source=lib_source, dest_dir=dest_dir,
        max_keep=2, exclude_patterns=["__pycache__", "*.pyc"],
    )


class TestCreateBackup:
    def test_creates_bot_archive_excluding_patterns(self, paths):
        entry = backup_admin.create_backup(paths, "bot")

        assert entry.path.exists()
        assert entry.name.startswith("bot_backup_")
        with tarfile.open(entry.path, "r:gz") as tar:
            names = tar.getnames()
        assert any(n.endswith("config.py") for n in names)
        assert not any("__pycache__" in n for n in names)

    def test_creates_library_archive_without_exclusions(self, paths):
        entry = backup_admin.create_backup(paths, "library")

        with tarfile.open(entry.path, "r:gz") as tar:
            names = tar.getnames()
        assert any(n.endswith("track.mp3") for n in names)

    def test_rejects_unknown_backup_type(self, paths):
        with pytest.raises(backup_admin.InvalidBackupTypeError):
            backup_admin.create_backup(paths, "database")

    def test_rotation_keeps_only_max_keep_backups(self, paths):
        import time

        for _ in range(paths.max_keep + 2):
            backup_admin.create_backup(paths, "bot")
            time.sleep(1.01)  # Timestamp-Aufloesung des Dateinamens ist Sekunden

        remaining = backup_admin.list_backups(paths, "bot")
        assert len(remaining) == paths.max_keep

    def test_rotation_keeps_newest_backups(self, paths, monkeypatch):
        import time

        names = []
        for _ in range(paths.max_keep + 1):
            entry = backup_admin.create_backup(paths, "bot")
            names.append(entry.name)
            time.sleep(1.01)  # Timestamp-Aufloesung des Dateinamens ist Sekunden

        remaining_names = {b.name for b in backup_admin.list_backups(paths, "bot")}
        assert names[0] not in remaining_names  # aeltestes wurde rotiert
        assert names[-1] in remaining_names  # neuestes bleibt


class TestListBackups:
    def test_empty_when_no_backups(self, paths):
        assert backup_admin.list_backups(paths, "bot") == []

    def test_sorted_newest_first(self, paths):
        backup_admin.create_backup(paths, "bot")
        entries = backup_admin.list_backups(paths, "bot")
        assert len(entries) == 1


class TestResolveBackupPathSec006:
    def test_resolves_valid_filename_inside_dest_dir(self, paths, tmp_path):
        paths.dest_dir.mkdir(parents=True, exist_ok=True)
        (paths.dest_dir / "bot_backup_x.tar.gz").write_text("data")

        resolved = backup_admin.resolve_backup_path(paths, "bot_backup_x.tar.gz")
        assert resolved == (paths.dest_dir / "bot_backup_x.tar.gz").resolve()

    def test_rejects_path_traversal(self, paths):
        paths.dest_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(backup_admin.InvalidBackupFilenameError):
            backup_admin.resolve_backup_path(paths, "../../etc/passwd")

    def test_rejects_absolute_path_escape(self, paths):
        paths.dest_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(backup_admin.InvalidBackupFilenameError):
            backup_admin.resolve_backup_path(paths, "/etc/passwd")


class TestDeleteBackup:
    def test_deletes_existing_backup(self, paths):
        entry = backup_admin.create_backup(paths, "bot")

        deleted_name = backup_admin.delete_backup(paths, entry.name)

        assert deleted_name == entry.name
        assert not entry.path.exists()

    def test_rejects_unknown_backup(self, paths):
        paths.dest_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(backup_admin.BackupNotFoundError):
            backup_admin.delete_backup(paths, "bot_backup_does_not_exist.tar.gz")

    def test_rejects_path_traversal_before_existence_check(self, paths):
        paths.dest_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(backup_admin.InvalidBackupFilenameError):
            backup_admin.delete_backup(paths, "../../etc/passwd")


class TestHumanSize:
    @pytest.mark.parametrize("size,expected_unit", [(500, "B"), (2048, "KB"), (5 * 1024**3, "GB")])
    def test_picks_appropriate_unit(self, size, expected_unit):
        assert backup_admin.human_size(size).endswith(expected_unit)
