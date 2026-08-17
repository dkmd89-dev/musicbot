"""
Characterization-Tests fuer handlers/enhanced_error_handler.py - mit 2508
Zeilen die groesste Datei im gesamten handlers/-Verzeichnis, vorher 0 Tests.

Zwei reale Bugs beim Lesen gefunden und gefixt:

BUG-005a: EnhancedErrorHandler hatte ZWEI __init__-Definitionen im
Klassenkoerper. Python ueberschreibt bei doppelten Methodennamen
stillschweigend mit der LETZTEN Definition - die erste (unvollstaendig,
Koerper nur "...") wurde daher nie ausgefuehrt, war aber totes
Code-Fragment ohne jede Funktion. Entfernt. Keine Verhaltensaenderung
(die zweite, vollstaendige __init__ war schon vorher die einzig wirksame),
daher kein klassischer git-stash-Regressionsbeweis moeglich - stattdessen
ein Test, der belegt, dass die Instanz korrekt und vollstaendig
initialisiert wird (recovery_strategies, error_messages etc. vorhanden).

BUG-005b (der eigentliche Laufzeit-Bug): ErrorHandlerAdminInterface.
_reply_or_edit() rief im dritten Fallback-Zweig (kein callback_query,
kein update.message, aber update.effective_chat vorhanden)
"context.bot.send_message(...)" auf - "context" war aber gar kein
Parameter der Methode. Dieser Zweig haette bei tatsaechlichem Erreichen
einen NameError geworfen statt die Nachricht zu senden. Fix: context als
Parameter ergaenzt, alle 15 Aufrufstellen angepasst.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.enhanced_error_handler import (
    DebugTracker,
    EnhancedErrorHandler,
    ErrorHandlerAdminInterface,
    ExceptionMonitor,
)


class FakeConfig:
    DEBUG_MODE = True
    LOG_ALL_EXCEPTIONS = True
    DETAILED_STACK_TRACES = True
    MAX_RECOVERY_ATTEMPTS = 3


class TestEnhancedErrorHandlerSingleInit:
    """Regressionstest fuer BUG-005a: nur eine (vollstaendige) __init__."""

    def test_constructing_handler_yields_fully_initialized_instance(self):
        handler = EnhancedErrorHandler(FakeConfig())

        assert handler.config is not None
        assert isinstance(handler.exception_monitor, ExceptionMonitor)
        assert isinstance(handler.debug_tracker, DebugTracker)
        assert handler.recovery_strategies  # von _register_recovery_strategies()
        assert "generic" in handler.error_messages
        assert handler.performance_stats["total_handled"] == 0

    def test_no_duplicate_init_in_class_body(self):
        """
        Statischer Beweis gegen ein erneutes versehentliches Wiedereinfuegen
        eines zweiten __init__: das kompilierte AST der Klasse darf nur
        genau ein FunctionDef mit Namen "__init__" enthalten.
        """
        import ast
        import inspect

        source = inspect.getsource(EnhancedErrorHandler)
        tree = ast.parse(source)
        class_node = tree.body[0]
        init_defs = [
            n
            for n in class_node.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ]
        assert len(init_defs) == 1


class TestExceptionMonitor:
    def test_connection_error_is_miscategorized_as_file_system_not_network(self):
        """
        Charakterisiert einen beim Schreiben dieser Tests gefundenen
        Kategorisierungs-Fehler: ConnectionError/TimeoutError erben in
        Python von OSError. "file_system" listet OSError ebenfalls und
        steht im categories-Dict VOR "network" - dadurch gewinnt
        "file_system" fuer JEDEN ConnectionError/TimeoutError, "network"
        ist fuer diese beiden (die einzigen zwei explizit als
        netzwerkbezogen gedachten Eintraege dort) faktisch unerreichbar.
        Reine Statistik-/Diagnose-Verzerrung (keine Auswirkung auf
        Kernfunktionen), bewusst nur dokumentiert statt gefixt - eine
        Umsortierung wuerde weitere Ueberschneidungen beruehren, die nicht
        Teil dieser Charakterisierung waren.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(ConnectionError()) == "file_system"
        assert monitor.categorize_exception(TimeoutError()) == "file_system"

    def test_categorizes_unknown_exception_type(self):
        class WeirdCustomException(Exception):
            pass

        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(WeirdCustomException()) == "unknown"

    def test_first_matching_category_wins_for_overlapping_types(self):
        """
        Charakterisiert bestehendes Verhalten: ValueError ist sowohl in
        "parsing" als auch in "data" gelistet. Da "parsing" im
        categories-Dict zuerst kommt, gewinnt IMMER "parsing" - "data" ist
        fuer ValueError faktisch unerreichbar (nur IndexError bleibt
        eindeutig "data"). Reine Dict-Reihenfolge-Semantik, kein Bug.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(ValueError()) == "parsing"
        assert monitor.categorize_exception(IndexError()) == "data"

    def test_determine_severity_critical_for_memory_error(self):
        monitor = ExceptionMonitor()
        assert monitor.determine_severity(MemoryError(), {}) == "critical"

    def test_determine_severity_warning_for_value_error(self):
        monitor = ExceptionMonitor()
        assert monitor.determine_severity(ValueError(), {}) == "warning"

    def test_determine_severity_defaults_to_error(self):
        class SomeOtherException(Exception):
            pass

        monitor = ExceptionMonitor()
        assert monitor.determine_severity(SomeOtherException(), {}) == "error"

    def test_record_exception_updates_statistics(self):
        monitor = ExceptionMonitor()
        exc_id = monitor.record_exception(ValueError("boom"), {"module": "test_mod"})

        assert exc_id.startswith("EXC_")
        stats = monitor.get_statistics()
        assert stats["total_exceptions"] == 1
        assert stats["by_category"]["parsing"] == 1
        assert stats["by_module"]["test_mod"] == 1

    def test_get_recent_exceptions_returns_latest_first_order(self):
        monitor = ExceptionMonitor()
        monitor.record_exception(ValueError("first"), {})
        monitor.record_exception(KeyError("second"), {})

        recent = monitor.get_recent_exceptions(count=10)
        assert len(recent) == 2
        assert recent[-1]["message"] == "'second'"

    def test_history_respects_max_history_limit(self):
        monitor = ExceptionMonitor(max_history=3)
        for i in range(5):
            monitor.record_exception(ValueError(f"err{i}"), {})

        assert len(monitor.exception_history) == 3
        # Aelteste wurden verdraengt, die letzten 3 bleiben
        remaining_messages = [r["message"] for r in monitor.exception_history]
        assert remaining_messages == ["err2", "err3", "err4"]


class TestDebugTracker:
    def test_start_session_creates_active_session(self):
        tracker = DebugTracker()
        tracker.start_session("sess-1", {"user": "test"})

        summary = tracker.get_session_summary("sess-1")
        assert summary is not None
        assert summary["status"] in ("active", "completed")

    def test_log_step_appends_to_session(self):
        tracker = DebugTracker()
        tracker.start_session("sess-1", {})
        tracker.log_step("sess-1", "step1", {"detail": "x"})

        summary = tracker.get_session_summary("sess-1")
        assert summary["step_count"] >= 1

    def test_end_session_marks_completed(self):
        tracker = DebugTracker()
        tracker.start_session("sess-1", {})
        tracker.end_session("sess-1", status="completed")

        summary = tracker.get_session_summary("sess-1")
        assert summary["status"] == "completed"

    def test_get_session_summary_for_unknown_session_returns_none(self):
        tracker = DebugTracker()
        assert tracker.get_session_summary("does-not-exist") is None


def make_update(user_id, has_callback_query=True, has_message=True, has_chat=True):
    update = Mock()
    update.effective_user.id = user_id

    if has_callback_query:
        update.callback_query = Mock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    else:
        update.callback_query = None

    if has_message:
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    else:
        update.message = None

    if has_chat:
        update.effective_chat = Mock()
        update.effective_chat.id = 999
    else:
        update.effective_chat = None

    return update


def make_context():
    context = Mock()
    context.bot = AsyncMock()
    context.args = []
    return context


ADMIN_IDS = [111, 222]


@pytest.fixture
def admin_interface():
    fake_error_handler = Mock()
    return ErrorHandlerAdminInterface(fake_error_handler, ADMIN_IDS)


class TestIsAdmin:
    def test_configured_admin_is_recognized(self, admin_interface):
        assert admin_interface.is_admin(111) is True

    def test_non_admin_is_rejected(self, admin_interface):
        assert admin_interface.is_admin(999) is False


class TestReplyOrEditBug005Regression:
    def test_uses_edit_message_text_when_callback_query_present(self, admin_interface):
        update = make_update(111, has_callback_query=True)
        context = make_context()

        asyncio.run(admin_interface._reply_or_edit(update, context, "hello"))

        update.callback_query.edit_message_text.assert_called_once()

    def test_uses_reply_text_when_only_message_present(self, admin_interface):
        update = make_update(111, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(admin_interface._reply_or_edit(update, context, "hello"))

        update.message.reply_text.assert_called_once()

    def test_falls_back_to_context_bot_send_message_without_crashing(
        self, admin_interface
    ):
        """
        Direkter Regressionsbeweis fuer BUG-005b: weder callback_query noch
        message vorhanden, nur effective_chat - vorher fehlte "context" als
        Parameter, dieser Zweig warf NameError statt zu senden.
        """
        update = make_update(111, has_callback_query=False, has_message=False, has_chat=True)
        context = make_context()

        asyncio.run(admin_interface._reply_or_edit(update, context, "hello"))

        context.bot.send_message.assert_called_once()
        _args, kwargs = context.bot.send_message.call_args
        assert kwargs["chat_id"] == 999
        assert kwargs["text"] == "hello"


class TestHandleErrorStatsCommandPermission:
    def test_non_admin_is_rejected(self, admin_interface):
        update = make_update(999, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(admin_interface.handle_error_stats_command(update, context))

        message = update.message.reply_text.call_args[1]["text"]
        assert "Berechtigung" in message

    def test_admin_gets_statistics(self, admin_interface):
        admin_interface.error_handler.get_comprehensive_statistics.return_value = {
            "exception_monitor": {"total_exceptions": 5, "by_category": {"network": 5}},
            "performance": {"avg_processing_time": 0.1, "recovery_success_rate": 0.5},
            "debug_tracker": {"active_sessions": 0},
        }
        update = make_update(111, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(admin_interface.handle_error_stats_command(update, context))

        message = update.message.reply_text.call_args[1]["text"]
        assert "STATISTIKEN" in message
