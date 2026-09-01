# tests/test_test_menu_handler_event_loop_blocking.py
# -*- coding: utf-8 -*-
"""
INV-01 (Baseline v5/v6 Technical Debt, jetzt behoben): TestMenuHandler
fuehrte insgesamt 5 subprocess.run()-Aufrufe direkt synchron im
Event-Loop-Thread aus, ohne asyncio.to_thread()/run_in_executor() -
strukturell identisch zum bereits behobenen FINDING-7
(enhanced_metadata_processor.py::normalize_loudness(), siehe
tests/test_enhanced_metadata_processor_loudness_blocking.py, dessen
Testmethodik hier repliziert wird).

Am schwerwiegendsten: _execute_test_run() blockiert bei Performance-Tests
bis zu 900s (15 Minuten) - waehrenddessen war der gesamte Bot fuer ALLE
Telegram-Nutzer eingefroren, nicht nur fuer den anfragenden Admin, sobald
irgendein Admin ueber das Test-Menu Performance-Tests startete.

Zwei sich ergaenzende Beweise fuer den Haupt-Fall (_execute_test_run),
analog FINDING-7:

1. TestExecuteTestRunRoutedThroughAsyncioToThread: deterministischer
   Beweis (kein Timing) - patcht asyncio.to_thread am Modulpfad und
   zeichnet auf, welche Funktion durchgereicht wird.
2. TestEventLoopStaysResponsiveDuringExecuteTestRun: der eigentliche
   Regressionstest - ersetzt subprocess.run() durch einen kontrollierten
   SYNCHRONEN time.sleep()-Stand-in und laesst parallel einen Heartbeat
   mitzaehlen. Laeuft der Call direkt im Event-Loop-Thread, kann der Loop
   waehrend des sleep() PRINZIPIELL keinen Heartbeat-Tick bedienen (0
   Ticks garantiert); laeuft er ueber asyncio.to_thread() in einem
   separaten OS-Thread, bedient der Loop den Heartbeat normal weiter.

Fuer die uebrigen 4 subprocess.run()-Aufrufstellen (Coverage-Verfuegbar-
keits-Check, show_coverage_report() x2, _run_test_type()) je ein
deterministischer "routed through asyncio.to_thread"-Beweis - der
Blockierungsmechanismus ist identisch, ein zusaetzlicher Heartbeat-Test
pro Stelle waere redundant.
"""

import asyncio
import subprocess
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from handlers.test_menu_handler import TestMenuHandler


class FakeConfig:
    def __init__(self, base_dir):
        self.BASE_DIR = str(base_dir)


def make_handler(tmp_path, create_dirs=None):
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


class TestExecuteTestRunRoutedThroughAsyncioToThread:
    def test_main_pytest_call_is_routed_through_asyncio_to_thread(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        real_to_thread = asyncio.to_thread
        calls = []

        fake_result = Mock(
            stdout="=========== 1 passed in 0.01s ===========",
            stderr="",
            returncode=0,
        )
        monkeypatch.setattr(subprocess, "run", Mock(return_value=fake_result))

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "handlers.test_menu_handler.asyncio.to_thread",
            side_effect=recording_to_thread,
        ):
            asyncio.run(
                handler._execute_test_run(update, "unit", timeout=600, context=Mock())
            )

        assert subprocess.run in calls, (
            "Der pytest-Lauf wurde nicht ueber asyncio.to_thread() "
            "aufgerufen - der Aufruf wuerde damit wieder direkt im "
            "Event-Loop-Thread laufen und diesen fuer alle Telegram-Nutzer "
            "bis zu `timeout` Sekunden blockieren."
        )


class TestEventLoopStaysResponsiveDuringExecuteTestRun:
    def test_event_loop_stays_responsive_during_pytest_run(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_run(*a, **kw):
            time.sleep(SLEEP_SECONDS)
            return Mock(
                stdout="=========== 1 passed in 0.01s ===========",
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", blocking_run)

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                await handler._execute_test_run(
                    update, "unit", timeout=600, context=Mock()
                )
            finally:
                hb_task.cancel()

        asyncio.run(run_with_heartbeat())

        expected_min_ticks = (SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(heartbeat_ticks) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend des pytest-Laufs nicht responsiv: "
            f"nur {len(heartbeat_ticks)} Heartbeat-Ticks (erwartet mind. "
            f"{expected_min_ticks:.0f}) - subprocess.run() laeuft offenbar "
            f"direkt im Event-Loop-Thread statt in asyncio.to_thread()."
        )


class TestRemainingSubprocessCallSitesRoutedThroughAsyncioToThread:
    """Die restlichen 4 subprocess.run()-Aufrufstellen - je ein
    deterministischer Beweis, kein zusaetzlicher Heartbeat-Test noetig
    (identischer Mechanismus wie oben bereits vollstaendig verifiziert)."""

    def test_coverage_availability_check_is_routed_through_asyncio_to_thread(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])
        update = make_update()

        real_to_thread = asyncio.to_thread
        calls = []

        # Erster subprocess.run()-Aufruf (Coverage-Verfuegbarkeits-Check)
        # muss erfolgreich sein, damit der zweite (Hauptlauf) ueberhaupt
        # erreicht wird - beide sollen aufgezeichnet werden.
        version_result = Mock(returncode=0)
        run_result = Mock(
            stdout="=========== 1 passed in 0.01s ===========",
            stderr="",
            returncode=0,
        )
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=[version_result, run_result])
        )

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "handlers.test_menu_handler.asyncio.to_thread",
            side_effect=recording_to_thread,
        ):
            asyncio.run(
                handler._execute_test_run(update, "unit", timeout=600, context=Mock())
            )

        assert calls.count(subprocess.run) == 2, (
            "Erwartet: sowohl der Coverage-Verfuegbarkeits-Check als auch "
            "der Hauptlauf werden ueber asyncio.to_thread() ausgefuehrt."
        )

    def test_show_coverage_report_calls_are_routed_through_asyncio_to_thread(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path)
        update = make_update()

        real_to_thread = asyncio.to_thread
        calls = []

        run_result = Mock(stdout="", returncode=0)
        report_result = Mock(
            stdout="Name    Stmts  Miss  Cover\nTOTAL     100    10    90%",
            returncode=0,
        )
        monkeypatch.setattr(
            subprocess, "run", Mock(side_effect=[run_result, report_result])
        )

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "handlers.test_menu_handler.asyncio.to_thread",
            side_effect=recording_to_thread,
        ):
            asyncio.run(handler.show_coverage_report(update, Mock()))

        assert calls.count(subprocess.run) == 2, (
            "Erwartet: beide subprocess.run()-Aufrufe in "
            "show_coverage_report() (coverage run + coverage report) "
            "werden ueber asyncio.to_thread() ausgefuehrt."
        )

    def test_run_test_type_is_routed_through_asyncio_to_thread(
        self, tmp_path, monkeypatch
    ):
        handler = make_handler(tmp_path, create_dirs=[("unit", ["test_x.py"])])

        real_to_thread = asyncio.to_thread
        calls = []

        fake_result = Mock(stdout="=========== 1 passed in 0.01s ===========", stderr="")
        monkeypatch.setattr(subprocess, "run", Mock(return_value=fake_result))

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "handlers.test_menu_handler.asyncio.to_thread",
            side_effect=recording_to_thread,
        ):
            asyncio.run(handler._run_test_type("unit"))

        assert subprocess.run in calls, (
            "_run_test_type() (von run_all_tests() dreimal nacheinander "
            "aufgerufen) muss subprocess.run() ueber asyncio.to_thread() "
            "ausfuehren."
        )
