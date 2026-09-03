"""
Unit-Tests für TestMenuHandler (handlers/test_menu_handler.py)
— vorher 0 Tests, live in RichMenuHandler verdrahtet
(rich_menu_handler.py:192/393-398, Callbacks "test_unit"/"test_integration"/
"test_performance"), gefunden über die systematische Ungetestet-Prüfung.

Async-Testmethoden nutzen bewusst `asyncio.run()` statt `@pytest.mark.asyncio`
(etabliertes Muster, siehe tests/test_enhanced_metadata_processor_aclose.py) -
pytest-asyncio ist in dieser Umgebung nicht installiert.

BUG-013: run_unit_tests() rief _execute_test_run(update, "integration", ...)
auf - jetzt auf "unit" korrigiert. Der "Unit-Tests"-Button im Telegram-
Admin-Menü führte in Wirklichkeit die Integration-Test-Suite aus (falsches
Verzeichnis, falsche pytest-Flags: -x statt --cov). Live per Codelesen
verifiziert.

BUG-014: _parse_pytest_output()s FAILED-Zeilen-Parsing nutzte
`stripped_line.split("FAILED")[0]` - das ist der Text VOR "FAILED", der bei
Zeilen wie "FAILED tests/test_x.py::test_y - AssertionError" immer ein
Leerstring ist (die Zeile beginnt mit "FAILED"). `results["failed_tests"]`
enthielt dadurch ausschliesslich Leerstrings statt der tatsaechlichen
Test-Bezeichner. Live verifiziert: `"FAILED tests/test_foo.py::test_bar - X".split("FAILED")[0].strip()`
liefert `''`. Fix: `split("FAILED", 1)[1]` (Text NACH "FAILED").

HINWEIS: tests/unit/, tests/integration/, tests/performance/ existieren im
Repo nicht (die echte Test-Suite liegt flach unter tests/*.py) - das gesamte
Feature meldet aktuell fuer ALLE drei Test-Typen "Keine Tests gefunden",
unabhaengig von BUG-013. Das ist ein separates, groesseres Architektur-Thema
(Testverzeichnis-Struktur vs. tatsaechliche Ablage) und wird hier bewusst
nur dokumentiert, nicht behoben (kein spekulativer Grossumbau ohne
Nutzerentscheidung, siehe Regel 18).
"""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, Mock

from handlers.test_menu_handler import TestMenuHandler


def run_async(coro):
    return asyncio.run(coro)


class FakeConfig:
    def __init__(self, base_dir):
        self.BASE_DIR = str(base_dir)


def make_handler(tmp_path, create_dirs=None):
    """Erstellt einen TestMenuHandler mit tmp_path als project_root.

    create_dirs: Liste von ("unit"|"integration"|"performance", [Dateinamen])
    zum Anlegen echter Test-Verzeichnisse mit test_*.py-Dateien.
    """
    config = FakeConfig(tmp_path)
    handler = TestMenuHandler(config, logger_factory=lambda name: Mock())

    if create_dirs:
        for subdir, filenames in create_dirs:
            d = tmp_path / "tests" / subdir
            d.mkdir(parents=True, exist_ok=True)
            for fn in filenames:
                (d / fn).write_text("def test_x(): pass\n")

    return handler


