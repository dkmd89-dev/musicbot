# handlers/family_challenge_scheduler.py
# -*- coding: utf-8 -*-
"""
FamilyChallengeScheduler – tägliche Auslösung/Verteilung der Familien-
Challenge (Phase F4, Family Hub).

Kein zweiter Scheduler-Mechanismus (Master-Prompt: "Prüfe den bestehenden
Scheduler/JobQueue. Nicht einen zweiten Scheduler erfinden."): dieses
Projekt nutzt kein python-telegram-bot-JobQueue und keinen
APScheduler/cron - Hintergrundausführung läuft ausschließlich über
asyncio-Loops (siehe services/statistik/play_history_poller.py::
PlayHistoryPoller). Diese Klasse folgt exakt demselben etablierten Muster
(start_polling()/stop_polling(), asyncio.create_task, while-True-Schleife
mit asyncio.sleep) statt eine neue Scheduling-Technologie einzuführen.

Bewusst in handlers/, nicht services/ (siehe CLAUDE.md Abschnitt 4,
Schichtgrenzen): diese Klasse sendet Telegram-Nachrichten (`bot.
send_message`) - Telegram-Objekte/API-Zugriff gehören nicht nach
services/. Von bot.py (ExtendedBot, hält die einzige echte `Bot`-Instanz
über self.application.bot) konstruiert/gestartet - analog zur
Konstruktionsstelle von StatistikService.start_polling() dort.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from logger import get_module_logger

from config import Config
from services.family.family_challenge_service import FamilyChallengeService
from services.family.family_service import FamilyService


class FamilyChallengeScheduler:
    """Erzeugt/verteilt täglich um Config.FAMILY_CHALLENGE_TIME die Familien-Challenge."""

    def __init__(
        self,
        bot,
        family_service: Optional[FamilyService] = None,
        challenge_service: Optional[FamilyChallengeService] = None,
        logger=None,
    ):
        self.bot = bot
        self.family_service = family_service or FamilyService()
        self.challenge_service = challenge_service or FamilyChallengeService(
            family_service=self.family_service
        )
        self.logger = logger or get_module_logger("FamilyChallengeScheduler")
        self._task: Optional[asyncio.Task] = None

    def start_polling(self):
        if self._task and not self._task.done():
            self.logger.warning("Family-Challenge-Scheduler läuft bereits.")
            return
        self._task = asyncio.create_task(self._run_daily_loop())

    async def stop_polling(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def _seconds_until_next_run(self) -> float:
        """Sekunden bis zur nächsten Config.FAMILY_CHALLENGE_TIME (heute, sonst morgen)."""
        hour, minute = (int(part) for part in Config.FAMILY_CHALLENGE_TIME.split(":"))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _run_daily_loop(self):
        while True:
            try:
                wait_seconds = self._seconds_until_next_run()
                self.logger.info(
                    f"🎯 Nächste Familien-Challenge in {wait_seconds:.0f}s "
                    f"(Config.FAMILY_CHALLENGE_TIME={Config.FAMILY_CHALLENGE_TIME})."
                )
                await asyncio.sleep(wait_seconds)
                await self.generate_and_broadcast_all_families()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(
                    f"❌ Fehler im Family-Challenge-Scheduler: {e}", exc_info=True
                )
                # Vermeidet Busy-Loop, falls derselbe Fehler sofort wieder
                # auftritt (z.B. dauerhaft kaputte Konfiguration).
                await asyncio.sleep(60)

    async def generate_and_broadcast_all_families(self):
        """
        Erzeugt für jede bekannte Familie die heutige Challenge (idempotent)
        und verteilt sie NUR, wenn sie durch diesen Aufruf neu erzeugt
        wurde - ein bereits per Menü-Klick manuell ausgelöstes
        get_or_create_todays_challenge() (z.B. vor 20 Uhr) soll keinen
        doppelten Broadcast auslösen.
        """
        for family_id in self.family_service.get_all_family_ids():
            try:
                challenge, created = self.challenge_service.get_or_create_todays_challenge(
                    family_id
                )
                if created:
                    await self._broadcast(family_id, challenge)
            except Exception as e:
                self.logger.error(
                    f"❌ Fehler bei Familien-Challenge für family_id={family_id}: {e}",
                    exc_info=True,
                )

    async def _broadcast(self, family_id: str, challenge: dict) -> None:
        members = self.family_service.get_members(family_id, active_only=True)
        text = (
            "🎯 Neue Familien-Challenge!\n\n"
            f"{challenge['question']}\n\n"
            "Antworte im Menü unter '💬 Familien-Challenge' -> '✅ Antworten'."
        )
        for telegram_id, data in members.items():
            if not data.get("notifications", False):
                continue
            try:
                await self.bot.send_message(chat_id=int(telegram_id), text=text)
            except Exception as e:
                self.logger.error(
                    f"❌ Konnte Familien-Challenge nicht an {telegram_id} zustellen: {e}",
                    exc_info=True,
                )
