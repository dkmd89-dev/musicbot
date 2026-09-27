# -*- coding: utf-8 -*-
"""Findings #31/#32 — Logger-Cleanup-Verdrahtung und tote Route.

#31: Die Telegram-Cleanup-Buttons (logger_cleanup_old/_large/_empty/
_rotated/_all_confirm/_archive, logger_cleanup_all_files) waren in keinem
Routing verdrahtet und liefen in "Funktion nicht implementiert"; eine
Cleanup-Fachlogik existierte nirgends. Jetzt:
services/logger_admin.py::cleanup_rotated_log_files() (nur rotierte
Backups `<name>.log.<N>`, prozessübergreifend sicher), Telegram mit
Vorschau → Bestätigung, nur für die Modi "old" und "rotated". Buttons
ohne sichere Semantik wurden entfernt.

#32: rich_menu_system.py routete "logger_search_module" auf die nie
existierende Methode logger_handler.search_module() → AttributeError
(vom zentralen Callback-Handler abgefangen). Route entfernt.
"""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.enhanced_logger_menu_handler import EnhancedLoggerMenuHandler
from handlers.menu.actions import admin_diagnostics as diag_actions
from handlers.menu.rich_menu_system import RichMenuSystem
from services.logger_admin import cleanup_rotated_log_files


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


def _touch(path: Path, content: str = "x", age_days: float = 0):
    path.write_text(content, encoding="utf-8")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


# ─────────────────────────────────────────────────────────────────────────
# Service: cleanup_rotated_log_files()
# ─────────────────────────────────────────────────────────────────────────


class TestCleanupRotatedLogFiles:
    def test_deletes_only_rotated_backups_never_active_files(self, log_dir):
        _touch(log_dir / "bot.log", "active", age_days=100)
        _touch(log_dir / "empty.log", "", age_days=100)
        _touch(log_dir / "big.log", "x" * 20000, age_days=100)
        _touch(log_dir / "bot.log.1", "r1")
        _touch(log_dir / "bot.log.2", "r2", age_days=100)
        _touch(log_dir / "bot.log.old", "keep", age_days=100)
        _touch(log_dir / "bot.log.1.gz", "keep", age_days=100)

        result = cleanup_rotated_log_files(log_dir)

        assert sorted(result.deleted) == ["bot.log.1", "bot.log.2"]
        remaining = sorted(p.name for p in log_dir.iterdir())
        assert remaining == ["big.log", "bot.log", "bot.log.1.gz", "bot.log.old", "empty.log"]
        assert result.freed_bytes == 4
        assert result.failed == []

    def test_older_than_days_filters_by_mtime(self, log_dir):
        _touch(log_dir / "bot.log.1", age_days=5)
        _touch(log_dir / "bot.log.2", age_days=40)

        result = cleanup_rotated_log_files(log_dir, older_than_days=30)

        assert result.deleted == ["bot.log.2"]
        assert (log_dir / "bot.log.1").exists()

    def test_dry_run_deletes_nothing(self, log_dir):
        _touch(log_dir / "bot.log.1", "abc")

        result = cleanup_rotated_log_files(log_dir, dry_run=True)

        assert result.matched == ["bot.log.1"]
        assert result.deleted == []
        assert result.freed_bytes == 3
        assert (log_dir / "bot.log.1").exists()

    def test_symlink_is_never_followed_or_deleted(self, log_dir, tmp_path):
        target = _touch(tmp_path / "outside.txt", "secret")
        (log_dir / "bot.log.1").symlink_to(target)

        result = cleanup_rotated_log_files(log_dir)

        assert result.matched == []
        assert target.exists()
        assert (log_dir / "bot.log.1").is_symlink()

    def test_missing_dir_returns_empty_result(self, tmp_path):
        result = cleanup_rotated_log_files(tmp_path / "nope")
        assert result.matched == [] and result.deleted == []

    def test_negative_days_rejected(self, log_dir):
        with pytest.raises(ValueError):
            cleanup_rotated_log_files(log_dir, older_than_days=-1)

    def test_unlink_failure_is_collected_not_raised(self, log_dir, monkeypatch):
        _touch(log_dir / "a.log.1")
        _touch(log_dir / "b.log.1")
        real_unlink = Path.unlink

        def _unlink(self, *a, **kw):
            if self.name == "a.log.1":
                raise PermissionError("nope")
            return real_unlink(self, *a, **kw)

        monkeypatch.setattr(Path, "unlink", _unlink)
        result = cleanup_rotated_log_files(log_dir)

        assert result.failed == ["a.log.1"]
        assert result.deleted == ["b.log.1"]


