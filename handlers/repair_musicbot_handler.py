# handlers/repair_musicbot_handler.py
# -*- coding: utf-8 -*-
"""
🛠️ REPAIR MUSICBOT — TELEGRAM MENÜ-HANDLER

Telegram-Oberfläche für services/library_repair/repair_service.py -
Detection/Analyse (Library Health), Findings-Review und Repair-Ausführung
bleiben strikt getrennte Verantwortlichkeiten (Aufgabe "Repair MusicBot"
Abschnitt 1/57):

    Findings lesen → Repair Capability → Repair Plan → Preview
    → explizite Bestätigung → Repair Executor → Verification
    → Findings-Update → Repair History

Ruft AUSSCHLIESSLICH den bestehenden Repair-Service auf (der seinerseits
den bereits gehärteten Subprozess-Pfad von MusicBot Doctor wiederverwendet,
siehe services/library_repair/doctor_runner.py) - kein eigener
Dateisystemzugriff, keine eigene Repair-Logik hier (CLAUDE.md §4
Schichtgrenzen).

Bewusst NUR SAFE_AUTOMATIC über Telegram ausführbar - identische
Sicherheitsgrenze wie MusicBot Doctor (siehe
handlers/library_doctor_handler.py, docs/LIBRARY_REPAIR.md §3). Alle
externen/destruktiven Level (COVER/EXTERNAL_METADATA/
METADATA_REPROCESSING/LOUDNESS/DUPLICATE) werden im Plan zwar angezeigt
(zur Transparenz), bleiben aber CLI-only.

Öffnen dieses Menüs, "Reparaturen analysieren" oder "Reparaturvorschläge"
starten NIEMALS automatisch eine Reparatur (Abschnitt 27/33) - nur der
explizit bestätigte "JA, REPARIEREN"-Tap tut das.

Nur für Admins sichtbar/nutzbar (Config.OWNER_USER_ID/ADMIN_USER_IDS),
identisches Muster wie handlers/library_doctor_handler.py. Die
Berechtigung wird am tatsächlichen Ausführungs-Handler ERNEUT geprüft
(Abschnitt 43) - eine Callback-ID allein ist kein Berechtigungsnachweis.
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
from services.library_repair.models import RepairLevel
from services.library_repair.repair_service import (
    HealthScanFailedError,
    RepairAlreadyRunningError,
    RepairPreview,
    build_preview,
    build_repair_plan,
    compute_repair_statistics,
    execute_safe_automatic_repair,
    get_safe_automatic_candidates,
    load_repair_history,
)

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_BACK_TO_ADMIN = "menu:admin_group_library"


class RepairMusicBotHandler:
    """Verwaltet den 'Repair MusicBot'-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("RepairMusicBotHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

    # ── Berechtigung ─────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        """Prüft Admin- oder Owner-Rechte (ARCH-023/P-7: delegiert an
        permissions.is_admin_or_owner() - vormals eigenständig
        implementiert, funktional unverändert, siehe
        tests/test_repair_musicbot_handler.py::TestIsAdminDirect). Bleibt
        als Defense-in-Depth-Schicht bestehen - insbesondere die erneute
        Prüfung am tatsächlichen Ausführungs-Handler (siehe Modul-
        Docstring, Abschnitt 43) ist unverändert, nur die Berechnung
        selbst ist jetzt zentral."""
        return is_admin_or_owner(user_id, self.config)

    def _back_keyboard(self, target: str = _BACK_TO_ADMIN, label: str = "◀️ Zurück") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])

    def _log_background_task_exception(self, task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self.logger.error(
                f"💥 Unbehandelte Exception in Repair-Hintergrund-Task: {exc}",
                exc_info=exc,
            )

    # ── Start (Abschnitt 27) ─────────────────────────────────────────────

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Nur Admins dürfen Repair MusicBot nutzen", show_alert=True)
            return
        await query.answer()

        text = "🛠️ <b>Repair MusicBot</b>\n\nWähle eine Aktion:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Reparaturen analysieren", callback_data="repair:analyze")],
            [InlineKeyboardButton("📋 Offene Reparaturen", callback_data="repair:analyze")],
            [InlineKeyboardButton("🛠️ Reparaturvorschläge", callback_data="repair:proposals")],
            [InlineKeyboardButton("📜 Reparaturhistorie", callback_data="repair:history")],
            [InlineKeyboardButton("📊 Repair-Statistik", callback_data="repair:stats")],
            [InlineKeyboardButton("◀️ Zurück", callback_data=_BACK_TO_ADMIN)],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Reparaturen analysieren / Offene Reparaturen (Abschnitt 27/31) ───

    async def handle_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text(
            "🔍 Analysiere Library ... kann je nach Größe einige Minuten dauern."
        )
        task = asyncio.create_task(self._run_analyze_and_report(placeholder))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_analyze_and_report(self, message: Message) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Analyse: {e}", exc_info=True)
            # ARCH-027/F6: injizierter error_handler bisher ungenutzt.
            # Kein update/context verfügbar (Hintergrund-Task) -
            # handle_exception() registriert die Exception zentral, ohne
            # eine zweite Nutzer-Benachrichtigung auszulösen (update=None).
            # HealthScanFailedError oben bleibt bewusst lokal (erwarteter,
            # bereits mit eigener Nutzer-Nachricht behandelter Fall, kein
            # unerwarteter Fehler im Sinne des zentralen Monitorings).
            if self.error_handler:
                await self.error_handler.handle_exception(
                    e,
                    context={
                        "module": "RepairMusicBotHandler",
                        "operation": "build_repair_plan",
                    },
                )
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        counts = plan.counts()
        manual = len(plan.manual_review())
        actionable = len(plan.actionable())
        unmapped = len(plan.unmapped_issue_codes)

        lines = [
            "🔍 <b>Reparaturen — Analyse</b>",
            "",
            f"Health-Score: {html.escape(str(plan.health_score))}",
            "",
        ]
        if counts:
            for level, count in counts.items():
                lines.append(f"  • <b>{count}×</b> {html.escape(level)}")
        else:
            lines.append("✅ Keine offenen Befunde mit Reparaturbezug.")
        lines.append("")
        lines.append(f"Automatisch ausführbar (SAFE_AUTOMATIC): "
                      f"{counts.get(RepairLevel.SAFE_AUTOMATIC.value, 0)}")
        lines.append(f"Nur manuelle Prüfung: {manual}")
        if unmapped:
            lines.append(f"Ohne Reparatur-Zuordnung: {unmapped}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛠️ Reparaturvorschläge", callback_data="repair:proposals")],
            [InlineKeyboardButton("◀️ Zurück", callback_data="repair:start")],
        ])
        await message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    # ── Reparaturvorschläge (Abschnitt 29/31) ────────────────────────────

    async def handle_proposals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text("🛠️ Ermittle Reparaturvorschläge ...")
        task = asyncio.create_task(self._run_proposals_and_report(placeholder))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_proposals_and_report(self, message: Message) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        safe_candidates = get_safe_automatic_candidates(plan)
        other_actionable = [
            c for c in plan.actionable() if c.level is not RepairLevel.SAFE_AUTOMATIC
        ]

        if not safe_candidates and not other_actionable:
            await message.edit_text(
                "✅ Keine reparierbaren Befunde gefunden.",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        lines = ["🛠️ <b>Reparaturvorschläge</b>", ""]
        lines.append(f"{len(safe_candidates)} automatisch ausführbare Reparatur(en) "
                      f"(🟢 SAFE)")
        for c in safe_candidates[:10]:
            loc = " / ".join(p for p in (c.artist, c.album, c.title) if p) or (c.path or "-")
            lines.append(f"  🟢 {html.escape(c.issue_code)} — {html.escape(loc)}")
        if len(safe_candidates) > 10:
            lines.append(f"  … {len(safe_candidates) - 10} weitere")

        if other_actionable:
            lines.append("")
            lines.append(f"{len(other_actionable)} weitere Reparatur(en) — 🟡 REVIEW "
                         "(nur über die CLI ausführbar, siehe docs/LIBRARY_REPAIR.md)")

        buttons = []
        if safe_candidates:
            buttons.append([InlineKeyboardButton(
                f"🔍 Preview ({len(safe_candidates)} SAFE)", callback_data="repair:preview",
            )])
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="repair:start")])

        await message.edit_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ── Preview (Abschnitt 32, read-only) ─────────────────────────────────

    async def handle_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text("🔍 Erstelle Vorschau ...")
        task = asyncio.create_task(self._run_preview_and_report(placeholder))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_preview_and_report(self, message: Message) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        safe_candidates = get_safe_automatic_candidates(plan)
        if not safe_candidates:
            await message.edit_text(
                "✅ Keine SAFE_AUTOMATIC-Reparaturen (mehr) verfügbar - "
                "möglicherweise wurde die Library seit der letzten Analyse "
                "bereits repariert.",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        preview = build_preview(safe_candidates)
        text, keyboard = self._format_preview(preview)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _format_preview(self, preview: RepairPreview):
        lines = [
            "🔍 <b>Reparatur-Vorschau</b>",
            "",
            f"Safety-Level: SAFE_AUTOMATIC (verlustfrei, kein Netzwerk, kein Re-Encode)",
            f"Executor(en): {html.escape(', '.join(preview.executor_components) or '-')}",
            "",
            f"Geplante Änderungen ({preview.candidate_count}):",
        ]
        for c in preview.candidates[:15]:
            loc = " / ".join(p for p in (c.artist, c.album, c.title) if p) or (c.path or "-")
            lines.append(f"  • {html.escape(c.issue_code)} — {html.escape(loc)}")
            if c.expected_change:
                lines.append(f"    → {html.escape(c.expected_change)}")
        if preview.candidate_count > 15:
            lines.append(f"  … {preview.candidate_count - 15} weitere")
        lines.append("")
        lines.append("Noch keine Änderungen durchgeführt.")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Reparatur ausführen", callback_data="repair:confirm")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="repair:start")],
        ])
        return "\n".join(lines), keyboard

    # ── Explizite Bestätigung (Abschnitt 33) ─────────────────────────────

    async def handle_confirm_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            "Diese Aktion verändert deine Music Library "
            "(verlustfreie Tag-/Dateinamen-Fixes, Backup + Journal + "
            "Verification-Scan).\n\n"
            "Fortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ JA, REPARIEREN", callback_data="repair:execute")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data="repair:start")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Ausführung (Abschnitt 35/38/42/43) ───────────────────────────────

    async def handle_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Einzige Stelle, die tatsächlich eine Reparatur startet - die
        Berechtigung wird HIER erneut geprüft (Abschnitt 43), unabhängig
        davon, ob vorherige Bildschirme bereits geprüft haben."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        placeholder = await query.edit_message_text("🛠️ Reparatur läuft ...")
        task = asyncio.create_task(self._run_execute_and_report(placeholder, user_id))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_execute_and_report(self, message: Message, user_id: int) -> None:
        try:
            result = await execute_safe_automatic_repair(triggered_by=f"telegram:{user_id}")
        except RepairAlreadyRunningError as e:
            await message.edit_text(
                f"⚠️ {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der Reparatur: {e}", exc_info=True)
            # ARCH-027/F6: siehe _run_analyze_and_report() oben.
            # RepairAlreadyRunningError bleibt bewusst lokal (erwarteter
            # Fall mit eigener Nutzer-Nachricht).
            if self.error_handler:
                await self.error_handler.handle_exception(
                    e,
                    context={
                        "module": "RepairMusicBotHandler",
                        "operation": "execute_safe_automatic_repair",
                    },
                )
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        text = self._format_result(result)
        await message.edit_text(text, parse_mode="HTML", reply_markup=self._back_keyboard("repair:start"))

    def _format_result(self, result) -> str:
        from services.library_repair.repair_service import (
            STATUS_FAILED,
            STATUS_SKIPPED,
            STATUS_SUCCESS,
        )

        if result.status == STATUS_SKIPPED and result.candidates_total == 0:
            return "✅ Keine offenen SAFE_AUTOMATIC-Reparaturen (mehr) vorhanden."

        if result.error_message:
            return (
                f"❌ <b>Reparatur fehlgeschlagen</b>\n\n"
                f"{html.escape(result.error_message)}"
            )

        counts = result.status_counts or {}
        success = counts.get("SUCCESS", 0)
        failed = counts.get("FAILED", 0)
        skipped = counts.get("SKIPPED", 0)

        emoji = "✅" if result.status == STATUS_SUCCESS else (
            "⚠️" if failed and success else "❌"
        )
        header = "Reparatur abgeschlossen" if not failed else "Reparatur teilweise abgeschlossen"

        lines = [
            f"{emoji} <b>{header}</b>",
            "",
            f"Erfolgreich: {success}",
            f"Übersprungen: {skipped}",
            f"Fehlgeschlagen: {failed}",
            "",
            f"Geänderte Dateien: {len(result.affected_files)}",
            f"Verifiziert behoben: {result.resolved_count}",
        ]
        regressed = getattr(result, "regressed_issue_codes", None) or []
        if regressed:
            lines.append("")
            lines.append(
                "⚠️ Mögliche Nebenwirkung: neue offene Findings bei nicht "
                f"betroffenen Issue-Codes: {html.escape(', '.join(regressed))}"
            )
        return "\n".join(lines)

    # ── Repair History (Abschnitt 44/45) ─────────────────────────────────

    async def handle_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        runs = load_repair_history(limit=10)
        if not runs:
            await query.edit_message_text(
                "📜 <b>Reparaturhistorie</b>\n\nNoch keine Reparaturen durchgeführt.",
                parse_mode="HTML",
                reply_markup=self._back_keyboard("repair:start"),
            )
            return

        lines = ["📜 <b>Reparaturhistorie</b>", ""]
        for run in runs:
            counts = run.get("status_counts") or {}
            total = sum(counts.values())
            status = run.get("status", "?")
            emoji = {"SUCCESS": "✅", "FAILED": "⚠️", "SKIPPED": "⏭️"}.get(status, "•")
            started = run.get("started_at", "-")
            lines.append(f"{emoji} {html.escape(started)}")
            lines.append(
                f"   {total} Reparatur(en) — {counts.get('SUCCESS', 0)} erfolgreich"
                + (f", {counts.get('FAILED', 0)} fehlgeschlagen" if counts.get("FAILED") else "")
            )
        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=self._back_keyboard("repair:start")
        )

    # ── Repair Statistics (Abschnitt 46) ──────────────────────────────────

    async def handle_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        stats = compute_repair_statistics()
        lines = [
            "🛠️ <b>Repair-Statistik</b>",
            "",
            f"Ausgeführte Reparaturen: {stats['total']}",
            f"Erfolgreich: {stats['success']}",
            f"Fehlgeschlagen: {stats['failed']}",
            f"Übersprungen: {stats['skipped']}",
        ]
        top = stats.get("most_common_issue_codes") or []
        if top:
            lines.append("")
            lines.append("Häufigste Reparaturen:")
            for code, count in top[:5]:
                lines.append(f"  {html.escape(code)}: {count}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=self._back_keyboard("repair:start")
        )
