# tests/test_library_maintenance_metadata_edit.py
# -*- coding: utf-8 -*-
"""
handlers/library_maintenance_handler.py — 📝 Metadaten bearbeiten (Manual
Metadata Editing v1): Artist bearbeiten, Titel bearbeiten (inkl.
Track-Picker), Verweis auf die bestehende Genre-Verwaltung (keine
Duplizierung).

Testmuster identisch zu tests/test_library_maintenance_genre_management.py:
die _run_*_and_report()-Hintergrund-Coroutinen werden direkt mit einem
Fake-Message-Objekt getestet; alle Service-Aufrufe (preview_artist_rename/
execute_artist_rename/preview_title_edit/execute_title_edit/current_title/
resolve_artist_by_index/resolve_track_by_index/artist_targets) werden
vollständig gemockt - kein echter Dateisystemzugriff.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import handlers.library_maintenance_handler as lmh_module
from handlers.library_maintenance_handler import LibraryMaintenanceHandler
from services.library_repair.executor import ExecOutcome
from services.library_repair.maintenance_service import (
    MaintenancePreview,
    MaintenanceRunResult,
    MaintenanceServiceError,
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


def _outcome(file, status, issue_code="ARTIST_MANUAL_RENAME", before=None, after=None):
    return ExecOutcome(
        file=file, issue_code=issue_code, action=issue_code, status=status,
        before=before or {}, after=after or {},
    )


def _preview(target_count, outcomes, action="artist-rename"):
    return MaintenancePreview(action=action, artist="Bausa", target_count=target_count, outcomes=outcomes)


def _run_result(status="SUCCESS", success=1, failed=0, skipped=0, target=1):
    return MaintenanceRunResult(
        run_id="r1", action="artist-rename", artist="Bausa",
        status=status, started_at="t0", finished_at="t1",
        target_count=target, success_count=success, failed_count=failed,
        skipped_count=skipped,
    )


# ═════════════════════════════════════════════════════════════════════
# 📝 Metadaten bearbeiten — Einstieg
# ═════════════════════════════════════════════════════════════════════


class TestMetaMenu:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_menu(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_meta_menu(update, context, 5))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_valid_index_stores_artist_and_shows_submenu(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_meta_menu(update, context, 0))
        assert context.user_data["libmaint_meta_artist"] == "Bausa"
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:artist:0" in callback_datas
        assert "libmaint:meta:title:0" in callback_datas
        assert "libmaint:genremenu:0" in callback_datas
        assert "libmaint:pick:0" in callback_datas

    def test_resets_previous_meta_state(self, handler, context):
        context.user_data["libmaint_meta_new_value"] = "stale"
        context.user_data["libmaint_awaiting_artist_text"] = True
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_meta_menu(update, context, 0))
        assert "libmaint_meta_new_value" not in context.user_data
        assert "libmaint_awaiting_artist_text" not in context.user_data

    def test_opening_meta_menu_does_not_start_any_edit(self, handler, context):
        """Kein Auto-Start (Auftrag §17/§20): Metadaten-Menü öffnen löst
        keine Aktion aus."""
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "execute_artist_rename") as mocked_a, \
             patch.object(lmh_module, "execute_title_edit") as mocked_t:
            run(handler.handle_meta_menu(update, context, 0))
        mocked_a.assert_not_called()
        mocked_t.assert_not_called()


# ═════════════════════════════════════════════════════════════════════
# 🎤 Artist bearbeiten
# ═════════════════════════════════════════════════════════════════════


class TestMetaArtistStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_artist_start(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_meta_artist_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_valid_index_sets_awaiting_flag_and_shows_current_artist(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Hardtekk Tutorial"):
            run(handler.handle_meta_artist_start(update, context, 3))
        assert context.user_data["libmaint_meta_artist"] == "Hardtekk Tutorial"
        assert context.user_data["libmaint_awaiting_artist_text"] is True
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Hardtekk Tutorial" in text


class TestProcessPendingArtistInput:
    def test_not_awaiting_returns_false(self, handler, context):
        update = _mock_update(ADMIN_ID, has_message=True)
        assert run(handler.process_pending_artist_input(update, context, "Neu")) is False

    def test_session_expired_when_artist_missing(self, handler, context):
        context.user_data["libmaint_awaiting_artist_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_artist_input(update, context, "Neu"))
        assert handled is True
        assert "libmaint_awaiting_artist_text" not in context.user_data
        update.message.reply_text.assert_called_once()

    @pytest.mark.parametrize("text", ["", "   ", "a\nb", "x" * 201])
    def test_invalid_input_stays_awaiting(self, handler, context, text):
        context.user_data["libmaint_awaiting_artist_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_artist_input(update, context, text))
        assert handled is True
        assert context.user_data["libmaint_awaiting_artist_text"] is True
        update.message.reply_text.assert_called_once()
        assert "❌" in update.message.reply_text.call_args.args[0]

    def test_valid_input_triggers_background_preview(self, handler, context):
        context.user_data["libmaint_awaiting_artist_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID, has_message=True)
        with patch.object(handler, "_run_artist_rename_preview_and_report", AsyncMock()) as mocked:
            handled = run(handler.process_pending_artist_input(update, context, "  Bausa Records  "))
        assert handled is True
        assert "libmaint_awaiting_artist_text" not in context.user_data
        assert context.user_data["libmaint_meta_new_value"] == "Bausa Records"
        mocked.assert_called_once()
        assert mocked.call_args.args[1:] == ("Bausa", "Bausa Records")


class TestArtistRenamePreviewAndReport:
    def test_service_error_shown(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "preview_artist_rename", side_effect=MaintenanceServiceError("boom")):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Neu"))
        text = message.edit_text.call_args.args[0]
        assert "boom" in text

    def test_unexpected_exception_reported(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "preview_artist_rename", side_effect=RuntimeError("kaputt")):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Neu"))
        text = message.edit_text.call_args.args[0]
        assert "Unerwarteter Fehler" in text

    def test_no_files_found(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "preview_artist_rename", return_value=_preview(0, [])):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Neu"))
        text = message.edit_text.call_args.args[0]
        assert "Keine Dateien" in text

    def test_identical_value_shows_no_change_message(self, handler):
        """Review-Fund (v1): eine pauschale "bereits korrekt"-Meldung waere
        irrefuehrend, da changed_count==0 beim tag-wert-getriebenen
        Artist-Rename entweder "bereits korrekt" ODER "kein Tag passt zum
        Ausgangswert" bedeuten kann - die Meldung deckt beide Faelle
        ehrlich ab, ohne "bereits korrekt" zu behaupten."""
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("a.m4a", "SKIPPED")]
        with patch.object(lmh_module, "preview_artist_rename", return_value=_preview(1, outcomes)):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Bausa"))
        text = message.edit_text.call_args.args[0]
        assert "Keine Änderung nötig" in text
        assert "bereits korrekt" in text

    def test_all_safety_skipped_shows_distinct_message(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("a.m4a", "SKIPPED")]
        outcomes[0].reason = "Safety: nicht auflösbar (…)"
        with patch.object(lmh_module, "preview_artist_rename", return_value=_preview(1, outcomes)):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Bausa Records"))
        text = message.edit_text.call_args.args[0]
        assert "Keine der" in text and "verfügbar" in text
        assert "Keine Änderung nötig" not in text

    def test_shows_preview_with_confirm_and_cancel(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("a.m4a", "DRY_RUN"), _outcome("b.m4a", "DRY_RUN")]
        with patch.object(lmh_module, "preview_artist_rename", return_value=_preview(2, outcomes)):
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Bausa Records"))
        text = message.edit_text.call_args.args[0]
        assert "Bausa" in text and "Bausa Records" in text
        assert "Betroffene Dateien: 2" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:artist:confirm" in callback_datas
        assert "libmaint:start" in callback_datas

    def test_preview_never_writes(self, handler):
        """Preview ist read-only (Auftrag §19) - execute_artist_rename
        darf niemals waehrend der Vorschau aufgerufen werden."""
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("a.m4a", "DRY_RUN")]
        with patch.object(lmh_module, "preview_artist_rename", return_value=_preview(1, outcomes)), \
             patch.object(lmh_module, "execute_artist_rename") as mocked_execute:
            run(handler._run_artist_rename_preview_and_report(message, "Bausa", "Bausa Records"))
        mocked_execute.assert_not_called()


class TestMetaArtistConfirm:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_artist_confirm(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_session_expired_when_state_missing(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_artist_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Sitzung abgelaufen" in text

    def test_shows_confirmation_with_execute_and_cancel(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_new_value"] = "Bausa Records"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_artist_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Bausa" in text and "Bausa Records" in text
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:artist:execute" in callback_datas
        assert "libmaint:start" in callback_datas


class TestMetaArtistExecute:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_artist_execute(update, context))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_lock_conflict_shown(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True):
            run(handler.handle_meta_artist_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_session_expired_when_state_missing(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False):
            run(handler.handle_meta_artist_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Sitzung abgelaufen" in text

    def test_triggers_background_execute_with_correct_args(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_new_value"] = "Bausa Records"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(handler, "_run_artist_rename_execute_and_report", AsyncMock()) as mocked:
            run(handler.handle_meta_artist_execute(update, context))
        mocked.assert_called_once()
        args = mocked.call_args.args
        assert args[2] == "Bausa"
        assert args[3] == "Bausa Records"
        assert args[4] == ADMIN_ID


class TestArtistRenameExecuteAndReport:
    def test_lock_error_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_artist_rename", side_effect=RepairAlreadyRunningError("busy")):
            run(handler._run_artist_rename_execute_and_report(message, context, "Bausa", "Neu", ADMIN_ID))
        assert "busy" in message.edit_text.call_args.args[0]

    def test_service_error_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_artist_rename", side_effect=MaintenanceServiceError("invalid")):
            run(handler._run_artist_rename_execute_and_report(message, context, "Bausa", "Neu", ADMIN_ID))
        assert "invalid" in message.edit_text.call_args.args[0]

    def test_success_clears_state_and_shows_result(self, handler, context):
        context.user_data["libmaint_meta_new_value"] = "Neu"
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_artist_rename", return_value=_run_result()) as mocked:
            run(handler._run_artist_rename_execute_and_report(message, context, "Bausa", "Neu", ADMIN_ID))
        mocked.assert_called_once_with("Bausa", "Neu", triggered_by=f"telegram:{ADMIN_ID}")
        assert "libmaint_meta_new_value" not in context.user_data
        text = message.edit_text.call_args.args[0]
        assert "Artist geändert" in text


# ═════════════════════════════════════════════════════════════════════
# 🎵 Titel bearbeiten
# ═════════════════════════════════════════════════════════════════════


class TestMetaTitleStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_title_start(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_artist_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_meta_title_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_no_tracks_shows_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "artist_targets", return_value=[]):
            run(handler.handle_meta_title_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine Tracks" in text

    def test_lists_tracks_as_index_based_buttons(self, handler, context):
        tracks = ["Bausa/01 - Bass im Blut.m4a", "Bausa/02 - Nachtfahrt.m4a"]
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "artist_targets", return_value=tracks):
            run(handler.handle_meta_title_start(update, context, 2))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:title:pick:2:0" in callback_datas
        assert "libmaint:meta:title:pick:2:1" in callback_datas
        assert "libmaint:meta:2" in callback_datas  # Zurück
        # kein Rohpfad in callback_data:
        assert not any("Bass im Blut" in cd for cd in callback_datas)


class TestMetaTitlePick:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_title_pick(update, context, 0, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_artist_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_meta_title_pick(update, context, 0, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_invalid_track_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_track_by_index", return_value=None):
            run(handler.handle_meta_title_pick(update, context, 0, 9))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Track nicht mehr gefunden" in text

    def test_valid_pick_sets_state_and_shows_current_title(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_track_by_index", return_value="Bausa/a.m4a"), \
             patch.object(lmh_module, "current_title", return_value="Bass im Blut"):
            run(handler.handle_meta_title_pick(update, context, 0, 0))
        assert context.user_data["libmaint_meta_artist"] == "Bausa"
        assert context.user_data["libmaint_meta_track"] == "Bausa/a.m4a"
        assert context.user_data["libmaint_meta_current_title"] == "Bass im Blut"
        assert context.user_data["libmaint_awaiting_title_text"] is True
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Bass im Blut" in text
        assert "Bausa/a.m4a" in text

    def test_title_read_exception_reported(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_track_by_index", return_value="Bausa/a.m4a"), \
             patch.object(lmh_module, "current_title", side_effect=RuntimeError("kaputt")):
            run(handler.handle_meta_title_pick(update, context, 0, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Unerwarteter Fehler" in text


class TestProcessPendingTitleInput:
    def test_not_awaiting_returns_false(self, handler, context):
        update = _mock_update(ADMIN_ID, has_message=True)
        assert run(handler.process_pending_title_input(update, context, "Neu")) is False

    def test_session_expired_when_track_missing(self, handler, context):
        context.user_data["libmaint_awaiting_title_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_title_input(update, context, "Neu"))
        assert handled is True
        assert "libmaint_awaiting_title_text" not in context.user_data

    @pytest.mark.parametrize("text", ["", "   ", "a\nb", "x" * 201])
    def test_invalid_input_stays_awaiting(self, handler, context, text):
        context.user_data["libmaint_awaiting_title_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_track"] = "Bausa/a.m4a"
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_title_input(update, context, text))
        assert handled is True
        assert context.user_data["libmaint_awaiting_title_text"] is True

    def test_valid_input_triggers_background_preview(self, handler, context):
        context.user_data["libmaint_awaiting_title_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_track"] = "Bausa/a.m4a"
        context.user_data["libmaint_meta_current_title"] = "Alt"
        update = _mock_update(ADMIN_ID, has_message=True)
        with patch.object(handler, "_run_title_edit_preview_and_report", AsyncMock()) as mocked:
            handled = run(handler.process_pending_title_input(update, context, "  Neuer Titel  "))
        assert handled is True
        assert "libmaint_awaiting_title_text" not in context.user_data
        assert context.user_data["libmaint_meta_new_value"] == "Neuer Titel"
        mocked.assert_called_once()
        assert mocked.call_args.args[1:] == ("Bausa", "Bausa/a.m4a", "Alt", "Neuer Titel")


class TestTitleEditPreviewAndReport:
    def test_no_automatic_title_cleanup_note(self, handler):
        """Kein TitleCleaner (Auftrag §8/9): der eingegebene Wert wird
        unveraendert (nur HTML-escaped fuer parse_mode="HTML") in der
        Vorschau angezeigt - keine Marketing-Suffix-/Anfuehrungszeichen-
        Bereinigung."""
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "DRY_RUN", issue_code="TITLE_MANUAL_EDIT")]
        with patch.object(lmh_module, "preview_title_edit", return_value=_preview(1, outcomes, action="title-edit")):
            run(handler._run_title_edit_preview_and_report(
                message, "Bausa", "Bausa/a.m4a", "Alt", '"Neu" prod. XY',
            ))
        text = message.edit_text.call_args.args[0]
        assert "prod. XY" in text
        assert "Alt" in text

    def test_identical_value_shows_no_change_message(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "SKIPPED", issue_code="TITLE_MANUAL_EDIT")]
        with patch.object(lmh_module, "preview_title_edit", return_value=_preview(1, outcomes, action="title-edit")):
            run(handler._run_title_edit_preview_and_report(message, "Bausa", "Bausa/a.m4a", "Alt", "Alt"))
        text = message.edit_text.call_args.args[0]
        assert "entspricht bereits dem aktuellen Wert" in text

    def test_file_still_present_but_unsafe_shows_distinct_message(self, handler):
        """Datei ist noch vorhanden, aber laut safety_check() aktuell
        nicht schreibbar (z. B. leere Datei, nicht unterstuetztes Format
        - target_count bleibt 1, ein SKIPPED-Outcome mit "Safety: ..."-
        Grund kommt zurueck) - eigene, unterscheidbare Meldung statt der
        generischen 'identischer Wert'-Nachricht (Auftrag §14). Seit
        CC-AC-6 (Containment-Haertung) ist "Datei zwischen Track-Auswahl
        und Eingabe komplett verschwunden" ein SEPARATER Fall mit
        target_count == 0 statt target_count == 1 + SKIPPED-Outcome,
        siehe test_target_count_zero_shows_file_gone_message() unten -
        Adversarial-Review-Fund CC-AC-6 Runde 1/2, PR #287."""
        message = Mock()
        message.edit_text = AsyncMock()
        skipped = ExecOutcome(
            file="Bausa/a.m4a", issue_code="TITLE_MANUAL_EDIT", action="TITLE_MANUAL_EDIT",
            status="SKIPPED", reason="Safety: leere Datei",
        )
        with patch.object(lmh_module, "preview_title_edit", return_value=_preview(1, [skipped], action="title-edit")):
            run(handler._run_title_edit_preview_and_report(message, "Bausa", "Bausa/a.m4a", "Alt", "Neu"))
        text = message.edit_text.call_args.args[0]
        assert "nicht mehr verfügbar" in text
        assert "entspricht bereits dem aktuellen Wert" not in text

    def test_target_count_zero_shows_file_gone_message(self, handler):
        """Regression (Adversarial-Review-Fund CC-AC-6 Runde 1/2, PR #287):
        seit der Containment-Haertung in `_title_edit_targets()` liefert
        eine zwischen Track-Auswahl und Eingabe verschwundene Datei
        `target_count == 0` UND `outcomes == []` (kein SKIPPED-Outcome
        mehr, da `apply_title_edit()` mit einer leeren Zielmenge
        aufgerufen wird) - vor dem Fix fiel dieser Fall faelschlich auf
        die generische 'Wert entspricht bereits dem aktuellen Wert'-
        Meldung durch, weil `skip = preview.outcomes[0] if ... else None`
        dann `None` war."""
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "preview_title_edit", return_value=_preview(0, [], action="title-edit")):
            run(handler._run_title_edit_preview_and_report(message, "Bausa", "Bausa/a.m4a", "Alt", "Neu"))
        text = message.edit_text.call_args.args[0]
        assert "nicht mehr verfügbar" in text
        assert "entspricht bereits dem aktuellen Wert" not in text

    def test_preview_never_writes(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "DRY_RUN", issue_code="TITLE_MANUAL_EDIT")]
        with patch.object(lmh_module, "preview_title_edit", return_value=_preview(1, outcomes, action="title-edit")), \
             patch.object(lmh_module, "execute_title_edit") as mocked_execute:
            run(handler._run_title_edit_preview_and_report(message, "Bausa", "Bausa/a.m4a", "Alt", "Neu"))
        mocked_execute.assert_not_called()


