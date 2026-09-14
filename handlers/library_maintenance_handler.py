# handlers/library_maintenance_handler.py
# -*- coding: utf-8 -*-
"""
🧹 LIBRARY-WARTUNG — TELEGRAM MENÜ-HANDLER (ARCH-032 Phase 4)

Telegram-Oberfläche für services/library_repair/maintenance_service.py -
Command-getriebener Flow (KEIN Health-Finding-Bezug, ADR-0001):

    Artist wählen → Aktion wählen → Preview (read-only)
    → explizite Bestätigung → Execute → Ergebnis

Ruft AUSSCHLIESSLICH den bestehenden Maintenance-Service auf - kein
eigener Dateisystemzugriff, keine Mutagen-/Backup-/Journal-Logik hier
(CLAUDE.md §4 Schichtgrenzen, ARCH-031 §14/B.7).

Callback-Präfix `libmaint:` - bewusst NICHT `maint:` (bereits durch den
Bot-Wartungsmodus/MaintenanceModeStore belegt, siehe
handlers/menu/rich_menu_system.py::_handle_maintenance_callback()).

Artist-Auswahl ausschließlich index-basiert (ARCH-031 B.8, identisches
Muster wie handlers/menu/reprocessing_menu_handler.py) - niemals ein
Rohpfad/String aus Telegram-`callback_data`.

set-genre ist über Telegram bewusst NUR im --from-mapping-Modus
erreichbar (kein Freitext-Genre-Eingabefeld in dieser Phase) - für
manuelle Werte bleibt die CLI zuständig
(scripts/library_repair.py --maintenance-action set-genre --genre "...").
--update-manual-mapping bleibt CLI-only (ARCH-031 A.4).

Öffnen dieses Menüs, der Artist-Liste oder der Aktions-Auswahl startet
NIEMALS automatisch eine Wartungsaktion - nur der explizit bestätigte
"JA, AUSFÜHREN"-Tap tut das.

Nur für Admins sichtbar/nutzbar (Config.OWNER_USER_ID/ADMIN_USER_IDS),
identisches Muster wie handlers/repair_musicbot_handler.py. Die
Berechtigung wird am tatsächlichen Ausführungs-Handler ERNEUT geprüft.
"""

from __future__ import annotations

