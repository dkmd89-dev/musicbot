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
    def test_connection_error_and_timeout_error_categorized_as_network(self):
        """
        ARCH-029/F11 Regressionstest: ConnectionError/TimeoutError erben in
        Python von OSError. "file_system" listet OSError ebenfalls, "network"
        listet ConnectionError/TimeoutError explizit - vor dem Fix gewann
        "file_system" trotzdem immer (erster Dict-Treffer), weil die
        Dict-Reihenfolge ueber die Kategorie entschied statt der
        Exception-Spezifitaet (siehe ARCH-026 F11, vormals
        test_connection_error_is_miscategorized_as_file_system_not_network).
        categorize_exception() waehlt jetzt den spezifischsten Treffer
        (ConnectionError/TimeoutError sind spezifischer als ihr Vorfahre
        OSError) - unabhaengig von der Dict-Reihenfolge.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(ConnectionError()) == "network"
        assert monitor.categorize_exception(TimeoutError()) == "network"

    def test_bare_os_error_remains_categorized_as_file_system(self):
        """
        ARCH-029/F11: ein generischer OSError (keine spezifischere
        Netzwerk-Subklasse) bleibt weiterhin "file_system" - das war schon
        vor dem Fix so und aendert sich nicht, da OSError hier der einzige
        Treffer ist (kein spezifischerer Konkurrent).
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(OSError()) == "file_system"

    def test_file_specific_os_subclasses_remain_file_system(self):
        """
        ARCH-029/F11: FileNotFoundError/PermissionError/IsADirectoryError
        sind (auch) OSError-Subklassen, bleiben aber unveraendert
        "file_system" - IsADirectoryError ist nirgends explizit gelistet,
        wird also (korrekt) nur ueber OSError erreicht.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(FileNotFoundError()) == "file_system"
        assert monitor.categorize_exception(PermissionError()) == "file_system"
        assert monitor.categorize_exception(IsADirectoryError()) == "file_system"

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

    def test_permission_error_is_categorized_as_file_system_not_authentication(self):
        """
        FINDINGS_INDEX.md F11 Re-Evaluation (2026-09-14): PermissionError
        war sowohl in "file_system" als auch in "authentication" gelistet -
        "file_system" gewann schon vorher immer (kommt zuerst im Dict),
        "authentication" war dadurch fuer PermissionError (ihren einzigen
        Eintrag) faktisch unerreichbar und wurde komplett entfernt. Dieser
        Test pinnt das bereits vorher tatsaechliche Ergebnis - keine
        Verhaltensaenderung, nur Entfernung des toten Duplikats.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(PermissionError()) == "file_system"

    def test_authentication_category_no_longer_exists(self):
        monitor = ExceptionMonitor()
        assert "authentication" not in monitor.categories

    def test_index_error_remains_categorized_as_data(self):
        """
        F11 Re-Evaluation: "data" listete zusaetzlich ValueError/KeyError,
        die bereits von "parsing" (kommt zuerst) abgefangen wurden - beide
        entfernt, "data" bleibt fuer IndexError (den einzigen nicht
        anderweitig doppelt vergebenen Typ) unveraendert erreichbar.
        """
        monitor = ExceptionMonitor()
        assert monitor.categorize_exception(IndexError()) == "data"
        assert monitor.categorize_exception(KeyError()) == "parsing"

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


