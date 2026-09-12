# handlers/family_stats_handler.py
# -*- coding: utf-8 -*-
"""
FamilyStatsHandler – Telegram-Präsentation für Familien-Statistiken
(Phase F2, Family Hub).

Verantwortlichkeit (Single Responsibility, siehe CLAUDE.md Abschnitt 4):
  - Ausschließlich Telegram-Präsentation (Nachrichtenversand, Formatierung).
  - Berechtigungsprüfung delegiert an FamilyService, Aggregation an
    FamilyStatsService - KEINE Fachlogik hier.

Stil bewusst identisch zu handlers/mugge_statistik_handler.py::StatistikHandler
übernommen (Plain-Text-Antworten ohne parse_mode, kein zentraler
error_handler - dieselbe Begründung: jeder except-Block editiert die
separat gesendete "läuft..."-Zwischennachricht, nicht die
callback_query-Nachricht selbst).

Datenschutz (Master-Prompt, Phase F1 "Datenschutz"): JEDE Methode prüft
zuerst `FamilyService.is_active_family_member()`, bevor irgendein
Family-Datum gelesen/gesendet wird. Ein normaler Bot-Benutzer ohne
Family-Zugehörigkeit bekommt ausschließlich eine Zugriffsverweigerung.
"""

from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from emoji import EMOJI
from logger import get_module_logger
from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService


def _format_seconds(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}min"
    return f"{minutes}min"


