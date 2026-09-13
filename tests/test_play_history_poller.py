"""
Unit-Tests für PlayHistoryPoller (services/statistik/play_history_poller.py)
— extrahiert aus StatistikService (ARCH-003, P-6). navidrome_api wird per
Mock injiziert (Regel 7: externe Services in Unit-Tests faken), repository
ist ein echtes PlayHistoryRepository auf tmp_path (Regel 10-artig: reine
Datei-Logik, kein externer Service).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services.statistik.play_history_poller import PlayHistoryPoller
from services.statistik.play_history_repository import PlayHistoryRepository


def make_poller(tmp_path, navidrome_api=None):
    repo = PlayHistoryRepository(tmp_path, logger=Mock())
    api = navidrome_api or AsyncMock()
    return PlayHistoryPoller(api, repo, logger=Mock()), repo, api


class TestStartStopPolling:
    def test_start_polling_creates_task(self, tmp_path):
        poller, _, _ = make_poller(tmp_path)

        async def scenario():
            poller.start_polling()
            assert poller._polling_task is not None
            await poller.stop_polling()

        asyncio.run(scenario())

    def test_start_polling_twice_does_not_create_second_task(self, tmp_path):
        poller, _, _ = make_poller(tmp_path)

        async def scenario():
            poller.start_polling()
            first_task = poller._polling_task
            poller.start_polling()
            assert poller._polling_task is first_task
            await poller.stop_polling()

        asyncio.run(scenario())

    def test_stop_polling_without_start_is_a_noop(self, tmp_path):
        poller, _, _ = make_poller(tmp_path)
        asyncio.run(poller.stop_polling())
        assert poller._polling_task is None


class TestUpdatePlayHistory:
    def test_no_now_playing_data_returns_false(self, tmp_path):
        poller, _, api = make_poller(tmp_path)
        api.get_now_playing.return_value = []

        result = asyncio.run(poller.update_play_history())

        assert result is False

    def test_valid_entry_is_appended_to_history(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"},
                "user": "alice",
                "player": "web",
            }
        ]

        result = asyncio.run(poller.update_play_history())

        assert result is True
        history = repo.load("alice")
        assert len(history) == 1
        assert history[0]["tracks"][0]["title"] == "Song A"

    def test_entry_without_song_is_skipped(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [{"song": None, "user": "alice"}]

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert repo.load("alice") == []

    def test_entry_with_placeholder_username_is_skipped(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {"title": "Song A", "artist": "X", "id": "1"},
                "user": "Unbekannter Nutzer",
            }
        ]

        result = asyncio.run(poller.update_play_history())

        assert result is False

    def test_same_song_still_playing_is_not_duplicated(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        song = {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"}
        api.get_now_playing.return_value = [
            {"song": song, "user": "alice", "player": "web"}
        ]

        asyncio.run(poller.update_play_history())
        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert len(repo.load("alice")) == 1

    def test_genre_field_is_captured_from_song_info_nav_f8(self, tmp_path):
        """NAV-F8 (Navidrome Menu System Audit): der Wiedergabeverlauf
        erfasste bisher kein 'genre'-Feld, wodurch 'gehoerte Genres nach
        Plays'-Statistiken unmoeglich waren - jetzt wird es aus dem
        bereits vorhandenen Song-Objekt mitgeschrieben."""
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {
                    "title": "Song A", "artist": "Bausa", "album": "Alb",
                    "id": "1", "genre": "Hip-Hop",
                },
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genre"] == "Hip-Hop"

    def test_genre_field_defaults_to_empty_string_when_missing_nav_f8(self, tmp_path):
        """Regressionsschutz: ein Song ohne 'genre'-Feld (Navidrome-
        Bibliothek ohne Genre-Tag) darf nicht crashen, sondern liefert
        einen leeren String (von StatisticsCalculator.generate_genre_stats()
        stillschweigend uebersprungen, nicht als 'Unbekannt' gezaehlt)."""
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {"title": "Song A", "artist": "Bausa", "id": "1"},
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genre"] == ""

    def test_structured_genres_field_is_captured_nav_f8(self, tmp_path):
        """NAV-F8-Nachtrag: das strukturierte 'genres'-Feld (Navidromes
        bevorzugtes Multi-Genre-Format, z.B.
        [{'name': 'Hip Hop'}, {'name': 'Deutschrap'}]) ist die von
        StatisticsCalculator.generate_genre_stats() bevorzugte
        Datenquelle - NICHT ausschliesslich das einfache 'genre'-Feld."""
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {
                    "title": "Song A", "artist": "Bausa", "album": "Alb",
                    "id": "1", "genre": "Hip Hop",
                    "genres": [
                        {"name": "Hip Hop"},
                        {"name": "Deutschrap"},
                        {"name": "Emo Rap"},
                        {"name": "Cloud Rap"},
                    ],
                },
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genres"] == [
            "Hip Hop", "Deutschrap", "Emo Rap", "Cloud Rap",
        ]
        # Das einfache "genre"-Feld bleibt zusaetzlich unveraendert erhalten.
        assert history[0]["tracks"][0]["genre"] == "Hip Hop"

    def test_duplicate_genre_names_within_same_play_are_deduplicated_nav_f8(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {
                    "title": "Song A", "artist": "Bausa", "id": "1",
                    "genres": [
                        {"name": "Hip Hop"},
                        {"name": "Hip Hop"},
                        {"name": "Deutschrap"},
                    ],
                },
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genres"] == ["Hip Hop", "Deutschrap"]

    def test_missing_genres_field_defaults_to_empty_list_nav_f8(self, tmp_path):
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {"title": "Song A", "artist": "Bausa", "id": "1"},
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genres"] == []

    def test_malformed_genres_entries_are_skipped_without_crashing_nav_f8(self, tmp_path):
        """Defensiv gegen abweichende Navidrome-Versionen/-Antworten: ein
        Eintrag ohne 'name'-Schluessel oder kein Dict darf nicht crashen."""
        poller, repo, api = make_poller(tmp_path)
        api.get_now_playing.return_value = [
            {
                "song": {
                    "title": "Song A", "artist": "Bausa", "id": "1",
                    "genres": [{"name": "Hip Hop"}, {"no_name": "x"}, "not-a-dict", {"name": ""}],
                },
                "user": "alice",
                "player": "web",
            }
        ]

        asyncio.run(poller.update_play_history())

        history = repo.load("alice")
        assert history[0]["tracks"][0]["genres"] == ["Hip Hop"]

    def test_api_exception_is_caught_and_returns_false(self, tmp_path):
        poller, _, api = make_poller(tmp_path)
        api.get_now_playing.side_effect = RuntimeError("boom")

        result = asyncio.run(poller.update_play_history())

        assert result is False
