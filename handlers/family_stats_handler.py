# handlers/family_stats_handler.py
# -*- coding: utf-8 -*-
"""
FamilyStatsHandler – Telegram-Präsentation für Familien-Statistiken
(Phase F2, Family Hub).

Verantwortlichkeit (Single Responsibility, siehe CLAUDE.md Abschnitt 4):
  - Ausschließlich Telegram-Präsentation (Nachrichtenversand, Formatierung).
  - Berechtigungsprüfung delegiert an FamilyService, Aggregation/Identity/
    Member-Attribution an FamilyStatsService - KEINE Fachlogik hier.

Stil bewusst identisch zu handlers/mugge_statistik_handler.py::StatistikHandler
übernommen (Plain-Text-Antworten ohne parse_mode, kein zentraler
error_handler - dieselbe Begründung: jeder except-Block editiert die
separat gesendete "läuft..."-Zwischennachricht, nicht die
callback_query-Nachricht selbst).

MASTER PHASE B (Family Statistics Attribution, Identity & UX
Optimization): Formatierung nutzt jetzt dieselben geteilten Presentation-
Helfer wie die Personal Statistics (`format_plays()`/`format_rank()`/
`format_date_range()`/`SEPARATOR`/`GERMAN_MONTHS`, siehe
handlers/statistik_format_helpers.py-Docstring) - keine zweite
Formatierungssprache. Datengrundlage (`top_songs`/`top_artists`) kommt
jetzt strukturiert mit echter Member-Attribution aus
`FamilyStatsService.generate_family_stats()` statt (name, count)-Tupeln.

Datenschutz (Master-Prompt, Phase F1 "Datenschutz"): JEDE Methode prüft
zuerst `FamilyService.is_active_family_member()`, bevor irgendein
Family-Datum gelesen/gesendet wird. Ein normaler Bot-Benutzer ohne
Family-Zugehörigkeit bekommt ausschließlich eine Zugriffsverweigerung.
"""

from typing import Any, Dict, List, Optional

from telegram import Update
from telegram.ext import ContextTypes

from emoji import EMOJI
from logger import get_module_logger
from services.family.family_service import FamilyService
from services.family.family_stats_service import FamilyStatsService
from services.statistik.statistics_calculator import GERMAN_MONTHS
from handlers.statistik_format_helpers import SEPARATOR, format_date_range, format_plays, format_rank


def _format_seconds(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}min"
    return f"{minutes}min"


def _format_percentage(part: int, total: int) -> str:
    """Deutsches Prozentformat, 1 Dezimalstelle, Komma statt Punkt
    (Abschnitt 17: "62,2 %"). `total` ist an dieser Stelle immer > 0
    (nur für Mitglieder mit mindestens einem Play aufgerufen)."""
    value = round(part / total * 100, 1)
    return f"{value:.1f}".replace(".", ",")


def _format_member_lines(members: List[Dict[str, Any]], total_plays: int) -> List[str]:
    """Abschnitt 14: Member-Zeilen ("👤 Name · X Plays"), Gesamtzeile
    ("📊 Gesamt · N Plays") NUR wenn mehr als ein Mitglied beteiligt ist -
    kein redundanter Gesamtwert bei genau einem Hörer."""
    lines = [f"   👤 {m['display_name']} · {format_plays(m['plays'])}" for m in members]
    if len(members) > 1:
        lines.append(f"   📊 Gesamt · {format_plays(total_plays)}")
    return lines


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

            date_range = format_date_range(stats["period_start"], stats["period_end"])
            lines = ["🎵 Top Songs Familie", date_range, ""]
            for idx, song in enumerate(stats["top_songs"][:5], start=1):
                lines.append(f"{format_rank(idx)} {song['title']}")
                lines.append(f"   {song['artists']}")
                lines.extend(_format_member_lines(song["members"], song["total_plays"]))
                lines.append("")

            lines.append(SEPARATOR)
            lines.append(f"📊 Familie gesamt · {format_plays(stats['total_plays'])}")
            await msg.edit_text("\n".join(lines))

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

            date_range = format_date_range(stats["period_start"], stats["period_end"])
            lines = ["🎤 Top Künstler Familie", date_range, ""]
            for idx, artist in enumerate(stats["top_artists"][:5], start=1):
                lines.append(f"{format_rank(idx)} {artist['artist']}")
                lines.extend(
                    _format_member_lines(artist["members"], artist["total_plays"])
                )
                lines.append("")

            lines.append(SEPARATOR)
            lines.append(f"📊 Familie gesamt · {format_plays(stats['total_plays'])}")
            await msg.edit_text("\n".join(lines))

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

            total = stats["total_plays"]
            ranked = sorted(
                stats["per_member"].values(),
                key=lambda m: (-m["plays"], m["display_name"]),
            )
            date_range = format_date_range(stats["period_start"], stats["period_end"])
            lines = ["👥 Statistik pro Person", date_range, ""]
            for idx, m in enumerate(ranked, start=1):
                lines.append(f"{format_rank(idx)} {m['display_name']}")
                lines.append(
                    f"   {format_plays(m['plays'])} · {_format_percentage(m['plays'], total)} %"
                )
                lines.append("")

            lines.append(SEPARATOR)
            lines.append(f"📊 Familie gesamt · {format_plays(total)}")
            await msg.edit_text("\n".join(lines))

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
                f"🏆 Musik-Champion\n\n{display_name} · {format_plays(plays)}"
            )

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(f"❌ Fehler in handle_family_champion: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # ⏰ Hör-Aktivität
    # ─────────────────────────────────────────────────────────────

    async def handle_family_listening_times(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        family_id = self._resolve_family_id(update)
        if family_id is None:
            await self._deny_access(update)
            return

        _, msg = await self._send_processing_message(update, "Lade Hör-Aktivität")
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
            date_range = format_date_range(result["period_start"], result["period_end"])

            lines = [
                "⏰ Hör-Aktivität Familie",
                date_range,
                "",
                f"Meistgehörte Stunde · {peak_hour[0]}:00 Uhr · {format_plays(peak_hour[1])}",
                f"Meistgehörter Wochentag · {peak_weekday} · {format_plays(peak_weekday_count)}",
                "",
                SEPARATOR,
                f"📊 Familie gesamt · {format_plays(result['total_plays'])}",
            ]
            await msg.edit_text("\n".join(lines))

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

            lines = ["📈 Monatsentwicklung Familie", ""]
            for month_key in trend["months"]:
                _year_str, month_str = month_key.split("-")
                month_name = GERMAN_MONTHS[int(month_str) - 1]
                plays = trend["plays_by_month"][month_key]
                lines.append(f"{month_name.ljust(11)}· {format_plays(plays)}")
            await msg.edit_text("\n".join(lines))

        except Exception as e:
            await msg.edit_text(f"{EMOJI['error']} Fehler: {e}")
            self.logger.error(
                f"❌ Fehler in handle_family_monthly_trend: {e}", exc_info=True
            )
