"""
Characterization-Tests fuer handlers/admin/backup_handler.py
(BackupHandler) - 509 Zeilen, vorher 0 Tests.

SEC-006 (docs/archive/MusicBot_ENGINEERING_BASELINE.md): confirm_delete() und
delete_backup() bauten filepath = self.dest_dir / filename, wobei
filename unvalidiert aus callback_data kommt
(backup_delete_<filename> / backup_delete_confirm_<filename> - Telegram
callback_data ist ein von jedem Client frei sendbarer String, siehe
SEC-003/SEC-005). pathlib.Path.__truediv__ hat zwei Faellen:
1. ".."-Traversal (dest_dir / "../../etc/passwd") wird beim Aufloesen
   (.resolve()) tatsaechlich ausserhalb von dest_dir aufgeloest.
2. Ein ABSOLUTER rechter Operand verwirft den linken Teil komplett:
   Path("/a/b") / "/etc/passwd" == Path("/etc/passwd") - live verifiziert.
delete_backup() ruft filepath.unlink() auf diesem unvalidierten Pfad auf -
jeder Admin (nicht nur der Owner, siehe SEC-005-Kontext) haette so
beliebige, vom Bot-Prozess beschreibbare Dateien loeschen koennen, nicht
nur Backups (z.B. config.py, .env, Musikdateien, Logs).

Fix: neue _resolve_backup_path() validiert per .resolve() +
is_relative_to() analog zum bereits bestehenden SEC-003-Fix in
handlers/enhanced_logger_menu_handler.py.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.admin.backup_handler import BackupHandler


class FakeConfig:
    def __init__(self, tmp_path):
        self.BACKUP_BOT_SOURCE_DIR = str(tmp_path / "bot_source")
        self.BACKUP_LIBRARY_SOURCE_DIR = str(tmp_path / "lib_source")
        self.BACKUP_DEST_DIR = str(tmp_path / "backups")
        self.BACKUP_MAX_KEEP = 3


def _make_handler(tmp_path):
    config = FakeConfig(tmp_path)
    Path(config.BACKUP_BOT_SOURCE_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.BACKUP_LIBRARY_SOURCE_DIR).mkdir(parents=True, exist_ok=True)
    return BackupHandler(config)


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestResolveBackupPathSec006:
    def test_normal_filename_resolves_inside_dest_dir(self, tmp_path):
        handler = _make_handler(tmp_path)
        (handler.dest_dir / "bot_backup_20260101_000000.tar.gz").write_bytes(b"x")

        result = handler._resolve_backup_path("bot_backup_20260101_000000.tar.gz")

        assert result is not None
        assert result.parent == handler.dest_dir.resolve()

    def test_dotdot_traversal_is_rejected(self, tmp_path):
        handler = _make_handler(tmp_path)
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("top secret")

        traversal = f"../{secret_file.name}"
        result = handler._resolve_backup_path(traversal)

        assert result is None

    def test_deep_dotdot_traversal_to_etc_passwd_is_rejected(self, tmp_path):
        handler = _make_handler(tmp_path)
        result = handler._resolve_backup_path("../../../../../../etc/passwd")
        assert result is None

    def test_absolute_path_override_is_rejected(self, tmp_path):
        """
        Der gefaehrlichste Fall: Path(dest_dir) / "/etc/passwd" verwirft
        dest_dir komplett und ergibt exakt "/etc/passwd" - ohne Fix haette
        delete_backup() dann unlink() auf einer beliebigen absoluten
        Systemdatei aufgerufen.
        """
        handler = _make_handler(tmp_path)
        result = handler._resolve_backup_path("/etc/passwd")
        assert result is None


class TestDeleteBackupSec006Regression:
    def test_delete_backup_refuses_traversal_filename(self, tmp_path):
        handler = _make_handler(tmp_path)
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("top secret")

        update = make_update()
        context = make_context()

        asyncio.run(
            handler.delete_backup(update, context, f"../{secret_file.name}")
        )

        assert secret_file.exists()  # NICHT geloescht
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Ungültiger Dateiname" in text

    def test_delete_backup_refuses_absolute_path_filename(self, tmp_path):
        handler = _make_handler(tmp_path)
        victim_file = tmp_path / "victim.txt"
        victim_file.write_text("do not delete me")

        update = make_update()
        context = make_context()

        asyncio.run(handler.delete_backup(update, context, str(victim_file)))

        assert victim_file.exists()  # NICHT geloescht

    def test_delete_backup_still_deletes_legitimate_backup(self, tmp_path):
        handler = _make_handler(tmp_path)
        backup_file = handler.dest_dir / "bot_backup_20260101_000000.tar.gz"
        backup_file.write_bytes(b"fake archive")

        update = make_update()
        context = make_context()

        asyncio.run(handler.delete_backup(update, context, backup_file.name))

        assert not backup_file.exists()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "gelöscht" in text

    def test_confirm_delete_refuses_traversal_filename(self, tmp_path):
        handler = _make_handler(tmp_path)

        update = make_update()
        context = make_context()

        asyncio.run(handler.confirm_delete(update, context, "../../etc/passwd"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Ungültiger Dateiname" in text


class TestListBackups:
    def test_lists_only_matching_type_prefix(self, tmp_path):
        handler = _make_handler(tmp_path)
        (handler.dest_dir / "bot_backup_20260101_000000.tar.gz").write_bytes(b"x")
        (handler.dest_dir / "library_backup_20260101_000000.tar.gz").write_bytes(b"x")

        bot_backups = handler._list_backups("bot")
        lib_backups = handler._list_backups("library")

        assert len(bot_backups) == 1
        assert len(lib_backups) == 1
        assert bot_backups[0]["name"].startswith("bot_backup_")

    def test_sorted_newest_first(self, tmp_path):
        import os
        import time

        handler = _make_handler(tmp_path)
        old = handler.dest_dir / "bot_backup_old.tar.gz"
        new = handler.dest_dir / "bot_backup_new.tar.gz"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        now = time.time()
        os.utime(old, (now - 100, now - 100))
        os.utime(new, (now, now))

        backups = handler._list_backups("bot")
        assert backups[0]["name"] == "bot_backup_new.tar.gz"


class TestRotateBackups:
    def test_oldest_backups_removed_when_exceeding_max_keep(self, tmp_path):
        import os
        import time

        handler = _make_handler(tmp_path)
        now = time.time()
        for i in range(5):
            f = handler.dest_dir / f"bot_backup_{i}.tar.gz"
            f.write_bytes(b"x")
            os.utime(f, (now - (5 - i) * 10, now - (5 - i) * 10))

        handler._rotate_backups("bot")

        remaining = handler._list_backups("bot")
        assert len(remaining) == handler.max_keep
        # Die zuletzt erstellten (hoechster Index) muessen ueberleben
        remaining_names = {b["name"] for b in remaining}
        assert "bot_backup_4.tar.gz" in remaining_names
        assert "bot_backup_0.tar.gz" not in remaining_names

    def test_no_rotation_when_under_max_keep(self, tmp_path):
        handler = _make_handler(tmp_path)
        f = handler.dest_dir / "bot_backup_1.tar.gz"
        f.write_bytes(b"x")

        handler._rotate_backups("bot")

        assert f.exists()


class TestHumanSize:
    @pytest.mark.parametrize(
        "size_bytes, expected_unit",
        [
            (500, "B"),
            (2048, "KB"),
            (5 * 1024 * 1024, "MB"),
            (3 * 1024 * 1024 * 1024, "GB"),
        ],
    )
    def test_picks_appropriate_unit(self, size_bytes, expected_unit):
        result = BackupHandler._human_size(size_bytes)
        assert result.endswith(expected_unit)


class TestCreateArchiveExcludePatterns:
    def test_exclude_patterns_omit_matching_files(self, tmp_path):
        handler = _make_handler(tmp_path)

        source = tmp_path / "bot_source"
        (source / "cache").mkdir()
        (source / "cache" / "data.bin").write_bytes(b"cache data")
        (source / "keep.py").write_text("print('keep')")

        archive_path = handler._create_archive(source, "bot", ["cache"])

        import tarfile

        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()

        assert any("keep.py" in n for n in names)
        assert not any("cache" in n for n in names)

    def test_wildcard_extension_pattern_is_excluded(self, tmp_path):
        handler = _make_handler(tmp_path)

        source = tmp_path / "bot_source"
        (source / "module.pyc").write_bytes(b"compiled")
        (source / "module.py").write_text("print('source')")

        archive_path = handler._create_archive(source, "bot", ["*.pyc"])

        import tarfile

        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()

        assert any(n.endswith("module.py") for n in names)
        assert not any(n.endswith("module.pyc") for n in names)
