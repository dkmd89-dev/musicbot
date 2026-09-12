"""
Phase F3 (Family Hub) - Tests für handlers/family_chat_handler.py.

Mock-Strategie identisch zu tests/test_family_stats_handler.py:
FamilyService/FamilyChatService werden als Mocks injiziert.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from handlers.family_chat_handler import FamilyChatHandler


def make_update(user_id: int = 111, has_callback_query=False):
    update = Mock()
    update.effective_user.id = user_id
    if has_callback_query:
        update.callback_query = AsyncMock()
        update.callback_query.message = Mock()
        update.callback_query.message.reply_text = AsyncMock()
        update.message = None
    else:
        update.callback_query = None
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    return update


def make_context():
    context = Mock()
    context.bot.send_message = AsyncMock()
    return context


def _make_handler(is_member=True):
    family_service = Mock()
    family_service.is_active_family_member.return_value = is_member
    chat_service = Mock()
    handler = FamilyChatHandler(family_service=family_service, chat_service=chat_service)
    return handler, family_service, chat_service


class TestHandleSendMessagePrompt:
    def test_non_member_is_denied_and_not_added_to_pending(self):
        handler, _, chat_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_send_message_prompt(update, make_context()))

        assert 999 not in handler.pending_message_senders
        update.message.reply_text.assert_called_once()
        assert "Familienmitglieder" in update.message.reply_text.call_args[0][0]

    def test_member_is_added_to_pending_and_prompted(self):
        handler, _, _ = _make_handler(is_member=True)
        update = make_update(111)

        asyncio.run(handler.handle_send_message_prompt(update, make_context()))

        assert 111 in handler.pending_message_senders
        sent_text = update.message.reply_text.call_args[0][0]
        assert "Schreibe" in sent_text


class TestProcessPendingMessage:
    def test_removes_sender_from_pending_regardless_of_outcome(self):
        handler, _, chat_service = _make_handler()
        chat_service.post_message.return_value = None
        update = make_update(111)
        handler.pending_message_senders.add(111)

        asyncio.run(handler.process_pending_message(update, make_context(), "Hallo"))

        assert 111 not in handler.pending_message_senders

    def test_failed_post_shows_warning_and_does_not_broadcast(self):
        handler, _, chat_service = _make_handler()
        chat_service.post_message.return_value = None
        update = make_update(111)
        context = make_context()

        asyncio.run(handler.process_pending_message(update, context, "  "))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "konnte nicht gesendet" in sent_text
        context.bot.send_message.assert_not_called()

    def test_successful_post_broadcasts_to_recipients(self):
        handler, _, chat_service = _make_handler()
        chat_service.post_message.return_value = {
            "sender_display_name": "Papa",
            "message": "Hallo Familie!",
        }
        chat_service.get_notification_recipients.return_value = ["222", "333"]
        update = make_update(111)
        context = make_context()

        asyncio.run(handler.process_pending_message(update, context, "Hallo Familie!"))

        assert context.bot.send_message.call_count == 2
        first_call_kwargs = context.bot.send_message.call_args_list[0].kwargs
        assert first_call_kwargs["chat_id"] == 222
        assert "Papa" in first_call_kwargs["text"]
        assert "Hallo Familie!" in first_call_kwargs["text"]

    def test_broadcast_failure_for_one_recipient_does_not_raise(self):
        handler, _, chat_service = _make_handler()
        chat_service.post_message.return_value = {
            "sender_display_name": "Papa",
            "message": "Hallo!",
        }
        chat_service.get_notification_recipients.return_value = ["222"]
        update = make_update(111)
        context = make_context()
        context.bot.send_message.side_effect = Exception("Telegram down")

        asyncio.run(handler.process_pending_message(update, context, "Hallo!"))
        # Kein Raise - Fehler wird nur geloggt.


class TestHandleRecentMessages:
    def test_denied_for_non_member(self):
        handler, _, chat_service = _make_handler()
        chat_service.get_recent_messages.return_value = None
        update = make_update(999)

        asyncio.run(handler.handle_recent_messages(update, make_context()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "Familienmitglieder" in sent_text

    def test_shows_placeholder_when_no_messages_yet(self):
        handler, _, chat_service = _make_handler()
        chat_service.get_recent_messages.return_value = []
        update = make_update(111)

        asyncio.run(handler.handle_recent_messages(update, make_context()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "Noch keine Nachrichten" in sent_text

    def test_formats_messages_with_sender_and_text(self):
        handler, _, chat_service = _make_handler()
        chat_service.get_recent_messages.return_value = [
            {
                "sender_display_name": "Papa",
                "message": "Eins",
                "created_at": "2026-09-12T18:00:00",
            },
            {
                "sender_display_name": "Mama",
                "message": "Zwei",
                "created_at": "2026-09-12T18:05:00",
            },
        ]
        update = make_update(111)

        asyncio.run(handler.handle_recent_messages(update, make_context()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "Papa" in sent_text and "Eins" in sent_text
        assert "Mama" in sent_text and "Zwei" in sent_text
        assert sent_text.index("Eins") < sent_text.index("Zwei")


class TestHandleToggleNotifications:
    def test_denied_for_non_member(self):
        handler, _, chat_service = _make_handler(is_member=False)
        update = make_update(999)

        asyncio.run(handler.handle_toggle_notifications(update, make_context()))

        chat_service.set_notifications.assert_not_called()

    def test_toggles_from_off_to_on(self):
        handler, _, chat_service = _make_handler()
        chat_service.notifications_enabled.return_value = False
        chat_service.set_notifications.return_value = True
        update = make_update(111)

        asyncio.run(handler.handle_toggle_notifications(update, make_context()))

        chat_service.set_notifications.assert_called_once_with(111, True)
        sent_text = update.message.reply_text.call_args[0][0]
        assert "AN" in sent_text

    def test_toggles_from_on_to_off(self):
        handler, _, chat_service = _make_handler()
        chat_service.notifications_enabled.return_value = True
        chat_service.set_notifications.return_value = True
        update = make_update(111)

        asyncio.run(handler.handle_toggle_notifications(update, make_context()))

        chat_service.set_notifications.assert_called_once_with(111, False)
        sent_text = update.message.reply_text.call_args[0][0]
        assert "AUS" in sent_text

    def test_shows_error_when_persistence_fails(self):
        handler, _, chat_service = _make_handler()
        chat_service.notifications_enabled.return_value = False
        chat_service.set_notifications.return_value = False
        update = make_update(111)

        asyncio.run(handler.handle_toggle_notifications(update, make_context()))

        sent_text = update.message.reply_text.call_args[0][0]
        assert "nicht gespeichert" in sent_text
