# handlers/library_health_review_handler.py
# -*- coding: utf-8 -*-
"""
🔎 LIBRARY HEALTH REVIEW — TELEGRAM MENÜ-HANDLER

Telegram-Oberfläche für die persistente Library-Health-Findings-Registry
(services/library_health/findings.py) — dieselbe zentrale Review-Service-
Logik (FindingsRegistry, group_open_findings_by_category(),
batch_review_category(), review_finding()) wie
scripts/library_health_review.py. Kein eigener JSON-Zugriff, keine
eigene Business-Logik hier (CLAUDE.md §4 Schichtgrenzen, Aufgabe
"Library Health Review" Abschnitt 1).

Navigation:

    Severity-Auswahl -> Kategorie-Auswahl -> Kategorie-Aktionen
        -> Einzelreview (Resolve/False Positive/Skip/Quit)
        -> Batch-False-Positive (mit expliziter Bestätigung)

Öffnen von "Library Health Review" ändert NIEMALS einen Status (Abschnitt
18) - nur tatsächliche Nutzeraktionen (Resolve/False Positive/Batch)
schreiben in die Registry. Ausschließlich die Findings-Registry wird
geschrieben - niemals eine Datei der Music Library (Abschnitt 25).

Nur für Admins sichtbar/nutzbar (Config.OWNER_USER_ID/ADMIN_USER_IDS),
identisches Muster wie handlers/library_doctor_handler.py.
"""

from __future__ import annotations

import html
from typing import Callable, Optional, TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import Config
from logger import get_module_logger
from services.library_health.findings import (
    DEFAULT_FILENAME,
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    CategoryGroup,
    Finding,
    FindingsRegistry,
    FindingsRegistryError,
    batch_review_category,
    group_open_findings_by_category,
)

if TYPE_CHECKING:
    from handlers.enhanced_error_handler import EnhancedErrorHandler

_TIER_EMOJI = {
    "CRITICAL": "🔴", "ERROR": "🟠", "WARNING": "🟡",
    "SUSPECTED": "🔎", "INFO": "ℹ️",
}
_TIER_ORDER = ("CRITICAL", "ERROR", "WARNING", "SUSPECTED", "INFO")
_TIER_LABEL = {
    "CRITICAL": "Critical", "ERROR": "Error", "WARNING": "Warning",
    "SUSPECTED": "Suspected", "INFO": "Info",
}

_SESSION_KEY = "health_review"
_BACK_TO_ADMIN = "menu:admin_group_library"


def _finding_location(finding: Finding) -> str:
    parts = [p for p in (finding.artist, finding.album, finding.title) if p]
    if parts:
        return " / ".join(parts)
    return finding.path or "-"


