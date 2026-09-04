from config import get_config
# /yt_music_bot/handlers/statistik_handler.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from typing import Callable
from telegram.constants import ParseMode
from typing import Any, Dict, List, Optional
import asyncio
import time
from datetime import datetime
import json  # NEU
from pathlib import Path  # NEU

from services.statistik_service import StatistikService
from logger import get_module_logger
from helfer.markdown_helfer import escape_md_v2
from emoji import EMOJI
from config import Config  # WICHTIG


class StatistikHandler:
    """
    Telegram Handler für Musik-Statistiken.

    📊 Hauptfunktionen:
    - 📅 Monats- und Jahresrückblick
    - 🎵 Top Songs und Künstler
    - 🔍 Zuletzt gespielter Song
    - 📈 Diagramm-Generierung

    🎯 Features:
    - ✨ Emoji-basierte Visualisierung
    - 📱 Plain Text Formatierung
    - 🖼️ Automatische Diagramm-Erstellung
    - ⚡ Asynchrone Verarbeitung
    - 👤 NEU: Benutzerspezifisches Mapping (TelegramID -> NavidromeUser)

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

    async def handle_month_review(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Behandelt die Anfrage für einen Monatsrückblick"""
        self.logger.info(f"{EMOJI['calendar']} 📅 Monatsrückblick angefragt")

        # 🔑 KERNÄNDERUNG: User-Mapping verwenden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Erstelle Monatsrückblick", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            # Statistiken mit Benutzername generieren
            stats = self.statistik_service.generate_stats(
                period="month", navidrome_username=nav_user
            )

            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                return

            esc = self._escape_text

            top_songs = [
                f"{esc(i+1)}. {esc(t)} ({esc(c)} Plays)"
                for i, (t, c) in enumerate(stats["top_songs"])
            ]
            top_artists = [
                f"{esc(i+1)}. {esc(a)} ({esc(c)} Plays)"
                for i, (a, c) in enumerate(stats["top_artists"])
            ]
            top_albums = [
                f"{esc(i+1)}. {esc(a)} ({esc(c)} Plays)"
                for i, (a, c) in enumerate(stats["top_albums"])
            ]

            lines = [
                f"{EMOJI['calendar']} Monatsrückblick (30 Tage) für {esc(nav_user)}:",
                f"{EMOJI['statistics']} Gesamt Plays: {esc(stats['total_plays'])}",
                "",
                f"{EMOJI['trophy']} Top Songs:",
                *top_songs,
                "",
                f"{EMOJI['trophy']} Top Künstler:",
                *top_artists,
                "",
                f"{EMOJI['trophy']} Top Alben:",
                *top_albums,
            ]

            await msg.edit_text("\n".join(lines))

            # Diagramme generieren
            song_chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "songs"
            )
            artist_chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "artists"
            )

            if song_chart_path and song_chart_path.exists():
                with open(song_chart_path, "rb") as f1:
                    await reply_target.reply_photo(
                        photo=f1,
                        caption=f"{EMOJI['topsongs']} Top Songs des Monats ({esc(nav_user)})",
                    )

            if artist_chart_path and artist_chart_path.exists():
                with open(artist_chart_path, "rb") as f2:
                    await reply_target.reply_photo(
                        photo=f2,
                        caption=f"{EMOJI['topartists']} Top Künstler des Monats ({esc(nav_user)})",
                    )

            self.logger.info(f"✅ Monatsrückblick erfolgreich (User: {nav_user})")

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"❌ Fehler in handle_month_review: {str(e)}", exc_info=True
            )

    async def handle_year_review(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Behandelt die Anfrage für einen Jahresrückblick"""
        self.logger.info(f"{EMOJI['yearreview']} 📅 Jahresrückblick angefragt")

        # 🔑 KERNÄNDERUNG: User-Mapping verwenden
        nav_user = self._get_navidrome_user_for_request(update)
        reply_target, msg = await self._send_processing_message(
            update, "Erstelle Jahresrückblick", nav_user
        )

        if not reply_target or not msg:
            return

        try:
            # Statistiken für Jahr generieren
            stats = self.statistik_service.generate_stats(
                period="year", navidrome_username=nav_user
            )
            if not stats:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Daten für Jahresrückblick (User: {nav_user})"
                )
                return

            esc = self._escape_text

            top_songs = [
                f"{esc(i+1)}. {esc(t)} ({esc(c)} Plays)"
                for i, (t, c) in enumerate(stats["top_songs"])
            ]
            top_artists = [
                f"{esc(i+1)}. {esc(a)} ({esc(c)} Plays)"
                for i, (a, c) in enumerate(stats["top_artists"])
            ]
            top_albums = [
                f"{esc(i+1)}. {esc(a)} ({esc(c)} Plays)"
                for i, (a, c) in enumerate(stats["top_albums"])
            ]

            lines = [
                f"{EMOJI['yearreview']} Jahresrückblick (365 Tage) für {esc(nav_user)}:",
                f"{EMOJI['statistics']} Gesamt Plays: {esc(stats['total_plays'])}",
                "",
                f"{EMOJI['trophy']} Top Songs:",
                *top_songs,
                "",
                f"{EMOJI['trophy']} Top Künstler:",
                *top_artists,
                "",
                f"{EMOJI['trophy']} Top Alben:",
                *top_albums,
            ]

            await msg.edit_text("\n".join(lines))
            self.logger.info(
                f"{EMOJI['success']} ✅ Jahresrückblick Text erstellt (User: {nav_user})"
            )

            # Diagramme generieren
            song_chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "songs"
            )
            artist_chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "artists"
            )

            if song_chart_path and song_chart_path.exists():
                with open(song_chart_path, "rb") as f1:
                    await reply_target.reply_photo(
                        photo=f1,
                        caption=f"{EMOJI['topsongs']} Top Songs des Jahres ({esc(nav_user)})",
                    )
                self.logger.info(
                    f"{EMOJI['chart']} 📊 Songs-Diagramm gesendet (User: {nav_user})"
                )

            if artist_chart_path and artist_chart_path.exists():
                with open(artist_chart_path, "rb") as f2:
                    await reply_target.reply_photo(
                        photo=f2,
                        caption=f"{EMOJI['topartists']} Top Künstler des Jahres ({esc(nav_user)})",
                    )
                self.logger.info(
                    f"{EMOJI['chart']} 📊 Künstler-Diagramm gesendet (User: {nav_user})"
                )

            self.logger.info(
                f"{EMOJI['success']} ✅ Jahresrückblick erfolgreich (User: {nav_user})"
            )

        except Exception as e:
            await msg.edit_text(
                f"{EMOJI['error']} ❌ Fehler: {self._escape_text(str(e))}"
            )
            self.logger.error(
                f"{EMOJI['error']} ❌ Fehler in handle_year_review: {str(e)}",
                exc_info=True,
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
            if not stats or not stats["top_songs"]:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Song-Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Song-Daten (User: {nav_user}, Periode: {period})"
                )
                return

            lines = [
                f"{self._escape_text(idx+1)}. {self._escape_text(title)} ({self._escape_text(count)} Plays)"
                for idx, (title, count) in enumerate(stats["top_songs"])
            ]

            response = (
                f"{EMOJI['topsongs']} Top Songs ({self._escape_text(period.title())}) für {self._escape_text(nav_user)}:\n\n"
                + "\n".join(lines)
                + f"\n\n{EMOJI['statistics']} Gesamt Plays: {self._escape_text(stats['total_plays'])}"
            )

            await msg.edit_text(response)
            self.logger.info(
                f"{EMOJI['success']} ✅ Top Songs Liste erstellt ({len(stats['top_songs'])} Einträge, User: {nav_user})"
            )

            # Diagramm generieren und senden
            chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "songs"
            )
            if chart_path and chart_path.exists():
                with open(chart_path, "rb") as chart_file:
                    await reply_target.reply_photo(
                        photo=chart_file,
                        caption=f"{EMOJI['topsongs']} Top Songs Visualisierung ({self._escape_text(nav_user)})",
                    )
                self.logger.info(
                    f"{EMOJI['chart']} 📊 Songs-Diagramm gesendet (User: {nav_user})"
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
            if not stats or not stats["top_artists"]:
                await msg.edit_text(
                    f"{EMOJI['warning']} ⚠️ Keine Künstler-Daten für '{self._escape_text(nav_user)}' verfügbar."
                )
                self.logger.warning(
                    f"{EMOJI['warning']} ⚠️ Keine Künstler-Daten (User: {nav_user}, Periode: {period})"
                )
                return

            lines = [
                f"{self._escape_text(idx+1)}. {self._escape_text(artist)} ({self._escape_text(count)} Plays)"
                for idx, (artist, count) in enumerate(stats["top_artists"])
            ]

            response = (
                f"{EMOJI['topartists']} Top Künstler ({self._escape_text(period.title())}) für {self._escape_text(nav_user)}:\n\n"
                + "\n".join(lines)
                + f"\n\n{EMOJI['statistics']} Gesamt Plays: {self._escape_text(stats['total_plays'])}"
            )

            await msg.edit_text(response)
            self.logger.info(
                f"{EMOJI['success']} ✅ Top Künstler Liste erstellt ({len(stats['top_artists'])} Einträge, User: {nav_user})"
            )

            # Diagramm generieren und senden
            chart_path = await asyncio.to_thread(
                self.statistik_service.create_chart, stats, "artists"
            )
            if chart_path and chart_path.exists():
                with open(chart_path, "rb") as chart_file:
                    await reply_target.reply_photo(
                        photo=chart_file,
                        caption=f"{EMOJI['topartists']} Top Künstler Visualisierung ({self._escape_text(nav_user)})",
                    )
                self.logger.info(
                    f"{EMOJI['chart']} 📊 Künstler-Diagramm gesendet (User: {nav_user})"
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

    async def handle_music_timeline(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Behandelt die Anfrage für die Music-Timeline-Übersicht
        (Heute / Diese Woche / Diesen Monat).

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

            esc = self._escape_text
            periods = timeline["periods"]

            def render_period(label: str, data: Dict[str, Any]) -> List[str]:
                block = [
                    label,
                    "──────────────",
                    f"{esc(data['track_count'])} Tracks",
                    self._format_duration(data["listening_seconds"]),
                ]
                if data["top_artist"]:
                    block.append(
                        f"🎤 Top Artist: {esc(data['top_artist'][0])} "
                        f"({esc(data['top_artist'][1])} Plays)"
                    )
                if data["top_album"]:
                    block.append(
                        f"💿 Top Album: {esc(data['top_album'][0])} "
                        f"({esc(data['top_album'][1])} Plays)"
                    )
                if data["most_replayed_track"]:
                    block.append(
                        f"🔁 Meistgehört: {esc(data['most_replayed_track'][0])} "
                        f"({esc(data['most_replayed_track'][1])}x)"
                    )
                block.append(f"🆕 Neue Tracks: {esc(data['new_track_count'])}")
                return block

            lines = [f"{EMOJI['calendar']} Deine Musik ({esc(nav_user)})", ""]
            lines += render_period("Heute", periods["today"])
            lines.append("")
            lines += render_period("Diese Woche", periods["week"])
            lines.append("")
            lines += render_period("Diesen Monat", periods["month"])

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
