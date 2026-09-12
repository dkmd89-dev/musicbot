# handlers/menu/rendering.py
# -*- coding: utf-8 -*-
"""
Menü-Rendering: Telegram-Tastatur- und Text-Erzeugung sowie das
Anzeigen/Aktualisieren eines Menüs.

ARCH-024/P-4 (Rendering Extraction): 1:1 aus
handlers/menu/rich_menu_system.py::render_menu()/get_menu_text()/
show_menu() verschoben (reine Move-Operation).

render_menu()/get_menu_text() waren bereits zustandslose Funktionen
ihrer Argumente (kein self.-Zugriff im Methodenkörper) - reine
Verschiebung ohne Signaturänderung. show_menu() benötigt Session-/
Registry-/Permission-Zugriff und nimmt diese Abhängigkeiten explizit
entgegen (kein Zugriff auf die RichMenuSystem-Instanz selbst - Rendering
beantwortet nur "wie wird etwas dargestellt", nicht "darf der Nutzer
das" oder "wie wird navigiert").
"""

from typing import Callable, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.menu.models import AccessLevel, MenuItem


def render_menu(
    menu_item: MenuItem, user_level: AccessLevel = AccessLevel.USER
) -> InlineKeyboardMarkup:
    """Erstellt Telegram InlineKeyboard für Menü"""
    keyboard = []

    accessible_items = [
        item
        for item in menu_item.children
        if item.is_active and item.is_accessible(user_level)
    ]

    for i in range(0, len(accessible_items), 2):
        row = []
        for item in accessible_items[i : i + 2]:
            button_text = f"{item.emoji} {item.title}"
            row.append(
                InlineKeyboardButton(button_text, callback_data=item.callback_data)
            )
        keyboard.append(row)

    if menu_item.parent:
        keyboard.append(
            [InlineKeyboardButton("⬅️ Zurück", callback_data="menu:back")]
        )

    if not menu_item.parent or menu_item.id == "main":
        keyboard.append(
            [InlineKeyboardButton("❌ Schließen", callback_data="menu:close")]
        )
    elif menu_item.parent and menu_item.id != "main":
        keyboard.append(
            [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")]
        )

    return InlineKeyboardMarkup(keyboard)


def get_menu_text(menu_item: MenuItem) -> str:
    """Erstellt Menü-Text mit Breadcrumb"""
    breadcrumb = " > ".join(menu_item.get_breadcrumb())

    text_parts = [
        f"📍 **Navigation:** {breadcrumb}",
        "",
    ]

    if menu_item.description:
        text_parts.extend(
            [
                menu_item.description,
                "",
            ]
        )

    if menu_item.has_children():
        text_parts.append("Wähle eine Option:")

    return "\n".join(text_parts)


async def show_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    menu_id: Optional[str],
    menu_registry: Dict[str, MenuItem],
    root_menu: MenuItem,
    get_session: Callable,
    get_user_access_level: Callable,
    logger,
) -> None:
    """Zeigt Menü an oder aktualisiert es"""
    query = update.callback_query
    user_id = update.effective_user.id

    session = get_session(user_id)

    if menu_id:
        menu_item = menu_registry.get(menu_id, root_menu)
    elif session.current_menu:
        menu_item = session.current_menu
    else:
        menu_item = root_menu

    session.navigate_to(menu_item)

    user_level = get_user_access_level(user_id)

    text = get_menu_text(menu_item)
    keyboard = render_menu(menu_item, user_level)

    try:
        if query:
            if (
                query.message.text == text
                and query.message.reply_markup == keyboard
            ):
                await query.answer("ℹ️ Ansicht bereits aktuell.")
                return

            await query.answer()
            await query.edit_message_text(
                text, reply_markup=keyboard, parse_mode="Markdown"
            )
            session.message_id = query.message.message_id
        else:
            message = await update.message.reply_text(
                text, reply_markup=keyboard, parse_mode="Markdown"
            )
            session.message_id = message.message_id

        logger.info(f"📱 Menü '{menu_item.id}' angezeigt für User {user_id}")

    except Exception as e:
        if "Message is not modified" in str(e):
            logger.debug("Menü-Update übersprungen (keine Änderung).")
        else:
            logger.error(f"❌ Fehler beim Anzeigen des Menüs: {e}", exc_info=True)