class FamilyStatsHandler:
    """Telegram-Handler für die Familien-Statistik-Menüzweige."""

    WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    def __init__(
        self,
        family_service: Optional[FamilyService] = None,
        family_stats_service: Optional[FamilyStatsService] = None,
    ):
        self.logger = get_module_logger("FamilyStatsHandler")
        self.family_service = family_service or FamilyService()
        self.family_stats_service = family_stats_service or FamilyStatsService(
            family_service=self.family_service
        )
        self.logger.info("✅ FamilyStatsHandler initialisiert")

    # ─────────────────────────────────────────────────────────────
    # Zugriffsprüfung + gemeinsame Hilfsfunktionen
    # ─────────────────────────────────────────────────────────────

    def _resolve_family_id(self, update: Update) -> Optional[str]:
        """
        Telegram User ID -> Familienmitglied? -> Family ID -> Zugriff erlaubt.

        Returns:
            family_id, wenn der anfragende Telegram-Nutzer ein AKTIVES
            Familienmitglied ist, sonst None.
        """
        telegram_id = update.effective_user.id
        if not self.family_service.is_active_family_member(telegram_id):
            return None
        return self.family_service.get_family_id_for_telegram_user(telegram_id)

    async def _reply_target(self, update: Update):
        return update.callback_query.message if update.callback_query else update.message

    async def _deny_access(self, update: Update) -> None:
        telegram_id = update.effective_user.id
        self.logger.warning(
            f"⛔ Zugriff auf Familien-Statistik verweigert für Telegram-ID {telegram_id} "
            "(kein aktives Familienmitglied)."
        )
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ Nur für Familienmitglieder verfügbar.", show_alert=True
            )
        reply_target = await self._reply_target(update)
        if reply_target:
            await reply_target.reply_text(
                f"{EMOJI['warning']} Diese Funktion ist nur für Familienmitglieder verfügbar."
            )

    async def _send_processing_message(self, update: Update, action: str):
        reply_target = await self._reply_target(update)
        if not reply_target:
            self.logger.error(f"❌ Keine Nachricht zum Antworten für {action}")
            return None, None
        msg = await reply_target.reply_text(f"{EMOJI['processing']} 🔄 {action}...")
        return reply_target, msg

    # ─────────────────────────────────────────────────────────────
    # 🎵 Top Songs Familie / 🎤 Top Künstler Familie
    # ─────────────────────────────────────────────────────────────

    async def handle_family_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Familien-Top-Songs")
        if not msg:
            return

        try:
            stats = self.family_stats_service.generate_family_stats(family_id, period)
            if not stats or not stats["top_songs"]:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie im Zeitraum '{period}'."
                )
                return

            lines = [
                f"{idx + 1}. {title} ({count} Plays)"
                for idx, (title, count) in enumerate(stats["top_songs"])
            ]
            response = (
                f"🎵 Top Songs Familie ({period.title()}):\n\n"
                + "\n".join(lines)
                + f"\n\n{EMOJI['chart']} Gesamt Plays: {stats['total_plays']}"
            )
            await msg.edit_text(response)

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(f"❌ Fehler in handle_family_top_songs: {e}", exc_info=True)

    async def handle_family_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Familien-Top-Künstler")
        if not msg:
            return

        try:
            stats = self.family_stats_service.generate_family_stats(family_id, period)
            if not stats or not stats["top_artists"]:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie im Zeitraum '{period}'."
                )
                return

            lines = [
                f"{idx + 1}. {artist} ({count} Plays)"
                for idx, (artist, count) in enumerate(stats["top_artists"])
            ]
            response = (
                f"🎤 Top Künstler Familie ({period.title()}):\n\n"
                + "\n".join(lines)
                + f"\n\n{EMOJI['chart']} Gesamt Plays: {stats['total_plays']}"
            )
            await msg.edit_text(response)

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(f"❌ Fehler in handle_family_top_artists: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # 👥 Statistik pro Person
    # ─────────────────────────────────────────────────────────────

    async def handle_family_member_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Statistik pro Person")
        if not msg:
            return

        try:
            stats = self.family_stats_service.generate_family_stats(family_id, period)
            if not stats or not stats["per_member"]:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie im Zeitraum '{period}'."
                )
                return

            ranked = sorted(
                stats["per_member"].values(), key=lambda m: m["plays"], reverse=True
            )
            lines = [f"👤 {m['display_name']}: {m['plays']} Plays" for m in ranked]
            response = (
                f"👥 Statistik pro Person ({period.title()}):\n\n" + "\n".join(lines)
            )
            await msg.edit_text(response)

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(
                f"❌ Fehler in handle_family_member_stats: {e}", exc_info=True
            )

    # ─────────────────────────────────────────────────────────────
    # 🏆 Musik-Champion
    # ─────────────────────────────────────────────────────────────

    async def handle_family_champion(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Ermittle Musik-Champion")
        if not msg:
            return

        try:
            champion = self.family_stats_service.get_champion(family_id, period)
            if champion is None:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie im Zeitraum '{period}'."
                )
                return

            _, display_name, plays = champion
            await msg.edit_text(
                f"🏆 Musik-Champion ({period.title()}): {display_name} mit {plays} Plays!"
            )

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(f"❌ Fehler in handle_family_champion: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # ⏰ Hörzeiten
    # ─────────────────────────────────────────────────────────────

    async def handle_family_listening_times(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Hörzeiten")
        if not msg:
            return

        try:
            result = self.family_stats_service.generate_listening_times(family_id, period)
            if not result:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie im Zeitraum '{period}'."
                )
                return

            peak_hour = max(result["by_hour"].items(), key=lambda kv: kv[1])
            peak_weekday_idx, peak_weekday_count = max(
                result["by_weekday"].items(), key=lambda kv: kv[1]
            )
            peak_weekday = self.WEEKDAY_NAMES[peak_weekday_idx]

            response = (
                f"⏰ Hörzeiten Familie ({period.title()}):\n\n"
                f"Meistgehörte Stunde: {peak_hour[0]}:00 Uhr ({peak_hour[1]} Plays)\n"
                f"Meistgehörter Wochentag: {peak_weekday} ({peak_weekday_count} Plays)\n\n"
                f"{EMOJI['chart']} Gesamt Plays: {result['total_plays']}"
            )
            await msg.edit_text(response)

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(
                f"❌ Fehler in handle_family_listening_times: {e}", exc_info=True
            )

    # ─────────────────────────────────────────────────────────────
    # 📈 Monatsentwicklung
    # ─────────────────────────────────────────────────────────────

    async def handle_family_monthly_trend(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Monatsentwicklung")
        if not msg:
            return

        try:
            trend = self.family_stats_service.generate_monthly_trend(family_id)
            if not trend:
                await msg.edit_text(
                    f"{EMOJI['warning']} Keine Wiedergaben der Familie in den letzten Monaten."
                )
                return

            lines = [
                f"{month}: {trend['plays_by_month'][month]} Plays"
                for month in trend["months"]
            ]
            response = "📈 Monatsentwicklung Familie:\n\n" + "\n".join(lines)
            await msg.edit_text(response)

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(
                f"❌ Fehler in handle_family_monthly_trend: {e}", exc_info=True
            )
