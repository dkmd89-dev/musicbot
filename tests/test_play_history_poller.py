"""
Unit-Tests für PlayHistoryPoller (services/statistik/play_history_poller.py)
— extrahiert aus StatistikService (ARCH-003, P-6).

Der Poller nutzt seit der playCount-Umstellung Navidromes serverseitigen
Zähler als Quelle der Wahrheit: getNowPlaying liefert nur, WELCHE Songs
beobachtet werden, neue History-Einträge entstehen aus dem Anstieg von
getSong(id).playCount gegenüber dem zuletzt gespeicherten Stand. Die erste
Sichtung eines Songs initialisiert nur den Zustand (kein Eintrag).

Externe Dienste sind gefakt (Regel 7): navidrome_api per Mock, der direkte
Subsonic-Client (getSong) per FakeSubsonic. Config und Zustandsverzeichnis
zeigen auf tmp_path, damit kein Test den echten history/-Ordner oder das
Netzwerk berührt. Das Repository ist ein echtes PlayHistoryRepository auf
tmp_path (reine Datei-Logik).
"""

import asyncio
import types
from unittest.mock import AsyncMock, Mock

import pytest

import config as config_module
from services.statistik import play_history_poller as poller_module
from services.statistik.play_history_poller import PlayHistoryPoller
from services.statistik.play_history_repository import PlayHistoryRepository


class FakeSubsonic:
    """Ersetzt _NavidromeSubsonicClient: getSong() liefert vorbereitete Songs."""

    def __init__(self):
        self.songs = {}
        self.calls = []

    def get_song(self, song_id):
        self.calls.append(song_id)
        song = self.songs.get(song_id)
        return dict(song) if song is not None else None


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    history_dir = tmp_path / "user_histories"
    history_dir.mkdir()
    fake_cfg = types.SimpleNamespace(
        NAVIDROME_URL="http://navidrome.invalid",
        NAVIDROME_USER="u",
        NAVIDROME_PASS="p",
        PLAY_HISTORY_FILE=history_dir,
        PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN=3,
    )
    monkeypatch.setattr(config_module, "get_config", lambda: fake_cfg)
    # Der Poller bindet get_config beim Import - dort ebenfalls umbiegen, sonst
    # landen Zustandsdateien im echten history/-Verzeichnis.
    monkeypatch.setattr(poller_module, "get_config", lambda: fake_cfg)
    return fake_cfg


@pytest.fixture
def make_poller(tmp_path, isolated_config):
    def _make(navidrome_api=None):
        repo = PlayHistoryRepository(tmp_path / "user_histories", logger=Mock())
        api = navidrome_api or AsyncMock()
        poller = PlayHistoryPoller(api, repo, logger=Mock())
        subsonic = FakeSubsonic()
        poller._subsonic = subsonic
        return poller, repo, api, subsonic

    return _make


def _play(poller, api, subsonic, song, user="alice", before=1, after=2):
    """Simuliert einen Song, dessen playCount zwischen zwei Poll-Zyklen von
    `before` auf `after` steigt. Gibt das Ergebnis des zweiten Zyklus zurück."""
    api.get_now_playing.return_value = [
        {"song": song, "user": user, "player": "web"}
    ]
    subsonic.songs[song["id"]] = {**song, "playCount": before}
    asyncio.run(poller.update_play_history())  # erste Sichtung: nur State
    subsonic.songs[song["id"]]["playCount"] = after
    return asyncio.run(poller.update_play_history())


class TestStartStopPolling:
    def test_start_polling_creates_task(self, make_poller):
        poller, _, _, _ = make_poller()

        async def scenario():
            poller.start_polling()
            assert poller._polling_task is not None
            await poller.stop_polling()

        asyncio.run(scenario())

    def test_start_polling_twice_does_not_create_second_task(self, make_poller):
        poller, _, _, _ = make_poller()

        async def scenario():
            poller.start_polling()
            first_task = poller._polling_task
            poller.start_polling()
            assert poller._polling_task is first_task
            await poller.stop_polling()

        asyncio.run(scenario())

    def test_stop_polling_without_start_is_a_noop(self, make_poller):
        poller, _, _, _ = make_poller()
        asyncio.run(poller.stop_polling())
        assert poller._polling_task is None


