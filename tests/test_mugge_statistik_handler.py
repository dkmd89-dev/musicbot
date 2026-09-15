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
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from telegram.constants import ParseMode

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


class TestTruncate:
    """Statistics Menu UX & Output Optimization: 'lange Namen'."""

    def test_short_text_is_unchanged(self):
        handler = _make_handler()
        assert handler._truncate("Song A") == "Song A"

    def test_long_text_is_truncated_with_ellipsis(self):
        handler = _make_handler()
        long_title = "A" * 80
        result = handler._truncate(long_title, max_len=45)
        assert len(result) == 45
        assert result.endswith("…")

    def test_exactly_max_len_is_unchanged(self):
        handler = _make_handler()
        text = "A" * 45
        assert handler._truncate(text, max_len=45) == text

    def test_none_becomes_empty_string(self):
        handler = _make_handler()
        assert handler._truncate(None) == ""


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
        """MASTER FIX (Rankings Closure): nutzt jetzt top_songs_detailed
        (Titel + vollständiger Artist-String getrennt) statt des alten
        kombinierten top_songs-Strings."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs_detailed": [
                ("Song A", "Artist A", 10),
                ("Song B", "Artist B", 5),
            ],
            "total_plays": 15,
        }

        update = make_update(111)
        context = Mock()

        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        msg_mock.edit_text.assert_called_once()
        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Song A" in sent_text and "Artist A" in sent_text
        assert "Song B" in sent_text and "Artist B" in sent_text
        assert "15" in sent_text

    def test_no_truncation_of_long_song_or_artist_names(self, tmp_path):
        """MASTER FIX (Rankings Closure), Abschnitt 2/5A: kein _truncate(),
        kein '…'/'...' mehr - vollständige Titel/Artist-Werte, Telegram
        darf normal umbrechen (identisch zur Wochen-/Monatsstatistik-UX)."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        long_title = "Der Letzte Song (ReBoot Live Concerts) - Ein sehr langer Titel"
        long_artists = "Toobrokeforfiji • makko • Beslik Meister • Ein vierter Artist"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs_detailed": [(long_title, long_artists, 3)],
            "total_plays": 3,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert long_title in sent_text
        assert long_artists in sent_text
        assert "…" not in sent_text
        assert "..." not in sent_text

    def test_medals_and_play_pluralization_used(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs_detailed": [
                ("Song A", "Artist A", 1),
                ("Song B", "Artist B", 2),
                ("Song C", "Artist C", 2),
                ("Song D", "Artist D", 1),
            ],
            "total_plays": 6,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🥇" in sent_text and "🥈" in sent_text and "🥉" in sent_text
        assert "4." in sent_text
        assert "1 Play" in sent_text
        assert "1 Plays" not in sent_text

    def test_no_png_chart_is_sent_anymore(self, tmp_path):
        """Statistics Menu UX & Output Optimization: 'PNG-Charts
        entfernen' - reply_photo() darf nicht mehr aufgerufen werden."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs_detailed": [("Song A", "Artist A", 10)],
            "total_plays": 10,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        update.message.reply_photo.assert_not_called()
        handler.statistik_service.create_chart.assert_not_called()

    def test_empty_period_shows_friendly_message_not_generic_error(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_songs_detailed": [],
            "top_artists_split": [],
            "total_plays": 0,
            "period_start": None,
            "period_end": None,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_songs(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Noch keine Wiedergaben in diesem Zeitraum" in sent_text


class TestHandleTopArtists:
    """Bisher 0 dedizierte Tests trotz eigenständiger Handler-Methode."""

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
            asyncio.run(handler.handle_top_artists(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Künstler-Daten" in sent_text

    def test_stats_with_artists_are_formatted_and_sent(self, tmp_path):
        """MASTER FIX (Rankings Closure): nutzt jetzt top_artists_split
        (bereits _split_artists()-aggregiert) statt des alten kombinierten
        top_artists-Strings."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_artists_split": [("Artist A", 10), ("Artist B", 5)],
            "total_plays": 15,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_artists(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Artist A" in sent_text
        assert "Artist B" in sent_text
        assert "15" in sent_text

    def test_multi_artist_combo_strings_are_split_into_separate_rankings(self, tmp_path):
        """MASTER FIX (Rankings Closure), Abschnitt 3/5B: 'makko &
        toobrokeforfiji' und 'Clueso • Mathea' erscheinen als getrennte
        Ranking-Einträge, weil generate_stats() top_artists_split bereits
        über StatisticsCalculator._split_artists() aggregiert liefert -
        der Handler splittet hier nichts selbst, sondern konsumiert nur
        das bereits korrekt aufgeschlüsselte Feld."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_artists_split": [
                ("makko", 15),
                ("toobrokeforfiji", 4),
                ("Clueso", 10),
                ("Mathea", 3),
            ],
            "total_plays": 32,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_artists(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "makko & toobrokeforfiji" not in sent_text
        assert "Clueso • Mathea" not in sent_text
        for name in ("makko", "toobrokeforfiji", "Clueso", "Mathea"):
            assert name in sent_text

    def test_no_truncation_of_long_artist_names(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        long_artist = "Toobrokeforfiji Und Ein Sehr Langer Zusatzname Der Nicht Gekuerzt Wird"
        handler.statistik_service.generate_stats.return_value = {
            "top_artists_split": [(long_artist, 2)],
            "total_plays": 2,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_artists(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert long_artist in sent_text
        assert "…" not in sent_text
        assert "..." not in sent_text

    def test_no_png_chart_is_sent_anymore(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_artists_split": [("Artist A", 10)],
            "total_plays": 10,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_artists(update, context))

        update.message.reply_photo.assert_not_called()
        handler.statistik_service.create_chart.assert_not_called()

    def test_empty_period_shows_friendly_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_stats.return_value = {
            "top_artists_split": [],
            "total_plays": 0,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_top_artists(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Noch keine Wiedergaben in diesem Zeitraum" in sent_text


class TestHandleGenreStats:
    """NAV-F8 (Navidrome Menu System Audit): reine
    'nav_genre_stats'-Delegation an StatistikService.generate_genre_stats()
    - kein neues eigenes Datenmodell hier, reine Presentation."""

    def test_no_stats_shows_no_data_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_genre_stats.return_value = None

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_genre_stats(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Daten" in sent_text

    def test_genres_are_formatted_descending_with_ranks(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_genre_stats.return_value = {
            "navidrome_username": "robin",
            "top_genres": [("Hip-Hop", 10), ("Pop", 5)],
            "total_plays_with_genre": 15,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_genre_stats(update, context))

        msg_mock.edit_text.assert_called_once()
        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Hip-Hop" in sent_text and "Pop" in sent_text
        assert "🥇" in sent_text and "🥈" in sent_text
        assert "15" in sent_text
        assert sent_text.index("Hip-Hop") < sent_text.index("Pop")

    def test_empty_genres_shows_friendly_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_genre_stats.return_value = {
            "navidrome_username": "robin",
            "top_genres": [],
            "total_plays_with_genre": 0,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_genre_stats(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Noch keine Wiedergaben mit Genre-Angabe" in sent_text

    def test_back_button_points_to_navidrome_menu(self, tmp_path):
        """Eigener 'Zurück'-Button statt ARCH-029-nav_markup (nav_genre_stats
        ist kein registriertes MenuItem, siehe handle_genre_stats()-Docstring)."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_genre_stats.return_value = {
            "navidrome_username": "robin",
            "top_genres": [("Pop", 1)],
            "total_plays_with_genre": 1,
        }

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_genre_stats(update, context))

        _, kwargs = msg_mock.edit_text.call_args
        keyboard = kwargs["reply_markup"].inline_keyboard
        assert keyboard[0][0].callback_data == "menu:navidrome"


