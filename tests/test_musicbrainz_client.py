"""
Characterization-Tests fuer services/clients/musicbrainz_client.py.

MusicBrainz ist explizit Teil des P0-Metadata-Flows in CLAUDE.md
("MusicBrainz / Lyrics / Cover"), hatte aber vor dieser Session keinerlei
Testabdeckung (426 Zeilen, 0 Tests).

ArtistNormalizer wird hier bewusst NICHT real instanziiert, sondern
gemockt: MusicBrainzClient.__init__() faellt beim ArtistNormalizer ohne
get_artist_normalizer()-Singleton auf eine EIGENE Instanz mit dem ECHTEN
Config.LIBRARY_DIR/ARTIST_OVERRIDE_FILE zurueck - genau das Szenario, das
in tests/test_artist_normalizer.py bereits einmal zu einem versehentlichen
Schreibzugriff auf die reale mapping/case_preserve.yaml gefuehrt hat. Diese
Klasse wird hier isoliert unit-getestet (Regel 8 Testpyramide), nicht
zusammen mit ihren echten Kollaborateuren.

ARCH-012 Phase 3B: der Client besitzt seit dieser Phase keinen
GenreMapper mehr (siehe docs/MusicBot_ARCH-012_Genre_Logic_Characterization.md,
Abschnitt "Phase 3B") - fetch_metadata()/_build_metadata() liefern nur
noch die rohen release-group-Tags, keine vorberechnete Genre-Entscheidung.
Die frueheren genre_mapper-Mocks in dieser Datei entfallen entsprechend.

Nebenbefund (dokumentiert, nicht gefixt): _build_metadata() setzt
"track_number" auf first_release["medium-track-count"]. Laut
musicbrainzngs-Quellcode (mbxml.py: "medium-list results from search have
an additional <track-count> element containing the number of tracks")
ist das die GESAMTANZAHL der Tracks auf dem Medium, nicht die Position des
gefundenen Recordings. Der Wert waere fuer jeden Track eines Albums
identisch (z.B. immer "12" bei einem 12-Track-Album) statt der echten
Tracknummer. Ungefixt, da KEIN Aufrufer im Repo dieses Feld liest
(track_number in DownloadResult/MetadataResult kommt aus einer anderen
Quelle, siehe album_processor.extract_track_number_from_string) - reiner
"toter", aber inhaltlich falscher Wert. Siehe docs/MusicBot_ENGINEERING_BASELINE.md.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.clients.musicbrainz_client as mb_module
from services.clients.musicbrainz_client import (
    MusicBrainzClient,
    _musicbrainz_result_cache,
    cached_musicbrainz_search,
    similarity,
)


@pytest.fixture(autouse=True)
def clear_musicbrainz_cache():
    _musicbrainz_result_cache.clear()
    yield
    _musicbrainz_result_cache.clear()


def _make_client(artist_normalizer=None):
    with patch.object(
        mb_module, "_get_artist_normalizer", return_value=artist_normalizer or MagicMock()
    ), patch("musicbrainzngs.set_useragent"):
        return MusicBrainzClient()


class TestSimilarity:
    def test_identical_strings_score_one(self):
        assert similarity("Bohemian Rhapsody", "Bohemian Rhapsody") == 1.0

    def test_case_insensitive(self):
        assert similarity("Bohemian Rhapsody", "BOHEMIAN RHAPSODY") == 1.0

    def test_completely_different_strings_score_low(self):
        assert similarity("abc", "xyz") < 0.3


class TestCachedMusicbrainzSearch:
    def test_cache_hit_does_not_call_api(self):
        _musicbrainz_result_cache["cached query"] = {"recording-list": [{"id": "1"}]}
        with patch("musicbrainzngs.search_recordings") as mock_search:
            result = asyncio.run(cached_musicbrainz_search("cached query", "recording"))
        mock_search.assert_not_called()
        assert result == {"recording-list": [{"id": "1"}]}

    def test_cache_miss_calls_search_recordings_for_recording_type(self):
        with patch(
            "musicbrainzngs.search_recordings", return_value={"recording-list": []}
        ) as mock_search:
            result = asyncio.run(cached_musicbrainz_search("new query", "recording"))
        mock_search.assert_called_once_with(query="new query", limit=10)
        assert result == {"recording-list": []}
        assert _musicbrainz_result_cache["new query"] == {"recording-list": []}

    def test_cache_miss_calls_search_releases_for_release_type(self):
        with patch(
            "musicbrainzngs.search_releases", return_value={"release-list": []}
        ) as mock_search:
            result = asyncio.run(cached_musicbrainz_search("album query", "release"))
        mock_search.assert_called_once_with(query="album query", limit=10)
        assert result == {"release-list": []}

    def test_invalid_search_type_returns_empty_dict(self):
        result = asyncio.run(cached_musicbrainz_search("q", "not-a-real-type"))
        assert result == {}

    def test_network_error_is_caught_and_returns_empty_dict_uncached(self):
        import musicbrainzngs

        with patch(
            "musicbrainzngs.search_recordings",
            side_effect=musicbrainzngs.NetworkError("down"),
        ):
            result = asyncio.run(cached_musicbrainz_search("q", "recording"))
        assert result == {}
        assert "q" not in _musicbrainz_result_cache

    def test_unexpected_exception_is_caught_and_returns_empty_dict(self):
        with patch(
            "musicbrainzngs.search_recordings", side_effect=RuntimeError("boom")
        ):
            result = asyncio.run(cached_musicbrainz_search("q", "recording"))
        assert result == {}


class TestParseSearchTerms:
    def test_youtube_format_title_is_reparsed_when_split_succeeds(self):
        normalizer = MagicMock()
        parsed = MagicMock()
        parsed.artist_string = "Real Artist"
        parsed.title = "Real Title"
        normalizer.parse_youtube_title.return_value = parsed
        client = _make_client(artist_normalizer=normalizer)

        title, artist = client.parse_search_terms(
            "Wrong Artist - Real Title", "Wrong Artist"
        )
        assert title == "Real Title"
        assert artist == "Real Artist"

    def test_falls_through_to_normalize_when_parse_result_incomplete(self):
        normalizer = MagicMock()
        parsed = MagicMock()
        parsed.artist_string = None
        parsed.title = None
        normalizer.parse_youtube_title.return_value = parsed
        normalizer.normalize.return_value = "Normalized Artist"
        client = _make_client(artist_normalizer=normalizer)

        title, artist = client.parse_search_terms("A - B", "Original Artist")
        assert title == "A - B"
        assert artist == "Normalized Artist"

    def test_normalized_artist_used_when_different_from_original(self):
        normalizer = MagicMock()
        normalizer.normalize.return_value = "Clean Artist"
        client = _make_client(artist_normalizer=normalizer)

        title, artist = client.parse_search_terms("Some Title", "clean artist ")
        assert title == "Some Title"
        assert artist == "Clean Artist"

    def test_normalized_artist_unknown_keeps_original(self):
        normalizer = MagicMock()
        normalizer.normalize.return_value = "Unknown"
        client = _make_client(artist_normalizer=normalizer)

        title, artist = client.parse_search_terms("Some Title", "Weird Artist")
        assert artist == "Weird Artist"

    def test_unchanged_normalize_result_returns_original_pair(self):
        normalizer = MagicMock()
        normalizer.normalize.return_value = "Same Artist"
        client = _make_client(artist_normalizer=normalizer)

        title, artist = client.parse_search_terms("Some Title", "Same Artist")
        assert (title, artist) == ("Some Title", "Same Artist")


class TestGetBestMatch:
    def test_selects_highest_scoring_recording_above_threshold(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Totally Different Song", "artist-credit-phrase": "Nobody"},
            {"title": "Bohemian Rhapsody", "artist-credit-phrase": "Queen"},
        ]
        best = client._get_best_match(recordings, "Bohemian Rhapsody", "Queen")
        assert best["title"] == "Bohemian Rhapsody"

    def test_returns_none_when_all_scores_below_threshold(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [{"title": "Nothing Alike", "artist-credit-phrase": "Someone Else"}]
        best = client._get_best_match(recordings, "Bohemian Rhapsody", "Queen")
        assert best is None

    def test_empty_recordings_returns_none(self):
        client = _make_client()
        assert client._get_best_match([], "Title", "Artist") is None


class TestFetchMetadata:
    def test_combined_query_match_returns_built_metadata(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recording = {
            "id": "rec-1",
            "title": "Bohemian Rhapsody",
            "artist-credit-phrase": "Queen",
        }
        combined_response = {"recording-list": [recording]}

        with patch.object(
            mb_module, "cached_musicbrainz_search", new=AsyncMock(return_value=combined_response)
        ), patch("musicbrainzngs.get_recording_by_id", return_value={"recording": recording}):
            result = asyncio.run(client.fetch_metadata("Bohemian Rhapsody", "Queen"))

        assert result["title"] == "Bohemian Rhapsody"
        assert result["artist"] == "Queen"
        assert result["mbid"] == "rec-1"

    def test_falls_back_to_title_only_search_when_combined_empty(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recording = {"id": "rec-2", "title": "Some Song", "artist-credit-phrase": "Some Artist"}
        responses = [{"recording-list": []}, {"recording-list": [recording]}]

        with patch.object(
            mb_module, "cached_musicbrainz_search", new=AsyncMock(side_effect=responses)
        ), patch("musicbrainzngs.get_recording_by_id", return_value={"recording": recording}):
            result = asyncio.run(client.fetch_metadata("Some Song", "Some Artist"))

        assert result["mbid"] == "rec-2"

    def test_no_results_anywhere_returns_empty_dict(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        empty_response = {"recording-list": [], "release-list": []}
        with patch.object(
            mb_module, "cached_musicbrainz_search", new=AsyncMock(return_value=empty_response)
        ):
            result = asyncio.run(client.fetch_metadata("Nothing", "Nobody"))
        assert result == {}

    def test_internal_exception_is_caught_and_returns_empty_dict(self):
        normalizer = MagicMock()
        normalizer.parse_youtube_title.side_effect = RuntimeError("boom")
        client = _make_client(artist_normalizer=normalizer)

        result = asyncio.run(client.fetch_metadata("A - B", "Some Artist"))
        assert result == {}


class TestBuildMetadataFieldExtraction:
    def test_extracts_isrc_release_and_ids(self):
        client = _make_client()
        match = {
            "id": "rec-123",
            "title": "Track Title",
            "release-list": [
                {
                    "id": "rel-456",
                    "title": "Album Title",
                    "release-group": {"id": "rg-789", "title": "Album Title", "tags": []},
                }
            ],
            "artist-credit": [{"artist": {"id": "artist-999"}}],
        }
        recording_detail = {
            "recording": {
                **match,
                "isrc-list": ["USABC1234567"],
            }
        }
        with patch("musicbrainzngs.get_recording_by_id", return_value=recording_detail):
            result = asyncio.run(client._build_metadata(match, "Original Artist"))

        assert result["isrc"] == "USABC1234567"
        assert result["release_id"] == "rel-456"
        assert result["release_group_id"] == "rg-789"
        assert result["artist_id"] == "artist-999"
        assert result["recording_id"] == "rec-123"
        assert result["artist"] == "Original Artist"

    def test_track_number_uses_real_track_position_not_medium_total_count(self):
        """
        Regressionstest fuer BUG-001 (docs/MusicBot_ENGINEERING_BASELINE.md):
        vorher wurde faelschlich "medium-track-count" (die GESAMTANZAHL der
        Tracks auf dem Medium) als Tracknummer verwendet. Die Fixture-Form
        (release-list -> medium-list -> track-list -> "number") entspricht
        der echten, live gegen musicbrainz.org verifizierten API-Antwort von
        search_recordings() fuer "Bohemian Rhapsody" (Track 8 auf einem
        Medium mit insgesamt 17 Tracks).
        """
        client = _make_client()
        match = {
            "id": "rec-1",
            "title": "Bohemian Rhapsody",
            "release-list": [
                {
                    "id": "rel-1",
                    "title": "Big Album",
                    "medium-track-count": "17",
                    "medium-list": [
                        {
                            "position": "1",
                            "track-count": 17,
                            "track-list": [
                                {"id": "trk-1", "number": "8", "title": "Bohemian Rhapsody"}
                            ],
                        }
                    ],
                }
            ],
        }
        with patch("musicbrainzngs.get_recording_by_id", return_value={}):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))

        assert result["track_number"] == 8

    def test_track_number_falls_back_to_source_track_number_from_release_path(self):
        """
        Regressionstest fuer den Release-Fallback-Pfad
        (_extract_recordings_from_releases): dort ersetzt _source_release
        first_release komplett (ohne medium-list), die echte Position kommt
        stattdessen aus _source_track_number.
        """
        client = _make_client()
        match = {
            "id": "rec-1",
            "title": "Some Track",
            "_source_release": {"id": "rel-1", "title": "Album"},
            "_source_track_number": "4",
        }
        with patch("musicbrainzngs.get_recording_by_id", return_value={}):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))

        assert result["track_number"] == 4

    def test_track_number_is_none_when_no_position_data_available(self):
        client = _make_client()
        match = {"id": "rec-1", "title": "Some Track", "release-list": []}
        with patch("musicbrainzngs.get_recording_by_id", return_value={}):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))
        assert result["track_number"] is None

    def test_release_group_tags_survive_the_detail_lookup(self):
        """
        Regressionstest fuer BUG-002 (docs/MusicBot_ENGINEERING_BASELINE.md):
        get_recording_by_id() unterstuetzt fuer "recording" keinen
        "release-groups"-Include, sein release-list hat daher NIE
        release-group-Daten. Vorher wurde die reichhaltigere release-list
        des urspruenglichen Suchtreffers (match) durch die aermere
        Detail-Antwort ueberschrieben - mb_tags/release-group.title waren
        dadurch in der Praxis IMMER leer/None.
        """
        client = _make_client()
        match = {
            "id": "rec-1",
            "title": "Some Track",
            "release-list": [
                {
                    "id": "rel-1",
                    "title": "Release Title",
                    "release-group": {
                        "id": "rg-1",
                        "title": "Release Group Title",
                        "tags": [{"name": "rock"}],
                    },
                }
            ],
        }
        # Simuliert die reale API: get_recording_by_id() liefert ein
        # release-list OHNE release-group (kein "release-groups"-Include
        # fuer diese Entity moeglich).
        detail_response = {
            "recording": {
                "id": "rec-1",
                "title": "Some Track",
                "release-list": [{"id": "rel-1", "title": "Release Title"}],
            }
        }
        with patch("musicbrainzngs.get_recording_by_id", return_value=detail_response):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))

        assert result["album"] == "Release Group Title"

    def test_release_group_tags_are_returned_raw_without_genre_determination(self):
        """
        ARCH-012 Phase 3B: _build_metadata() liefert die release-group-Tags
        seit dieser Phase unveraendert als "tags" zurueck - keine
        GenreMapper.determine_genre()-Verdichtung mehr im Client (siehe
        docs/MusicBot_ARCH-012_Genre_Logic_Characterization.md, Phase 3B).
        Die fachliche Priorisierung liegt jetzt ausschliesslich in
        genre_processor.py::_fetch_genre_from_musicbrainz() ueber
        prioritize_genres().
        """
        client = _make_client()

        match = {
            "id": "rec-1",
            "title": "Some Track",
            "release-list": [
                {
                    "id": "rel-1",
                    "release-group": {"tags": [{"name": "jazz"}, {"name": "smooth"}]},
                }
            ],
        }
        with patch("musicbrainzngs.get_recording_by_id", return_value={}):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))

        assert result["tags"] == ["jazz", "smooth"]
        assert result["genre"] == "unknown"

    def test_no_tags_genre_stays_unknown_placeholder(self):
        """
        ARCH-012 Phase 3B: ohne release-group-Tags liefert "genre" den
        festen Platzhalter "unknown" - kein Artist-/Channel-Fallback ueber
        GenreMapper mehr im Client (dieser lag ohnehin bereits vor
        genre_processor.py's eigenem Schritt 1/2 der Gesamt-Pipeline,
        siehe ARCH-012 Phase 3A/3B).
        """
        client = _make_client()

        match = {"id": "rec-1", "title": "Some Track", "release-list": []}
        with patch("musicbrainzngs.get_recording_by_id", return_value={}):
            result = asyncio.run(client._build_metadata(match, "Some Artist"))

        assert result["genre"] == "unknown"
        assert result["tags"] == []
