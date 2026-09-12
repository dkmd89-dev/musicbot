# handlers/menu/actions/library.py
# -*- coding: utf-8 -*-
"""
Admin > Bibliothek & Navidrome-Actions: Reprocessing, MusicBot Doctor,
Library Health Review, Repair MusicBot - entspricht der bestehenden
"admin_group_library"-Gruppierung in initialize_menu_structure()
(Navidrome-Scan selbst liegt in actions/admin_operations.py, da dort
keine eigene Handler-Klasse existiert - reine RichMenuHandler-Logik).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py verschoben (reine Move-Operation).
Jede Callback-Dispatcher-Funktion behält ihre eigene, historisch
bewusst unterschiedliche Defense-in-Depth-Berechtigungsprüfung
(Reprocessing: reiner Owner-Check gegen config.OWNER_USER_ID; Doctor/
Review/Repair: is_admin_check-Callable, siehe ARCH-023/P-3) -
keine Vereinheitlichung, das war ARCH-023-Scope und ist abgeschlossen.
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.actions._common import show_handler_not_available


# ====== METADATA-REPROCESSING ======


async def handle_reprocessing_show(update: Update, context: ContextTypes.DEFAULT_TYPE, reprocessing_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu den
    Navidrome-Actions."""
    if reprocessing_handler:
        await reprocessing_handler.show_artist_list(update, context)
    else:
        await show_handler_not_available(update, "Reprocessing-Handler")


async def handle_reprocessing_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    reprocessing_handler,
    config,
    logger,
) -> None:
    """
    Dispatcher für alle reprocess:* Callbacks.

    Routing:
      reprocess:show        → Artist-Liste anzeigen
      reprocess:pick:<idx>  → Dry-Run für Artist <idx> starten
      reprocess:live:<idx>  → LIVE-Lauf für Artist <idx> starten

    Eigener Owner-Check hier (Defense-in-Depth, analog zu maint: -
    bewusst NICHT in _ADMIN_ONLY_PREFIXES aufgenommen, da OWNER
    strenger als ADMIN ist und dieser Dispatcher seinen eigenen,
    passenden Check macht statt sich auf den ADMIN-Check zu verlassen).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if user_id != getattr(config, "OWNER_USER_ID", None):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Owner {user_id} versuchte "
            f"Reprocessing-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not reprocessing_handler:
        await query.answer("⚠️ Reprocessing-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "reprocess:show":
        await reprocessing_handler.show_artist_list(update, context)
        return

    if callback_data.startswith("reprocess:pick:"):
        idx_str = callback_data[len("reprocess:pick:") :]
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await reprocessing_handler.handle_pick(update, context, idx)
        return

    if callback_data.startswith("reprocess:live:"):
        idx_str = callback_data[len("reprocess:live:") :]
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await reprocessing_handler.handle_live(update, context, idx)
        return

    await query.answer("⚠️ Unbekannter Reprocessing-Callback")


# ====== MUSICBOT DOCTOR (Phase 3, P1.3) ======


async def handle_doctor_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, doctor_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_reprocessing_show()."""
    if doctor_handler:
        await doctor_handler.handle_scan(update, context)
    else:
        await show_handler_not_available(update, "Doctor-Handler")


