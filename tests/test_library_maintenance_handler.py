# tests/test_library_maintenance_handler.py
# -*- coding: utf-8 -*-
"""
handlers/library_maintenance_handler.py — Telegram-Oberfläche für
services/library_repair/maintenance_service.py (ARCH-032 Phase 4).

Testmuster analog zu tests/test_repair_musicbot_handler.py: die
_run_*_and_report()-Hintergrund-Coroutinen werden direkt mit einem
Fake-Message-Objekt getestet; die öffentlichen handle_*()-Wrapper werden
nur auf "Placeholder gezeigt + Hintergrund-Task gestartet" geprüft.
Mutmaterial (execute_*/preview_*) wird ausschließlich gemockt - kein
echter Dateisystemzugriff in dieser Testdatei.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import handlers.library_maintenance_handler as lmh_module
from handlers.library_maintenance_handler import LibraryMaintenanceHandler
from services.library_repair.executor import ExecOutcome
from services.library_repair.maintenance_service import (
    ACTION_ARTIST_CASING,
    ACTION_LEGACY_GENRE_CLEANUP,
    ACTION_SET_GENRE,
    MaintenanceServiceError,
    MaintenancePreview,
    MaintenanceRunResult,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError


class FakeConfig:
    OWNER_USER_ID = 12345
    ADMIN_USER_IDS = [67890]


OWNER_ID = 12345
ADMIN_ID = 67890
OTHER_ID = 999


@pytest.fixture
def handler():
    return LibraryMaintenanceHandler(FakeConfig(), logger_factory=lambda name: Mock())


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


def _outcome(file, status, before=None, after=None):
    return ExecOutcome(
        file=file, issue_code="X", action="X", status=status,
        before=before or {}, after=after or {},
    )


# ── Start / Artist-Liste / Aktions-Auswahl (Flow, kein Auto-Start) ──────


class TestHandleStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_start(update, context))
        update.callback_query.answer.assert_called_with(
            "⛔ Nur Admins dürfen Library-Wartung nutzen", show_alert=True
        )

    def test_admin_sees_start_menu_without_side_effects(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_start(update, context))
        update.callback_query.edit_message_text.assert_called_once()
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Library-Wartung" in text


class TestHandleArtistList:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_artist_list(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_empty_library_shows_no_artists_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "list_library_artist_dirs", return_value=[]):
            run(handler.handle_artist_list(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine Artist-Verzeichnisse" in text

    def test_lists_artists_as_index_based_buttons(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "list_library_artist_dirs", return_value=["Aymen", "Bausa"]):
            run(handler.handle_artist_list(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        callback_datas = [b.callback_data for b in buttons]
        assert "libmaint:pick:0" in callback_datas
        assert "libmaint:pick:1" in callback_datas
        # kein Rohpfad/-name in callback_data, nur der Index:
        assert not any("Aymen" in cd or "Bausa" in cd for cd in callback_datas)


class TestHandlePickArtist:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_pick_artist(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_index_shows_retry_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_pick_artist(update, context, 99))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_valid_index_shows_three_actions(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_pick_artist(update, context, 0))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert f"libmaint:action:{ACTION_ARTIST_CASING}:0" in callback_datas
        assert f"libmaint:action:{ACTION_LEGACY_GENRE_CLEANUP}:0" in callback_datas
        assert f"libmaint:action:{ACTION_SET_GENRE}:0" in callback_datas

    def test_opening_action_selection_does_not_call_execute(self, handler, context):
        """Kein Auto-Start (Auftrag §11.5): Artist waehlen loest keine
        Aktion aus."""
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "execute_artist_casing_fix") as mocked:
            run(handler.handle_pick_artist(update, context, 0))
        mocked.assert_not_called()


# ── Preview (read-only) ──────────────────────────────────────────────────


class TestHandlePreview:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_preview(update, context, ACTION_ARTIST_CASING, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_admin_triggers_background_preview_task(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(handler, "_run_preview_and_report", AsyncMock()):
            run(handler.handle_preview(update, context, ACTION_ARTIST_CASING, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Vorschau" in text

    def test_preview_never_calls_execute(self, handler):
        """Auftrag §11.6: Preview MUSS read-only sein."""
        message = Mock()
        message.edit_text = AsyncMock()
        preview = MaintenancePreview(
            action=ACTION_ARTIST_CASING, artist="Bausa", target_count=1,
            outcomes=[_outcome("a.m4a", "DRY_RUN", before={"artist": ["bausa"]}, after={"artist": ["Bausa"]})],
        )
        with patch.object(lmh_module, "preview_artist_casing", return_value=preview), \
             patch.object(lmh_module, "execute_artist_casing_fix") as mocked_execute:
            run(handler._run_preview_and_report(message, ACTION_ARTIST_CASING, "Bausa", 0))
        mocked_execute.assert_not_called()

    def test_preview_shows_changed_files(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        preview = MaintenancePreview(
            action=ACTION_ARTIST_CASING, artist="Bausa", target_count=1,
            outcomes=[_outcome("a.m4a", "DRY_RUN", before={"artist": ["bausa"]}, after={"artist": ["Bausa"]})],
        )
        with patch.object(lmh_module, "preview_artist_casing", return_value=preview):
            run(handler._run_preview_and_report(message, ACTION_ARTIST_CASING, "Bausa", 0))
        text = message.edit_text.call_args.args[0]
        assert "a.m4a" in text
        assert "Noch keine Änderungen durchgeführt" in text

    def test_preview_no_changes_shows_already_correct(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        preview = MaintenancePreview(
            action=ACTION_ARTIST_CASING, artist="Bausa", target_count=1,
            outcomes=[_outcome("a.m4a", "SKIPPED")],
        )
        with patch.object(lmh_module, "preview_artist_casing", return_value=preview):
            run(handler._run_preview_and_report(message, ACTION_ARTIST_CASING, "Bausa", 0))
        text = message.edit_text.call_args.args[0]
        assert "keine Änderung nötig" in text

    def test_preview_no_files_found(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        preview = MaintenancePreview(action=ACTION_ARTIST_CASING, artist="Bausa", target_count=0, outcomes=[])
        with patch.object(lmh_module, "preview_artist_casing", return_value=preview):
            run(handler._run_preview_and_report(message, ACTION_ARTIST_CASING, "Bausa", 0))
        text = message.edit_text.call_args.args[0]
        assert "Keine Dateien" in text

    def test_preview_service_error_shown_to_user(self, handler):
        """z.B. set-genre fuer einen Artist ohne Mapping-Eintrag."""
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            lmh_module, "preview_set_genre",
            side_effect=MaintenanceServiceError("Artist 'X' nicht in artist_genre.yaml gefunden."),
        ):
            run(handler._run_preview_and_report(message, ACTION_SET_GENRE, "X", 0))
        text = message.edit_text.call_args.args[0]
        assert "nicht in artist_genre.yaml gefunden" in text


# ── Confirm ───────────────────────────────────────────────────────────


class TestHandleConfirmPrompt:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_confirm_prompt(update, context, ACTION_ARTIST_CASING, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_confirm_prompt_alone_does_not_execute(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "execute_artist_casing_fix") as mocked:
            run(handler.handle_confirm_prompt(update, context, ACTION_ARTIST_CASING, 0))
        mocked.assert_not_called()
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "ACHTUNG" in text


# ── Execute ───────────────────────────────────────────────────────────


class TestHandleExecute:
    def test_permission_rechecked_at_execute(self, handler, context):
        update = _mock_update(OTHER_ID)
        with patch.object(lmh_module, "execute_artist_casing_fix") as mocked:
            run(handler.handle_execute(update, context, ACTION_ARTIST_CASING, 0))
        mocked.assert_not_called()
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_locked_shows_wait_message_without_starting_background_task(self, handler, context):
        """Auftrag §11.5.1 Doppelklick-Schutz: bereits belegter Lock wird
        vor dem Start erkannt."""
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True), \
             patch.object(handler, "_run_execute_and_report", AsyncMock()) as mocked:
            run(handler.handle_execute(update, context, ACTION_ARTIST_CASING, 0))
        mocked.assert_not_called()
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_unlocked_admin_triggers_background_task(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(handler, "_run_execute_and_report", AsyncMock()):
            run(handler.handle_execute(update, context, ACTION_ARTIST_CASING, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft" in text

    def test_invalid_artist_index_at_execute_time(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_execute(update, context, ACTION_ARTIST_CASING, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_success_result_reported(self, handler):
        result = MaintenanceRunResult(
            run_id="abc", action=ACTION_ARTIST_CASING, artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=2, success_count=2,
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_artist_casing_fix", return_value=result):
            run(handler._run_execute_and_report(message, ACTION_ARTIST_CASING, "Bausa", ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "Erfolgreich: 2" in text
        assert "Fehlgeschlagen: 0" in text

    def test_partial_success_reported_distinctly(self, handler):
        """Auftrag §8.5: Partial Success (Erfolg + Fehler gemischt) muss
        sichtbar unterschieden werden, nicht als reines SUCCESS."""
        result = MaintenanceRunResult(
            run_id="abc", action=ACTION_ARTIST_CASING, artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=2,
            success_count=1, failed_count=1,
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_artist_casing_fix", return_value=result):
            run(handler._run_execute_and_report(message, ACTION_ARTIST_CASING, "Bausa", ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "teilweise" in text
        assert "Erfolgreich: 1" in text
        assert "Fehlgeschlagen: 1" in text

    def test_repair_already_running_race_is_caught(self, handler):
        """TOCTOU zwischen Vorab-Lock-Check und dem tatsaechlichen
        acquire_repair_lock() in maintenance_service.py."""
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            lmh_module, "execute_artist_casing_fix",
            side_effect=RepairAlreadyRunningError("Es läuft bereits eine Reparatur."),
        ):
            run(handler._run_execute_and_report(message, ACTION_ARTIST_CASING, "Bausa", ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "läuft bereits" in text

    def test_maintenance_service_error_shown_to_user(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(
            lmh_module, "execute_set_genre",
            side_effect=MaintenanceServiceError("Artist 'X' nicht in artist_genre.yaml gefunden."),
        ):
            run(handler._run_execute_and_report(message, ACTION_SET_GENRE, "X", ADMIN_ID))
        text = message.edit_text.call_args.args[0]
        assert "nicht in artist_genre.yaml gefunden" in text

    def test_unexpected_exception_reports_to_error_handler(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        handler.error_handler = Mock()
        handler.error_handler.handle_exception = AsyncMock()
        with patch.object(
            lmh_module, "execute_artist_casing_fix", side_effect=RuntimeError("boom"),
        ):
            run(handler._run_execute_and_report(message, ACTION_ARTIST_CASING, "Bausa", ADMIN_ID))
        handler.error_handler.handle_exception.assert_called_once()
        text = message.edit_text.call_args.args[0]
        assert "Unerwarteter Fehler" in text


# ── Alle drei Actions durchgereicht ─────────────────────────────────────


class TestAllThreeActionsWired:
    @pytest.mark.parametrize(
        "action, execute_fn_name",
        [
            (ACTION_ARTIST_CASING, "execute_artist_casing_fix"),
            (ACTION_LEGACY_GENRE_CLEANUP, "execute_legacy_genre_cleanup"),
            (ACTION_SET_GENRE, "execute_set_genre"),
        ],
    )
    def test_execute_calls_correct_service_function_with_resolved_artist(
        self, handler, action, execute_fn_name
    ):
        """Service wird ausschliesslich mit dem aufgeloesten Artist-Namen
        aufgerufen, nie mit dem Index selbst (ARCH-031 B.8)."""
        result = MaintenanceRunResult(
            run_id="x", action=action, artist="Bausa", status="SUCCESS",
            started_at="t0", finished_at="t1", target_count=1, success_count=1,
        )
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, execute_fn_name, return_value=result) as mocked:
            run(handler._run_execute_and_report(message, action, "Bausa", ADMIN_ID))
        mocked.assert_called_once()
        assert mocked.call_args.args[0] == "Bausa"
        assert mocked.call_args.kwargs["triggered_by"] == f"telegram:{ADMIN_ID}"