def _dna(**over):
    base = {
        "navidrome_username": "robin",
        "total_plays": 10,
        "unique_songs": 6,
        "top_genres_pct": [("Hip-Hop", 66.7), ("Pop", 33.3)],
        "top_artists_pct": [("Clueso", 40.0), ("Bausa", 20.0)],
        "time_of_day_pct": {"morgens": 10.0, "nachmittags": 20.0, "abends": 50.0, "nachts": 20.0},
        "repeat_rate_pct": 40.0,
    }
    base.update(over)
    return base


class TestHandleMusicDna:
    """Music DNA v1: reine Presentation über
    StatistikService.generate_music_dna() - identisches Testmuster wie
    TestHandleGenreStats oben."""

    def test_no_data_shows_no_data_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.return_value = None

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Daten" in sent_text

    def test_zero_plays_shows_friendly_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.return_value = _dna(
            total_plays=0, unique_songs=0, top_genres_pct=[], top_artists_pct=[],
            time_of_day_pct={"morgens": 0.0, "nachmittags": 0.0, "abends": 0.0, "nachts": 0.0},
            repeat_rate_pct=0.0,
        )

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Noch keine Wiedergaben" in sent_text

    def test_profile_contains_all_dimensions(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.return_value = _dna()

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context))

        msg_mock.edit_text.assert_called_once()
        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Hip-Hop" in sent_text and "66.7%" in sent_text
        assert "Clueso" in sent_text and "40.0%" in sent_text
        assert "Morgens" in sent_text and "10.0%" in sent_text
        assert "Abends" in sent_text and "50.0%" in sent_text
        assert "Repeat-Rate" in sent_text and "40.0%" in sent_text
        assert "10" in sent_text  # total_plays
        assert "6" in sent_text  # unique_songs

    def test_no_genre_data_omits_genre_section_without_crashing(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.return_value = _dna(top_genres_pct=[])

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🎤 Genres" not in sent_text

    def test_reply_markup_passed_through_arch029_style(self, tmp_path):
        """ARCH-029: Music DNA ist (anders als genre_stats) ein echtes
        MenuItem und nutzt daher den nav_markup-Passthrough statt eines
        eigenen Zurück-Buttons."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.return_value = _dna()

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)
        fake_markup = Mock()

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context, reply_markup=fake_markup))

        _, kwargs = msg_mock.edit_text.call_args
        assert kwargs["reply_markup"] is fake_markup

    def test_exception_shows_error_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.generate_music_dna.side_effect = RuntimeError("boom")

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(handler.handle_music_dna(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Fehler" in sent_text and "boom" in sent_text


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

    def test_reply_markup_is_attached_when_provided_nav_f10(self, tmp_path):
        """NAV-F10 (Navidrome Menu System Audit): reply_markup additiv/
        optional, an den terminalen edit_text()-Aufruf angehängt - schließt
        den in ARCH-029 übersehenen Dead-End für 'Zuletzt gespielt'."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        handler.statistik_service.get_last_played_song.return_value = {
            "title": "Some Title",
            "artist": "Some Artist",
            "album": "Some Album",
            "timestamp": "2026-01-15T12:30:00",
        }
        sentinel_markup = Mock(name="nav_markup")

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
            mock_get_config.return_value.NAVIDROME_USER = "robin"
            asyncio.run(
                handler.handle_last_played(
                    update, context, reply_markup=sentinel_markup
                )
            )

        _, kwargs = msg_mock.edit_text.call_args
        assert kwargs.get("reply_markup") is sentinel_markup


