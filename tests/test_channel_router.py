"""
Unit-Tests für ChannelRouter (services/downloader/download/channel_router.py)
— vorher 0 Tests, live in EnhancedDownloadProcessor._do_init() verdrahtet
(download_utils.py), gefunden über die systematische Ungetestet-Prüfung.

Nutzt mapping_dir_copy (tmp-Kopie des echten mapping/-Verzeichnisses, siehe
tests/conftest.py) fuer echte special_channel.yaml-Daten bei P2/P3-Tests,
statt die Sonderkanal-Konfiguration zu erfinden (Regel 3 - Mapping-Dateien
sind Fachlogik).
"""

from unittest.mock import Mock

import pytest

from services.downloader.download.channel_router import ChannelRouter


class FakeConfig:
    def __init__(self, mapping_dir):
        self.GENRE_MAPPING_DIR = mapping_dir
        self.SPECIAL_CHANNELS = {}


@pytest.fixture
def config(mapping_dir_copy):
    return FakeConfig(mapping_dir_copy)


@pytest.fixture
def artist_normalizer():
    normalizer = Mock()
    normalizer.normalize.side_effect = lambda name: name  # Identitaet als Default
    return normalizer


@pytest.fixture
def router(artist_normalizer, config):
    return ChannelRouter(artist_normalizer, config, logger=Mock())


class TestResolveDominantArtistP1:
    def test_existing_dominant_artist_is_kept_unchanged(self, router):
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist="Already Set Artist",
            playlist_info={"uploader": "Some Channel"},
            entries=[],
        )
        assert result == "Already Set Artist"


class TestResolveDominantArtistP2:
    def test_special_channel_returns_canonical_name(self, router):
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None,
            playlist_info={"uploader": "Gemischtes Hack"},
            entries=[],
        )
        assert result == "Gemischtes Hack"

    def test_channel_from_entries_when_playlist_info_missing(self, router):
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None,
            playlist_info={},
            entries=[{"uploader": "Gemischtes Hack"}],
        )
        assert result == "Gemischtes Hack"


class TestResolveDominantArtistP3:
    def test_track_level_special_channel_used_when_playlist_channel_is_not_special(
        self, router
    ):
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None,
            playlist_info={"uploader": "DkmD89"},
            entries=[
                {"uploader": "Gemischtes Hack"},
                {"uploader": "Gemischtes Hack"},
                {"uploader": "Gemischtes Hack"},
            ],
        )
        assert result == "Gemischtes Hack"


class TestResolveDominantArtistP4:
    def test_normal_channel_used_as_fallback(self, router, artist_normalizer):
        artist_normalizer.normalize.side_effect = lambda name: name  # unveraendert
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None,
            playlist_info={"uploader": "Some Regular Channel"},
            entries=[],
        )
        assert result == "Some Regular Channel"


class TestResolveDominantArtistP5:
    def test_no_channel_at_all_returns_none(self, router):
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None, playlist_info={}, entries=[]
        )
        assert result is None

    def test_normalizer_returns_unknown_falls_to_compilation_mode(
        self, router, artist_normalizer
    ):
        artist_normalizer.normalize.side_effect = lambda name: "Unknown"
        _channel_raw, result = router.resolve_dominant_artist(
            dominant_artist=None,
            playlist_info={"uploader": "Some Regular Channel"},
            entries=[],
        )
        assert result is None


class TestFindDominantSpecialChannelFromEntries:
    def test_empty_entries_returns_none(self, router):
        assert router.find_dominant_special_channel_from_entries([]) is None

    def test_most_common_special_channel_wins(self, router):
        entries = [
            {"uploader": "Gemischtes Hack"},
            {"uploader": "Gemischtes Hack"},
            {"uploader": "Some Other Channel"},
        ]
        result = router.find_dominant_special_channel_from_entries(entries)
        assert result == "Gemischtes Hack"

    def test_no_special_channel_among_entries_returns_none(self, router):
        entries = [{"uploader": "Totally Normal Channel"}]
        assert router.find_dominant_special_channel_from_entries(entries) is None

    def test_normalizer_exception_falls_back_to_raw_channel_name(
        self, router, artist_normalizer
    ):
        artist_normalizer.normalize.side_effect = RuntimeError("boom")
        entries = [{"uploader": "Gemischtes Hack"}]
        # Normalisierung schlaegt fehl, aber der rohe Name wird trotzdem
        # gegen die Sonderkanal-Liste geprueft (get_special_channel_info
        # wird zusaetzlich mit dem unveraenderten track_channel aufgerufen).
        result = router.find_dominant_special_channel_from_entries(entries)
        assert result == "Gemischtes Hack"


class TestIsSpecialChannel:
    def test_known_special_channel_returns_true(self, router):
        assert router._is_special_channel("Gemischtes Hack") is True

    def test_unknown_channel_returns_false(self, router):
        assert router._is_special_channel("Some Random Channel") is False

    def test_empty_string_returns_false(self, router):
        assert router._is_special_channel("") is False
