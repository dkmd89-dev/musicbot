# tests/test_library_doctor_handler.py
# -*- coding: utf-8 -*-
"""
Tests fuer handlers/library_doctor_handler.py::LibraryDoctorHandler
(Phase 3, P1.3 "MusicBot Doctor").

services/library_repair/doctor_runner.py (run_health_scan()/
run_safe_automatic_repair()) ist hier durchgehend gemockt - dessen eigene
echte Subprozess-Integration wird getrennt getestet (analog zum bereits
etablierten Muster in test_reprocessing_menu_handler.py fuer
services/metadata/reprocessing_runner.py, CLAUDE.md Abschnitt 8).
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.library_doctor_handler import LibraryDoctorHandler, _short_issue_label
from services.library_repair.doctor_runner import DoctorRepairResult, DoctorScanResult


class FakeConfig:
    OWNER_USER_ID = 111
    ADMIN_USER_IDS = [222]


OWNER_ID = 111
ADMIN_ID = 222
OTHER_ID = 999


@pytest.fixture
def handler():
    return LibraryDoctorHandler(FakeConfig(), logger_factory=lambda name: Mock())


def _mock_update(user_id):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = Mock()
    update.callback_query.message.edit_text = AsyncMock()
    return update


def _mock_context():
    return Mock()


def run_async(coro):
    return asyncio.run(coro)


def last_edit_text(update):
    return update.callback_query.edit_message_text.call_args.args[0]


def last_edit_keyboard_texts(update):
    markup = update.callback_query.edit_message_text.call_args.kwargs.get(
        "reply_markup"
    )
    if markup is None:
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _sample_report(extra_issues=None):
    issues_by_code = {"GENRE_DELIMITER_INCONSISTENT": 3, "LYRICS_MISSING": 19}
    issues_by_code.update(extra_issues or {})
    return {
        "statistics": {
            "total_files": 388,
            "total_artists": 12,
            "total_albums": 34,
            "issues_by_code": issues_by_code,
        },
        "health": {"score": 98.0, "status": "EXCELLENT"},
    }


class TestIsAdminDirect:
    """ARCH-023/P-7: direkte Charakterisierung von _is_admin() selbst
    (bisher nur indirekt ueber handle_scan() etc. getestet) - Baseline
    vor der Umstellung auf permissions.is_admin_or_owner(), belegt
    Aequivalenz."""

    def test_owner_is_admin(self, handler):
        assert handler._is_admin(OWNER_ID) is True

    def test_configured_admin_is_admin(self, handler):
        assert handler._is_admin(ADMIN_ID) is True

    def test_other_user_is_not_admin(self, handler):
        assert handler._is_admin(OTHER_ID) is False


class TestHandleScanAdminGating:
    def test_non_admin_is_rejected(self, handler):
        update = _mock_update(OTHER_ID)

        run_async(handler.handle_scan(update, _mock_context()))

        update.callback_query.answer.assert_awaited_once()
        assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True
        update.callback_query.edit_message_text.assert_not_called()

    def test_owner_is_allowed_to_start_scan(self, handler):
        """_run_scan_and_report() selbst wird gemockt statt asyncio.create_task
        zu patchen - ein gemocktes create_task() wuerde die von
        self._run_scan_and_report(...) erzeugte echte Coroutine nie
        awaiten und eine 'coroutine was never awaited'-Warnung erzeugen
        (siehe test_reprocessing_menu_handler.py fuer dasselbe Muster)."""
        update = _mock_update(OWNER_ID)

        with patch.object(handler, "_run_scan_and_report", AsyncMock()):
            run_async(handler.handle_scan(update, _mock_context()))

        update.callback_query.answer.assert_awaited_once_with()
        update.callback_query.edit_message_text.assert_awaited_once()

    def test_admin_is_allowed_to_start_scan(self, handler):
        update = _mock_update(ADMIN_ID)

        with patch.object(handler, "_run_scan_and_report", AsyncMock()):
            run_async(handler.handle_scan(update, _mock_context()))

        update.callback_query.answer.assert_awaited_once_with()
        update.callback_query.edit_message_text.assert_awaited_once()


class TestFormatScanResult:
    def test_success_shows_counts_score_and_apply_button(self, handler):
        result = DoctorScanResult(exit_code=0, report=_sample_report())

        text, keyboard = handler._format_scan_result(result)

        assert "388" in text
        assert "34" in text
        assert "12" in text
        assert "98.0" in text
        buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("SAFE_AUTOMATIC" in b for b in buttons)

    def test_info_severity_codes_use_human_description_not_raw_code(self, handler):
        """GENRE_DELIMITER_INCONSISTENT/LYRICS_MISSING sind beides INFO -
        keine rohen SNAKE_CASE-Codes mehr im Text, sondern die Beschreibung
        aus services/library_health/issues.py (Single Source of Truth)."""
        result = DoctorScanResult(exit_code=0, report=_sample_report())

        text, _ = handler._format_scan_result(result)

        assert "GENRE_DELIMITER_INCONSISTENT" not in text
        assert "LYRICS_MISSING" not in text
        assert "Nur Beobachtung, kein Mangel" in text
        assert "Keine Befunde, die den Score senken" in text

    def test_warning_or_error_codes_appear_in_problem_section(self, handler):
        """META_ARTIST_MISSING ist ERROR-Severity - muss im 'wirkt sich auf
        den Score aus'-Abschnitt landen, nicht bei den Beobachtungen."""
        result = DoctorScanResult(
            exit_code=0,
            report=_sample_report(extra_issues={"META_ARTIST_MISSING": 2}),
        )

        text, _ = handler._format_scan_result(result)

        assert "Wirkt sich auf den Score aus" in text
        assert "Nur Beobachtung, kein Mangel" in text  # die INFO-Codes bleiben daneben bestehen
        assert "Keine Befunde, die den Score senken" not in text

    def test_unregistered_code_falls_back_to_raw_code_as_problem(self, handler):
        """Ein (theoretisch) unbekannter Code darf nicht stillschweigend als
        harmlose Beobachtung verschwinden - Fail-safe: als Problem anzeigen."""
        result = DoctorScanResult(
            exit_code=0,
            report=_sample_report(extra_issues={"SOME_UNKNOWN_CODE": 1}),
        )

        text, _ = handler._format_scan_result(result)

        assert "SOME_UNKNOWN_CODE" in text
        assert "Wirkt sich auf den Score aus" in text

    def test_failure_shows_error_without_apply_button(self, handler):
        result = DoctorScanResult(
            exit_code=3, report=None, stderr_tail="boom"
        )

        text, keyboard = handler._format_scan_result(result)

        assert "fehlgeschlagen" in text
        buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert not any("SAFE_AUTOMATIC" in b for b in buttons)

    def test_timeout_shows_timeout_detail(self, handler):
        result = DoctorScanResult(
            exit_code=None, report=None, timed_out=True,
            error_message="Timeout nach 900s - Prozess wurde beendet.",
        )

        text, _ = handler._format_scan_result(result)

        assert "Timeout" in text


