"""
Phase F4 (Family Hub) - Tests für handlers/family_challenge_scheduler.py.

Lifecycle-Tests (start/stop) nach demselben Muster wie
tests/test_play_history_poller.py::TestStartStopPolling - die
Schleife selbst (_run_daily_loop) wird NICHT laufen gelassen (würde real
bis Config.FAMILY_CHALLENGE_TIME schlafen); stattdessen werden
_seconds_until_next_run() und generate_and_broadcast_all_families()/
_broadcast() isoliert getestet.

ARCH-027 (Error-Handler-Closure), Bugfix: FAMILY_CHALLENGE_TIME ist eine
@property der Config-INSTANZ (config.py) - der vorherige Zugriff über
die bloße Klasse (Config.FAMILY_CHALLENGE_TIME) lieferte das
property-Objekt selbst statt des Strings ('property' object has no
attribute 'split', Live-Fund). _make_scheduler() injiziert seither eine
FakeConfig-Instanz statt die Klasse zu patchen.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.family_challenge_scheduler import FamilyChallengeScheduler


class FakeConfig:
    FAMILY_CHALLENGE_TIME = "20:00"


def _make_scheduler(config=None, error_handler=None):
    bot = Mock()
    bot.send_message = AsyncMock()
    family_service = Mock()
    challenge_service = Mock()
    scheduler = FamilyChallengeScheduler(
        bot,
        config=config or FakeConfig(),
        family_service=family_service,
        challenge_service=challenge_service,
        error_handler=error_handler,
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

        with patch("handlers.family_challenge_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            seconds = scheduler._seconds_until_next_run()

        assert 0 < seconds <= 24 * 3600

    def test_target_already_passed_today_rolls_over_to_tomorrow(self):
        scheduler, *_ = _make_scheduler()
        fixed_now = datetime(2026, 9, 13, 21, 0, 0)

        with patch("handlers.family_challenge_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            seconds = scheduler._seconds_until_next_run()

        # 21:00 -> naechster Lauf morgen 20:00 = 23h spaeter
        assert 22 * 3600 < seconds <= 23 * 3600

    def test_reads_time_from_injected_config_instance_not_bare_class(self):
        """Regressionstest fuer den Live-Fund 'property' object has no
        attribute 'split': FAMILY_CHALLENGE_TIME ist eine @property der
        Config-INSTANZ - ein Zugriff ueber die bloße Klasse muss hier
        nicht mehr moeglich sein, self.config (Instanz) ist Pflicht."""
        config = FakeConfig()
        config.FAMILY_CHALLENGE_TIME = "06:30"
        scheduler, *_ = _make_scheduler(config=config)
        fixed_now = datetime(2026, 9, 13, 10, 0, 0)

        with patch("handlers.family_challenge_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            seconds = scheduler._seconds_until_next_run()

        # 10:00 -> naechster Lauf morgen 06:30 = 20,5h spaeter
        assert 20 * 3600 < seconds <= 21 * 3600

    def test_real_config_property_does_not_raise_property_object_has_no_split(self):
        """Regressionstest gegen die tatsaechliche config.Config-Klasse
        (nicht FakeConfig) - stellt sicher, dass der reale Live-Bug
        ('property' object has no attribute 'split') mit einer echten
        Config-Instanz nicht mehr auftritt."""
        from config import Config

        scheduler, *_ = _make_scheduler(config=Config())
        # Darf nicht raisen:
        seconds = scheduler._seconds_until_next_run()
        assert seconds > 0


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


class TestErrorHandlerIntegration:
    """ARCH-027 (Error-Handler-Closure): FamilyChallengeScheduler hatte
    bisher keine einzige error_handler-Referenz - Exceptions landeten
    ausschließlich im lokalen Logger, nie im zentralen
    EnhancedErrorHandler (bestätigt per Verifikation vor diesem Fix).
    Diese Tests stellen sicher, dass die Injection tatsächlich wirkt,
    nicht nur auf dem Papier existiert (Fehler einer Familie/eines
    Broadcasts dürfen die anderen weiterhin nicht stoppen - siehe
    bereits bestehende Tests oben, unverändert)."""

    def test_family_error_is_reported_to_injected_error_handler(self):
        error_handler = Mock()
        error_handler.handle_exception = AsyncMock()
        scheduler, bot, family_service, challenge_service = _make_scheduler(
            error_handler=error_handler
        )
        family_service.get_all_family_ids.return_value = ["broken", "main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True}
        }
        exc = RuntimeError("kaputt")

        def _get_or_create(family_id):
            if family_id == "broken":
                raise exc
            return {"question": "Q"}, True

        challenge_service.get_or_create_todays_challenge.side_effect = _get_or_create

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 1  # "main" lief weiter
        error_handler.handle_exception.assert_awaited_once()
        call_args = error_handler.handle_exception.call_args
        assert call_args.args[0] is exc
        assert call_args.kwargs["context"]["module"] == "FamilyChallengeScheduler"
        assert call_args.kwargs["context"]["family_id"] == "broken"

    def test_broadcast_failure_is_reported_to_injected_error_handler(self):
        error_handler = Mock()
        error_handler.handle_exception = AsyncMock()
        scheduler, bot, family_service, challenge_service = _make_scheduler(
            error_handler=error_handler
        )
        family_service.get_all_family_ids.return_value = ["main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True},
            "222": {"active": True, "notifications": True},
        }
        challenge_service.get_or_create_todays_challenge.return_value = (
            {"question": "Q"},
            True,
        )
        exc = Exception("Telegram down")
        bot.send_message.side_effect = [exc, None]

        asyncio.run(scheduler.generate_and_broadcast_all_families())

        assert bot.send_message.call_count == 2  # zweiter Empfaenger lief weiter
        error_handler.handle_exception.assert_awaited_once()
        call_args = error_handler.handle_exception.call_args
        assert call_args.args[0] is exc
        assert call_args.kwargs["context"]["module"] == "FamilyChallengeScheduler"
        assert call_args.kwargs["context"]["operation"] == "broadcast"

    def test_without_error_handler_still_isolates_family_failures(self):
        """Rueckwaertskompatibilitaet: error_handler=None (Default,
        Standalone-Konstruktion) aendert das bestehende Verhalten nicht."""
        scheduler, bot, family_service, challenge_service = _make_scheduler()
        assert scheduler.error_handler is None
        family_service.get_all_family_ids.return_value = ["broken", "main"]
        family_service.get_members.return_value = {
            "111": {"active": True, "notifications": True}
        }

        def _get_or_create(family_id):
            if family_id == "broken":
                raise RuntimeError("kaputt")
            return {"question": "Q"}, True

        challenge_service.get_or_create_todays_challenge.side_effect = _get_or_create

        asyncio.run(scheduler.generate_and_broadcast_all_families())  # darf nicht raisen

        assert bot.send_message.call_count == 1

    def test_run_daily_loop_reports_unexpected_exception_to_error_handler(self):
        """Deckt den echten Live-Bug-Pfad ab: eine Exception in
        _seconds_until_next_run()/generate_and_broadcast_all_families(),
        die bis in _run_daily_loop()s eigenen except-Block durchschlägt,
        muss zentral gemeldet werden."""
        error_handler = Mock()
        error_handler.handle_exception = AsyncMock()
        scheduler, *_ = _make_scheduler(error_handler=error_handler)
        exc = RuntimeError("seconds boom")
        call_count = 0

        def _raise_once_then_cancel():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc
            raise asyncio.CancelledError()

        async def _run():
            with patch.object(
                scheduler, "_seconds_until_next_run", side_effect=_raise_once_then_cancel
            ), patch(
                "handlers.family_challenge_scheduler.asyncio.sleep",
                AsyncMock(return_value=None),
            ):
                with pytest.raises(asyncio.CancelledError):
                    await scheduler._run_daily_loop()

        asyncio.run(_run())

        error_handler.handle_exception.assert_awaited_once()
        call_args = error_handler.handle_exception.call_args
        assert call_args.args[0] is exc
        assert call_args.kwargs["context"]["operation"] == "run_daily_loop"
