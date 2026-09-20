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

Library Genre Management v2 (Chat-Charakterisierung 2026-09-15) - erweitert
set-genre um eine eigene "🎭 Genre-Verwaltung"-Sektion:
  - ✏️ Genre setzen: Quelle (Mapping/Manuell), Modus (Überschreiben/
    Nur-wenn-fehlt), optionales Mapping-Speichern (--update-manual-mapping,
    ueber services.library_repair.genre.save_manual_genre_mapping() -
    weiterhin dieselbe Prioritaet ggue. Auto-Learning, keine neue Semantik).
    Manuelle Texteingabe laeuft ueber das bestehende Freitext-Muster
    (context.user_data["libmaint_awaiting_genre_text"], siehe
    handlers/menu/rich_menu_handler.py::handle_text_message()) - identisches
    Prinzip wie Family-Chat/-Challenge, KEIN neuer ConversationHandler.
  - 🧹 Fehlende Genres: Artist-Liste aus offenen GENRE_EMPTY/
    META_GENRE_MISSING-Findings (services.library_repair.repair_service.
    build_repair_plan()/planner.filter_plan(), read-only Health-Scan) -
    fuehrt in denselben Set-Genre-Flow, only-if-missing als empfohlener
    Default (Auftrag §12).
  - 🔄 Genre revalidieren: services.library_repair.
    genre_revalidation_runner.run_genre_revalidation_subprocess() - LAEUFT
    ALS SUBPROZESS (nicht in-process!), weil GenreMapper/ArtistNormalizer
    SingletonMixin sind und ein in-process-Aufruf dieselben, bereits beim
    Bot-Start fuer die Live-Download-Pipeline konstruierten Instanzen
    treffen wuerde - identisches Risiko/identische Loesung wie bei ARCH-033
    L2/L3 (siehe repair_musicbot_handler.py-Docstring). Der normale
    Download-Pfad (GenreProcessor.determine_genre_with_fallbacks()) bleibt
    davon vollstaendig unberuehrt.

Alle drei Genre-Verwaltung-Flows halten sich strikt an Preview → explizite
Bestätigung → Execute → Verification/Run-Tracking, identisch zu den
bereits bestehenden drei Maintenance-Actions unten - keine Ausnahme.

