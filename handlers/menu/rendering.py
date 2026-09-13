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

Telegram Start/Help/Menu UX Finalization v2: show_menu() akzeptiert
optional `header_text` - ein bereits fertig formatierter, vorangestellter
Textblock (z. B. die kurze /start-Begrüßung aus content/greeting.py).
Damit lassen sich Begrüßung + zentrales Hauptmenü in EINER Telegram-
Nachricht kombinieren, ohne eine zweite Rendering-/Menü-Implementierung
zu bauen - `text`/`keyboard` bleiben exakt die des angeforderten Menüs,
nur der sichtbare Nachrichtentext bekommt einen Präfix. Bei `header_text
= None` (Standard, z. B. /menu und jede normale Navigation) ist das
Verhalten unverändert identisch zum bisherigen Stand - reine additive
Erweiterung, keine Breaking Change.
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


def render_result_navigation(menu_item: MenuItem) -> InlineKeyboardMarkup:
    """ARCH-029 (Menu Navigation Continuity): kontextuelle Navigation für
    die ERGEBNISNACHRICHT einer Menü-Action (z. B. "Diese Woche" ->
    Wochenstatistik-Text) - abgeleitet ausschließlich aus der statischen
    Parent-Kette von `menu_item` im MenuItem-Baum (dieselbe Struktur, die
    bereits get_breadcrumb() nutzt), KEIN Session-/History-Zugriff.

    Bewusst NICHT über "menu:back"/session.history: Action-Handler werden
    von RichMenuSystem.handle_callback() direkt aufgerufen, ohne
    show_menu()/session.navigate_to() - session.current_menu bleibt daher
    beim ELTERN-Menü stehen, von dem aus die Action gestartet wurde. Ein
    "menu:back"-Klick (history-Pop relativ zu diesem unveränderten
    current_menu) würde deshalb eine Ebene zu weit zurückspringen (z. B.
    von "Diese Woche" direkt zu "Statistiken" statt zu "Rückblicke").
    Der literale `menu:<parent.id>`-Callback (bereits existierendes,
    unverändertes Format aus MenuItem.__post_init__) referenziert
    stattdessen exakt den unmittelbaren Parent - kein neuer
    Callback-Präfix, keine zweite Back-Navigation.

    Level 1 (falls vorhanden): "⬅️ <Parent-Titel>" - eigene Zeile.
    Level 2: Grandparent (nur wenn dieser nicht bereits "main" ist, um
    keinen redundanten Button neben "🏠 Hauptmenü" zu erzeugen) + "🏠
    Hauptmenü" in derselben Zeile. Ist `menu_item` bereits direktes Kind
    von "main" (kein sinnvoller Zwischen-Parent), nur ein einzelner
    "🏠 Hauptmenü"-Button."""
    parent = menu_item.parent
    if not parent or parent.id == "main":
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main")]]
        )

    rows = [
        [InlineKeyboardButton(f"⬅️ {parent.title}", callback_data=f"menu:{parent.id}")]
    ]

    grandparent = parent.parent
    second_row = []
    if grandparent and grandparent.id != "main":
        second_row.append(
            InlineKeyboardButton(
                f"{grandparent.emoji} {grandparent.title}",
                callback_data=f"menu:{grandparent.id}",
            )
        )
    second_row.append(InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:main"))
    rows.append(second_row)

    return InlineKeyboardMarkup(rows)


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
    header_text: Optional[str] = None,
) -> None:
    """Zeigt Menü an oder aktualisiert es. `header_text` (optional): wird,
    falls gesetzt, vor den eigentlichen Menütext gestellt (siehe
    Moduldocstring) - Keyboard/Navigation/Session-Verhalten bleiben
    unverändert."""
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
    if header_text:
        text = f"{header_text}\n\n{text}"
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
