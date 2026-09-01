# tests/test_backup_handler_error_handler.py
# -*- coding: utf-8 -*-
"""
Tests für die EnhancedErrorHandler-Integration in
handlers/admin/backup_handler.py::BackupHandler.

Analog zum bereits etablierten Muster (navidrome_menu_handler.py,
duplicate_handler.py, enhanced_logger_menu_handler.py, test_menu_handler.py,
admin/user_management_handler.py): ist error_handler gesetzt (wird von
handlers/menu/rich_menu_handler.py nach der Konstruktion zugewiesen -
self.backup_handler.error_handler = self.error_handler, bislang fehlte
diese Zuweisung komplett - BackupHandler war "nie verdrahtet"), wird er
STATT der bisherigen lokalen Fehlermeldung aufgerufen; ohne error_handler
bleibt das bisherige Verhalten unveraendert.

Von den insgesamt 7 except-Bloecken der Datei sind nur 2 fuer diese
Integration relevant (start_bot_backup, start_lib_backup) - beide editieren
dieselbe query-Nachricht sowohl fuer den "laeuft..."-Zwischenstand als auch
fuer das Endergebnis (kein Nachrichten-Mismatch-Risiko wie z.B. bei
mugge_statistik_handler.py, wo eine separat versendete "Verarbeite..."-
Nachricht editiert wird - dort wurde die Integration bewusst zurueckgestellt).
delete_backup()s except baut nur einen lokalen Text fuer eine gemeinsame
Erfolg/Fehler-Nachricht am Ende der Methode und wurde bewusst nicht
verdrahtet, um diesen gemeinsamen Codepfad nicht aufzubrechen.
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


def run_async(coro):
    return asyncio.run(coro)


class TestStartBotBackupErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._create_archive = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.start_bot_backup(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "backup_bot_start"
        assert isinstance(call_args[3], RuntimeError)
        # kein doppeltes Benachrichtigen: nur der "laeuft..."-Zwischenstand
        # (1 Aufruf), keine zweite (Fehler-)Nachricht ueber error_handler hinaus
        assert update.callback_query.edit_message_text.await_count == 1

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler = _make_handler(tmp_path)
        assert handler.error_handler is None
        handler._create_archive = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.start_bot_backup(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Backup fehlgeschlagen" in text
        assert update.callback_query.edit_message_text.await_count == 2


class TestStartLibBackupErrorHandling:
    def test_routes_through_error_handler_when_set(self, tmp_path):
        handler = _make_handler(tmp_path)
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler._create_archive = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.start_lib_backup(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[2] == "backup_lib_start"
        assert isinstance(call_args[3], RuntimeError)
        assert update.callback_query.edit_message_text.await_count == 1

    def test_falls_back_to_local_message_without_error_handler(self, tmp_path):
        handler = _make_handler(tmp_path)
        assert handler.error_handler is None
        handler._create_archive = Mock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        run_async(handler.start_lib_backup(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Backup fehlgeschlagen" in text
        assert update.callback_query.edit_message_text.await_count == 2
