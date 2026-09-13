"""
Characterization-Tests fuer handlers/enhanced_status_handler.py
(EnhancedStatusHandler, vorher 0 Tests).

STATUS-MENU-CLOSURE (siehe docs/MusicBot_STATUS_MENU_CLOSURE.md):
von 19 im Status-Menue (dieses File) als Buttons gerenderten
"status_*"-callback_data-Werten sind in
handlers/menu/actions/admin_diagnostics.py::handle_status_callback()s
routing_map weiterhin nur 7 tatsaechlich verdrahtet:

  Verdrahtet:  status_menu, status_system, status_bot, status_services,
               status_performance, status_storage, status_refresh
  Platzhalter: status_bot_handlers, status_bot_logs,
               status_performance_history, status_performance_reset,
               status_services_check, status_services_detail,
               status_storage_cleanup, status_storage_detail,
               status_system_detail, status_system_history,
               status_trends, status_users

Repoweit verifiziert: fuer keinen der 12 Platzhalter-Callbacks existiert
irgendwo eine Handler-Implementierung (weder unter diesem noch einem
anderen Methodennamen) - echte Kategorie C (Button ohne Handler), nicht
nur "nicht geroutet". Bewusst nicht blind verdrahtet (kein Feature-Bau in
dieser Phase). Seit dem Closure-Fix werden sie in
handle_status_callback() explizit als bekannter Platzhalter erkannt
(freundliche "🚧 noch nicht implementiert"-Rueckmeldung, kein
WARNING-Log wie bei einem echten unerwarteten callback_data-Wert) - siehe
tests/test_menu_actions_admin_diagnostics.py fuer die Routing-Tests.

Zwei reale Telegram-Markdown-Parse-Bugs gefunden und gefixt (Live-Fund):
platform.machine() ("x86_64") in show_system_status() und
Config.LIBRARY_DIR ("/mnt/musik_bilder/library") in show_storage_status()
enthalten je einen unpaarigen Unterstrich, der Telegrams Legacy-
"Markdown"-Parser mit "Can't parse entities" ablehnen liess. Fix: neue
Modul-Funktion _escape_markdown() fuer alle dynamischen Werte, die in
Markdown-Text eingebettet werden (siehe TestEscapeMarkdown unten).

Zusaetzlich: "Message is not modified" (Telegram-Idempotenzfall bei
identischem Refresh) wurde bisher wie ein echter Fehler behandelt (Log +
teils zusaetzliche, verwirrende Fehleranzeige) - jetzt per
_is_message_not_modified_error() als No-op erkannt, siehe
TestMessageNotModifiedHandling unten.
"""

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram.error import BadRequest

from handlers.enhanced_status_handler import (
    BotStatusTracker,
    EnhancedStatusHandler,
    SystemMonitor,
    _escape_markdown,
    _is_message_not_modified_error,
)


class FakeConfig:
    BASE_DIR = Path("/tmp")
    LIBRARY_DIR = Path("/tmp/nonexistent_library")
    DOWNLOAD_DIR = Path("/tmp/nonexistent_downloads")
    DATA_DIR = Path("/tmp/nonexistent_data")
    LOG_DIR = Path("/tmp/nonexistent_logs")
    VERSION = "2.0"


