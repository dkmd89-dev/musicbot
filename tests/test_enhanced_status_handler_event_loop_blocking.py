"""
P1 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27): EnhancedStatusHandler.
show_storage_status() traversierte 5 Verzeichnisse (rglob + stat pro Datei)
inklusive LIBRARY_DIR direkt inline im Event-Loop-Thread - real gegen die
tatsaechliche Library dieser Umgebung gemessen: 9,46s allein fuer die Library.
Der gesamte Bot war waehrenddessen fuer ALLE Telegram-Nutzer eingefroren, jedes
Mal wenn der Storage-Status-Button im Status-Menue gedrueckt wurde.

Fix: die Traversierung wurde in _build_storage_report() (sync, @staticmethod)
extrahiert und ueber asyncio.get_event_loop().run_in_executor() aufgerufen -
identisches Muster wie handlers/admin/backup_handler.py::_dir_size().

Testmethodik wie bei FINDING-1/FINDING-7/backup_handler-P1: deterministischer
Beweis (Patch + Aufzeichnung) plus Heartbeat-Test fuer echte
Event-Loop-Responsivitaet.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.enhanced_status_handler import EnhancedStatusHandler


class FakeConfig:
    BASE_DIR = Path("/tmp")
    LIBRARY_DIR = Path("/tmp/nonexistent_library")
    DOWNLOAD_DIR = Path("/tmp/nonexistent_downloads")
    DATA_DIR = Path("/tmp/nonexistent_data")
    LOG_DIR = Path("/tmp/nonexistent_logs")
    TEMP_DIR = Path("/tmp/nonexistent_temp")


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


class TestStorageReportRoutedThroughExecutor:
    def test_show_storage_status_routes_report_through_executor(self):
        handler = EnhancedStatusHandler(FakeConfig())
        calls = []

        loop = asyncio.new_event_loop()
        try:
            real_run_in_executor = loop.run_in_executor

            def recording_run_in_executor(executor, func, *args):
                calls.append(func)
                return real_run_in_executor(executor, func, *args)

            loop.run_in_executor = recording_run_in_executor
            loop.run_until_complete(
                handler.show_storage_status(make_update(), Mock())
            )
        finally:
            loop.close()

        assert (
            handler._build_storage_report in calls
            or EnhancedStatusHandler._build_storage_report in calls
        ), (
            "_build_storage_report() wurde nicht ueber run_in_executor() "
            "aufgerufen - der Aufruf wuerde damit wieder direkt im "
            "Event-Loop-Thread laufen und diesen fuer alle Telegram-Nutzer "
            "blockieren."
        )


class TestEventLoopStaysResponsiveDuringStorageReport:
    def test_event_loop_stays_responsive_during_show_storage_status(
        self, monkeypatch
    ):
        handler = EnhancedStatusHandler(FakeConfig())

        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_report(directories):
            time.sleep(SLEEP_SECONDS)
            return "📁 **Storage-Status**\n\nstand-in"

        monkeypatch.setattr(
            EnhancedStatusHandler,
            "_build_storage_report",
            staticmethod(blocking_report),
        )

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                await handler.show_storage_status(make_update(), Mock())
            finally:
                hb_task.cancel()

        asyncio.run(run_with_heartbeat())

        expected_min_ticks = (SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(heartbeat_ticks) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend _build_storage_report() nicht "
            f"responsiv: nur {len(heartbeat_ticks)} Heartbeat-Ticks "
            f"(erwartet mind. {expected_min_ticks:.0f}) - der blockierende "
            f"Call laeuft offenbar direkt im Event-Loop-Thread statt im "
            f"Executor."
        )
