# handlers/duplicate_check_handler.py
# -*- coding: utf-8 -*-
"""
🔁 DUPLIKAT-CHECK — TELEGRAM MENÜ-HANDLER (Chat-Charakterisierung 2026-09-15)

Telegram-Oberfläche für services/library_repair/duplicate_runner.py, das
seinerseits scripts/resolve_duplicates.py als Subprozess aufruft (bereits
gehärtete Klassifikations-/Resolution-/Safety-Gate-Engine, siehe
docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md) - kein eigener
Dateisystemzugriff, keine eigene Duplikat-Erkennung hier (CLAUDE.md §4
Schichtgrenzen).

Bewusst NUR Erkennung + Vorschlag (read-only Dry-Run-Scan), KEINE
Ausführung/Löschung über Telegram. Der ursprüngliche Vorschlag ("bei
höher-bitratigem Duplikat automatisch ersetzen") wurde im Chat bewusst
abgelehnt - das hätte die gesamte im Projekt etablierte
Sicherheitsphilosophie durchbrochen (jede andere Library-Mutation läuft
über Plan → Preview → explizite Bestätigung → Execute, nie automatisch,
siehe repair_musicbot_handler.py/library_maintenance_handler.py). Das
tatsächliche Löschen bleibt CLI-only:

    scripts/library_repair.py --allow-delete --artist <Name> --apply

Öffnen dieses Menüs oder der Artist-Liste löst NIEMALS einen Scan aus -
nur die explizite Artist-Auswahl startet den (read-only) Subprozess-Lauf.
Nur für Admins sichtbar/nutzbar (Config.OWNER_USER_ID/ADMIN_USER_IDS),
identisches Muster wie die übrigen library_repair-Handler. Berechtigung
wird am tatsächlichen Scan-Auslöser erneut geprüft (Defense-in-Depth).

Artist-Auswahl ausschließlich index-basiert (ARCH-031 B.8, identisches
Muster wie handlers/library_maintenance_handler.py) - niemals ein
Rohpfad/String aus Telegram-`callback_data`.
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
from services.library_repair.duplicate_runner import DuplicateScanResult, run_duplicate_scan
from services.library_repair.library_artists import (
    list_library_artist_dirs,
    resolve_artist_by_index,
)
from services.library_repair.run_tracking import RepairAlreadyRunningError

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_BACK_TO_ADMIN = "menu:admin_group_library"

# Wie viele Duplikat-Gruppen maximal in EINER Telegram-Nachricht gezeigt
# werden - schuetzt vor einer Nachricht ueber dem Telegram-Zeichenlimit
# bei einem Artist mit sehr vielen Gruppen.
_MAX_GROUPS_SHOWN = 12


class DuplicateCheckHandler:
    """Verwaltet den '🔁 Duplikat-Check'-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("DuplicateCheckHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

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
                f"💥 Unbehandelte Exception im Duplikat-Check-Hintergrund-Task: {exc}",
                exc_info=exc,
            )

    async def _report_error(self, e: Exception, operation: str) -> None:
        if self.error_handler:
            await self.error_handler.handle_exception(
                e, context={"module": "DuplicateCheckHandler", "operation": operation},
            )

    # ── Start ─────────────────────────────────────────────────────────

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Nur Admins dürfen den Duplikat-Check nutzen", show_alert=True)
            return
        await query.answer()

        text = (
            "🔁 <b>Duplikat-Check</b>\n\n"
            "Sucht pro Artist nach höher-bitratigen Duplikaten und zeigt "
            "einen Vorschlag, welche Version behalten werden sollte — "
            "rein lesend, es wird nichts gelöscht.\n\n"
            "Tatsächliches Löschen bleibt bewusst der CLI vorbehalten:\n"
            "<code>scripts/library_repair.py --allow-delete --artist &lt;Name&gt; --apply</code>\n\n"
            "Wähle zuerst einen Artist."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Artist wählen", callback_data="dupcheck:artists")],
            [InlineKeyboardButton("◀️ Zurück", callback_data=_BACK_TO_ADMIN)],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Artist-Auswahl (Index-Picker) ────────────────────────────────

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
                reply_markup=self._back_keyboard("dupcheck:start"),
            )
            return

        buttons = [
            [InlineKeyboardButton(f"🎵 {name}", callback_data=f"dupcheck:pick:{idx}")]
            for idx, name in enumerate(artists)
        ]
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="dupcheck:start")])
        await query.edit_message_text(
            f"👤 <b>Artist wählen</b>\n\n{len(artists)} Artist(en) gefunden:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def handle_pick_artist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        """Einzige Stelle, die tatsächlich einen Scan startet - read-only,
        aber echter Subprozess-Lauf, daher Admin-Check hier erneut
        (Defense-in-Depth) und als Hintergrund-Task."""
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
                reply_markup=self._back_keyboard("dupcheck:artists"),
            )
            return

        placeholder = await query.edit_message_text(
            f"🔁 Duplikat-Scan läuft für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_scan_and_report(placeholder, artist))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_scan_and_report(self, message: Message, artist: str) -> None:
        try:
            result = await run_duplicate_scan(artist)
        except RepairAlreadyRunningError as e:
            await message.edit_text(
                f"🔒 {html.escape(str(e))}",
                reply_markup=self._back_keyboard("dupcheck:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler beim Duplikat-Scan: {e}", exc_info=True)
            await self._report_error(e, "run_duplicate_scan")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("dupcheck:start"),
            )
            return

        text = self._format_scan_result(artist, result)
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._back_keyboard("dupcheck:start"))

    def _format_scan_result(self, artist: str, result: DuplicateScanResult) -> str:
        # Bewusst `result.report is None` statt `not result.success` als
        # Fallunterscheidung: Exit-Code 3 (Safety-Violation, vom Skript
        # SELBST erkannt) liefert `success=False` (exit_code != 0), aber
        # TROTZDEM einen gültigen Report mit `read_only_intact=False` -
        # der spricht ausdrücklich seine eigene Warnung unten aus. Nur
        # wenn wirklich KEIN Report vorliegt (Subprozess-Start-Fehler,
        # Timeout, unerwarteter Exit-Code, kaputtes JSON), ist es ein
        # generischer Fehlschlag.
        if result.report is None:
            if result.timed_out or result.error_message:
                detail = result.error_message or "Timeout"
            else:
                detail = result.stderr_tail.strip()[-800:] or "Kein Fehlertext verfügbar."
            return (
                f"❌ <b>Duplikat-Scan fehlgeschlagen</b>\n"
                f"Artist: {html.escape(artist)}\n\n"
                f"<pre>{html.escape(detail)}</pre>"
            )

        report = result.report
        if not report.get("read_only_intact", True):
            return (
                f"🚨 <b>Sicherheitswarnung</b>\n\n"
                f"Das Dateisystem hat sich während des Scans für "
                f"{html.escape(artist)} verändert - Ergebnis verworfen, "
                f"bitte erneut versuchen."
            )

        groups = report.get("duplicate_groups", 0)
        resolved = report.get("resolved_groups", 0)
        manual = report.get("manual_review_groups", 0)

        if groups == 0:
            return (
                f"✅ <b>Duplikat-Check — {html.escape(artist)}</b>\n\n"
                f"Keine Duplikat-Gruppen gefunden "
                f"({report.get('files_scanned', 0)} Dateien geprüft)."
            )

        lines = [
            f"🔁 <b>Duplikat-Check — {html.escape(artist)}</b>",
            "",
            f"{groups} Duplikat-Gruppe(n) — {resolved} mit Vorschlag, "
            f"{manual} zur manuellen Prüfung",
            "",
        ]

        decisions = report.get("decisions", [])
        for decision in decisions[:_MAX_GROUPS_SHOWN]:
            title = html.escape(decision.get("title") or "?")
            if decision.get("action") == "RESOLVED":
                keep_path = decision.get("keep")
                remove_paths = decision.get("remove_proposal") or []
                keep_candidate = next(
                    (c for c in decision.get("candidates", []) if c.get("path") == keep_path),
                    None,
                )
                keep_bitrate = keep_candidate.get("bitrate") if keep_candidate else None
                lines.append(f"🎵 <b>{title}</b>")
                lines.append(
                    f"  ✅ Behalten: {html.escape(_short_path(keep_path))}"
                    + (f" ({keep_bitrate} kbps)" if keep_bitrate else "")
                )
                for rp in remove_paths:
                    rp_candidate = next(
                        (c for c in decision.get("candidates", []) if c.get("path") == rp),
                        None,
                    )
                    rp_bitrate = rp_candidate.get("bitrate") if rp_candidate else None
                    lines.append(
                        f"  🗑️ Vorschlag entfernen: {html.escape(_short_path(rp))}"
                        + (f" ({rp_bitrate} kbps)" if rp_bitrate else "")
                    )
            else:
                lines.append(f"🎵 <b>{title}</b>")
                lines.append(
                    f"  ⚠️ {html.escape(decision.get('action', 'MANUAL_REVIEW'))}: "
                    f"{html.escape(decision.get('reason') or 'kein Grund angegeben')}"
                )
            lines.append("")

        if len(decisions) > _MAX_GROUPS_SHOWN:
            lines.append(f"… {len(decisions) - _MAX_GROUPS_SHOWN} weitere Gruppe(n)")
            lines.append("")

        lines.append(
            "Löschen nur über die CLI: "
            "<code>scripts/library_repair.py --allow-delete "
            f"--artist {html.escape(artist)} --apply</code>"
        )
        return "\n".join(lines)


def _short_path(path: Optional[str]) -> str:
    """Zeigt nur den Dateinamen statt des vollen Library-Pfads - kompakter
    für die Telegram-Anzeige, der volle Pfad steht ohnehin im CLI-Befehl
    (--artist) und im JSON-Report selbst."""
    if not path:
        return "?"
    return path.rsplit("/", 1)[-1]
