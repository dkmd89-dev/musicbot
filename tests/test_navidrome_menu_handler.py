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


class TestAlbumDetailNavF9:
    """NAV-F9: handle_album_detail() schließt den bisherigen
    nav_album_<id>-STUB (Navidrome Menu System Audit, 2026-09-13)."""

    def test_album_details_are_rendered_with_tracklist(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "album": {
                    "id": "a1",
                    "name": "Test Album",
                    "artist": "Test Artist",
                    "artistId": "ar1",
                    "songCount": 2,
                    "duration": 245,
                    "year": 2023,
                    "song": [
                        {"id": "s1", "title": "Track One", "track": 1},
                        {"id": "s2", "title": "Track Two", "track": 2},
                    ],
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_album_detail(update, context, "a1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert kwargs["parse_mode"] == "MarkdownV2"
        assert "Test Artist" in kwargs["text"]
        buttons = {
            b.callback_data
            for row in kwargs["reply_markup"].inline_keyboard
            for b in row
        }
        assert "nav_song_s1" in buttons
        assert "nav_song_s2" in buttons
        assert "nav_artist_ar1" in buttons
        assert "menu:navidrome" in buttons

    def test_album_name_with_special_chars_is_escaped(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "album": {
                    "id": "a1",
                    "name": "Greatest Hits (Deluxe)!",
                    "artist": "Artist & Friends",
                    "song": [],
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_album_detail(update, context, "a1"))

        sent_text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "(Deluxe)!" not in sent_text
        assert "\\(Deluxe\\)\\!" in sent_text

    def test_album_not_found_shows_error_without_crashing(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {"subsonic-response": {}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_album_detail(update, context, "a1"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht gefunden" in text

    def test_connection_error_shown_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.handle_album_detail(update, context, "a1"))

        mock_request.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text


class TestSongDetailNavF9:
    """NAV-F9: handle_song_detail() schließt den bisherigen
    nav_song_<id>-STUB (Navidrome Menu System Audit, 2026-09-13)."""

    def test_song_details_are_rendered_with_navigation_buttons(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "song": {
                    "id": "s1",
                    "title": "Some Song",
                    "artist": "Artist X",
                    "artistId": "ar1",
                    "album": "Album Y",
                    "albumId": "al1",
                    "track": 5,
                    "year": 2022,
                    "genre": "Pop",
                    "duration": 187,
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_song_detail(update, context, "s1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert kwargs["parse_mode"] == "MarkdownV2"
        sent_text = kwargs["text"]
        assert "Artist X" in sent_text
        assert "Album Y" in sent_text
        assert "3\\:07" in sent_text  # 187s -> 3:07
        buttons = {
            b.callback_data
            for row in kwargs["reply_markup"].inline_keyboard
            for b in row
        }
        assert "nav_artist_ar1" in buttons
        assert "nav_album_al1" in buttons
        assert "menu:navidrome" in buttons

    def test_song_title_with_special_chars_is_escaped(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "song": {"id": "s1", "title": "Song (Live) - Remix!", "artist": "A"}
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_song_detail(update, context, "s1"))

        sent_text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "(Live) - Remix!" not in sent_text
        assert "\\(Live\\) \\- Remix\\!" in sent_text

    def test_song_not_found_shows_error_without_crashing(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {"subsonic-response": {}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_song_detail(update, context, "s1"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht gefunden" in text


class TestFormatTrackDuration:
    def test_formats_seconds_as_minutes_seconds(self):
        assert NavidromeMenuHandler._format_track_duration(187) == "3:07"
        assert NavidromeMenuHandler._format_track_duration(60) == "1:00"
        assert NavidromeMenuHandler._format_track_duration(0) == "0:00"

    def test_handles_missing_or_invalid_value(self):
        assert NavidromeMenuHandler._format_track_duration(None) == "0:00"
        assert NavidromeMenuHandler._format_track_duration("n/a") == "0:00"


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


class TestBackButtonsUseValidMenuCallbackFormatNavF1:
    """NAV-F1-Regressionstest (Navidrome Menu System Audit, 2026-09-13):
    alle "🔙 Zurück"/"❌ Abbrechen"-Buttons dieser Klasse nutzten bisher
    callback_data "menu_navidrome"/"menu_main" (Unterstrich) - weder als
    PTB-CallbackQueryHandler-Pattern registriert (nur "^menu:" mit
    Doppelpunkt, siehe rich_menu_handler.py::get_telegram_handlers())
    noch von RichMenuSystem.handle_callback() geroutet. Jeder Klick
    verpuffte dadurch stillschweigend. Pinnt jetzt, dass ausschließlich
    das gültige "menu:<id>"-Format verwendet wird."""

    def _extract_callback_data_values(self, reply_markup) -> set:
        return {
            button.callback_data
            for row in reply_markup.inline_keyboard
            for button in row
        }

    def test_browse_artists_back_button_uses_menu_colon_format(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[{"id": "1", "name": "Artist A"}]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_values = self._extract_callback_data_values(markup)
        assert "menu:navidrome" in callback_values
        assert "menu_navidrome" not in callback_values

    def test_connection_error_reconnect_and_back_use_valid_callbacks(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_values = self._extract_callback_data_values(markup)
        assert "menu:main" in callback_values
        assert "menu_main" not in callback_values
        # "🔄 Erneut versuchen" bleibt unverändert nav_reconnect (kein
        # Teil von NAV-F1 - eigener, bereits gültiger nav_-Präfix).
        assert "nav_reconnect" in callback_values

    def test_reconnect_success_button_uses_menu_colon_format(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        # NAV-F6: handle_reconnect() ruft jetzt echt check_connection() auf
        # (Regel 7 - externer Netzwerkaufruf wird gemockt).
        handler.navidrome_api.check_connection = AsyncMock(return_value=True)
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_reconnect(update, context))

        markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
        callback_values = self._extract_callback_data_values(markup)
        assert "menu:navidrome" in callback_values
        assert "menu_navidrome" not in callback_values

    def test_no_underscore_menu_callbacks_remain_anywhere_in_source(self):
        """Repoweiter Beweis (Abschnitt 20 CLAUDE.md-Analogon: Wiederholungs-
        nachweis) - kein 'callback_data="menu_navidrome"'/'callback_data=
        "menu_main"' (Unterstrich) mehr im Handler-Quelltext (Docstring-
        Erwähnungen des Bugs selbst bleiben erlaubt, daher der engere,
        auf das tatsächliche callback_data=-Muster beschränkte Check statt
        eines naiven Substring-Checks)."""
        import inspect
        import handlers.navidrome_menu_handler as module

        source = inspect.getsource(module)
        assert 'callback_data="menu_navidrome"' not in source
        assert 'callback_data="menu_main"' not in source


class TestReconnectUsesRealConnectionCheckNavF6:
    """NAV-F6-Regressionstest (Navidrome Menu System Audit, 2026-09-13):
    handle_reconnect() prüfte bisher nur erneut die Config-Präsenz
    (_initialize_api()/_check_connection()), NIEMALS einen echten
    Subsonic-`ping`. "🔄 Erneut versuchen" meldete dadurch auch dann
    Erfolg, wenn der Server tatsächlich nicht erreichbar war. Pinnt
    jetzt, dass ein echter NavidromeAPI.check_connection()-Aufruf
    stattfindet und dessen Ergebnis über Erfolg/Fehler entscheidet."""

    def test_successful_ping_shows_success_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.check_connection = AsyncMock(return_value=True)
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_reconnect(update, context))

        handler.navidrome_api.check_connection.assert_awaited_once()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Verbindung wiederhergestellt" in text

    def test_failed_ping_shows_connection_error_not_success(self):
        """Der eigentliche Bug: bei nicht erreichbarem Server (echter
        ping schlägt fehl) durfte NIE 'Verbindung wiederhergestellt'
        angezeigt werden, obwohl die Config selbst vollständig ist."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.check_connection = AsyncMock(return_value=False)
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_reconnect(update, context))

        handler.navidrome_api.check_connection.assert_awaited_once()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text
        assert "wiederhergestellt" not in text

    def test_failed_ping_resets_connection_status_for_subsequent_clicks(self):
        """Ohne diesen Reset würde der nächste Klick auf z.B. 'Künstler
        durchsuchen' die veraltete True-Config-Präsenz nutzen und eine
        echte API-Exception riskieren statt der freundlichen
        Verbindungsfehler-Meldung."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.check_connection = AsyncMock(return_value=False)
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_reconnect(update, context))

        assert handler.connection_status is False

    def test_unconfigured_config_shows_connection_error_without_ping(self):
        """Bei fehlender Config wird kein Netzwerkaufruf ausgelöst -
        der schnelle lokale Check bleibt die erste Instanz."""
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        handler.navidrome_api.check_connection = AsyncMock(return_value=True)
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_reconnect(update, context))

        handler.navidrome_api.check_connection.assert_not_awaited()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text

    def test_browse_precheck_remains_local_no_network_call(self):
        """Der schnelle lokale Vorab-Check vor den übrigen Browse-/Such-
        Methoden bleibt bewusst unverändert - kein ping vor jedem
        einzelnen Klick (Latenz-Trade-off, siehe NAV-F6-Dokumentation)."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.check_connection = AsyncMock(return_value=True)
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[{"id": "1", "name": "Artist A"}]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        handler.navidrome_api.check_connection.assert_not_awaited()


class TestGenreSongsAllRoutingNavF2:
    """NAV-F2-Regressionstest: 'nav_genre_songs_all_<name>' wurde bisher
    vom generischen 'nav_genre_'-Präfix-Zweig abgefangen und lieferte
    einen korrupten Parameter ('songs_all_<name>' statt '<name>') an
    handle_genre_detail(). Pinnt jetzt, dass der Callback sauber als
    eigener (noch nicht implementierter) Zweig behandelt wird, OHNE
    handle_genre_detail() mit einem falschen Genre-Namen aufzurufen."""

    def test_songs_all_callback_does_not_call_genre_detail_with_corrupted_name(self):
        from handlers.menu.actions.navidrome import handle_navidrome_callback

        navidrome_handler = Mock()
        navidrome_handler.handle_genre_detail = AsyncMock()
        update = make_update()
        update.callback_query.data = "nav_genre_songs_all_Lo-Fi"
        context = make_context()
        logger = Mock()

        asyncio.run(
            handle_navidrome_callback(
                update, context, "nav_genre_songs_all_Lo-Fi", navidrome_handler, logger
            )
        )

        navidrome_handler.handle_genre_detail.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "songs_all" not in text

    def test_normal_genre_callback_still_extracts_correct_name(self):
        """Regressionsschutz: der Fix darf den normalen
        'nav_genre_<name>'-Pfad nicht brechen."""
        from handlers.menu.actions.navidrome import handle_navidrome_callback

        navidrome_handler = Mock()
        navidrome_handler.handle_genre_detail = AsyncMock()
        update = make_update()
        update.callback_query.data = "nav_genre_Lo-Fi"
        context = make_context()
        logger = Mock()

        asyncio.run(
            handle_navidrome_callback(
                update, context, "nav_genre_Lo-Fi", navidrome_handler, logger
            )
        )

        navidrome_handler.handle_genre_detail.assert_awaited_once_with(
            update, context, "Lo-Fi"
        )
