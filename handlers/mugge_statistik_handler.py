from config import get_config
# /yt_music_bot/handlers/statistik_handler.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from typing import Callable
from telegram.constants import ParseMode
from typing import Any, Dict, List, Optional
import time
from datetime import datetime, timedelta
from html import escape as html_escape
import json  # NEU
from pathlib import Path  # NEU

from services.statistik_service import StatistikService
from services.statistik.statistics_calculator import GERMAN_MONTHS as _GERMAN_MONTHS
from logger import get_module_logger
from helfer.markdown_helfer import escape_md_v2
from emoji import EMOJI
from config import Config  # WICHTIG
from handlers.statistik_format_helpers import (
    RANK_MEDALS as _RANK_MEDALS,
    format_plays as _format_plays_helper,
    format_rank as _format_rank_helper,
    format_date_range as _format_date_range_helper,
)

# Statistics UX & Architecture (v Final), Abschnitt 17: _GERMAN_MONTHS
# ist jetzt ein Re-Export der kanonischen Quelle in
# services/statistik/statistics_calculator.py (dort auch von
# generate_year_stats() für monthly_plays/highlights verwendet) - EINE
# Quelle statt einer zweiten, potenziell abweichenden Konstante.
#
# MASTER PHASE B (Family Statistics, Abschnitt 26.1): _format_plays()/
# _format_rank()/_format_date_range()/_RANK_MEDALS sind jetzt nach
# handlers/statistik_format_helpers.py extrahiert und werden von dort
# importiert - die Instanzmethoden unten bleiben als dünne Delegatoren
# bestehen (bestehende Call-Sites/Tests in dieser Klasse bleiben
# unverändert lauffähig), handlers/family_stats_handler.py importiert
# direkt aus dem geteilten Modul.