class TestRunScanAndReport:
    def test_success_result_is_formatted_and_sent(self, handler):
        update = _mock_update(OWNER_ID)
        message = update.callback_query.message

        with patch(
            "handlers.library_doctor_handler.run_health_scan",
            new=AsyncMock(return_value=DoctorScanResult(exit_code=0, report=_sample_report())),
        ):
            run_async(handler._run_scan_and_report(message))

        message.edit_text.assert_awaited_once()
        sent_text = message.edit_text.call_args.args[0]
        assert "388" in sent_text

    def test_unexpected_exception_shows_generic_error_not_crash(self, handler):
        update = _mock_update(OWNER_ID)
        message = update.callback_query.message

        with patch(
            "handlers.library_doctor_handler.run_health_scan",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            run_async(handler._run_scan_and_report(message))  # darf nicht raisen

        message.edit_text.assert_awaited_once()
        assert "boom" in message.edit_text.call_args.args[0]


class TestApplySafeConfirmPrompt:
    def test_non_admin_is_rejected(self, handler):
        update = _mock_update(OTHER_ID)

        run_async(handler.handle_apply_safe_confirm_prompt(update, _mock_context()))

        update.callback_query.edit_message_text.assert_not_called()

    def test_admin_sees_confirmation_with_two_buttons(self, handler):
        update = _mock_update(ADMIN_ID)

        run_async(handler.handle_apply_safe_confirm_prompt(update, _mock_context()))

        text = last_edit_text(update)
        assert "SAFE_AUTOMATIC" in text
        buttons = last_edit_keyboard_texts(update)
        assert any("Ja" in b for b in buttons)
        assert any("Abbrechen" in b for b in buttons)


class TestApplySafeConfirmed:
    def test_non_admin_is_rejected(self, handler):
        update = _mock_update(OTHER_ID)

        run_async(handler.handle_apply_safe_confirmed(update, _mock_context()))

        update.callback_query.edit_message_text.assert_not_called()

    def test_admin_starts_background_repair_task(self, handler):
        update = _mock_update(ADMIN_ID)

        with patch.object(handler, "_run_repair_and_report", AsyncMock()):
            run_async(handler.handle_apply_safe_confirmed(update, _mock_context()))

        update.callback_query.edit_message_text.assert_awaited_once()


class TestFormatRepairResult:
    def test_success_shows_stdout_tail(self, handler):
        result = DoctorRepairResult(exit_code=0, stdout_tail="12 success · 0 failed")

        text, _ = handler._format_repair_result(result)

        assert "erfolgreich" in text
        assert "12 success" in text

    def test_non_zero_exit_shown_as_warning_not_success(self, handler):
        result = DoctorRepairResult(exit_code=1, stdout_tail="1 success · new issue")

        text, _ = handler._format_repair_result(result)

        assert "Exit-Code 1" in text

    def test_timeout_or_start_failure_shown_as_could_not_execute(self, handler):
        result = DoctorRepairResult(
            exit_code=None, error_message="Timeout nach 900s - Prozess wurde beendet."
        )

        text, _ = handler._format_repair_result(result)

        assert "konnte nicht ausgeführt werden" in text


class TestLogBackgroundTaskException:
    def test_cancelled_task_is_ignored(self, handler):
        task = Mock()
        task.cancelled.return_value = True

        handler._log_background_task_exception(task)  # darf nicht raisen
        task.exception.assert_not_called()

    def test_exception_is_logged(self, handler):
        task = Mock()
        task.cancelled.return_value = False
        task.exception.return_value = RuntimeError("boom")

        handler._log_background_task_exception(task)

        handler.logger.error.assert_called_once()

    def test_no_exception_is_noop(self, handler):
        task = Mock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        handler._log_background_task_exception(task)

        handler.logger.error.assert_not_called()


class TestShortIssueLabel:
    def test_short_description_is_returned_unchanged(self):
        assert _short_issue_label("Kein ISRC.") == "Kein ISRC."

    def test_cuts_at_em_dash(self):
        text = (
            "Genre-Wert liegt ausserhalb der Konvention — Tag-Hygiene, "
            "kein Qualitaetsdefekt (Genre zeigt sich im Player weiterhin)."
        )
        result = _short_issue_label(text)
        assert result == "Genre-Wert liegt ausserhalb der Konvention"

    def test_cuts_at_first_sentence(self):
        text = "Erster Satz ist die Kernaussage. Zweiter Satz ist nur Zusatzkontext."
        assert _short_issue_label(text) == "Erster Satz ist die Kernaussage"

    def test_hard_cap_truncates_at_word_boundary_with_ellipsis(self):
        text = "Wort " * 40  # weit ueber jedem sinnvollen max_len, kein Satzende
        result = _short_issue_label(text, max_len=20)
        assert result.endswith("…")
        assert len(result) <= 21
        assert not result[:-1].endswith(" ")