class TestUpdatePlayHistory:
    def test_no_now_playing_data_returns_false(self, make_poller):
        poller, _, api, _ = make_poller()
        api.get_now_playing.return_value = []

        result = asyncio.run(poller.update_play_history())

        assert result is False

    def test_first_sighting_only_initialises_state_without_entry(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"}
        api.get_now_playing.return_value = [
            {"song": song, "user": "alice", "player": "web"}
        ]
        subsonic.songs["1"] = {**song, "playCount": 5}

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert repo.load("alice") == []
        assert poller._state_path("alice").exists()

    def test_valid_entry_is_appended_when_playcount_increases(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"}

        result = _play(poller, api, subsonic, song, before=5, after=6)

        assert result is True
        history = repo.load("alice")
        assert len(history) == 1
        assert history[0]["tracks"][0]["title"] == "Song A"
        assert history[0]["tracks"][0]["username"] == "alice"

    def test_repeat_increases_playcount_by_more_than_one_creates_multiple_entries(
        self, make_poller
    ):
        """Kernvorteil der playCount-Quelle: Repeat/mehrfache Starts zwischen
        zwei Polls werden vollständig erfasst."""
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"}

        _play(poller, api, subsonic, song, before=5, after=8)

        assert len(repo.load("alice")) == 3

    def test_unchanged_playcount_creates_no_duplicate(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "album": "Alb", "id": "1"}
        _play(poller, api, subsonic, song, before=5, after=6)

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert len(repo.load("alice")) == 1

    def test_song_without_playcount_is_ignored(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "id": "1"}
        api.get_now_playing.return_value = [
            {"song": song, "user": "alice", "player": "web"}
        ]
        subsonic.songs["1"] = dict(song)  # kein playCount-Feld

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert repo.load("alice") == []

    def test_entry_without_song_is_skipped(self, make_poller):
        poller, repo, api, _ = make_poller()
        api.get_now_playing.return_value = [{"song": None, "user": "alice"}]

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert repo.load("alice") == []

    def test_entry_with_placeholder_username_is_skipped(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "X", "id": "1"}
        api.get_now_playing.return_value = [
            {"song": song, "user": "Unbekannter Nutzer"}
        ]
        subsonic.songs["1"] = {**song, "playCount": 3}

        result = asyncio.run(poller.update_play_history())

        assert result is False
        assert subsonic.calls == []

    def test_genre_field_is_captured_from_song_info_nav_f8(self, make_poller):
        """NAV-F8: der Wiedergabeverlauf erfasst das 'genre'-Feld, damit
        'gehörte Genres nach Plays'-Statistiken möglich sind."""
        poller, repo, api, subsonic = make_poller()
        song = {
            "title": "Song A", "artist": "Bausa", "album": "Alb",
            "id": "1", "genre": "Hip-Hop",
        }

        _play(poller, api, subsonic, song)

        assert repo.load("alice")[0]["tracks"][0]["genre"] == "Hip-Hop"

    def test_genre_field_defaults_to_empty_string_when_missing_nav_f8(self, make_poller):
        """Ein Song ohne 'genre'-Feld darf nicht crashen, sondern liefert einen
        leeren String (von generate_genre_stats() übersprungen)."""
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "id": "1"}

        _play(poller, api, subsonic, song)

        assert repo.load("alice")[0]["tracks"][0]["genre"] == ""

    def test_structured_genres_field_is_captured_nav_f8(self, make_poller):
        """Das strukturierte 'genres'-Feld (Navidromes Multi-Genre-Format) ist
        die von generate_genre_stats() bevorzugte Datenquelle; das einfache
        'genre'-Feld bleibt zusätzlich erhalten."""
        poller, repo, api, subsonic = make_poller()
        song = {
            "title": "Song A", "artist": "Bausa", "album": "Alb",
            "id": "1", "genre": "Hip Hop",
            "genres": [
                {"name": "Hip Hop"},
                {"name": "Deutschrap"},
                {"name": "Emo Rap"},
                {"name": "Cloud Rap"},
            ],
        }

        _play(poller, api, subsonic, song)

        track = repo.load("alice")[0]["tracks"][0]
        assert track["genres"] == ["Hip Hop", "Deutschrap", "Emo Rap", "Cloud Rap"]
        assert track["genre"] == "Hip Hop"

    def test_duplicate_genre_names_within_same_play_are_deduplicated_nav_f8(
        self, make_poller
    ):
        poller, repo, api, subsonic = make_poller()
        song = {
            "title": "Song A", "artist": "Bausa", "id": "1",
            "genres": [{"name": "Hip Hop"}, {"name": "Hip Hop"}, {"name": "Deutschrap"}],
        }

        _play(poller, api, subsonic, song)

        assert repo.load("alice")[0]["tracks"][0]["genres"] == ["Hip Hop", "Deutschrap"]

    def test_missing_genres_field_defaults_to_empty_list_nav_f8(self, make_poller):
        poller, repo, api, subsonic = make_poller()
        song = {"title": "Song A", "artist": "Bausa", "id": "1"}

        _play(poller, api, subsonic, song)

        assert repo.load("alice")[0]["tracks"][0]["genres"] == []

    def test_malformed_genres_entries_are_skipped_without_crashing_nav_f8(
        self, make_poller
    ):
        """Defensiv gegen abweichende Navidrome-Versionen/-Antworten."""
        poller, repo, api, subsonic = make_poller()
        song = {
            "title": "Song A", "artist": "Bausa", "id": "1",
            "genres": [{"name": "Hip Hop"}, {"no_name": "x"}, "not-a-dict", {"name": ""}],
        }

        _play(poller, api, subsonic, song)

        assert repo.load("alice")[0]["tracks"][0]["genres"] == ["Hip Hop"]

    def test_api_exception_is_caught_and_returns_false(self, make_poller):
        poller, _, api, _ = make_poller()
        api.get_now_playing.side_effect = RuntimeError("boom")

        result = asyncio.run(poller.update_play_history())

        assert result is False