class LibraryHealthReviewHandler:
    """Verwaltet den 'Library Health Review'-Menübereich im Rich-Menu-System."""

    def __init__(self, config: Config, logger_factory: Callable = None):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("LibraryHealthReviewHandler")
        self.error_handler: Optional["EnhancedErrorHandler"] = None

    # ── Berechtigung ─────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        if user_id == getattr(self.config, "OWNER_USER_ID", None):
            return True
        return user_id in getattr(self.config, "ADMIN_USER_IDS", [])

    def _registry_path(self):
        from pathlib import Path

        return Path(self.config.DATA_DIR) / DEFAULT_FILENAME

    def _load_registry(self) -> Optional[FindingsRegistry]:
        try:
            return FindingsRegistry(self._registry_path(), logger=self.logger)
        except FindingsRegistryError as e:
            self.logger.error(f"❌ Findings-Registry ungültig: {e}")
            return None

    # ── Kleine Render-Helfer ─────────────────────────────────────────────

    def _back_keyboard(self, target: str, label: str = "◀️ Zurück") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])

    def _registry_error_message(self) -> tuple:
        text = (
            "❌ <b>Findings-Registry ungültig</b>\n\n"
            "Die Registry-Datei ist beschädigt oder hat ein unerwartetes "
            "Schema und wurde deshalb NICHT verändert. Bitte manuell prüfen."
        )
        return text, self._back_keyboard(_BACK_TO_ADMIN)

    # ── Start / Übersicht (Abschnitt 18) ─────────────────────────────────

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Nur Admins dürfen Findings prüfen", show_alert=True)
            return
        await query.answer()
        context.user_data.pop(_SESSION_KEY, None)

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        groups = group_open_findings_by_category(registry)
        text, keyboard = self._render_overview(groups)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    def _render_overview(self, groups: list[CategoryGroup]):
        total_open = sum(g.open_count for g in groups)
        tier_counts: dict[str, int] = {t: 0 for t in _TIER_ORDER}
        tier_categories: dict[str, int] = {t: 0 for t in _TIER_ORDER}
        for g in groups:
            tier_counts[g.tier] = tier_counts.get(g.tier, 0) + g.open_count
            tier_categories[g.tier] = tier_categories.get(g.tier, 0) + 1

        lines = [
            "🔎 <b>Library Health Review</b>",
            "",
            f"Offene Befunde: {total_open}",
            f"Kategorien: {len(groups)}",
            "",
        ]
        for tier in _TIER_ORDER:
            lines.append(f"{_TIER_EMOJI[tier]} {tier} ({tier_counts[tier]})")

        buttons = []
        for tier in _TIER_ORDER:
            if tier_counts[tier] > 0:
                buttons.append([InlineKeyboardButton(
                    f"{_TIER_EMOJI[tier]} {_TIER_LABEL[tier]}",
                    callback_data=f"review:severity:{tier}",
                )])
        buttons.append([InlineKeyboardButton("🔄 Aktualisieren", callback_data="review:start")])
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data=_BACK_TO_ADMIN)])

        if total_open == 0:
            lines.append("")
            lines.append("✅ Keine offenen Befunde.")

        return "\n".join(lines), InlineKeyboardMarkup(buttons)

    # ── Severity-Auswahl (Abschnitt 19) ──────────────────────────────────

    async def handle_severity(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, tier: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        groups = [g for g in group_open_findings_by_category(registry) if g.tier == tier]

        if not groups:
            await query.edit_message_text(
                f"{_TIER_EMOJI.get(tier, '')} <b>{html.escape(tier)}</b>\n\n"
                "✅ Keine offenen Kategorien mehr in dieser Severity-Stufe.",
                parse_mode="HTML",
                reply_markup=self._back_keyboard("review:start"),
            )
            return

        lines = [f"{_TIER_EMOJI.get(tier, '')} <b>{html.escape(tier)}</b>", ""]
        buttons = []
        for g in groups:
            buttons.append([InlineKeyboardButton(
                f"{g.code} · {g.open_count}", callback_data=f"review:category:{g.code}",
            )])
        buttons.append([InlineKeyboardButton("◀️ Zurück", callback_data="review:start")])

        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ── Kategorie-Aktionen (Abschnitt 20/21) ─────────────────────────────

    async def handle_category(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        group = self._find_category(registry, code)
        if group is None:
            await self._show_category_gone(query, code)
            return

        text = (
            f"🔎 <b>{html.escape(code)}</b>\n\n"
            f"{group.open_count} aktuell offene Befunde"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Befunde bearbeiten", callback_data=f"review:edit:{code}")],
            [InlineKeyboardButton(
                "🚫 Ganze Kategorie → False Positive",
                callback_data=f"review:batchconfirm:{code}",
            )],
            [InlineKeyboardButton("◀️ Zurück", callback_data=f"review:severity:{group.tier}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    @staticmethod
    def _find_category(registry: FindingsRegistry, code: str) -> Optional[CategoryGroup]:
        for g in group_open_findings_by_category(registry):
            if g.code == code:
                return g
        return None

    async def _show_category_gone(self, query, fallback_target: str = "review:start") -> None:
        await query.edit_message_text(
            "⚠️ Diese Kategorie hat keine offenen Befunde mehr.\n\n"
            "Die Findings wurden zwischenzeitlich aktualisiert.",
            reply_markup=self._back_keyboard("review:start", "🔄 Aktualisieren"),
        )

    # ── Batch False Positive (Abschnitt 23) ──────────────────────────────

    async def handle_batch_confirm_prompt(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        group = self._find_category(registry, code)
        if group is None:
            await self._show_category_gone(query)
            return

        text = (
            "⚠️ <b>Kategorie als FALSE POSITIVE markieren?</b>\n\n"
            f"{html.escape(code)}\n\n"
            f"{group.open_count} aktuell offene Befunde\n\n"
            "Diese Aktion betrifft ALLE aktuell offenen Befunde dieser Kategorie."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🚫 Ja, alle markieren", callback_data=f"review:batchyes:{code}",
            )],
            [InlineKeyboardButton("❌ Abbrechen", callback_data=f"review:category:{code}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_batch_confirmed(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        # Stale-Revalidierung unmittelbar vor der Aenderung (Abschnitt 24):
        # die Kategorie MUSS zum Zeitpunkt der tatsaechlichen Aktion noch
        # offene Findings haben.
        group = self._find_category(registry, code)
        if group is None:
            await self._show_category_gone(query)
            return

        count = group.open_count
        reviewer = f"telegram:{user_id}"
        batch_review_category(registry, code, STATUS_FALSE_POSITIVE, reviewed_by=reviewer)
        registry.save()
        self.logger.info(
            f"📋 [REVIEW] Batch-FALSE_POSITIVE: {count} Befund(e) der Kategorie "
            f"'{code}' von User {user_id}"
        )

        await query.edit_message_text(
            f"✅ {count} Findings als FALSE_POSITIVE markiert.",
            reply_markup=self._back_keyboard("review:start", "◀️ Zurück zur Übersicht"),
        )

    # ── Einzelreview (Abschnitt 22/24) ────────────────────────────────────

    async def handle_edit_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()
        context.user_data[_SESSION_KEY] = {"code": code, "position": 0}
        await self._render_current_finding(query, context)

    async def _render_current_finding(self, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        session = context.user_data.get(_SESSION_KEY)
        if not session:
            await self._show_category_gone(query)
            return
        code = session["code"]
        position = session["position"]

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        group = self._find_category(registry, code)
        if group is None or position >= group.open_count:
            context.user_data.pop(_SESSION_KEY, None)
            await query.edit_message_text(
                f"✅ Kategorie <b>{html.escape(code)}</b> abgeschlossen — "
                "keine offenen Befunde mehr.",
                parse_mode="HTML",
                reply_markup=self._back_keyboard("review:start", "◀️ Zur Übersicht"),
            )
            return

        finding = group.findings[position]
        text = (
            f"🔎 <b>{html.escape(code)}</b>\n\n"
            f"Befund {position + 1}/{group.open_count}\n\n"
            f"{html.escape(_finding_location(finding))}"
        )
        if finding.path:
            text += f"\n\n{html.escape(finding.path)}"
        if finding.message:
            text += f"\n\n{html.escape(finding.message)}"
        if finding.occurrences > 1:
            text += f"\n\nBereits {finding.occurrences}x erkannt"

        fid = finding.finding_id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Resolve", callback_data=f"review:resolve:{fid}")],
            [InlineKeyboardButton("🚫 False Positive", callback_data=f"review:fp:{fid}")],
            [InlineKeyboardButton("⏭️ Skip", callback_data=f"review:skip:{fid}")],
            [InlineKeyboardButton("❌ Review beenden", callback_data=f"review:quit:{fid}")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    async def handle_single_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, finding_id: str,
    ) -> None:
        query = update.callback_query
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await query.answer("⛔ Keine Berechtigung", show_alert=True)
            return
        await query.answer()

        session = context.user_data.get(_SESSION_KEY)
        if not session:
            await self._show_category_gone(query)
            return

        if action == "quit":
            context.user_data.pop(_SESSION_KEY, None)
            await query.edit_message_text(
                "❌ Review beendet — bisherige Bewertungen bleiben gespeichert.",
                reply_markup=self._back_keyboard("review:start", "◀️ Zur Übersicht"),
            )
            return

        registry = self._load_registry()
        if registry is None:
            text, keyboard = self._registry_error_message()
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        # ── Stale-Callback-Absicherung (Abschnitt 24) ─────────────────────
        # Vor JEDER Statusänderung: existiert das Finding noch, und ist es
        # noch OPEN? Ein veralteter Button (z.B. nach parallelem Review
        # durch einen zweiten Admin) darf keine Änderung mehr auslösen.
        finding = registry.get(finding_id)
        if finding is None or finding.status != STATUS_OPEN:
            await query.edit_message_text(
                "⚠️ Dieser Befund ist nicht mehr verfügbar.\n\n"
                "Die Findings wurden zwischenzeitlich aktualisiert.",
                reply_markup=self._back_keyboard("review:start", "🔄 Aktualisieren"),
            )
            return

        reviewer = f"telegram:{user_id}"
        if action == "resolve":
            registry.review_finding(finding_id, STATUS_RESOLVED, reviewed_by=reviewer)
            registry.save()
            self.logger.info(f"📋 [REVIEW] {finding_id} -> RESOLVED (User {user_id})")
        elif action == "fp":
            registry.review_finding(finding_id, STATUS_FALSE_POSITIVE, reviewed_by=reviewer)
            registry.save()
            self.logger.info(f"📋 [REVIEW] {finding_id} -> FALSE_POSITIVE (User {user_id})")
        elif action == "skip":
            session["position"] += 1
        else:
            self.logger.warning(f"⚠️ Unbekannte Review-Aktion: {action!r}")
            return

        await self._render_current_finding(query, context)
