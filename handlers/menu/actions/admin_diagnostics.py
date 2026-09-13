# handlers/menu/actions/admin_diagnostics.py
# -*- coding: utf-8 -*-
"""
Admin > Diagnose & Monitoring-Actions (System-Status, System-Logs,
Error-Verwaltung, Logger-Verwaltung) - entspricht der bestehenden
"admin_group_diagnostics"-Gruppierung in initialize_menu_structure().

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py und handlers/menu/rich_menu_handler.py
verschoben (reine Move-Operation). Permission-Prüfungen (is_admin_or_owner)
werden unverändert wiederverwendet (ARCH-023-Ergebnis), nicht neu
gestaltet.
"""

from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.permissions import is_admin_or_owner


# ====== Logger-Verwaltung ======


async def handle_logger_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    logger_handler,
    logger,
) -> None:
    """Spezial-Handler für alle logger_* Callbacks"""
    if not logger_handler:
        await update.callback_query.answer("⚠️ Logger-Handler nicht verfügbar")
        return

    query = update.callback_query
    await query.answer()

    routing_map = {
        "logger_main_menu": logger_handler.show_main_menu,
        "logger_modules_list": logger_handler.show_modules_list,
        "logger_global_level": logger_handler.show_global_level_menu,
        "logger_files_list": logger_handler.show_log_files_list,
        "logger_global_stats": logger_handler.show_comprehensive_statistics,
        "logger_handlers_list": logger_handler.manage_handlers_advanced,
        "logger_cleanup_menu": logger_handler.show_cleanup_menu,
        "logger_enable_all": logger_handler.enable_all_modules,
        "logger_disable_all": logger_handler.disable_all_modules,
        "logger_add_module": logger_handler.add_module,
        "logger_files_stats": logger_handler.show_log_files_stats,
        "logger_configure_handlers": logger_handler.configure_handlers,
        "logger_handler_details": logger_handler.handler_details,
        "logger_add_handler": logger_handler.add_handler,
        "logger_remove_handler": logger_handler.remove_handler,
        "logger_reload_handlers": logger_handler.reload_handlers,
    }

    if callback_data.startswith("logger_module_detail_"):
        module_name = callback_data.replace("logger_module_detail_", "")
        await logger_handler.show_module_detail(update, context, module_name)
        return

    if callback_data.startswith("logger_module_toggle_"):
        module_name = callback_data.replace("logger_module_toggle_", "")
        await logger_handler.toggle_module(update, context, module_name)
        return

    if callback_data.startswith("logger_module_level_"):
        module_name = callback_data.replace("logger_module_level_", "")
        await logger_handler.show_module_level_menu(update, context, module_name)
        return

    if callback_data.startswith("logger_set_module_level_"):
        parts = callback_data.replace("logger_set_module_level_", "").split("_", 1)
        if len(parts) == 2:
            module_name, level = parts
            await logger_handler.set_module_level(update, context, module_name, level)
        return

    if callback_data.startswith("logger_set_global_level_"):
        level = callback_data.replace("logger_set_global_level_", "")
        await logger_handler.set_global_log_level(update, context, level)
        return

    if callback_data.startswith("logger_file_detail_"):
        filename = callback_data.replace("logger_file_detail_", "")
        await logger_handler.show_log_file_detail(update, context, filename)
        return

    if callback_data.startswith("logger_file_download_"):
        filename = callback_data.replace("logger_file_download_", "")
        await logger_handler.download_log_file(update, context, filename)
        return

    handler_method = routing_map.get(callback_data)
    if handler_method:
        await handler_method(update, context)
    else:
        logger.warning(f"⚠️ Unbekannter Logger-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")


# ====== Error-Verwaltung ======