# ─────────────────────────────────────────────────────────────────────────
# Telegram-Handler: Menü, Vorschau, Ausführung
# ─────────────────────────────────────────────────────────────────────────


class FakeConfig:
    def __init__(self, log_dir):
        self.LOG_DIR = str(log_dir)


@pytest.fixture
def handler(log_dir):
    return EnhancedLoggerMenuHandler(FakeConfig(log_dir))


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.answer = AsyncMock()
    return update


def _sent(update):
    args, kwargs = update.callback_query.edit_message_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    markup = kwargs.get("reply_markup")
    buttons = [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []
    return text, buttons


ROUTED_CLEANUP_CALLBACKS = {
    "logger_cleanup_old", "logger_cleanup_rotated",
    "logger_cleanup_old_confirm", "logger_cleanup_rotated_confirm",
}


class TestCleanupMenuButtons:
    def test_cleanup_menu_offers_only_routed_actions(self, handler):
        update = make_update()
        run(handler.show_cleanup_menu(update, Mock()))
        _, buttons = _sent(update)
        assert set(buttons) == {"logger_cleanup_old", "logger_cleanup_rotated", "logger_main_menu"}

    def test_files_list_no_longer_offers_unrouted_all_files_cleanup(self, handler, log_dir):
        _touch(log_dir / "bot.log")
        update = make_update()
        run(handler.show_log_files_list(update, Mock()))
        _, buttons = _sent(update)
        assert "logger_cleanup_all_files" not in buttons
        assert "logger_cleanup_menu" in buttons


class TestCleanupPreviewAndExecute:
    def test_preview_lists_files_and_asks_confirmation_without_deleting(self, handler, log_dir):
        _touch(log_dir / "bot.log.1", age_days=40)
        update = make_update()

        run(handler.show_cleanup_preview(update, Mock(), "old"))

        text, buttons = _sent(update)
        assert "bot.log.1" in text
        assert "logger_cleanup_old_confirm" in buttons
        assert (log_dir / "bot.log.1").exists()

    def test_preview_without_matches_has_no_confirm(self, handler, log_dir):
        _touch(log_dir / "bot.log.1", age_days=1)
        update = make_update()

        run(handler.show_cleanup_preview(update, Mock(), "old"))

        text, buttons = _sent(update)
        assert "Keine passenden Dateien" in text
        assert not any(b.endswith("_confirm") for b in buttons)

    def test_execute_rotated_deletes_rotated_only(self, handler, log_dir):
        _touch(log_dir / "bot.log", "active")
        _touch(log_dir / "bot.log.1")
        update = make_update()

        run(handler.execute_cleanup(update, Mock(), "rotated"))

        text, _ = _sent(update)
        assert "Gelöscht: 1" in text
        assert not (log_dir / "bot.log.1").exists()
        assert (log_dir / "bot.log").exists()

    @pytest.mark.parametrize("mode", ["large", "empty", "all", "archive", ""])
    def test_unknown_mode_deletes_nothing(self, handler, log_dir, mode):
        _touch(log_dir / "bot.log.1")
        update = make_update()

        run(handler.execute_cleanup(update, Mock(), mode))
        run(handler.show_cleanup_preview(update, Mock(), mode))

        assert (log_dir / "bot.log.1").exists()


# ─────────────────────────────────────────────────────────────────────────
# Routing: handlers/menu/actions/admin_diagnostics.py::handle_logger_callback
# ─────────────────────────────────────────────────────────────────────────


def _spec_handler():
    h = Mock(spec=EnhancedLoggerMenuHandler)
    h.show_cleanup_preview = AsyncMock()
    h.execute_cleanup = AsyncMock()
    return h


def _diag_update():
    update = Mock()
    update.callback_query = AsyncMock()
    update.effective_user = Mock(id=1)
    return update


class TestCleanupRouting:
    @pytest.mark.parametrize("callback,method,mode", [
        ("logger_cleanup_old", "show_cleanup_preview", "old"),
        ("logger_cleanup_rotated", "show_cleanup_preview", "rotated"),
        ("logger_cleanup_old_confirm", "execute_cleanup", "old"),
        ("logger_cleanup_rotated_confirm", "execute_cleanup", "rotated"),
    ])
    def test_routed(self, callback, method, mode):
        h = _spec_handler()
        run(diag_actions.handle_logger_callback(_diag_update(), Mock(), callback, h, Mock()))
        getattr(h, method).assert_awaited_once()
        assert getattr(h, method).call_args.args[2] == mode

    @pytest.mark.parametrize("callback", [
        "logger_cleanup_large", "logger_cleanup_empty", "logger_cleanup_all_confirm",
        "logger_cleanup_archive", "logger_cleanup_all_files", "logger_cleanup_old_confirmX",
        "logger_cleanup_large_confirm", "logger_cleanup_", "logger_search_module",
    ])
    def test_invalid_callback_data_is_not_implemented_without_side_effect(self, callback):
        h = _spec_handler()
        update = _diag_update()
        log = Mock()
        run(diag_actions.handle_logger_callback(update, Mock(), callback, h, log))
        h.show_cleanup_preview.assert_not_awaited()
        h.execute_cleanup.assert_not_awaited()
        update.callback_query.answer.assert_any_await("⚠️ Funktion nicht implementiert")
        log.warning.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# RichMenuSystem: Admin-Gating + tote Route logger_search_module (#32)
# ─────────────────────────────────────────────────────────────────────────


class MockConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [12345, 67890]
    SESSION_TIMEOUT = 300
    MAX_CONCURRENT_SESSIONS = 100


ADMIN, NON_ADMIN = 67890, 99999


@pytest.fixture
def menu_system():
    system = RichMenuSystem(MockConfig())
    system.initialize_menu_structure()
    system.set_logger_handler(_spec_handler())
    system.error_handler = Mock()
    system.error_handler.handle_callback_error = AsyncMock()
    return system


def _menu_update(user_id, data):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


class TestRichMenuLogger:
    def test_search_module_no_attribute_error(self, menu_system):
        update = _menu_update(ADMIN, "logger_search_module")
        run(menu_system.handle_callback(update, Mock()))
        menu_system.error_handler.handle_callback_error.assert_not_awaited()
        update.callback_query.answer.assert_any_await("⚠️ Funktion nicht implementiert")

    def test_search_module_non_admin_rejected(self, menu_system):
        update = _menu_update(NON_ADMIN, "logger_search_module")
        run(menu_system.handle_callback(update, Mock()))
        _args, kwargs = update.callback_query.answer.call_args
        assert "Berechtigung" in (_args[0] if _args else kwargs.get("text", ""))

    @pytest.mark.parametrize("callback", sorted(ROUTED_CLEANUP_CALLBACKS))
    def test_cleanup_non_admin_rejected(self, menu_system, callback):
        update = _menu_update(NON_ADMIN, callback)
        run(menu_system.handle_callback(update, Mock()))
        menu_system.logger_handler.execute_cleanup.assert_not_awaited()
        menu_system.logger_handler.show_cleanup_preview.assert_not_awaited()
        _args, kwargs = update.callback_query.answer.call_args
        assert "Berechtigung" in (_args[0] if _args else kwargs.get("text", ""))
        assert kwargs.get("show_alert") is True

    def test_cleanup_confirm_admin_executes(self, menu_system):
        update = _menu_update(ADMIN, "logger_cleanup_rotated_confirm")
        run(menu_system.handle_callback(update, Mock()))
        menu_system.logger_handler.execute_cleanup.assert_awaited_once()
        menu_system.error_handler.handle_callback_error.assert_not_awaited()
