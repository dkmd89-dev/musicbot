"""
P1 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27): BackupHandler._dir_size()
traversiert das komplette Quellverzeichnis (rglob + stat pro Datei) - real gegen
die tatsaechliche Library dieser Umgebung gemessen: 9,46s fuer 2286 Dateien/9,0 GB.
Trotz eines irrefuehrenden Kommentars ("nicht-blockierend schaetzen") lief der
Aufruf ungewrappt direkt im Event-Loop-Thread - waehrenddessen war der gesamte Bot
fuer ALLE Telegram-Nutzer eingefroren, jedes Mal wenn das Backup-Menue geoeffnet
oder eine Backup-Bestaetigung angezeigt wurde.

Fix: _dir_size() ueber asyncio.get_event_loop().run_in_executor() aufgerufen -
exakt dasselbe, bereits im selben File fuer _create_archive() etablierte Muster
(start_bot_backup()/start_lib_backup()).

Testmethodik wie bei FINDING-1/FINDING-7: deterministischer Beweis (Patch +
Aufzeichnung, kein Timing) plus ein Heartbeat-Test, der echte
Event-Loop-Responsivitaet waehrend eines kontrollierten, synchronen Stand-ins
fuer die reale Blockierung nachweist.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.admin.backup_handler import BackupHandler


class FakeConfig:
    def __init__(self, tmp_path):
        self.BACKUP_BOT_SOURCE_DIR = str(tmp_path / "bot_source")
        self.BACKUP_LIBRARY_SOURCE_DIR = str(tmp_path / "lib_source")
        self.BACKUP_DEST_DIR = str(tmp_path / "backups")
        self.BACKUP_MAX_KEEP = 3


def _make_handler(tmp_path):
    config = FakeConfig(tmp_path)
    Path(config.BACKUP_BOT_SOURCE_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.BACKUP_LIBRARY_SOURCE_DIR).mkdir(parents=True, exist_ok=True)
    return BackupHandler(config)


def make_update():
    update = Mock()
    update.callback_query = Mock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


class TestDirSizeRoutedThroughExecutor:
    def test_show_main_menu_routes_dir_size_through_executor(self, tmp_path):
        handler = _make_handler(tmp_path)
        calls = []

        # asyncio.get_event_loop() innerhalb einer laufenden Coroutine liefert
        # das laufende Loop-Objekt zurueck - explizit dieselbe Loop-Instanz
        # verwenden (statt asyncio.run(), das intern eine eigene, neue Loop
        # erzeugt), damit der Patch auf run_in_executor tatsaechlich greift.
        loop = asyncio.new_event_loop()
        try:
            real_run_in_executor = loop.run_in_executor

            def recording_run_in_executor(executor, func, *args):
                calls.append(func)
                return real_run_in_executor(executor, func, *args)

            loop.run_in_executor = recording_run_in_executor
            loop.run_until_complete(handler.show_main_menu(make_update(), Mock()))
        finally:
            loop.close()

        assert handler._dir_size in calls or BackupHandler._dir_size in calls, (
            "_dir_size() wurde nicht ueber run_in_executor() aufgerufen - der "
            "Aufruf wuerde damit wieder direkt im Event-Loop-Thread laufen und "
            "diesen fuer alle Telegram-Nutzer blockieren."
        )


class TestEventLoopStaysResponsiveDuringDirSize:
    def test_event_loop_stays_responsive_during_show_main_menu(
        self, tmp_path, monkeypatch
    ):
        """
        Der eigentliche Regressionstest: waehrend _dir_size() laeuft, muss der
        Event-Loop weiterhin andere Coroutinen bedienen koennen. Ersetzt den
        echten rglob()-Scan durch einen kontrollierten synchronen time.sleep()
        (steht stellvertretend fuer die real gemessene Blockierung) und laesst
        parallel einen Heartbeat mitzaehlen.
        """
        handler = _make_handler(tmp_path)

        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_dir_size(path):
            time.sleep(SLEEP_SECONDS)
            return 1234

        monkeypatch.setattr(BackupHandler, "_dir_size", staticmethod(blocking_dir_size))

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                await handler.show_main_menu(make_update(), Mock())
            finally:
                hb_task.cancel()

        asyncio.run(run_with_heartbeat())

        # show_main_menu ruft _dir_size() zweimal auf (bot_source + lib_source)
        # -> insgesamt ~0.6s Blockierungs-Stand-in.
        expected_min_ticks = (2 * SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(heartbeat_ticks) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend _dir_size() nicht responsiv: "
            f"nur {len(heartbeat_ticks)} Heartbeat-Ticks (erwartet mind. "
            f"{expected_min_ticks:.0f}) - der blockierende Call laeuft "
            f"offenbar direkt im Event-Loop-Thread statt im Executor."
        )