class TestDecoratorConfigAccessBugFix:
    """ARCH-027/F5: handle_async_exceptions()/handle_sync_exceptions()
    riefen bei einer abgefangenen Exception self.config.get(
    "SUPPRESS_HANDLED_EXCEPTIONS", False) auf - config.Config (und die
    hier verwendete FakeConfig, dieselbe reine Attribut-Klasse ohne
    .get()/__getattr__) hat keine .get()-Methode. Bei tatsaechlicher
    Verwendung des Decorators haette das den echten AttributeError
    geworfen und die urspruengliche Exception maskiert (ARCH-026/F5,
    ARCH-027 Abschnitt 9/11) - 0 produktive Verwendungen bisher, aber
    beide Decorators bleiben als dokumentierte, weiterhin unterstuetzte
    API bestehen (Verwendungsbeispiel 2 im Modul-Docstring). Fix:
    getattr(self.config, ...) statt .get(...). Diese Tests wuerden ohne
    den Fix mit AttributeError statt der erwarteten RuntimeError
    fehlschlagen (Pre-Fix-Diskriminierung ueber die urspruengliche
    self.config.get(...)-Zeile manuell nachvollzogen)."""

    @pytest.mark.asyncio
    async def test_async_decorator_reraises_original_exception_not_attributeerror(self):
        handler = EnhancedErrorHandler(FakeConfig())

        @handler.handle_async_exceptions("TestModule", "test_op")
        async def _boom():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await _boom()

    @pytest.mark.asyncio
    async def test_async_decorator_suppresses_when_configured(self):
        config = FakeConfig()
        config.SUPPRESS_HANDLED_EXCEPTIONS = True
        handler = EnhancedErrorHandler(config)

        @handler.handle_async_exceptions("TestModule", "test_op")
        async def _boom():
            raise RuntimeError("boom")

        result = await _boom()
        assert result is None

    def test_sync_decorator_reraises_original_exception_not_attributeerror(self):
        handler = EnhancedErrorHandler(FakeConfig())

        @handler.handle_sync_exceptions("TestModule", "test_op")
        def _boom():
            raise RuntimeError("boom")

        async def _run():
            with pytest.raises(RuntimeError, match="boom"):
                _boom()
            # Dem von handle_sync_exceptions() intern per
            # asyncio.create_task() geplanten handle_exception()-Aufruf
            # eine Iteration Zeit geben, damit er (inkl. des jetzt
            # gefixten getattr()-Zugriffs) tatsaechlich durchlaeuft.
            await asyncio.sleep(0)

        asyncio.run(_run())

    def test_sync_decorator_suppresses_when_configured(self):
        config = FakeConfig()
        config.SUPPRESS_HANDLED_EXCEPTIONS = True
        handler = EnhancedErrorHandler(config)

        @handler.handle_sync_exceptions("TestModule", "test_op")
        def _boom():
            raise RuntimeError("boom")

        result = _boom()
        assert result is None


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


class FakeConfig:
    # ARCH-023/P-5: OWNER_USER_ID bewusst ausserhalb von ADMIN_IDS/999
    # gewaehlt, damit TestIsAdmin unten weiterhin ausschliesslich die
    # ADMIN_USER_IDS-Mitgliedschaftslogik testet (nicht die neue
    # Owner-Sonderregel - die ist in
    # tests/test_menu_router_characterization.py::
    # TestErradminCharacterization dediziert abgedeckt).
    OWNER_USER_ID = 999999
    ADMIN_USER_IDS = ADMIN_IDS


@pytest.fixture
def admin_interface():
    fake_error_handler = Mock()
    return ErrorHandlerAdminInterface(fake_error_handler, ADMIN_IDS, FakeConfig())


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


