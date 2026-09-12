# handlers/menu/actions/usermgmt.py
# -*- coding: utf-8 -*-
"""
Benutzerverwaltungs-Actions ("usermgmt_*"-Callbacks + Menü-Einstieg
"admin_users").

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py und handlers/menu/rich_menu_handler.py
verschoben (reine Move-Operation). Permission-Prüfung (is_admin_or_owner)
unverändert wiederverwendet (ARCH-023-Ergebnis).
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.permissions import is_admin_or_owner


async def handle_usermgmt_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    user_mgmt_handler,
    logger,
) -> None:
    """
    Spezial-Handler für alle usermgmt_* Callbacks
    Unterstützt Navidrome-User-Workflows
    """
    if not user_mgmt_handler:
        await update.callback_query.answer("⚠️ UserManagement-Handler nicht verfügbar")
        return

    query = update.callback_query
    admin_user_id = update.effective_user.id
    await query.answer()

    logger.debug(f"👥 UserMgmt-Callback: {callback_data}")

    if callback_data == "usermgmt_add_user":
        context.user_data["workflow"] = "add_user_id"
        context.user_data.pop("pending_user_id", None)
        context.user_data.pop("target_user_id", None)
        await query.edit_message_text(
            "➕ **Neuen Benutzer hinzufügen (Schritt 1/2)**\n\n"
            "Bitte sende mir jetzt die **Telegram User-ID** des neuen Benutzers als Nachricht.\n\n"
            "*(Du kannst /cancel eingeben, um abzubrechen)*",
            parse_mode="Markdown",
        )
        return

    if callback_data.startswith("usermgmt_set_navidrome_"):
        target_user_id = callback_data.replace("usermgmt_set_navidrome_", "")
        context.user_data["workflow"] = "edit_navidrome_user"
        context.user_data["target_user_id"] = target_user_id
        await query.edit_message_text(
            f"👤 **Navidrome-Benutzer festlegen**\n\n"
            f"Betroffene User-ID: `{target_user_id}`\n\n"
            "Bitte sende mir jetzt den **Navidrome-Benutzernamen** für diesen Benutzer.\n\n"
            "*(Du kannst /cancel eingeben, um abzubrechen)*",
            parse_mode="Markdown",
        )
        return

    if callback_data.startswith("usermgmt_list_"):
        page = int(callback_data.replace("usermgmt_list_", ""))
        await user_mgmt_handler.show_user_management_menu(update, context, page)
        return

    if callback_data.startswith("usermgmt_detail_"):
        user_id = callback_data.replace("usermgmt_detail_", "")
        await user_mgmt_handler.show_user_detail(update, context, user_id)
        return

    if callback_data.startswith("usermgmt_change_role_"):
        user_id = callback_data.replace("usermgmt_change_role_", "")
        await user_mgmt_handler.show_role_change_menu(update, context, user_id)
        return

    if callback_data.startswith("usermgmt_set_role_"):
        parts = callback_data.replace("usermgmt_set_role_", "").split("_", 1)
        if len(parts) == 2:
            user_id, new_role = parts
            await user_mgmt_handler.set_user_role(update, context, user_id, new_role)
        return

    if callback_data.startswith("usermgmt_delete_confirm_"):
        user_id = callback_data.replace("usermgmt_delete_confirm_", "")
        await user_mgmt_handler.delete_user_confirm(update, context, user_id)
        return

    if callback_data.startswith("usermgmt_delete_confirmed_"):
        user_id = callback_data.replace("usermgmt_delete_confirmed_", "")
        await user_mgmt_handler.delete_user(update, context, user_id)
        return

    routing_map = {
        "usermgmt_stats": user_mgmt_handler.show_statistics,
        "usermgmt_search": lambda u, c: query.edit_message_text(
            "🔍 **Benutzer suchen**\n\nDiese Funktion wird gerade entwickelt..."
        ),
        "usermgmt_cleanup": lambda u, c: query.edit_message_text(
            "🗑️ **Aufräumen**\n\nDiese Funktion wird gerade entwickelt..."
        ),
        "usermgmt_pending": lambda u, c: query.edit_message_text(
            "📋 **Pending Users**\n\nKeine wartenden Benutzer."
        ),
    }

    if callback_data.startswith("usermgmt_permissions_"):
        user_id = callback_data.replace("usermgmt_permissions_", "")
        await user_mgmt_handler.show_permission_menu(update, context, user_id)
        return

    if callback_data.startswith("usermgmt_toggle_perm_"):
        parts = callback_data.replace("usermgmt_toggle_perm_", "").split("_", 1)
        if len(parts) == 2:
            user_id, permission = parts
            await user_mgmt_handler.toggle_user_permission(
                update, context, user_id, permission
            )
        return

    if callback_data.startswith("usermgmt_ban_"):
        user_id = callback_data.replace("usermgmt_ban_", "")
        await query.edit_message_text(
            f"🚫 **Benutzer sperren**\n\nUser: {user_id}\n\n"
            "Diese Funktion wird gerade entwickelt..."
        )
        return

    handler_method = routing_map.get(callback_data)
    if handler_method:
        await handler_method(update, context)
    else:
        logger.warning(f"⚠️ Unbekannter UserMgmt-Callback: {callback_data}")
        await query.answer("⚠️ Funktion nicht implementiert")


async def handle_user_management_wrapper(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    user_mgmt_handler,
    error_handler,
    logger,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    if not is_admin_or_owner(user_id, config):
        await query.answer("⛔ Keine Berechtigung")
        return
    await query.answer()
    try:
        if user_mgmt_handler:
            await user_mgmt_handler.show_user_management_menu(update, context, page=0)
        else:
            await query.edit_message_text("⚠️ UserManagement-Handler nicht verfügbar.")
    except Exception as e:
        logger.error(f"❌ Fehler in Benutzerverwaltung: {e}", exc_info=True)
        if error_handler:
            await error_handler.handle_callback_error(
                update, context, "user_management", e
            )
        else:
            await query.edit_message_text("❌ Fehler beim Laden der Benutzerverwaltung")