def make_update(user_id=123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query.edit_message_text = AsyncMock()
    return update


# ─────────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────────


class TestInit:
    def test_paths_derived_from_base_dir(self, tmp_path):
        handler = make_handler(tmp_path)
        assert handler.project_root == tmp_path
        assert handler.tests_dir == tmp_path / "tests"
        assert handler.unit_tests_dir == tmp_path / "tests" / "unit"
        assert handler.test_results_cache == {}
        assert handler.running_tests == {}

    def test_falls_back_to_current_dir_without_base_dir(self):
        class ConfigWithoutBaseDir:
            pass

        handler = TestMenuHandler(
            ConfigWithoutBaseDir(), logger_factory=lambda name: Mock()
        )
        assert str(handler.project_root) == "."


# ─────────────────────────────────────────────────────────────────────────
# BUG-013 Regression: run_unit_tests() muss "unit" durchreichen
# ─────────────────────────────────────────────────────────────────────────


class TestBug013RunUnitTestsTypeRegression:
    def test_run_unit_tests_calls_execute_with_unit_type(self, tmp_path):
        handler = make_handler(tmp_path)
        handler._execute_test_run = AsyncMock()
        update = make_update()
        context = Mock()

        run_async(handler.run_unit_tests(update, context=context))

        handler._execute_test_run.assert_awaited_once_with(
            update, "unit", timeout=600, context=context
        )

    def test_run_integration_tests_calls_execute_with_integration_type(self, tmp_path):
        handler = make_handler(tmp_path)
        handler._execute_test_run = AsyncMock()
        update = make_update()
        context = Mock()

        run_async(handler.run_integration_tests(update, context=context))

        handler._execute_test_run.assert_awaited_once_with(
            update, "integration", timeout=600, context=context
        )

    def test_run_performance_tests_calls_execute_with_performance_type(self, tmp_path):
        handler = make_handler(tmp_path)
        handler._execute_test_run = AsyncMock()
        update = make_update()
        context = Mock()

        run_async(handler.run_performance_tests(update, context=context))

        handler._execute_test_run.assert_awaited_once_with(
            update, "performance", timeout=900, context=context
        )


# ─────────────────────────────────────────────────────────────────────────
# _execute_test_run
# ─────────────────────────────────────────────────────────────────────────


class TestExecuteTestRun:
    def test_already_running_shows_busy_message(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update(user_id=42)
        handler.running_tests[42] = "unit"

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "laufen bereits" in msg
        # Lock bleibt unveraendert (kein Ueberschreiben eines laufenden Locks)
        assert handler.running_tests[42] == "unit"

    def test_missing_test_dir_reports_no_tests_found(self, tmp_path):
        handler = make_handler(tmp_path)  # kein tests/unit/ angelegt
        update = make_update()

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        last_msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Unit-Tests gefunden" in last_msg
        # Lock wird trotz frühem Return korrekt wieder freigegeben
        assert update.effective_user.id not in handler.running_tests

    def test_happy_path_runs_subprocess_and_shows_results(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        fake_result = Mock(
            stdout="=========== 3 passed in 1.23s ===========",
            stderr="",
            returncode=0,
        )
        mock_run = Mock(return_value=fake_result)
        monkeypatch.setattr(subprocess, "run", mock_run)

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        assert "unit" in handler.test_results_cache
        assert handler.test_results_cache["unit"]["passed"] == 3
        assert handler.test_results_cache["unit"]["returncode"] == 0
        # Lock wieder freigegeben
        assert update.effective_user.id not in handler.running_tests

    def test_timeout_shows_timeout_message(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=600)

        monkeypatch.setattr(subprocess, "run", raise_timeout)

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        last_msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Zeitlimit" in last_msg
        assert update.effective_user.id not in handler.running_tests

    def test_unexpected_exception_shows_error_message(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        monkeypatch.setattr(subprocess, "run", Mock(side_effect=RuntimeError("boom")))

        run_async(handler._execute_test_run(update, "unit", timeout=600))

        last_msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Fehler bei der Ausführung" in last_msg
        assert update.effective_user.id not in handler.running_tests


# ─────────────────────────────────────────────────────────────────────────
# _parse_pytest_output (inkl. BUG-014-Regression)
# ─────────────────────────────────────────────────────────────────────────


class TestParsePytestOutput:
    def test_simple_passed_summary(self, tmp_path):
        handler = make_handler(tmp_path)
        stdout = "=========================== 5 passed in 1.23s ============================"
        result = handler._parse_pytest_output(stdout, "")
        assert result["passed"] == 5
        assert result["total"] == 5

    def test_mixed_passed_failed_summary(self, tmp_path):
        handler = make_handler(tmp_path)
        stdout = "=========== 3 failed, 2 passed in 1.23s ==========="
        result = handler._parse_pytest_output(stdout, "")
        assert result["failed"] == 3
        assert result["passed"] == 2
        assert result["total"] == 5

    def test_coverage_total_line(self, tmp_path):
        handler = make_handler(tmp_path)
        stdout = "TOTAL                      120     15    88%"
        result = handler._parse_pytest_output(stdout, "")
        assert result["coverage"] == 88

    def test_bug014_failed_test_name_extraction_regression(self, tmp_path):
        handler = make_handler(tmp_path)
        stdout = "FAILED tests/test_foo.py::test_bar - AssertionError: assert 1 == 2"
        result = handler._parse_pytest_output(stdout, "")
        # Vor dem Fix: '' (Text VOR "FAILED", immer leer). Nach dem Fix: der
        # tatsaechliche Test-Bezeichner NACH "FAILED".
        assert result["failed_tests"] == [
            "tests/test_foo.py::test_bar - AssertionError: assert 1 == 2"
        ]

    def test_parse_exception_is_swallowed_returns_defaults(self, tmp_path):
        handler = make_handler(tmp_path)
        # stdout=None bricht beim .split() -> AttributeError, wird intern gefangen
        result = handler._parse_pytest_output(None, "")
        assert result["total"] == 0
        assert result["passed"] == 0


# ─────────────────────────────────────────────────────────────────────────
# _show_test_results
# ─────────────────────────────────────────────────────────────────────────


class TestShowTestResults:
    def test_success_shows_checkmark(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()
        results = {
            "passed": 5,
            "failed": 0,
            "total": 5,
            "skipped": 0,
            "errors": 0,
            "duration": 1.5,
        }

        run_async(handler._show_test_results(update, results, "unit"))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "✅" in text
        assert "5 Tests" in text

    def test_failure_shows_cross_and_failed_tests_truncated(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()
        results = {
            "passed": 1,
            "failed": 7,
            "total": 8,
            "skipped": 0,
            "errors": 0,
            "duration": 1.5,
            "failed_tests": [f"tests/test_x.py::test_{i}" for i in range(7)],
        }

        run_async(handler._show_test_results(update, results, "unit"))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "❌" in text
        assert "und 2 weitere" in text

    def test_coverage_line_shown_only_when_present(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()
        results = {
            "passed": 1,
            "failed": 0,
            "total": 1,
            "skipped": 0,
            "errors": 0,
            "duration": 0.1,
            "coverage": 77,
        }

        run_async(handler._show_test_results(update, results, "unit"))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "77%" in text


# ─────────────────────────────────────────────────────────────────────────
# show_test_details
# ─────────────────────────────────────────────────────────────────────────


class TestShowTestDetails:
    def test_no_cached_results_shows_error(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()

        run_async(handler.show_test_details(update, context=Mock(), test_type="unit"))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine unit-Ergebnisse" in msg

    def test_cached_results_shown(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()
        handler.test_results_cache["unit"] = {
            "stdout": "test_x.py::test_a PASSED",
            "stderr": "",
        }

        run_async(handler.show_test_details(update, context=Mock(), test_type="unit"))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "test_a" in text


# ─────────────────────────────────────────────────────────────────────────
# show_coverage_report
# ─────────────────────────────────────────────────────────────────────────


class TestShowCoverageReport:
    def test_success_shows_total_coverage(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path)
        update = make_update()

        run_result = Mock(stdout="", returncode=0)
        report_result = Mock(
            stdout="Name    Stmts  Miss  Cover\nTOTAL     100    10    90%",
            returncode=0,
        )
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=[run_result, report_result])
        )

        run_async(handler.show_coverage_report(update, context=Mock()))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "90%" in text

    def test_nonzero_returncode_shows_error(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path)
        update = make_update()

        run_result = Mock(stdout="", returncode=0)
        report_result = Mock(stdout="", stderr="boom", returncode=1)
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=[run_result, report_result])
        )

        run_async(handler.show_coverage_report(update, context=Mock()))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Fehler beim Generieren" in msg

    def test_timeout_shows_timeout_message(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path)
        update = make_update()

        monkeypatch.setattr(
            subprocess,
            "run",
            Mock(side_effect=subprocess.TimeoutExpired(cmd="coverage", timeout=120)),
        )

        run_async(handler.show_coverage_report(update, context=Mock()))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Zeitlimit" in msg


# ─────────────────────────────────────────────────────────────────────────
# show_all_test_results
# ─────────────────────────────────────────────────────────────────────────


class TestShowAllTestResults:
    def test_empty_cache_shows_no_results_message(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()

        run_async(handler.show_all_test_results(update, context=Mock()))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Test-Ergebnisse" in msg

    def test_aggregates_totals_across_types(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update()
        handler.test_results_cache = {
            "unit": {"passed": 5, "failed": 0, "total": 5, "duration": 1.0},
            "integration": {"passed": 2, "failed": 1, "total": 3, "duration": 2.0},
        }

        run_async(handler.show_all_test_results(update, context=Mock()))

        text = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "8 Tests" in text
        assert "Erfolgreich: 7" in text
        assert "Fehlgeschlagen: 1" in text


# ─────────────────────────────────────────────────────────────────────────
# run_all_tests / _run_test_type
# ─────────────────────────────────────────────────────────────────────────


class TestRunAllTests:
    def test_already_running_shows_busy_message(self, tmp_path):
        handler = make_handler(tmp_path)
        update = make_update(user_id=7)
        handler.running_tests[7] = "unit"

        run_async(handler.run_all_tests(update, context=Mock()))

        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "laufen bereits" in msg

    def test_runs_all_three_types_then_shows_overview(self, tmp_path):
        handler = make_handler(tmp_path)
        handler._run_test_type = AsyncMock()
        handler.show_all_test_results = AsyncMock()
        update = make_update()

        run_async(handler.run_all_tests(update, context=Mock()))

        assert handler._run_test_type.await_count == 3
        called_types = [c.args[0] for c in handler._run_test_type.await_args_list]
        assert called_types == ["unit", "integration", "performance"]
        handler.show_all_test_results.assert_awaited_once()
        assert update.effective_user.id not in handler.running_tests


class TestRunTestType:
    def test_missing_dir_skips_without_crash(self, tmp_path):
        handler = make_handler(tmp_path)
        run_async(handler._run_test_type("unit"))
        assert "unit" not in handler.test_results_cache

    def test_existing_dir_runs_subprocess_and_caches(self, tmp_path, monkeypatch):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        fake_result = Mock(stdout="=========== 1 passed in 0.1s ===========", stderr="")
        monkeypatch.setattr(subprocess, "run", Mock(return_value=fake_result))

        run_async(handler._run_test_type("unit"))

        assert handler.test_results_cache["unit"]["passed"] == 1

    def test_unknown_type_returns_none_without_dir_lookup_crash(self, tmp_path):
        handler = make_handler(tmp_path)
        run_async(handler._run_test_type("does_not_exist"))
        assert "does_not_exist" not in handler.test_results_cache
