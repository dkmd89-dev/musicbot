"""
Characterization-Tests fuer handlers/mugge_statistik_handler.py
(StatistikHandler, 570 Zeilen, vorher 0 Tests) - letzter offener Punkt
der Telegram-Handler-Layer-Charakterisierung.

WICHTIG: StatistikHandler.__init__() konstruiert intern eine ECHTE
StatistikService()-Instanz, deren __init__() wiederum echte Verzeichnisse
unter Config.STATS_DIR/Config.PLAY_HISTORY_FILE anlegt (mkdir) und eine
echte NavidromeAPI() erstellt. _make_handler() patcht StatistikService
waehrend der Konstruktion auf einen Mock, um jeden echten Seiteneffekt
zu vermeiden (analog zur Vorsicht bei user_data.json in anderen Tests
dieser Session).

Kein neuer Bug gefunden. Eine Beobachtung gegengeprueft und als
harmlos bestaetigt statt vorschnell als Bug gemeldet: _escape_text()
"escaped" nichts (nur str()-Konvertierung), aber die Klasse verwendet
laut eigenem Docstring durchgehend "Plain Text Formatierung" - kein
einziger reply_text()/edit_text()-Aufruf im ganzen File setzt einen
parse_mode. Ohne Markdown-Parsing gibt es nichts zu escapen; der
irrefuehrende Name ist ein Stil-, kein Funktionsproblem.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from handlers.mugge_statistik_handler import StatistikHandler


def _make_handler(user_mgmt_handler=None):
    with patch("handlers.mugge_statistik_handler.StatistikService") as mock_service_cls:
        handler = StatistikHandler(user_mgmt_handler=user_mgmt_handler)
    handler.statistik_service = Mock()
    return handler


def make_update(user_id: int = 111, has_callback_query=False):
    update = Mock()
    update.effective_user.id = user_id
    if has_callback_query:
        update.callback_query = Mock()
        update.callback_query.message = Mock()
        update.callback_query.message.reply_text = AsyncMock()
        update.message = None
    else:
        update.callback_query = None
        update.message = Mock()
        update.message.reply_text = AsyncMock()
    return update


class TestGetNavidromeUserForRequestPriority:
    def test_prefers_user_mgmt_handler_when_available(self, tmp_path):
        fake_user_mgmt = Mock()
        fake_user_mgmt.get_navidrome_user.return_value = "robin_from_cache"
        handler = _make_handler(user_mgmt_handler=fake_user_mgmt)
        handler.user_data_file = tmp_path / "user_data.json"

        update = make_update(111)
        result = handler._get_navidrome_user_for_request(update)

        assert result == "robin_from_cache"

    def test_falls_back_to_direct_file_read_when_user_mgmt_returns_none(self, tmp_path):
        fake_user_mgmt = Mock()
        fake_user_mgmt.get_navidrome_user.return_value = None
        handler = _make_handler(user_mgmt_handler=fake_user_mgmt)

        user_data_file = tmp_path / "user_data.json"
        user_data_file.write_text(
            json.dumps({"111": {"navidrome_user": "robin_from_file"}})
        )
        handler.user_data_file = user_data_file

        update = make_update(111)
        result = handler._get_navidrome_user_for_request(update)

        assert result == "robin_from_file"

    def test_falls_back_to_config_when_nothing_else_available(self, tmp_path):
        handler = _make_handler(user_mgmt_handler=None)
        handler.user_data_file = tmp_path / "does_not_exist.json"

        update = make_update(999)
        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "config_fallback_user"
            result = handler._get_navidrome_user_for_request(update)

        assert result == "config_fallback_user"

    def test_blank_navidrome_user_in_file_is_treated_as_missing(self, tmp_path):
        handler = _make_handler(user_mgmt_handler=None)
        user_data_file = tmp_path / "user_data.json"
        user_data_file.write_text(
            json.dumps({"111": {"navidrome_user": "   "}})
        )
        handler.user_data_file = user_data_file

        update = make_update(111)
        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "config_fallback_user"
            result = handler._get_navidrome_user_for_request(update)

        assert result == "config_fallback_user"


class TestEscapeTextIsPlainTextConversionOnly:
    def test_none_becomes_empty_string(self):
        handler = _make_handler()
        assert handler._escape_text(None) == ""

    def test_number_becomes_string(self):
        handler = _make_handler()
        assert handler._escape_text(42) == "42"

    def test_no_markdown_special_chars_are_actually_escaped(self):
        """
        Charakterisiert bewusst das (harmlose) Verhalten: "_escape_text"
        entfernt/maskiert KEINE Markdown-Sonderzeichen. Ungefaehrlich, da
        kein Aufrufer im File parse_mode setzt (reines Plain-Text-Handling).
        """
        handler = _make_handler()
        assert handler._escape_text("Artist_Name (feat. X)") == "Artist_Name (feat. X)"


class TestSendProcessingMessage:
    def test_uses_message_reply_text_for_plain_message(self):
        handler = _make_handler()
        update = make_update(111, has_callback_query=False)

        reply_target, msg = asyncio.run(
            handler._send_processing_message(update, "Teste", "robin")
        )

        update.message.reply_text.assert_called_once()
        assert reply_target is update.message

    def test_uses_callback_query_message_when_triggered_via_button(self):
        handler = _make_handler()
        update = make_update(111, has_callback_query=True)

        reply_target, msg = asyncio.run(
            handler._send_processing_message(update, "Teste", "robin")
        )

        update.callback_query.message.reply_text.assert_called_once()
        assert reply_target is update.callback_query.message

    def test_returns_none_tuple_when_no_target_available(self):
        handler = _make_handler()
        update = Mock()
        update.callback_query = None
        update.message = None

        reply_target, msg = asyncio.run(
            handler._send_processing_message(update, "Teste", "robin")
        )

        assert reply_target is None
        assert msg is None


class TestHandleTopSongs:
    def test_no_stats_shows_no_data_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = None

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Song-Daten" in sent_text

    def test_stats_with_songs_are_formatted_and_sent(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs": [("Song A", 10), ("Song B", 5)],
            "total_plays": 15,
        }
        handler.statistik_service.create_chart.return_value = None

        update = make_update(111)
        context = Mock()

        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        msg_mock.edit_text.assert_called_once()
        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Song A" in sent_text
        assert "Song B" in sent_text
        assert "15" in sent_text


class TestHandleLastPlayed:
    def test_no_history_shows_appropriate_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.get_last_played_song.return_value = None

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_last_played(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Songs" in sent_text

    def test_formats_last_played_song_details(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.get_last_played_song.return_value = {
            "title": "Some Title",
            "artist": "Some Artist",
            "album": "Some Album",
            "timestamp": "2026-01-15T12:30:00",
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_last_played(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Some Title" in sent_text
        assert "Some Artist" in sent_text
        assert "15.01.2026" in sent_text