class TestSystemMonitor:
    def test_get_system_metrics_returns_expected_top_level_keys(self):
        monitor = SystemMonitor(FakeConfig())
        metrics = monitor.get_system_metrics()

        assert set(metrics.keys()) >= {"cpu", "memory", "disk", "network", "process"}

    def test_get_uptime_formats_correctly(self):
        monitor = SystemMonitor(FakeConfig())
        uptime = monitor.get_uptime()

        assert uptime["days"] == 0
        assert "formatted" in uptime
        assert uptime["total_seconds"] >= 0

    def test_record_operation_increments_counter(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_operation("download")
        monitor.record_operation("download")
        monitor.record_operation("search")

        stats = monitor.get_performance_stats()
        assert stats["operation_breakdown"]["download"] == 2
        assert stats["operation_breakdown"]["search"] == 1
        assert stats["total_operations"] == 3

    def test_record_error_increments_counter(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_error("timeout")

        stats = monitor.get_performance_stats()
        assert stats["total_errors"] == 1
        assert stats["error_rate"] == 100.0  # 1 error / 1 total_operations(0->max(0,1)=1)

    def test_reset_statistics_clears_counters(self):
        monitor = SystemMonitor(FakeConfig())
        monitor.record_operation("download")
        monitor.record_error("timeout")

        monitor.reset_statistics()

        stats = monitor.get_performance_stats()
        assert stats["total_operations"] == 0
        assert stats["total_errors"] == 0


class TestBotStatusTracker:
    def test_update_handler_status_stores_status(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_handler_status("download_handler", "active")

        overview = tracker.get_handler_overview()
        assert overview["total_handlers"] == 1
        assert overview["active_handlers"] == 1
        assert overview["handlers"]["download_handler"]["status"] == "active"

    def test_update_service_status_only_for_known_services(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_service_status("navidrome", "healthy")
        tracker.update_service_status("totally_unknown_service", "healthy")

        overview = tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "healthy"
        assert "totally_unknown_service" not in overview["services"]
        assert overview["healthy_services"] == 1

    def test_record_user_activity_tracks_unique_active_users(self):
        tracker = BotStatusTracker(FakeConfig())
        tracker.record_user_activity(111, "download")
        tracker.record_user_activity(111, "search")
        tracker.record_user_activity(222, "download")

        activity = tracker.get_user_activity()
        assert activity["active_users"] == 2
        assert activity["total_recorded_activities"] == 3

    def test_user_activity_history_respects_recent_20_limit(self):
        tracker = BotStatusTracker(FakeConfig())
        for i in range(25):
            tracker.record_user_activity(i, "download")

        activity = tracker.get_user_activity()
        assert len(activity["recent_activities"]) == 20
        assert activity["total_recorded_activities"] == 25


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestShowStorageStatus:
    def test_missing_directory_is_reported_not_found(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Nicht gefunden" in text

    def test_existing_directory_reports_size(self, tmp_path):
        class ConfigWithRealDir(FakeConfig):
            LIBRARY_DIR = tmp_path

        (tmp_path / "song.mp3").write_bytes(b"x" * 1024)

        handler = EnhancedStatusHandler(ConfigWithRealDir())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "GB" in text


class TestUnroutedStatusButtonsAreDocumented:
    """
    Statischer Abgleich: extrahiert alle in enhanced_status_handler.py
    gerenderten "status_*"-callback_data-Werte und vergleicht sie gegen
    die tatsaechlich in handle_status_callback()s routing_map verdrahtete
    Liste - schuetzt davor, dass sich die Diskrepanz unbemerkt vergroessert
    oder (bei zukuenftiger Verdrahtung) diese Charakterisierung veraltet,
    ohne dass es auffaellt.

    STATUS-MENU-CLOSURE: "unrouted" heisst seit dem Closure-Fix konkret
    "nicht in routing_map, sondern im expliziten
    _PLACEHOLDER_STATUS_CALLBACKS-Platzhalter-Pfad" - nicht mehr "faellt
    unbemerkt auf den generischen Unbekannt-Zweig zurueck". Die
    Callback-Menge selbst ist unveraendert (keine neuen Handler
    implementiert, keine Buttons entfernt).
    """

    ROUTED_STATUS_CALLBACKS = {
        "status_menu",
        "status_system",
        "status_bot",
        "status_services",
        "status_performance",
        "status_storage",
        "status_refresh",
    }

    PLACEHOLDER_STATUS_CALLBACKS = {
        "status_bot_handlers",
        "status_bot_logs",
        "status_performance_history",
        "status_performance_reset",
        "status_services_check",
        "status_services_detail",
        "status_storage_cleanup",
        "status_storage_detail",
        "status_system_detail",
        "status_system_history",
        "status_trends",
        "status_users",
    }

    def test_known_placeholder_buttons_are_still_not_in_routing_map(self):
        # ARCH-024/P-2: die routing_map lebt in
        # handlers/menu/actions/admin_diagnostics.py::handle_status_callback().
        source = Path("handlers/menu/actions/admin_diagnostics.py").read_text(encoding="utf-8")
        # Groben Ausschnitt der routing_map in handle_status_callback holen
        start = source.index("async def handle_status_callback")
        end = source.index("async def handle_status_menu")
        section = source[start:end]

        rendered = set(
            re.findall(r'callback_data="(status_[a-z_]+)"',
                       Path("handlers/enhanced_status_handler.py").read_text(encoding="utf-8"))
        )
        routed = set(re.findall(r'"(status_[a-z_]+)":', section))

        assert routed == self.ROUTED_STATUS_CALLBACKS
        unrouted = rendered - routed
        # Die Menge der nicht in routing_map verdrahteten Buttons ist
        # exakt die bekannte Platzhalter-Menge - kein neu aufgetauchter,
        # tatsaechlich unbekannter Button.
        assert unrouted == self.PLACEHOLDER_STATUS_CALLBACKS


class TestEscapeMarkdown:
    """
    _escape_markdown(): Legacy-Telegram-"Markdown"-Escaping (NICHT
    MarkdownV2) fuer dynamische Werte - siehe Modul-Docstring von
    handlers/enhanced_status_handler.py fuer die Begruendung, warum
    helfer/markdown_helfer.py::escape_md_v2() hier NICHT passt (andere
    Zeichenmenge, wuerde z.B. Punkte in Versionsnummern escapen).
    """

    def test_plain_text_without_special_chars_is_unchanged(self):
        assert _escape_markdown("Linux") == "Linux"
        assert _escape_markdown("3.12.3") == "3.12.3"

    def test_underscore_is_escaped(self):
        # Der reale Live-Bug: platform.machine() == "x86_64"
        assert _escape_markdown("x86_64") == "x86\\_64"

    def test_path_with_underscores_is_escaped(self):
        # Der reale Live-Bug: Config.LIBRARY_DIR == "/mnt/musik_bilder/library"
        assert _escape_markdown("/mnt/musik_bilder/library") == "/mnt/musik\\_bilder/library"

    def test_path_with_underscores_generic_example(self):
        assert (
            _escape_markdown("/mnt/test/path_with_underscores/")
            == "/mnt/test/path\\_with\\_underscores/"
        )

    def test_value_with_leading_underscore_style_name(self):
        assert _escape_markdown("Linux_6.x") == "Linux\\_6.x"
        assert _escape_markdown("value_with_underscores") == "value\\_with\\_underscores"

    def test_asterisk_is_escaped(self):
        assert _escape_markdown("foo*bar") == "foo\\*bar"

    def test_backtick_is_escaped(self):
        assert _escape_markdown("foo`bar") == "foo\\`bar"

    def test_opening_bracket_is_escaped(self):
        assert _escape_markdown("foo[bar") == "foo\\[bar"

    def test_hyphen_and_parentheses_are_not_touched(self):
        # Legacy-Markdown (im Gegensatz zu MarkdownV2) kennt weder "-"
        # noch "(", ")" als reservierte Zeichen - kein unnoetiges Escaping.
        assert _escape_markdown("foo-bar") == "foo-bar"
        assert _escape_markdown("foo(bar)") == "foo(bar)"

    def test_non_string_value_is_converted_first(self):
        assert _escape_markdown(2.0) == "2.0"
        assert _escape_markdown(42) == "42"

    def test_empty_string_is_unchanged(self):
        assert _escape_markdown("") == ""


class TestIsMessageNotModifiedError:
    """_is_message_not_modified_error(): erkennt ausschliesslich
    Telegrams Idempotenzfall, keine anderen Telegram-/generischen
    Exceptions (Phase 6: "keine globale Unterdrueckung aller
    Telegram-Fehler")."""

    def test_recognizes_message_is_not_modified(self):
        exc = BadRequest("Message is not modified")
        assert _is_message_not_modified_error(exc) is True

    def test_recognizes_case_insensitively(self):
        exc = BadRequest("MESSAGE IS NOT MODIFIED: specific diff")
        assert _is_message_not_modified_error(exc) is True

    def test_other_bad_request_is_not_treated_as_no_op(self):
        exc = BadRequest("Query is too old and response timeout expired")
        assert _is_message_not_modified_error(exc) is False

    def test_non_telegram_exception_is_not_treated_as_no_op(self):
        assert _is_message_not_modified_error(RuntimeError("Message is not modified")) is False


class TestShowSystemStatusMarkdownSafety:
    """Regressionstest fuer den realen Live-Bug: 'Can't parse entities:
    can't find end of the entity starting at byte offset 108' -
    platform.machine() == 'x86_64' enthaelt einen unpaarigen Unterstrich."""

    def test_architecture_with_underscore_does_not_break_rendering(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch("handlers.enhanced_status_handler.platform.machine", return_value="x86_64"):
            asyncio.run(handler.show_system_status(update, context))

        # darf nicht ueber _show_error_message() gelaufen sein (kein Crash)
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "x86\\_64" in text
        assert "x86_64" not in text  # nur escaped, nicht roh

    def test_release_with_underscore_does_not_break_rendering(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.platform.release",
            return_value="6.8.0_custom_build",
        ):
            asyncio.run(handler.show_system_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "6.8.0\\_custom\\_build" in text


class TestShowStorageStatusMarkdownSafety:
    """Regressionstest fuer den realen Live-Bug: 'Can't parse entities:
    can't find end of the entity starting at byte offset 67' -
    Config.LIBRARY_DIR ('/mnt/musik_bilder/library') enthaelt einen
    unpaarigen Unterstrich."""

    def test_library_path_with_underscore_does_not_break_rendering(self, tmp_path):
        class ConfigWithUnderscorePath(FakeConfig):
            LIBRARY_DIR = tmp_path / "musik_bilder" / "library"

        ConfigWithUnderscorePath.LIBRARY_DIR.mkdir(parents=True)
        (ConfigWithUnderscorePath.LIBRARY_DIR / "song.mp3").write_bytes(b"x" * 1024)

        handler = EnhancedStatusHandler(ConfigWithUnderscorePath())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "musik\\_bilder" in text
        assert "musik_bilder" not in text

    def test_realistic_problematic_path_characters_are_all_escaped(self, tmp_path):
        # Master-Prompt-Beispiele: alle in einem einzigen Pfad kombiniert.
        tricky_dir = tmp_path / "foo-bar(x)_test[case]"
        tricky_dir.mkdir()
        (tricky_dir / "f.mp3").write_bytes(b"x")

        class ConfigWithTrickyPath(FakeConfig):
            LIBRARY_DIR = tricky_dir

        handler = EnhancedStatusHandler(ConfigWithTrickyPath())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        # Muss gerendert worden sein (kein Absturz/Fehleranzeige statt Report)
        assert "GB" in text
        # Sonderzeichen aus _MARKDOWN_V1_SPECIAL_CHARS muessen escaped sein
        assert "\\_test" in text
        assert "\\[case" in text
        # Telegram Legacy-Markdown kennt laut offizieller Doku nur
        # _ * ` [ als reservierte Zeichen - NICHT "]" (das schliessende
        # "]" allein loest ohne vorangehendes unescaped "[" keinen
        # Link-Parse-Versuch aus). "-" und "(...)" sind ebenfalls
        # unkritisch. Alle drei bleiben bewusst roh/unescaped.
        assert "case]" in text
        assert "foo-bar(x)" in text


class TestMessageNotModifiedHandling:
    """Phase 6: ein identischer Refresh (edit_message_text() mit exakt
    demselben Inhalt) darf nicht als echter Fehler erscheinen - kein
    Error-Log-Pfad ueber _show_error_message(), kein Crash. Andere
    Telegram-/generische Exceptions bleiben unveraendert sichtbar."""

    def test_show_system_status_swallows_message_not_modified(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        context = make_context()

        asyncio.run(handler.show_system_status(update, context))  # darf nicht raisen

        # Kein zweiter edit_message_text()-Aufruf ueber _show_error_message()
        assert update.callback_query.edit_message_text.call_count == 1

    def test_show_storage_status_swallows_message_not_modified(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        context = make_context()

        asyncio.run(handler.show_storage_status(update, context))

        assert update.callback_query.edit_message_text.call_count == 1

    def test_show_performance_status_swallows_message_not_modified(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        context = make_context()

        asyncio.run(handler.show_performance_status(update, context))

        assert update.callback_query.edit_message_text.call_count == 1

    def test_show_status_menu_swallows_message_not_modified_without_error_handler(self):
        handler = EnhancedStatusHandler(FakeConfig())
        assert handler.error_handler is None
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        context = make_context()

        asyncio.run(handler.show_status_menu(update, context))  # darf nicht raisen

        assert update.callback_query.edit_message_text.call_count == 1

    def test_show_status_menu_does_not_call_error_handler_for_message_not_modified(self):
        handler = EnhancedStatusHandler(FakeConfig())
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        context = make_context()

        asyncio.run(handler.show_status_menu(update, context))

        handler.error_handler.handle_callback_error.assert_not_awaited()

    def test_other_telegram_error_still_shows_error_message(self):
        """Regression: Phase 6 verlangt explizit, dass ANDERE
        Telegram-Exceptions weiterhin normal (sichtbar) behandelt werden -
        keine globale Unterdrueckung."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=[BadRequest("Query is too old"), None]
        )
        context = make_context()

        asyncio.run(handler.show_system_status(update, context))

        # 1. Aufruf wirft, 2. Aufruf ist der _show_error_message()-Fallback
        assert update.callback_query.edit_message_text.call_count == 2
        error_text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Fehler" in error_text

    def test_other_generic_exception_still_shows_error_message(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.platform.machine",
            side_effect=RuntimeError("boom"),
        ):
            asyncio.run(handler.show_system_status(update, context))

        error_text = update.callback_query.edit_message_text.call_args.args[0]
        assert "Fehler" in error_text
        assert "boom" in error_text
