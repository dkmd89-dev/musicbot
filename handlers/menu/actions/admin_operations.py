# handlers/menu/actions/admin_operations.py
# -*- coding: utf-8 -*-
"""
Admin > Bot & Betrieb-Actions: Backup-Verwaltung, Bot-Neustart,
Wartungsmodus, Navidrome-Scan - entspricht der bestehenden
"admin_group_operations"-Gruppierung in initialize_menu_structure()
(Navidrome-Scan ist UI-seitig unter admin_group_library einsortiert,
liegt hier aber bei den übrigen reinen-Inline-Logik-Actions ohne eigene
Handler-Klasse - siehe P-1-Audit).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py und handlers/menu/rich_menu_handler.py
verschoben (reine Move-Operation). Wartungsmodus bleibt bewusst ohne
eigene Handler-Klasse (siehe ursprünglicher Kommentar in
rich_menu_system.py) - Logik liest/schreibt MaintenanceModeStore direkt.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.menu.actions._common import show_handler_not_available
from emoji import EMOJI
from helfer.markdown_helfer import escape_md_v2
from utils.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError
from handlers.menu.permissions import is_admin_or_owner


# ====== BACKUP-VERWALTUNG ======


async def handle_backup_main(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_handler):
    """Wrapper: Backup-Hauptmenü"""
    if backup_handler:
        await backup_handler.show_main_menu(update, context)
    else:
        await show_handler_not_available(update, "Backup-Handler")


async def handle_backup_bot_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_handler):
    """Wrapper: Bot-Backup Bestätigung"""
    if backup_handler:
        await backup_handler.confirm_bot_backup(update, context)
    else:
        await show_handler_not_available(update, "Backup-Handler")


async def handle_backup_lib_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_handler):
    """Wrapper: Library-Backup Bestätigung"""
    if backup_handler:
        await backup_handler.confirm_lib_backup(update, context)
    else:
        await show_handler_not_available(update, "Backup-Handler")


async def handle_backup_list_bot(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_handler):
    """Wrapper: Bot-Backup-Liste anzeigen"""
    if backup_handler:
        await backup_handler.show_list_bot(update, context)
    else:
        await show_handler_not_available(update, "Backup-Handler")


async def handle_backup_list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_handler):
    """Wrapper: Library-Backup-Liste anzeigen"""
    if backup_handler:
        await backup_handler.show_list_lib(update, context)
    else:
        await show_handler_not_available(update, "Backup-Handler")


async def handle_backup_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    backup_handler,
    logger,
) -> None:
    """Spezial-Handler für alle backup_* Callbacks"""
    if not backup_handler:
        await update.callback_query.answer("⚠️ Backup-Handler nicht verfügbar")
        return

    query = update.callback_query
    await query.answer()

    logger.debug(f"💾 Backup-Callback: {callback_data}")

    if callback_data.startswith("backup_delete_confirm_"):
        filename = callback_data.replace("backup_delete_confirm_", "")
        await backup_handler.confirm_delete(update, context, filename)
        return

    if callback_data.startswith("backup_delete_"):
        filename = callback_data.replace("backup_delete_", "")
        await backup_handler.delete_backup(update, context, filename)
        return

    routing_map = {
        "backup_main": backup_handler.show_main_menu,
        "backup_bot_confirm": backup_handler.confirm_bot_backup,
        "backup_lib_confirm": backup_handler.confirm_lib_backup,
        "backup_bot_start": backup_handler.start_bot_backup,
        "backup_lib_start": backup_handler.start_lib_backup,
        "backup_list_bot": backup_handler.show_list_bot,
        "backup_list_lib": backup_handler.show_list_lib,
    }

    handler_method = routing_map.get(callback_data)
    if handler_method:
        await handler_method(update, context)
    else:
        logger.warning(f"⚠️ Unbekannter Backup-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")


# ====== BOT-NEUSTART ======


async def handle_restart_show(update: Update, context: ContextTypes.DEFAULT_TYPE, restart_handler) -> None:
    """
    Einstiegspunkt aus dem Menü-System für den Bot-Neustart.
    Leitet an BotRestartHandler.show_restart_confirm() weiter.
    """
    if not restart_handler:
        query = update.callback_query
        await query.answer("⚠️ Restart-Handler nicht verfügbar", show_alert=True)
        return
    await restart_handler.show_restart_confirm(update, context)


async def handle_restart_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    restart_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle restart:* Callbacks.

    Routing:
      restart:show    → Bestätigungs-Dialog anzeigen
      restart:confirm → Neustart ausführen
      restart:cancel  → Neustart abbrechen
    """
    if not restart_handler:
        await update.callback_query.answer(
            "⚠️ Restart-Handler nicht verfügbar", show_alert=True
        )
        return

    user_id = update.effective_user.id
    if not is_admin_check(user_id):
        await update.callback_query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    logger.debug(f"🔄 Restart-Callback: {callback_data} von User {user_id}")

    routing: dict = {
        "restart:show": restart_handler.show_restart_confirm,
        "restart:confirm": restart_handler.execute_restart,
        "restart:cancel": restart_handler.cancel_restart,
    }

    handler_fn = routing.get(callback_data)
    if handler_fn:
        await handler_fn(update, context)
    else:
        logger.warning(f"⚠️ Unbekannter Restart-Callback: {callback_data}")
        await update.callback_query.answer("⚠️ Unbekannte Aktion")