Manual Metadata Editing v1 (ARCH-032-Folgeauftrag "Manual Metadata Editing
v1") - erweitert die Aktions-Auswahl um "📝 Metadaten bearbeiten"
(`libmaint:meta:<idx>`):
  - 🎤 Artist bearbeiten (`libmaint:meta:artist:*`): expliziter, vom Nutzer
    eingegebener Zielwert fuer ©ART/ARTISTS-Freeform, Artist-weiter Scope
    (identische Zielmenge wie Artist Casing - artist_targets()). KEINE
    Casing-Korrektur/Normalisierung/Identity-Resolution (Auftrag
    Abschnitt 6) - services.library_repair.executor.apply_artist_rename()
    aendert pro Datei nur dann etwas, wenn der tatsaechliche Tag-Wert dem
    gewaehlten Ausgangs-Artist entspricht (tag-wert-getrieben, ARCH-031 B.8).
  - 🎵 Titel bearbeiten (`libmaint:meta:title:*`): IMMER track-spezifisch -
    Track-Auswahl ueber einen zusaetzlichen index-basierten Picker
    (`libmaint:meta:title:pick:<idx>:<tidx>`, resolve_track_by_index()),
    dieselbe Datei-Zielmenge wie artist_targets() (Auftrag Abschnitt 16).
    KEIN automatischer TitleCleaner (Auftrag Abschnitt 8/9) - der manuell
    eingegebene Zielwert wird unveraendert geschrieben, die automatische
    Title-Cleanup-/Reprocessing-Pipeline
    (services/metadata/track_reprocessor.py) bleibt komplett unberuehrt.
  - 🎭 Genre-Verwaltung: KEINE Duplizierung - der Button unter
    "📝 Metadaten bearbeiten" fuehrt in denselben, bereits bestehenden
    genremenu:*-Flow (handle_genre_menu() oben) wie der direkte Button auf
    dem Aktions-Auswahl-Bildschirm (beide bleiben erreichbar, Auftrag
    Abschnitt 10).

  Beide neuen Flows folgen demselben context.user_data-Freitext-Muster wie
  Genre setzen (libmaint_awaiting_artist_text/libmaint_awaiting_title_text
  statt libmaint_awaiting_genre_text) und demselben Preview → explizite
  Bestätigung → Execute-Ablauf ueber den bestehenden Executor
  (apply_artist_rename()/apply_title_edit() - Backup + Journal +
  Audio-Essenz-Verifikation identisch zu den uebrigen Maintenance-Actions,
  KEINE neue Schreib-Pipeline, Auftrag Abschnitt 13). Terminal-/
  Fehlerpfade fuehren einheitlich zu "libmaint:start" zurueck (identisches
  Prinzip wie die gs:*/gr:*-Flows oben).

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
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from handlers.menu.permissions import is_admin_or_owner
from services.library_repair import genre as genre_domain
from services.library_repair.genre import GenreDomainError, save_manual_genre_mapping
from services.library_repair.genre_revalidation_runner import run_genre_revalidation_subprocess
from services.library_repair.library_artists import (
    list_library_artist_dirs,
    resolve_artist_by_index,
)
from services.library_repair.library_artists import (
    list_artist_albums,
    resolve_album_by_index,
)
from services.library_repair.maintenance_service import (
    ACTION_ARTIST_CASING,
    ACTION_LEGACY_GENRE_CLEANUP,
    MaintenanceServiceError,
    artist_targets,
    current_album,
    current_album_artist,
    current_title,
    execute_album_artist_edit,
    execute_album_edit,
    execute_artist_casing_fix,
    execute_artist_rename,
    execute_legacy_genre_cleanup,
    execute_set_genre,
    execute_title_edit,
    preview_album_artist_edit,
    preview_album_edit,
    preview_artist_casing,
    preview_artist_rename,
    preview_legacy_genre_cleanup,
    preview_set_genre,
    preview_title_edit,
    resolve_target_genre,
    resolve_track_by_index,
)
from services.library_repair.planner import filter_plan
from services.library_repair.repair_service import HealthScanFailedError, build_repair_plan
from services.library_repair.run_tracking import RepairAlreadyRunningError, is_repair_running

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_BACK_TO_ADMIN = "menu:admin_group_library"

_ACTION_LABELS = {
    ACTION_ARTIST_CASING: "🎤 Artist Casing korrigieren",
    ACTION_LEGACY_GENRE_CLEANUP: "🧹 Legacy Genre bereinigen",
}

# ── Genre-Verwaltung (Library Genre Management v2) ──────────────────────
_MISSING_GENRE_ISSUE_CODES = ("GENRE_EMPTY", "META_GENRE_MISSING")
_GENRE_MAX_INPUT_LEN = 200

# ── Metadaten bearbeiten (Manual Metadata Editing v1/v2) ─────────────────
_META_MAX_INPUT_LEN = 200
# Telegram lehnt zu grosse InlineKeyboardMarkup-Payloads ab (Bad Request) -
# ein Artist mit sehr vielen Tracks/Alben wuerde sonst handle_meta_title_
# start()/handle_meta_album_start() zum Absturz bringen (Review-Fund,
# Manual Metadata Editing v1). Keine echte Pagination (Auftrag v2 §25:
# "wenn bereits vorhanden wiederverwenden" - keine vorhanden, keine neue
# Infrastruktur bauen) - stattdessen defensive Kappung mit Hinweistext.
_META_PICKER_LIMIT = 80


def _validate_manual_meta_input(text: Optional[str], *, label: str) -> Optional[str]:
    """Format-Validierung fuer die manuelle Artist-/Titel-Freitext-Eingabe
    (Auftrag Abschnitt 14) - identisches Prinzip wie
    _validate_manual_genre_input() unten, aber ohne Genre-spezifische
    Normalisierung (Manual Artist/Title Editing hat keine
    Delimiter-Normalisierung - der Zielwert ist der explizite
    Nutzerwunsch, Auftrag Abschnitt 6/8/9)."""
    if text is None:
        return "Keine Eingabe erhalten."
    if "\n" in text or "\r" in text:
        return f"Zeilenumbrüche sind nicht erlaubt — bitte {label} in einer Zeile eingeben."
    stripped = text.strip()
    if not stripped:
        return "Eingabe darf nicht leer sein."
    if len(stripped) > _META_MAX_INPUT_LEN:
        return f"Eingabe zu lang (max. {_META_MAX_INPUT_LEN} Zeichen)."
    return None


def _validate_manual_genre_input(text: Optional[str]) -> Optional[str]:
    """Gibt eine Nutzer-Fehlermeldung zurück, wenn `text` als manuelle
    Genre-Eingabe ungültig ist, sonst None (Auftrag Abschnitt 6). Reine
    Format-/Längenprüfung - die eigentliche Normalisierung übernimmt
    weiterhin ausschließlich genre_domain.normalize_genre_input() (keine
    zweite/konkurrierende Normalisierung hier). Shell-/YAML-Injection sind
    strukturell ausgeschlossen: der Wert wird nie in einen Shell-Befehl
    eingebettet (Mutagen-API, kein Subprocess-String-Aufbau) und
    ausschließlich über yaml.safe_dump() (automatisches Escaping)
    geschrieben (save_manual_genre_mapping())."""
    if text is None:
        return "Keine Eingabe erhalten."
    if "\n" in text or "\r" in text:
        return "Zeilenumbrüche sind nicht erlaubt — bitte das Genre in einer Zeile eingeben."
    stripped = text.strip()
    if not stripped:
        return "Eingabe darf nicht leer sein."
    if len(stripped) > _GENRE_MAX_INPUT_LEN:
        return f"Eingabe zu lang (max. {_GENRE_MAX_INPUT_LEN} Zeichen)."
    return None


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
    # ACTION_SET_GENRE ist hier BEWUSST NICHT mehr enthalten (Library
    # Genre Management v2): das alte, hier ueber diese generische
    # action/idx-Signatur erreichbare "Genre setzen (aus Mapping)"
    # (from_mapping=True fest verdrahtet, kein Freitext, kein
    # only-if-missing) ist durch den neuen, mehrschrittigen
    # "🎭 Genre-Verwaltung"-Flow (handle_genre_menu()/handle_gs_*() unten)
    # ersetzt - kein Button erzeugt mehr "libmaint:action:set-genre:*".
    # preview_set_genre()/execute_set_genre() bleiben unveraendert
    # importiert, werden jetzt direkt von den gs_*()-Methoden mit den
    # tatsaechlich vom Nutzer gewaehlten Optionen aufgerufen.

    def _preview_fn(self, action: str) -> Callable:
        return {
            ACTION_ARTIST_CASING: preview_artist_casing,
            ACTION_LEGACY_GENRE_CLEANUP: preview_legacy_genre_cleanup,
        }[action]

    def _execute_fn(self, action: str) -> Callable:
        return {
            ACTION_ARTIST_CASING: execute_artist_casing_fix,
            ACTION_LEGACY_GENRE_CLEANUP: execute_legacy_genre_cleanup,
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
            "• 🎭 Genre-Verwaltung (setzen/revalidieren)\n\n"
            "Wähle zuerst einen Artist, oder springe direkt zu Artists mit "
            "fehlendem Genre."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Artist wählen", callback_data="libmaint:artists")],
            [InlineKeyboardButton("🧹 Fehlende Genres", callback_data="libmaint:missing")],
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
                "📝 Metadaten bearbeiten", callback_data=f"libmaint:meta:{idx}",
            )],
            [InlineKeyboardButton(
                _ACTION_LABELS[ACTION_ARTIST_CASING],
                callback_data=f"libmaint:action:{ACTION_ARTIST_CASING}:{idx}",
            )],
            [InlineKeyboardButton(
                _ACTION_LABELS[ACTION_LEGACY_GENRE_CLEANUP],
                callback_data=f"libmaint:action:{ACTION_LEGACY_GENRE_CLEANUP}:{idx}",
            )],
            [InlineKeyboardButton(
                "🎭 Genre-Verwaltung", callback_data=f"libmaint:genremenu:{idx}",
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

    # ═════════════════════════════════════════════════════════════════
    # 🎭 GENRE-VERWALTUNG (Library Genre Management v2,
    # Chat-Charakterisierung 2026-09-15)
    # ═════════════════════════════════════════════════════════════════
    #
    # Session-Status ausschließlich in context.user_data (PTB-nativ,
    # bereits etabliertes Muster für Freitext-Workflows in diesem Projekt,
    # siehe handlers/library_health_review_handler.py::_SESSION_KEY und
    # handlers/menu/rich_menu_handler.py::handle_text_message()):
    #   libmaint_genre_artist            -> str, der aktuell gewählte Artist
    #   libmaint_genre_set               -> dict, Optionen des Set-Genre-Flows
    #       {"source": "mapping"|"manual", "manual_genre": str|None,
    #        "only_if_missing": bool, "save_mapping": bool,
    #        "missing_genre_flow": bool (nur gesetzt, wenn über
    #        "🧹 Fehlende Genres" gestartet - steuert nur einen Hinweistext,
    #        keine eigene Logik)}
    #   libmaint_awaiting_genre_text     -> True, während auf eine
    #       Freitext-Antwort gewartet wird (siehe process_pending_genre_input())
    #   libmaint_missing_genre_artists   -> list[str], Artist-Liste aus dem
    #       letzten "🧹 Fehlende Genres"-Scan (index-basierte Auswahl,
    #       ARCH-031 B.8 - kein Rohname in callback_data)
    #
    # Alle Abbruch-/Fehlerpfade führen bewusst einheitlich zurück zu
    # "libmaint:start" statt einer feingranularen Rücknavigation - hält
    # die Zustandsverwaltung klein (kein zusätzliches idx-Tracking über
    # den gesamten mehrstufigen Flow hinweg nötig).

    def _genre_artist(self, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        return context.user_data.get("libmaint_genre_artist")

    async def _genre_session_expired(self, query) -> None:
        await query.edit_message_text(
            "⚠️ Sitzung abgelaufen — bitte Artist erneut wählen.",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    # ── Einstieg: Genre-Verwaltung für EINEN Artist ─────────────────────

    async def handle_genre_menu(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        context.user_data["libmaint_genre_artist"] = artist
        context.user_data.pop("libmaint_genre_set", None)
        context.user_data.pop("libmaint_awaiting_genre_text", None)

        text = f"🎭 <b>Genre-Verwaltung — {html.escape(artist)}</b>\n\nWähle eine Aktion:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Genre setzen", callback_data="libmaint:gs:src")],
            [InlineKeyboardButton("🔄 Genre revalidieren", callback_data="libmaint:gr:preview")],
            [InlineKeyboardButton("◀️ Zurück", callback_data=f"libmaint:pick:{idx}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── 🧹 Fehlende Genres (ARCH-031 Follow-up F1: GENRE_EMPTY/
    # META_GENRE_MISSING) - findet betroffene Artists über den
    # bestehenden Health-Scan/Planner, KEINE eigene Scan-Logik ─────────

    async def handle_missing_genre_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text(
            "🔍 Suche Artists mit fehlendem Genre ... kann je nach "
            "Library-Größe einige Minuten dauern."
        )
        task = asyncio.create_task(self._run_missing_genre_scan_and_report(placeholder, context))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_missing_genre_scan_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Suche: {e}", exc_info=True)
            await self._report_error(e, "missing_genre_scan")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist_names: set = set()
        for code in _MISSING_GENRE_ISSUE_CODES:
            for candidate in filter_plan(plan, issue_code=code).candidates:
                if candidate.artist:
                    artist_names.add(candidate.artist)
        artists = sorted(artist_names)

        if not artists:
            await message.edit_text(
                "✅ Keine offenen Befunde mit fehlendem Genre "
                f"({'/'.join(_MISSING_GENRE_ISSUE_CODES)}) gefunden.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        context.user_data["libmaint_missing_genre_artists"] = artists
        buttons = [
            [InlineKeyboardButton(f"🎵 {name}", callback_data=f"libmaint:missingpick:{idx}")]
            for idx, name in enumerate(artists)
        ]
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="libmaint:start")])
        await message.edit_text(
            f"🧹 <b>Fehlende Genres</b>\n\n{len(artists)} Artist(en) mit "
            f"{'/'.join(_MISSING_GENRE_ISSUE_CODES)}:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def handle_missing_genre_pick(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artists = context.user_data.get("libmaint_missing_genre_artists") or []
        if not (0 <= idx < len(artists)):
            await query.edit_message_text(
                "⚠️ Liste ist abgelaufen (z. B. neuer Bot-Start) — bitte "
                "erneut suchen.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        artist = artists[idx]

        context.user_data["libmaint_genre_artist"] = artist
        context.user_data["libmaint_genre_set"] = {"missing_genre_flow": True}
        context.user_data.pop("libmaint_awaiting_genre_text", None)

        text = (
            f"🧹 <b>{html.escape(artist)}</b> — Genre fehlt laut Health-Scan.\n\n"
            "Quelle wählen:"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Aus Mapping", callback_data="libmaint:gs:mapping")],
            [InlineKeyboardButton("✏️ Manuell eingeben", callback_data="libmaint:gs:manual")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── ✏️ Genre setzen: Quelle → Modus → (Manuell: Mapping speichern?)
    # → Preview → Bestätigung → Execute ─────────────────────────────────

    async def handle_gs_src(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        if not artist:
            await self._genre_session_expired(query)
            return

        context.user_data["libmaint_genre_set"] = {}
        text = f"✏️ <b>Genre setzen — {html.escape(artist)}</b>\n\nQuelle wählen:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Aus Mapping", callback_data="libmaint:gs:mapping")],
            [InlineKeyboardButton("✏️ Manuell eingeben", callback_data="libmaint:gs:manual")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _gs_state(self, context: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        return context.user_data.get("libmaint_genre_set")

    async def handle_gs_mapping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return
        state["source"] = "mapping"
        state["manual_genre"] = None
        await self._show_gs_mode_screen(query, context, artist)

    async def handle_gs_manual(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return
        state["source"] = "manual"
        context.user_data["libmaint_awaiting_genre_text"] = True
        await query.edit_message_text(
            f"✏️ <b>Neues Genre für {html.escape(artist)}</b>\n\n"
            "Bitte das Genre als Text senden (z. B. „Heavy Metal\" oder "
            "„Pop; Rock\" für mehrere Genres). Mit /cancel abbrechen.",
            parse_mode="HTML",
        )

    async def process_pending_genre_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        """Wird von handlers/menu/rich_menu_handler.py::handle_text_message()
        aufgerufen, WENN context.user_data["libmaint_awaiting_genre_text"]
        gesetzt ist (identisches Freitext-Übergabemuster wie Family-Chat/
        -Challenge dort). Gibt True zurück, wenn die Nachricht hier
        behandelt wurde (Aufrufer darf dann nicht mehr weiterreichen)."""
        if not context.user_data.get("libmaint_awaiting_genre_text"):
            return False

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            context.user_data.pop("libmaint_awaiting_genre_text", None)
            await update.message.reply_text(
                "⚠️ Sitzung abgelaufen — bitte über /menu erneut beginnen."
            )
            return True

        error = _validate_manual_genre_input(text)
        if error:
            await update.message.reply_text(
                f"❌ {error} Bitte erneut eingeben oder /cancel."
            )
            return True  # bleibt awaiting - erneuter Versuch möglich

        normalized = genre_domain.normalize_genre_input(text.strip())
        if not normalized:
            await update.message.reply_text(
                "❌ Genre ist nach Normalisierung leer. Bitte erneut eingeben "
                "oder /cancel."
            )
            return True

        context.user_data.pop("libmaint_awaiting_genre_text", None)
        state["manual_genre"] = normalized

        gs_text, keyboard = self._render_gs_save_or_mode_screen(context, artist)
        await update.message.reply_text(gs_text, parse_mode="HTML", reply_markup=keyboard)
        return True

    async def _show_gs_mode_screen(
        self, query, context: ContextTypes.DEFAULT_TYPE, artist: str
    ) -> None:
        text, keyboard = self._render_gs_mode_screen(context, artist)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _render_gs_mode_screen(self, context: ContextTypes.DEFAULT_TYPE, artist: str):
        state = self._gs_state(context) or {}
        onlymissing_label = "🆕 Nur wenn Genre fehlt"
        if state.get("missing_genre_flow"):
            onlymissing_label += " (empfohlen)"
        text = f"✏️ <b>Genre setzen — {html.escape(artist)}</b>\n\nModus wählen:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✏️ Genre setzen (überschreiben erlaubt)",
                callback_data="libmaint:gs:mode:overwrite",
            )],
            [InlineKeyboardButton(onlymissing_label, callback_data="libmaint:gs:mode:onlymissing")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        return text, keyboard

    def _render_gs_save_or_mode_screen(self, context: ContextTypes.DEFAULT_TYPE, artist: str):
        """Nach der manuellen Texteingabe: falls only_if_missing bereits
        beantwortet wurde (kann bei diesem Flow aktuell nicht vorkommen,
        da Text-Eingabe VOR dem Modus abgefragt wird - defensiv trotzdem
        korrekt), direkt zur Save-Frage, sonst zurück zum Modus-Screen."""
        return self._render_gs_mode_screen(context, artist)

    async def handle_gs_mode(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return
        state["only_if_missing"] = (mode == "onlymissing")

        if state.get("source") == "manual":
            text, keyboard = self._render_gs_save_screen(artist)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        placeholder = await query.edit_message_text(
            f"🔍 Erstelle Vorschau für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_gs_preview_and_report(placeholder, context, artist))
        task.add_done_callback(self._log_background_task_exception)

    def _render_gs_save_screen(self, artist: str):
        text = f"✏️ <b>Genre setzen — {html.escape(artist)}</b>\n\nMapping speichern?"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 Nur setzen", callback_data="libmaint:gs:save:no")],
            [InlineKeyboardButton(
                "💾 Setzen + Mapping speichern", callback_data="libmaint:gs:save:yes",
            )],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        return text, keyboard

    async def handle_gs_save(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, save: bool
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return
        state["save_mapping"] = save

        placeholder = await query.edit_message_text(
            f"🔍 Erstelle Vorschau für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_gs_preview_and_report(placeholder, context, artist))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_gs_preview_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, artist: str
    ) -> None:
        state = self._gs_state(context) or {}
        from_mapping = state.get("source") == "mapping"
        manual_genre = state.get("manual_genre")
        only_if_missing = bool(state.get("only_if_missing"))

        try:
            target_genre = resolve_target_genre(
                artist, genre=manual_genre, from_mapping=from_mapping,
            )
            preview = preview_set_genre(
                artist, genre=manual_genre, from_mapping=from_mapping,
                only_if_missing=only_if_missing,
            )
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Genre-Vorschau: {e}", exc_info=True)
            await self._report_error(e, "gs_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        if preview.target_count == 0:
            await message.edit_text(
                f"📁 Keine Dateien für {html.escape(artist)} gefunden.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        if preview.changed_count == 0:
            reason = (
                "bereits korrekt" if not only_if_missing else
                "Genre bereits vorhanden (only-if-missing aktiv)"
            )
            await message.edit_text(
                f"✅ {html.escape(artist)}: keine Änderung nötig "
                f"({preview.target_count} Datei(en), {reason}).",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        save_mapping = bool(state.get("save_mapping")) and state.get("source") == "manual"
        lines = [
            "🎭 <b>Genre ändern</b>",
            "",
            f"Künstler: {html.escape(artist)}",
            f"Neu: {html.escape(target_genre)}",
            f"Quelle: {'Aus Mapping' if from_mapping else 'Manuelle Eingabe'}",
            f"Mapping: {'Wird gespeichert' if save_mapping else 'Wird NICHT gespeichert'}",
            f"Modus: {'Nur wenn Genre fehlt' if only_if_missing else 'Überschreiben erlaubt'}",
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
            [InlineKeyboardButton("✅ Anwenden", callback_data="libmaint:gs:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def handle_gs_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Genre für {html.escape(artist)} wird geändert "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, AUSFÜHREN", callback_data="libmaint:gs:execute")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_gs_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Einzige Stelle, die tatsächlich eine Genre-Änderung ausführt -
        Berechtigung wird HIER erneut geprüft, Lock-Status vorab geprüft
        (Doppelklick-Schutz, identisches Muster wie handle_execute() oben)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._genre_artist(context)
        state = self._gs_state(context)
        if not artist or state is None:
            await self._genre_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"🎭 Genre wird gesetzt für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(
            self._run_gs_execute_and_report(placeholder, context, artist, dict(state), user_id)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_gs_execute_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE,
        artist: str, state: dict, user_id: int,
    ) -> None:
        from_mapping = state.get("source") == "mapping"
        manual_genre = state.get("manual_genre")
        only_if_missing = bool(state.get("only_if_missing"))
        save_mapping = bool(state.get("save_mapping")) and state.get("source") == "manual"

        try:
            result = execute_set_genre(
                artist, triggered_by=f"telegram:{user_id}", genre=manual_genre,
                from_mapping=from_mapping, only_if_missing=only_if_missing,
            )
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
            self.logger.error(f"💥 Unerwarteter Fehler beim Genre setzen: {e}", exc_info=True)
            await self._report_error(e, "gs_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        mapping_note = ""
        if save_mapping and result.success_count > 0:
            try:
                mapping_result = save_manual_genre_mapping(
                    artist, manual_genre, Path(Config.GENRE_MAPPING_DIR), dry_run=False,
                )
                if mapping_result.written:
                    mapping_note = "\n\n💾 Mapping gespeichert."
                elif mapping_result.unchanged:
                    mapping_note = "\n\n💾 Mapping bereits identisch (nicht erneut geschrieben)."
            except GenreDomainError as e:
                mapping_note = f"\n\n⚠️ Mapping-Speichern fehlgeschlagen: {html.escape(str(e))}"
                self.logger.error(f"💥 Mapping-Speichern fehlgeschlagen ({artist}): {e}")

        await message.edit_text(
            self._format_gs_result(artist, result) + mapping_note,
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    def _format_gs_result(self, artist: str, result) -> str:
        if result.status == "SUCCESS":
            emoji = "⚠️" if result.failed_count else "✅"
        elif result.status == "FAILED":
            emoji = "❌"
        else:
            emoji = "ℹ️"
        header = "Genre gesetzt" if not result.failed_count else "Genre teilweise gesetzt"
        lines = [
            f"{emoji} <b>{header}</b>",
            f"Künstler: {html.escape(artist)}",
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

    # ── 🔄 Genre revalidieren (Preview → Bestätigung → Execute, läuft
    # als Subprozess - siehe genre_revalidation_runner.py-Docstring) ────

    async def handle_gr_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        if not artist:
            await self._genre_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"🔄 Prüfe Last.fm für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_gr_preview_and_report(placeholder, artist))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_gr_preview_and_report(self, message: Message, artist: str) -> None:
        try:
            run_result = await run_genre_revalidation_subprocess(artist, apply=False)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Revalidierung: {e}", exc_info=True)
            await self._report_error(e, "gr_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        text, keyboard = self._format_gr_result(artist, run_result, applied=False)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_gr_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._genre_artist(context)
        if not artist:
            await self._genre_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Genre-Revalidierung für {html.escape(artist)} wird angewendet "
            "(Auto-Learn-Mapping wird aktualisiert).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Änderung anwenden", callback_data="libmaint:gr:execute")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_gr_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._genre_artist(context)
        if not artist:
            await self._genre_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"🔄 Revalidiere {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_gr_execute_and_report(placeholder, artist))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_gr_execute_and_report(self, message: Message, artist: str) -> None:
        try:
            run_result = await run_genre_revalidation_subprocess(artist, apply=True)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Revalidierung: {e}", exc_info=True)
            await self._report_error(e, "gr_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        text, keyboard = self._format_gr_result(artist, run_result, applied=True)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _format_gr_result(self, artist: str, run_result, *, applied: bool):
        back_kb = self._back_keyboard("libmaint:start")

        if not run_result.success:
            detail = (
                run_result.error_message or run_result.stderr_tail.strip()[-800:]
                or "Kein Fehlertext verfügbar."
            )
            text = (
                f"❌ <b>Genre-Revalidierung fehlgeschlagen</b>\n"
                f"Künstler: {html.escape(artist)}\n\n"
                f"<pre>{html.escape(detail)}</pre>"
            )
            return text, back_kb

        data = run_result.data or {}
        outcome = data.get("outcome")
        current_primary = data.get("current_primary")
        candidate_primary = data.get("candidate_primary")

        header = "🔄 <b>Genre-Revalidierung</b>" if applied else "🔄 <b>Revalidierungs-Vorschau</b>"
        lines = [
            header, "",
            f"Künstler: {html.escape(artist)}",
            f"Aktuell: {html.escape(current_primary) if current_primary else '(kein Genre)'}",
        ]
        if candidate_primary:
            lines.append(f"Neu ermittelt: {html.escape(candidate_primary)}")
            lines.append(f"Quelle: {html.escape(data.get('candidate_source') or 'lastfm')}")
        if data.get("learning_status"):
            lines.append(f"Learning Status: {html.escape(data['learning_status'])}")
        lines.append("")
        lines.append(html.escape(data.get("reason") or ""))

        if data.get("error_message"):
            lines.append("")
            lines.append(f"⚠️ {html.escape(data['error_message'])}")

        if outcome == "OVERTURN_ALLOWED":
            if applied:
                lines.append("")
                lines.append("✅ Änderung durchgeführt." if data.get("mutated") else "ℹ️ Keine Mutation durchgeführt.")
                return "\n".join(lines), back_kb
            lines.append("")
            lines.append("Noch keine Änderungen durchgeführt.")
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Änderung anwenden", callback_data="libmaint:gr:confirm")],
                [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
            ])
            return "\n".join(lines), keyboard

        lines.append("")
        lines.append(
            "ℹ️ Keine Änderung erforderlich" if outcome == "SAME_GENRE" else
            "ℹ️ Keine Änderung möglich"
        )
        return "\n".join(lines), back_kb

    # ═════════════════════════════════════════════════════════════════
    # 📝 METADATEN BEARBEITEN (Manual Metadata Editing v1 + v2)
    # ═════════════════════════════════════════════════════════════════
    #
    # Session-Status in context.user_data (identisches Prinzip wie die
    # Genre-Verwaltung oben):
    #   libmaint_meta_artist          -> str, aktuell gewählter Artist
    #   libmaint_meta_track           -> str, relativer Pfad des gewählten
    #       Tracks (NUR Titel bearbeiten - kommt ausschließlich aus
    #       resolve_track_by_index(), kein Rohpfad aus callback_data)
    #   libmaint_meta_current_title   -> str, aktueller Titel-Tag-Wert des
    #       gewählten Tracks (NUR Anzeige in der Preview)
    #   libmaint_meta_album           -> str, gewählter Album-Verzeichnis-
    #       name (Album bearbeiten UND Albuminterpret bearbeiten - kommt
    #       ausschließlich aus resolve_album_by_index())
    #   libmaint_meta_current_album          -> str, aktueller ©alb-
    #       Repräsentativwert (NUR Album bearbeiten, Anzeige)
    #   libmaint_meta_current_album_artist   -> str, aktueller aART-
    #       Repräsentativwert (NUR Albuminterpret bearbeiten, Anzeige)
    #   libmaint_meta_new_value       -> str, validierter neuer Zielwert
    #       (Artist-Name/Titel/Albumname/Albuminterpret, je nach aktivem
    #       Flow)
    #   libmaint_awaiting_artist_text      -> True, während auf die
    #       manuelle Artist-Eingabe gewartet wird
    #   libmaint_awaiting_title_text       -> True, während auf die
    #       manuelle Titel-Eingabe gewartet wird
    #   libmaint_awaiting_album_text       -> True, während auf die
    #       manuelle Albumname-Eingabe gewartet wird
    #   libmaint_awaiting_albumartist_text -> True, während auf die
    #       manuelle Albuminterpret-Eingabe gewartet wird
    #
    # Terminal-/Fehlerpfade führen bewusst einheitlich zurück zu
    # "libmaint:start" (identisches Prinzip wie die gs:*/gr:*-Flows oben -
    # hält die Zustandsverwaltung klein).
    #
    # State Cleanup (Auftrag v2 §27, Review-Fund aus v1): JEDER neue
    # Flow-Einstiegspunkt (handle_meta_artist_start()/handle_meta_title_
    # pick()/handle_meta_album_pick()/handle_meta_albumartist_pick())
    # ruft _reset_meta_edit_state() VOR dem Setzen seines eigenen
    # awaiting-Flags auf - verhindert, dass ein abgebrochener Flow (z. B.
    # Artist bearbeiten gestartet, dann ohne Abschluss zu Titel
    # bearbeiten gewechselt) sein awaiting-Flag/seinen Zielwert an einen
    # später gestarteten, anderen Flow "vererbt" (reales Szenario: ohne
    # diesen Reset würde eine anschließend eingegebene Titel-Eingabe vom
    # noch aktiven Artist-awaiting-Flag abgefangen und fälschlich als
    # Artist-Umbenennung interpretiert - handle_text_message() prüft die
    # Flags in fester Reihenfolge).

    def _meta_artist(self, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        return context.user_data.get("libmaint_meta_artist")

    def _reset_meta_edit_state(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        for key in (
            "libmaint_meta_track",
            "libmaint_meta_current_title",
            "libmaint_meta_album",
            "libmaint_meta_current_album",
            "libmaint_meta_current_album_artist",
            "libmaint_meta_new_value",
            "libmaint_awaiting_artist_text",
            "libmaint_awaiting_title_text",
            "libmaint_awaiting_album_text",
            "libmaint_awaiting_albumartist_text",
        ):
            context.user_data.pop(key, None)

    async def _meta_session_expired(self, query) -> None:
        await query.edit_message_text(
            "⚠️ Sitzung abgelaufen — bitte Artist erneut wählen.",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    def _album_display_label(self, album: str) -> str:
        """Anzeige-Label fuer einen Album-Kontext (Auftrag/Nutzer-Fund
        2026-09-20: list_artist_albums() liefert fuer Singles
        "<Singles-Ordner>/<Dateiname>" statt eines Verzeichnisnamens - ein
        "/" im Wert kommt AUSSCHLIESSLICH von einer Single, da echte
        Album-Verzeichnisnamen aus iterdir() nie "/" enthalten koennen).
        `album` selbst (der Rohwert) bleibt unveraendert der an
        preview_*/execute_*/current_*() uebergebene Bezeichner - nur die
        TELEGRAM-ANZEIGE wird hier huebscher aufbereitet."""
        if "/" in album:
            return f"{Path(album).stem} (Single)"
        return album

    def _format_manual_edit_result(
        self, header_ok: str, header_partial: str, artist: str, result,
    ) -> str:
        """Gemeinsame Ergebnis-Formatierung fuer Artist-Rename und
        Title-Edit (identisches MaintenanceRunResult-Shape wie
        _format_result()/_format_gs_result() oben - eigene Funktion statt
        Wiederverwendung, da jene an eine feste, andere Kopfzeile
        gebunden sind)."""
        if result.status == "SUCCESS":
            emoji = "⚠️" if result.failed_count else "✅"
        elif result.status == "FAILED":
            emoji = "❌"
        else:
            emoji = "ℹ️"
        header = header_partial if result.failed_count else header_ok
        lines = [
            f"{emoji} <b>{header}</b>",
            f"Künstler: {html.escape(artist)}",
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

    # ── Einstieg: Metadaten bearbeiten für EINEN Artist ─────────────────

    async def handle_meta_menu(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        context.user_data["libmaint_meta_artist"] = artist
        self._reset_meta_edit_state(context)

        text = f"📝 <b>Metadaten bearbeiten — {html.escape(artist)}</b>\n\nWähle eine Aktion:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎤 Artist bearbeiten", callback_data=f"libmaint:meta:artist:{idx}")],
            [InlineKeyboardButton("🎵 Titel bearbeiten", callback_data=f"libmaint:meta:title:{idx}")],
            [InlineKeyboardButton("💿 Album bearbeiten", callback_data=f"libmaint:meta:album:{idx}")],
            [InlineKeyboardButton(
                "👤 Albuminterpret bearbeiten", callback_data=f"libmaint:meta:albumartist:{idx}",
            )],
            [InlineKeyboardButton("🎭 Genre-Verwaltung", callback_data=f"libmaint:genremenu:{idx}")],
            [InlineKeyboardButton("◀️ Zurück", callback_data=f"libmaint:pick:{idx}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── 🎤 Artist bearbeiten (Auftrag Abschnitt 5-7) ────────────────────

    async def handle_meta_artist_start(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        self._reset_meta_edit_state(context)
        context.user_data["libmaint_meta_artist"] = artist
        context.user_data["libmaint_awaiting_artist_text"] = True
        await query.edit_message_text(
            f"🎤 <b>Artist bearbeiten</b>\n\n"
            f"Aktueller Artist:\n{html.escape(artist)}\n\n"
            "Neuen Artist-Namen eingeben. Mit /cancel abbrechen.",
            parse_mode="HTML",
        )

    async def process_pending_artist_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        """Wird von handlers/menu/rich_menu_handler.py::handle_text_message()
        aufgerufen, WENN context.user_data["libmaint_awaiting_artist_text"]
        gesetzt ist (identisches Freitext-Übergabemuster wie
        process_pending_genre_input()). Gibt True zurück, wenn die
        Nachricht hier behandelt wurde."""
        if not context.user_data.get("libmaint_awaiting_artist_text"):
            return False

        artist = self._meta_artist(context)
        if not artist:
            context.user_data.pop("libmaint_awaiting_artist_text", None)
            await update.message.reply_text(
                "⚠️ Sitzung abgelaufen — bitte über /menu erneut beginnen."
            )
            return True

        error = _validate_manual_meta_input(text, label="den Artist-Namen")
        if error:
            await update.message.reply_text(f"❌ {error} Bitte erneut eingeben oder /cancel.")
            return True  # bleibt awaiting - erneuter Versuch möglich

        new_artist = text.strip()
        context.user_data.pop("libmaint_awaiting_artist_text", None)
        context.user_data["libmaint_meta_new_value"] = new_artist

        placeholder = await update.message.reply_text(
            f"🔍 Erstelle Vorschau für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(
            self._run_artist_rename_preview_and_report(placeholder, artist, new_artist)
        )
        task.add_done_callback(self._log_background_task_exception)
        return True

    async def _run_artist_rename_preview_and_report(
        self, message: Message, artist: str, new_artist: str
    ) -> None:
        try:
            preview = preview_artist_rename(artist, new_artist)
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Artist-Vorschau: {e}", exc_info=True)
            await self._report_error(e, "meta_artist_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        if preview.target_count == 0:
            await message.edit_text(
                f"📁 Keine Dateien für {html.escape(artist)} gefunden.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        if preview.changed_count == 0:
            # Artist-Rename ist tag-wert-getrieben (Auftrag §7/§15,
            # normalize_values() gegen den casefold-Wert des gewaehlten
            # Ausgangs-Artist) - "keine Aenderung" kann hier entweder
            # "Wert bereits korrekt" ODER "kein Datei-Tag entspricht
            # aktuell exakt diesem Ausgangswert" bedeuten (Review-Fund:
            # eine pauschale "bereits korrekt"-Meldung waere in letzterem
            # Fall irrefuehrend). Safety-Skips (Datei nicht mehr
            # verfuegbar) werden zusaetzlich separat gemeldet, identisches
            # Prinzip wie beim Titel-Edit unten.
            safety_skipped = [
                o for o in preview.outcomes
                if o.reason and o.reason.startswith("Safety:")
            ]
            if safety_skipped and len(safety_skipped) == len(preview.outcomes):
                await message.edit_text(
                    f"📁 Keine der {preview.target_count} Datei(en) ist aktuell "
                    "verfügbar/lesbar — bitte erneut prüfen.",
                    reply_markup=self._back_keyboard("libmaint:start"),
                )
                return
            await message.edit_text(
                "ℹ️ Keine Änderung nötig: kein Artist-Tag entspricht aktuell "
                f"exakt „{html.escape(artist)}\", oder der Wert war bereits korrekt "
                f"({preview.target_count} Datei(en) geprüft).",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        lines = [
            "🔍 <b>Änderung prüfen</b>", "",
            "Artist:",
            html.escape(artist),
            "↓",
            html.escape(new_artist),
            "",
            f"Betroffene Dateien: {preview.changed_count}",
        ]
        changed = [o for o in preview.outcomes if o.status == "DRY_RUN"]
        for oc in changed[:10]:
            lines.append(f"  • {html.escape(oc.file)}")
        if len(changed) > 10:
            lines.append(f"  … {len(changed) - 10} weitere")
        lines.append("")
        lines.append("Noch keine Änderungen durchgeführt.")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ausführen", callback_data="libmaint:meta:artist:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_artist_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._meta_artist(context)
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not new_value:
            await self._meta_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Artist wird geändert:\n{html.escape(artist)} → {html.escape(new_value)}\n\n"
            "Diese Aktion verändert Tags in deiner Music Library "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, AUSFÜHREN", callback_data="libmaint:meta:artist:execute")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_artist_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einzige Stelle, die tatsächlich einen Artist-Rename ausführt -
        Berechtigung wird HIER erneut geprüft, Lock-Status vorab geprüft
        (Doppelklick-Schutz, identisches Muster wie handle_execute() oben)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._meta_artist(context)
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not new_value:
            await self._meta_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"🎤 Artist wird geändert für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(
            self._run_artist_rename_execute_and_report(placeholder, context, artist, new_value, user_id)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_artist_rename_execute_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE,
        artist: str, new_value: str, user_id: int,
    ) -> None:
        try:
            result = execute_artist_rename(artist, new_value, triggered_by=f"telegram:{user_id}")
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
            self.logger.error(f"💥 Unerwarteter Fehler beim Artist-Rename: {e}", exc_info=True)
            await self._report_error(e, "meta_artist_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        context.user_data.pop("libmaint_meta_new_value", None)
        await message.edit_text(
            self._format_manual_edit_result(
                "Artist geändert", "Artist teilweise geändert", artist, result,
            ),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    # ── 🎵 Titel bearbeiten (Auftrag Abschnitt 8/9/16) ──────────────────

    async def handle_meta_title_start(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        tracks = artist_targets(artist)
        if not tracks:
            await query.edit_message_text(
                f"📁 Keine Tracks für {html.escape(artist)} gefunden.",
                reply_markup=self._back_keyboard(f"libmaint:meta:{idx}"),
            )
            return

        context.user_data["libmaint_meta_artist"] = artist
        # Defensive Kappung (Review-Fund): _META_PICKER_LIMIT verhindert
        # ein zu grosses InlineKeyboardMarkup (Telegram Bad Request) bei
        # sehr vielen Tracks - tidx bleibt der echte Index in `tracks`
        # (Slice von vorne, resolve_track_by_index() loest gegen dieselbe
        # vollstaendige Liste erneut auf).
        shown = tracks[:_META_PICKER_LIMIT]
        buttons = [
            [InlineKeyboardButton(
                f"🎵 {Path(rel).stem[:60]}", callback_data=f"libmaint:meta:title:pick:{idx}:{tidx}",
            )]
            for tidx, rel in enumerate(shown)
        ]
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data=f"libmaint:meta:{idx}")])
        note = (
            f" (nur die ersten {_META_PICKER_LIMIT} angezeigt)"
            if len(tracks) > _META_PICKER_LIMIT else ""
        )
        await query.edit_message_text(
            f"🎵 <b>Titel bearbeiten — {html.escape(artist)}</b>\n\n"
            f"{len(tracks)} Track(s) gefunden{note} — Track wählen:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def handle_meta_title_pick(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int, track_idx: int
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

        rel = resolve_track_by_index(artist, track_idx)
        if rel is None:
            await query.edit_message_text(
                "⚠️ Track nicht mehr gefunden (Liste hat sich geändert) — "
                "bitte erneut wählen.",
                reply_markup=self._back_keyboard(f"libmaint:meta:title:{idx}"),
            )
            return

        try:
            title_now = current_title(rel)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler beim Titel-Lesen: {e}", exc_info=True)
            await self._report_error(e, "meta_title_read")
            await query.edit_message_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        self._reset_meta_edit_state(context)
        context.user_data["libmaint_meta_artist"] = artist
        context.user_data["libmaint_meta_track"] = rel
        context.user_data["libmaint_meta_current_title"] = title_now
        context.user_data["libmaint_awaiting_title_text"] = True
        await query.edit_message_text(
            f"🎵 <b>Titel bearbeiten</b>\n\n"
            f"Datei:\n{html.escape(rel)}\n\n"
            f"Aktueller Titel:\n{html.escape(title_now) if title_now else '(kein Titel)'}\n\n"
            "Neuen Titel eingeben. Mit /cancel abbrechen.",
            parse_mode="HTML",
        )

    async def process_pending_title_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        """Wird von handlers/menu/rich_menu_handler.py::handle_text_message()
        aufgerufen, WENN context.user_data["libmaint_awaiting_title_text"]
        gesetzt ist. Gibt True zurück, wenn die Nachricht hier behandelt
        wurde."""
        if not context.user_data.get("libmaint_awaiting_title_text"):
            return False

        artist = self._meta_artist(context)
        rel = context.user_data.get("libmaint_meta_track")
        current = context.user_data.get("libmaint_meta_current_title") or ""
        if not artist or not rel:
            context.user_data.pop("libmaint_awaiting_title_text", None)
            await update.message.reply_text(
                "⚠️ Sitzung abgelaufen — bitte über /menu erneut beginnen."
            )
            return True

        error = _validate_manual_meta_input(text, label="den Titel")
        if error:
            await update.message.reply_text(f"❌ {error} Bitte erneut eingeben oder /cancel.")
            return True  # bleibt awaiting - erneuter Versuch möglich

        new_title = text.strip()
        context.user_data.pop("libmaint_awaiting_title_text", None)
        context.user_data["libmaint_meta_new_value"] = new_title

        placeholder = await update.message.reply_text(
            f"🔍 Erstelle Vorschau für {html.escape(rel)} ..."
        )
        task = asyncio.create_task(
            self._run_title_edit_preview_and_report(placeholder, artist, rel, current, new_title)
        )
        task.add_done_callback(self._log_background_task_exception)
        return True

    async def _run_title_edit_preview_and_report(
        self, message: Message, artist: str, rel: str, current: str, new_title: str,
    ) -> None:
        try:
            preview = preview_title_edit(artist, rel, new_title)
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Titel-Vorschau: {e}", exc_info=True)
            await self._report_error(e, "meta_title_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        if preview.changed_count == 0:
            # target_count ist bei Title-Edit immer 1 (Scope = genau eine
            # Datei) - "keine Aenderung" kann daher entweder "identischer
            # Wert" ODER "Datei zwischen Track-Auswahl und Eingabe
            # verschwunden" bedeuten (safety_check() in apply_title_edit()
            # liefert dafuer einen "Safety: ..."-Grund). Beide Faelle
            # bleiben read-only-sicher (nichts wird geschrieben), aber
            # verdienen unterschiedliche Rueckmeldungen (Auftrag §14).
            skip = preview.outcomes[0] if preview.outcomes else None
            if skip is not None and skip.reason and skip.reason.startswith("Safety:"):
                await message.edit_text(
                    f"📁 Datei nicht mehr verfügbar ({html.escape(skip.reason)}) — "
                    "bitte erneut wählen.",
                    reply_markup=self._back_keyboard("libmaint:start"),
                )
                return
            await message.edit_text(
                "✅ Der neue Wert entspricht bereits dem aktuellen Wert "
                "(keine Änderung nötig).",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        lines = [
            "🔍 <b>Änderung prüfen</b>", "",
            "Datei:", html.escape(rel), "",
            "Titel:",
            html.escape(current) if current else "(kein Titel)",
            "↓",
            html.escape(new_title),
            "",
            "Noch keine Änderungen durchgeführt.",
        ]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ausführen", callback_data="libmaint:meta:title:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_title_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._meta_artist(context)
        rel = context.user_data.get("libmaint_meta_track")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not rel or not new_value:
            await self._meta_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Titel wird geändert für:\n{html.escape(rel)}\n\n"
            "Diese Aktion verändert Tags in deiner Music Library "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, AUSFÜHREN", callback_data="libmaint:meta:title:execute")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_title_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einzige Stelle, die tatsächlich einen Title-Edit ausführt -
        Berechtigung wird HIER erneut geprüft, Lock-Status vorab geprüft."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._meta_artist(context)
        rel = context.user_data.get("libmaint_meta_track")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not rel or not new_value:
            await self._meta_session_expired(query)
            return

        placeholder = await query.edit_message_text("🎵 Titel wird geändert ...")
        task = asyncio.create_task(
            self._run_title_edit_execute_and_report(placeholder, context, artist, rel, new_value, user_id)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_title_edit_execute_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE,
        artist: str, rel: str, new_value: str, user_id: int,
    ) -> None:
        try:
            result = execute_title_edit(
                artist, rel, new_value, triggered_by=f"telegram:{user_id}",
            )
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
            self.logger.error(f"💥 Unerwarteter Fehler beim Title-Edit: {e}", exc_info=True)
            await self._report_error(e, "meta_title_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        context.user_data.pop("libmaint_meta_new_value", None)
        context.user_data.pop("libmaint_meta_track", None)
        context.user_data.pop("libmaint_meta_current_title", None)
        await message.edit_text(
            self._format_manual_edit_result(
                "Titel geändert", "Titel teilweise geändert", artist, result,
            ),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    # ── 💿 Album bearbeiten (Manual Metadata Editing v2, Auftrag §6-9) ──

    async def _show_album_picker(
        self, query, context: ContextTypes.DEFAULT_TYPE, idx: int, artist: str, next_prefix: str,
    ) -> bool:
        """Zeigt die Album-Auswahl fuer `artist` - gemeinsam genutzt von
        Album bearbeiten UND Albuminterpret bearbeiten (`next_prefix`
        bestimmt die Callback-Route der Buttons, z. B.
        "libmaint:meta:album:pick" bzw. "libmaint:meta:albumartist:pick").
        Gibt False zurueck (und hat bereits eine Meldung gezeigt), wenn
        keine Alben gefunden wurden."""
        albums = list_artist_albums(artist)
        if not albums:
            await query.edit_message_text(
                f"📁 Keine Alben oder Singles für {html.escape(artist)} gefunden.",
                reply_markup=self._back_keyboard(f"libmaint:meta:{idx}"),
            )
            return False

        shown = albums[:_META_PICKER_LIMIT]
        buttons = [
            [InlineKeyboardButton(
                f"🎵 {self._album_display_label(name)[:55]}" if "/" in name
                else f"💿 {name[:60]}",
                callback_data=f"{next_prefix}:{idx}:{aidx}",
            )]
            for aidx, name in enumerate(shown)
        ]
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data=f"libmaint:meta:{idx}")])
        note = (
            f" (nur die ersten {_META_PICKER_LIMIT} angezeigt)"
            if len(albums) > _META_PICKER_LIMIT else ""
        )
        await query.edit_message_text(
            f"💿 <b>Album auswählen — {html.escape(artist)}</b>\n\n"
            f"{len(albums)} Album(en) gefunden{note}:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return True

    async def handle_meta_album_start(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        context.user_data["libmaint_meta_artist"] = artist
        await self._show_album_picker(query, context, idx, artist, "libmaint:meta:album:pick")

    async def handle_meta_album_pick(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int, album_idx: int
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

        album = resolve_album_by_index(artist, album_idx)
        if album is None:
            await query.edit_message_text(
                "⚠️ Album nicht mehr gefunden (Liste hat sich geändert) — "
                "bitte erneut wählen.",
                reply_markup=self._back_keyboard(f"libmaint:meta:album:{idx}"),
            )
            return

        try:
            album_now = current_album(artist, album)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler beim Album-Lesen: {e}", exc_info=True)
            await self._report_error(e, "meta_album_read")
            await query.edit_message_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        self._reset_meta_edit_state(context)
        context.user_data["libmaint_meta_artist"] = artist
        context.user_data["libmaint_meta_album"] = album
        context.user_data["libmaint_meta_current_album"] = album_now
        context.user_data["libmaint_awaiting_album_text"] = True
        await query.edit_message_text(
            f"💿 <b>Album bearbeiten</b>\n\n"
            f"Album:\n{html.escape(self._album_display_label(album))}\n\n"
            f"Aktueller Albumname:\n{html.escape(album_now) if album_now else '(kein Albumname)'}\n\n"
            "Neuen Albumnamen eingeben. Mit /cancel abbrechen.",
            parse_mode="HTML",
        )

    async def process_pending_album_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        """Wird von handlers/menu/rich_menu_handler.py::handle_text_message()
        aufgerufen, WENN context.user_data["libmaint_awaiting_album_text"]
        gesetzt ist. Gibt True zurück, wenn die Nachricht hier behandelt
        wurde."""
        if not context.user_data.get("libmaint_awaiting_album_text"):
            return False

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        current = context.user_data.get("libmaint_meta_current_album") or ""
        if not artist or not album:
            context.user_data.pop("libmaint_awaiting_album_text", None)
            await update.message.reply_text(
                "⚠️ Sitzung abgelaufen — bitte über /menu erneut beginnen."
            )
            return True

        error = _validate_manual_meta_input(text, label="den Albumnamen")
        if error:
            await update.message.reply_text(f"❌ {error} Bitte erneut eingeben oder /cancel.")
            return True  # bleibt awaiting - erneuter Versuch möglich

        new_album = text.strip()
        context.user_data.pop("libmaint_awaiting_album_text", None)
        context.user_data["libmaint_meta_new_value"] = new_album

        placeholder = await update.message.reply_text(
            f"🔍 Erstelle Vorschau für {html.escape(self._album_display_label(album))} ..."
        )
        task = asyncio.create_task(
            self._run_album_edit_preview_and_report(placeholder, artist, album, current, new_album)
        )
        task.add_done_callback(self._log_background_task_exception)
        return True

    async def _run_album_edit_preview_and_report(
        self, message: Message, artist: str, album: str, current: str, new_album: str,
    ) -> None:
        try:
            preview = preview_album_edit(artist, album, new_album)
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Album-Vorschau: {e}", exc_info=True)
            await self._report_error(e, "meta_album_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        if preview.target_count == 0:
            await message.edit_text(
                f"📁 Keine Dateien mehr für {html.escape(self._album_display_label(album))} "
                "gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        if preview.changed_count == 0:
            safety_skipped = [
                o for o in preview.outcomes
                if o.reason and o.reason.startswith("Safety:")
            ]
            if safety_skipped and len(safety_skipped) == len(preview.outcomes):
                await message.edit_text(
                    f"📁 Keine der {preview.target_count} Datei(en) ist aktuell "
                    "verfügbar/lesbar — bitte erneut prüfen.",
                    reply_markup=self._back_keyboard("libmaint:start"),
                )
                return
            await message.edit_text(
                "✅ Der neue Wert entspricht bereits dem aktuellen Wert "
                f"({preview.target_count} Datei(en) geprüft, keine Änderung nötig).",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        lines = [
            "🔍 <b>Änderung prüfen</b>", "",
            "Album:", html.escape(self._album_display_label(album)), "",
            "Albumname:",
            html.escape(current) if current else "(kein Albumname)",
            "↓",
            html.escape(new_album),
            "",
            f"Betroffene Tracks: {preview.changed_count}",
            f"Betroffene Dateien: {preview.changed_count}",
            "", "Noch keine Änderungen durchgeführt.",
        ]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ausführen", callback_data="libmaint:meta:album:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_album_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not album or not new_value:
            await self._meta_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Album {html.escape(self._album_display_label(album))} wird geändert:\n"
            f"Albumname → {html.escape(new_value)}\n\n"
            "Diese Aktion verändert Tags in deiner Music Library "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, AUSFÜHREN", callback_data="libmaint:meta:album:execute")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_album_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einzige Stelle, die tatsächlich einen Album-Edit ausführt -
        Berechtigung wird HIER erneut geprüft, Lock-Status vorab geprüft."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not album or not new_value:
            await self._meta_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"💿 Album wird geändert für {html.escape(self._album_display_label(album))} ..."
        )
        task = asyncio.create_task(
            self._run_album_edit_execute_and_report(
                placeholder, context, artist, album, new_value, user_id,
            )
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_album_edit_execute_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE,
        artist: str, album: str, new_album: str, user_id: int,
    ) -> None:
        try:
            result = execute_album_edit(
                artist, album, new_album, triggered_by=f"telegram:{user_id}",
            )
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
            self.logger.error(f"💥 Unerwarteter Fehler beim Album-Edit: {e}", exc_info=True)
            await self._report_error(e, "meta_album_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        context.user_data.pop("libmaint_meta_new_value", None)
        context.user_data.pop("libmaint_meta_album", None)
        context.user_data.pop("libmaint_meta_current_album", None)
        await message.edit_text(
            self._format_manual_edit_result(
                "Album geändert", "Album teilweise geändert", artist, result,
            ),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )

    # ── 👤 Albuminterpret bearbeiten (Manual Metadata Editing v2,
    # Auftrag §10-13) ─────────────────────────────────────────────────

    async def handle_meta_albumartist_start(
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
                "⚠️ Artist nicht mehr gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:artists"),
            )
            return

        context.user_data["libmaint_meta_artist"] = artist
        await self._show_album_picker(query, context, idx, artist, "libmaint:meta:albumartist:pick")

    async def handle_meta_albumartist_pick(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int, album_idx: int
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

        album = resolve_album_by_index(artist, album_idx)
        if album is None:
            await query.edit_message_text(
                "⚠️ Album nicht mehr gefunden (Liste hat sich geändert) — "
                "bitte erneut wählen.",
                reply_markup=self._back_keyboard(f"libmaint:meta:albumartist:{idx}"),
            )
            return

        try:
            album_artist_now = current_album_artist(artist, album)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler beim Albuminterpret-Lesen: {e}", exc_info=True)
            await self._report_error(e, "meta_albumartist_read")
            await query.edit_message_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        self._reset_meta_edit_state(context)
        context.user_data["libmaint_meta_artist"] = artist
        context.user_data["libmaint_meta_album"] = album
        context.user_data["libmaint_meta_current_album_artist"] = album_artist_now
        context.user_data["libmaint_awaiting_albumartist_text"] = True
        await query.edit_message_text(
            f"👤 <b>Albuminterpret bearbeiten</b>\n\n"
            f"Album:\n{html.escape(self._album_display_label(album))}\n\n"
            "Aktueller Albuminterpret:\n"
            f"{html.escape(album_artist_now) if album_artist_now else '(kein Albuminterpret)'}\n\n"
            "Neuen Albuminterpret eingeben. Mit /cancel abbrechen.",
            parse_mode="HTML",
        )

    async def process_pending_albumartist_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> bool:
        """Wird von handlers/menu/rich_menu_handler.py::handle_text_message()
        aufgerufen, WENN context.user_data["libmaint_awaiting_albumartist_text"]
        gesetzt ist. Gibt True zurück, wenn die Nachricht hier behandelt
        wurde."""
        if not context.user_data.get("libmaint_awaiting_albumartist_text"):
            return False

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        current = context.user_data.get("libmaint_meta_current_album_artist") or ""
        if not artist or not album:
            context.user_data.pop("libmaint_awaiting_albumartist_text", None)
            await update.message.reply_text(
                "⚠️ Sitzung abgelaufen — bitte über /menu erneut beginnen."
            )
            return True

        error = _validate_manual_meta_input(text, label="den Albuminterpret")
        if error:
            await update.message.reply_text(f"❌ {error} Bitte erneut eingeben oder /cancel.")
            return True  # bleibt awaiting - erneuter Versuch möglich

        new_album_artist = text.strip()
        context.user_data.pop("libmaint_awaiting_albumartist_text", None)
        context.user_data["libmaint_meta_new_value"] = new_album_artist

        placeholder = await update.message.reply_text(
            f"🔍 Erstelle Vorschau für {html.escape(self._album_display_label(album))} ..."
        )
        task = asyncio.create_task(
            self._run_album_artist_edit_preview_and_report(
                placeholder, artist, album, current, new_album_artist,
            )
        )
        task.add_done_callback(self._log_background_task_exception)
        return True

    async def _run_album_artist_edit_preview_and_report(
        self, message: Message, artist: str, album: str, current: str, new_album_artist: str,
    ) -> None:
        try:
            preview = preview_album_artist_edit(artist, album, new_album_artist)
        except MaintenanceServiceError as e:
            await message.edit_text(
                f"❌ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Albuminterpret-Vorschau: {e}", exc_info=True)
            await self._report_error(e, "meta_albumartist_preview")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        if preview.target_count == 0:
            await message.edit_text(
                f"📁 Keine Dateien mehr für {html.escape(self._album_display_label(album))} "
                "gefunden — bitte erneut wählen.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return
        if preview.changed_count == 0:
            safety_skipped = [
                o for o in preview.outcomes
                if o.reason and o.reason.startswith("Safety:")
            ]
            if safety_skipped and len(safety_skipped) == len(preview.outcomes):
                await message.edit_text(
                    f"📁 Keine der {preview.target_count} Datei(en) ist aktuell "
                    "verfügbar/lesbar — bitte erneut prüfen.",
                    reply_markup=self._back_keyboard("libmaint:start"),
                )
                return
            await message.edit_text(
                "✅ Der neue Wert entspricht bereits dem aktuellen Wert "
                f"({preview.target_count} Datei(en) geprüft, keine Änderung nötig).",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        lines = [
            "🔍 <b>Änderung prüfen</b>", "",
            "Album:", html.escape(self._album_display_label(album)), "",
            "Albuminterpret:",
            html.escape(current) if current else "(kein Albuminterpret)",
            "↓",
            html.escape(new_album_artist),
            "",
            f"Betroffene Tracks: {preview.changed_count}",
            f"Betroffene Dateien: {preview.changed_count}",
            "", "Noch keine Änderungen durchgeführt.",
        ]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ausführen", callback_data="libmaint:meta:albumartist:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="libmaint:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_albumartist_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not album or not new_value:
            await self._meta_session_expired(query)
            return

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Albuminterpret für Album {html.escape(self._album_display_label(album))} wird "
            f"geändert:\nAlbuminterpret → {html.escape(new_value)}\n\n"
            "Der normale Artist-Tag (©ART) bleibt dabei unverändert.\n\n"
            "Diese Aktion verändert Tags in deiner Music Library "
            "(Backup + Journal + Audio-Essenz-Verifikation vor jeder "
            "Übernahme).\n\nFortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ JA, AUSFÜHREN", callback_data="libmaint:meta:albumartist:execute",
            )],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="libmaint:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_meta_albumartist_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einzige Stelle, die tatsächlich einen Album-Artist-Edit
        ausführt - Berechtigung wird HIER erneut geprüft, Lock-Status
        vorab geprüft."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if is_repair_running():
            await query.edit_message_text(
                "🔒 Eine andere Reparatur/Wartung läuft gerade — bitte "
                "warten, bis diese abgeschlossen ist.",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        artist = self._meta_artist(context)
        album = context.user_data.get("libmaint_meta_album")
        new_value = context.user_data.get("libmaint_meta_new_value")
        if not artist or not album or not new_value:
            await self._meta_session_expired(query)
            return

        placeholder = await query.edit_message_text(
            f"👤 Albuminterpret wird geändert für {html.escape(self._album_display_label(album))} ..."
        )
        task = asyncio.create_task(
            self._run_album_artist_edit_execute_and_report(
                placeholder, context, artist, album, new_value, user_id,
            )
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_album_artist_edit_execute_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE,
        artist: str, album: str, new_album_artist: str, user_id: int,
    ) -> None:
        try:
            result = execute_album_artist_edit(
                artist, album, new_album_artist, triggered_by=f"telegram:{user_id}",
            )
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
            self.logger.error(f"💥 Unerwarteter Fehler beim Album-Artist-Edit: {e}", exc_info=True)
            await self._report_error(e, "meta_albumartist_execute")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("libmaint:start"),
            )
            return

        context.user_data.pop("libmaint_meta_new_value", None)
        context.user_data.pop("libmaint_meta_album", None)
        context.user_data.pop("libmaint_meta_current_album_artist", None)
        await message.edit_text(
            self._format_manual_edit_result(
                "Albuminterpret geändert", "Albuminterpret teilweise geändert", artist, result,
            ),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("libmaint:start"),
        )