import asyncio
import html
from typing import Callable, Optional, TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from handlers.menu.permissions import is_admin_or_owner
from services.library_repair.library_artists import (
    list_library_artist_dirs,
    resolve_artist_by_index,
)
from services.library_repair.maintenance_service import (
    ACTION_ARTIST_CASING,
    ACTION_LEGACY_GENRE_CLEANUP,
    ACTION_SET_GENRE,
    MaintenanceServiceError,
    execute_artist_casing_fix,
    execute_legacy_genre_cleanup,
    execute_set_genre,
    preview_artist_casing,
    preview_legacy_genre_cleanup,
    preview_set_genre,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError, is_repair_running

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_BACK_TO_ADMIN = "menu:admin_group_library"

_ACTION_LABELS = {
    ACTION_ARTIST_CASING: "🎤 Artist Casing korrigieren",
    ACTION_LEGACY_GENRE_CLEANUP: "🧹 Legacy Genre bereinigen",
    ACTION_SET_GENRE: "🎼 Genre setzen (aus Mapping)",
}


class LibraryMaintenanceHandler:
    """Verwaltet den '🧹 Library-Wartung'-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("LibraryMaintenanceHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

    # ── Berechtigung ─────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        return is_admin_or_owner(user_id, self.config)

    def _back_keyboard(self, target: str = _BACK_TO_ADMIN, label: str = "◀️ Zurück") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])

    def _log_background_task_exception(self, task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self.logger.error(
                f"💥 Unbehandelte Exception in Library-Wartung-Hintergrund-Task: {exc}",
                exc_info=exc,
            )

    async def _report_error(self, e: Exception, operation: str) -> None:
        if self.error_handler:
            await self.error_handler.handle_exception(
                e, context={"module": "LibraryMaintenanceHandler", "operation": operation},
            )

    # ── Preview-/Execute-Funktionsauflösung ────────────────────────────

    def _preview_fn(self, action: str) -> Callable:
        return {
            ACTION_ARTIST_CASING: preview_artist_casing,
            ACTION_LEGACY_GENRE_CLEANUP: preview_legacy_genre_cleanup,
            ACTION_SET_GENRE: lambda artist: preview_set_genre(artist, from_mapping=True),
        }[action]

    def _execute_fn(self, action: str) -> Callable:
        return {
            ACTION_ARTIST_CASING: execute_artist_casing_fix,
            ACTION_LEGACY_GENRE_CLEANUP: execute_legacy_genre_cleanup,
            ACTION_SET_GENRE: lambda artist, *, triggered_by: execute_set_genre(
                artist, triggered_by=triggered_by, from_mapping=True
            ),
        }[action]

    # ── Start ─────────────────────────────────────────────────────────

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Nur Admins dürfen Library-Wartung nutzen", show_alert=True)
            return
        await query.answer()

        text = (
            "🧹 <b>Library-Wartung</b>\n\n"
            "Gezielte Wartungsaktionen für einen Artist — kein Health-Scan, "
            "kein Finding-Bezug (siehe 🛠️ Repair MusicBot dafür):\n\n"
            "• 🎤 Artist Casing korrigieren\n"
            "• 🧹 Legacy Genre bereinigen\n"
            "• 🎼 Genre aus dem Mapping setzen\n\n"
            "Wähle zuerst einen Artist."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Artist wählen", callback_data="libmaint:artists")],
            [InlineKeyboardButton("◀️ Zurück", callback_data=_BACK_TO_ADMIN)],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Artist-Auswahl (ARCH-031 B.8, Index-Picker) ─────────────────────

    async def handle_artist_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artists = list_library_artist_dirs()
        if not artists:
            await query.edit_message_text(
                "📁 Keine Artist-Verzeichnisse in der Library gefunden.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        buttons = [
            [InlineKeyboardButton(f"🎵 {name}", callback_data=f"libmaint:pick:{idx}")]
            for idx, name in enumerate(artists)
        ]
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="libmaint:start")])
        await query.edit_message_text(
            f"👤 <b>Artist wählen</b>\n\n{len(artists)} Artist(en) gefunden:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def handle_pick_artist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = resolve_artist_by_index(idx)
        if artist is None:
            await query.edit_message_text(
                "⚠️ Artist nicht mehr gefunden (Liste hat sich geändert) — "
                "bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        text = f"👤 <b>{html.escape(artist)}</b>\n\nWähle eine Aktion:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                _ACTION_LABELS[ACTION_ARTIST_CASING],
                callback_data=f"libmaint:action:{ACTION_ARTIST_CASING}:{idx}",
            )],
            [InlineKeyboardButton(
                _ACTION_LABELS[ACTION_LEGACY_GENRE_CLEANUP],
                callback_data=f"libmaint:action:{ACTION_LEGACY_GENRE_CLEANUP}:{idx}",
            )],
            [InlineKeyboardButton(
                _ACTION_LABELS[ACTION_SET_GENRE],
                callback_data=f"libmaint:action:{ACTION_SET_GENRE}:{idx}",
            )],
            [InlineKeyboardButton("◀️ Zurück", callback_data="libmaint:artists")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Preview (read-only, Auftrag §11.6) ───────────────────────────────

    async def handle_preview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = resolve_artist_by_index(idx)
        if artist is None:
            await query.edit_message_text(
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        placeholder = await query.edit_message_text(
            f"🔍 Erstelle Vorschau für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_preview_and_report(placeholder, action, artist, idx))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_preview_and_report(
        self, message: Message, action: str, artist: str, idx: int
    ) -> None:
        try:
            preview = self._preview_fn(action)(artist)
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard(f"libmaint:pick:{idx}"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Vorschau: {e}", exc_info=True)
            await self._report_error(e, "preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard(f"libmaint:pick:{idx}"),
            )
            return

        if preview.target_count == 0:
            await message.edit_text(
                f"📁 Keine Dateien für {html.escape(artist)} gefunden.",
                reply_markup=self._back_keyboard(f"libmaint:pick:{idx}"),
            )
            return
        if preview.changed_count == 0:
            await message.edit_text(
                f"✅ {html.escape(artist)}: keine Änderung nötig "
                f"({preview.target_count} Datei(en) bereits korrekt).",
                reply_markup=self._back_keyboard(f"libmaint:pick:{idx}"),
            )
            return

        lines = [
            f"🔍 <b>Vorschau — {_ACTION_LABELS[action]}</b>",
            f"Artist: {html.escape(artist)}",
            "",
            f"{preview.changed_count} von {preview.target_count} Datei(en) würden geändert:",
        ]
        changed = [o for o in preview.outcomes if o.status == "DRY_RUN"]
        for oc in changed[:10]:
            lines.append(f"  • {html.escape(oc.file)}")
            if oc.before or oc.after:
                lines.append(f"    {html.escape(str(oc.before))} → {html.escape(str(oc.after))}")
        if len(changed) > 10:
            lines.append(f"  … {len(changed) - 10} weitere")
        lines.append("")
        lines.append("Noch keine Änderungen durchgeführt.")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ausführen", callback_data=f"libmaint:confirm:{action}:{idx}")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data=f"libmaint:pick:{idx}")],
        ])
        await message.edit_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=keyboard,
        )

    # ── Explizite Bestätigung ─────────────────────────────────────────

    async def handle_confirm_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Aktion: {_ACTION_LABELS[action]}\n\n"
            "Diese Aktion verändert Tags in deiner Music Library "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\n"
            "Fortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, AUSFÜHREN", callback_data=f"libmaint:execute:{action}:{idx}")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data=f"libmaint:pick:{idx}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Ausführung ────────────────────────────────────────────────────

    async def handle_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, idx: int
    ) -> None:
        """Einzige Stelle, die tatsächlich eine Wartungsaktion startet -
        Berechtigung wird HIER erneut geprüft. Lock-Status wird VOR dem
        Start explizit geprüft (Auftrag §11.5.1, Doppelklick-Schutz) -
        die eigentliche, race-sichere Durchsetzung bleibt trotzdem
        acquire_repair_lock() innerhalb von execute_*() (unten
        abgefangen); dieser Vorab-Check verhindert nur unnötige
        Hintergrund-Tasks bei einem bereits erkennbar belegten Lock."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte warten, "
                "bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = resolve_artist_by_index(idx)
        if artist is None:
            await query.edit_message_text(
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        placeholder = await query.edit_message_text(
            f"🧹 Wartung läuft für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(
            self._run_execute_and_report(placeholder, action, artist, user_id)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_execute_and_report(
        self, message: Message, action: str, artist: str, user_id: int
    ) -> None:
        try:
            result = self._execute_fn(action)(artist, triggered_by=f"telegram:{user_id}")
        except RepairAlreadyRunningError as e:
            await message.edit_text(
                f"🔒 {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Wartungsaktion: {e}", exc_info=True)
            await self._report_error(e, "execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        await message.edit_text(
            self._format_result(action, artist, result),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    def _format_result(self, action: str, artist: str, result) -> str:
        if result.status == "SUCCESS":
            emoji = "⚠️" if result.failed_count else "✅"
        elif result.status == "FAILED":
            emoji = "❌"
        else:
            emoji = "ℹ️"
        header = "Wartung abgeschlossen" if not result.failed_count else "Wartung teilweise abgeschlossen"
        lines = [
            f"{emoji} <b>{header}</b>",
            f"Aktion: {_ACTION_LABELS.get(action, html.escape(action))}",
            f"Artist: {html.escape(artist)}",
            "",
            f"Ziele: {result.target_count}",
            f"Erfolgreich: {result.success_count}",
            f"Übersprungen: {result.skipped_count}",
            f"Fehlgeschlagen: {result.failed_count}",
        ]
        if result.error_message:
            lines.append("")
            lines.append(f"⚠️ {html.escape(result.error_message)}")
        return "\n".join(lines)
