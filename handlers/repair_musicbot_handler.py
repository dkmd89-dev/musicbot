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

SAFE_AUTOMATIC (Level 1) bleibt der primäre, ohne Vorschau-Umweg direkt
über "Reparaturvorschläge" ausführbare Weg - identische Sicherheitsgrenze
wie MusicBot Doctor (siehe handlers/library_doctor_handler.py,
docs/LIBRARY_REPAIR.md §3). Seit ARCH-033 sind zusätzlich Level 2
(METADATA_REPROCESSING) und Level 3 (EXTERNAL_METADATA) über Telegram
erreichbar - aber bewusst NUR pro Artist, mit eigener Vorschau und
eigener Bestätigung je Artist (ADR-0003, docs/LIBRARY_REPAIR.md §12) über
den separaten "🛠️ L2/L3-Reparaturen (nach Artist)"-Sub-Flow
(`l23rep:*`-Callbacks unten). COVER/LOUDNESS/DUPLICATE bleiben weiterhin
CLI-only (spätere, eigene Phasen ARCH-034/035).

Öffnen dieses Menüs, "Reparaturen analysieren", "Reparaturvorschläge"
oder der L2/L3-Artist-/Aktions-Auswahl starten NIEMALS automatisch eine
Reparatur (Abschnitt 27/33) - nur der explizit bestätigte
"JA, REPARIEREN"-bzw. "✅ Jetzt ausführen"-Tap tut das, und niemals für
mehr als einen Artist auf einmal (keine globale L2/L3-Batch-Freigabe).

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
from services.library_repair.planner import filter_plan, group_candidates_by_artist
from services.library_repair.repair_service import (
    HealthScanFailedError,
    LevelRepairResult,
    RepairAlreadyRunningError,
    RepairPreview,
    build_preview,
    build_repair_plan,
    compute_repair_statistics,
    execute_level2_repair,
    execute_level3_repair,
    execute_safe_automatic_repair,
    get_safe_automatic_candidates,
    load_repair_history,
)

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_BACK_TO_ADMIN = "menu:admin_group_library"

