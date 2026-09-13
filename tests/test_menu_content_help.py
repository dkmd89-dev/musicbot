# tests/test_menu_content_help.py
# -*- coding: utf-8 -*-
"""
Tests fuer handlers/menu/content/help.py (bisher 0 dedizierte Tests).

Telegram Start/Help/Menu UX Finalization v2: /help zeigte bisher pro
Feature zusaetzlich `feature["commands"]` an (z. B. "/download",
"/stats", "/month", "/year", "/navidrome", "/search", "/admin",
"/users", "/tests") - keiner dieser Werte war je als echter
Telegram-CommandHandler registriert (siehe
handlers/menu/content/user_context.py-Docstring; einzige real
registrierte Commands: /start, /menu, /help, siehe
RichMenuHandler.get_telegram_handlers()). Dieser Test stellt sicher,
dass keiner dieser erfundenen Befehle mehr im /help-Text auftaucht.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.content import help as help_content
from handlers.menu.content import messages

_INVENTED_COMMANDS = (
    "/download",
    "/stats",
    "/month",
    "/year",
    "/navidrome",
    "/search",
    "/admin",
    "/users",
    "/tests",
)


def make_update():
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = 111
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    return Mock()


async def _run_send_help_message(role="user"):
    update = make_update()
    with patch(
        "handlers.menu.content.help.user_context.get_user_role",
        return_value=role,
    ):
        await help_content.send_help_message(
            update, make_context(), Mock(), Mock(), Mock(), None, Mock()
        )
    return update.message.reply_text.call_args.args[0]


class TestHelpMessageHasNoInventedCommands:
    def test_user_help_contains_no_invented_feature_commands(self):
        text = asyncio.run(_run_send_help_message(role="user"))

        for fake_cmd in _INVENTED_COMMANDS:
            assert fake_cmd not in text, f"Erfundener Befehl {fake_cmd} im /help-Text"

    def test_admin_help_contains_no_invented_feature_commands(self):
        text = asyncio.run(_run_send_help_message(role="admin"))

        for fake_cmd in _INVENTED_COMMANDS:
            assert fake_cmd not in text, f"Erfundener Befehl {fake_cmd} im /help-Text"

    def test_help_lists_only_real_general_commands(self):
        text = asyncio.run(_run_send_help_message(role="user"))

        for real_cmd in ("/start", "/menu", "/help", "/cancel"):
            assert real_cmd in text


class TestHelpMessageGrouping:
    def test_shows_download_stats_navidrome_for_plain_user(self):
        text = asyncio.run(_run_send_help_message(role="user"))

        assert "Downloads" in text
        assert "Statistiken" in text
        assert "Navidrome" in text
        assert "Administration" not in text

    def test_admin_role_also_sees_admin_and_tests_group(self):
        text = asyncio.run(_run_send_help_message(role="admin"))

        assert "Administration" in text
        assert "Test-System" in text


class TestNavidromeHelpTextHasNoInventedSearchCommand:
    def test_get_navidrome_help_does_not_mention_search_command(self):
        text = help_content.get_navidrome_help()

        assert "/search" not in text
        assert "/menu" in text

    def test_navidrome_help_matches_messages_constant(self):
        assert help_content.get_navidrome_help() == messages.HELP_NAVIDROME


class TestHelpCallbackAdminGating:
    def test_admin_topic_hidden_for_plain_user(self):
        update = make_update()
        update.callback_query = AsyncMock()
        update.callback_query.data = "help:admin"

        with patch(
            "handlers.menu.content.help.user_context.get_user_role",
            return_value="user",
        ):
            asyncio.run(
                help_content.send_help_callback_response(
                    update, make_context(), Mock(), Mock(), Mock(), Mock()
                )
            )

        text = update.callback_query.edit_message_text.call_args.args[0]
        # Kein Admin-Text - faellt auf die Hauptuebersicht zurueck.
        assert text == messages.HELP_MAIN_MENU_TEXT

    def test_admin_topic_visible_for_admin(self):
        update = make_update()
        update.callback_query = AsyncMock()
        update.callback_query.data = "help:admin"

        with patch(
            "handlers.menu.content.help.user_context.get_user_role",
            return_value="admin",
        ):
            asyncio.run(
                help_content.send_help_callback_response(
                    update, make_context(), Mock(), Mock(), Mock(), Mock()
                )
            )

        text = update.callback_query.edit_message_text.call_args.args[0]
        assert text == messages.HELP_ADMIN
