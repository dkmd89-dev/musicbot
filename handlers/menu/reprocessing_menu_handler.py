# handlers/menu/reprocessing_menu_handler.py
# -*- coding: utf-8 -*-
"""
🔧 REPROCESSING MENÜ-HANDLER

Telegram-Oberfläche für scripts/reprocess_artist_metadata.py. Ruft das
Skript ausschließlich als eigenständigen Subprozess auf (siehe
docs/METADATA_REPROCESSING.md Abschnitt 2a, services/metadata/
reprocessing_runner.py) - importiert es nie direkt.

Nur für den Owner sichtbar/nutzbar (Config.OWNER_USER_ID) - das Skript
greift auf Metadata-/Auto-Learn-Dateien zu, kein Feature für normale
Nutzer/Moderatoren (siehe Nutzer-Entscheidung, docs/FINDINGS_INDEX.md).

Ablauf: Artist-Liste (Buttons aus vorhandenen Verzeichnissen unter
/tmp/musicbot_test/metadaten/) -> Dry-Run (immer zuerst, keine Ausnahme) ->
Zusammenfassung mit "Jetzt LIVE ausführen"-Button -> Live-Lauf ->
Zusammenfassung. Jeder Subprozess-Lauf läuft als eigenständiger
Hintergrund-Task (asyncio.create_task), analog zum bereits etablierten
Muster in rich_menu_handler.py::_process_url() - verhindert, dass ein
mehrere Minuten dauernder Lauf alle anderen Telegram-Updates blockiert.
"""

import asyncio
import html
from typing import Callable, Optional, TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from services.metadata.reprocessing_runner import (
    ReprocessingRunResult,
    list_available_artist_dirs,
    run_reprocessing,
)

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


