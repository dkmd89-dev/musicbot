"""
Characterization-Tests fuer den echten GenreProcessor.

Ersetzt die vorherige Testdatei, die eine eigene GenreProcessor-Klasse
innerhalb der Testdatei nachgebaut hatte (TEST-001 aus der Engineering
Baseline) und ausserdem nicht von pytest eingesammelt wurde, weil die
Testklasse einen __init__-Konstruktor besass.

Getestet wird die Produktionsklasse
services.downloader.utils.metadata.genre_processor.GenreProcessor
zusammen mit dem echten utils.genre_map.GenreMapper gegen die realen
YAML-Dateien in mapping/. Externe Services (MusicBrainz, Last.fm) werden
hier nicht angesprochen - normalize_genre_name() und prioritize_genres()
sind rein lokale, synchrone Methoden ohne externe Aufrufe.
"""

import asyncio

import pytest

from services.downloader.utils.metadata.genre_processor import GenreProcessor
from utils.genre_map import GenreMapper


@pytest.fixture
def genre_processor(config):
    genre_mapper = GenreMapper(str(config.GENRE_MAPPING_DIR))
    return GenreProcessor(config, genre_mapper)


class TestNormalizeGenreName:
    def test_deutschrap_variants(self, genre_processor):
        cases = [
            ("deutschrap", "Deutschrap"),
            ("german hip hop", "Deutschrap"),
            ("ruhrpott rap", "Ruhrpott Rap"),
            ("berliner rap", "Berliner Rap"),
            ("hamburger schule", "Hamburger Rap"),
        ]
        for raw, expected in cases:
            assert genre_processor.normalize_genre_name(raw) == expected

    def test_hip_hop(self, genre_processor):
        assert genre_processor.normalize_genre_name("hip hop") == "Hip Hop"
        assert genre_processor.normalize_genre_name("rap") == "Hip Hop"

    def test_pop(self, genre_processor):
        assert genre_processor.normalize_genre_name("pop") == "Pop"

    def test_electronic(self, genre_processor):
        assert genre_processor.normalize_genre_name("edm") == "Electronic"

    def test_case_insensitive(self, genre_processor):
        assert genre_processor.normalize_genre_name("DEUTSCHRAP") == "Deutschrap"

    def test_empty_string_returns_unknown(self, genre_processor):
        assert genre_processor.normalize_genre_name("") == "Unknown"


class TestPrioritizeGenres:
    def test_deutschrap_over_hip_hop(self, genre_processor):
        primary, _ = genre_processor.prioritize_genres(["deutschrap", "hip hop"])
        assert primary == "Deutschrap"

    def test_subgenre_over_main_genre(self, genre_processor):
        primary, _ = genre_processor.prioritize_genres(["ruhrpott rap", "deutschrap"])
        assert primary == "Ruhrpott Rap"

    def test_deutschrap_subgenres(self, genre_processor):
        cases = [
            (["hamburger schule", "deutschrap"], "Hamburger Rap"),
            (["berliner rap", "deutschrap"], "Berliner Rap"),
        ]
        for tags, expected in cases:
            primary, _ = genre_processor.prioritize_genres(tags)
            assert primary == expected

    def test_ignored_secondary_tags_are_filtered(self, genre_processor):
        primary, secondary = genre_processor.prioritize_genres(
            ["deutschrap", "seen live"]
        )
        assert primary == "Deutschrap"
        assert secondary == []

    def test_artist_name_is_filtered_from_tags(self, genre_processor):
        primary, _ = genre_processor.prioritize_genres(
            ["deutschrap", "kollegah"], artist_name="kollegah"
        )
        assert primary == "Deutschrap"

    def test_secondary_max_five(self, genre_processor):
        _, secondary = genre_processor.prioritize_genres(
            ["deutschrap", "a", "b", "c", "d", "e", "f", "g"]
        )
        assert len(secondary) <= 5

    def test_secondary_has_no_duplicates(self, genre_processor):
        _, secondary = genre_processor.prioritize_genres(
            ["deutschrap", "hip hop", "hip hop", "rap"]
        )
        assert len(secondary) == len(set(secondary))

    def test_empty_tags_returns_unknown(self, genre_processor):
        primary, secondary = genre_processor.prioritize_genres([])
        assert primary == "Unknown"
        assert secondary == []

    def test_german_vs_us_rap_prefers_deutschrap(self, genre_processor):
        primary, _ = genre_processor.prioritize_genres(["german hip hop", "hip hop"])
        assert primary == "Deutschrap"

    def test_regional_subgenres(self, genre_processor):
        cases = [
            ("berliner rap", "Berliner Rap"),
            ("hamburger schule", "Hamburger Rap"),
            ("ruhrpott rap", "Ruhrpott Rap"),
        ]
        for tag, expected in cases:
            assert genre_processor.normalize_genre_name(tag) == expected


