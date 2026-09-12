"""
Phase F4 (Family Hub) - Tests für handlers/family_challenge_scheduler.py.

Lifecycle-Tests (start/stop) nach demselben Muster wie
tests/test_play_history_poller.py::TestStartStopPolling - die
Schleife selbst (_run_daily_loop) wird NICHT laufen gelassen (würde real
bis Config.FAMILY_CHALLENGE_TIME schlafen); stattdessen werden
_seconds_until_next_run() und generate_and_broadcast_all_families()/
_broadcast() isoliert getestet.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.family_challenge_scheduler import FamilyChallengeScheduler


def _make_scheduler():
    bot = Mock()
    bot.send_message = AsyncMock()
    family_service = Mock()
    challenge_service = Mock()
    scheduler = FamilyChallengeScheduler(
        bot, family_service=family_service, challenge_service=challenge_service
    )
    return scheduler, bot, family_service, challenge_service


class TestStartStopPolling:
    def test_start_polling_creates_task(self):
        scheduler, *_ = _make_scheduler()

        async def _run():
            scheduler.start_polling()
            assert scheduler._task is not None
            await scheduler.stop_polling()

        asyncio.run(_run())

    def test_start_polling_twice_does_not_create_second_task(self):
        scheduler, *_ = _make_scheduler()

        async def _run():
            scheduler.start_polling()
            first_task = scheduler._task
            scheduler.start_polling()
            assert scheduler._task is first_task
            await scheduler.stop_polling()

        asyncio.run(_run())

    def test_stop_polling_without_start_is_a_noop(self):
        scheduler, *_ = _make_scheduler()
        asyncio.run(scheduler.stop_polling())
        assert scheduler._task is None

    def test_stop_polling_cancels_running_task(self):
        scheduler, *_ = _make_scheduler()

        async def _run():
            scheduler.start_polling()
            await scheduler.stop_polling()
            assert scheduler._task is None

        asyncio.run(_run())


class TestSecondsUntilNextRun:
    def test_target_later_today_returns_positive_seconds_less_than_a_day(self):
        scheduler, *_ = _make_scheduler()
        fixed_now = datetime(2026, 9, 13, 10, 0, 0)

        with patch(
            "handlers.family_challenge_scheduler.Config.FAMILY_CHALLENGE_TIME",
            "20:00",
        ), patch("handlers.family_challenge_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            seconds = scheduler._seconds_until_next_run()

        assert 0 < seconds <= 24 * 3600

    def test_target_already_passed_today_rolls_over_to_tomorrow(self):
        scheduler, *_ = _make_scheduler()
        fixed_now = datetime(2026, 9, 13, 21, 0, 0)

        with patch(
            "handlers.family_challenge_scheduler.Config.FAMILY_CHALLENGE_TIME",
            "20:00",
        ), patch("handlers.family_challenge_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            seconds = scheduler._seconds_until_next_run()

        # 21:00 -> naechster Lauf morgen 20:00 = 23h spaeter
        assert 22 * 3600 < seconds <= 23 * 3600


class TestGenerateAndBroadcastAllFamilies:
    def test_broadcasts_only_for_newly_created_challenges(self):
        scheduler, bot, family_service, challenge_service = _make_scheduler()
        family_service.get_all_family_ids.return_value = ["main", "other"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True}
        }

        def _get_or_create(family_id):
            if family_id == "main":
                return {"question": "Q-main"}, True
            return {"question": "Q-other"}, False  # bereits manuell erzeugt

        challenge_service.get_or_create_todays_challenge.side_effect = _get_or_create

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 1
        assert "Q-main" in bot.send_message.call_args.kwargs["text"]

    def test_skips_members_with_notifications_disabled(self):
        scheduler, bot, family_service, challenge_service = _make_scheduler()
        family_service.get_all_family_ids.return_value = ["main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": False},
            "222": {"active": True, "notifications": True},
        }
        challenge_service.get_or_create_todays_challenge.return_value = (
            {"question": "Q"},
            True,
        )

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 1
        assert bot.send_message.call_args.kwargs["chat_id"] == 222

    def test_one_family_erroring_does_not_block_others(self):
        scheduler, bot, family_service, challenge_service = _make_scheduler()
        family_service.get_all_family_ids.return_value = ["broken", "main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True}
        }

        def _get_or_create(family_id):
            if family_id == "broken":
                raise RuntimeError("kaputt")
            return {"question": "Q"}, True

        challenge_service.get_or_create_todays_challenge.side_effect = _get_or_create

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 1

    def test_one_recipient_send_failure_does_not_raise(self):
        scheduler, bot, family_service, challenge_service = _make_scheduler()
        family_service.get_all_family_ids.return_value = ["main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True},
            "222": {"active": True, "notifications": True},
        }
        challenge_service.get_or_create_todays_challenge.return_value = (
            {"question": "Q"},
            True,
        )
        bot.send_message.side_effect = [Exception("Telegram down"), None]

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 2