# ====== WARTUNGSMODUS ======
#
# Bewusst OHNE eigene Handler-Klasse: die Logik beschraenkt sich auf
# Lesen/Schreiben des einen booleschen Zustands im geteilten
# MaintenanceModeStore (services/bot_maintenance.py) - kein
# Bestaetigungsdialog (anders als beim Neustart), da instant reversibel
# und ohne Datenverlust/Verbindungsabbruch.


async def handle_maintenance_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    is_admin_check,
    maintenance_store,
) -> None:
    """
    Einstiegspunkt aus dem Menü-System - zeigt den aktuellen
    Wartungsmodus-Status mit Toggle-Button.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_admin_check(user_id):
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return
    await query.answer()

    if not maintenance_store:
        await query.edit_message_text("⚠️ Wartungsmodus-Speicher nicht verfügbar")
        return

    active = maintenance_store.is_active()
    status_text = "🔴 AKTIV" if active else "🟢 Inaktiv"
    toggle_label = (
        "🟢 Wartungsmodus beenden" if active else "🔴 Wartungsmodus aktivieren"
    )

    text = (
        "🛠️ <b>Wartungsmodus</b>\n\n"
        f"Status: {status_text}\n\n"
        "Im aktiven Wartungsmodus können nur Admins/Owner den Bot "
        "normal nutzen - alle anderen Nutzer erhalten an jedem "
        "Einstiegspunkt eine Wartungsmeldung statt der eigentlichen "
        "Funktion."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(toggle_label, callback_data="maint:toggle")],
            [
                InlineKeyboardButton(
                    "◀️ Zurück", callback_data="menu:admin_group_operations"
                )
            ],
        ]
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def handle_maintenance_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    is_admin_check,
    maintenance_store,
    logger,
) -> None:
    """
    Dispatcher für alle maint:* Callbacks.

    Routing:
      maint:show   → Status anzeigen
      maint:toggle → Zustand umschalten, danach Status erneut anzeigen
    """
    query = update.callback_query
    user_id = update.effective_user.id

    # Admin-Check (Defense-in-Depth, analog zu restart:/erradmin: -
    # maint: ist bewusst NICHT in _ADMIN_ONLY_PREFIXES aufgenommen,
    # da dieser Dispatcher seinen eigenen Check macht).
    if not is_admin_check(user_id):
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not maintenance_store:
        await query.answer(
            "⚠️ Wartungsmodus-Speicher nicht verfügbar", show_alert=True
        )
        return

    if callback_data == "maint:show":
        await handle_maintenance_show(update, context, is_admin_check, maintenance_store)
        return

    if callback_data == "maint:toggle":
        new_state = not maintenance_store.is_active()
        maintenance_store.set_active(new_state, changed_by_user_id=user_id)
        logger.warning(
            f"🛠️ Wartungsmodus {'aktiviert' if new_state else 'deaktiviert'} "
            f"von Admin {user_id}"
        )
        await handle_maintenance_show(update, context, is_admin_check, maintenance_store)
        return

    await query.answer("⚠️ Unbekannter Wartungsmodus-Callback")


# ====== NAVIDROME-SCAN (RichMenuHandler) ======


async def handle_navidrome_scan(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    logger,
) -> None:
    """
    ARCH-009 Phase 9 (Umsetzung A): ruft NavidromeScanTrigger.run_scan()
    direkt auf statt über die inzwischen entfernte
    NavidromeAPI.execute_scan()-Bridge (api/navidrome_api.py, war seit
    ARCH-009 Phase 5 nur noch ein reiner Pass-Through ohne eigene
    Telegram-Formatierung). Die MarkdownV2-Nachrichtenbildung (Erfolg,
    Fehlschlag, Timeout, generische Exception) bleibt unverändert hier -
    Text/Emojis/Escaping 1:1 übernommen, siehe
    docs/archive/arch/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md
    und docs/archive/arch/MusicBot_ARCH-009_Phase9_Finaler_Migrationsabschluss_Analyse.md.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_admin_or_owner(user_id, config):
        await query.answer("⛔ Keine Berechtigung")
        return
    await query.answer("🔄 Starte Scan ...")
    try:
        try:
            result = await NavidromeScanTrigger.run_scan()
            if result.success:
                message = f"{EMOJI['scan']} Scan erfolgreich: \n```{escape_md_v2(result.stdout)}```"
            else:
                message = f"{EMOJI['error']} Scan fehlgeschlagen: \n```{escape_md_v2(result.stderr)}```"
        except ScanTimeoutError as e:
            message = f"{EMOJI['warning']} Scan dauert länger als {e.timeout_seconds} Sekunden \\– bitte im Log prüfen\\."
        await query.edit_message_text(message, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"❌ Navidrome-Scan-Fehler: {e}", exc_info=True)
        await query.edit_message_text(
            f"{EMOJI['error']} Unerwarteter Fehler: `{escape_md_v2(str(e))}`",
            parse_mode="MarkdownV2",
        )
