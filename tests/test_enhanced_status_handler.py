"""
Characterization-Tests fuer handlers/enhanced_status_handler.py
(EnhancedStatusHandler).

STATUS-MENU-CLOSURE — MASTER-PHASE "Complete Telegram System Status Menu"
(siehe docs/MusicBot_STATUS_MENU_CLOSURE.md fuer die vollstaendige
Fall-A/B/C/D-Entscheidung je Callback):

Vorherige Phase hatte 12 Buttons ohne Handler-Implementierung als
"bekannten Platzhalter" behandelt (freundliche Meldung statt
WARNING-Log). Diese Phase hat fuer jeden der 12 tatsaechlich vorhandene
Datenquellen im Projekt gesucht (Fall A/B) und - wo eine echte,
nicht-spekulative Implementierung moeglich war - eine kleine, lokale
Status-Funktion ergaenzt:

  IMPLEMENTED (11): status_users (BotStatusTracker.get_user_activity()),
    status_trends + status_system_history (SystemMonitor cpu_history/
    memory_history/disk_history), status_system_detail (psutil
    loadavg/swap/per-core), status_bot_handlers
    (BotStatusTracker.get_handler_overview()), status_bot_logs
    (get_logging_stats(), inkl. Fix des strukturellen "Gesamt-Logs: 0"-
    Bugs aus der Vorphase), status_services_check (echter, read-only
    NavidromeAPI.check_connection()-Ping), status_services_detail
    (Check-Verfuegbarkeits-Transparenz), status_performance_reset
    (nutzt die bereits vorhandene SystemMonitor.reset_statistics()),
    status_storage_detail (psutil disk_partitions()/disk_usage()).
  REMOVED (1): status_performance_history - keine ueber
    Resets/Neustarts hinweg gespeicherte Performance-Historie
    existiert, eine "Verlauf"-Ansicht haette zwangslaeufig Fake-Daten
    gezeigt. Button komplett aus dem UI entfernt (siehe
    show_performance_status()s Keyboard).
  UNAVAILABLE_BY_DESIGN (1): status_storage_cleanup - explizit
    verbotene destruktive Aktion ohne definierten Cleanup-Contract,
    bleibt der einzige verbleibende Platzhalter.

Damit sind ALLE 18 verbleibenden "status_*"-Callbacks (19 minus das
entfernte status_performance_history) vollstaendig charakterisiert -
keiner ist mehr "unbekannt"/"orphaned"/"unerreichbar".

Aus der Vorphase weiterhin gueltig: zwei reale Telegram-Markdown-Parse-
Bugs (platform.machine()="x86_64", Config.LIBRARY_DIR mit Unterstrich)
gefixt via _escape_markdown() (siehe TestEscapeMarkdown), sowie
"Message is not modified" als No-op erkannt via
_is_message_not_modified_error() (siehe TestMessageNotModifiedHandling).
Alle NEUEN dynamischen Werte in dieser Phase (Handler-/Modulnamen,
Mountpoints, Dateisystemtypen) werden ebenfalls konsequent escaped.
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
    _find_partition_for_path,
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

    def test_get_extended_system_info_returns_expected_keys(self):
        """STATUS-MENU-CLOSURE (status_system_detail): neue Methode,
        reine psutil-Zusatzwerte, keine neue Datenquelle."""
        monitor = SystemMonitor(FakeConfig())
        info = monitor.get_extended_system_info()

        assert "load_average" in info
        assert "swap" in info
        assert {"total", "used", "percent"} <= set(info["swap"].keys())
        assert isinstance(info["cpu_per_core"], list)
        assert len(info["cpu_per_core"]) >= 1
        assert info["boot_time"] is not None

    def test_get_history_summary_returns_zeroed_defaults_without_measurements(self):
        """STATUS-MENU-CLOSURE (status_trends): ohne vorherige
        get_system_metrics()-Aufrufe sind die History-Deques leer -
        keine Fake-Werte, saubere 0.0-Defaults."""
        monitor = SystemMonitor(FakeConfig())
        summary = monitor.get_history_summary()

        assert summary["sample_count"] == 0
        for metric in ("cpu", "memory", "disk"):
            assert summary[metric] == {
                "current": 0.0, "average": 0.0, "min": 0.0, "max": 0.0,
            }

    def test_get_history_summary_reflects_real_recorded_measurements(self):
        """Verifiziert echte Aggregation (nicht nur Struktur) - füttert
        die History-Deque direkt (dieselbe, die get_system_metrics()
        befüllt) und prüft min/avg/max/current."""
        monitor = SystemMonitor(FakeConfig())
        monitor.cpu_history.extend([10.0, 20.0, 30.0])

        summary = monitor.get_history_summary()

        assert summary["cpu"]["current"] == 30.0
        assert summary["cpu"]["average"] == 20.0
        assert summary["cpu"]["min"] == 10.0
        assert summary["cpu"]["max"] == 30.0
        assert summary["sample_count"] == 3


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

    def test_update_service_status_stores_optional_reason(self):
        """STATUS-MENU-CLOSURE Final Correction: der optionale `reason`-
        Parameter erklaert ehrlich, warum ein Service z. B. "unknown"
        bleibt (kein automatisierter Health-Check verfuegbar)."""
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_service_status(
            "download", "unknown", reason="Kein automatisierter Health-Check verfügbar"
        )

        overview = tracker.get_service_overview()
        assert (
            overview["services"]["download"]["reason"]
            == "Kein automatisierter Health-Check verfügbar"
        )

    def test_update_service_status_without_reason_defaults_to_none(self):
        """Ein Aufruf ohne `reason` darf keinen veralteten Grund aus einem
        frueheren, unabhaengigen Aufruf uebernehmen - jeder Aufruf setzt
        den Service-Eintrag vollstaendig neu."""
        tracker = BotStatusTracker(FakeConfig())
        tracker.update_service_status("navidrome", "unknown", reason="alter Grund")
        tracker.update_service_status("navidrome", "healthy")

        overview = tracker.get_service_overview()
        assert overview["services"]["navidrome"]["reason"] is None

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
    Liste - schuetzt davor, dass sich eine Diskrepanz unbemerkt vergroessert
    oder diese Charakterisierung veraltet, ohne dass es auffaellt.

    STATUS-MENU-CLOSURE (Master-Phase): 11 der zuvor 12 Platzhalter sind
    jetzt in der routing_map verdrahtet (echte Implementierungen, siehe
    Modul-Docstring oben). Nur noch "status_storage_cleanup" bleibt
    Platzhalter (UNAVAILABLE_BY_DESIGN). "status_performance_history"
    wurde komplett aus dem UI entfernt (REMOVED) - taucht daher weder in
    "rendered" noch in einer der beiden Mengen unten auf.
    """

    ROUTED_STATUS_CALLBACKS = {
        "status_menu",
        "status_system",
        "status_bot",
        "status_services",
        "status_performance",
        "status_storage",
        "status_refresh",
        "status_users",
        "status_trends",
        "status_system_detail",
        "status_system_history",
        "status_bot_handlers",
        "status_bot_logs",
        "status_services_check",
        "status_services_detail",
        "status_performance_reset",
        "status_storage_detail",
    }

    PLACEHOLDER_STATUS_CALLBACKS = {
        "status_storage_cleanup",
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

    def test_status_performance_history_button_was_removed_entirely(self):
        """STATUS-MENU-CLOSURE: keine Fake-History - der Button wurde
        komplett aus dem UI entfernt, nicht nur umklassifiziert."""
        rendered = set(
            re.findall(
                r'callback_data="(status_[a-z_]+)"',
                Path("handlers/enhanced_status_handler.py").read_text(encoding="utf-8"),
            )
        )
        assert "status_performance_history" not in rendered
        assert len(rendered) == 18  # 19 urspruenglich - 1 entfernt


class TestFindPartitionForPath:
    """_find_partition_for_path() (status_storage_detail): laengster
    passender Mountpoint-Praefix, reine psutil-Abfrage."""

    def test_root_path_resolves_to_a_partition(self):
        partition = _find_partition_for_path(Path("/"))
        assert partition is not None
        assert partition.mountpoint == "/"

    def test_nonexistent_path_still_resolves_via_prefix_matching(self):
        # .resolve() funktioniert auch fuer nicht existierende Pfade -
        # der Mountpoint wird ueber den laengsten passenden Praefix
        # gefunden, unabhaengig davon, ob der Pfad selbst existiert.
        partition = _find_partition_for_path(Path("/this/does/not/exist/at/all"))
        assert partition is not None


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


# =============================================================================
# STATUS-MENU-CLOSURE (Master-Phase): Tests fuer die 10 neu implementierten
# Views (status_users, status_trends, status_system_detail/_history,
# status_bot_handlers/_logs, status_services_check/_detail,
# status_performance_reset, status_storage_detail).
# =============================================================================


class TestShowUsersStatus:
    def test_shows_aggregate_counts_only(self):
        handler = EnhancedStatusHandler(FakeConfig())
        handler.bot_tracker.record_user_activity(111, "download")
        handler.bot_tracker.record_user_activity(222, "search")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_users_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "2" in text  # active_users

    def test_does_not_leak_user_ids_or_chat_ids(self):
        """Phase 7: keine PII - User-IDs duerfen nicht im gerenderten
        Text auftauchen."""
        handler = EnhancedStatusHandler(FakeConfig())
        handler.bot_tracker.record_user_activity(123456789, "download")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_users_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "123456789" not in text


class TestShowTrends:
    def test_shows_min_avg_max_current_from_real_history(self):
        handler = EnhancedStatusHandler(FakeConfig())
        handler.system_monitor.cpu_history.extend([10.0, 50.0])
        handler.system_monitor.memory_history.extend([20.0])
        handler.system_monitor.disk_history.extend([30.0])
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_trends(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "CPU" in text and "RAM" in text and "Disk" in text

    def test_no_measurements_does_not_crash(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_trends(update, context))  # darf nicht raisen

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "0.0%" in text


class TestShowSystemDetail:
    def test_renders_load_swap_and_per_core_cpu(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_system_detail(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Load Average" in text
        assert "Swap" in text
        assert "Kern 0" in text

    def test_missing_loadavg_shown_gracefully(self):
        """Manche Plattformen (u.a. Windows) haben kein getloadavg() -
        AttributeError/OSError darf nicht crashen."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch("psutil.getloadavg", side_effect=OSError("not supported")):
            asyncio.run(handler.show_system_detail(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht verfügbar" in text


class TestShowSystemHistory:
    def test_shows_recent_samples_as_sequence(self):
        handler = EnhancedStatusHandler(FakeConfig())
        handler.system_monitor.cpu_history.extend([10.0, 20.0, 30.0])
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_system_history(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "10%" in text and "20%" in text and "30%" in text

    def test_no_measurements_shows_placeholder_not_crash(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_system_history(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        # STATUS-MENU-CLOSURE Final Correction: case-insensitiv geprueft -
        # der korrigierte, explizite Platzhaltertext beginnt satzinitial
        # mit Grossbuchstaben ("Noch keine Messungen seit Bot-Start."),
        # waehrend die alte, jetzt entfernte pro-Metrik-Kurzform
        # klein geschrieben war ("(noch keine Messungen)"). Die eigentliche
        # Pruefsemantik (Platzhalter statt Crash/Fake-Werte) bleibt
        # unveraendert - siehe auch
        # test_no_measurements_shows_explicit_empty_placeholder_text unten
        # fuer die exakte Textpruefung.
        assert "noch keine messungen" in text.lower()

    def test_no_measurements_shows_explicit_empty_placeholder_text(self):
        """STATUS-MENU-CLOSURE Final Correction: bei komplett leerer
        Historie wird der explizite Platzhaltertext gezeigt (nicht nur
        die pro-Metrik-Kurzform), analog zur Vorgabe im Master-Fix."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_system_history(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Noch keine Messungen seit Bot-Start." in text

    def test_viewing_history_creates_no_new_measurement(self):
        """STATUS-MENU-CLOSURE Final Correction: show_system_history()
        ist eine reine HISTORY VIEW und darf keine neue SAMPLING-Messung
        erzeugen (Root Cause des zuvor fehlschlagenden Tests: die alte
        Implementierung rief get_system_metrics() auf, das als
        Seiteneffekt cpu_history/memory_history/disk_history befuellt)."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        assert len(handler.system_monitor.cpu_history) == 0
        assert len(handler.system_monitor.memory_history) == 0
        assert len(handler.system_monitor.disk_history) == 0

        asyncio.run(handler.show_system_history(update, context))

        assert len(handler.system_monitor.cpu_history) == 0
        assert len(handler.system_monitor.memory_history) == 0
        assert len(handler.system_monitor.disk_history) == 0

    def test_viewing_existing_history_does_not_change_entry_count(self):
        """Anzahl der History-Eintraege bleibt beim reinen Anzeigen
        unveraendert - auch wenn bereits Messungen vorhanden sind."""
        handler = EnhancedStatusHandler(FakeConfig())
        handler.system_monitor.cpu_history.extend([10.0, 20.0, 30.0])
        handler.system_monitor.memory_history.extend([40.0, 50.0])
        handler.system_monitor.disk_history.extend([60.0])
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_system_history(update, context))

        assert len(handler.system_monitor.cpu_history) == 3
        assert len(handler.system_monitor.memory_history) == 2
        assert len(handler.system_monitor.disk_history) == 1


class TestShowBotStatus:
    """show_bot_status() selbst hatte bisher 0 Tests - insbesondere der
    'Gesamt-Logs: 0'-Bug (Deferred Finding der Vorphase) war dadurch
    unentdeckt. Gemockter get_logging_stats() fuer Determinismus
    (dieselbe Begruendung wie TestShowBotLogs)."""

    def test_total_logs_now_correctly_aggregated_across_modules(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 2,
            "modules": {
                "ModuleA": {"total_logs": 7},
                "ModuleB": {"total_logs": 3},
            },
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Gesamt-Logs: 10" in text  # 7 + 3, nicht mehr strukturell 0


class TestShowBotHandlers:
    def test_shows_real_handler_statuses(self):
        """STATUS-MENU-CLOSURE: reale, ueber
        BotStatusTracker.update_handler_status() aufgezeichnete Daten -
        keine erfundene Liste."""
        handler = EnhancedStatusHandler(FakeConfig())
        handler.bot_tracker.update_handler_status("error_handler", "active")
        handler.bot_tracker.update_handler_status("navidrome_handler", "error")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_bot_handlers(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Gesamt:** 2" in text
        assert "Aktiv:** 1" in text

    def test_handler_names_with_underscores_are_escaped(self):
        """Regression: 'error_handler'/'navidrome_handler' etc. enthalten
        Unterstriche - genau das Live-Bug-Muster aus der Vorphase
        (x86_64/musik_bilder), hier fuer echte Handler-Namen."""
        handler = EnhancedStatusHandler(FakeConfig())
        handler.bot_tracker.update_handler_status("error_handler", "active")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_bot_handlers(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "error\\_handler" in text
        assert "error_handler" not in text

    def test_no_handlers_recorded_shows_placeholder(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_bot_handlers(update, context))  # darf nicht raisen

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Noch keine Handler-Status" in text


class TestShowBotLogs:
    """
    Nutzt einen gemockten get_logging_stats()-Rueckgabewert statt des
    echten, prozessweit geteilten _module_loggers-Zustands - der ist
    ueber die gesamte Testsuite hinweg gemeinsam genutzt (jeder Test, der
    irgendwo get_module_logger() aufruft, traegt dazu bei) und wuerde
    "Top 5 nach Fehlern"-Assertions unzuverlaessig machen, wenn andere
    Tests zufaellig mehr Fehler auf anderen Modulen erzeugt haben.
    """

    def test_shows_aggregated_total_logs_not_zero(self):
        """Regressionstest fuer den in der Vorphase dokumentierten
        Deferred Finding: 'Gesamt-Logs' zeigte strukturell immer 0."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 1,
            "modules": {"TestModule": {"total_logs": 5, "error_count": 1, "critical_count": 0}},
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_logs(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Gesamt-Logs:** 0" not in text
        assert "Gesamt-Logs:** 5" in text

    def test_module_names_with_underscores_are_escaped(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 1,
            "modules": {
                "Test_Module_With_Underscores": {
                    "total_logs": 3, "error_count": 3, "critical_count": 0,
                }
            },
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_logs(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Test\\_Module\\_With\\_Underscores" in text
        assert "Test_Module_With_Underscores" not in text

    def test_never_shows_raw_log_message_content(self):
        """Master-Prompt Phase 5: keine vollstaendigen Logfiles/Secrets -
        nur Zaehler, niemals der eigentliche Lognachrichtentext. Da
        get_logging_stats() strukturell ohnehin nur Zaehlwerte liefert
        (siehe logger.py::ModuleLogger.get_stats()), ist ein Leak hier
        architektonisch ausgeschlossen - dieser Test dokumentiert das."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 1,
            "modules": {"SecretModule": {"total_logs": 1, "error_count": 1, "critical_count": 0}},
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_logs(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "supersecret123" not in text
        assert "password" not in text

    def test_top_modules_sorted_by_error_count_descending(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 2,
            "modules": {
                "QuietModule": {"total_logs": 10, "error_count": 0, "critical_count": 0},
                "NoisyModule": {"total_logs": 10, "error_count": 5, "critical_count": 1},
            },
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_logs(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "NoisyModule" in text
        # QuietModule hat 0 Fehler - wird gemaess Filter nicht gelistet.
        assert "QuietModule" not in text

    def test_no_module_errors_shows_placeholder(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()
        fake_stats = {
            "total_modules": 1,
            "modules": {"CleanModule": {"total_logs": 10, "error_count": 0, "critical_count": 0}},
        }

        with patch(
            "handlers.enhanced_status_handler.get_logging_stats",
            return_value=fake_stats,
        ):
            asyncio.run(handler.show_bot_logs(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Fehler" in text


class TestShowServicesCheck:
    def test_updates_navidrome_status_to_healthy_on_successful_ping(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        overview = handler.bot_tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "healthy"

    def test_updates_navidrome_status_to_error_on_failed_ping(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=False
            )
            asyncio.run(handler.show_services_check(update, context))

        overview = handler.bot_tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "error"

    def test_connection_exception_is_handled_not_raised(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                side_effect=RuntimeError("network down")
            )
            asyncio.run(handler.show_services_check(update, context))  # darf nicht raisen

        overview = handler.bot_tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "error"

    def test_other_services_remain_honestly_unknown_not_faked_healthy(self):
        """Kein Fake-Daten-Verstoss: download/statistics/logger haben
        keinen automatisierten Check - duerfen NICHT pauschal auf
        'healthy' gesetzt werden."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        overview = handler.bot_tracker.get_service_overview()
        for name in ("download", "statistics", "logger"):
            assert overview["services"][name]["status"] == "unknown"

    def test_renders_services_view_after_check(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        update.callback_query.edit_message_text.assert_awaited()

    def test_non_navidrome_services_get_explicit_unknown_reason(self):
        """STATUS-MENU-CLOSURE Final Correction: download/statistics/
        logger bleiben nicht nur ehrlich 'unknown', sondern erhalten
        einen konkreten, nachvollziehbaren Grund (keine erfundene
        Health-Aussage, aber auch kein unbegruendetes 'unknown')."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        overview = handler.bot_tracker.get_service_overview()
        for name in ("download", "statistics", "logger"):
            assert overview["services"][name]["reason"] == (
                "Kein automatisierter Health-Check verfügbar"
            )
        # Navidrome hat einen echten Check - kein "kein Check verfuegbar"-Grund.
        assert overview["services"]["navidrome"]["reason"] is None

    def test_all_four_services_are_considered_during_check(self):
        """Alle vier bekannten Services muessen beim Check tatsaechlich
        verarbeitet werden (last_check wird fuer jeden gesetzt) - keiner
        wird stillschweigend ausgelassen."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        overview = handler.bot_tracker.get_service_overview()
        for name in ("download", "navidrome", "statistics", "logger"):
            assert overview["services"][name]["last_check"] is not None

    def test_error_in_one_service_does_not_block_the_others(self):
        """Fehlerisolation: ein Fehler bei genau einem Service (hier:
        'statistics') darf die Verarbeitung der uebrigen drei Services
        nicht verhindern - der gesamte Button darf nicht wegen eines
        einzelnen Checks abbrechen."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        original_update = handler.bot_tracker.update_service_status

        def flaky_update(service_name, status, reason=None):
            if service_name == "statistics":
                raise RuntimeError("Statistics-Check fehlgeschlagen")
            original_update(service_name, status, reason=reason)

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls, patch.object(
            handler.bot_tracker, "update_service_status", side_effect=flaky_update
        ):
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))  # darf nicht raisen

        overview = handler.bot_tracker.get_service_overview()
        assert overview["services"]["navidrome"]["status"] == "healthy"
        assert overview["services"]["download"]["status"] == "unknown"
        assert overview["services"]["logger"]["status"] == "unknown"
        # "statistics" bleibt beim urspruenglichen Zustand (Fehler beim
        # Setzen), aber der Button ist insgesamt nicht abgebrochen.
        update.callback_query.edit_message_text.assert_awaited()

    def test_rendered_view_shows_reason_for_unknown_services(self):
        """Nach dem Check zeigt die gerenderte Ansicht (show_services_status())
        den Grund fuer die Services ohne echten Check an."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        # Der Grund-Text enthaelt keine Legacy-Markdown-Sonderzeichen
        # (_ * ` [), wird also unveraendert von _escape_markdown() zurueckgegeben.
        assert "Kein automatisierter Health-Check verfügbar" in text
        assert text.count("Grund: Kein automatisierter Health-Check verfügbar") == 3

    def test_check_result_contains_no_pii_or_secrets(self):
        """Kein Nutzer-/Token-/Passwort-Leck ueber den Service-Check-Text."""
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler.NavidromeAPI"
        ) as mock_navidrome_cls:
            mock_navidrome_cls.return_value.check_connection = AsyncMock(
                return_value=True
            )
            asyncio.run(handler.show_services_check(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        for forbidden in ("password", "token", "api_key", "Authorization"):
            assert forbidden.lower() not in text.lower()


class TestShowServicesDetail:
    def test_shows_check_availability_per_service(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_services_detail(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "automatisierter Check verfügbar" in text  # Navidrome
        assert "kein automatisierter Check definiert" in text  # die anderen 3


class TestShowPerformanceReset:
    def test_resets_operation_and_error_counters(self):
        handler = EnhancedStatusHandler(FakeConfig())
        handler.system_monitor.record_operation("status_menu")
        handler.system_monitor.record_error("timeout")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_performance_reset(update, context))

        stats = handler.system_monitor.get_performance_stats()
        assert stats["total_operations"] == 0
        assert stats["total_errors"] == 0

    def test_renders_performance_view_after_reset(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_performance_reset(update, context))

        update.callback_query.edit_message_text.assert_awaited()

    def test_no_confirmation_step_required_matches_admin_gated_low_stakes_design(self):
        """Dokumentiert die bewusste Entscheidung: kein separater
        Confirm-Callback (siehe Docstring von show_performance_reset()) -
        ein einzelner Tap fuehrt den Reset direkt aus."""
        handler = EnhancedStatusHandler(FakeConfig())
        handler.system_monitor.record_operation("x")
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_performance_reset(update, context))

        assert handler.system_monitor.get_performance_stats()["total_operations"] == 0


class TestShowStorageDetail:
    def test_shows_mountpoint_and_filesystem_for_root(self):
        class ConfigWithRootLibrary(FakeConfig):
            LIBRARY_DIR = Path("/")

        handler = EnhancedStatusHandler(ConfigWithRootLibrary())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_detail(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Mountpoint" in text
        assert "Dateisystem" in text
        assert "GB" in text

    def test_path_with_underscores_is_escaped(self, tmp_path):
        class ConfigWithUnderscorePath(FakeConfig):
            LIBRARY_DIR = tmp_path / "musik_bilder"

        ConfigWithUnderscorePath.LIBRARY_DIR.mkdir()
        handler = EnhancedStatusHandler(ConfigWithUnderscorePath())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_storage_detail(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "musik\\_bilder" in text

    def test_unresolvable_mountpoint_does_not_crash(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        with patch(
            "handlers.enhanced_status_handler._find_partition_for_path",
            return_value=None,
        ):
            asyncio.run(handler.show_storage_detail(update, context))  # darf nicht raisen

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "konnte nicht ermittelt werden" in text


class TestShowPerformanceStatusHistoryButtonRemoved:
    def test_keyboard_no_longer_offers_history_button(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_performance_status(update, context))

        keyboard = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        callback_datas = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        }
        assert "status_performance_history" not in callback_datas
        assert "status_performance_reset" in callback_datas

    def test_empty_operation_breakdown_shows_placeholder_not_nothing(self):
        handler = EnhancedStatusHandler(FakeConfig())
        update = make_update()
        context = make_context()

        asyncio.run(handler.show_performance_status(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Noch keine aufgezeichneten Operationen" in text