class TestDetermineGenreWithFallbacksManualMapping:
    """
    Characterization-Test fuer den ersten Pfad der async Pipeline:
    ein Artist mit exaktem Eintrag in artist_genre.yaml muss ohne
    externe Services (mb_client=None, lfm_client=None) sofort das
    manuelle Genre liefern (Schritt 1 der Pipeline, hoechste Prioritaet).
    """

    def test_known_manual_artist_returns_manual_genre_without_external_calls(
        self, genre_processor
    ):
        known_artist = next(iter(genre_processor.genre_mapper.artist_map), None)
        if known_artist is None:
            pytest.skip("Keine Eintraege in artist_genre.yaml vorhanden")

        expected = genre_processor.genre_mapper.artist_map[known_artist].primary

        result = asyncio.run(
            genre_processor.determine_genre_with_fallbacks(
                track_metadata={"title": f"{known_artist} - Testsong"},
                artist_name=known_artist,
                channel_name="SomeChannel",
            )
        )

        assert result is not None
        assert result.primary == expected
        assert result.source == "artist_exact_manual"


class FakeMusicBrainzClient:
    def __init__(self, response):
        self._response = response

    async def fetch_metadata(self, title, artist):
        return self._response


class FakeLastFmClient:
    def __init__(self, response):
        self._response = response

    async def fetch_metadata(self, title, artist, include_genre=True, mbid=None):
        return self._response


class TestDetermineGenreWithFallbacksExternalSteps:
    """
    Charakterisiert die Schritte 3-5 der Pipeline (MusicBrainz, Last.fm,
    Feature-Artist-Inferenz), die in Phase 1 noch nicht getestet waren.
    Alle Beispiele nutzen einen Artist/Titel ohne Eintrag in artist_genre.yaml/
    channel_genre.yaml, damit die manuellen/lokalen Schritte 1-2 durchfallen
    und der jeweils getestete Fallback-Schritt tatsaechlich greift.
    """

    async def _run(self, genre_processor, **kwargs):
        return await genre_processor.determine_genre_with_fallbacks(
            track_metadata={"title": kwargs.pop("title", "Some Song")},
            artist_name=kwargs.pop("artist_name", "Totally Unknown Artist XYZ"),
            channel_name=kwargs.pop("channel_name", "SomeUnknownChannel"),
            **kwargs,
        )

    def test_musicbrainz_genre_hit_populates_mb_ids(self, genre_processor):
        mb_client = FakeMusicBrainzClient(
            {
                "genre": "deutschrap",
                "tags": ["hip hop", "rap"],
                "recording_id": "abc-123",
            }
        )
        result = asyncio.run(
            self._run(genre_processor, mb_client=mb_client)
        )

        assert result is not None
        assert result.primary == "Deutschrap"
        assert result.source == "normalized"
        assert result.mb_ids["recording_id"] == "abc-123"

    def test_musicbrainz_ids_only_sentinel_when_no_genre(self, genre_processor):
        mb_client = FakeMusicBrainzClient({"recording_id": "abc-123"})
        result = asyncio.run(
            self._run(genre_processor, mb_client=mb_client)
        )

        assert result is not None
        assert result.source == "musicbrainz_ids_only"
        assert result.mb_ids["recording_id"] == "abc-123"

    def test_lastfm_fallback_used_when_musicbrainz_has_no_client(
        self, genre_processor
    ):
        lfm_client = FakeLastFmClient({"tags": ["hip hop", "deutschrap"]})
        result = asyncio.run(
            self._run(genre_processor, mb_client=None, lfm_client=lfm_client)
        )

        assert result is not None
        assert result.primary == "Deutschrap"
        assert result.source == "lastfm_prioritized"

    def test_feature_artist_inference_when_no_external_clients(
        self, genre_processor
    ):
        result = asyncio.run(
            self._run(
                genre_processor,
                mb_client=None,
                lfm_client=None,
                feat_artists=["Bausa"],
            )
        )

        assert result is not None
        assert result.primary == "Hip Hop"
        assert result.source == "feature_inference"
        assert result.confidence == 0.7

    def test_no_match_anywhere_returns_none(self, genre_processor):
        result = asyncio.run(
            self._run(genre_processor, mb_client=None, lfm_client=None)
        )
        assert result is None
