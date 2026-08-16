from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from typing import List, Tuple

from services.commands_services import COMMAND_CATEGORIES, COMMAND_DESCRIPTIONS
from emoji import EMOJI
from logger import log_button_debug, log_button_warning, log_button_error


def truncate_callback_data(data: str, max_bytes: int = 60) -> str:
    encoded = data.encode("utf-8")
    while len(encoded) > max_bytes and len(data) > 0:
        data = data[:-1]
        encoded = data.encode("utf-8")
    return data


def create_navigation_buttons() -> List[List[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(
                f"{EMOJI['back_arrow']} Zurück zu den Hauptkategorien",
                callback_data="show_categories",
            ),
            InlineKeyboardButton(
                f"{EMOJI['question']} Hilfe", callback_data="show_help"
            ),
        ]
    ]


async def ensure_message_with_buttons(
    update: Update, text: str, reply_markup: InlineKeyboardMarkup
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    try:
        await query.edit_message_text(
            text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    except Exception:
        try:
            await query.message.reply_text(
                text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log_button_error(
                f"Fehler beim Senden einer neuen Nachricht: {e}",
                context="ButtonHandler",
                exc_info=True,
            )


def generate_category_command_buttons(
    selected_category_key: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    buttons = []
    message_parts = []
    current_content = COMMAND_CATEGORIES.get(selected_category_key)
    parent_category = None

    if not current_content:
        for parent, subcats in COMMAND_CATEGORIES.items():
            if isinstance(subcats, dict) and selected_category_key in subcats:
                current_content = subcats[selected_category_key]
                parent_category = parent
                break

    if not current_content:
        return (
            f"{EMOJI['error']} Kategorie nicht gefunden.",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🏠 Hauptmenü", callback_data="show_categories"
                        )
                    ]
                ]
            ),
        )

    emoji = EMOJI.get(selected_category_key.lower().replace(" ", "_"), "")
    desc = COMMAND_DESCRIPTIONS.get(selected_category_key, "")
    message_parts.append(f"<b>{emoji} {selected_category_key}</b>")
    if desc:
        message_parts.append(f"\n\n{desc}\n")

    if isinstance(current_content, dict):
        message_parts.append("\n<b>Wähle eine Option:</b>\n")
        for sub_name, sub_content in current_content.items():
            sub_emoji = EMOJI.get(sub_name.lower().replace(" ", "_"), "")
            sub_desc = COMMAND_DESCRIPTIONS.get(sub_name, "")
            message_parts.append(f"\n<b>{sub_emoji} {sub_name}</b>")
            if sub_desc:
                message_parts.append(f" {sub_desc}")
            message_parts.append("\n")
            if isinstance(sub_content, dict):
                for sub_sub_name in sub_content:
                    sub_sub_emoji = EMOJI.get(
                        sub_sub_name.lower().replace(" ", "_"), ""
                    )
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                f"{sub_sub_name} {sub_sub_emoji}",
                                callback_data=truncate_callback_data(
                                    f"show_category:{sub_sub_name}"
                                ),
                            )
                        ]
                    )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f"{sub_name} {sub_emoji}",
                            callback_data=truncate_callback_data(
                                f"show_category:{sub_name}"
                            ),
                        )
                    ]
                )
    elif isinstance(current_content, list):
        message_parts.append("<b>Verfügbare Befehle:</b>\n")
        for cmd in current_content:
            for key in COMMAND_DESCRIPTIONS:
                if key.endswith(f" {cmd}") or key == cmd:
                    label = key
                    desc = COMMAND_DESCRIPTIONS.get(key, "")
                    message_parts.append(f"\n<b>{label}</b> - {desc}\n")
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                label,
                                callback_data=truncate_callback_data(
                                    f"execute_command:{cmd}"
                                ),
                            )
                        ]
                    )
                    break

    nav_buttons = []
    if parent_category:
        nav_buttons.append(
            InlineKeyboardButton(
                f"⬅️ Zurück zu {parent_category}",
                callback_data=truncate_callback_data(
                    f"show_category:{parent_category}"
                ),
            )
        )
    nav_buttons.append(
        InlineKeyboardButton("🏠 Hauptmenü", callback_data="show_categories")
    )
    buttons.append(nav_buttons)
    buttons.extend(create_navigation_buttons())
    return ("".join(message_parts), InlineKeyboardMarkup(buttons))