async def handle_doctor_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    doctor_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle doctor:* Callbacks.

    Routing:
      doctor:scan                 → Health-Scan starten (auch über
                                     den Menüpunkt direkt erreichbar)
      doctor:apply_safe           → Bestätigung vor SAFE_AUTOMATIC-Apply
      doctor:apply_safe_confirm   → SAFE_AUTOMATIC-Apply tatsächlich starten

    Eigener Admin-Check hier (Defense-in-Depth, analog zu maint:/
    reprocess: - callback_data ist frei sendbar, siehe SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Doctor-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not doctor_handler:
        await query.answer("⚠️ Doctor-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "doctor:scan":
        await doctor_handler.handle_scan(update, context)
        return

    if callback_data == "doctor:apply_safe":
        await doctor_handler.handle_apply_safe_confirm_prompt(update, context)
        return

    if callback_data == "doctor:apply_safe_confirm":
        await doctor_handler.handle_apply_safe_confirmed(update, context)
        return

    await query.answer("⚠️ Unbekannter Doctor-Callback")


# ====== LIBRARY HEALTH REVIEW ======


async def handle_review_start(update: Update, context: ContextTypes.DEFAULT_TYPE, review_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_doctor_scan()."""
    if review_handler:
        await review_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Review-Handler")


async def handle_review_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    review_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle review:* Callbacks.

    Routing (siehe handlers/library_health_review_handler.py):
      review:start                    → Übersicht (Severity-Verteilung)
      review:severity:<TIER>          → Kategorien dieser Severity-Stufe
      review:category:<CODE>          → Kategorie-Aktionen
      review:edit:<CODE>              → Einzelreview starten
      review:resolve:<finding_id>     → Resolve im Einzelreview
      review:fp:<finding_id>          → False Positive im Einzelreview
      review:skip:<finding_id>        → Skip im Einzelreview
      review:quit:<finding_id>        → Review beenden
      review:batchconfirm:<CODE>      → Bestätigung vor Batch-False-Positive
      review:batchyes:<CODE>          → Batch-False-Positive ausführen
      review:accepted                 → Liste der akzeptierten Findings (nach Code)
      review:acccode:<CODE>           → akzeptierte Findings dieser Kategorie
      review:accshow:<finding_id>     → ein akzeptiertes Finding (Detail)
      review:unaccept:<finding_id>    → Acceptance zurücknehmen (→ OPEN)

    Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
    maint:/reprocess: - callback_data ist frei sendbar, siehe SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Review-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not review_handler:
        await query.answer("⚠️ Review-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "review:start":
        await review_handler.handle_start(update, context)
        return
    if callback_data == "review:accepted":
        await review_handler.handle_accepted_list(update, context)
        return

    parts = callback_data.split(":", 2)
    if len(parts) < 3:
        await query.answer("⚠️ Unbekannter Review-Callback")
        return
    action, payload = parts[1], parts[2]

    if action == "severity":
        await review_handler.handle_severity(update, context, payload)
    elif action == "category":
        await review_handler.handle_category(update, context, payload)
    elif action == "edit":
        await review_handler.handle_edit_start(update, context, payload)
    elif action == "batchconfirm":
        await review_handler.handle_batch_confirm_prompt(update, context, payload)
    elif action == "batchyes":
        await review_handler.handle_batch_confirmed(update, context, payload)
    elif action in ("resolve", "fp", "skip", "quit"):
        await review_handler.handle_single_action(update, context, action, payload)
    elif action == "acccode":
        await review_handler.handle_accepted_category(update, context, payload)
    elif action == "accshow":
        await review_handler.handle_accepted_show(update, context, payload)
    elif action == "unaccept":
        await review_handler.handle_unaccept(update, context, payload)
    else:
        await query.answer("⚠️ Unbekannter Review-Callback")


# ====== REPAIR MUSICBOT ======


async def handle_repair_start(update: Update, context: ContextTypes.DEFAULT_TYPE, repair_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_doctor_scan()/handle_review_start()."""
    if repair_handler:
        await repair_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Repair-Handler")


async def handle_repair_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    repair_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle repair:* Callbacks.

    Routing (siehe handlers/repair_musicbot_handler.py):
      repair:start      → Startseite
      repair:analyze    → Reparaturen analysieren / Offene Reparaturen
      repair:proposals  → Reparaturvorschläge (SAFE_AUTOMATIC)
      repair:preview    → Read-only Vorschau
      repair:confirm    → explizite Bestätigung vor Ausführung
      repair:execute    → tatsächliche Ausführung (Berechtigung erneut geprüft)
      repair:history    → Reparaturhistorie
      repair:stats      → Repair-Statistik

    Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
    review:/maint:/reprocess: - callback_data ist frei sendbar, siehe
    SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Repair-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not repair_handler:
        await query.answer("⚠️ Repair-Handler nicht verfügbar", show_alert=True)
        return

    routing = {
        "repair:start": repair_handler.handle_start,
        "repair:analyze": repair_handler.handle_analyze,
        "repair:proposals": repair_handler.handle_proposals,
        "repair:preview": repair_handler.handle_preview,
        "repair:confirm": repair_handler.handle_confirm_prompt,
        "repair:execute": repair_handler.handle_execute,
        "repair:history": repair_handler.handle_history,
        "repair:stats": repair_handler.handle_statistics,
    }
    handler_fn = routing.get(callback_data)
    if handler_fn is None:
        await query.answer("⚠️ Unbekannter Repair-Callback")
        return
    await handler_fn(update, context)
