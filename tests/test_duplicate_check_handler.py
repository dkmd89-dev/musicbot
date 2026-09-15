# tests/test_duplicate_check_handler.py
# -*- coding: utf-8 -*-
"""
handlers/duplicate_check_handler.py — Telegram-Oberfläche für
services/library_repair/duplicate_runner.py (Chat-Charakterisierung
2026-09-15). Testmuster identisch zu tests/test_library_maintenance_handler.py:
die _run_*_and_report()-Hintergrund-Coroutine wird direkt mit einem
Fake-Message-Objekt getestet; run_duplicate_scan() wird vollständig
gemockt (patch.object auf dem Handler-Modul) - kein echter Subprozess,
keine echte Library-Änderung.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import handlers.duplicate_check_handler as dch_module
from handlers.duplicate_check_handler import DuplicateCheckHandler
from services.library_repair.duplicate_runner import DuplicateScanResult
from services.library_repair.run_tracking import RepairAlreadyRunningError


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def handler():
    return DuplicateCheckHandler(FakeConfig(), logger_factory=lambda name: Mock())


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.fixture
def context():
    return Mock()


def run(coro):
    return asyncio.run(coro)


def _resolved_report(**over):
    base = {
        "duplicate_groups": 1,
        "resolved_groups": 1,
        "manual_review_groups": 0,
        "files_scanned": 10,
        "read_only_intact": True,
        "decisions": [
            {
                "artist": "bausa", "title": "chicago",
                "candidates": [
                    {"path": "/lib/Bausa/a.m4a", "bitrate": 256},
                    {"path": "/lib/Bausa/b.m4a", "bitrate": 128},
                ],
                "keep": "/lib/Bausa/a.m4a",
                "remove_proposal": ["/lib/Bausa/b.m4a"],
                "action": "RESOLVED",
                "reason": "higher bitrate",
            },
        ],
    }
    base.update(over)
    return base


class TestHandleStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_start(update, context))
        update.callback_query.answer.assert_called_with(
            "⛔ Nur Admins dürfen den Duplikat-Check nutzen", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()

    def test_admin_shows_start_menu_with_cli_hint(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "resolve_duplicates" not in text  # Nutzer sieht das interne Skript nicht
        assert "library_repair.py --allow-delete" in text

    def test_no_scan_triggered_on_open(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "run_duplicate_scan", AsyncMock()) as scan:
            run(handler.handle_start(update, context))
        scan.assert_not_called()


class TestHandleArtistList:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_artist_list(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_empty_library_shows_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "list_library_artist_dirs", return_value=[]):
            run(handler.handle_artist_list(update, context))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Artist-Verzeichnisse" in text

    def test_shows_index_based_buttons_no_raw_artist_in_callback_data(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "list_library_artist_dirs", return_value=["Bausa", "Clueso"]):
            run(handler.handle_artist_list(update, context))
        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_datas = [
            btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data
        ]
        assert "dupcheck:pick:0" in callback_datas
        assert "dupcheck:pick:1" in callback_datas
        assert not any("Bausa" in cd for cd in callback_datas)

    def test_no_scan_triggered_on_list(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "list_library_artist_dirs", return_value=["Bausa"]), \
             patch.object(dch_module, "run_duplicate_scan", AsyncMock()) as scan:
            run(handler.handle_artist_list(update, context))
        scan.assert_not_called()


class TestHandlePickArtist:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_pick_artist(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_unresolvable_index_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_pick_artist(update, context, 5))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht mehr gefunden" in text

    def test_valid_index_starts_background_scan(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(dch_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(dch_module, "run_duplicate_scan", AsyncMock()) as scan, \
             patch("asyncio.create_task") as mock_create_task:
            run(handler.handle_pick_artist(update, context, 0))
        update.callback_query.edit_message_text.assert_called_once()
        assert "Bausa" in update.callback_query.edit_message_text.call_args[0][0]
        mock_create_task.assert_called_once()


class TestRunScanAndReport:
    def test_lock_conflict_shows_message(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            dch_module, "run_duplicate_scan",
            AsyncMock(side_effect=RepairAlreadyRunningError("läuft bereits")),
        ):
            run(handler._run_scan_and_report(message, "Bausa"))
        text = message.edit_text.call_args[0][0]
        assert "läuft bereits" in text

    def test_unexpected_exception_shows_error(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            dch_module, "run_duplicate_scan", AsyncMock(side_effect=RuntimeError("boom")),
        ):
            run(handler._run_scan_and_report(message, "Bausa"))
        text = message.edit_text.call_args[0][0]
        assert "boom" in text

    def test_success_calls_run_duplicate_scan_with_artist(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = DuplicateScanResult(exit_code=0, report=_resolved_report())
        with patch.object(dch_module, "run_duplicate_scan", AsyncMock(return_value=result)) as scan:
            run(handler._run_scan_and_report(message, "Bausa"))
        scan.assert_called_once_with("Bausa")


class TestFormatScanResult:
    def test_failure_shows_error(self, handler):
        result = DuplicateScanResult(exit_code=2, report=None, stderr_tail="boom")
        text = handler._format_scan_result("Bausa", result)
        assert "fehlgeschlagen" in text
        assert "boom" in text

    def test_safety_violation_discards_result(self, handler):
        result = DuplicateScanResult(
            exit_code=3, report=_resolved_report(read_only_intact=False),
        )
        text = handler._format_scan_result("Bausa", result)
        assert "Sicherheitswarnung" in text

    def test_no_groups_shows_clean_message(self, handler):
        result = DuplicateScanResult(
            exit_code=0,
            report={"duplicate_groups": 0, "files_scanned": 5, "read_only_intact": True,
                    "resolved_groups": 0, "manual_review_groups": 0, "decisions": []},
        )
        text = handler._format_scan_result("Bausa", result)
        assert "Keine Duplikat-Gruppen gefunden" in text

    def test_resolved_group_shows_keep_and_remove_with_bitrate(self, handler):
        result = DuplicateScanResult(exit_code=0, report=_resolved_report())
        text = handler._format_scan_result("Bausa", result)
        assert "a.m4a" in text and "256" in text
        assert "b.m4a" in text and "128" in text
        assert "Behalten" in text
        assert "entfernen" in text

    def test_manual_review_group_shows_reason_not_keep_remove(self, handler):
        report = _resolved_report()
        report["decisions"][0]["action"] = "MANUAL_REVIEW"
        report["decisions"][0]["reason"] = "album context risk"
        report["resolved_groups"] = 0
        report["manual_review_groups"] = 1
        result = DuplicateScanResult(exit_code=0, report=report)

        text = handler._format_scan_result("Bausa", result)

        assert "MANUAL_REVIEW" in text
        assert "album context risk" in text
        assert "Behalten" not in text

    def test_result_never_offers_delete_button(self, handler):
        """Bewusst KEIN Execute/Delete - nur Text-Hinweis auf die CLI."""
        result = DuplicateScanResult(exit_code=0, report=_resolved_report())
        text = handler._format_scan_result("Bausa", result)
        assert "--allow-delete" in text
        assert "--apply" in text

    def test_shows_cli_hint_with_actual_artist_name(self, handler):
        result = DuplicateScanResult(exit_code=0, report=_resolved_report())
        text = handler._format_scan_result("Bausa", result)
        assert "--artist Bausa" in text
