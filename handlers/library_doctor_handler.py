# handlers/library_doctor_handler.py
# -*- coding: utf-8 -*-
"""
🩺 MUSICBOT DOCTOR MENÜ-HANDLER (Phase 3, P1.3)

Telegram-Oberfläche für scripts/library_health_check.py (Health-Scan) und
scripts/library_repair.py --level SAFE_AUTOMATIC --apply (verlustfreie
Tag-/Rename-Fixes). Ruft beide Skripte ausschließlich als eigenständige
Subprozesse auf (services/library_repair/doctor_runner.py) - importiert
sie nie direkt, exakt dasselbe Muster wie
handlers/menu/reprocessing_menu_handler.py für
scripts/reprocess_artist_metadata.py.

Nur für Admins sichtbar/nutzbar (Config.OWNER_USER_ID/ADMIN_USER_IDS) -
der Apply-Zweig schreibt echte Tag-/Dateinamen-Änderungen in die
Produktions-Library (mit Backup + Journal + Verification-Scan aus
Phase 2, aber eine echte Mutation ist es trotzdem).

Ablauf: Scan-Button -> Health-Zusammenfassung mit "SAFE_AUTOMATIC
anwenden"-Button -> Bestätigung -> Apply-Lauf -> Ergebnis. Jeder
Subprozess-Lauf läuft als eigenständiger Hintergrund-Task
(asyncio.create_task), analog zu rich_menu_handler.py::_process_url() -
verhindert, dass ein mehrminütiger Lauf alle anderen Telegram-Updates
blockiert (die Application läuft ohne concurrent_updates=True).

Bewusst NUR SAFE_AUTOMATIC über diesen Weg erreichbar - alle externen/
destruktiven Repair-Level (COVER/EXTERNAL_METADATA/METADATA_REPROCESSING/
LOUDNESS/DUPLICATE) bleiben CLI-only, siehe docs/LIBRARY_REPAIR.md §3.
"""

import html
from typing import Callable, Optional, TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from handlers.menu.permissions import is_admin_or_owner
from services.library_health.issues import REGISTRY as ISSUE_REGISTRY
from services.library_health.models import Severity
from services.library_repair.doctor_runner import (
    DoctorRepairResult,
    DoctorScanResult,
    run_health_scan,
    run_safe_automatic_repair,
)

# Reine Anzeige-Zuordnung Health-Status -> Ampel-Emoji (Statusbänder selbst
# kommen unveraendert aus services/library_health/scoring.py - hier wird
# nur der bereits im Report vorhandene Status-String eingefaerbt, keine
# eigene Schwellenwert-Logik).
_STATUS_EMOJI = {
    "EXCELLENT": "🟢", "GOOD": "🟢", "FAIR": "🟡",
    "POOR": "🟠", "CRITICAL": "🔴", "UNSCORED": "⚪",
}


def _short_issue_label(description: str, max_len: int = 110) -> str:
    """Kuerzt eine Issue-Beschreibung aus services/library_health/issues.py
    fuer die Chat-Anzeige. Die Registry-Texte sind bewusst engineering-
    ausfuehrlich (Begruendung, Regex-Referenzen, Folgeverhalten) - das ist
    fuer die technische Doku richtig, aber zu lang fuer eine Telegram-
    Zeile. Nimmt nur den ersten Satz/Halbsatz (bis ". " bzw. " — ") und
    deckelt zusaetzlich hart auf max_len, an einer Wortgrenze."""
    for sep in (" — ", ". "):
        if sep in description:
            description = description.split(sep, 1)[0]
            break
    if len(description) <= max_len:
        return description
    return description[:max_len].rsplit(" ", 1)[0].rstrip(",;: ") + "…"

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler


class LibraryDoctorHandler:
    """Verwaltet den 'MusicBot Doctor'-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("LibraryDoctorHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

    def _is_admin(self, user_id: int) -> bool:
        """Prüft Admin- oder Owner-Rechte (ARCH-023/P-7: delegiert an
        permissions.is_admin_or_owner() - vormals eigenständig
        implementiert, funktional unverändert, siehe
        tests/test_library_doctor_handler.py::TestIsAdminDirect).
        Bleibt als Defense-in-Depth-Schicht hinter dem bereits zentral
        gegateten "doctor:"-Präfix bestehen (RichMenuSystem._handle_doctor_
        callback())."""
        return is_admin_or_owner(user_id, self.config)

    def _back_to_admin_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀️ Zurück", callback_data="menu:admin_group_library")]]
        )

    async def handle_scan(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Einstiegspunkt: startet einen Health-Scan. Admin-Check hier UND
        im Callback-Dispatcher (Defense-in-Depth, analog zum
        Reprocessing-/Wartungsmodus-Muster in rich_menu_system.py)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Nur Admins dürfen den Doctor nutzen", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text(
            "🩺 Health-Scan läuft ... kann je nach Library-Größe einige "
            "Minuten dauern."
        )
        import asyncio

        task = asyncio.create_task(self._run_scan_and_report(placeholder))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_scan_and_report(self, message: Message) -> None:
        try:
            result = await run_health_scan()
        except Exception as e:
            self.logger.error(f"💥 Unerwarteter Fehler beim Health-Scan: {e}", exc_info=True)
            # ARCH-027/F6: injizierter error_handler bisher ungenutzt.
            # Kein update/context verfügbar (Hintergrund-Task) -
            # handle_exception() registriert die Exception zentral, ohne
            # eine zweite Nutzer-Benachrichtigung auszulösen (update=None).
            if self.error_handler:
                await self.error_handler.handle_exception(
                    e,
                    context={
                        "module": "LibraryDoctorHandler",
                        "operation": "run_health_scan",
                    },
                )
            await message.edit_text(f"❌ Unerwarteter Fehler: {html.escape(str(e))}")
            return

        text, keyboard = self._format_scan_result(result)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _format_scan_result(self, result: DoctorScanResult):
        if not result.success:
            if result.timed_out:
                detail = result.error_message or "Timeout"
            elif result.error_message:
                detail = result.error_message
            else:
                detail = result.stderr_tail.strip()[-800:] or "Kein Fehlertext verfügbar."
            text = (
                f"❌ <b>Health-Scan fehlgeschlagen</b>\n\n"
                f"Exit-Code: {result.exit_code}\n\n"
                f"<pre>{html.escape(detail)}</pre>"
            )
            return text, self._back_to_admin_keyboard()

        report = result.report
        stats = report.get("statistics", {})
        health = report.get("health", {})
        total_files = stats.get("total_files") or 0

        # Nach Severity trennen (REGISTRY = Single Source of Truth aus
        # services/library_health/issues.py, dieselbe Quelle wie der
        # Health-Score selbst) - INFO ist laut Projektkonvention kein
        # Mangel und beeinflusst den Score nicht (LIBRARY_HEALTH.md §4),
        # sollte deshalb auch hier nicht wie ein Problem aussehen.
        problem_codes: list = []
        info_codes: list = []
        for code, count in stats.get("issues_by_code", {}).items():
            spec = ISSUE_REGISTRY.get(code)
            bucket = info_codes if spec and spec.default_severity == Severity.INFO else problem_codes
            bucket.append((code, count, spec))

        def _render(entries, limit=5):
            lines = []
            for code, count, spec in sorted(entries, key=lambda e: e[1], reverse=True)[:limit]:
                label = html.escape(_short_issue_label(spec.description)) if spec else html.escape(code)
                pct = (
                    f" ({count / total_files * 100:.0f} % der Tracks)"
                    if spec and spec.scope.value == "file" and total_files
                    else ""
                )
                lines.append(f"  • <b>{count}×</b> {label}{pct}")
            return lines

        section_lines = []
        problem_lines = _render(problem_codes)
        if problem_lines:
            section_lines.append("⚠️ <b>Wirkt sich auf den Score aus:</b>")
            section_lines.extend(problem_lines)
        else:
            section_lines.append("✅ Keine Befunde, die den Score senken.")

        info_lines = _render(info_codes)
        if info_lines:
            section_lines.append("")
            section_lines.append(
                "ℹ️ <b>Nur Beobachtung, kein Mangel</b> (zählt nicht in den Score):"
            )
            section_lines.extend(info_lines)

        status = health.get("status", "UNSCORED")
        status_emoji = _STATUS_EMOJI.get(status, "⚪")

        text = (
            f"🩺 <b>MusicBot Doctor — Health-Scan</b>\n\n"
            f"🎵 {html.escape(str(stats.get('total_files')))} Tracks  ·  "
            f"💿 {html.escape(str(stats.get('total_albums')))} Alben  ·  "
            f"🎤 {html.escape(str(stats.get('total_artists')))} Artists\n"
            f"{status_emoji} <b>Health-Score: {html.escape(str(health.get('score')))}"
            f" ({html.escape(str(status))})</b>\n\n"
            + "\n".join(section_lines) +
            "\n\n🔧 Sichere, verlustfreie Tag-/Dateinamen-Reparaturen können "
            "direkt angewendet werden. Cover/MusicBrainz/Lyrics/Loudness/"
            "Duplikate bleiben bewusst CLI-only (siehe docs/LIBRARY_REPAIR.md)."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔧 SAFE_AUTOMATIC anwenden", callback_data="doctor:apply_safe"
            )],
            [InlineKeyboardButton("◀️ Zurück", callback_data="menu:admin_group_library")],
        ])
        return text, keyboard

    async def handle_apply_safe_confirm_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Zeigt die Bestätigung vor dem tatsächlichen Apply-Lauf -
        SAFE_AUTOMATIC ist verlustfrei, aber eine echte Library-Mutation
        bleibt es trotzdem (Nutzer-Entscheidung: keine Ausführung ohne
        expliziten zweiten Tap, analog zum Reprocessing-Live-Lauf)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        await query.edit_message_text(
            "⚠️ <b>SAFE_AUTOMATIC jetzt anwenden?</b>\n\n"
            "Führt verlustfreie Tag-/Dateinamen-Fixes aus (Backup + "
            "Journal + Verification-Scan, siehe docs/LIBRARY_REPAIR.md). "
            "Kein Netzwerk, kein Re-Encode, kein Löschen.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Ja, anwenden", callback_data="doctor:apply_safe_confirm"
                )],
                [InlineKeyboardButton("❌ Abbrechen", callback_data="menu:admin_group_library")],
            ]),
        )

    async def handle_apply_safe_confirmed(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Startet den tatsächlichen SAFE_AUTOMATIC --apply-Lauf, nachdem
        der Nutzer die Bestätigung bestätigt hat."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text(
            "🔧 SAFE_AUTOMATIC-Reparatur läuft ..."
        )
        import asyncio

        task = asyncio.create_task(self._run_repair_and_report(placeholder))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_repair_and_report(self, message: Message) -> None:
        try:
            result = await run_safe_automatic_repair()
        except Exception as e:
            self.logger.error(f"💥 Unerwarteter Fehler beim Repair-Lauf: {e}", exc_info=True)
            # ARCH-027/F6: siehe _run_scan_and_report() oben.
            if self.error_handler:
                await self.error_handler.handle_exception(
                    e,
                    context={
                        "module": "LibraryDoctorHandler",
                        "operation": "run_safe_automatic_repair",
                    },
                )
            await message.edit_text(f"❌ Unerwarteter Fehler: {html.escape(str(e))}")
            return

        text, keyboard = self._format_repair_result(result)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _format_repair_result(self, result: DoctorRepairResult):
        if result.timed_out or result.error_message:
            detail = result.error_message or "Timeout"
            text = (
                f"❌ <b>SAFE_AUTOMATIC-Reparatur konnte nicht ausgeführt werden</b>\n\n"
                f"{html.escape(detail)}"
            )
        else:
            status = "✅ erfolgreich" if result.success else f"⚠️ Exit-Code {result.exit_code}"
            tail = result.stdout_tail.strip()[-1200:] or "Keine Ausgabe."
            text = (
                f"🔧 <b>SAFE_AUTOMATIC-Reparatur {status}</b>\n\n"
                f"<pre>{html.escape(tail)}</pre>"
            )
        return text, self._back_to_admin_keyboard()

    def _log_background_task_exception(self, task) -> None:
        """Sicherheitsnetz analog zu ReprocessingMenuHandler - fängt eine
        Exception ab, die NICHT bereits innerhalb von _run_*_and_report()
        selbst behandelt wurde (dort ist bereits ein try/except um den
        eigentlichen Subprozess-Aufruf)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self.logger.error(
                f"💥 Unbehandelte Exception in Doctor-Hintergrund-Task: {exc}",
                exc_info=exc,
            )
