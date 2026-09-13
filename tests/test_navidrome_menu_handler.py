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
(process_search_query) escapen dynamische Inhalte bereits
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


class TestBrowseArtistsCharacterization:
    """Architecture Refactoring Audit, Migrationsstufe 3 (Browse-Rendering-
    Extraktion, siehe
    docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md):
    Pflichtschritt VOR der Extraktion. handle_browse_artists() hatte bisher
    nur 1 duennen Test (Button-Format in TestBackButtonsUseValidMenuCallbackFormatNavF1),
    keinen echten Verhaltenstest fuer Pagination/leere Liste. Diese Klasse
    schliesst die Luecke, damit der Rendering/API-Schnitt denselben
    Regressionsschutz hat wie bei Stufe 1 (Album/Song/Playlist)."""

    def test_empty_list_shows_no_artists_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.get_artists = AsyncMock(return_value=[])
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Künstler" in text

    def test_first_page_renders_artist_buttons_without_previous_button(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[
                {"id": "1", "name": "Artist A"},
                {"id": "2", "name": "Artist B"},
            ]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context, page=0))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert kwargs["parse_mode"] == "MarkdownV2"
        assert "Seite 1" in kwargs["text"]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_artist_1" in buttons
        assert "nav_artist_2" in buttons
        assert not any(cb.startswith("nav_browse_artists_") for cb in buttons)

    def test_middle_page_shows_both_previous_and_next_buttons(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        # page_size=20 -> 45 Kuenstler ergeben 3 Seiten (0,1,2).
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[{"id": str(i), "name": f"Artist {i}"} for i in range(45)]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context, page=1))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_browse_artists_0" in buttons
        assert "nav_browse_artists_2" in buttons

    def test_last_page_omits_next_button(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[{"id": str(i), "name": f"Artist {i}"} for i in range(25)]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context, page=1))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_browse_artists_0" in buttons
        assert not any(cb == "nav_browse_artists_2" for cb in buttons)

    def test_artist_name_and_id_fall_back_to_alternate_fields(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.get_artists = AsyncMock(
            return_value=[{"title": "Fallback Name", "artistId": "fb1"}]
        )
        update = make_update()
        context = make_context()

        asyncio.run(handler.handle_browse_artists(update, context))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_artist_fb1" in buttons


class TestBrowseAlbumsCharacterization:
    """Architecture Refactoring Audit, Migrationsstufe 3, Pflichtschritt:
    handle_browse_albums() hatte bisher 0 direkte Tests, obwohl sie zwei
    unterschiedliche API-Pfade (getArtist vs. getAlbumList2) und echte
    Pagination-Arithmetik enthaelt (siehe Audit-Tabelle im Migrationsplan)."""

    def test_empty_albums_shows_no_albums_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {"albumList2": {"album": []}}
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_albums(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Alben" in text

    def test_no_artist_id_uses_album_list2_and_shows_all_albums_title(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "albumList2": {
                    "album": [{"id": "al1", "name": "Album One", "artist": "X"}]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ) as mock_to_thread:
            asyncio.run(handler.handle_browse_albums(update, context))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert "Alle Alben" in kwargs["text"]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_album_al1" in buttons
        # Kein "Kuenstler"-Back-Button ohne artist_id.
        assert "nav_browse_artists" not in buttons
        assert mock_to_thread.call_args[0][1] == "getAlbumList2"

    def test_with_artist_id_uses_get_artist_endpoint_and_shows_kuenstler_button(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "artist": {
                    "album": [{"id": "al1", "name": "Album One", "artist": "X"}]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ) as mock_to_thread:
            asyncio.run(handler.handle_browse_albums(update, context, artist_id="ar1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert "Alben des Künstlers" in kwargs["text"]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_browse_artists" in buttons
        assert mock_to_thread.call_args[0][1] == "getArtist"

    def test_full_page_shows_next_button_with_artist_id_suffix(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        # page_size=15 - genau 15 Alben loest has_next aus.
        fake_response = {
            "subsonic-response": {
                "artist": {
                    "album": [
                        {"id": f"al{i}", "name": f"Album {i}"} for i in range(15)
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_albums(update, context, artist_id="ar1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_browse_albums_1_ar1" in buttons

    def test_previous_button_includes_artist_id_suffix(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        # page_size=15, page=1 -> Slice [15:30]; braucht >15 Alben, sonst
        # ist die Seite leer und "Keine Alben gefunden" greift statt der
        # Navigation (siehe test_empty_albums_shows_no_albums_message).
        fake_response = {
            "subsonic-response": {
                "artist": {
                    "album": [
                        {"id": f"al{i}", "name": f"Album {i}"} for i in range(20)
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(
                handler.handle_browse_albums(update, context, page=1, artist_id="ar1")
            )

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "nav_browse_albums_0_ar1" in buttons

    def test_connection_error_shown_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.handle_browse_albums(update, context))

        mock_request.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text


class TestBrowseGenresCharacterization:
    """Architecture Refactoring Audit, Migrationsstufe 3, Pflichtschritt:
    handle_browse_genres() hatte bisher 0 direkte Tests, obwohl sie einen
    Sortier-Fallback-Zweig (songCount nicht parsebar -> alphabetisch)
    enthaelt (siehe Audit-Tabelle im Migrationsplan)."""

    def test_empty_genres_shows_no_genres_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {"subsonic-response": {"genres": {"genre": []}}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_genres(update, context))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Keine Genres" in text

    def test_genres_sorted_by_song_count_descending(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "genres": {
                    "genre": [
                        {"value": "Pop", "songCount": 5},
                        {"value": "Hip-Hop", "songCount": 50},
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_genres(update, context))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons_in_order = [
            b.text for row in kwargs["reply_markup"].inline_keyboard for b in row
            if b.callback_data.startswith("nav_genre_")
        ]
        assert buttons_in_order.index("🎭 Hip-Hop (50)") < buttons_in_order.index("🎭 Pop (5)")

    def test_non_numeric_song_count_crashes_instead_of_falling_back_cleanly(self):
        """Charakterisiert einen TATSAECHLICHEN, bisher unentdeckten Bug
        (kein Sollverhalten): handle_browse_genres() hat einen
        try/except um den Sortier-Aufruf, der bei nicht-numerischem
        `songCount` (z.B. "n/a") auf alphabetische Sortierung nach
        `x.get("name", "")` zurückfaellt (Zeile ~366) - ABER die
        anschliessende Anzeige-Schleife nutzt denselben rohen,
        nicht-konvertierten `song_count`-Wert direkt in einem
        `if song_count > 0:`-Vergleich (Zeile ~382), was bei einem
        String/None-Wert mit
        "TypeError: '>' not supported between instances of 'str' and 'int'"
        crasht. Der Fallback im Sortier-Schritt faengt diesen
        Folgefehler NICHT ab - die Methode landet im aeusseren
        Exception-Handler und zeigt die generische Fehlermeldung statt
        einer (wenn auch fehlerhaft sortierten) Genre-Liste. Zusaetzlich
        zeigt der Sortier-Fallback selbst einen zweiten, dadurch aber
        praktisch unbeobachtbaren Bug: er sortiert nach `x.get("name", "")`
        statt nach dem tatsaechlich fuer die Anzeige genutzten
        `x.get("value")`-Feld (Zeile ~378/1222) - unbeobachtbar, weil der
        Crash oben in der Praxis immer zuerst eintritt, bevor das
        Sortierergebnis je gerendert wird. Entdeckt beim Schreiben dieses
        Characterization-Tests (Architecture Refactoring Audit,
        Migrationsstufe 3, Pflichtschritt) - bewusst NICHT gefixt, siehe
        Kandidat-Finding NAV-F14 in
        docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "genres": {
                    "genre": [
                        {"value": "Zeta", "songCount": "n/a"},
                        {"value": "Alpha", "songCount": "n/a"},
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_genres(update, context))

        # Kein Crash der Testumgebung (Exception wird intern abgefangen),
        # aber die generische Fehlermeldung statt einer Genre-Liste -
        # kein "reply_markup"/keine Genre-Buttons im Ergebnis.
        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "reply_markup" not in kwargs
        assert "Fehler beim Laden der Genres" in args[0]

    def test_genre_button_omits_parens_when_song_count_zero(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "genres": {"genre": [{"value": "Obscure", "songCount": 0}]}
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_genres(update, context))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        buttons = {b.text for row in kwargs["reply_markup"].inline_keyboard for b in row}
        assert "🎭 Obscure" in buttons

    def test_max_20_genres_shown_in_keyboard(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()
        fake_response = {
            "subsonic-response": {
                "genres": {
                    "genre": [
                        {"value": f"Genre{i}", "songCount": i} for i in range(30)
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_browse_genres(update, context))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        # "nav_genre_stats" (Control-Button) startet ebenfalls mit
        # "nav_genre_" (derselbe NAV-F12-Praefix, siehe
        # handlers/menu/actions/navidrome.py) - hier explizit
        # ausgeschlossen, um nur echte Genre-Buttons zu zaehlen.
        genre_buttons = [
            b for row in kwargs["reply_markup"].inline_keyboard for b in row
            if b.callback_data.startswith("nav_genre_")
            and b.callback_data != "nav_genre_stats"
        ]
        assert len(genre_buttons) == 20

    def test_connection_error_shown_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.handle_browse_genres(update, context))

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

    def test_static_top_songs_footer_parens_are_escaped(self):
        """Regressionstest fuer einen echten Live-Fund: der statische
        Text '(erste 10 angezeigt)' im 'Top Songs'-Footer enthielt
        unescapte Klammern trotz parse_mode='MarkdownV2' - fuehrte bei
        JEDEM erfolgreichen Genre-Lookup mit Songs zu 'Can't parse
        entities: character '(' is reserved' (Telegram lehnte die
        Nachricht ab). Nicht auf dynamische Inhalte beschraenkt (BUG-007-
        artig), sondern ein statischer String-Literal-Bug."""
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
            asyncio.run(handler.handle_genre_detail(update, context, "Experimental"))

        sent_text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "(erste 10 angezeigt)" not in sent_text
        assert "\\(erste 10 angezeigt\\)" in sent_text


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


class TestPlaylistDetailNavF5:
    """NAV-F5: handle_playlist_detail() schließt die bisherige
    nav_playlist_<id>-Dead-Route (Navidrome Menu System Audit,
    2026-09-13). Nachtrag (Architecture Refactoring Audit, Stufe 1):
    diese Methode hatte bisher KEINE direkten Unit-Tests - anders als
    handle_album_detail()/handle_song_detail() (je 3-4 Tests) - obwohl
    sie strukturell identisch ist. Ergänzt VOR der Rendering-Extraktion
    (docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md,
    Abschnitt 5, Pflichtschritt), damit die Extraktion denselben
    Regressionsschutz hat wie bei Album/Song."""

    def test_playlist_details_are_rendered_with_tracklist(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "playlist": {
                    "id": "pl1",
                    "name": "Test Playlist",
                    "owner": "robin",
                    "songCount": 2,
                    "duration": 245,
                    "entry": [
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
            asyncio.run(handler.handle_playlist_detail(update, context, "pl1"))

        kwargs = update.callback_query.edit_message_text.call_args[1]
        assert kwargs["parse_mode"] == "MarkdownV2"
        assert "robin" in kwargs["text"]
        buttons = {
            b.callback_data
            for row in kwargs["reply_markup"].inline_keyboard
            for b in row
        }
        assert "nav_song_s1" in buttons
        assert "nav_song_s2" in buttons
        assert "menu:navidrome" in buttons

    def test_playlist_name_and_owner_with_special_chars_are_escaped(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "playlist": {
                    "id": "pl1",
                    "name": "Party (Deluxe)!",
                    "owner": "Artist & Friends",
                    "entry": [],
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_playlist_detail(update, context, "pl1"))

        sent_text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "(Deluxe)!" not in sent_text
        assert "\\(Deluxe\\)\\!" in sent_text
        # "&" ist KEIN MarkdownV2-Sonderzeichen (escape_md_v2() escapt es
        # bewusst nicht, siehe helfer/markdown_helfer.py) - der Owner-Name
        # erscheint daher unveraendert.
        assert "Artist & Friends" in sent_text

    def test_playlist_not_found_shows_error_without_crashing(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        update = make_update()
        context = make_context()

        fake_response = {"subsonic-response": {}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.handle_playlist_detail(update, context, "pl1"))

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "nicht gefunden" in text

    def test_connection_error_shown_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        update = make_update()
        context = make_context()

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.handle_playlist_detail(update, context, "pl1"))

        mock_request.assert_not_called()
        text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "nicht verfügbar" in text


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


class TestGenreSearchQueryNavF7:
    """NAV-F7 (Navidrome Menu System Audit): nav_search_genres war ein
    STUB - process_search_query() routet 'genres'-Suchen jetzt an
    _process_genre_search_query() (case-insensitiver Teilstring-Filter
    ueber die bereits von handle_browse_genres() genutzte
    getGenres()-Liste, keine eigene Such-API/-Pipeline)."""

    def _make_search_update(self, user_id=111):
        update = make_update(user_id)
        update.message = Mock()
        update.message.reply_text = AsyncMock(return_value=AsyncMock())
        return update

    def test_matches_are_shown_as_genre_buttons(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        user_id = 111
        handler.browse_states[user_id] = {
            "waiting_for_search": True, "search_type": "genres",
        }
        update = self._make_search_update(user_id)
        context = make_context()

        fake_response = {
            "subsonic-response": {
                "genres": {
                    "genre": [
                        {"value": "Hip-Hop", "songCount": 12},
                        {"value": "Pop", "songCount": 5},
                    ]
                }
            }
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            result = asyncio.run(
                handler.process_search_query(update, context, "hip")
            )

        assert result is True
        search_msg = update.message.reply_text.return_value
        kwargs = search_msg.edit_text.call_args[1]
        buttons = {
            b.callback_data
            for row in kwargs["reply_markup"].inline_keyboard
            for b in row
        }
        assert "nav_genre_Hip-Hop" in buttons
        assert "nav_genre_Pop" not in buttons

    def test_no_matches_shows_friendly_message(self):
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        user_id = 111
        handler.browse_states[user_id] = {
            "waiting_for_search": True, "search_type": "genres",
        }
        update = self._make_search_update(user_id)
        context = make_context()

        fake_response = {
            "subsonic-response": {"genres": {"genre": [{"value": "Pop"}]}}
        }

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.process_search_query(update, context, "zzz-nomatch"))

        search_msg = update.message.reply_text.return_value
        sent_text = search_msg.edit_text.call_args[0][0]
        assert "Kein Genre gefunden" in sent_text

    def test_does_not_call_generic_search3(self):
        """Regressionsschutz: die Genre-Suche darf nicht in den
        generischen search3()-Pfad (Artist/Album/Song-Ergebnisse) fallen."""
        handler = NavidromeMenuHandler(FakeConfigConfigured())
        handler.navidrome_api.search = AsyncMock()
        user_id = 111
        handler.browse_states[user_id] = {
            "waiting_for_search": True, "search_type": "genres",
        }
        update = self._make_search_update(user_id)
        context = make_context()

        fake_response = {"subsonic-response": {"genres": {"genre": []}}}

        with patch(
            "handlers.navidrome_menu_handler.asyncio.to_thread",
            new=AsyncMock(return_value=fake_response),
        ):
            asyncio.run(handler.process_search_query(update, context, "pop"))

        handler.navidrome_api.search.assert_not_called()

    def test_connection_error_shown_when_unconfigured(self):
        handler = NavidromeMenuHandler(FakeConfigUnconfigured())
        user_id = 111
        handler.browse_states[user_id] = {
            "waiting_for_search": True, "search_type": "genres",
        }
        update = self._make_search_update(user_id)
        context = make_context()

        with patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request") as mock_request:
            asyncio.run(handler.process_search_query(update, context, "pop"))

        mock_request.assert_not_called()
        update.message.reply_text.assert_awaited_once_with(
            "❌ Keine Verbindung zu Navidrome."
        )


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
