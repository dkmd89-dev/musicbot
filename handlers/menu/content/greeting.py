# handlers/menu/content/greeting.py
# -*- coding: utf-8 -*-
"""
/start-Begrüßung: personalisierte Grußnachricht + Feature-Übersicht.

ARCH-025 (Command/Help Decomposition): 1:1 aus
handlers/menu/rich_menu_handler.py::handle_start_command() verschoben.
RichMenuHandler.handle_start_command() bleibt ein dünner Delegator
(Maintenance-Gate + Activity-Tracking + Aufruf hierher) - siehe
docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md.

Content-Separation-Closure: die statischen Begrüßungstexte/Button-
Labels wurden nach handlers/menu/content/messages.py ausgelagert -
diese Datei bleibt für die Orchestrierung zuständig (Nutzerkontext
laden, Neuling-/Rollen-/Feature-Ermittlung, dynamische Werte in die
Templates einsetzen, Nachricht senden), siehe
docs/MusicBot_ARCH-025_Menu_Command_Help_Content_Closure.md.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.menu.content import messages
from handlers.menu.content import user_context

_ROLE_EMOJI = {"moderator": "🛡️", "admin": "⚙️", "owner": "👑"}
_ROLE_EMOJI_DEFAULT = "👤"


async def send_start_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    user_mgmt_handler,
    user_data_file,
    error_handler,
    logger,
) -> None:
    """Erweiterter /start Command Handler mit personalisierter Begrüßung."""
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name

        logger.info(f"🚀 /start von User {user_id} ({username})")

        is_new = user_context.is_new_user(user_id, user_data_file, logger, user_mgmt_handler)
        user_role = user_context.get_user_role(
            user_id, config, user_data_file, logger, user_mgmt_handler
        )
        available_features = user_context.get_available_features(user_role)

        greeting_parts = []
        if is_new:
            greeting_parts.extend(
                [
                    messages.GREETING_WELCOME_NEW.format(username=username),
                    messages.GREETING_WELCOME_NEW_LINE_2,
                    messages.GREETING_WELCOME_NEW_LINE_3,
                ]
            )
        else:
            greeting_parts.extend(
                [
                    messages.GREETING_WELCOME_BACK.format(username=username),
                    messages.GREETING_WELCOME_BACK_LINE_2,
                ]
            )

        if user_role != "user":
            role_emoji = _ROLE_EMOJI.get(user_role, _ROLE_EMOJI_DEFAULT)
            greeting_parts.append(
                messages.GREETING_ROLE_LINE.format(
                    role_emoji=role_emoji, role_title=user_role.capitalize()
                )
            )

        greeting_parts.append(messages.GREETING_FEATURES_HEADER)
        for feature_id, feature in available_features.items():
            greeting_parts.append(f"{feature['emoji']} **{feature['title']}**")
            greeting_parts.append(f"   _{feature['description']}_\n")

        greeting_parts.extend(
            [
                messages.GREETING_QUICKSTART_HEADER,
                messages.GREETING_QUICKSTART_MENU,
                messages.GREETING_QUICKSTART_HELP,
            ]
        )

        if "download" in available_features:
            greeting_parts.append(messages.GREETING_HINT_DOWNLOAD)
        if "navidrome" in available_features:
            greeting_parts.append(messages.GREETING_HINT_SEARCH)

        greeting = "\n".join(greeting_parts)

        keyboard = [
            [InlineKeyboardButton(messages.BTN_MAIN_MENU, callback_data="menu:main")]
        ]
        feature_buttons = [
            InlineKeyboardButton(
                f"{fdata['emoji']} {fdata['title']}",
                callback_data=f"menu:{fdata.get('menu_id', fid)}",
            )
            for fid, fdata in available_features.items()
        ]
        for i in range(0, len(feature_buttons), 2):
            keyboard.append(feature_buttons[i : i + 2])
        keyboard.append(
            [InlineKeyboardButton("❓ Hilfe", callback_data="help:main")]
        )

        await update.message.reply_text(
            greeting,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        logger.info(f"✅ Start-Nachricht gesendet an {user_id}")

    except Exception as e:
        logger.error(f"❌ Fehler in handle_start_command: {e}", exc_info=True)
        if error_handler:
            await error_handler.handle_command_error(
                update, context, "start", e
            )
        else:
            try:
                await update.message.reply_text(messages.ERROR_GENERIC)
            except Exception:
                pass