class ReprocessingMenuHandler:
    """Verwaltet den Reprocessing-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("ReprocessingMenuHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

    def _is_owner(self, user_id: int) -> bool:
        return user_id == getattr(self.config, "OWNER_USER_ID", None)

    def _back_to_admin_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀️ Zurück", callback_data="menu:admin")]]
        )

    async def show_artist_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt: listet die verfügbaren Artist-Verzeichnisse als
        Buttons. Owner-Check hier UND im Callback-Dispatcher (Defense-in-
        Depth, analog zum Wartungsmodus-Muster in rich_menu_system.py) -
        das MenuItem selbst blendet den Button nur für Nicht-Owner aus,
        prüft aber nichts beim tatsächlichen Callback-Empfang."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_owner(user_id):
            await query.answer(
                "⛔ Nur der Owner darf das Reprocessing-Tool nutzen",
                show_alert=True,
            )
            return
        await query.answer()

        artists = list_available_artist_dirs()
        if not artists:
            await query.edit_message_text(
                "📁 Keine Artist-Verzeichnisse unter "
                "<code>/tmp/musicbot_test/metadaten/</code> gefunden.\n\n"
                "Kopiere zuerst einen Artist-Ordner manuell dorthin (siehe "
                "docs/METADATA_REPROCESSING.md, Abschnitt 13).",
                parse_mode="HTML",
                reply_markup=self._back_to_admin_keyboard(),
            )
            return

        buttons = [
            [
                InlineKeyboardButton(
                    f"🎵 {name}", callback_data=f"reprocess:pick:{idx}"
                )
            ]
            for idx, name in enumerate(artists)
        ]
        buttons.append(
            [InlineKeyboardButton("◀️ Zurück", callback_data="menu:admin")]
        )

        await query.edit_message_text(
            "🔧 <b>Metadata-Reprocessing</b>\n\n"
            f"{len(artists)} Artist-Verzeichnis(se) gefunden. Wähle einen "
            "Artist für einen Dry-Run (analysiert nur, ändert keine Datei):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    def _resolve_artist_by_index(self, idx: int) -> Optional[str]:
        """Löst einen Button-Index gegen eine frisch geholte Artist-Liste
        auf. Re-globbt bewusst bei jedem Aufruf statt eine Liste über
        mehrere Schritte im Speicher zu halten (einfacher als
        Session-State, ausreichend fuer ein Single-Owner-Tool ohne
        gleichzeitige andere Schreibzugriffe auf dieses Verzeichnis)."""
        artists = list_available_artist_dirs()
        if 0 <= idx < len(artists):
            return artists[idx]
        return None

    async def handle_pick(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        """Startet den Dry-Run für den per Index gewählten Artist."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_owner(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        artist_name = self._resolve_artist_by_index(idx)
        if artist_name is None:
            await query.answer(
                "⚠️ Artist nicht mehr gefunden - Liste hat sich geändert.",
                show_alert=True,
            )
            await self.show_artist_list(update, context)
            return
        await query.answer()

        await self._start_run(query.message, artist_name, dry_run=True, idx=idx)

    async def handle_live(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        """Startet den LIVE-Lauf für den per Index gewählten Artist -
        ausschließlich über den 'Jetzt LIVE ausführen'-Button nach einem
        vorherigen Dry-Run erreichbar (Nutzer-Entscheidung: kein direkter
        Live-Einstieg ohne vorherige Sichtprüfung)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_owner(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return

        artist_name = self._resolve_artist_by_index(idx)
        if artist_name is None:
            await query.answer(
                "⚠️ Artist nicht mehr gefunden - Liste hat sich geändert.",
                show_alert=True,
            )
            await self.show_artist_list(update, context)
            return
        await query.answer()

        await self._start_run(query.message, artist_name, dry_run=False, idx=idx)

    async def _start_run(
        self, message: Message, artist_name: str, dry_run: bool, idx: int
    ) -> None:
        """Zeigt eine Platzhalter-Nachricht, startet den eigentlichen
        Subprozess-Lauf als Hintergrund-Task und kehrt sofort zurück -
        analog zu rich_menu_handler.py::_process_url() (siehe dortiger
        Docstring: ohne Hintergrund-Task würde ein mehrminütiger Lauf jedes
        weitere Telegram-Update blockieren, da die Application ohne
        concurrent_updates=True läuft)."""
        mode_label = "Dry-Run" if dry_run else "🔴 LIVE-Lauf"
        placeholder = await message.edit_text(
            f"⏳ {mode_label} für <b>{html.escape(artist_name)}</b> läuft ... "
            "kann je nach Trackanzahl mehrere Minuten dauern.",
            parse_mode="HTML",
        )
        task = asyncio.create_task(
            self._run_and_report(placeholder, artist_name, dry_run, idx)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_and_report(
        self, message: Message, artist_name: str, dry_run: bool, idx: int
    ) -> None:
        try:
            result = await run_reprocessing(artist_name, dry_run=dry_run)
        except Exception as e:
            self.logger.error(
                f"💥 Unerwarteter Fehler beim Reprocessing von "
                f"'{artist_name}': {e}",
                exc_info=True,
            )
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}"
            )
            return

        text, keyboard = self._format_result(artist_name, dry_run, idx, result)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _format_result(
        self,
        artist_name: str,
        dry_run: bool,
        idx: int,
        result: ReprocessingRunResult,
    ):
        mode_label = "DRY-RUN" if dry_run else "LIVE"
        safe_artist = html.escape(artist_name)

        if not result.success:
            if result.timed_out:
                detail = result.error_message or "Timeout"
            elif result.error_message:
                detail = result.error_message
            else:
                detail = (
                    result.stderr_tail.strip()[-800:]
                    or "Kein Fehlertext verfügbar (siehe Log)."
                )
            text = (
                f"❌ <b>Reprocessing fehlgeschlagen</b> ({mode_label})\n\n"
                f"Artist: {safe_artist}\n"
                f"Exit-Code: {result.exit_code}\n\n"
                f"<code>{html.escape(detail)}</code>"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="reprocess:show")]]
            )
            return text, keyboard

        s = result.summary
        lines = [
            f"✅ <b>Reprocessing abgeschlossen</b> ({mode_label})",
            "",
            f"Artist: {safe_artist}",
            f"Dateien verarbeitet: {s.get('files_processed', 0)}",
            f"Geändert: {s.get('changed', 0)} | Unverändert: {s.get('unchanged', 0)}",
            f"Unresolved: {s.get('unresolved', 0)} | Fehler: {s.get('errors', 0)}",
            f"Gesamtergebnis: {html.escape(str(s.get('overall', '?')))}",
        ]
        if s.get("auto_learn_artists"):
            lines.append(
                "Auto-Learn Artists: "
                + html.escape(", ".join(s["auto_learn_artists"]))
            )
        if s.get("auto_learn_genres"):
            lines.append(
                "Auto-Learn Genres: "
                + html.escape(", ".join(s["auto_learn_genres"]))
            )
        if result.log_path:
            lines.append("")
            lines.append(f"Log: <code>{html.escape(result.log_path)}</code>")
        text = "\n".join(lines)

        if dry_run:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔴 Jetzt LIVE ausführen",
                            callback_data=f"reprocess:live:{idx}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "◀️ Zurück", callback_data="reprocess:show"
                        )
                    ],
                ]
            )
        else:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "◀️ Zurück zum Menü", callback_data="menu:admin"
                        )
                    ]
                ]
            )
        return text, keyboard

    def _log_background_task_exception(self, task: "asyncio.Task") -> None:
        """add_done_callback()-Sicherheitsnetz - siehe rich_menu_handler.py::
        _log_background_download_task_exception() für dasselbe etablierte
        Muster. _run_and_report() faengt bereits alle erwartbaren Fehler
        selbst ab; dies ist nur ein Netz gegen eine stumme 'Task exception
        was never retrieved'-Warnung bei wirklich unerwarteten Ausnahmen."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self.logger.error(
                f"💥 Unerwarteter Fehler im Hintergrund-Reprocessing-Task: {exc}",
                exc_info=exc,
            )