async def handle_error_admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    error_admin_interface,
    logger,
) -> None:
    """Spezial-Handler für alle erradmin:* Callbacks"""
    if not error_admin_interface:
        await update.callback_query.answer("⚠️ Error Admin Interface nicht verfügbar")
        return

    user_id = update.effective_user.id
    if not error_admin_interface.is_admin(user_id):
        await update.callback_query.answer("⛔ Keine Berechtigung")
        return

    logger.debug(f"🚨 ErrorAdmin-Callback: {callback_data}")

    routing_map = {
        "erradmin:show_stats": error_admin_interface.handle_error_stats_command,
        "erradmin:show_report": error_admin_interface.handle_error_report_command,
        "erradmin:show_recent": error_admin_interface.handle_recent_errors_command,
        "erradmin:reset_confirm": error_admin_interface.show_reset_stats_confirm,
        "erradmin:reset_execute": error_admin_interface.execute_reset_stats,
    }

    handler_method = routing_map.get(callback_data)
    if handler_method:
        await handler_method(update, context)
    else:
        logger.warning(f"⚠️ Unbekannter ErrorAdmin-Callback: {callback_data}")
        await update.callback_query.answer("⚠️ Funktion nicht implementiert")


# ====== System-Status ======

# STATUS-MENU-CLOSURE: handlers/enhanced_status_handler.py rendert 12
# "status_*"-Buttons (Detail-/History-/Check-/Reset-/Cleanup-Unteransichten
# sowie die Top-Level-Buttons "status_users"/"status_trends"), für die
# KEINE Handler-Implementierung existiert (repoweit verifiziert, siehe
# docs/MusicBot_STATUS_MENU_CLOSURE.md) - reine, bislang unfertige UI-
# Vorschau ohne Backing-Funktion. Bewusst NICHT auf eine erfundene/
# angenäherte Funktion geroutet (Master-Prompt: "nicht blind
# registrieren"). Damit ein Klick darauf nicht wie ein echter, unerwarteter
# Bug aussieht (bisher identisch zu einem tatsächlich unbekannten
# callback_data-Wert behandelt - "⚠️ Unbekannter Status-Callback" im Log),
# werden sie hier explizit als bekannter Platzhalter geführt: freundliche
# Nutzer-Rückmeldung, aber kein WARNING-Log wie bei einem echten,
# unerwarteten Callback-Wert.
_PLACEHOLDER_STATUS_CALLBACKS = frozenset(
    {
        "status_users",
        "status_trends",
        "status_system_detail",
        "status_system_history",
        "status_bot_handlers",
        "status_bot_logs",
        "status_services_check",
        "status_services_detail",
        "status_performance_history",
        "status_performance_reset",
        "status_storage_cleanup",
        "status_storage_detail",
    }
)


async def handle_status_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    status_handler,
    logger,
) -> None:
    """Spezial-Handler für alle status_* Callbacks"""
    if not status_handler:
        await update.callback_query.answer("⚠️ Status-Handler nicht verfügbar")
        return

    query = update.callback_query
    await query.answer()

    logger.debug(f"📊 Status-Callback: {callback_data}")

    routing_map = {
        "status_menu": status_handler.show_status_menu,
        "status_system": status_handler.show_system_status,
        "status_bot": status_handler.show_bot_status,
        "status_services": status_handler.show_services_status,
        "status_performance": status_handler.show_performance_status,
        "status_storage": status_handler.show_storage_status,
        "status_refresh": status_handler.show_status_menu,
    }

    handler_method = routing_map.get(callback_data)
    if handler_method:
        await handler_method(update, context)
    elif callback_data in _PLACEHOLDER_STATUS_CALLBACKS:
        logger.debug(
            f"📋 Status-Platzhalter aufgerufen (noch nicht implementiert): {callback_data}"
        )
        await query.answer("🚧 Diese Funktion ist noch nicht implementiert.")
    else:
        logger.warning(f"⚠️ Unbekannter Status-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")


async def handle_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, status_handler, show_handler_not_available):
    """Wrapper für Status-Menü"""
    if status_handler:
        await status_handler.show_status_menu(update, context)
    else:
        await show_handler_not_available(update, "Status-Handler")


# ====== System-Logs (RichMenuHandler) ======


async def handle_view_logs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    logger,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_admin_or_owner(user_id, config):
        await query.answer("⛔ Keine Berechtigung")
        return
    await query.answer()
    try:
        log_file = Path(config.LOG_FILE)
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_lines = lines[-20:]
            log_text = "".join(last_lines)
            await query.edit_message_text(
                f"📄 **System-Logs** (letzte 20 Zeilen)\n\n```\n{log_text[:3000]}\n```",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                "📄 **System-Logs**\n\nLog-Datei nicht gefunden."
            )
    except Exception as e:
        logger.error(f"❌ Fehler beim Laden der Logs: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Logs")
