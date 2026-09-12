# handlers/menu/actions/duplicates.py
# -*- coding: utf-8 -*-
"""
Duplikat-Verwaltung ("dup:*"-Callbacks).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py::_handle_duplicate_callback
verschoben (reine Move-Operation). Eigenes Modul statt Zusammenlegung
mit admin_operations.py, da Duplicate Detection laut CLAUDE.md
Abschnitt 15 eine eigene P0-Domäne ist, nicht Teil von "Bibliothek".
"""

from telegram import Update
from telegram.ext import ContextTypes


async def handle_duplicate_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    duplicate_handler,
    logger,
) -> None:
    """Spezial-Handler für alle dup:* Callbacks"""
    if not duplicate_handler:
        await update.callback_query.answer("⚠️ Duplicate-Handler nicht verfügbar")
        return

    query = update.callback_query

    logger.debug(f"♻️ Duplicate-Callback: {callback_data}")

    if callback_data == "dup:show_stats":
        await query.answer("Lade Statistiken...")
        await duplicate_handler.show_statistics_menu(update, context)
        return

    if callback_data == "dup:clear_cache_confirm":
        await query.answer()
        await duplicate_handler.show_clear_cache_confirm(update, context)
        return

    if callback_data == "dup:clear_cache_execute":
        await query.answer("Cache wird geleert...")
        await duplicate_handler.execute_clear_cache(update, context)
        return

    logger.warning(f"⚠️ Unbekannter Duplicate-Callback: {callback_data}")
    await query.answer("⚠️ Funktion nicht implementiert")
