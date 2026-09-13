# handlers/menu/content/greeting.py
# -*- coding: utf-8 -*-
"""
/start-Begrüßung: kurzer, personalisierter Willkommenstext gefolgt vom
zentralen Hauptmenü - beides in EINER Telegram-Nachricht.

ARCH-025 (Command/Help Decomposition): 1:1 aus
handlers/menu/rich_menu_handler.py::handle_start_command() verschoben.
RichMenuHandler.handle_start_command() bleibt ein dünner Delegator
(Maintenance-Gate + Activity-Tracking + Aufruf hierher) - siehe
docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md.

Telegram Start/Help/Menu UX Finalization v2: /start zeigte bisher eine
eigene, vollständige Feature-Liste mit eigener Tastatur - eine zweite,
parallele Menüdarstellung mit eigener Access-Filterung über
user_context.FEATURES/get_available_features(), inhaltlich redundant
zum zentralen Hauptmenü (gleiche Funktionen, gleiche Buttons). Das
widersprach der Architekturregel "eine zentrale Main-Menu-Definition,
eine zentrale Navigation" (siehe docs/MusicBot_TELEGRAM_MENU_SYSTEM.md).

send_start_message() erzeugt jetzt nur noch einen kurzen
Begrüßungstext (Name + optionale Rollenzeile) und übergibt ihn als
`header_text` an RichMenuSystem.show_menu(update, context, "main") -
identisches Hauptmenü, identische Tastatur, identische
AccessLevel-Filterung wie /menu (handlers/menu/models.py::AccessLevel /
handlers/menu/permissions.py). Keine eigene Feature-Liste/Tastatur mehr
in dieser Datei - `menu_system` wird dafür explizit als zusätzliche
Abhängigkeit entgegengenommen (RichMenuHandler hält bereits eine
Instanz, siehe rich_menu_handler.py::handle_start_command()).

`user_role` (via content.user_context.get_user_role()) dient hier
ausschließlich der kurzen, dezenten Begrüßungszeile - NICHT der
Menü-/Button-Sichtbarkeit (die bleibt vollständig durch die zentrale
AccessLevel-Architektur bestimmt, siehe ARCH-021/P-3-Entscheidung in
user_context.py). Keine Berechtigungslogik in dieser Content-Datei.
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.content import messages
from handlers.menu.content import user_context

_ROLE_EMOJI = {"moderator": "🛡️", "admin": "⚙️", "owner": "👑"}
_ROLE_EMOJI_DEFAULT = "👤"

# Legacy-Markdown-Sonderzeichen (parse_mode="Markdown"), die in einem
# dynamischen Wert (hier: Telegram-Username/Vorname) escaped werden
# müssen, bevor er in den fett formatierten Begrüßungstext eingesetzt
# wird - sonst droht bei z. B. "john_doe" ein
# "BadRequest: Can't parse entities" (dieselbe Fehlerklasse wie
# docs/FINDINGS_INDEX.md, dl:-Menüs mit dynamischen Inhalten).
_MARKDOWN_V1_SPECIAL_CHARS = ("_", "*", "`", "[")


def _escape_markdown(value: str) -> str:
    text = str(value)
    for char in _MARKDOWN_V1_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


async def send_start_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config,
    user_mgmt_handler,
    user_data_file,
    error_handler,
    logger,
    menu_system,
) -> None:
    """Erweiterter /start Command Handler: kurze Begrüßung + zentrales
    Hauptmenü in einer Nachricht (siehe Moduldocstring)."""
    try:
        user = update.effective_user
        user_id = user.id
        username = _escape_markdown(user.username or user.first_name)

        logger.info(f"🚀 /start von User {user_id} ({username})")

        is_new = user_context.is_new_user(user_id, user_data_file, logger, user_mgmt_handler)
        user_role = user_context.get_user_role(
            user_id, config, user_data_file, logger, user_mgmt_handler
        )

        greeting_parts = [
            (
                messages.GREETING_WELCOME_NEW.format(username=username)
                if is_new
                else messages.GREETING_WELCOME_BACK.format(username=username)
            ),
            messages.GREETING_TAGLINE,
        ]
        if user_role != "user":
            role_emoji = _ROLE_EMOJI.get(user_role, _ROLE_EMOJI_DEFAULT)
            greeting_parts.append(
                messages.GREETING_ROLE_LINE.format(
                    role_emoji=role_emoji, role_title=user_role.capitalize()
                )
            )
        greeting_parts.append(messages.GREETING_DIVIDER)

        welcome_text = "\n\n".join(greeting_parts)

        await menu_system.show_menu(update, context, "main", header_text=welcome_text)
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
