# tests/test_menu_content_greeting.py
# -*- coding: utf-8 -*-
"""
Tests fuer handlers/menu/content/greeting.py::send_start_message()
(bisher 0 dedizierte Tests). Telegram Start/Help/Menu UX Finalization
v2: /start liefert nur noch einen kurzen, personalisierten
Begruessungstext als `header_text` an
RichMenuSystem.show_menu(..., "main") - keine eigene Feature-Liste/
Tastatur mehr (siehe Moduldocstring von greeting.py).

user_context.is_new_user()/get_user_role() werden gemockt (reines
Datei-I/O-Detail, hier irrelevant) - Fokus dieser Tests ist die
Zusammensetzung des Begruessungstexts und die korrekte Delegation an
menu_system.show_menu().
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.menu.content import greeting


def make_update(user_id: int = 111, username: str = "testuser"):
    update = Mock()
    update.effective_user = Mock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.first_name = "Test"
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    return Mock()


async def _run_send_start_message(
    update,
    *,
    is_new=True,
    role="user",
    error_handler=None,
    menu_system=None,
):
    if menu_system is None:
        menu_system = Mock()
        menu_system.show_menu = AsyncMock()
    with patch(
        "handlers.menu.content.greeting.user_context.is_new_user",
        return_value=is_new,
    ), patch(
        "handlers.menu.content.greeting.user_context.get_user_role",
        return_value=role,
    ):
        await greeting.send_start_message(
            update,
            make_context(),
            Mock(),  # config
            Mock(),  # user_mgmt_handler
            Mock(),  # user_data_file
            error_handler,
            Mock(),  # logger
            menu_system,
        )
    return menu_system


class TestSendStartMessageDelegatesToCentralMenu:
    def test_delegates_to_menu_system_show_menu_main(self):
        update = make_update()

        menu_system = asyncio.run(_run_send_start_message(update))

        menu_system.show_menu.assert_awaited_once()
        args, kwargs = menu_system.show_menu.call_args
        assert args[0] is update
        assert args[2] == "main"
        assert "header_text" in kwargs

    def test_no_direct_reply_text_call(self):
        """Keine zweite, parallele Nachricht/Tastatur mehr - die
        Begruessung wird ausschliesslich ueber menu_system.show_menu()
        (header_text) ausgeliefert."""
        update = make_update()

        asyncio.run(_run_send_start_message(update))

        update.message.reply_text.assert_not_called()

    def test_header_text_contains_no_duplicated_feature_list(self):
        """Regressionsschutz: die frueher inline gerenderte, vollstaendige
        Feature-Liste (Duplikat des zentralen Hauptmenues) darf nicht
        wieder auftauchen."""
        update = make_update()

        menu_system = asyncio.run(_run_send_start_message(update))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "Verfügbare Funktionen" not in header_text
        assert "Schnellstart" not in header_text


class TestSendStartMessageContent:
    def test_new_user_gets_new_user_welcome(self):
        update = make_update(username="newuser")

        menu_system = asyncio.run(_run_send_start_message(update, is_new=True))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "Willkommen bei deinem MusicBot, newuser" in header_text

    def test_returning_user_gets_welcome_back(self):
        update = make_update(username="olduser")

        menu_system = asyncio.run(_run_send_start_message(update, is_new=False))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "Willkommen zurück, olduser" in header_text

    def test_plain_user_role_has_no_role_line(self):
        update = make_update()

        menu_system = asyncio.run(_run_send_start_message(update, role="user"))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "Rolle:" not in header_text

    def test_admin_role_gets_dezent_role_line(self):
        update = make_update()

        menu_system = asyncio.run(_run_send_start_message(update, role="admin"))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "⚙️ Rolle: **Admin**" in header_text

    def test_owner_role_gets_own_emoji(self):
        update = make_update()

        menu_system = asyncio.run(_run_send_start_message(update, role="owner"))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "👑 Rolle: **Owner**" in header_text


class TestSendStartMessageMarkdownSafety:
    def test_username_with_underscore_is_escaped(self):
        """Ohne Escaping wuerde Telegrams Legacy-Markdown-Parser ein
        einzelnes '_' als unvollstaendige Kursiv-Formatierung
        interpretieren (BadRequest: Can't parse entities) - siehe
        docs/FINDINGS_INDEX.md fuer dieselbe Fehlerklasse bei dl:-Menüs."""
        update = make_update(username="john_doe")

        menu_system = asyncio.run(_run_send_start_message(update))

        header_text = menu_system.show_menu.call_args.kwargs["header_text"]
        assert "john\\_doe" in header_text
        assert "john_doe" not in header_text


class TestSendStartMessageErrorHandling:
    def test_exception_delegates_to_error_handler(self):
        update = make_update()
        menu_system = Mock()
        menu_system.show_menu = AsyncMock(side_effect=RuntimeError("boom"))
        error_handler = Mock()
        error_handler.handle_command_error = AsyncMock()

        asyncio.run(
            _run_send_start_message(
                update, error_handler=error_handler, menu_system=menu_system
            )
        )

        error_handler.handle_command_error.assert_awaited_once()
        assert error_handler.handle_command_error.call_args.args[2] == "start"

    def test_exception_without_error_handler_falls_back_to_generic_message(self):
        update = make_update()
        menu_system = Mock()
        menu_system.show_menu = AsyncMock(side_effect=RuntimeError("boom"))

        asyncio.run(
            _run_send_start_message(
                update, error_handler=None, menu_system=menu_system
            )
        )

        update.message.reply_text.assert_awaited_once()
        assert "Fehler" in update.message.reply_text.call_args.args[0]
