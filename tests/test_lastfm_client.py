"""
Characterization-Tests fuer klassen/lastfm_client.py (LastFMClient).

Last.fm ist Teil der Genre-Fallback-Kette (siehe GENRE-003-Eintrag in der
Baseline: "MusicBrainz/Last.fm/Feature-Inferenz-Fallbacks") und hatte vor
dieser Session keinerlei Testabdeckung.

pylast wird komplett gemockt (Regel 7 - externe Dienste in Unit-Tests
nicht real ansprechen). GenreMapper wird als Mock injiziert statt real
konstruiert - GenreMapper erbt von SingletonMixin, LastFMClient.__init__
ruft es ohne Argumente auf (GenreMapper()), was bei einer bereits
initialisierten Singleton-Instanz schlicht die bestehende Instanz
zurueckgibt (kein Risiko wie bei der fruehreren ArtistNormalizer-
Inzidenz, da GenreMapper rein lesend ist - keine Auto-Learning-Schreib-
zugriffe wie ArtistNormalizer). Die Injektion macht die Tests trotzdem
unabhaengig vom Inhalt der echten mapping/-Dateien.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from klassen.lastfm_client import LastFMClient


def _make_tag(name):
    tag_item = MagicMock()
    tag_item.get_name.return_value = name
    tag_wrapper = MagicMock()
    tag_wrapper.item = tag_item
    return tag_wrapper


def _make_client(genremapper=None, lastfm_timeout=10):
    with patch("klassen.lastfm_client.pylast.LastFMNetwork") as mock_network_cls:
        with patch("klassen.lastfm_client.Config") as mock_config_cls:
            mock_config_cls.return_value.LASTFM_API_KEY = "fake-key"
            mock_config_cls.return_value.LASTFM_API_SECRET = "fake-secret"
            mock_config_cls.LASTFM_TIMEOUT = lastfm_timeout
            with patch("klassen.lastfm_client.GenreMapper", return_value=genremapper or MagicMock()):
                client = LastFMClient()
    return client, mock_network_cls.return_value


class TestGetLastfmData:
    def test_artist_not_found_returns_none_and_empty_tags(self):
        client, network = _make_client()
        network.get_artist.return_value = None

        track_info, tags = client._get_lastfm_data("Some Title", "Some Artist")
        assert track_info is None
        assert tags == []

    def test_combines_artist_and_track_tags_deduplicated(self):
        client, network = _make_client()

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = [_make_tag("Hip Hop"), _make_tag("Rap")]
        network.get_artist.return_value = artist_obj

        track_obj = MagicMock()
        track_obj.get_top_tags.return_value = [_make_tag("Rap"), _make_tag("Trap")]
        network.get_track.return_value = track_obj

        track_info, tags = client._get_lastfm_data("Some Title", "Some Artist")

        assert track_info is not None
        # Artist-Tags zuerst, Duplikate (rap kommt in beiden vor) nur einmal
        assert tags == ["hip hop", "rap", "trap"]

    def test_artist_tag_fetch_failure_does_not_abort_whole_lookup(self):
        client, network = _make_client()

        artist_obj = MagicMock()
        artist_obj.get_top_tags.side_effect = RuntimeError("lastfm down")
        network.get_artist.return_value = artist_obj

        track_obj = MagicMock()
        track_obj.get_top_tags.return_value = [_make_tag("Pop")]
        network.get_track.return_value = track_obj

        track_info, tags = client._get_lastfm_data("Some Title", "Some Artist")

        assert track_info is not None
        assert tags == ["pop"]

    def test_track_lookup_failure_still_returns_artist_tags(self):
        client, network = _make_client()

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = [_make_tag("Schlager")]
        network.get_artist.return_value = artist_obj
        network.get_track.side_effect = RuntimeError("no such track")

        track_info, tags = client._get_lastfm_data("Some Title", "Some Artist")

        assert track_info is not None
        assert tags == ["schlager"]

    def test_unexpected_exception_returns_none_and_empty_tags(self):
        client, network = _make_client()
        network.get_artist.side_effect = RuntimeError("network error")

        track_info, tags = client._get_lastfm_data("Some Title", "Some Artist")
        assert track_info is None
        assert tags == []


class TestFetchMetadata:
    def test_no_track_info_returns_empty_dict(self):
        client, network = _make_client()
        network.get_artist.return_value = None

        result = asyncio.run(client.fetch_metadata("Some Title", "Some Artist"))
        assert result == {}

    def test_tags_present_with_include_genre_determines_genre(self):
        genremapper = MagicMock()
        genremapper.determine_genre.return_value = MagicMock(primary="Hip Hop")
        client, network = _make_client(genremapper=genremapper)

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = [_make_tag("Hip Hop")]
        network.get_artist.return_value = artist_obj
        network.get_track.return_value = None

        result = asyncio.run(
            client.fetch_metadata("Some Title", "Some Artist", include_genre=True)
        )

        assert result["tags"] == ["hip hop"]
        assert result["genre"] == "Hip Hop"
        genremapper.determine_genre.assert_called_once()

    def test_include_genre_false_skips_genre_determination(self):
        genremapper = MagicMock()
        client, network = _make_client(genremapper=genremapper)

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = [_make_tag("Hip Hop")]
        network.get_artist.return_value = artist_obj
        network.get_track.return_value = None

        result = asyncio.run(
            client.fetch_metadata("Some Title", "Some Artist", include_genre=False)
        )

        assert result["genre"] == "unknown"
        genremapper.determine_genre.assert_not_called()

    def test_no_tags_genre_stays_unknown(self):
        genremapper = MagicMock()
        client, network = _make_client(genremapper=genremapper)

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = []
        network.get_artist.return_value = artist_obj
        network.get_track.return_value = None

        result = asyncio.run(
            client.fetch_metadata("Some Title", "Some Artist", include_genre=True)
        )

        assert result["genre"] == "unknown"
        genremapper.determine_genre.assert_not_called()

    def test_real_timeout_returns_empty_dict_not_raises(self):
        """
        Echter Timeout-Beweis: async_timeout.timeout(Config.LASTFM_TIMEOUT)
        umschliesst den kompletten asyncio.to_thread(...)-Aufruf. Ein
        winziges Timeout (0.01s) + eine tatsaechlich blockierende
        _get_lastfm_data() erzwingt den echten
        "except asyncio.TimeoutError"-Pfad in fetch_metadata(), nicht nur
        den "kein track_info"-Pfad.
        """
        import time

        client, network = _make_client(lastfm_timeout=0.01)

        def _slow_get_artist(*args, **kwargs):
            time.sleep(0.2)
            return None

        network.get_artist.side_effect = _slow_get_artist

        result = asyncio.run(client.fetch_metadata("Some Title", "Some Artist"))
        assert result == {}

    def test_unexpected_exception_in_fetch_returns_empty_dict(self):
        client, network = _make_client()
        network.get_artist.side_effect = RuntimeError("boom")

        result = asyncio.run(client.fetch_metadata("Some Title", "Some Artist"))
        assert result == {}

    def test_result_includes_listeners_playcount_album_wiki_from_track_info(self):
        """
        Charakterisiert bestehendes Verhalten: _get_lastfm_data() liefert
        aktuell IMMER None fuer listeners/playcount/album/wiki (simuliertes
        track_info, Kommentar "Simuliere track_info fuer minimalen
        Fallback") - pylast liefert diese Felder trotz vorhandener API nie
        tatsaechlich ab. Kein aktiver Aufrufer liest diese Felder derzeit
        (siehe genre_processor.py._fetch_genre_from_lastfm), daher folgenlos.
        """
        client, network = _make_client()

        artist_obj = MagicMock()
        artist_obj.get_top_tags.return_value = [_make_tag("Pop")]
        network.get_artist.return_value = artist_obj
        network.get_track.return_value = None

        result = asyncio.run(client.fetch_metadata("Some Title", "Some Artist"))

        assert result["listeners"] is None
        assert result["playcount"] is None
        assert result["album"] is None
        assert result["wiki"] is None