class StatistikHandler:
    """
    Telegram Handler für Musik-Statistiken.

    📊 Hauptfunktionen:
    - 📅 Wochen-, Monats- und Jahresrückblick (Kalenderperioden)
    - 🎵 Top Songs und Künstler
    - 🔍 Zuletzt gespielter Song

    🎯 Features:
    - ✨ Emoji-basierte Visualisierung
    - 📱 Plain Text Formatierung
    - ⚡ Asynchrone Verarbeitung
    - 👤 Benutzerspezifisches Mapping (TelegramID -> NavidromeUser)

    Statistics Menu UX & Output Optimization: PNG-Chart-Generierung
    entfernt (reiner Text-Output, siehe
    docs/MusicBot_TELEGRAM_MENU_SYSTEM.md Abschnitt 10).

    KEIN error_handler integriert (bewusste, geschlossene Entscheidung,
    siehe docs/FINDINGS_INDEX.md) - anders als die übrigen Telegram-
    Handler dieses Projekts. Grund: jeder except-Block hier editiert die
    separat gesendete "läuft..."-Zwischennachricht (self.msg.edit_text(),
    aus _send_processing_message()), NICHT die callback_query-Nachricht
    selbst. Ein mechanisch verdrahteter error_handler (der wie bei den
    übrigen Handlern die callback_query-Nachricht editieren würde) würde
    hier die falsche Nachricht treffen und die "läuft..."-Nachricht
    dauerhaft hängen lassen - eine echte UX-Regression, kein
    kosmetisches Detail. Die bestehenden lokalen except-Blöcke sind
    bereits funktional äquivalent zu dem, was ein error_handler leisten
    würde (Nutzer bekommt die exakt richtige Nachricht editiert), nur
    lokal statt über die geteilte Komponente - keine offene Lücke.
    """

    def __init__(self, user_mgmt_handler=None):
        """
        Initialisiert den StatistikHandler mit User-Management-Integration

        Args:
            user_mgmt_handler: Referenz zum UserManagementHandler (optional)
        """
        self.logger = get_module_logger("StatistikHandler")
        self.statistik_service = StatistikService()

        # NEU: Referenz zum UserManagementHandler
        self.user_mgmt_handler = user_mgmt_handler

        # NEU: Pfad zur User-Datenbank (als Fallback)
        try:
            base_data_path = Config.BASE_DIR / "data" / "user_data.json"
            root_data_path = Path("data/user_data.json")

            if base_data_path.exists():
                self.user_data_file = base_data_path
            elif root_data_path.exists():
                self.user_data_file = root_data_path
                self.logger.warning(
                    f"user_data.json nicht in {base_data_path} gefunden. "
                    f"Verwende Fallback-Pfad: {root_data_path}"
                )
            else:
                self.logger.error(f"Benutzerdatenbank (user_data.json) nicht gefunden.")
                self.user_data_file = None
        except Exception as e:
            self.logger.error(f"Fehler beim Definieren des user_data.json Pfades: {e}")
            self.user_data_file = None

        self.logger.info(f"{EMOJI['statistics']} 📊 StatistikHandler initialisiert")

    def set_user_mgmt_handler(self, handler):
        """
        Setzt die Referenz zum UserManagementHandler

        Args:
            handler: UserManagementHandler-Instanz
        """
        self.user_mgmt_handler = handler
        self.logger.info("✅ UserManagementHandler verknüpft mit StatistikHandler")

    def _get_navidrome_user_for_request(self, update: Update) -> str:
        """
        Ermittelt den Navidrome-Benutzer basierend auf der Telegram-ID

        🎯 PRIORITÄT:
        1. Versuche UserManagementHandler-Cache
        2. Fallback: Lade user_data.json direkt
        3. Fallback: get_config().NAVIDROME_USER

        Args:
            update: Telegram Update-Objekt

        Returns:
            str: Navidrome-Benutzername
        """
        telegram_id = update.effective_user.id
        telegram_id_str = str(telegram_id)

        # === METHODE 1: UserManagementHandler (bevorzugt) ===
        if self.user_mgmt_handler:
            nav_user = self.user_mgmt_handler.get_navidrome_user(telegram_id)

            if nav_user:
                self.logger.debug(
                    f"✅ User {telegram_id} → Navidrome-User '{nav_user}' "
                    "(via UserManagementHandler)"
                )
                return nav_user

        # === METHODE 2: Direktes Laden (Fallback) ===
        if self.user_data_file and self.user_data_file.exists():
            try:
                with open(self.user_data_file, "r", encoding="utf-8") as f:
                    user_data = json.load(f)

                user_info = user_data.get(telegram_id_str)
                if user_info and user_info.get("navidrome_user"):
                    nav_user = user_info["navidrome_user"]

                    if nav_user and nav_user.strip():
                        self.logger.debug(
                            f"✅ User {telegram_id} → Navidrome-User '{nav_user}' "
                            "(via direktes Laden)"
                        )
                        return nav_user
            except Exception as e:
                self.logger.error(f"❌ Fehler beim Laden von user_data.json: {e}")

        # === METHODE 3: Config-Fallback ===
        fallback_user = get_config().NAVIDROME_USER
        self.logger.warning(
            f"⚠️ Kein 'navidrome_user' für Telegram-ID {telegram_id} gefunden. "
            f"Verwende Fallback: {fallback_user}"
        )
        return fallback_user

    def _escape_text(self, text: str) -> str:
        """Hilfsfunktion zum Escapen von Text"""
        return str(text) if text else ""

    def _truncate(self, text: str, max_len: int = 45) -> str:
        """
        Statistics Menu UX & Output Optimization: kappt sehr lange Song-/
        Künstler-/Albumnamen (z. B. lange Feature-Ketten oder
        Sonderzeichen-Titel) auf `max_len` Zeichen + „…" - verhindert,
        dass eine einzelne überlange Zeile den optischen Rhythmus einer
        Top-10-Liste in Telegram (schmale mobile Ansicht) sprengt. Reine
        Kürzung, kein Escaping (siehe _escape_text()-Docstring: diese
        Klasse verwendet durchgehend Plain-Text-Formatierung).
        """
        text = self._escape_text(text)
        if len(text) <= max_len:
            return text
        return text[: max_len - 1].rstrip() + "…"

    def _format_period_label(self, period: str, period_start) -> str:
        """
        Statistics Menu UX & Architecture Optimization: einheitliches
        "<Bezeichnung> · <Kalenderbezug>"-Label - EINZIGER Konsument ist
        seit der Statistics UX & Architecture (v Final)-Phase
        handle_music_timeline() (Heute/Diese Woche/Diesen Monat, siehe
        deren render_period()). Ersetzt dort weiterhin die vorherigen,
        irreführenden Rolling-Window-Labels.

        Der "year"-Zweig entfiel (Abschnitt 13 des Master-Prompts: alle
        Consumer vor Änderung prüfen) - Woche-/Monatsrückblick verwenden
        seither _format_date_range() (echter Zeitraum statt Einzeldatum,
        siehe Abschnitt 12), Jahresrückblick hat einen eigenen
        Annual-Renderer mit eigenem Datumsbereich. Music Timeline hatte
        nie eine "year"-Periode und ist daher von dieser Reduktion nicht
        betroffen - keine Verhaltensänderung an Timeline (Abschnitt 30:
        "Keine Scope-Ausweitung").
        """
        if period == "today":
            return f"Heute · {period_start.strftime('%d.%m.%Y')}"
        if period == "week":
            return f"Diese Woche · {period_start.strftime('%d.%m.%Y')}"
        # "month"
        return f"Diesen Monat · {_GERMAN_MONTHS[period_start.month - 1]} {period_start.year}"

    def _format_plays(self, count: int) -> str:
        """Statistics UX & Architecture (v Final), Abschnitt 9: zentrale
        Play-Pluralisierung ("1 Play" / "2 Plays"). MASTER PHASE B,
        Abschnitt 26.1: dünner Delegator auf
        handlers/statistik_format_helpers.py (siehe Modul-Docstring
        oben) - Verhalten unverändert."""
        return _format_plays_helper(count)

    def _format_rank(self, position: int) -> str:
        """1-basierter Rang -> Medaille (1.-3. Platz) oder reine Zahl mit
        Punkt (4./5. Platz), siehe Abschnitt 8. Dünner Delegator, siehe
        _format_plays()."""
        return _format_rank_helper(position)

    def _format_date_range(self, period_start: datetime, period_end: datetime) -> str:
        """
        Statistics UX & Architecture (v Final), Abschnitt 12. Dünner
        Delegator auf handlers/statistik_format_helpers.py, siehe
        _format_plays()."""
        return _format_date_range_helper(period_start, period_end)

    def _format_report_age(self, completed_at_iso: str) -> str:
        """
        Formatiert das Alter eines Library-Health-Reports relativ zu jetzt
        (Phase 3, P1.1) — der Report ist eine Momentaufnahme vom letzten
        Scan, kein Live-Wert; ohne diesen Hinweis könnte eine veraltete
        Zahl für aktuell gehalten werden.
        """
        try:
            scanned_at = datetime.fromisoformat(completed_at_iso)
            now = (
                datetime.now(scanned_at.tzinfo)
                if scanned_at.tzinfo
                else datetime.now()
            )
            age = now - scanned_at
            seconds = age.total_seconds()
            if seconds < 0:
                relative = "gerade eben"
            elif seconds < 3600:
                relative = f"vor {int(seconds // 60)} Min."
            elif seconds < 86400:
                relative = f"vor {int(seconds // 3600)} Std."
            else:
                relative = f"vor {int(seconds // 86400)} Tagen"
            return f"{self._escape_text(completed_at_iso)} ({relative})"
        except (ValueError, TypeError):
            return self._escape_text(completed_at_iso)

    async def _send_processing_message(
        self, update: Update, action: str, nav_user: str
    ):
        """
        Sendet eine Verarbeitungsnachricht und gibt die Nachricht und das Ziel zurück

        Args:
            update: Telegram Update-Objekt
            action: Beschreibung der Aktion
            nav_user: Navidrome-Benutzername

        Returns:
            tuple: (reply_target, message)
        """
        reply_target = (
            update.callback_query.message if update.callback_query else update.message
        )
        if not reply_target:
            self.logger.error(f"❌ Keine Nachricht zum Antworten für {action}")
            return None, None

        msg = await reply_target.reply_text(
            f"{EMOJI['processing']} 🔄 {action} für '{self._escape_text(nav_user)}'..."
        )
        return reply_target, msg

    def _format_period_statistics(
        self, stats: Dict[str, Any], period_label: str, date_range: str, nav_user: str
    ) -> str:
        """
        Statistics UX & Architecture (v Final), Abschnitt 26: gemeinsamer
        Renderer für Wochen-/Monatsstatistik (identisches Layout, siehe
        Abschnitt 8) - reine Presentation, keine Business-Logik (Ranking/
        Aggregation kommt bereits fertig aus generate_stats()). `period_label`
        ist "Wochenstatistik"/"Monatsstatistik", `date_range` kommt aus
        _format_date_range(). Erwartet `stats["total_plays"] > 0` (der
        Empty-Zustand wird vom Aufrufer vorher separat behandelt).

        Song-Karten sind zweizeilig (Titel, dann eingerückt Artist(s) +
        Plays) mit einer Leerzeile zwischen den Karten; Künstler-Zeilen
        sind einzeilig ohne Leerzeilen dazwischen (Abschnitt 8). KEIN
        _truncate() auf Titel/Artist (Abschnitt 11/30 - Telegram darf
        normal umbrechen)."""
        esc = self._escape_text

        lines = [
            f"📊 {period_label} · {esc(nav_user)}",
            date_range,
            f"🎧 {self._format_plays(stats['total_plays'])} insgesamt",
            "",
            "🎵 Top 5 Songs",
        ]
        for idx, (title, artists, count) in enumerate(
            stats["top_songs_detailed"][:5], start=1
        ):
            lines.append(f"{self._format_rank(idx)} {esc(title)}")
            lines.append(f"   {esc(artists)} · {self._format_plays(count)}")
            lines.append("")

        lines.append("👑 Top 5 Künstler")
        for idx, (artist, count) in enumerate(
            stats["top_artists_split"][:5], start=1
        ):
            lines.append(f"{self._format_rank(idx)} {esc(artist)} · {self._format_plays(count)}")

        return "\n".join(lines)

    async def _handle_period_review(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        period: str,
        short_label: str,
        period_label: str,
    ):
        """
        Statistics UX & Architecture (v Final): gemeinsame Implementierung
        für Wochen-/Monatsrückblick (identisches Layout, siehe
        _format_period_statistics()). `period` ist "week"/"month" -
        Jahresrückblick hat seit dieser Phase eine eigene Implementierung
        (handle_year_review(), eigener Annual-Renderer mit KPIs/Highlight/
        Monatsdiagramm, siehe Master-Prompt Abschnitt 14/22/26).

        `generate_stats()` liefert bei 0 Plays in der Periode (aber
        vorhandenem Account-Verlauf) ein gültiges Dict statt `None` -
        ermöglicht eine periodenbezogene "noch keine Wiedergaben"-Meldung
        statt einer generischen Fehlermeldung.
        """
        self.logger.info(f"{EMOJI['calendar']} {short_label} angefragt")

        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, f"Erstelle {short_label}", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            stats = self.statistik_service.generate_stats(
                period=period, navidrome_username=nav_user
            )

            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für {short_label} (User: {nav_user})"
                )
                return

            date_range = self._format_date_range(
                stats["period_start"], stats["period_end"]
            )

            if stats["total_plays"] == 0:
                esc = self._escape_text
                await msg.edit_text(
                    f"📊 {period_label} · {esc(nav_user)}\n{date_range}\n\n"
                    f"Noch keine Wiedergaben in diesem Zeitraum."
                )
                self.logger.info(
                    f"ℹ️ {short_label}: leere Periode (User: {nav_user})"
                )
                return

            text = self._format_period_statistics(
                stats, period_label, date_range, nav_user
            )
            await msg.edit_text(text)
            self.logger.info(f"✅ {short_label} erfolgreich (User: {nav_user})")

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"❌ Fehler bei {short_label}: {str(e)}", exc_info=True
            )

    async def handle_week_review(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Behandelt die Anfrage für "Diese Woche" (Statistics Menu UX &
        Architecture Optimization, neu). Bewusst eigenständig neben
        Music Timeline: Timeline zeigt eine verdichtete Übersicht
        (jeweils EIN Top-Artist/meistgehörter Track), dieser Rückblick
        liefert wie Monat/Jahr die vollständige Top-10-Liste für exakt
        eine Periode - kein redundanter zweiter Wochen-Handler, sondern
        eine andere Darstellungstiefe (Master-Prompt Phase 14, Option A)."""
        await self._handle_period_review(
            update, context, "week", "Wochenrückblick", "Wochenstatistik"
        )

    async def handle_month_review(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Behandelt die Anfrage für einen Monatsrückblick"""
        await self._handle_period_review(
            update, context, "month", "Monatsrückblick", "Monatsstatistik"
        )

    async def handle_library_overview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Zeigt die Library-Zusammensetzung (Tracks/Albums/Artists/Genre-
        Verteilung/Health-Score) aus dem zuletzt erzeugten Library-Health-
        Report (Phase 3, P1.1). Anders als die übrigen Methoden dieser
        Klasse: keine Play-History, kein Navidrome-User-Bezug — der
        Health-Report ist library-weit, nicht pro Benutzer.
        """
        self.logger.info(f"{EMOJI['statistics']} 📚 Library-Übersicht angefragt")

        reply_target = (
            update.callback_query.message if update.callback_query else update.message
        )
        if not reply_target:
            self.logger.error("❌ Keine Nachricht zum Antworten für Library-Übersicht")
            return

        msg = await reply_target.reply_text(
            f"{EMOJI['processing']} 🔄 Lade Library-Übersicht..."
        )

        report_path = Config.DATA_DIR / "library_health_report.json"

        try:
            if not report_path.exists():
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Noch kein Library-Health-Report vorhanden.\n"
                    f"Zuerst einen Scan starten (scripts/library_health_check.py)."
                )
                return

            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)

            stats = report["statistics"]
            health = report["health"]
            esc = self._escape_text

            genre_dist = stats.get("genre_distribution", {})
            total_genre_hits = sum(genre_dist.values())
            top_genres = sorted(
                genre_dist.items(), key=lambda kv: kv[1], reverse=True
            )[:8]
            genre_lines = [
                f"  {esc(name)}: {esc(count)} "
                f"({(count / total_genre_hits * 100) if total_genre_hits else 0:.0f}%)"
                for name, count in top_genres
            ]

            lines = [
                f"{EMOJI['statistics']} Music Library Übersicht",
                f"Stand: {self._format_report_age(report['scan']['completed_at'])}",
                "",
                f"Tracks:  {esc(stats['total_files'])}",
                f"Albums:  {esc(stats['total_albums'])}",
                f"Artists: {esc(stats['total_artists'])}",
                "",
                f"Health-Score: {esc(health.get('score'))} ({esc(health.get('status'))})",
                "",
                "Genres:" if genre_lines else "Genres: keine Daten",
                *genre_lines,
            ]

            await msg.edit_text("\n".join(lines))
            self.logger.info("✅ Library-Übersicht erfolgreich gesendet")

        except (json.JSONDecodeError, KeyError, OSError) as e:
            await msg.edit_text(
                f"{EMOJI['warning']} ⚠️ Health-Report ist unlesbar/unvollständig "
                f"({self._escape_text(str(e))}). Neuen Scan starten."
            )
            self.logger.error(
                f"❌ Health-Report unlesbar in handle_library_overview: {e}",
                exc_info=True,
            )
        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"❌ Fehler in handle_library_overview: {str(e)}", exc_info=True
            )

    def _format_monthly_chart(self, monthly_plays: List[Any]) -> str:
        """
        Statistics UX & Architecture (v Final), Abschnitt 22/22.1: Rohdaten
        (`monthly_plays`, aus generate_year_stats()) -> monospace
        Balkendiagramm. Feste Spaltenbreiten (Monatsname 10, Balken 16,
        Plays 5, je 1 Leerzeichen dazwischen) - passt ohne horizontales
        Scrollen auf gängige Mobilgeräte, volle deutsche Monatsnamen
        (längster "September" = 9 Zeichen) passen ohne Kürzung. Stärkster
        Monat = 16 gefüllte Zeichen, alle anderen proportional dazu
        (mindestens 1 Zeichen bei `plays > 0`), keine Division durch 0 bei
        durchgehend 0 Plays.
        """
        max_plays = max((plays for _, plays in monthly_plays), default=0)
        lines = []
        for name, plays in monthly_plays:
            if max_plays > 0 and plays > 0:
                filled = max(1, round(plays / max_plays * 16))
            else:
                filled = 0
            bar = "█" * filled + "░" * (16 - filled)
            lines.append(f"{html_escape(name):<10} {bar:<16} {plays:>5}")
        return "\n".join(lines)

    def _render_annual_statistics(self, stats: Dict[str, Any], nav_user: str) -> str:
        """
        Statistics UX & Architecture (v Final), Abschnitt 24/26: eigener
        Annual-Renderer (nicht der Wochen-/Monats-Renderer) - zusätzliche
        KPIs/Highlight/Monatsdiagramm, dieselbe visuelle Sprache
        (Header/Abstände/Rang-Symbole/Play-Formatter). Top-5-Songs/-
        Künstler folgen hier bewusst der einzeiligen Zieldarstellung aus
        Abschnitt 24 (nicht dem zweizeiligen Song-Layout aus Abschnitt 8) -
        bei bereits umfangreichem Jahres-Text (KPIs+Highlight+12-Zeilen-
        Diagramm) hält das die Nachricht kompakt; die Kollisionssicherheit
        der zugrunde liegenden Zählung (_identity_key()) bleibt davon
        unberührt.

        HTML-Escaping (Abschnitt 23): dynamische Werte (Nutzer-/Song-/
        Künstlernamen) werden über `html.escape()` escaped, da diese
        Nachricht mit `parse_mode=ParseMode.HTML` gesendet wird (für den
        `<code>`-Monatsblock) - `_escape_text()` escaped nichts (siehe
        dessen Docstring) und wäre hier nicht ausreichend.
        """
        esc = html_escape
        date_range = self._format_date_range(stats["period_start"], stats["period_end"])
        highlight = stats["highlights"]["strongest_month"]

        lines = [
            f"📊 Jahresstatistik · {esc(nav_user)}",
            date_range,
            "",
            f"🎧 {self._format_plays(stats['total_plays'])}",
            f"🎵 {stats['total_songs']} Songs",
            f"👑 {stats['total_artists']} Künstler",
            f"💿 {stats['total_albums']} Alben",
            "",
            "✨ Jahres-Highlight",
            "",
            "🔥 Stärkster Monat",
        ]
        if highlight["delta_pct"] is not None:
            lines.append(
                f"{esc(highlight['name'])} · {highlight['delta_pct']} % "
                "über Monatsdurchschnitt"
            )
        else:
            lines.append(esc(highlight["name"]))

        lines += [
            "",
            "📈 Plays pro Monat",
            "",
            "<code>",
            self._format_monthly_chart(stats["monthly_plays"]),
            "</code>",
            "",
            "🎵 Top 5 Songs",
        ]
        for idx, (title, _artists, count) in enumerate(
            stats["top_songs_detailed"][:5], start=1
        ):
            lines.append(
                f"{self._format_rank(idx)} {esc(title)} · {self._format_plays(count)}"
            )

        lines.append("")
        lines.append("👑 Top 5 Künstler")
        for idx, (artist, count) in enumerate(stats["top_artists_split"][:5], start=1):
            lines.append(
                f"{self._format_rank(idx)} {esc(artist)} · {self._format_plays(count)}"
            )

        return "\n".join(lines)

    async def handle_year_review(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Behandelt die Anfrage für einen Jahresrückblick. Statistics UX &
        Architecture (v Final): eigenständige Implementierung (nicht mehr
        über _handle_period_review(), das seit dieser Phase nur noch
        Woche/Monat bedient) - eigener Datensatz
        (generate_year_stats()) und eigener Renderer
        (_render_annual_statistics(), inkl. `<code>`-Monatsdiagramm,
        daher `parse_mode=ParseMode.HTML` statt der sonst in dieser
        Klasse durchgängigen Plain-Text-Formatierung)."""
        self.logger.info(f"{EMOJI['calendar']} Jahresrückblick angefragt")

        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Erstelle Jahresrückblick", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            stats = self.statistik_service.generate_year_stats(
                navidrome_username=nav_user
            )

            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für Jahresrückblick (User: {nav_user})"
                )
                return

            if stats["total_plays"] == 0:
                esc = self._escape_text
                date_range = self._format_date_range(
                    stats["period_start"], stats["period_end"]
                )
                await msg.edit_text(
                    f"📊 Jahresstatistik · {esc(nav_user)}\n{date_range}\n\n"
                    f"Noch keine Wiedergaben in diesem Jahr."
                )
                self.logger.info(
                    f"ℹ️ Jahresrückblick: leeres Jahr (User: {nav_user})"
                )
                return

            text = self._render_annual_statistics(stats, nav_user)
            await msg.edit_text(text, parse_mode=ParseMode.HTML)
            self.logger.info(f"✅ Jahresrückblick erfolgreich (User: {nav_user})")

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"❌ Fehler bei Jahresrückblick: {str(e)}", exc_info=True
            )

    async def handle_top_songs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        """Behandelt die Anfrage für Top Songs"""
        self.logger.info(
            f"{EMOJI['topsongs']} 🎵 Top Songs angefragt für Periode: {period}"
        )

        # 🔑 KERNÄNDERUNG: User-Mapping verwenden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Lade Top Songs", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            # Statistiken generieren
            stats = self.statistik_service.generate_stats(
                period=period, navidrome_username=nav_user
            )
            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Song-Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Song-Daten (User: {nav_user}, Periode: {period})"
                )
                return

            header = f"Top Songs ({self._escape_text(period.title())}) für {self._escape_text(nav_user)}"

            if stats["total_plays"] == 0:
                await msg.edit_text(
                    f"{EMOJI['topsongs']} {header}:\n\nNoch keine Wiedergaben in diesem Zeitraum."
                )
                self.logger.info(f"ℹ️ Top Songs: leere Periode (User: {nav_user})")
                return

            # MASTER FIX (Personal Statistics Rankings Closure): nutzt
            # jetzt top_songs_detailed (Titel + vollständiger, unveränderter
            # Artist-String, kollisionssicher über _identity_key()) statt
            # des alten kombinierten top_songs-Strings - und _format_rank()/
            # _format_plays() statt der alten "N. X (Y Plays)"-Formatierung.
            # KEIN _truncate() mehr (Abschnitt 2 des Master-Prompts - Telegram
            # darf normal umbrechen, identisch zur bereits etablierten
            # Wochen-/Monatsstatistik-UX, siehe _format_period_statistics()).
            lines = [f"{EMOJI['topsongs']} {header}", ""]
            for idx, (title, artists, count) in enumerate(
                stats["top_songs_detailed"], start=1
            ):
                lines.append(f"{self._format_rank(idx)} {self._escape_text(title)}")
                lines.append(
                    f"   {self._escape_text(artists)} · {self._format_plays(count)}"
                )
                lines.append("")

            lines.append(
                f"{EMOJI['statistics']} Gesamt Plays: {self._format_plays(stats['total_plays'])}"
            )
            response = "\n".join(lines)

            await msg.edit_text(response)
            self.logger.info(
                f"{EMOJI['success']} ✅ Top Songs Liste erstellt "
                f"({len(stats['top_songs_detailed'])} Einträge, User: {nav_user})"
            )

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"{EMOJI['error']} ❌ Fehler in handle_top_songs: {e}", exc_info=True
            )

    async def handle_top_artists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "month"
    ):
        """Behandelt die Anfrage für Top Künstler"""
        self.logger.info(
            f"{EMOJI['topartists']} 👑 Top Künstler angefragt für Periode: {period}"
        )

        # 🔑 KERNÄNDERUNG: User-Mapping verwenden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Lade Top Künstler", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            # Statistiken generieren
            stats = self.statistik_service.generate_stats(
                period=period, navidrome_username=nav_user
            )
            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Künstler-Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Künstler-Daten (User: {nav_user}, Periode: {period})"
                )
                return

            header = f"Top Künstler ({self._escape_text(period.title())}) für {self._escape_text(nav_user)}"

            if stats["total_plays"] == 0:
                await msg.edit_text(
                    f"{EMOJI['topartists']} {header}:\n\nNoch keine Wiedergaben in diesem Zeitraum."
                )
                self.logger.info(f"ℹ️ Top Künstler: leere Periode (User: {nav_user})")
                return

            # MASTER FIX (Personal Statistics Rankings Closure): nutzt
            # jetzt top_artists_split (StatisticsCalculator._split_artists()
            # bereits VOR der Aggregation angewendet, siehe dessen Docstring)
            # statt des alten kombinierten top_artists-Strings - Multi-
            # Artist-Einträge wie "makko & toobrokeforfiji" erscheinen jetzt
            # als getrennte Artist-Identitäten. KEIN _truncate() mehr
            # (Abschnitt 2/4 des Master-Prompts).
            lines = [f"{EMOJI['topartists']} {header}", ""]
            for idx, (artist, count) in enumerate(stats["top_artists_split"], start=1):
                lines.append(
                    f"{self._format_rank(idx)} {self._escape_text(artist)} · "
                    f"{self._format_plays(count)}"
                )

            lines.append("")
            lines.append(
                f"{EMOJI['statistics']} Gesamt Plays: {self._format_plays(stats['total_plays'])}"
            )
            response = "\n".join(lines)

            await msg.edit_text(response)
            self.logger.info(
                f"{EMOJI['success']} ✅ Top Künstler Liste erstellt "
                f"({len(stats['top_artists_split'])} Einträge, User: {nav_user})"
            )

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"{EMOJI['error']} ❌ Fehler in handle_top_artists: {str(e)}",
                exc_info=True,
            )

    async def handle_last_played(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Behandelt die Anfrage für den zuletzt gespielten Song"""
        self.logger.info(f"{EMOJI['lastplayed']} 🔍 Letzter Song angefragt")

        # 🔑 KERNÄNDERUNG: User-Mapping verwenden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Suche letzten Song", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            # Letzten Song aus History abrufen
            last_song = self.statistik_service.get_last_played_song(
                navidrome_username=nav_user
            )

            if not last_song:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Songs in der History für '{self._escape_text(nav_user)}' gefunden."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Songs in der History gefunden (User: {nav_user})"
                )
                return

            def esc(t):
                return self._escape_text(t or "")

            # Zeitstempel formatieren
            timestamp_str = esc(last_song.get("timestamp"))
            try:
                dt_object = datetime.fromisoformat(last_song.get("timestamp"))
                timestamp_str = esc(dt_object.strftime("%d.%m.%Y, %H:%M:%S"))
            except (ValueError, TypeError):
                pass  # Behalte den ISO-String, wenn die Formatierung fehlschlägt

            response = (
                f"{EMOJI['lastplayed']} Zuletzt gespielt (von {esc(nav_user)}):\n\n"
                f"🎵 Titel: {esc(last_song.get('title'))}\n"
                f"🎤 Künstler: {esc(last_song.get('artist'))}\n"
                f"💿 Album: {esc(last_song.get('album'))}\n"
                f"⏱️ Zeitpunkt: {timestamp_str}"
            )

            await msg.edit_text(response)
            self.logger.info(
                f"{EMOJI['success']} ✅ Letzter Song gefunden (User: {nav_user}): {last_song.get('artist')} - {last_song.get('title')}"
            )

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"{EMOJI['error']} ❌ Fehler in handle_last_played: {str(e)}",
                exc_info=True,
            )

    def _format_duration(self, seconds: Any) -> str:
        """Formatiert Sekunden als 'Xh Ym' (bzw. nur 'Ym' unter einer Stunde)."""
        try:
            total_minutes = int(float(seconds or 0)) // 60
        except (TypeError, ValueError):
            total_minutes = 0
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"

    _TIMELINE_SEPARATOR = "────────────────────"
    _TIMELINE_EMPTY_LABELS = {
        "today": "heute",
        "week": "diese Woche",
        "month": "diesen Monat",
    }

    def _format_timeline_period_label(self, period_key: str, data: Dict[str, Any]) -> str:
        """
        Music Timeline Consistency & UX, Abschnitt 3: "Heute"/"Diesen
        Monat" verwenden weiterhin unverändert _format_period_label()
        (einziger Consumer dieser Methode, siehe deren Docstring). "Diese
        Woche" zeigt dagegen einen echten Datumsbereich
        (_format_date_range(), bereits aus der Woche-/Monatsstatistik-
        Phase vorhanden) statt eines Einzeldatums - ein einzelnes
        Wochen-Datum wäre hier weniger aussagekräftig als in den
        Rückblicken, da Timeline drei Perioden nebeneinander zeigt.
        """
        if period_key == "week":
            date_range = self._format_date_range(
                data["period_start"], data["period_end"]
            )
            return f"Diese Woche · {date_range}"
        return self._format_period_label(period_key, data["period_start"])

    def _render_timeline_period(self, period_key: str, data: Dict[str, Any]) -> List[str]:
        """
        Music Timeline Consistency & UX, Abschnitt 3/4/5: dieselbe
        visuelle Sprache wie Woche-/Monats-/Jahresstatistik -
        `_format_plays()` statt `(Nx)`/`(N Plays)`, konsistente Emojis
        (🎤💿🔁🆕), kein `_truncate()` (Telegram darf normal umbrechen,
        analog zum Rückblick-Layout), keine `0m`-Zeile bei fehlender
        Dauer, sauberer Empty-State statt einer Null-Sektion.
        """
        esc = self._escape_text
        block = [
            self._format_timeline_period_label(period_key, data),
            self._TIMELINE_SEPARATOR,
        ]

        if data["track_count"] == 0:
            block.append(
                f"Keine Wiedergaben {self._TIMELINE_EMPTY_LABELS[period_key]}"
            )
            return block

        block.append(f"🎧 {data['track_count']} Tracks")
        if data["listening_seconds"] > 0:
            block.append(f"⏱️ {self._format_duration(data['listening_seconds'])}")
        if data["top_artist"]:
            artist, plays = data["top_artist"]
            block.append(f"🎤 Top Artist: {esc(artist)} · {self._format_plays(plays)}")
        if data["top_album"]:
            album, plays = data["top_album"]
            block.append(f"💿 Top Album: {esc(album)} · {self._format_plays(plays)}")
        if data["most_replayed_track"]:
            title, plays = data["most_replayed_track"]
            block.append(f"🔁 Meistgehört: {esc(title)} · {self._format_plays(plays)}")
        block.append(f"🆕 Neue Tracks: {data['new_track_count']}")
        return block

    async def handle_music_timeline(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Behandelt die Anfrage für die Music-Timeline-Übersicht
        (Heute / Diese Woche / Diesen Monat).

        Music Timeline Consistency & UX: Layout überarbeitet, damit
        Timeline dieselbe visuelle Sprache wie Woche-/Monats-/
        Jahresstatistik spricht (siehe _render_timeline_period()) -
        insbesondere zeigt "Top Artist" jetzt garantiert dieselbe Zahl
        wie der jeweilige Period-Rückblick (Artist-Split-Fix in
        StatisticsCalculator.generate_timeline_stats(), siehe deren
        Docstring), statt wie zuvor einen unsplitteten Combo-String zu
        zählen.

        Feature-Basis: History.txt ("Music Timeline"). Der dort skizzierte
        Genre-Zeitverlauf ist NICHT enthalten, da das Datenmodell aktuell
        kein "genre"-Feld im Wiedergabeverlauf erfasst (siehe
        StatisticsCalculator.generate_timeline_stats).
        """
        self.logger.info(f"{EMOJI['chart']} 📅 Music Timeline angefragt")

        # 🔑 Gleiche User-Mapping-Logik wie alle übrigen Handler-Methoden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Erstelle Music Timeline", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            timeline = self.statistik_service.generate_timeline_stats(
                navidrome_username=nav_user
            )

            if not timeline:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Timeline-Daten (User: {nav_user})"
                )
                return

            periods = timeline["periods"]
            lines = [f"📅 Deine Musik · {self._escape_text(nav_user)}", ""]
            lines += self._render_timeline_period("today", periods["today"])
            lines.append("")
            lines += self._render_timeline_period("week", periods["week"])
            lines.append("")
            lines += self._render_timeline_period("month", periods["month"])

            await msg.edit_text("\n".join(lines))
            self.logger.info(
                f"{EMOJI['success']} ✅ Music Timeline erstellt (User: {nav_user})"
            )

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"{EMOJI['error']} ❌ Fehler in handle_music_timeline: {str(e)}",
                exc_info=True,
            )
