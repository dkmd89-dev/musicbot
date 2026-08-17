"""
Characterization-Tests fuer handlers/navidrome_menu_handler.py
(NavidromeMenuHandler, 1116 Zeilen, vorher 0 Tests).

Regel 7: NavidromeAPI wird komplett gemockt (kein echter Netzwerkaufruf).

Zwei reale Bugs gefunden und gefixt:

BUG-007a: _initialize_api() prüfte
"hasattr(self.config, 'NAVIDROME_URL') and hasattr(self.config, 'NAVIDROME_USER')".
NAVIDROME_URL/NAVIDROME_USER sind @property auf Config und liefern bei
fehlender .env-Variable "" statt eine Exception zu werfen - hasattr()
prüft nur, ob die Property EXISTIERT (immer der Fall), nicht ob sie einen
echten Wert hat. connection_status war dadurch unabhängig von der
tatsächlichen Konfiguration IMMER True. Fix: prüft jetzt echte
(nicht-leere) Werte.

BUG-007b: handle_artist_detail()/handle_genre_detail() fügten
artist_name/genre_name ungeschützt in einen mit parse_mode="MarkdownV2"
gesendeten Nachrichtentext ein. Andere Methoden im selben File
(process_search_query, handle_stats) escapen dynamische Inhalte bereits
korrekt mit escape_md_v2() - diese zwei nicht. Jeder MarkdownV2-
Sonderzeichen im Namen (Punkt, Bindestrich, Klammern, Ausrufezeichen -
in echten Künstler-/Genre-Namen keine Seltenheit, z.B. "Lo-Fi", "R&B/Soul")
hätte zu einem von Telegram abgelehnten "can't parse entities"-Fehler
geführt, der als generische Fehlermeldung endet statt die Details
anzuzeigen.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.navidrome_menu_handler import NavidromeMenuHandler


class FakeConfigConfigured:
    NAVIDROME_URL = "http://navidrome.example.test"
    NAVIDROME_USER = "botuser"
    NAVIDROME_PASS = "secret"


class FakeConfigUnconfigured:
    NAVIDROME_URL = ""
    NAVIDROME_USER = ""
    NAVIDROME_PASS = ""


def make_update(user_id: int = 111):
    update = Mock()
    update.effective_user.id = user_id
    update.callback_query = Mock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    return Mock()


class TestInitializeApiBug007aConnectionStatus:
    def test_configured_navidrome_sets_connection_status_true(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        assert handler.connection_status is True

    def test_unconfigured_navidrome_sets_connection_status_false(self):
        """
        Regressionstest fuer BUG-007a: vorher wurde hasattr() auf die
        IMMER vorhandene Property geprueft statt auf einen echten Wert -
        connection_status war bei komplett leerer .env-Konfiguration
        faelschlich True.
        """
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        assert handler.connection_status is False

    def test_partially_configured_navidrome_sets_connection_status_false(self):
        class PartialConfig:
            NAVIDROME_URL = "http://navidrome.example.test"
            NAVIDROME_USER = ""  # fehlt

        handler = NavidromeMenuHandler(PartialConfig())
        assert handler.connection_status is False

    def test_check_connection_reflects_status(self):
        configured = NavidromeMenuHandler(FakeConfigConfigured())
        unconfigured = NavidromeMenuHandler(FakeConfigUnconfigured())

        assert configured._check_connection() is True
        assert unconfigured._check_connection() is False


class TestConnectionErrorShownWhenUnconfigured:
    def test_browse_artists_shows_connection_error_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        with patch("api.navidrome_api.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.handle_browse_artists(update, context))

        mock_request.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text


class TestArtistDetailMarkdownEscapingBug007b:
    def test_artist_name_with_special_chars_is_escaped(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "artist": {
                    "name": "Sum 41 (Live) - Vol. 2!",
                    "album": [],
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_artist_detail(update, context, "artist-1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert kwargs["parse_mode"] == "MarkdownV2"
        sent_text = kwargs["text"]
        # Unescaped Sonderzeichen duerfen NICHT roh im gesendeten Text stehen
        assert "(Live)" not in sent_text
        assert "\\(Live\\)" in sent_text
        assert "Vol\\. 2\\!" in sent_text

    def test_artist_not_found_shows_error_without_crashing(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {"subsonic-response": {}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_artist_detail(update, context, "artist-1"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht gefunden" in text


class TestGenreDetailMarkdownEscapingBug007b:
    def test_genre_name_with_special_chars_is_escaped(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "songsByGenre": {
                    "song": [
                        {"id": "1", "title": "Song A", "artist": "Artist A", "album": "Album A"}
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(
                handler.handle_genre_detail(update, context, "Lo-Fi (Chill)!")
            )

        kwargs = update.callback_query.edit_message_text.call_args[1]
        sent_text = kwargs["text"]
        assert "Lo-Fi (Chill)!" not in sent_text
        assert "Lo\\-Fi \\(Chill\\)\\!" in sent_text

    def test_no_songs_shows_plain_error_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {"subsonic-response": {"songsByGenre": {"song": []}}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_genre_detail(update, context, "EmptyGenre"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Songs" in text