class TestReplyOrEditDefaultParseModeHotfix2:
    """PARSE-MODE-AUDIT 2026-09-13, Hotfix 2: alle error_msg-Aufrufer
    (f"...: {e}") riefen _reply_or_edit() bisher OHNE explizites
    parse_mode auf und erbten damit den vorherigen Default "Markdown" -
    ein einzelnes "_"/"`"/"[" im rohen Exception-Text liess die
    Fehleranzeige selbst mit "Can't parse entities" abstuerzen. Default
    ist jetzt None (Plain-Text); Aufrufer mit explizitem
    parse_mode="Markdown" (statischer, kontrollierter Text) bleiben
    unveraendert."""

    def test_default_parse_mode_is_none_for_edit_message_text(self, admin_interface):
        update = make_update(111, has_callback_query=True, has_message=False)
        context = make_context()

        asyncio.run(
            admin_interface._reply_or_edit(update, context, "❌ Fehler: /pfad_mit_unterstrich")
        )

        _args, kwargs = update.callback_query.edit_message_text.call_args
        assert kwargs["parse_mode"] is None

    def test_default_parse_mode_is_none_for_reply_text(self, admin_interface):
        update = make_update(111, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(
            admin_interface._reply_or_edit(update, context, "❌ Fehler: /pfad_mit_unterstrich")
        )

        _args, kwargs = update.message.reply_text.call_args
        assert kwargs["parse_mode"] is None

    def test_explicit_parse_mode_still_honored(self, admin_interface):
        """Aufrufer mit statischem, kontrolliertem Text setzen parse_mode
        weiterhin explizit - das darf durch den neuen Default nicht
        beeinflusst werden."""
        update = make_update(111, has_callback_query=True, has_message=False)
        context = make_context()

        asyncio.run(
            admin_interface._reply_or_edit(
                update, context, "📊 **Text**", parse_mode="Markdown"
            )
        )

        _args, kwargs = update.callback_query.edit_message_text.call_args
        assert kwargs["parse_mode"] == "Markdown"


class TestHandleRecentErrorsCommandMessagePreviewEscaping:
    """PARSE-MODE-AUDIT 2026-09-13, Hotfix 2 (Zusatzfund): message_preview
    stammt aus echten Exception-Texten und wird trotz explizitem
    parse_mode="Markdown" ungeschuetzt eingebettet - derselbe unpaarige-
    Sonderzeichen-Absturz wie bei error_msg, hier aber im Erfolgspfad
    (nicht im Fallback), daher vom Default-parse_mode-Fix allein nicht
    abgedeckt."""

    def test_message_preview_with_underscore_is_escaped(self, admin_interface):
        admin_interface.error_handler.get_recent_exceptions_summary.return_value = [
            {
                "timestamp": "2026-09-13T12:00:00",
                "type": "OSError",
                "category": "filesystem",
                "message_preview": "/mnt/musik_bilder/library nicht gefunden",
            }
        ]
        update = make_update(111, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(admin_interface.handle_recent_errors_command(update, context))

        _args, kwargs = update.message.reply_text.call_args
        assert "musik\\_bilder" in kwargs["text"]
        assert kwargs["parse_mode"] == "Markdown"

    def test_no_recent_exceptions_shows_plain_message(self, admin_interface):
        admin_interface.error_handler.get_recent_exceptions_summary.return_value = []
        update = make_update(111, has_callback_query=False, has_message=True)
        context = make_context()

        asyncio.run(admin_interface.handle_recent_errors_command(update, context))

        message = update.message.reply_text.call_args[1]["text"]
        assert "Keine aktuellen Exceptions" in message


class TestDebugSessionLifecycle:
    """ARCH-029/F8: vorher rief jeder der 3 High-Level-Entry-Points
    (handle_telegram_error/handle_command_error/handle_callback_error) UND
    beide Decoratoren (handle_async_exceptions/handle_sync_exceptions)
    selbst debug_tracker.start_session() auf und uebergab dieselbe
    session_id an handle_exception(), das unbedingt selbst erneut
    start_session() aufrief (ueberschreibt) und in seinem finally-Block
    end_session() aufrief - bei den Decoratoren zusaetzlich ein zweites,
    harmloses (No-Op) end_session() im eigenen finally-Block (ARCH-026 F8).
    Fix: handle_exception() erhielt manage_session (Default True, siehe
    Docstring dort) - die 3 Entry-Points haben keinen eigenen
    start_session()-Vorlauf mehr (handle_exception() ist alleiniger
    Besitzer), die 2 Decoratoren uebergeben manage_session=False (sie
    besitzen die Session bereits selbst, auch fuer ihren Erfolgspfad)."""

    @staticmethod
    def _count_session_calls(handler):
        tracker = handler.debug_tracker
        start_spy = Mock(wraps=tracker.start_session)
        end_spy = Mock(wraps=tracker.end_session)
        tracker.start_session = start_spy
        tracker.end_session = end_spy
        return start_spy, end_spy

    @pytest.mark.asyncio
    async def test_handle_exception_direct_call_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        await handler.handle_exception(RuntimeError("boom"), context={"module": "x"})

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_telegram_error_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        update = make_update(111)
        context = make_context()
        context.error = RuntimeError("tg-boom")

        await handler.handle_telegram_error(update, context)

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_command_error_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        update = make_update(111)
        context = make_context()

        await handler.handle_command_error(
            update, context, "mycommand", RuntimeError("cmd-boom")
        )

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_callback_error_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        update = make_update(111)
        context = make_context()

        await handler.handle_callback_error(
            update, context, "nav_test_callback", RuntimeError("cb-boom")
        )

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_async_decorator_exception_path_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        @handler.handle_async_exceptions("TestModule", "test_op")
        async def _boom():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await _boom()

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_async_decorator_success_path_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        @handler.handle_async_exceptions("TestModule", "test_op")
        async def _ok():
            return "done"

        result = await _ok()

        assert result == "done"
        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    def test_sync_decorator_exception_path_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        @handler.handle_sync_exceptions("TestModule", "test_op")
        def _boom():
            raise RuntimeError("boom")

        async def _run():
            with pytest.raises(RuntimeError):
                _boom()
            # Dem per asyncio.create_task() geplanten handle_exception()
            # genug Event-Loop-Zyklen geben, um vollstaendig durchzulaufen
            # (mehrere interne awaits, siehe ARCH-029/F8-Kommentar am
            # add_done_callback() in handle_sync_exceptions()) - ein
            # einzelnes asyncio.sleep(0) reicht dafuer nicht zuverlaessig.
            await asyncio.sleep(0.05)

        asyncio.run(_run())

        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    def test_sync_decorator_success_path_has_single_start_and_end(self):
        handler = EnhancedErrorHandler(FakeConfig())
        start_spy, end_spy = self._count_session_calls(handler)

        @handler.handle_sync_exceptions("TestModule", "test_op")
        def _ok():
            return "done"

        result = _ok()

        assert result == "done"
        assert start_spy.call_count == 1
        assert end_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_session_id_consistent_across_lifecycle(self):
        handler = EnhancedErrorHandler(FakeConfig())
        seen_ids = []
        original_start = handler.debug_tracker.start_session
        original_end = handler.debug_tracker.end_session

        def spy_start(session_id, ctx):
            seen_ids.append(("start", session_id))
            return original_start(session_id, ctx)

        def spy_end(session_id, status="completed"):
            seen_ids.append(("end", session_id))
            return original_end(session_id, status)

        handler.debug_tracker.start_session = spy_start
        handler.debug_tracker.end_session = spy_end

        await handler.handle_exception(RuntimeError("boom"), context={"module": "x"})

        assert len(seen_ids) == 2
        assert seen_ids[0][1] == seen_ids[1][1]

    @pytest.mark.asyncio
    async def test_callback_error_debug_context_preserved_in_session(self):
        """ARCH-029/F8: der entry-point-spezifische Kontext (hier
        callback_data) landet jetzt direkt im DebugTracker-Session-Objekt,
        statt beim ueberschreibenden zweiten start_session() verloren zu
        gehen (ARCH-026 F8: 'der ursspruengliche, entry-point-spezifische
        Kontext ... geht damit fuer die DebugTracker-Session verloren')."""
        handler = EnhancedErrorHandler(FakeConfig())
        captured = {}
        original_end = handler.debug_tracker.end_session

        def spy_end(session_id, status="completed"):
            captured["context"] = handler.debug_tracker.sessions[session_id][
                "context"
            ]
            return original_end(session_id, status)

        handler.debug_tracker.end_session = spy_end

        update = make_update(111)
        context = make_context()

        await handler.handle_callback_error(
            update, context, "nav_test_callback", RuntimeError("cb-boom")
        )

        assert captured["context"].get("callback_data") == "nav_test_callback"

    @pytest.mark.asyncio
    async def test_async_decorator_debug_context_preserved_across_exception(self):
        """ARCH-029/F8: die vom Decorator selbst beim Funktionsstart
        gesetzte Session (function/module/operation) bleibt erhalten, weil
        handle_exception() bei manage_session=False keine neue Session
        anlegt, die sie ueberschreiben wuerde."""
        handler = EnhancedErrorHandler(FakeConfig())

        @handler.handle_async_exceptions("TestModule", "test_op")
        async def _boom():
            raise RuntimeError("boom")

        captured_sessions = []
        original_end = handler.debug_tracker.end_session

        def spy_end(session_id, status="completed"):
            captured_sessions.append(
                dict(handler.debug_tracker.sessions[session_id]["context"])
            )
            return original_end(session_id, status)

        handler.debug_tracker.end_session = spy_end

        with pytest.raises(RuntimeError):
            await _boom()

        assert len(captured_sessions) == 1
        assert captured_sessions[0].get("module") == "TestModule"
        assert captured_sessions[0].get("operation") == "test_op"


class TestHandleErrorRemoved:
    """ARCH-029/F9: handle_error() war ein Kompatibilitaets-Wrapper mit 0
    Aufrufern ausserhalb der eigenen Definition (ARCH-026 F9, repoweit
    inkl. Tests/Docs/Reflection erneut bestaetigt) - ersatzlos entfernt.
    Die spezialisierten Entry-Points (handle_telegram_error/
    handle_command_error/handle_callback_error/handle_exception) bleiben
    unveraendert die einzigen Einstiegspunkte."""

    def test_handle_error_no_longer_exists(self):
        handler = EnhancedErrorHandler(FakeConfig())
        assert not hasattr(handler, "handle_error")


class TestExportDebugSessionRemoved:
    """ARCH-029/F10: export_debug_session() hatte 0 externe Aufrufer
    (ARCH-026 F10, repoweit erneut bestaetigt) - ersatzlos entfernt, ohne
    neue Ersatz-API. DebugTracker bleibt interner Mechanismus von
    EnhancedErrorHandler (ARCH-027 Abschnitt 10) und funktioniert dafuer
    unveraendert weiter."""

    def test_export_debug_session_no_longer_exists(self):
        handler = EnhancedErrorHandler(FakeConfig())
        assert not hasattr(handler, "export_debug_session")

    def test_debug_tracker_still_functions_internally(self):
        handler = EnhancedErrorHandler(FakeConfig())
        assert isinstance(handler.debug_tracker, DebugTracker)

        handler.debug_tracker.start_session("s1", {"foo": "bar"})
        handler.debug_tracker.log_step("s1", "step")
        handler.debug_tracker.end_session("s1")

        summary = handler.debug_tracker.get_session_summary("s1")
        assert summary is not None
        assert summary["status"] == "completed"


class TestProductionLoggingPIIMinimization:
    """ARCH-029/F12: _log_exception_details() loggte User-Klarname/
    -Username sowie den vollen Nachrichtentext-Preview unbedingt ueber
    den Standard-Logger, unabhaengig von debug_mode (ARCH-026 F12). Fix:
    Production (debug_mode=False) loggt nur user_id/message_id: Debug
    (debug_mode=True) bleibt unveraendert vollstaendig. callback_data
    bleibt in beiden Modi sichtbar (bot-interne ID, fuer Diagnose
    essenziell, keine PII)."""

    @staticmethod
    def _make_handler(debug_mode: bool):
        class LocalFakeConfig:
            DEBUG_MODE = debug_mode
            LOG_ALL_EXCEPTIONS = True
            DETAILED_STACK_TRACES = True
            MAX_RECOVERY_ATTEMPTS = 3

        handler = EnhancedErrorHandler(LocalFakeConfig())
        logged_lines = []
        handler.logger = Mock()
        handler.logger.error = lambda msg="": logged_lines.append(str(msg))
        handler.logger.info = lambda msg="": logged_lines.append(str(msg))
        handler.logger.warning = lambda msg="": logged_lines.append(str(msg))
        handler.logger.critical = lambda msg="": logged_lines.append(str(msg))
        return handler, logged_lines

    @staticmethod
    def _make_full_context(handler):
        exception = RuntimeError("boom")
        update = make_update(111)
        update.effective_user.first_name = "Robin"
        update.effective_user.username = "robin_m"
        update.effective_user.language_code = "de"
        update.message.text = "ein privater Nachrichtentext"
        update.callback_query.data = "nav_test_callback"
        return exception, handler._build_full_context(exception, {}, update)

    @pytest.mark.asyncio
    async def test_production_mode_omits_first_name_and_username(self):
        handler, logged_lines = self._make_handler(debug_mode=False)
        exception, full_context = self._make_full_context(handler)

        await handler._log_exception_details(exception, full_context, "EXC_1", "sess-1")

        full_log = "\n".join(logged_lines)
        assert "Robin" not in full_log
        assert "robin_m" not in full_log
        assert f"User-ID: {111}" in full_log

    @pytest.mark.asyncio
    async def test_production_mode_omits_message_text_preview(self):
        handler, logged_lines = self._make_handler(debug_mode=False)
        exception, full_context = self._make_full_context(handler)

        await handler._log_exception_details(exception, full_context, "EXC_1", "sess-1")

        full_log = "\n".join(logged_lines)
        assert "ein privater Nachrichtentext" not in full_log

    @pytest.mark.asyncio
    async def test_production_mode_keeps_callback_data(self):
        handler, logged_lines = self._make_handler(debug_mode=False)
        exception, full_context = self._make_full_context(handler)

        await handler._log_exception_details(exception, full_context, "EXC_1", "sess-1")

        full_log = "\n".join(logged_lines)
        assert "nav_test_callback" in full_log

    @pytest.mark.asyncio
    async def test_debug_mode_keeps_full_context(self):
        handler, logged_lines = self._make_handler(debug_mode=True)
        exception, full_context = self._make_full_context(handler)

        await handler._log_exception_details(exception, full_context, "EXC_1", "sess-1")

        full_log = "\n".join(logged_lines)
        assert "Robin" in full_log
        assert "robin_m" in full_log
        assert "ein privater Nachrichtentext" in full_log
        assert "nav_test_callback" in full_log

    @pytest.mark.asyncio
    async def test_debug_mode_still_shows_exception_type_and_category(self):
        """Abschnitt 8 des Master-Prompts: keine uebertriebene Redaction -
        die fuer die Fehlerdiagnose noetigen technischen Angaben bleiben in
        BEIDEN Modi erhalten."""
        for debug_mode in (True, False):
            handler, logged_lines = self._make_handler(debug_mode=debug_mode)
            exception, full_context = self._make_full_context(handler)

            await handler._log_exception_details(
                exception, full_context, "EXC_1", "sess-1"
            )

            full_log = "\n".join(logged_lines)
            assert "RuntimeError" in full_log
            assert "runtime" in full_log
