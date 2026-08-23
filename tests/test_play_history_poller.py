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

    def test_api_exception_is_caught_and_returns_false(self, tmp_path):
        poller, _, api = make_poller(tmp_path)
        api.get_now_playing.side_effect = RuntimeError("boom")

        result = asyncio.run(poller.update_play_history())

        assert result is False