# ── L2/L3 Pro-Artist-Sub-Flow (ARCH-033) ────────────────────────────────
_L23REP_SESSION_KEY = "l23rep_session"
_L23REP_ARTISTS_PER_PAGE = 8
_L23REP_LEVEL_LABELS = {
    "l2": "L2 · Metadata Reprocessing",
    "l3": "L3 · External Metadata",
}
_L23REP_REPAIR_LEVEL_VALUES = {
    "l2": RepairLevel.METADATA_REPROCESSING.value,
    "l3": RepairLevel.EXTERNAL_METADATA.value,
}
_L23REP_WARNING_TEXT = {
    "l2": (
        "Metadata Reprocessing durchläuft die volle Metadaten-Pipeline "
        "erneut (Genre/Lyrics/Cover-Logik inklusive). Dabei können sich "
        "auch Auto-Learn-Mappings ändern."
    ),
    "l3": (
        "External Metadata ruft MusicBrainz und weitere externe Dienste "
        "auf. Netzwerk-/Rate-Limit-Fehler sind möglich und werden je "
        "Datei als FEHLGESCHLAGEN sichtbar, nicht still übersprungen."
    ),
}


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

        l2l3_count = sum(
            1 for c in other_actionable
            if c.level in (RepairLevel.METADATA_REPROCESSING, RepairLevel.EXTERNAL_METADATA)
        )
        if other_actionable:
            lines.append("")
            lines.append(f"{len(other_actionable)} weitere Reparatur(en) — 🟡 REVIEW "
                         "(nur über die CLI ausführbar, siehe docs/LIBRARY_REPAIR.md)")
            if l2l3_count:
                lines.append(
                    f"  davon {l2l3_count}× L2/L3 — jetzt auch pro Artist über "
                    "Telegram ausführbar (Button unten)."
                )

        buttons = []
        if safe_candidates:
            buttons.append([InlineKeyboardButton(
                f"🔍 Preview ({len(safe_candidates)} SAFE)", callback_data="repair:preview",
            )])
        if l2l3_count:
            buttons.append([InlineKeyboardButton(
                "🛠️ L2/L3-Reparaturen (nach Artist)", callback_data="l23rep:start",
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

    # ── L2/L3 Pro-Artist-Reparatur (ARCH-033) ─────────────────────────────
    #
    # Findings-getrieben (ADR-0001) wie "Reparaturvorschläge" oben, aber
    # bewusst NUR pro Artist mit eigener Vorschau/Bestätigung (ADR-0003).
    # Die Artist-Liste (inkl. L2-/L3-Kandidatenzahl) wird pro
    # Telegram-Session in context.user_data gecacht (identisches Muster
    # zu handlers/library_health_review_handler.py::_SESSION_KEY) - ein
    # frischer Health-Scan bei JEDEM Button-Tap (Seitenwechsel,
    # Aktions-Auswahl) wäre für eine große Library nicht praktikabel.
    # Unmittelbar vor der tatsächlichen Ausführung (execute_level2_repair/
    # execute_level3_repair) baut der Service selbst ohnehin immer einen
    # frischen Plan (Stale-Plan-Schutz, siehe repair_service.py) - der
    # Cache hier dient ausschließlich der Navigation, nie der Ausführung.

    def _l23_session(self, context: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        return context.user_data.get(_L23REP_SESSION_KEY)

    def _l23_resolve(self, context: ContextTypes.DEFAULT_TYPE, idx: int):
        session = self._l23_session(context)
        if session is None:
            return None
        artists = session.get("artists") or []
        if not (0 <= idx < len(artists)):
            return None
        return artists[idx]

    async def handle_l23_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        text = (
            "🛠️ <b>L2/L3-Reparaturen (nach Artist)</b>\n\n"
            "Metadata Reprocessing (L2) und External Metadata (L3) sind "
            "weitreichender als die automatischen SAFE-Reparaturen und "
            "werden deshalb nur pro Artist mit eigener Vorschau und "
            "eigener Bestätigung ausgeführt (nie global).\n\n"
            "Wähle zuerst einen Artist."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Artist wählen", callback_data="l23rep:artists")],
            [InlineKeyboardButton("◀️ Zurück", callback_data="repair:proposals")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Artist-Liste (Index-Picker, gecacht, paginiert) ──────────────────

    async def handle_l23_artist_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0,
        *, force_refresh: bool = False,
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        if not force_refresh and self._l23_session(context) is not None:
            text, keyboard = self._l23_artist_page_args(context, page)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        placeholder = await query.edit_message_text("🔍 Analysiere Library nach Artist ...")
        task = asyncio.create_task(self._run_l23_artist_scan_and_report(placeholder, context, page))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_l23_artist_scan_and_report(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, page: int,
    ) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("l23rep:start"),
            )
            return

        groups = group_candidates_by_artist(plan)
        artists = [
            (summary.artist, summary.l2_count, summary.l3_count)
            for summary in groups.values()
        ]
        context.user_data[_L23REP_SESSION_KEY] = {"artists": artists}

        if not artists:
            await message.edit_text(
                "✅ Keine offenen L2/L3-Befunde (mehr) gefunden.",
                reply_markup=self._back_keyboard("l23rep:start"),
            )
            return

        text, keyboard = self._l23_artist_page_args(context, page)
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _l23_artist_page_args(self, context: ContextTypes.DEFAULT_TYPE, page: int):
        session = self._l23_session(context) or {"artists": []}
        artists = session["artists"]
        total_pages = max(1, (len(artists) + _L23REP_ARTISTS_PER_PAGE - 1) // _L23REP_ARTISTS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        start = page * _L23REP_ARTISTS_PER_PAGE
        page_artists = artists[start:start + _L23REP_ARTISTS_PER_PAGE]

        text = (
            f"👤 <b>Artist wählen</b> (L2/L3-Kandidaten)\n\n"
            f"{len(artists)} Artist(en), Seite {page + 1}/{total_pages}:"
        )
        buttons = []
        for offset, (name, l2_count, l3_count) in enumerate(page_artists):
            idx = start + offset
            label = f"🎵 {name} (L2:{l2_count} L3:{l3_count})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"l23rep:pick:{idx}")])

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Vorherige", callback_data=f"l23rep:artists:{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Nächste ▶️", callback_data=f"l23rep:artists:{page + 1}"))
        if nav_row:
            buttons.append(nav_row)
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="l23rep:start")])
        return text, InlineKeyboardMarkup(buttons)

    async def handle_l23_pick_artist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        entry = self._l23_resolve(context, idx)
        if entry is None:
            await query.edit_message_text(
                "⚠️ Artist-Liste ist abgelaufen (z. B. neuer Bot-Start) — "
                "bitte erneut wählen.",
                reply_markup=self._back_keyboard("l23rep:artists"),
            )
            return

        artist, l2_count, l3_count = entry
        text = f"👤 <b>{html.escape(artist)}</b>\n\nWähle eine Aktion:"
        buttons = []
        if l2_count:
            buttons.append([InlineKeyboardButton(
                f"L2 · Metadata Reprocessing ({l2_count})",
                callback_data=f"l23rep:preview:l2:{idx}",
            )])
        if l3_count:
            buttons.append([InlineKeyboardButton(
                f"L3 · External Metadata ({l3_count})",
                callback_data=f"l23rep:preview:l3:{idx}",
            )])
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="l23rep:artists")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    # ── Preview (read-only) ──────────────────────────────────────────────

    async def handle_l23_preview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, level: str, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        entry = self._l23_resolve(context, idx)
        if entry is None:
            await query.edit_message_text(
                "⚠️ Artist-Liste ist abgelaufen — bitte erneut wählen.",
                reply_markup=self._back_keyboard("l23rep:artists"),
            )
            return
        artist = entry[0]

        placeholder = await query.edit_message_text(
            f"🔍 Erstelle Vorschau für {html.escape(artist)} ..."
        )
        task = asyncio.create_task(self._run_l23_preview_and_report(placeholder, level, artist, idx))
        task.add_done_callback(self._log_background_task_exception)

    async def _run_l23_preview_and_report(
        self, message: Message, level: str, artist: str, idx: int
    ) -> None:
        try:
            plan = await build_repair_plan()
        except HealthScanFailedError as e:
            await message.edit_text(
                f"❌ Health-Scan fehlgeschlagen: {html.escape(str(e))}",
                reply_markup=self._back_keyboard(f"l23rep:pick:{idx}"),
            )
            return

        candidates = filter_plan(
            plan, artist=artist, level=_L23REP_REPAIR_LEVEL_VALUES[level],
        ).candidates
        if not candidates:
            await message.edit_text(
                f"✅ {html.escape(artist)}: keine offenen "
                f"{html.escape(_L23REP_LEVEL_LABELS[level])}-Befunde (mehr) "
                "vorhanden.",
                reply_markup=self._back_keyboard(f"l23rep:pick:{idx}"),
            )
            return

        preview = build_preview(candidates, level=_L23REP_REPAIR_LEVEL_VALUES[level])
        lines = [
            f"🔍 <b>Vorschau — {html.escape(_L23REP_LEVEL_LABELS[level])}</b>",
            f"Artist: {html.escape(artist)}",
            "",
            f"⚠️ {_L23REP_WARNING_TEXT[level]}",
            "",
            f"Betroffene Befunde ({preview.candidate_count}):",
        ]
        for c in preview.candidates[:15]:
            loc = " / ".join(p for p in (c.artist, c.album, c.title) if p) or (c.path or "-")
            lines.append(f"  • {html.escape(c.issue_code)} — {html.escape(loc)}")
        if preview.candidate_count > 15:
            lines.append(f"  … {preview.candidate_count - 15} weitere")
        lines.append("")
        lines.append("Noch keine Änderungen durchgeführt.")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ Weiter zur Bestätigung", callback_data=f"l23rep:confirm:{level}:{idx}",
            )],
            [InlineKeyboardButton("❌ Abbrechen", callback_data=f"l23rep:pick:{idx}")],
        ])
        await message.edit_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=keyboard,
        )

    # ── Explizite Bestätigung ─────────────────────────────────────────────

    async def handle_l23_confirm_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, level: str, idx: int
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        entry = self._l23_resolve(context, idx)
        if entry is None:
            await query.edit_message_text(
                "⚠️ Artist-Liste ist abgelaufen — bitte erneut wählen.",
                reply_markup=self._back_keyboard("l23rep:artists"),
            )
            return
        artist = entry[0]

        text = (
            "⚠️ <b>ACHTUNG</b>\n\n"
            f"Aktion: {html.escape(_L23REP_LEVEL_LABELS[level])}\n"
            f"Artist: {html.escape(artist)}\n\n"
            f"{_L23REP_WARNING_TEXT[level]}\n\n"
            "Diese Aktion verändert Tags/Metadaten dieses Artists in "
            "deiner Music Library (Backup + Journal + "
            "Verification-Scan). Fortfahren?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Jetzt ausführen", callback_data=f"l23rep:execute:{level}:{idx}")],
            [InlineKeyboardButton("❌ ABBRECHEN", callback_data=f"l23rep:pick:{idx}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Ausführung ─────────────────────────────────────────────────────────

    async def handle_l23_execute(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, level: str, idx: int
    ) -> None:
        """Einzige Stelle, die tatsächlich eine L2/L3-Reparatur startet -
        Berechtigung wird HIER erneut geprüft (Defense-in-Depth,
        identisch zu handle_execute() oben)."""
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        entry = self._l23_resolve(context, idx)
        if entry is None:
            await query.edit_message_text(
                "⚠️ Artist-Liste ist abgelaufen — bitte erneut wählen.",
                reply_markup=self._back_keyboard("l23rep:artists"),
            )
            return
        artist = entry[0]

        placeholder = await query.edit_message_text(
            f"🛠️ {html.escape(_L23REP_LEVEL_LABELS[level])} läuft für "
            f"{html.escape(artist)} ..."
        )
        task = asyncio.create_task(
            self._run_l23_execute_and_report(placeholder, level, artist, user_id)
        )
        task.add_done_callback(self._log_background_task_exception)

    async def _run_l23_execute_and_report(
        self, message: Message, level: str, artist: str, user_id: int
    ) -> None:
        # Namens-Lookup im Modul-Globalstate zur AUFRUFZEIT statt eines
        # beim Import gebauten Dicts - identisches Prinzip wie
        # repair_service.py::_execute_level_repair() (siehe dort für den
        # dokumentierten Bug, den diese Form vermeidet: ein früh
        # gebundenes Dict ignoriert unittest.mock.patch.object() in
        # Tests und würde einen echten Subprozess gegen die
        # Produktionslibrary starten).
        execute_fn = globals()["execute_level2_repair" if level == "l2" else "execute_level3_repair"]
        try:
            result = await execute_fn(artist, triggered_by=f"telegram:{user_id}")
        except RepairAlreadyRunningError as e:
            await message.edit_text(
                f"🔒 {html.escape(str(e))}",
                reply_markup=self._back_keyboard("l23rep:start"),
            )
            return
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"💥 Unerwarteter Fehler bei der L2/L3-Reparatur: {e}", exc_info=True)
            await self._report_error(e, f"execute_{level}")
            await message.edit_text(
                f"❌ Unerwarteter Fehler: {html.escape(str(e))}",
                reply_markup=self._back_keyboard("l23rep:start"),
            )
            return

        await message.edit_text(
            self._format_l23_result(level, artist, result),
            parse_mode="HTML",
            reply_markup=self._back_keyboard("l23rep:start"),
        )

    async def _report_error(self, e: Exception, operation: str) -> None:
        if self.error_handler:
            await self.error_handler.handle_exception(
                e, context={"module": "RepairMusicBotHandler", "operation": operation},
            )

    def _format_l23_result(self, level: str, artist: str, result: LevelRepairResult) -> str:
        if result.status == "SKIPPED" and result.total == 0:
            return (
                f"✅ {html.escape(artist)}: keine offenen "
                f"{html.escape(_L23REP_LEVEL_LABELS[level])}-Befunde (mehr) "
                "vorhanden."
            )

        if result.error_message:
            return (
                f"❌ <b>{html.escape(_L23REP_LEVEL_LABELS[level])} fehlgeschlagen</b>\n"
                f"Artist: {html.escape(artist)}\n\n"
                f"{html.escape(result.error_message)}"
            )

        emoji = "✅" if result.status == "SUCCESS" and not result.failed else (
            "⚠️" if result.failed and result.success else "❌"
        )
        header = "abgeschlossen" if not result.failed else "teilweise abgeschlossen"

        lines = [
            f"{emoji} <b>{html.escape(_L23REP_LEVEL_LABELS[level])} {header}</b>",
            f"Artist: {html.escape(artist)}",
            "",
            f"Erfolgreich: {result.success}",
            f"Übersprungen: {result.skipped}",
            f"Fehlgeschlagen: {result.failed}",
            "",
            f"Geänderte Dateien: {len(result.affected_files)}",
            f"Verifiziert behoben: {result.resolved_count}",
        ]
        if result.rescan_triggered:
            lines.append("")
            lines.append(
                "ℹ️ Ein Verifikations-Scan wurde durchgeführt. Möglicherweise "
                "haben sich dabei auch Auto-Learn-Mappings geändert "
                "(mapping/auto_learned_*.json) - unabhängig davon manuell "
                "prüfbar."
            )
        return "\n".join(lines)
