# handlers/buttons/ button_router.py

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from logger import (
    log_button_info,
    log_button_warning,
    log_button_error,
    log_button_debug,
)
from helfer.markdown_helfer import escape_md_v2
from services.commands_services import COMMAND_CATEGORIES, COMMAND_DESCRIPTIONS
from emoji import EMOJI

from .navigation import (
    generate_category_command_buttons,
    ensure_message_with_buttons,
    create_navigation_buttons,
)
from .command_dispatcher import handle_execute_command
from handlers.logger_handler import handle_logger_callbacks
from handlers.navidrome_handler import NavidromeHandler
from config import Config  # NEU
from handlers.telegram_handler import (
    send_script,
)  # NEU - Diese Zeile importiert send_script direkt

# Instanz des NavidromeHandlers erstellen
navidrome_handler = NavidromeHandler()


# Eine Liste von Prefixen, die vom Logger-Callback-Handler verarbeitet werden
LOGGER_CALLBACK_PREFIXES = (
    "show_viewlogs_menu",
    "show_clearlogs_menu",
    "logger_select_level_",
    "logger_select_view_",
    "logger_select_clear_",
    "set_level_",
    "confirm_clear_",
    "cancel_action",
    "show_loglevels",
    "show_main_logger_menu",
)


async def handle_button_click(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Zentraler Handler, der alle Button-Klicks verarbeitet."""
    query = update.callback_query
    if not query:
        log_button_warning(
            "Keine CallbackQuery im Update-Objekt gefunden.", context="ButtonHandler"
        )
        return
    await query.answer()
    callback_data = query.data
    log_button_info(f"Button-Klick empfangen: {callback_data}", context="ButtonHandler")

    try:
        if not callback_data:
            log_button_warning("Callback-Daten sind None.", context="ButtonHandler")
            await query.message.reply_text(
                f"{EMOJI['error']} Es ist ein Problem aufgetreten. Bitte versuche es erneut."
            )
            return

        await context.bot.send_chat_action(
            chat_id=query.message.chat.id, action="typing"
        )

        # --- Zentrales Logger-Callback-Routing ---
        if any(callback_data.startswith(prefix) for prefix in LOGGER_CALLBACK_PREFIXES):
            log_button_debug(
                f"Logger Callback wird an handle_logger_callbacks weitergeleitet: {callback_data}",
                context="ButtonHandler",
            )
            await handle_logger_callbacks(update, context)

        elif callback_data.startswith("view_script:"):
            script_name = callback_data.split(":", 1)[1]
            full_path = Config.ESCAPE_DIR / script_name
            log_button_info(
                f"Anfrage zum Anzeigen von Skript: {full_path}", context="ButtonHandler"
            )
            # Rufe die send_script Funktion aus dem telegram_handler auf
            await send_script(
                update, context, str(full_path)
            )  # GEÄNDERT: Direkter Aufruf von send_script

        # --- Navigation: Kategorien und Befehle ---
        elif callback_data.startswith("show_category:"):
            category_name = callback_data.split(":", 1)[1]
            message_text, reply_markup = generate_category_command_buttons(
                category_name
            )
            await ensure_message_with_buttons(update, message_text, reply_markup)

        elif callback_data.startswith("execute_command:"):
            cmd_name = callback_data.split(":", 1)[1]
            log_button_info(
                f"Button 'execute_command:{cmd_name}' geklickt.",
                context="ButtonHandler",
            )
            await handle_execute_command(update, context, cmd_name)

        # Handler für paginierte Navidrome-Listen (Künstler, Genres, Indexes)
        elif (
            callback_data.startswith("artists:")
            or callback_data.startswith("genres:")
            or callback_data.startswith("albumlist:")
        ):
            parts = callback_data.split(":")
            command_type = parts[0]  # z.B. 'artists', 'genres', 'albumlist'
            page = (
                int(parts[1]) if len(parts) > 1 else 1
            )  # Standardseite 1, wenn nicht angegeben

            # Füge die Seitenzahl zu context.args hinzu, damit der Handler sie verarbeiten kann
            context.args = [str(page)]

            # Delegiere an die entsprechende NavidromeHandler-Methode
            if command_type == "artists":
                await navidrome_handler.handle_artists(update, context)
            elif command_type == "genres":
                await navidrome_handler.handle_genres(update, context)
            elif command_type == "albumlist":
                # Hier muss zwischen verschiedenen Albumlisten-Typen unterschieden werden
                # Aktuell ruft handle_albumlist immer "newest" ab.
                # Wenn du weitere Typen (z.B. "frequent", "random") über Buttons anbieten willst,
                # müsste handle_albumlist angepasst werden, um einen Typ-Parameter zu akzeptieren.
                await navidrome_handler.handle_albumlist(update, context)
            # 'indexes' hat keine Paginierung in deinem Beispiel, falls doch, hier hinzufügen
            # elif command_type == 'indexes':
            #     await navidrome_handler.handle_indexes(update, context)
            else:
                log_button_warning(
                    f"Unbekannter Paginierungs-Befehl: {callback_data}",
                    context="ButtonHandler",
                )
                await query.message.reply_text(
                    f"{EMOJI['cross_mark']} Unbekannte Paginierungs-Option. Bitte wähle eine Option aus dem Menü."
                )

        # Entferne den spezifischen Handler für albumlist_ da er oben generischer behandelt wird
        # elif callback_data.startswith('albumlist_'):
        #     type_param = callback_data.split('_', 1)[1]
        #     await navidrome_handler.handle_albumlist_criteria(update, context, type_param) # Diese Methode existiert noch nicht

        elif callback_data == "show_categories":
            message_parts = [f"*{escape_md_v2('Willkommen! Wähle eine Kategorie:')}*"]
            buttons = []

            for (
                main_category_name,
                sub_categories_or_commands,
            ) in COMMAND_CATEGORIES.items():
                # Ermittle das Hauptkategorie-Emoji
                main_cat_emoji_key = (
                    main_category_name.split(" ")[1].strip()
                    if " " in main_category_name
                    else main_category_name
                )
                # Mapping für bekannte Hauptkategorien, falls nötig
                emoji_map = {
                    "Navidrome": EMOJI.get("navidrome", "📚"),
                    "YouTube": EMOJI.get(
                        "youtube", "▶️"
                    ),  # Angenommen, du hast ein YouTube-Emoji
                    "System": EMOJI.get("wrench", "⚙️"),
                }
                main_emoji = emoji_map.get(
                    main_cat_emoji_key, EMOJI.get("folder", "📦")
                )  # Standard-Emoji, falls nicht gefunden

                # Erstelle den Text für die Hauptkategorie
                description_parts = []
                if isinstance(
                    sub_categories_or_commands, dict
                ):  # Es gibt Unterkategorien
                    for sub_cat_name, commands in sub_categories_or_commands.items():
                        # Extrahiere Emoji aus dem beschreibenden String, z.B. "📂 Medien" -> "📂"
                        sub_cat_display_name = (
                            sub_cat_name.split(" ", 1)[1]
                            if " " in sub_cat_name
                            else sub_cat_name
                        )
                        sub_cat_emoji = (
                            sub_cat_name.split(" ")[0]
                            if " " in sub_cat_name
                            else EMOJI.get("folder", "📄")
                        )  # Standard
                        description_parts.append(
                            f"{sub_cat_emoji} {escape_md_v2(sub_cat_display_name)}"
                        )
                else:  # Es sind direkte Befehle
                    # Dies sollte bei der aktuellen Struktur nicht vorkommen, da alle Hauptkategorien Dictionaries sind
                    # Aber als Fallback, falls COMMAND_CATEGORIES geändert wird
                    direct_commands_descriptions = [
                        COMMAND_DESCRIPTIONS.get(
                            f"{EMOJI.get('default_emoji', '')} {cmd}", cmd
                        )
                        for cmd in sub_categories_or_commands
                    ]
                    description_parts.append(
                        escape_md_v2(", ".join(direct_commands_descriptions))
                    )

                # Füge die Hauptkategorie zur Nachricht hinzu
                message_parts.append(
                    f"\n{main_emoji} *{escape_md_v2(main_category_name.split(' ', 1)[1] if ' ' in main_category_name else main_category_name)}*: {escape_md_v2(', '.join(description_parts))}"
                )

                # Füge den Button für die Hauptkategorie hinzu
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f"{main_category_name}",
                            callback_data=f"show_category:{main_category_name}",
                        )
                    ]
                )

            buttons.extend(create_navigation_buttons())
            reply_markup = InlineKeyboardMarkup(buttons)
            await ensure_message_with_buttons(
                update, "\n".join(message_parts), reply_markup
            )

        elif callback_data == "show_help":
            from handlers.help_handler import handle_help

            await handle_help(update, context)

        else:
            log_button_warning(
                f"Unbekannter Callback: {callback_data}", context="ButtonHandler"
            )
            await query.message.reply_text(
                f"{EMOJI['cross_mark']} Unbekannte Option. Bitte wähle eine Option aus dem Menü."
            )

    except Exception as e:
        log_button_error(
            f"Exception in handle_button_click for callback '{callback_data}': {e}",
            context="ButtonHandler",
            exc_info=True,
        )
        escaped_error = escape_md_v2(str(e))
        await query.message.reply_text(
            f"{EMOJI['error']} Unerwarteter Fehler: `{escaped_error}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
