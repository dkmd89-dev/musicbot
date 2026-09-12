# handlers/menu/actions/_common.py
# -*- coding: utf-8 -*-
"""
Kleine, zustandslose Helfer, die von mehreren Actions-Modulen geteilt
werden (ARCH-024/P-2).

show_handler_not_available() wurde 1:1 aus
RichMenuSystem._show_handler_not_available() verschoben - reiner
Telegram-Helfer ohne RichMenuSystem-spezifischen State (liest nur
update.callback_query). RichMenuSystem._show_handler_not_available()
bleibt als dünner Delegator bestehen (weiterhin von noch nicht
extrahierten Methoden in rich_menu_system.py selbst genutzt).
"""

from telegram import Update


async def show_handler_not_available(update: Update, handler_name: str) -> None:
    """Zeigt Fehlermeldung wenn Handler nicht verfügbar"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"⚠️ {handler_name} nicht verfügbar\n\n"
        f"Bitte warte bis das System vollständig geladen ist."
    )
