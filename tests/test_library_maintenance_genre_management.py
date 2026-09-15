# tests/test_library_maintenance_genre_management.py
# -*- coding: utf-8 -*-
"""
handlers/library_maintenance_handler.py — 🎭 Genre-Verwaltung (Library
Genre Management v2, Chat-Charakterisierung 2026-09-15): Genre setzen
(Mapping/Manuell, only-if-missing, Mapping speichern), Fehlende Genres
(GENRE_EMPTY/META_GENRE_MISSING-Artist-Picker), Genre revalidieren.

Testmuster identisch zu tests/test_library_maintenance_handler.py: die
_run_*_and_report()-Hintergrund-Coroutinen werden direkt mit einem
Fake-Message-Objekt getestet; alle Service-/Runner-Aufrufe (preview_set_genre/
execute_set_genre/save_manual_genre_mapping/build_repair_plan/filter_plan/
run_genre_revalidation_subprocess) werden vollständig gemockt - kein echter
Dateisystemzugriff, kein echter Subprozess, kein echter Last.fm-Call.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import handlers.library_maintenance_handler as lmh_module
from handlers.library_maintenance_handler import LibraryMaintenanceHandler
from services.library_repair.executor import ExecOutcome
from services.library_repair.genre import GenreDomainError, ManualMappingSaveResult
from services.library_repair.genre_revalidation_runner import GenreRevalidationRunResult
from services.library_repair.maintenance_service import (
    MaintenancePreview,
    MaintenanceRunResult,
    MaintenanceServiceError,
)
from services.library_repair.repair_service import HealthScanFailedError
from services.library_repair.run_tracking import RepairAlreadyRunningError


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]
    GENRE_MAPPING_DIR = "mapping"


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def handler():
    return LibraryMaintenanceHandler(FakeConfig(), logger_factory=lambda name: Mock())


def _mock_update(user_id, *, has_message=False):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    if has_message:
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def context():
    ctx = Mock()
    ctx.user_data = {}
    return ctx


def run(coro):
    return asyncio.run(coro)


def _outcome(file, status, before=None, after=None):
    return ExecOutcome(
        file=file, issue_code="SET_GENRE", action="SET_GENRE", status=status,
        before=before or {}, after=after or {},
    )


def _preview(target_count, outcomes):
    return MaintenancePreview(action="set-genre", artist="Bausa", target_count=target_count, outcomes=outcomes)


# ═════════════════════════════════════════════════════════════════════
# 🎭 Genre-Verwaltung — Einstieg
# ═════════════════════════════════════════════════════════════════════


class TestGenreMenu:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_genre_menu(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_genre_menu(update, context, 5))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_valid_index_stores_artist_and_shows_submenu(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_genre_menu(update, context, 0))
        assert context.user_data["libmaint_genre_artist"] == "Bausa"
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:src" in callback_datas
        assert "libmaint:gr:preview" in callback_datas

    def test_resets_previous_genre_set_state(self, handler, context):
        context.user_data["libmaint_genre_set"] = {"source": "manual", "manual_genre": "Old"}
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_genre_menu(update, context, 0))
        assert "libmaint_genre_set" not in context.user_data


# ═════════════════════════════════════════════════════════════════════
# 🧹 Fehlende Genres
# ═════════════════════════════════════════════════════════════════════


def _candidate(artist):
    return Mock(artist=artist)


def _plan_with(candidates):
    plan = Mock()
    return plan, candidates


class TestMissingGenre:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_missing_genre_start(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_health_scan_failure_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "build_repair_plan", AsyncMock(side_effect=HealthScanFailedError("boom"))):
            run(handler._run_missing_genre_scan_and_report(message, context))
        text = message.edit_text.call_args.args[0]
        assert "Health-Scan fehlgeschlagen" in text

    def test_no_findings_shows_clean_message(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        plan = Mock()
        with patch.object(lmh_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(lmh_module, "filter_plan", return_value=Mock(candidates=[])):
            run(handler._run_missing_genre_scan_and_report(message, context))
        text = message.edit_text.call_args.args[0]
        assert "Keine offenen Befunde" in text

    def test_dedupes_artists_across_both_issue_codes(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        plan = Mock()

        def fake_filter_plan(p, issue_code=None):
            if issue_code == "GENRE_EMPTY":
                return Mock(candidates=[_candidate("Bausa"), _candidate("Clueso")])
            return Mock(candidates=[_candidate("Bausa")])  # META_GENRE_MISSING

        with patch.object(lmh_module, "build_repair_plan", AsyncMock(return_value=plan)), \
             patch.object(lmh_module, "filter_plan", side_effect=fake_filter_plan):
            run(handler._run_missing_genre_scan_and_report(message, context))

        assert context.user_data["libmaint_missing_genre_artists"] == ["Bausa", "Clueso"]
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:missingpick:0" in callback_datas
        assert "libmaint:missingpick:1" in callback_datas
        assert not any("Bausa" in cd for cd in callback_datas)  # index-basiert, kein Rohname

    def test_no_scan_triggered_on_open(self, handler, context):
        """Auftrag §11.5: Oeffnen des Fehlende-Genres-Screens loest den
        Health-Scan nur als Hintergrund-Task aus, nicht synchron - hier
        via gemocktem asyncio.create_task verifiziert (identisches Muster
        wie TestGsMode.test_mapping_source_goes_straight_to_preview), da
        ein ungemockter Background-Task innerhalb desselben asyncio.run()
        durchaus noch zur Ausfuehrung kommen kann."""
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "build_repair_plan", AsyncMock()) as mocked, \
             patch("asyncio.create_task") as mock_create_task:
            run(handler.handle_missing_genre_start(update, context))
        mocked.assert_not_called()
        mock_create_task.assert_called_once()


class TestMissingGenrePick:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_missing_genre_pick(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_stale_list_shows_error(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_missing_genre_pick(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "abgelaufen" in text

    def test_valid_pick_sets_state_with_missing_genre_flag(self, handler, context):
        context.user_data["libmaint_missing_genre_artists"] = ["Bausa", "Clueso"]
        update = _mock_update(ADMIN_ID)
        run(handler.handle_missing_genre_pick(update, context, 1))
        assert context.user_data["libmaint_genre_artist"] == "Clueso"
        assert context.user_data["libmaint_genre_set"] == {"missing_genre_flow": True}


# ═════════════════════════════════════════════════════════════════════
# ✏️ Genre setzen — Quelle/Modus/Speichern
# ═════════════════════════════════════════════════════════════════════


class TestGsSrc:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gs_src(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_session_expired_without_artist(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_src(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "abgelaufen" in text

    def test_shows_source_choice(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_src(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:mapping" in callback_datas
        assert "libmaint:gs:manual" in callback_datas


class TestGsMapping:
    def test_sets_source_and_shows_mode_screen(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_mapping(update, context))
        assert context.user_data["libmaint_genre_set"]["source"] == "mapping"
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:mode:overwrite" in callback_datas
        assert "libmaint:gs:mode:onlymissing" in callback_datas

    def test_missing_genre_flow_shows_recommended_hint(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {"missing_genre_flow": True}
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_mapping(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in keyboard.inline_keyboard for b in row]
        assert any("empfohlen" in label for label in labels)


class TestGsManualTextInput:
    def test_prompts_for_text_and_sets_awaiting_flag(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_manual(update, context))
        assert context.user_data["libmaint_awaiting_genre_text"] is True
        assert context.user_data["libmaint_genre_set"]["source"] == "manual"

    def test_process_pending_ignored_when_not_awaiting(self, handler, context):
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_genre_input(update, context, "Rock"))
        assert handled is False

    def test_process_pending_empty_input_rejected_stays_awaiting(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        context.user_data["libmaint_awaiting_genre_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_genre_input(update, context, "   "))
        assert handled is True
        assert context.user_data["libmaint_awaiting_genre_text"] is True  # erneuter Versuch moeglich
        text = update.message.reply_text.call_args.args[0]
        assert "leer" in text

    def test_process_pending_newline_rejected(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        context.user_data["libmaint_awaiting_genre_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        run(handler.process_pending_genre_input(update, context, "Rock\nPop"))
        text = update.message.reply_text.call_args.args[0]
        assert "Zeilenumbrüche" in text

    def test_process_pending_too_long_rejected(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        context.user_data["libmaint_awaiting_genre_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        run(handler.process_pending_genre_input(update, context, "X" * 500))
        text = update.message.reply_text.call_args.args[0]
        assert "zu lang" in text

    def test_process_pending_valid_input_normalizes_and_advances(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        context.user_data["libmaint_awaiting_genre_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        run(handler.process_pending_genre_input(update, context, "  Heavy Metal, Thrash  "))
        assert "libmaint_awaiting_genre_text" not in context.user_data
        assert context.user_data["libmaint_genre_set"]["manual_genre"] == "Heavy Metal; Thrash"
        update.message.reply_text.assert_called_once()

    def test_process_pending_session_expired(self, handler, context):
        context.user_data["libmaint_awaiting_genre_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_genre_input(update, context, "Rock"))
        assert handled is True
        text = update.message.reply_text.call_args.args[0]
        assert "abgelaufen" in text


class TestGsMode:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gs_mode(update, context, "overwrite"))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_mapping_source_goes_straight_to_preview(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {"source": "mapping"}
        update = _mock_update(ADMIN_ID)
        with patch("asyncio.create_task") as mock_create_task:
            run(handler.handle_gs_mode(update, context, "onlymissing"))
        assert context.user_data["libmaint_genre_set"]["only_if_missing"] is True
        update.callback_query.edit_message_text.assert_called_once()
        mock_create_task.assert_called_once()

    def test_manual_source_shows_save_screen(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {"source": "manual", "manual_genre": "Rock"}
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_mode(update, context, "overwrite"))
        assert context.user_data["libmaint_genre_set"]["only_if_missing"] is False
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:save:no" in callback_datas
        assert "libmaint:gs:save:yes" in callback_datas


class TestGsSave:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gs_save(update, context, True))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_sets_save_flag_and_starts_preview(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {"source": "manual", "manual_genre": "Rock"}
        update = _mock_update(ADMIN_ID)
        with patch("asyncio.create_task") as mock_create_task:
            run(handler.handle_gs_save(update, context, True))
        assert context.user_data["libmaint_genre_set"]["save_mapping"] is True
        mock_create_task.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
# ✏️ Genre setzen — Preview / Execute
# ═════════════════════════════════════════════════════════════════════


class TestGsPreview:
    def test_service_error_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        context.user_data["libmaint_genre_set"] = {"source": "manual", "manual_genre": "Rock"}
        with patch.object(lmh_module, "resolve_target_genre", side_effect=MaintenanceServiceError("Kein Genre.")):
            run(handler._run_gs_preview_and_report(message, context, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Kein Genre." in text

    def test_no_files_found(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        context.user_data["libmaint_genre_set"] = {"source": "mapping"}
        with patch.object(lmh_module, "resolve_target_genre", return_value="Rock"), \
             patch.object(lmh_module, "preview_set_genre", return_value=_preview(0, [])):
            run(handler._run_gs_preview_and_report(message, context, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Keine Dateien" in text

    def test_no_change_needed_only_if_missing_reason(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        context.user_data["libmaint_genre_set"] = {"source": "mapping", "only_if_missing": True}
        outcomes = [_outcome("a.m4a", "SKIPPED")]
        with patch.object(lmh_module, "resolve_target_genre", return_value="Rock"), \
             patch.object(lmh_module, "preview_set_genre", return_value=_preview(1, outcomes)):
            run(handler._run_gs_preview_and_report(message, context, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "only-if-missing aktiv" in text

    def test_shows_full_preview_with_all_details(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        context.user_data["libmaint_genre_set"] = {
            "source": "manual", "manual_genre": "Heavy Metal",
            "only_if_missing": False, "save_mapping": True,
        }
        outcomes = [_outcome("a.m4a", "DRY_RUN", before={"genre": "Rock"}, after={"genre": "Heavy Metal"})]
        with patch.object(lmh_module, "resolve_target_genre", return_value="Heavy Metal"), \
             patch.object(lmh_module, "preview_set_genre", return_value=_preview(1, outcomes)):
            run(handler._run_gs_preview_and_report(message, context, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Bausa" in text
        assert "Heavy Metal" in text
        assert "Manuelle Eingabe" in text
        assert "Wird gespeichert" in text
        assert "Überschreiben erlaubt" in text
        assert "Noch keine Änderungen durchgeführt" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:confirm" in callback_datas

    def test_mapping_source_never_calls_save_manual_mapping(self, handler, context):
        """Preview allein darf niemals mutieren - auch nicht das Mapping."""
        message = Mock()
        message.edit_text = AsyncMock()
        context.user_data["libmaint_genre_set"] = {"source": "mapping", "save_mapping": True}
        outcomes = [_outcome("a.m4a", "DRY_RUN")]
        with patch.object(lmh_module, "resolve_target_genre", return_value="Rock"), \
             patch.object(lmh_module, "preview_set_genre", return_value=_preview(1, outcomes)), \
             patch.object(lmh_module, "save_manual_genre_mapping") as mock_save:
            run(handler._run_gs_preview_and_report(message, context, "Bausa"))
        mock_save.assert_not_called()


class TestGsConfirmAndExecute:
    def test_confirm_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gs_confirm(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_confirm_shows_achtung_screen(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gs_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ACHTUNG" in text
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gs:execute" in callback_datas

    def test_execute_lock_conflict_shown(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True):
            run(handler.handle_gs_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_execute_calls_service_with_resolved_options(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "manual", "manual_genre": "Heavy Metal", "only_if_missing": True, "save_mapping": False}
        result = MaintenanceRunResult(
            run_id="x", action="set-genre", artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=1, success_count=1,
        )
        with patch.object(lmh_module, "execute_set_genre", return_value=result) as mocked:
            handler_ = LibraryMaintenanceHandler(FakeConfig(), logger_factory=lambda name: Mock())
            run(handler_._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        mocked.assert_called_once_with(
            "Bausa", triggered_by=f"telegram:{ADMIN_ID}", genre="Heavy Metal",
            from_mapping=False, only_if_missing=True,
        )
        text = message.edit_text.call_args.args[0]
        assert "Genre gesetzt" in text

    def test_execute_saves_mapping_when_requested_and_successful(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "manual", "manual_genre": "Heavy Metal", "save_mapping": True}
        result = MaintenanceRunResult(
            run_id="x", action="set-genre", artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=1, success_count=1,
        )
        save_result = ManualMappingSaveResult(
            written=True, unchanged=False, dry_run=False, artist_key="bausa",
            primary="Heavy Metal", secondary=[], mapping_path="mapping/artist_genre.yaml",
        )
        with patch.object(lmh_module, "execute_set_genre", return_value=result), \
             patch.object(lmh_module, "save_manual_genre_mapping", return_value=save_result) as mock_save:
            run(handler._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        mock_save.assert_called_once()
        text = message.edit_text.call_args.args[0]
        assert "Mapping gespeichert" in text

    def test_execute_does_not_save_mapping_when_source_is_mapping(self, handler):
        """save_mapping macht nur bei manueller Eingabe Sinn - bei
        Mapping-Quelle wuerde es das Mapping mit sich selbst
        ueberschreiben."""
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "mapping", "save_mapping": True}
        result = MaintenanceRunResult(
            run_id="x", action="set-genre", artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=1, success_count=1,
        )
        with patch.object(lmh_module, "execute_set_genre", return_value=result), \
             patch.object(lmh_module, "save_manual_genre_mapping") as mock_save:
            run(handler._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        mock_save.assert_not_called()

    def test_execute_zero_success_does_not_save_mapping(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "manual", "manual_genre": "Heavy Metal", "save_mapping": True}
        result = MaintenanceRunResult(
            run_id="x", action="set-genre", artist="Bausa", status="SKIPPED",
            started_at="t0", finished_at="t1", target_count=1, success_count=0, skipped_count=1,
        )
        with patch.object(lmh_module, "execute_set_genre", return_value=result), \
             patch.object(lmh_module, "save_manual_genre_mapping") as mock_save:
            run(handler._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        mock_save.assert_not_called()

    def test_execute_mapping_save_failure_shown_but_does_not_crash(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "manual", "manual_genre": "Heavy Metal", "save_mapping": True}
        result = MaintenanceRunResult(
            run_id="x", action="set-genre", artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=1, success_count=1,
        )
        with patch.object(lmh_module, "execute_set_genre", return_value=result), \
             patch.object(lmh_module, "save_manual_genre_mapping", side_effect=GenreDomainError("fehlt")):
            run(handler._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "Mapping-Speichern fehlgeschlagen" in text

    def test_execute_lock_already_running_error_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        state = {"source": "mapping"}
        with patch.object(
            lmh_module, "execute_set_genre",
            side_effect=RepairAlreadyRunningError("läuft bereits"),
        ):
            run(handler._run_gs_execute_and_report(message, Mock(), "Bausa", state, ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "läuft bereits" in text

    def test_no_auto_start_on_confirm_screen(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        context.user_data["libmaint_genre_set"] = {}
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "execute_set_genre") as mocked:
            run(handler.handle_gs_confirm(update, context))
        mocked.assert_not_called()


# ═════════════════════════════════════════════════════════════════════
# 🔄 Genre revalidieren
# ═════════════════════════════════════════════════════════════════════


def _rr(exit_code=0, data=None, **overrides):
    base = {
        "artist": "Bausa", "outcome": "OVERTURN_ALLOWED", "reason": "ok",
        "manual_mapping_protected": False, "current_primary": "Rock",
        "current_secondary": [], "candidate_primary": "Pop", "candidate_secondary": [],
        "candidate_source": "lastfm", "learning_status": "CONFIRMED",
        "locked_primary": "Pop", "observation_count": 9, "mutated": False,
        "error_message": None,
    }
    base.update(overrides)
    return GenreRevalidationRunResult(exit_code=exit_code, data=base)


class TestGrPreview:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gr_preview(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_session_expired(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gr_preview(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "abgelaufen" in text

    def test_no_auto_execute_on_open(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock()) as mocked, \
             patch("asyncio.create_task"):
            run(handler.handle_gr_preview(update, context))
        mocked.assert_not_called()

    def test_overturn_allowed_shows_apply_button(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=_rr())):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Bausa" in text and "Rock" in text and "Pop" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gr:confirm" in callback_datas

    def test_same_genre_shows_no_apply_button(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _rr(outcome="SAME_GENRE", candidate_primary="Rock")
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=result)):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Keine Änderung erforderlich" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gr:confirm" not in callback_datas

    def test_overturn_rejected_no_apply_button(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _rr(outcome="OVERTURN_REJECTED")
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=result)):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gr:confirm" not in callback_datas

    def test_no_candidate_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _rr(outcome="NO_CANDIDATE", candidate_primary=None)
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=result)):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gr:confirm" not in callback_datas

    def test_manual_mapping_protected_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        result = _rr(outcome="BLOCKED_MANUAL", manual_mapping_protected=True, candidate_primary=None)
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=result)):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:gr:confirm" not in callback_datas

    def test_subprocess_failure_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        failed = GenreRevalidationRunResult(exit_code=3, data=None, stderr_tail="boom")
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=failed)):
            run(handler._run_gr_preview_and_report(message, "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "fehlgeschlagen" in text


class TestGrConfirmAndExecute:
    def test_confirm_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_gr_confirm(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_confirm_shows_achtung(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_gr_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ACHTUNG" in text

    def test_execute_lock_conflict(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True):
            run(handler.handle_gr_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_execute_calls_subprocess_with_apply_true(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            lmh_module, "run_genre_revalidation_subprocess", AsyncMock(return_value=_rr(mutated=True)),
        ) as mocked:
            run(handler._run_gr_execute_and_report(message, "Bausa"))
        mocked.assert_called_once_with("Bausa", apply=True)
        text = message.edit_text.call_args.args[0]
        assert "Änderung durchgeführt" in text

    def test_no_auto_start_on_preview_screen(self, handler, context):
        context.user_data["libmaint_genre_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "run_genre_revalidation_subprocess", AsyncMock()) as mocked, \
             patch("asyncio.create_task"):
            run(handler.handle_gr_confirm(update, context))
        mocked.assert_not_called()