class TestHandleLibraryOverview:
    """Phase 3, P1.1 — Library-Statistics-Ansicht aus dem Health-Report."""

    def _fake_report(self, **overrides):
        report = {
            "scan": {"completed_at": "2026-01-01T00:00:00+00:00"},
            "statistics": {
                "total_files": 388,
                "total_artists": 12,
                "total_albums": 34,
                "genre_distribution": {"Pop": 5, "Hip-Hop": 15},
            },
            "health": {"score": 98.0, "status": "EXCELLENT"},
        }
        report.update(overrides)
        return report

    def test_missing_report_shows_hint_to_run_scan(self, tmp_path):
        handler = _make_handler()
        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch(
            "handlers.mugge_statistik_handler.Config.DATA_DIR", tmp_path
        ):
            asyncio.run(handler.handle_library_overview(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "kein Library-Health-Report" in sent_text
        assert "library_health_check.py" in sent_text

    def test_valid_report_shows_counts_genres_and_age(self, tmp_path):
        handler = _make_handler()
        report_path = tmp_path / "library_health_report.json"
        report_path.write_text(
            json.dumps(self._fake_report()), encoding="utf-8"
        )

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch(
            "handlers.mugge_statistik_handler.Config.DATA_DIR", tmp_path
        ):
            asyncio.run(handler.handle_library_overview(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "388" in sent_text
        assert "34" in sent_text
        assert "12" in sent_text
        assert "Hip-Hop" in sent_text
        assert "98.0" in sent_text
        assert "2026-01-01T00:00:00+00:00" in sent_text  # Report-Alter sichtbar

    def test_corrupt_report_shows_warning_not_crash(self, tmp_path):
        handler = _make_handler()
        report_path = tmp_path / "library_health_report.json"
        report_path.write_text("{not valid json", encoding="utf-8")

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch(
            "handlers.mugge_statistik_handler.Config.DATA_DIR", tmp_path
        ):
            asyncio.run(handler.handle_library_overview(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "unlesbar" in sent_text or "unvollständig" in sent_text

    def test_missing_genre_distribution_key_does_not_crash(self, tmp_path):
        """Aeltere Reports (vor P1.1) haben noch kein genre_distribution."""
        handler = _make_handler()
        report = self._fake_report()
        del report["statistics"]["genre_distribution"]
        report_path = tmp_path / "library_health_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        update = make_update(111)
        context = Mock()
        msg_mock = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch(
            "handlers.mugge_statistik_handler.Config.DATA_DIR", tmp_path
        ):
            asyncio.run(handler.handle_library_overview(update, context))

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "keine Daten" in sent_text


def _run_period_handler(handler, method_name, generate_stats_return):
    handler.statistik_service.generate_stats.return_value = generate_stats_return

    update = make_update(111)
    context = Mock()
    msg_mock = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=msg_mock)

    with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
        mock_get_config.return_value.NAVIDROME_USER = "robin"
        asyncio.run(getattr(handler, method_name)(update, context))

    return msg_mock, update


def _run_year_handler(handler, generate_year_stats_return):
    handler.statistik_service.generate_year_stats.return_value = generate_year_stats_return

    update = make_update(111)
    context = Mock()
    msg_mock = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=msg_mock)

    with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
        mock_get_config.return_value.NAVIDROME_USER = "robin"
        asyncio.run(handler.handle_year_review(update, context))

    return msg_mock, update


def _period_stats(period_start, period_end, total_plays=3):
    return {
        "period_start": period_start,
        "period_end": period_end,
        "total_plays": total_plays,
        "top_songs_detailed": (
            [("Song A", "Artist A", total_plays)] if total_plays else []
        ),
        "top_artists_split": (
            [("Artist A", total_plays)] if total_plays else []
        ),
    }


class TestFormatPlays:
    def test_singular(self):
        handler = _make_handler()
        assert handler._format_plays(1) == "1 Play"

    def test_plural(self):
        handler = _make_handler()
        assert handler._format_plays(2) == "2 Plays"
        assert handler._format_plays(0) == "0 Plays"


class TestFormatRank:
    def test_medals_for_top_three(self):
        handler = _make_handler()
        assert handler._format_rank(1) == "🥇"
        assert handler._format_rank(2) == "🥈"
        assert handler._format_rank(3) == "🥉"

    def test_plain_numbering_from_rank_four(self):
        handler = _make_handler()
        assert handler._format_rank(4) == "4."
        assert handler._format_rank(5) == "5."


class TestFormatDateRange:
    def test_week_within_same_month(self):
        handler = _make_handler()
        result = handler._format_date_range(
            datetime(2026, 9, 7), datetime(2026, 9, 14)
        )
        assert result == "07.–13.09.2026"

    def test_month_range(self):
        handler = _make_handler()
        result = handler._format_date_range(
            datetime(2026, 9, 1), datetime(2026, 10, 1)
        )
        assert result == "01.–30.09.2026"

    def test_week_spanning_month_change(self):
        handler = _make_handler()
        result = handler._format_date_range(
            datetime(2026, 9, 28), datetime(2026, 10, 5)
        )
        assert result == "28.09.–04.10.2026"

    def test_week_spanning_year_change(self):
        handler = _make_handler()
        result = handler._format_date_range(
            datetime(2026, 12, 28), datetime(2027, 1, 4)
        )
        assert result == "28.12.2026–03.01.2027"


class TestHandleWeekReview:
    """Statistics UX & Architecture (v Final): 'Diese Woche' im neuen
    Layout (Datumsbereich, top_songs_detailed/top_artists_split,
    _format_plays(), keine Alben, keine PNG-Charts, kein _truncate())."""

    def test_no_stats_shows_no_data_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", None)

        assert "Keine Daten" in msg_mock.edit_text.call_args[0][0]

    def test_calls_generate_stats_with_week_period(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        _run_period_handler(handler, "handle_week_review", None)

        _, kwargs = handler.statistik_service.generate_stats.call_args
        assert kwargs.get("period") == "week"

    def test_header_shows_week_date_range(self, tmp_path):
        """Master-Prompt Abschnitt 12: inklusiver Datumsbereich aus dem
        exklusiven period_end."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "07.–13.09.2026" in sent_text
        assert "30 Tage" not in sent_text
        assert "📊 Wochenstatistik · robin" in sent_text

    def test_song_card_shows_title_artists_and_plays(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))
        stats["top_songs_detailed"] = [
            ("Inundauswendig", "makko • The Chainsmokers", 2),
        ]

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🥇 Inundauswendig" in sent_text
        assert "makko • The Chainsmokers · 2 Plays" in sent_text

    def test_singular_play_formatting(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))
        stats["top_songs_detailed"] = [("Song A", "Artist A", 1)]

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "1 Play" in sent_text
        assert "1 Plays" not in sent_text

    def test_no_albums_section_anymore(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Alben" not in sent_text

    def test_no_png_chart_is_sent_anymore(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))

        msg_mock, update = _run_period_handler(handler, "handle_week_review", stats)

        update.message.reply_photo.assert_not_called()
        handler.statistik_service.create_chart.assert_not_called()

    def test_no_truncation_of_long_names(self, tmp_path):
        """Master-Prompt Abschnitt 11: KEIN _truncate() im neuen Layout."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        long_title = "A" * 80
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))
        stats["top_songs_detailed"] = [(long_title, "Artist A", 1)]

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert long_title in sent_text
        assert "…" not in sent_text

    def test_fewer_than_five_songs_no_placeholders(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14))
        stats["top_songs_detailed"] = [("Only Song", "Artist A", 1)]

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        songs_section = msg_mock.edit_text.call_args[0][0].split("Top 5 Songs")[1].split(
            "Top 5 Künstler"
        )[0]
        assert songs_section.count("🥇") == 1
        assert "🥈" not in songs_section

    def test_empty_period_shows_friendly_calendar_aware_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 7), datetime(2026, 9, 14), total_plays=0)

        msg_mock, _ = _run_period_handler(handler, "handle_week_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "07.–13.09.2026" in sent_text
        assert "Noch keine Wiedergaben in diesem Zeitraum" in sent_text


class TestHandleMonthReview:
    def test_header_shows_month_date_range(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = _period_stats(datetime(2026, 9, 1), datetime(2026, 10, 1))

        msg_mock, _ = _run_period_handler(handler, "handle_month_review", stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "01.–30.09.2026" in sent_text
        assert "30 Tage" not in sent_text
        assert "📊 Monatsstatistik · robin" in sent_text

    def test_calls_generate_stats_with_month_period(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        _run_period_handler(handler, "handle_month_review", None)

        _, kwargs = handler.statistik_service.generate_stats.call_args
        assert kwargs.get("period") == "month"


class TestHandleYearReview:
    """Statistics UX & Architecture (v Final), Abschnitt 14/22/24: eigener
    Annual-Renderer mit KPIs, Jahres-Highlight, Monatsdiagramm."""

    def _year_stats(self, **overrides):
        stats = {
            "year": 2026,
            "period_start": datetime(2026, 1, 1),
            "period_end": datetime(2027, 1, 1),
            "total_plays": 10,
            "total_songs": 8,
            "total_artists": 5,
            "total_albums": 3,
            "monthly_plays": [
                ("Januar", 0), ("Februar", 0), ("März", 0), ("April", 0),
                ("Mai", 0), ("Juni", 0), ("Juli", 10), ("August", 0),
                ("September", 0), ("Oktober", 0), ("November", 0), ("Dezember", 0),
            ],
            "highlights": {
                "strongest_month": {"name": "Juli", "plays": 10, "delta_pct": 18},
            },
            "top_songs_detailed": [("Song A", "Artist A", 4)],
            "top_artists_split": [("Artist A", 4)],
        }
        stats.update(overrides)
        return stats

    def test_no_stats_shows_no_data_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, None)

        assert "Keine Daten" in msg_mock.edit_text.call_args[0][0]

    def test_calls_generate_year_stats_not_generate_stats(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        _run_year_handler(handler, None)

        handler.statistik_service.generate_year_stats.assert_called_once()
        handler.statistik_service.generate_stats.assert_not_called()

    def test_uses_html_parse_mode_for_code_block(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        _, kwargs = msg_mock.edit_text.call_args
        assert kwargs.get("parse_mode") == ParseMode.HTML

    def test_kpis_are_shown(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🎧 10 Plays" in sent_text
        assert "🎵 8 Songs" in sent_text
        assert "👑 5 Künstler" in sent_text
        assert "💿 3 Alben" in sent_text

    def test_date_range_is_full_year(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "01.–31.12.2026" in sent_text

    def test_highlight_with_delta_shown(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🔥 Stärkster Monat" in sent_text
        assert "Juli · 18 % über Monatsdurchschnitt" in sent_text

    def test_highlight_without_delta_shows_no_play_count(self, tmp_path):
        """Master-Prompt Abschnitt 21: im None-Fall keine Play-Zahl
        ergänzen."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = self._year_stats()
        stats["highlights"]["strongest_month"]["delta_pct"] = None

        msg_mock, _ = _run_year_handler(handler, stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🔥 Stärkster Monat\nJuli" in sent_text
        assert "%" not in sent_text.split("🔥 Stärkster Monat")[1].split("\n\n")[0]

    def test_monthly_chart_is_wrapped_in_code_block(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "<code>" in sent_text
        assert "</code>" in sent_text
        code_block = sent_text.split("<code>")[1].split("</code>")[0]
        assert "Juli" in code_block
        assert "Dezember" in code_block

    def test_html_special_characters_in_names_are_escaped(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = self._year_stats()
        stats["top_songs_detailed"] = [("<script>Song</script>", "Artist A", 4)]

        msg_mock, _ = _run_year_handler(handler, stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "<script>" not in sent_text
        assert "&lt;script&gt;" in sent_text

    def test_top_songs_and_artists_shown_single_line(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_year_handler(handler, self._year_stats())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🥇 Song A · 4 Plays" in sent_text
        assert "🥇 Artist A · 4 Plays" in sent_text

    def test_empty_year_shows_friendly_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        stats = self._year_stats(total_plays=0)

        msg_mock, _ = _run_year_handler(handler, stats)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Noch keine Wiedergaben in diesem Jahr" in sent_text

    def test_no_png_chart_is_sent(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, update = _run_year_handler(handler, self._year_stats())

        update.message.reply_photo.assert_not_called()
        handler.statistik_service.create_chart.assert_not_called()


def _run_timeline_handler(handler, timeline_return):
    handler.statistik_service.generate_timeline_stats.return_value = timeline_return

    update = make_update(111)
    context = Mock()
    msg_mock = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=msg_mock)

    with patch("handlers.mugge_statistik_handler.get_config") as mock_get_config:
        mock_get_config.return_value.NAVIDROME_USER = "robin"
        asyncio.run(handler.handle_music_timeline(update, context))

    return msg_mock, update


class TestHandleMusicTimelineLayout:
    """MASTER PHASE — MUSIC TIMELINE — FINAL CLOSURE: Timeline zeigt
    ausschließlich den aktuellen Tag als kompakte Daily-Music-Übersicht.
    Ersetzt die vorherige Heute/Woche/Monat-Testklasse (kein
    "periods"-Wrapper mehr im Service-Return, siehe
    StatisticsCalculator.generate_timeline_stats())."""

    def _fake_timeline(self, **today_overrides):
        today = {
            "period_start": datetime(2026, 9, 13),
            "period_end": datetime(2026, 9, 14),
            "track_count": 24,
            "listening_seconds": 3600,
            "top_artist": ("Clueso", 6),
            "top_album": ("Stadtrandlichter", 6),
            "top_genre": ("Hip-Hop", 8),
            "most_replayed_track": ("Mit dir alleine sein", 4),
            "new_track_count": 18,
        }
        today.update(today_overrides)
        return {"navidrome_username": "robin", "today": today}

    def test_header_uses_heute_date_format(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text.startswith("📅 Heute · 13.09.2026")

    def test_footer_shows_username(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text.rstrip().splitlines()[-1] == "👤 robin"

    def test_exact_final_output_for_full_data(self, tmp_path):
        """Section 13/31: die verbindliche Standardausgabe."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text == (
            "📅 Heute · 13.09.2026\n"
            "\n"
            "🎧 24 Plays\n"
            "🔥 Clueso · 6 Plays\n"
            "💿 Stadtrandlichter · 6 Plays\n"
            "🎸 Hip-Hop · 8 Plays\n"
            "❤️ Mit dir alleine sein\n"
            "✨ 18 neue Tracks entdeckt\n"
            "\n"
            "👤 robin"
        )

    def test_most_replayed_track_shows_no_plays_count(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "❤️ Mit dir alleine sein" in sent_text
        assert "Mit dir alleine sein · 4 Plays" not in sent_text
        assert "Meistgehört" not in sent_text

    def test_no_separator_line(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "─" not in sent_text

    def test_no_week_or_month_content(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Diese Woche" not in sent_text
        assert "Diesen Monat" not in sent_text

    def test_no_duration_line(self, tmp_path):
        """Verbindliche Endausgabe (Section 13/14) enthält keine
        Hörzeit-Zeile mehr - listening_seconds bleibt intern vorhanden,
        wird aber nicht mehr gerendert."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, self._fake_timeline())

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "⏱️" not in sent_text

    def test_no_truncation_of_long_names(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        long_artist = "A" * 80
        timeline = self._fake_timeline(top_artist=(long_artist, 9))

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert long_artist in sent_text
        assert "…" not in sent_text

    def test_singular_play_uses_format_plays_helper(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(track_count=1)

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🎧 1 Play" in sent_text
        assert "🎧 1 Plays" not in sent_text

    def test_missing_artist_line_omitted(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(top_artist=None)

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🔥" not in sent_text
        assert "💿 Stadtrandlichter · 6 Plays" in sent_text
        assert "✨ 18 neue Tracks entdeckt" in sent_text

    def test_missing_album_line_omitted(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(top_album=None)

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "💿" not in sent_text
        assert "🔥 Clueso · 6 Plays" in sent_text

    def test_missing_genre_line_omitted(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(top_genre=None)

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "🎸" not in sent_text
        assert "❤️ Mit dir alleine sein" in sent_text

    def test_missing_most_replayed_track_line_omitted(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(most_replayed_track=None)

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "❤️" not in sent_text
        assert "✨ 18 neue Tracks entdeckt" in sent_text

    def test_no_placeholder_values_for_missing_fields(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(
            top_artist=None, top_album=None, top_genre=None
        )

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        for placeholder in ("N/A", "Unknown", "Keine Daten", " - \n"):
            assert placeholder not in sent_text

    def test_empty_state_shows_exact_message(self, tmp_path):
        """Section 16: exakte Empty-State-Ausgabe bei 0 Wiedergaben
        heute, keine "0 Plays"-Zeilen, keine Platzhalter."""
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"
        timeline = self._fake_timeline(
            track_count=0,
            listening_seconds=0,
            top_artist=None,
            top_album=None,
            top_genre=None,
            most_replayed_track=None,
            new_track_count=0,
        )

        msg_mock, _ = _run_timeline_handler(handler, timeline)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert sent_text == (
            "📅 Heute · 13.09.2026\n"
            "\n"
            "Keine Wiedergaben heute\n"
            "\n"
            "👤 robin"
        )
        assert "0 Plays" not in sent_text
        assert "🎧" not in sent_text

    def test_no_data_shows_generic_message(self, tmp_path):
        handler = _make_handler()
        handler.user_data_file = tmp_path / "does_not_exist.json"

        msg_mock, _ = _run_timeline_handler(handler, None)

        sent_text = msg_mock.edit_text.call_args[0][0]
        assert "Keine Daten" in sent_text