class TestMetaTitleConfirmAndExecute:
    def test_confirm_session_expired(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_title_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Sitzung abgelaufen" in text

    def test_confirm_shows_execute_and_cancel(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_track"] = "Bausa/a.m4a"
        context.user_data["libmaint_meta_new_value"] = "Neu"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_title_confirm(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:title:execute" in callback_datas
        assert "libmaint:start" in callback_datas

    def test_execute_lock_conflict(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True):
            run(handler.handle_meta_title_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_execute_triggers_background_task(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_track"] = "Bausa/a.m4a"
        context.user_data["libmaint_meta_new_value"] = "Neu"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(handler, "_run_title_edit_execute_and_report", AsyncMock()) as mocked:
            run(handler.handle_meta_title_execute(update, context))
        mocked.assert_called_once()
        args = mocked.call_args.args
        assert args[2:] == ("Bausa", "Bausa/a.m4a", "Neu", ADMIN_ID)


class TestTitleEditExecuteAndReport:
    def test_success_clears_state_and_shows_result(self, handler, context):
        context.user_data["libmaint_meta_new_value"] = "Neu"
        context.user_data["libmaint_meta_track"] = "Bausa/a.m4a"
        context.user_data["libmaint_meta_current_title"] = "Alt"
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_title_edit", return_value=_run_result()) as mocked:
            run(handler._run_title_edit_execute_and_report(
                message, context, "Bausa", "Bausa/a.m4a", "Neu", ADMIN_ID,
            ))
        mocked.assert_called_once_with("Bausa", "Bausa/a.m4a", "Neu", triggered_by=f"telegram:{ADMIN_ID}")
        assert "libmaint_meta_new_value" not in context.user_data
        assert "libmaint_meta_track" not in context.user_data
        assert "libmaint_meta_current_title" not in context.user_data
        text = message.edit_text.call_args.args[0]
        assert "Titel geändert" in text

    def test_lock_error_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_title_edit", side_effect=RepairAlreadyRunningError("busy")):
            run(handler._run_title_edit_execute_and_report(
                message, context, "Bausa", "Bausa/a.m4a", "Neu", ADMIN_ID,
            ))
        assert "busy" in message.edit_text.call_args.args[0]


# ═════════════════════════════════════════════════════════════════════
# Cross-Flow State Reset (Review-Fund v1, Auftrag v2 §27)
# ═════════════════════════════════════════════════════════════════════
#
# Ohne _reset_meta_edit_state() an jedem neuen Flow-Einstiegspunkt wuerde
# ein abgebrochener Flow sein awaiting-Flag/seinen Zielwert an einen
# spaeter gestarteten, anderen Flow "vererben" - z. B. eine Titel-
# Eingabe faelschlich als Artist-Umbenennung interpretiert werden, weil
# handle_text_message() die Flags in fester Reihenfolge prueft.


class TestCrossFlowStateReset:
    def test_starting_artist_flow_clears_stale_title_awaiting_flag(self, handler, context):
        context.user_data["libmaint_awaiting_title_text"] = True
        context.user_data["libmaint_meta_track"] = "Bausa/old.m4a"
        context.user_data["libmaint_meta_new_value"] = "stale title"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_meta_artist_start(update, context, 0))
        assert "libmaint_awaiting_title_text" not in context.user_data
        assert "libmaint_meta_track" not in context.user_data
        assert "libmaint_meta_new_value" not in context.user_data
        assert context.user_data["libmaint_awaiting_artist_text"] is True

    def test_picking_track_clears_stale_artist_awaiting_flag(self, handler, context):
        context.user_data["libmaint_awaiting_artist_text"] = True
        context.user_data["libmaint_meta_new_value"] = "stale artist"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_track_by_index", return_value="Bausa/a.m4a"), \
             patch.object(lmh_module, "current_title", return_value="T"):
            run(handler.handle_meta_title_pick(update, context, 0, 0))
        assert "libmaint_awaiting_artist_text" not in context.user_data
        assert "libmaint_meta_new_value" not in context.user_data
        assert context.user_data["libmaint_awaiting_title_text"] is True

    def test_picking_album_clears_stale_artist_and_title_state(self, handler, context):
        context.user_data["libmaint_awaiting_artist_text"] = True
        context.user_data["libmaint_meta_track"] = "Bausa/old.m4a"
        context.user_data["libmaint_meta_current_title"] = "Old"
        context.user_data["libmaint_meta_new_value"] = "stale"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="2020 - Album X"), \
             patch.object(lmh_module, "current_album", return_value="Album X"):
            run(handler.handle_meta_album_pick(update, context, 0, 0))
        assert "libmaint_awaiting_artist_text" not in context.user_data
        assert "libmaint_meta_track" not in context.user_data
        assert "libmaint_meta_current_title" not in context.user_data
        assert "libmaint_meta_new_value" not in context.user_data
        assert context.user_data["libmaint_awaiting_album_text"] is True

    def test_picking_albumartist_clears_stale_album_edit_state(self, handler, context):
        context.user_data["libmaint_awaiting_album_text"] = True
        context.user_data["libmaint_meta_current_album"] = "Old Album Name"
        context.user_data["libmaint_meta_new_value"] = "stale"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="2020 - Album X"), \
             patch.object(lmh_module, "current_album_artist", return_value="Bausa"):
            run(handler.handle_meta_albumartist_pick(update, context, 0, 0))
        assert "libmaint_awaiting_album_text" not in context.user_data
        assert "libmaint_meta_current_album" not in context.user_data
        assert "libmaint_meta_new_value" not in context.user_data
        assert context.user_data["libmaint_awaiting_albumartist_text"] is True

    def test_re_entering_meta_menu_clears_everything(self, handler, context):
        context.user_data["libmaint_awaiting_album_text"] = True
        context.user_data["libmaint_awaiting_albumartist_text"] = True
        context.user_data["libmaint_meta_album"] = "stale"
        context.user_data["libmaint_meta_new_value"] = "stale"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_meta_menu(update, context, 0))
        for key in (
            "libmaint_awaiting_album_text", "libmaint_awaiting_albumartist_text",
            "libmaint_meta_album", "libmaint_meta_new_value",
        ):
            assert key not in context.user_data


class TestMetaMenuAlbumButtons:
    def test_shows_album_and_albumartist_buttons(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"):
            run(handler.handle_meta_menu(update, context, 0))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:album:0" in callback_datas
        assert "libmaint:meta:albumartist:0" in callback_datas


# ═════════════════════════════════════════════════════════════════════
# 💿 Album bearbeiten
# ═════════════════════════════════════════════════════════════════════


class TestMetaAlbumStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_album_start(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_artist_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value=None):
            run(handler.handle_meta_album_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "nicht mehr gefunden" in text

    def test_no_albums_shows_message(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "list_artist_albums", return_value=[]):
            run(handler.handle_meta_album_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine Alben oder Singles" in text

    def test_lists_albums_as_index_based_buttons(self, handler, context):
        albums = ["2019 - Album A", "2020 - Album B"]
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "list_artist_albums", return_value=albums):
            run(handler.handle_meta_album_start(update, context, 3))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:album:pick:3:0" in callback_datas
        assert "libmaint:meta:album:pick:3:1" in callback_datas
        assert "libmaint:meta:3" in callback_datas  # Zurück

    def test_artist_with_only_singles_shows_pickable_buttons(self, handler, context):
        """Nutzer-Fund 2026-09-20 (Apache 207): ein Artist ohne Mehr-
        Track-Album-Ordner bekommt trotzdem einen nicht-leeren Picker -
        jede Single als eigener Button."""
        albums = ["Singles/2019 - Roller.m4a", "Singles/2020 - Powerbank.m4a"]
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Apache 207"), \
             patch.object(lmh_module, "list_artist_albums", return_value=albums):
            run(handler.handle_meta_album_start(update, context, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Keine Alben oder Singles" not in text
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:album:pick:0:0" in callback_datas
        assert "libmaint:meta:album:pick:0:1" in callback_datas

    def test_single_button_label_differs_from_album_button_label(self, handler, context):
        albums = ["2020 - Album X", "Singles/2019 - Roller.m4a"]
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "list_artist_albums", return_value=albums):
            run(handler.handle_meta_album_start(update, context, 0))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in keyboard.inline_keyboard for b in row]
        assert any(label.startswith("💿") and "Album X" in label for label in labels)
        assert any(label.startswith("🎵") and "Roller" in label and "Singles/" not in label for label in labels)


class TestAlbumDisplayLabel:
    def test_regular_album_unchanged(self, handler):
        assert handler._album_display_label("2020 - Album X") == "2020 - Album X"

    def test_single_gets_suffix_and_no_path_prefix(self, handler):
        assert handler._album_display_label("Singles/2019 - Roller.m4a") == "2019 - Roller (Single)"


class TestMetaAlbumPick:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_album_pick(update, context, 0, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_album_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value=None):
            run(handler.handle_meta_album_pick(update, context, 0, 9))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Album nicht mehr gefunden" in text

    def test_valid_pick_sets_state_and_shows_current_album(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="2020 - Album X"), \
             patch.object(lmh_module, "current_album", return_value="Album X"):
            run(handler.handle_meta_album_pick(update, context, 0, 0))
        assert context.user_data["libmaint_meta_artist"] == "Bausa"
        assert context.user_data["libmaint_meta_album"] == "2020 - Album X"
        assert context.user_data["libmaint_meta_current_album"] == "Album X"
        assert context.user_data["libmaint_awaiting_album_text"] is True
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Album X" in text

    def test_album_read_exception_reported(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="2020 - Album X"), \
             patch.object(lmh_module, "current_album", side_effect=RuntimeError("kaputt")):
            run(handler.handle_meta_album_pick(update, context, 0, 0))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Unerwarteter Fehler" in text

    def test_picking_single_shows_friendly_label(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Apache 207"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="Singles/2019 - Roller.m4a"), \
             patch.object(lmh_module, "current_album", return_value="Roller"):
            run(handler.handle_meta_album_pick(update, context, 0, 0))
        assert context.user_data["libmaint_meta_album"] == "Singles/2019 - Roller.m4a"
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "2019 - Roller (Single)" in text
        assert "Singles/" not in text


class TestProcessPendingAlbumInput:
    def test_not_awaiting_returns_false(self, handler, context):
        update = _mock_update(ADMIN_ID, has_message=True)
        assert run(handler.process_pending_album_input(update, context, "Neu")) is False

    def test_session_expired_when_album_missing(self, handler, context):
        context.user_data["libmaint_awaiting_album_text"] = True
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_album_input(update, context, "Neu"))
        assert handled is True
        assert "libmaint_awaiting_album_text" not in context.user_data

    @pytest.mark.parametrize("text", ["", "   ", "a\nb", "x" * 201])
    def test_invalid_input_stays_awaiting(self, handler, context, text):
        context.user_data["libmaint_awaiting_album_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_album_input(update, context, text))
        assert handled is True
        assert context.user_data["libmaint_awaiting_album_text"] is True

    def test_valid_input_triggers_background_preview(self, handler, context):
        context.user_data["libmaint_awaiting_album_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_current_album"] = "Album X"
        update = _mock_update(ADMIN_ID, has_message=True)
        with patch.object(handler, "_run_album_edit_preview_and_report", AsyncMock()) as mocked:
            handled = run(handler.process_pending_album_input(update, context, "  Album X Deluxe  "))
        assert handled is True
        assert "libmaint_awaiting_album_text" not in context.user_data
        assert context.user_data["libmaint_meta_new_value"] == "Album X Deluxe"
        mocked.assert_called_once()
        assert mocked.call_args.args[1:] == (
            "Bausa", "2020 - Album X", "Album X", "Album X Deluxe",
        )


class TestAlbumEditPreviewAndReport:
    def test_no_files_found(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "preview_album_edit", return_value=_preview(0, [], action="album-edit")):
            run(handler._run_album_edit_preview_and_report(
                message, "Bausa", "2020 - Album X", "Album X", "Neu",
            ))
        text = message.edit_text.call_args.args[0]
        assert "Keine Dateien" in text

    def test_identical_value_shows_no_change_message(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "SKIPPED", issue_code="ALBUM_MANUAL_EDIT")]
        with patch.object(lmh_module, "preview_album_edit", return_value=_preview(1, outcomes, action="album-edit")):
            run(handler._run_album_edit_preview_and_report(
                message, "Bausa", "2020 - Album X", "Album X", "Album X",
            ))
        text = message.edit_text.call_args.args[0]
        assert "entspricht bereits dem aktuellen Wert" in text

    def test_shows_preview_with_confirm_and_cancel(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [
            _outcome("Bausa/a.m4a", "DRY_RUN", issue_code="ALBUM_MANUAL_EDIT"),
            _outcome("Bausa/b.m4a", "DRY_RUN", issue_code="ALBUM_MANUAL_EDIT"),
        ]
        with patch.object(lmh_module, "preview_album_edit", return_value=_preview(2, outcomes, action="album-edit")):
            run(handler._run_album_edit_preview_and_report(
                message, "Bausa", "2020 - Album X", "Album X", "Album X (Deluxe)",
            ))
        text = message.edit_text.call_args.args[0]
        assert "Album X" in text and "Album X (Deluxe)" in text
        assert "Betroffene Tracks: 2" in text
        assert "Betroffene Dateien: 2" in text
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:album:confirm" in callback_datas
        assert "libmaint:start" in callback_datas

    def test_preview_never_writes(self, handler):
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "DRY_RUN", issue_code="ALBUM_MANUAL_EDIT")]
        with patch.object(lmh_module, "preview_album_edit", return_value=_preview(1, outcomes, action="album-edit")), \
             patch.object(lmh_module, "execute_album_edit") as mocked_execute:
            run(handler._run_album_edit_preview_and_report(
                message, "Bausa", "2020 - Album X", "Album X", "Album X (Deluxe)",
            ))
        mocked_execute.assert_not_called()


class TestMetaAlbumConfirmAndExecute:
    def test_confirm_session_expired(self, handler, context):
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_album_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Sitzung abgelaufen" in text

    def test_confirm_shows_execute_and_cancel(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_new_value"] = "Album X (Deluxe)"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_album_confirm(update, context))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:album:execute" in callback_datas
        assert "libmaint:start" in callback_datas

    def test_execute_lock_conflict(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=True):
            run(handler.handle_meta_album_execute(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "läuft gerade" in text

    def test_execute_triggers_background_task(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_new_value"] = "Album X (Deluxe)"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(handler, "_run_album_edit_execute_and_report", AsyncMock()) as mocked:
            run(handler.handle_meta_album_execute(update, context))
        mocked.assert_called_once()
        args = mocked.call_args.args
        assert args[2:] == ("Bausa", "2020 - Album X", "Album X (Deluxe)", ADMIN_ID)


class TestAlbumEditExecuteAndReport:
    def test_success_clears_state_and_shows_result(self, handler, context):
        context.user_data["libmaint_meta_new_value"] = "Neu"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_current_album"] = "Alt"
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_album_edit", return_value=_run_result()) as mocked:
            run(handler._run_album_edit_execute_and_report(
                message, context, "Bausa", "2020 - Album X", "Neu", ADMIN_ID,
            ))
        mocked.assert_called_once_with("Bausa", "2020 - Album X", "Neu", triggered_by=f"telegram:{ADMIN_ID}")
        assert "libmaint_meta_new_value" not in context.user_data
        assert "libmaint_meta_album" not in context.user_data
        assert "libmaint_meta_current_album" not in context.user_data
        text = message.edit_text.call_args.args[0]
        assert "Album geändert" in text

    def test_lock_error_shown(self, handler, context):
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_album_edit", side_effect=RepairAlreadyRunningError("busy")):
            run(handler._run_album_edit_execute_and_report(
                message, context, "Bausa", "2020 - Album X", "Neu", ADMIN_ID,
            ))
        assert "busy" in message.edit_text.call_args.args[0]


# ═════════════════════════════════════════════════════════════════════
# 👤 Albuminterpret bearbeiten
# ═════════════════════════════════════════════════════════════════════


class TestMetaAlbumArtistStart:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_albumartist_start(update, context, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_lists_albums_as_index_based_buttons(self, handler, context):
        albums = ["2019 - Album A", "2020 - Album B"]
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "list_artist_albums", return_value=albums):
            run(handler.handle_meta_albumartist_start(update, context, 0))
        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:albumartist:pick:0:0" in callback_datas
        assert "libmaint:meta:albumartist:pick:0:1" in callback_datas


class TestMetaAlbumArtistPick:
    def test_non_admin_rejected(self, handler, context):
        update = _mock_update(OTHER_ID)
        run(handler.handle_meta_albumartist_pick(update, context, 0, 0))
        update.callback_query.answer.assert_called_with("⛔ Keine Berechtigung", show_alert=True)

    def test_invalid_album_index_shows_retry(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value=None):
            run(handler.handle_meta_albumartist_pick(update, context, 0, 9))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Album nicht mehr gefunden" in text

    def test_valid_pick_sets_state_and_shows_current_album_artist(self, handler, context):
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "resolve_artist_by_index", return_value="Bausa"), \
             patch.object(lmh_module, "resolve_album_by_index", return_value="2020 - Album X"), \
             patch.object(lmh_module, "current_album_artist", return_value="Bausa"):
            run(handler.handle_meta_albumartist_pick(update, context, 0, 0))
        assert context.user_data["libmaint_meta_album"] == "2020 - Album X"
        assert context.user_data["libmaint_meta_current_album_artist"] == "Bausa"
        assert context.user_data["libmaint_awaiting_albumartist_text"] is True
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Bausa" in text


class TestProcessPendingAlbumArtistInput:
    def test_not_awaiting_returns_false(self, handler, context):
        update = _mock_update(ADMIN_ID, has_message=True)
        assert run(handler.process_pending_albumartist_input(update, context, "Neu")) is False

    @pytest.mark.parametrize("text", ["", "   ", "a\nb", "x" * 201])
    def test_invalid_input_stays_awaiting(self, handler, context, text):
        context.user_data["libmaint_awaiting_albumartist_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        update = _mock_update(ADMIN_ID, has_message=True)
        handled = run(handler.process_pending_albumartist_input(update, context, text))
        assert handled is True
        assert context.user_data["libmaint_awaiting_albumartist_text"] is True

    def test_valid_input_triggers_background_preview(self, handler, context):
        context.user_data["libmaint_awaiting_albumartist_text"] = True
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_current_album_artist"] = "Bausa"
        update = _mock_update(ADMIN_ID, has_message=True)
        with patch.object(handler, "_run_album_artist_edit_preview_and_report", AsyncMock()) as mocked:
            handled = run(handler.process_pending_albumartist_input(update, context, "  Bausa & Friends  "))
        assert handled is True
        assert context.user_data["libmaint_meta_new_value"] == "Bausa & Friends"
        mocked.assert_called_once()
        assert mocked.call_args.args[1:] == (
            "Bausa", "2020 - Album X", "Bausa", "Bausa & Friends",
        )


class TestAlbumArtistEditPreviewAndReport:
    def test_shows_preview_with_artist_tag_unaffected_note(self, handler):
        """Auftrag §11/§13: die Preview darf niemals suggerieren, dass
        ©ART veraendert wird."""
        message = Mock()
        message.edit_text = AsyncMock()
        outcomes = [_outcome("Bausa/a.m4a", "DRY_RUN", issue_code="ALBUM_ARTIST_MANUAL_EDIT")]
        with patch.object(
            lmh_module, "preview_album_artist_edit",
            return_value=_preview(1, outcomes, action="album-artist-edit"),
        ):
            run(handler._run_album_artist_edit_preview_and_report(
                message, "Bausa", "2020 - Album X", "Bausa", "Bausa & Friends",
            ))
        text = message.edit_text.call_args.args[0]
        assert "Friends" in text  # html.escape() macht aus "&" -> "&amp;"
        keyboard = message.edit_text.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "libmaint:meta:albumartist:confirm" in callback_datas


class TestMetaAlbumArtistConfirmAndExecute:
    def test_confirm_mentions_artist_tag_stays_unchanged(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_new_value"] = "Bausa & Friends"
        update = _mock_update(ADMIN_ID)
        run(handler.handle_meta_albumartist_confirm(update, context))
        text = update.callback_query.edit_message_text.call_args.args[0]
        assert "©ART" in text
        assert "unverändert" in text

    def test_execute_triggers_background_task(self, handler, context):
        context.user_data["libmaint_meta_artist"] = "Bausa"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_new_value"] = "Bausa & Friends"
        update = _mock_update(ADMIN_ID)
        with patch.object(lmh_module, "is_repair_running", return_value=False), \
             patch.object(handler, "_run_album_artist_edit_execute_and_report", AsyncMock()) as mocked:
            run(handler.handle_meta_albumartist_execute(update, context))
        mocked.assert_called_once()
        args = mocked.call_args.args
        assert args[2:] == ("Bausa", "2020 - Album X", "Bausa & Friends", ADMIN_ID)


class TestAlbumArtistEditExecuteAndReport:
    def test_success_clears_state_and_shows_result(self, handler, context):
        context.user_data["libmaint_meta_new_value"] = "Bausa & Friends"
        context.user_data["libmaint_meta_album"] = "2020 - Album X"
        context.user_data["libmaint_meta_current_album_artist"] = "Bausa"
        message = Mock()
        message.edit_text = AsyncMock()
        with patch.object(lmh_module, "execute_album_artist_edit", return_value=_run_result()) as mocked:
            run(handler._run_album_artist_edit_execute_and_report(
                message, context, "Bausa", "2020 - Album X", "Bausa & Friends", ADMIN_ID,
            ))
        mocked.assert_called_once_with(
            "Bausa", "2020 - Album X", "Bausa & Friends", triggered_by=f"telegram:{ADMIN_ID}",
        )
        assert "libmaint_meta_new_value" not in context.user_data
        assert "libmaint_meta_album" not in context.user_data
        assert "libmaint_meta_current_album_artist" not in context.user_data
        text = message.edit_text.call_args.args[0]
        assert "Albuminterpret geändert" in text
