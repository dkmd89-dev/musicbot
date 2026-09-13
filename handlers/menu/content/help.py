# handlers/menu/content/help.py
# -*- coding: utf-8 -*-
"""
/help-Kommando + Help-Callback ("^help:"): Themenübersicht und
statische Hilfe-Texte je Feature-Bereich.

ARCH-025 (Command/Help Decomposition): 1:1 aus
handlers/menu/rich_menu_handler.py::handle_help()/handle_help_callback()/
_get_download_help()/_get_stats_help()/_get_navidrome_help()/
_get_admin_help() verschoben. RichMenuHandler.handle_help()/
handle_help_callback() bleiben dünne Delegatoren (Maintenance-Gate +
Activity-Tracking + Aufruf hierher) - siehe
docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md.

Charakterisierte Asymmetrie (unverändert übernommen, keine
Verhaltensänderung): send_help_message()'s except-Zweig ruft bei
vorhandenem error_handler dessen handle_command_error() auf,
send_help_callback_response()'s except-Zweig loggt nur - dieselbe
Asymmetrie wie im ursprünglichen handle_help()/handle_help_callback().

Content-Separation-Closure: get_download_help()/get_stats_help()/
get_navidrome_help()/get_admin_help() sind seither dünne Wrapper um
die in handlers/menu/content/messages.py zentralisierten Texte -
diese Datei bleibt für Themenauswahl/Keyboard-Aufbau/Telegram-Versand
zuständig, siehe
docs/MusicBot_ARCH-025_Menu_Command_Help_Content_Closure.md.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.menu.content import messages
from handlers.menu.content import user_context


def get_download_help() -> str:
    """Hilfe für Download-Funktionen (YouTube)."""
    return messages.HELP_DOWNLOAD


def get_stats_help() -> str:
    return messages.HELP_STATS


def get_navidrome_help() -> str:
    return messages.HELP_NAVIDROME


def get_admin_help() -> str:
    return messages.HELP_ADMIN


async def send_help_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    user_mgmt_handler,
    user_data_file,
    error_handler,
    logger,
) -> None:
    """Erweiterter /help Command Handler."""
    try:
        user_id = update.effective_user.id
        user_role = user_context.get_user_role(
            user_id, config, user_data_file, logger, user_mgmt_handler
        )
        available_features = user_context.get_available_features(user_role)

        logger.info(f"❓ /help von User {user_id}")

        help_parts = [
            messages.HELP_INTRO_TITLE,
            messages.HELP_INTRO_SUBTITLE,
        ]
        for feature_id, feature in available_features.items():
            commands = feature.get("commands", [])
            help_parts.append(f"{feature['emoji']} **{feature['title']}**")
            help_parts.append(feature["description"])
            if commands:
                help_parts.append(f"_Befehle: {', '.join(commands)}_\n")
            else:
                help_parts.append("")

        help_parts.extend(
            [
                messages.HELP_GENERAL_COMMANDS_HEADER,
                messages.HELP_CMD_START,
                messages.HELP_CMD_MENU,
                messages.HELP_CMD_HELP,
                messages.HELP_CMD_CANCEL,
                messages.HELP_SUPPORT_HEADER,
                messages.HELP_SUPPORT_TEXT,
            ]
        )

        keyboard = [
            [InlineKeyboardButton(messages.BTN_MAIN_MENU, callback_data="menu:main")],
            [
                InlineKeyboardButton(messages.BTN_HELP_DOWNLOAD, callback_data="help:download"),
                InlineKeyboardButton(messages.BTN_HELP_STATS, callback_data="help:stats"),
            ],
            [InlineKeyboardButton(messages.BTN_HELP_NAVIDROME, callback_data="help:navidrome")],
        ]
        if user_role in ["admin", "owner"]:
            keyboard.append(
                [InlineKeyboardButton(messages.BTN_HELP_ADMIN, callback_data="help:admin")]
            )
        keyboard.append(
            [InlineKeyboardButton(messages.BTN_CLOSE, callback_data="menu:close")]
        )

        await update.message.reply_text(
            "\n".join(help_parts),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"❌ Fehler in handle_help: {e}", exc_info=True)
        if error_handler:
            await error_handler.handle_command_error(
                update, context, "help", e
            )


async def send_help_callback_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    user_mgmt_handler,
    user_data_file,
    logger,
) -> None:
    """Callback-Handler für spezifische Hilfe-Themen (pattern='^help:')."""
    try:
        query = update.callback_query
        topic = query.data.split(":", 1)[-1]
        await query.answer()

        user_id = update.effective_user.id
        user_role = user_context.get_user_role(
            user_id, config, user_data_file, logger, user_mgmt_handler
        )

        help_texts = {
            "download": get_download_help(),
            "stats": get_stats_help(),
            "navidrome": get_navidrome_help(),
            "admin": (
                get_admin_help() if user_role in ["admin", "owner"] else None
            ),
        }

        help_text = help_texts.get(topic) if topic != "main" else None

        if topic == "main" or not help_text:
            main_text = messages.HELP_MAIN_MENU_TEXT
            keyboard = [
                [InlineKeyboardButton(messages.BTN_MAIN_MENU, callback_data="menu:main")],
                [
                    InlineKeyboardButton(
                        messages.BTN_HELP_DOWNLOAD, callback_data="help:download"
                    ),
                    InlineKeyboardButton(
                        messages.BTN_HELP_STATS, callback_data="help:stats"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        messages.BTN_HELP_NAVIDROME, callback_data="help:navidrome"
                    )
                ],
            ]
            if user_role in ["admin", "owner"]:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            messages.BTN_HELP_ADMIN, callback_data="help:admin"
                        )
                    ]
                )
            keyboard.append(
                [InlineKeyboardButton(messages.BTN_CLOSE, callback_data="menu:close")]
            )
            await query.edit_message_text(
                main_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Zurück zur Hilfe", callback_data="help:main"
                    )
                ],
                [InlineKeyboardButton(messages.BTN_MAIN_MENU, callback_data="menu:main")],
                [InlineKeyboardButton(messages.BTN_CLOSE, callback_data="menu:close")],
            ]
        )
        await query.edit_message_text(
            help_text, reply_markup=keyboard, parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"❌ Fehler in handle_help_callback: {e}", exc_info=True)
