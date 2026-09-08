# tests/test_repair_musicbot_handler.py
# -*- coding: utf-8 -*-
"""
handlers/repair_musicbot_handler.py — Telegram-Oberfläche für
services/library_repair/repair_service.py.

Testmuster analog zu tests/test_library_doctor_handler.py: die
_run_*_and_report()-Hintergrund-Coroutinen werden direkt mit einem
Fake-Message-Objekt getestet (nicht über asyncio.create_task, das die
Coroutine nur fire-and-forget planen würde); die öffentlichen handle_*()-
Wrapper werden nur auf "Placeholder gezeigt + Hintergrund-Task gestartet"
geprüft (der eigentliche Subprozess-Aufruf in services/library_repair/
repair_service.py hat eigene Tests in tests/test_repair_service.py).
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import handlers.repair_musicbot_handler as repair_handler_module
from handlers.repair_musicbot_handler import RepairMusicBotHandler
from services.library_repair.models import (
    RepairAction,
    RepairCandidate,
    RepairLevel,
    RepairPlan,
)
from services.library_repair.repair_service import (
    RepairAlreadyRunningError,
    RepairPreview,
    RepairRunResult,
    HealthScanFailedError,
)


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def handler():
    return RepairMusicBotHandler(FakeConfig(), logger_factory=lambda name: Mock())


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
    ctx = Mock()
    return ctx


def run(coro):
    return asyncio.run(coro)


def _candidate(code, level, **kw):
    base = dict(
        issue_code=code, action=RepairAction.NONE, level=level, severity="WARNING",
        scope="file", path=None, artist=None, album=None, title=None,
        reuses_component="TagWriter", requires_approval=False, requires_external=False,
        is_destructive=False, expected_change="Testaenderung",
    )
    base.update(kw)
    return RepairCandidate(**base)


def _plan(candidates, score=95.0):
    plan = RepairPlan(library_root="/lib", health_score=score)
    plan.candidates = list(candidates)
    return plan


class TestHandleStart:
    def test_shows_menu(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        update.callback_query.edit_message_text.assert_called()

    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_start(update, context))
        update.callback_query.answer.assert_called_with(
            "⛔ Nur Admins dürfen Repair MusicBot nutzen", show_alert=True
        )
        update.callback_query.edit_message_text.assert_not_called()

    def test_no_automatic_repair_on_open(self, handler, context):
        """Abschnitt 27/33: das bloße Öffnen darf niemals eine Reparatur
        auslösen."""
        update = _mock_update(ADMIN_ID)
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair", new=AsyncMock()
        ) as mocked_execute:
            run(handler.handle_start(update, context))
        mocked_execute.assert_not_called()


class TestHandleAnalyze:
    def test_shows_placeholder_and_starts_background_task(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(handler, "_run_analyze_and_report", AsyncMock()):
            run(handler.handle_analyze(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Analysiere" in text

    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_analyze(update, context))
        update.callback_query.edit_message_text.assert_not_called()

    def test_report_shows_dynamic_counts_by_level(self, handler):
        candidates = [
            _candidate("META_ALBUM_ARTIST_MISSING", RepairLevel.SAFE_AUTOMATIC),
            _candidate("ARTWORK_MISSING", RepairLevel.COVER),
            _candidate("ALBUM_TRACK_GAP", RepairLevel.MANUAL_REVIEW, scope="album"),
        ]
        plan = _plan(candidates, score=87.5)
        message = Mock()
        message.edit_text = AsyncMock()

        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_analyze_and_report(message))

        text = message.edit_text.call_args.args[0]
        assert "87.5" in text
        assert "1×" in text  # jede Kategorie hat genau 1 Kandidaten
        assert "SAFE_AUTOMATIC: 1" in text or "1" in text

    def test_health_scan_failure_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan",
            new=AsyncMock(side_effect=HealthScanFailedError("boom")),
        ):
            run(handler._run_analyze_and_report(message))
        text = message.edit_text.call_args.args[0]
        assert "Health-Scan fehlgeschlagen" in text
        assert "boom" in text

    def test_empty_plan_shows_all_clear(self, handler):
        plan = _plan([])
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_analyze_and_report(message))
        text = message.edit_text.call_args.args[0]
        assert "Keine offenen Befunde" in text


class TestHandleProposals:
    def test_only_safe_and_review_tiers_shown_no_hardcoded_counts(self, handler):
        safe = [_candidate("META_ALBUM_ARTIST_MISSING", RepairLevel.SAFE_AUTOMATIC, path="a.m4a")]
        review = [_candidate("ARTWORK_MISSING", RepairLevel.COVER, path="b.m4a")]
        plan = _plan(safe + review)
        message = Mock()
        message.edit_text = AsyncMock()

        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_proposals_and_report(message))

        text = message.edit_text.call_args.args[0]
        assert "1 automatisch ausführbare" in text
        assert "SAFE" in text
        assert "REVIEW" in text

    def test_no_repairable_findings(self, handler):
        plan = _plan([])
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_proposals_and_report(message))
        text = message.edit_text.call_args.args[0]
        assert "Keine reparierbaren Befunde" in text

    def test_preview_button_only_shown_when_safe_candidates_exist(self, handler):
        review_only = [_candidate("ARTWORK_MISSING", RepairLevel.COVER, path="b.m4a")]
        plan = _plan(review_only)
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_proposals_and_report(message))
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "repair:preview" not in callback_datas


class TestHandlePreview:
    def test_preview_is_read_only_text_and_has_execute_confirm_button(self, handler):
        safe = [_candidate("META_ALBUM_ARTIST_MISSING", RepairLevel.SAFE_AUTOMATIC, path="a.m4a")]
        plan = _plan(safe)
        message = Mock()
        message.edit_text = AsyncMock()

        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_preview_and_report(message))

        text = message.edit_text.call_args.args[0]
        assert "Noch keine Änderungen durchgeführt" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "repair:confirm" in callback_datas

    def test_preview_disappeared_candidates_shows_message(self, handler):
        plan = _plan([])  # inzwischen leer (z.B. schon repariert)
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan", new=AsyncMock(return_value=plan)
        ):
            run(handler._run_preview_and_report(message))
        text = message.edit_text.call_args.args[0]
        assert "Keine SAFE_AUTOMATIC-Reparaturen" in text


class TestHandleConfirmPrompt:
    def test_shows_explicit_confirmation_with_two_buttons(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_confirm_prompt(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ACHTUNG" in text
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "repair:execute" in callback_datas
        assert "repair:start" in callback_datas

    def test_confirm_prompt_alone_does_not_execute(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair", new=AsyncMock()
        ) as mocked:
            run(handler.handle_confirm_prompt(update, context))
        mocked.assert_not_called()


class TestHandleExecute:
    def test_permission_rechecked_at_execute(self, handler, context):
        """Abschnitt 43: Berechtigung wird am tatsaechlichen Ausfuehrungs-
        Handler erneut geprueft."""
        update = _mock_update(OTHER_ID)
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair", new=AsyncMock()
        ) as mocked:
            run(handler.handle_execute(update, context))
        mocked.assert_not_called()
        update.callback_query.answer.assert_called_with(
            "⛔ Keine Berechtigung", show_alert=True
        )

    def test_admin_can_trigger_execute_background_task(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(handler, "_run_execute_and_report", AsyncMock()):
            run(handler.handle_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft" in text

    def test_success_result_reported(self, handler):
        result = RepairRunResult(
            repair_id="abc", status="SUCCESS", started_at="t0", finished_at="t1",
            candidates_total=2, resolved_count=2,
            status_counts={"SUCCESS": 2}, affected_files=["a.m4a", "b.m4a"],
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair",
            new=AsyncMock(return_value=result),
        ):
            run(handler._run_execute_and_report(message, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "Erfolgreich: 2" in text
        assert "Fehlgeschlagen: 0" in text
        assert "Verifiziert behoben: 2" in text

    def test_failed_result_reported_distinctly(self, handler):
        result = RepairRunResult(
            repair_id="abc", status="FAILED", started_at="t0", finished_at="t1",
            candidates_total=1, resolved_count=0,
            status_counts={"FAILED": 1}, affected_files=["a.m4a"],
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair",
            new=AsyncMock(return_value=result),
        ):
            run(handler._run_execute_and_report(message, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "Fehlgeschlagen: 1" in text

    def test_skipped_empty_plan_reported(self, handler):
        result = RepairRunResult(
            repair_id="abc", status="SKIPPED", started_at="t0", finished_at="t1",
            candidates_total=0, resolved_count=0,
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair",
            new=AsyncMock(return_value=result),
        ):
            run(handler._run_execute_and_report(message, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "Keine offenen SAFE_AUTOMATIC-Reparaturen" in text

    def test_already_running_shown_gracefully(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair",
            new=AsyncMock(side_effect=RepairAlreadyRunningError("läuft bereits")),
        ):
            run(handler._run_execute_and_report(message, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "läuft bereits" in text

    def test_triggered_by_includes_telegram_user_id(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = RepairRunResult(
            repair_id="x", status="SKIPPED", started_at="t0", finished_at="t1",
            candidates_total=0, resolved_count=0,
        )
        with patch.object(
            repair_handler_module, "execute_safe_automatic_repair",
            new=AsyncMock(return_value=result),
        ) as mocked:
            run(handler._run_execute_and_report(message, ADMIN_ID))
        assert mocked.call_args.kwargs["triggered_by"] == f"telegram:{ADMIN_ID}"


class TestHandleHistory:
    def test_shows_only_actually_stored_runs(self, handler, context):
        update = _mock_update(ADMIN_ID)
        fake_runs = [
            {"repair_id": "1", "started_at": "2026-09-07T23:51:00Z", "status": "SUCCESS",
             "status_counts": {"SUCCESS": 3}},
        ]
        with patch.object(repair_handler_module, "load_repair_history", return_value=fake_runs):
            run(handler.handle_history(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "2026-09-07T23:51:00Z" in text
        assert "3 Reparatur(en)" in text

    def test_empty_history_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(repair_handler_module, "load_repair_history", return_value=[]):
            run(handler.handle_history(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Noch keine Reparaturen" in text

    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        with patch.object(repair_handler_module, "load_repair_history") as mocked:
            run(handler.handle_history(update, context))
        mocked.assert_not_called()


class TestHandleStatistics:
    def test_statistics_dynamic_no_hardcoded_values(self, handler, context):
        update = _mock_update(ADMIN_ID)
        fake_stats = {
            "total_runs": 4, "total": 37, "success": 35, "failed": 2, "skipped": 0,
            "most_common_issue_codes": [("ARTWORK_MISSING", 12)],
        }
        with patch.object(repair_handler_module, "compute_repair_statistics", return_value=fake_stats):
            run(handler.handle_statistics(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Ausgeführte Reparaturen: 37" in text
        assert "Erfolgreich: 35" in text
        assert "Fehlgeschlagen: 2" in text
        assert "ARTWORK_MISSING: 12" in text

    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        with patch.object(repair_handler_module, "compute_repair_statistics") as mocked:
            run(handler.handle_statistics(update, context))
        mocked.assert_not_called()
