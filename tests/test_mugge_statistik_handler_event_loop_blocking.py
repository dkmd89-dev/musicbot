"""
AE-10 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md): StatistikHandler ruft
self.statistik_service.create_chart() (matplotlib-Rendering, real gegen
repraesentative 15-Item-Statistiken gemessen: 660,6ms kalt / ~300ms warm
pro Chart) ungewrappt direkt aus async-Handlern auf. Waehrend der gesamte
Bot fuer ALLE Telegram-Nutzer eingefroren war, konnte das an 6 Stellen in
handlers/mugge_statistik_handler.py passieren (Monats-/Jahresrueckblick
rendern je 2 Charts hintereinander, Top-Songs/Top-Kuenstler je 1 Chart) -
erreichbar ueber normale, nicht-Admin-Telegram-Buttons.

Fix: alle 6 create_chart()-Aufrufe ueber asyncio.to_thread() geroutet
(siehe auch tests/test_chart_renderer_thread_safety.py fuer den dazu
notwendigen Thread-Safety-Fix in ChartRenderer selbst - ohne den waere
to_thread() hier nicht sicher gewesen).

Testmethodik wie bei FINDING-1/FINDING-7/backup_handler-P1/
enhanced_status_handler-P1: deterministischer Routing-Beweis (Patch +
Aufzeichnung, kein Timing) plus ein Heartbeat-Test fuer echte
Event-Loop-Responsivitaet waehrend eines kontrollierten synchronen
Stand-ins fuer die reale Blockierung.
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.mugge_statistik_handler import StatistikHandler


def _make_handler():
    with patch("handlers.mugge_statistik_handler.StatistikService"):
        handler = StatistikHandler(user_mgmt_handler=None)
    handler.statistik_service = Mock()
    return handler


def _stats_with_songs():
    return {
        "top_songs": [(f"Song {i}", 10 - i) for i in range(5)],
        "total_plays": 42,
    }


def make_update():
    update = Mock()
    update.effective_user.id = 111
    update.callback_query = None
    update.message = Mock()
    return update


class TestCreateChartRoutedThroughExecutor:
    def test_handle_top_songs_routes_create_chart_through_to_thread(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = _stats_with_songs()
        handler.statistik_service.create_chart.return_value = None

        update = make_update()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        calls = []
        real_to_thread = asyncio.to_thread

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "handlers.mugge_statistik_handler.asyncio.to_thread",
            recording_to_thread,
        ), patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, Mock()))

        assert handler.statistik_service.create_chart in calls, (
            "create_chart() wurde nicht ueber asyncio.to_thread() "
            "aufgerufen - der Aufruf wuerde damit wieder direkt im "
            "Event-Loop-Thread laufen und diesen fuer alle "
            "Telegram-Nutzer blockieren."
        )


class TestEventLoopStaysResponsiveDuringChartCreation:
    def test_event_loop_stays_responsive_during_handle_top_songs(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = _stats_with_songs()

        update = make_update()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_create_chart(stats, chart_type):
            time.sleep(SLEEP_SECONDS)
            return None

        handler.statistik_service.create_chart = blocking_create_chart

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                with patch(
                    "handlers.mugge_statistik_handler.get_config"
                ) as mock_get_config:
                    mock_get_config.return_value.NAVIDROME_USER = "robin"
                    await handler.handle_top_songs(update, Mock())
            finally:
                hb_task.cancel()

        asyncio.run(run_with_heartbeat())

        expected_min_ticks = (SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(heartbeat_ticks) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend create_chart() nicht responsiv: "
            f"nur {len(heartbeat_ticks)} Heartbeat-Ticks (erwartet mind. "
            f"{expected_min_ticks:.0f}) - der blockierende Call laeuft "
            f"offenbar direkt im Event-Loop-Thread statt im Executor."
        )
