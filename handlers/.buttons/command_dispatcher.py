# command_dispatcher.py

import unittest
import io
import importlib
import os
import traceback
import asyncio
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import html

# Konfiguration und Helfer importieren
from config import Config
from logger import log_button_warning, log_button_error
from helfer.markdown_helfer import escape_md_v2
from emoji import EMOJI

# Handler-Klassen und -Funktionen importieren
from handlers.start_handler import handle_start

# from handlers.stop_handler import handle_stop_command, handle_restart_command
from handlers.status_handler import status, quick_status, handle_detailed_status_command
from handlers.logger_handler import (
    handle_set_loglevel,
    handle_logger_status_summary,
    handle_view_logs,
    handle_clear_logs,
    show_main_logger_menu,
    handle_bulk_logger_operations,
)

from handlers.navidrome_handler import NavidromeHandler
from handlers.statistik_handler import StatistikHandler

# Instanzen der Handler erstellen
navidrome_handler = NavidromeHandler()
statistik_handler = StatistikHandler()


async def handle_view_scripts_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    Durchsucht das ESCAPE_DIR nach .py- und .txt-Dateien und zeigt sie als interaktive Buttons an.
    """
    msg = update.effective_message
    escape_dir = Config.ESCAPE_DIR
    escaped_dir = escape_md_v2(str(escape_dir))

    if not escape_dir.exists() or not escape_dir.is_dir():
        await msg.reply_text(
            f"{escape_md_v2(EMOJI['error'])} Das Skript\\-Verzeichnis `{escaped_dir}` wurde nicht gefunden\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        allowed_extensions = {".py", ".txt"}
        scripts = sorted(
            [
                f
                for f in escape_dir.iterdir()
                if f.is_file() and f.suffix in allowed_extensions
            ]
        )

        if not scripts:
            await msg.reply_text(
                f"{escape_md_v2(EMOJI['info'])} Keine Skripte im Verzeichnis `{escaped_dir}` gefunden\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        buttons = []
        for script_path in scripts:
            script_name = script_path.name
            safe_callback = re.sub(r"[^a-zA-Z0-9_:.]", "_", script_name)
            callback_data = f"view_script:{safe_callback}"
            buttons.append(
                [InlineKeyboardButton(script_name, callback_data=callback_data)]
            )

        back_text = f"{EMOJI['back']} Zurück zum Hauptmenü"
        buttons.append(
            [InlineKeyboardButton(back_text, callback_data="show_categories")]
        )

        reply_markup = InlineKeyboardMarkup(buttons)
        await msg.reply_text(
            escape_md_v2("Bitte wähle ein Skript zum Anzeigen aus:"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    except Exception as e:
        error_msg = escape_md_v2(str(e))
        log_button_error(
            f"Fehler beim Lesen des Skript-Verzeichnisses: {error_msg}", exc_info=True
        )
        await msg.reply_text(
            f"{escape_md_v2(EMOJI['error'])} Ein Fehler ist aufgetreten: `{error_msg}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def handle_view_script_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str
):
    """
    Zeigt den Inhalt einer escaped MarkdownV2-Datei blockweise an.
    """
    message = update.callback_query.message
    file_path = Config.ESCAPE_DIR / filename

    if not file_path.exists():
        await message.reply_text(
            f"{escape_md_v2(EMOJI['error'])} Datei `{escape_md_v2(filename)}` nicht gefunden.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        content = file_path.read_text(encoding="utf-8")
        chunks = [content[i : i + 3900] for i in range(0, len(content), 3900)]
        for chunk in chunks:
            await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        await message.reply_text(
            f"{escape_md_v2(EMOJI['error'])} Fehler beim Senden:\n`{escape_md_v2(str(e))}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def handle_execute_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cmd_name: str
):
    """
    Leitet Befehle, die von Buttons oder direkten Eingaben kommen, an die entsprechenden Handler weiter.
    """
    try:
        msg = update.effective_message

        # --- Navidrome-Befehle (API-Interaktionen) ---
        if cmd_name == "navidrome":
            await navidrome_handler.handle_navidrome_url(update, context)
        elif cmd_name == "scan":
            await navidrome_handler.handle_navidrome_status(update, context)
        elif cmd_name == "test_api":
            await navidrome_handler.test_navidrome_api(update, context)
        elif cmd_name == "artists":
            await navidrome_handler.handle_artists(update, context)
        elif cmd_name == "genres":
            await navidrome_handler.handle_genres(update, context)
        elif cmd_name == "indexes":
            await navidrome_handler.handle_indexes(update, context)
        elif cmd_name == "albumlist":
            await navidrome_handler.handle_albumlist(update, context)
        elif cmd_name == "playing":
            await navidrome_handler.handle_playing(update, context)
        elif cmd_name == "search":
            await navidrome_handler.handle_search_songs(update, context)

        # --- Statistik-Befehle (lokale History-Interaktionen) ---
        elif cmd_name == "topsongs":
            await statistik_handler.handle_top_songs(update, context)
        elif cmd_name == "topsongs7":
            await statistik_handler.handle_top_songs(update, context, period="week")
        elif cmd_name == "topartists":
            await statistik_handler.handle_top_artists(update, context)
        elif cmd_name == "monthreview":
            await statistik_handler.handle_month_review(update, context)
        elif cmd_name == "yearreview":
            await statistik_handler.handle_year_review(update, context)
        elif cmd_name == "lastplayed":
            await statistik_handler.handle_last_played(update, context)

        # --- System-Befehle ---
        elif cmd_name == "status":
            await status(update, context)
        elif cmd_name == "quickstatus":
            await quick_status(update, context)
        elif cmd_name == "detailedstatus":
            await handle_detailed_status_command(update, context)
        elif cmd_name == "view_scripts":
            await handle_view_scripts_command(update, context)
        elif cmd_name == "start":
            await handle_start(update, context)
        elif cmd_name == "stop":
            await handle_stop_command(update, context)
        elif cmd_name == "restart":
            await handle_restart_command(update, context)
        elif cmd_name == "backup":
            await handle_backup(update, context)
        elif cmd_name == "rescan_library":
            await navidrome_handler.handle_rescan_library(update, context)

        # --- Logger-Befehle ---
        elif cmd_name == "logs":
            await show_main_logger_menu(msg)
        elif cmd_name == "loglevels":
            await handle_logger_status_summary(update, context)
        elif cmd_name == "setloglevel":
            await handle_set_loglevel(update, context)
        elif cmd_name == "viewlogs":
            await handle_view_logs(update, context)
        elif cmd_name == "clearlogs":
            await handle_clear_logs(update, context)
        elif cmd_name == "bulklogger":
            await handle_bulk_logger_operations(update, context)

        # --- YouTube Befehle ---
        elif cmd_name == "download":
            escaped_cmd = escape_md_v2(cmd_name)
            await msg.reply_text(
                f"Der '{escaped_cmd}' Befehl wird derzeit nicht unterstützt\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        # --- Hilfe Befehle ---
        elif cmd_name == "help":
            from handlers.help_handler import handle_help

            await handle_help(update, context)

        else:
            log_button_warning(
                f"Unbekannter Befehl: {cmd_name}", context="CommandDispatcher"
            )
            cross_mark = escape_md_v2(EMOJI.get("cross_mark", "❌"))
            escaped_cmd = escape_md_v2(cmd_name)
            await msg.reply_text(
                f"{cross_mark} Befehl `{escaped_cmd}` nicht implementiert\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )

    except Exception as e:
        log_button_error(
            f"Exception in handle_execute_command for '{cmd_name}': {e}", exc_info=True
        )
        escaped_error = escape_md_v2(str(e))
        error_emoji = escape_md_v2(EMOJI.get("error", "❌"))
        await update.effective_message.reply_text(
            f"{error_emoji} Unerwarteter Fehler:\n`{escaped_error}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
