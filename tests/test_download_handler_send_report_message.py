"""
Regressionstests fuer klassen/download_handler.py::_send_report_message()
— vorher 0 Tests.

ARCH-007/P-2 (2026-08-24): der eigentliche Telegram-Versand fuer Duplikat-/
Abschluss-Meldungen lag vorher teils in services/downloader/utils/
download_result_reporter.py (send_final_summary()/send_playlist_direct_summary()),
teils bereits in klassen/download_handler.py (_handle_duplicate_found()).
Jetzt liegt der Versand ausschliesslich hier - services/ liefert nur noch
fertigen Text (build_*_message()), keine Telegram-Abhaengigkeit mehr.
_send_report_message() ist das gemeinsame Send-Muster (status_msg mit
Fallback auf update.message, TelegramError-Fang) fuer alle drei
Aufrufstellen (_handle_duplicate_found/handle_single_track_success/
handle_playlist_success) - siehe
tests/test_download_result_reporter.py fuer die reinen Text-Bau-Tests
(die frueheren Versand-/Fallback-/Fehlerbehandlungs-Tests, die vorher dort
lagen, sind hierher verschoben).

DownloadHandler hat einen schweren Konstruktor - object.__new__() umgeht
ihn bewusst, da _send_report_message() nur self.status_msg/self.update/
self.logger tatsaechlich verwendet (etabliertes Muster dieser Session,
siehe test_download_handler_process_single_download_result.py).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

from telegram.error import TelegramError

from klassen.download_handler import DownloadHandler


def run_async(coro):
    return asyncio.run(coro)


def make_handler(status_msg=None):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.status_msg = status_msg
    handler.update = Mock()
    handler.update.message = Mock()
    handler.update.message.reply_text = AsyncMock()
    return handler


def make_status_msg():
    msg = Mock()
    msg.edit_text = AsyncMock()
    return msg


class TestSendReportMessage:
    def test_uses_status_msg_when_present(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)

        run_async(handler._send_report_message("hello", "err: "))

        status_msg.edit_text.assert_called_once_with("hello")
        handler.update.message.reply_text.assert_not_called()

    def test_falls_back_to_update_message_when_no_status_msg(self):
        handler = make_handler(status_msg=None)

        run_async(handler._send_report_message("hello", "err: "))

        handler.update.message.reply_text.assert_called_once_with("hello")

    def test_telegram_error_is_logged_with_given_prefix_not_raised(self):
        status_msg = make_status_msg()
        status_msg.edit_text.side_effect = TelegramError("boom")
        handler = make_handler(status_msg)

        run_async(handler._send_report_message("hello", "❌ custom prefix: "))

        handler.logger.error.assert_called_once()
        logged = handler.logger.error.call_args[0][0]
        assert logged == "❌ custom prefix: boom"

    def test_success_log_msg_is_logged_when_given_and_send_succeeds(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)

        run_async(
            handler._send_report_message(
                "hello", "err: ", success_log_msg="✅ done"
            )
        )

        handler.logger.info.assert_called_once_with("✅ done")

    def test_no_success_log_when_success_log_msg_omitted(self):
        status_msg = make_status_msg()
        handler = make_handler(status_msg)

        run_async(handler._send_report_message("hello", "err: "))

        handler.logger.info.assert_not_called()

    def test_success_log_not_emitted_when_send_fails(self):
        status_msg = make_status_msg()
        status_msg.edit_text.side_effect = TelegramError("boom")
        handler = make_handler(status_msg)

        run_async(
            handler._send_report_message(
                "hello", "err: ", success_log_msg="✅ done"
            )
        )

        handler.logger.info.assert_not_called()
