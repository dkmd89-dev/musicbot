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

ARCH-009 Phase 8 (2026-08-24): NavidromeAPI (der reine Adapter) wurde nach
services/clients/navidrome_api.py verschoben. Das Patch-Ziel in
TestConnectionErrorShownWhenUnconfigured wurde dabei bewusst auf das
konsumierende Modul umgestellt
("handlers.navidrome_menu_handler.NavidromeAPI.make_request" statt
"api.navidrome_api.NavidromeAPI.make_request") - robuster gegenüber
künftigen Verschiebungen, da der Patch-Pfad dem tatsächlichen Import in
diesem Handler folgt statt dem Ursprungsmodul.
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

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
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


class TestErrorHandlerIntegration:
    """error_handler wird von rich_menu_handler.py nach der Konstruktion
    zugewiesen (self.navidrome_handler.error_handler = self.error_handler).
    Ohne explizite Zuweisung bleibt er None - alle obigen Tests (ohne
    error_handler) decken bereits ab, dass der bisherige Fallback dann
    unveraendert greift. Diese Klasse deckt den NEUEN Pfad ab: ist
    error_handler gesetzt, wird er tatsaechlich aufgerufen - und zwar
    STATT der bisherigen lokalen Fehlermeldung (kein doppeltes
    Benachrichtigen), analog zum bereits etablierten Muster in
    handlers/enhanced_status_handler.py / handlers/menu/rich_menu_system.py."""

    def test_browse_artists_routes_through_error_handler_when_set(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.navidrome_api.get_artists = AsyncMock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        call_args = handler.error_handler.handle_callback_error.call_args[0]
        assert call_args[0] is update
        assert call_args[1] is context
        assert call_args[2] == "navidrome_browse_artists"
        assert isinstance(call_args[3], RuntimeError)
        # kein doppeltes Benachrichtigen: die alte lokale Fehlermeldung
        # darf NICHT zusaetzlich gesendet werden.
        update.callback_query.edit_message_text.assert_not_called()

    def test_browse_artists_falls_back_to_local_message_without_error_handler(self):
        """Nichtregression, explizit gegen den neuen Codepfad geprueft
        (nicht nur implizit ueber bestehende Tests)."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        assert handler.error_handler is None
        handler.navidrome_api.get_artists = AsyncMock(side_effect=RuntimeError("boom"))
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Fehler beim Laden der Künstler" in text

    def test_search_query_routes_through_error_handler_when_set(self):
        """process_search_query wird per Textnachricht (nicht per
        Callback) ausgeloest - prueft, dass die Integration auch fuer
        diesen Update-Typ korrekt verdrahtet ist. Die erste reply_text()
        ("Suche nach ...") passiert VOR dem Fehler und bleibt daher immer
        bestehen - entscheidend ist, dass keine ZWEITE, lokale
        Fehlermeldung mehr gesendet wird, wenn error_handler gesetzt ist."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        handler.navidrome_api.search = AsyncMock(side_effect=RuntimeError("boom"))
        user_id = 111
        handler.browse_states[user_id] = {"waiting_for_search": True, "search_type": "all"}
        update = make_update(user_id=user_id)
        update.message = Mock()
        update.message.reply_text = AsyncMock(return_value=Mock())
        context = make_context()

        asyncio.run(handler.process_search_query(update, context, "query text"))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        assert handler.error_handler.handle_callback_error.call_args[0][2] == "navidrome_search_query"
        # nur die "Suche nach ..."-Nachricht, KEINE zusaetzliche lokale
        # Fehlermeldung mehr.
        assert update.message.reply_text.await_count == 1

    def test_search_query_falls_back_to_local_message_without_error_handler(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        assert handler.error_handler is None
        handler.navidrome_api.search = AsyncMock(side_effect=RuntimeError("boom"))
        user_id = 111
        handler.browse_states[user_id] = {"waiting_for_search": True, "search_type": "all"}
        update = make_update(user_id=user_id)
        update.message = Mock()
        update.message.reply_text = AsyncMock(return_value=Mock())
        context = make_context()

        asyncio.run(handler.process_search_query(update, context, "query text"))

        # "Suche nach ..." + lokale Fehlermeldung = 2 Aufrufe.
        assert update.message.reply_text.await_count == 2
        error_text = update.message.reply_text.call_args[0][0]
        assert "Fehler bei der Suche" in error_text

    def test_stats_routes_through_error_handler_when_set(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.error_handler = Mock()
        handler.error_handler.handle_callback_error = AsyncMock()
        update = make_update()
        context = make_context()

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            asyncio.run(handler.handle_stats(update, context))

        handler.error_handler.handle_callback_error.assert_awaited_once()
        assert handler.error_handler.handle_callback_error.call_args[0][2] == "navidrome_stats"
