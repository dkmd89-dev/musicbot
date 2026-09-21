# tests/test_repair_handler_level23.py
# -*- coding: utf-8 -*-
"""
handlers/repair_musicbot_handler.py — L2/L3 Pro-Artist-Sub-Flow
(ARCH-033/ADR-0003): l23rep:* Callbacks.

Testmuster analog zu tests/test_repair_musicbot_handler.py und
tests/test_library_maintenance_handler.py: die _run_*_and_report()-
Hintergrund-Coroutinen werden direkt mit einem Fake-Message-Objekt
getestet; execute_level2_repair()/execute_level3_repair() werden
gemockt (patch.object auf dem Handler-Modul, identisches Prinzip wie
tests/test_repair_service_level23.py - der Aufruf erfolgt per
Namens-Lookup zur Laufzeit, siehe
handlers/repair_musicbot_handler.py::_run_l23_execute_and_report()) -
kein echter Subprozess/keine echte Library-Änderung in dieser Testdatei.
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
from services.library_repair.planner import ArtistCandidateSummary
from services.library_repair.repair_service import (
    HealthScanFailedError,
    LevelRepairResult,
    RepairAlreadyRunningError,
    RepairPreview,
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
    ctx.user_data = {}
    return ctx


def run(coro):
    return asyncio.run(coro)


def _candidate(code, level, artist="Bausa", **kw):
    base = dict(
        issue_code=code, action=RepairAction.NONE, level=level, severity="WARNING",
        scope="file", path=f"{artist}/Singles/x.m4a", artist=artist, album=None,
        title="x", reuses_component="TrackReprocessor", requires_approval=True,
        requires_external=(level is RepairLevel.EXTERNAL_METADATA),
        is_destructive=False, expected_change="Testaenderung",
    )
    base.update(kw)
    return RepairCandidate(**base)


def _plan(candidates, score=95.0):
    plan = RepairPlan(library_root="/lib", health_score=score)
    plan.candidates = list(candidates)
    return plan


def _seed_session(context, artists):
    """artists: list[(name, l2_count, l3_count)]"""
    context.user_data["l23rep_session"] = {"artists": list(artists)}


def _all_callback_data(markup) -> list[str]:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]


# ── Start ────────────────────────────────────────────────────────────────


class TestL23Start:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_start(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)
        update.callback_query.edit_message_text.assert_not_called()

    def test_admin_shows_start_menu(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_start(update, context))
        update.callback_query.edit_message_text.assert_called()

    def test_no_execute_call_on_open(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock()) as l2, \
             patch.object(repair_handler_module, "execute_level3_repair", AsyncMock()) as l3:
            run(handler.handle_l23_start(update, context))
        l2.assert_not_called()
        l3.assert_not_called()


# ── Artist-Liste ────────────────────────────────────────────────────────


class TestL23ArtistList:
    def test_health_scan_failure_shows_error(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "build_repair_plan",
            AsyncMock(side_effect=HealthScanFailedError("boom")),
        ):
            run(handler._run_l23_artist_scan_and_report(message, context, 0))
        text = message.edit_text.call_args[0][0]
        assert "Health-Scan fehlgeschlagen" in text

    def test_empty_groups_shows_no_candidates_message(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        plan = _plan([])
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(repair_handler_module, "group_candidates_by_artist", return_value={}):
            run(handler._run_l23_artist_scan_and_report(message, context, 0))
        text = message.edit_text.call_args[0][0]
        assert "Keine offenen L2/L3-Befunde" in text

    def test_success_caches_session_and_shows_index_based_buttons(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        plan = _plan([_candidate("META_TITLE_NOT_CLEAN", RepairLevel.METADATA_REPROCESSING)])
        groups = {"Bausa": ArtistCandidateSummary(artist="Bausa", l2_count=1, l3_count=0)}
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(repair_handler_module, "group_candidates_by_artist", return_value=groups):
            run(handler._run_l23_artist_scan_and_report(message, context, 0))

        assert context.user_data["l23rep_session"]["artists"] == [("Bausa", 1, 0)]
        markup = message.edit_text.call_args[1]["reply_markup"]
        callback_datas = _all_callback_data(markup)
        assert "l23rep:pick:0" in callback_datas
        # Index-basiert: kein Rohname in callback_data (nur im Label-Text)
        assert not any("Bausa" in cd for cd in callback_datas)

    def test_pagination_uses_cache_no_rescan(self, handler, context):
        artists = [(f"Artist{i}", 1, 0) for i in range(10)]
        _seed_session(context, artists)
        update = _mock_update(ADMIN_ID)
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock()) as scan:
            run(handler.handle_l23_artist_list(update, context, 1))
        scan.assert_not_called()
        update.callback_query.edit_message_text.assert_called()

    def test_force_refresh_ignores_cache(self, handler, context):
        _seed_session(context, [("Old", 1, 0)])
        update = _mock_update(ADMIN_ID)
        plan = _plan([])
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock(return_value=plan)) as scan, \
             patch.object(repair_handler_module, "group_candidates_by_artist", return_value={}):
            run(handler.handle_l23_artist_list(update, context, 0, force_refresh=True))
        scan.assert_called_once()

    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_artist_list(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)


# ── Aktions-Auswahl (Pick) ──────────────────────────────────────────────


class TestL23PickArtist:
    def test_expired_session_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_pick_artist(update, context, 0))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "abgelaufen" in text

    def test_shows_l2_and_l3_buttons_when_both_present(self, handler, context):
        _seed_session(context, [("Bausa", 2, 1)])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_pick_artist(update, context, 0))
        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_datas = _all_callback_data(markup)
        assert "l23rep:preview:l2:0" in callback_datas
        assert "l23rep:preview:l3:0" in callback_datas

    def test_hides_button_for_zero_count_level(self, handler, context):
        _seed_session(context, [("Bausa", 0, 3)])
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_pick_artist(update, context, 0))
        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_datas = _all_callback_data(markup)
        assert "l23rep:preview:l2:0" not in callback_datas
        assert "l23rep:preview:l3:0" in callback_datas

    def test_non_admin_rejected(self, handler, context):
        _seed_session(context, [("Bausa", 1, 0)])
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_pick_artist(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)


# ── Preview (read-only) ─────────────────────────────────────────────────


class TestL23Preview:
    def test_expired_session_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_preview(update, context, "l2", 0))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "abgelaufen" in text

    def test_no_candidates_shows_resolved_message(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        plan = _plan([])
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(repair_handler_module, "filter_plan", return_value=_plan([])):
            run(handler._run_l23_preview_and_report(message, "l2", "Bausa", 0))
        text = message.edit_text.call_args[0][0]
        assert "keine offenen" in text

    def test_shows_warning_and_confirm_button_mutates_nothing(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        cand = _candidate("META_MB_RECORDING_MISSING", RepairLevel.EXTERNAL_METADATA)
        plan = _plan([cand])
        with patch.object(repair_handler_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(repair_handler_module, "filter_plan", return_value=_plan([cand])), \
             patch.object(repair_handler_module, "execute_level2_repair", AsyncMock()) as l2, \
             patch.object(repair_handler_module, "execute_level3_repair", AsyncMock()) as l3:
            run(handler._run_l23_preview_and_report(message, "l3", "Bausa", 0))
        l2.assert_not_called()
        l3.assert_not_called()
        text = message.edit_text.call_args[0][0]
        assert "Netzwerk-/Rate-Limit-Fehler" in text
        assert "Noch keine Änderungen durchgeführt" in text
        markup = message.edit_text.call_args[1]["reply_markup"]
        assert "l23rep:confirm:l3:0" in _all_callback_data(markup)

    def test_non_admin_rejected(self, handler, context):
        _seed_session(context, [("Bausa", 1, 0)])
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_preview(update, context, "l2", 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)


# ── Explizite Bestätigung ───────────────────────────────────────────────


class TestL23ConfirmPrompt:
    def test_expired_session_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_confirm_prompt(update, context, "l2", 0))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "abgelaufen" in text

    def test_shows_confirmation_prompt_mutates_nothing(self, handler, context):
        _seed_session(context, [("Bausa", 2, 0)])
        update = _mock_update(ADMIN_ID)
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock()) as l2:
            run(handler.handle_l23_confirm_prompt(update, context, "l2", 0))
        l2.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "ACHTUNG" in text
        assert "Bausa" in text
        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_datas = _all_callback_data(markup)
        assert "l23rep:execute:l2:0" in callback_datas

    def test_non_admin_rejected(self, handler, context):
        _seed_session(context, [("Bausa", 1, 0)])
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_confirm_prompt(update, context, "l2", 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)


# ── Ausführung ───────────────────────────────────────────────────────────


def _result(**over):
    base = dict(
        repair_id="r1", artist="Bausa", level="l2", status="SUCCESS",
        started_at="t0", finished_at="t1", total=2, success=2, failed=0,
        skipped=0, unresolved=0, resolved_count=1, entries=[], affected_files=["a.m4a"],
        changed_files=["a.m4a"],
        rescan_triggered=True, error_message=None,
    )
    base.update(over)
    return LevelRepairResult(**base)


class TestL23Execute:
    def test_expired_session_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_l23_execute(update, context, "l2", 0))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "abgelaufen" in text

    def test_non_admin_rejected(self, handler, context):
        _seed_session(context, [("Bausa", 1, 0)])
        update = _mock_update(OTHER_ID)
        run(handler.handle_l23_execute(update, context, "l2", 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_calls_execute_level2_with_artist_and_triggered_by(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_level2_repair",
            AsyncMock(return_value=_result(level="l2")),
        ) as l2:
            run(handler._run_l23_execute_and_report(message, "l2", "Bausa", ADMIN_ID))
        l2.assert_called_once_with("Bausa", triggered_by=f"telegram:{ADMIN_ID}")

    def test_calls_execute_level3_not_level2(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock()) as l2, \
             patch.object(
                 repair_handler_module, "execute_level3_repair",
                 AsyncMock(return_value=_result(level="l3")),
             ) as l3:
            run(handler._run_l23_execute_and_report(message, "l3", "Bausa", ADMIN_ID))
        l3.assert_called_once_with("Bausa", triggered_by=f"telegram:{ADMIN_ID}")
        l2.assert_not_called()

    def test_lock_conflict_shows_message(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            repair_handler_module, "execute_level2_repair",
            AsyncMock(side_effect=RepairAlreadyRunningError("läuft bereits")),
        ):
            run(handler._run_l23_execute_and_report(message, "l2", "Bausa", ADMIN_ID))
        text = message.edit_text.call_args[0][0]
        assert "läuft bereits" in text

    def test_result_message_contains_all_fields(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _result(
            status="SUCCESS", success=3, failed=0, skipped=1,
            resolved_count=2, affected_files=["a.m4a", "b.m4a"],
            changed_files=["a.m4a", "b.m4a"], rescan_triggered=True,
        )
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock(return_value=result)):
            run(handler._run_l23_execute_and_report(message, "l2", "Bausa", ADMIN_ID))
        text = message.edit_text.call_args[0][0]
        assert "Bausa" in text
        assert "Erfolgreich: 3" in text
        assert "Übersprungen: 1" in text
        assert "Fehlgeschlagen: 0" in text
        assert "Geänderte Dateien: 2" in text
        assert "Verifiziert behoben: 2" in text
        assert "Auto-Learn" in text

    def test_partial_success_shown_with_warning_emoji(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _result(status="SUCCESS", success=1, failed=1, skipped=0)
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock(return_value=result)):
            run(handler._run_l23_execute_and_report(message, "l2", "Bausa", ADMIN_ID))
        text = message.edit_text.call_args[0][0]
        assert "teilweise abgeschlossen" in text
        assert "⚠️" in text

    def test_no_open_findings_shows_resolved_message(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _result(status="SKIPPED", total=0, success=0, failed=0, skipped=0, rescan_triggered=False)
        with patch.object(repair_handler_module, "execute_level2_repair", AsyncMock(return_value=result)):
            run(handler._run_l23_execute_and_report(message, "l2", "Bausa", ADMIN_ID))
        text = message.edit_text.call_args[0][0]
        assert "keine offenen" in text


# ── ARCH-033-F1: unresolved-Anzeige / changed_files / SKIPPED-Emoji ───────


class TestFormatL23ResultErweiterungen:
    """Regressionstests fuer die drei Teil-Fixes aus ARCH-033-F1
    (docs/FINDINGS_INDEX.md): (a) unresolved als vierte Summary-Zeile,
    (b) 'Geaenderte Dateien' zaehlt changed_files statt affected_files,
    (c) eigener SKIPPED-/UNRESOLVED-Zweig statt Fallback auf ❌."""

    def test_success_run_shows_no_cross_mark(self, handler):
        result = _result(
            status="SUCCESS", total=2, success=2, skipped=0, unresolved=0, failed=0,
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "Erfolgreich: 2" in text
        assert "❌" not in text
        assert "✅" in text

    def test_pure_skipped_run_shows_yellow_not_cross_mark(self, handler):
        """0 success / 3 skipped / 0 unresolved / 0 failed -> reiner
        SKIPPED-Lauf: kein ❌, kein irrefuehrendes 'Erfolgreich'-Emoji."""
        result = _result(
            status="SKIPPED", total=3, success=0, skipped=3, unresolved=0, failed=0,
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "❌" not in text
        assert "🟡" in text
        assert "Übersprungen: 3" in text

    def test_unresolved_run_shows_review_line_and_orange_marker(self, handler):
        """0 success / 0 skipped / 2 unresolved / 0 failed -> muss die
        neue 'Ueberpruefen'-Zeile zeigen (vorher: verschwand spurlos)."""
        result = _result(
            status="SKIPPED", total=2, success=0, skipped=0, unresolved=2, failed=0,
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "Überprüfen: 2" in text
        assert "🟠" in text
        assert "❌" not in text

    def test_failed_run_shows_cross_mark(self, handler):
        result = _result(
            status="FAILED", total=1, success=0, skipped=0, unresolved=0, failed=1,
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "❌" in text
        assert "Fehlgeschlagen: 1" in text

    def test_mixed_run_failed_dominates(self, handler):
        """failed>0 gewinnt immer, auch wenn zusaetzlich success/skipped/
        unresolved > 0 sind (docs/prompts/arch-033-f1-fix.txt §6)."""
        result = _result(
            status="FAILED", total=4, success=1, skipped=1, unresolved=1, failed=1,
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "❌" in text
        assert "🟠" not in text
        assert "🟡" not in text

    def test_changed_files_used_instead_of_affected_files(self, handler):
        """'Geaenderte Dateien' zaehlt NUR tatsaechlich geaenderte Dateien
        (changed_files), nicht alle beruehrten (affected_files) -
        Kernbeispiel: eine uebersprungene Datei zaehlt nicht mit."""
        result = _result(
            status="SUCCESS", total=2, success=1, skipped=1, unresolved=0, failed=0,
            affected_files=["a.m4a", "b.m4a"], changed_files=["a.m4a"],
        )
        text = handler._format_l23_result("l2", "Bausa", result)
        assert "Geänderte Dateien: 1" in text
