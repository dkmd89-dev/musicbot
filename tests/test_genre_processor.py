"""
Characterization-Tests fuer den echten GenreProcessor.

Ersetzt die vorherige Testdatei, die eine eigene GenreProcessor-Klasse
innerhalb der Testdatei nachgebaut hatte (TEST-001 aus der Engineering
Baseline) und ausserdem nicht von pytest eingesammelt wurde, weil die
Testklasse einen __init__-Konstruktor besass.

Getestet wird die Produktionsklasse
services.metadata.genre_processor.GenreProcessor
zusammen mit dem echten utils.genre_map.GenreMapper gegen die realen
YAML-Dateien in mapping/. Externe Services (MusicBrainz, Last.fm) werden
hier nicht angesprochen - normalize_genre_name() und prioritize_genres()
sind rein lokale, synchrone Methoden ohne externe Aufrufe.
"""

import asyncio

import pytest

from services.metadata.genre_processor import GenreProcessor
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
        """
        ARCH-012 Phase 3B: mb_client liefert seit dieser Phase nur noch
        rohe "tags" (kein vorberechnetes "genre"-Feld mehr) -
        _fetch_genre_from_musicbrainz() priorisiert sie ueber
        prioritize_genres(). "hip hop"/"rap" sind als zu allgemeine
        Uebergenres in mapping/genre_filters.yaml::IGNORE_SECONDARY
        gelistet und werden herausgefiltert; "deutschrap" bleibt als
        valides Tag uebrig.
        """
        mb_client = FakeMusicBrainzClient(
            {
                "tags": ["deutschrap", "hip hop", "rap"],
                "recording_id": "abc-123",
            }
        )
        result = asyncio.run(
            self._run(genre_processor, mb_client=mb_client)
        )

        assert result is not None
        assert result.primary == "Deutschrap"
        assert result.source == "musicbrainz_prioritized"
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


class TestLastFmGenreFieldIsIgnored:
    """
    ARCH-012 Phase 1 (docs/archive/arch/MusicBot_ARCH-012_Genre_Logic_Characterization.md,
    Abschnitt 3/9) stellte fest, dass lastfm_client.py intern ein "genre"-
    Feld per GenreMapper.determine_genre() berechnet, das hier in
    _fetch_genre_from_lastfm() praktisch nie verwendet wird - stattdessen
    entscheidet ausschliesslich prioritize_genres() auf den rohen "tags".

    Charakterisiert vor ARCH-012 Phase 2 (Entfernung dieses toten Feldes
    im Client): das "genre"-Feld im vom Last.fm-Client gelieferten Dict
    hat KEINEN Einfluss auf das effektive Ergebnis - weder wenn es einen
    (ggf. voellig falschen) Wert enthaelt, noch wenn es komplett fehlt
    (der Zustand nach der Client-Bereinigung). Wird dieser Test nach der
    Entfernung des toten Pfads erneut ausgefuehrt, muss er unveraendert
    gruen bleiben - das ist der Beleg, dass die Bereinigung keine
    Verhaltensaenderung ist.
    """

    async def _run(self, genre_processor, lfm_client):
        return await genre_processor.determine_genre_with_fallbacks(
            track_metadata={"title": "Some Song"},
            artist_name="Totally Unknown Artist XYZ",
            channel_name="SomeUnknownChannel",
            mb_client=None,
            lfm_client=lfm_client,
        )

    def test_genre_field_value_does_not_affect_effective_result(
        self, genre_processor
    ):
        tags = ["hip hop", "deutschrap"]

        with_bogus_genre = FakeLastFmClient(
            {"tags": tags, "genre": "Totally Wrong Genre Value"}
        )
        without_genre_field = FakeLastFmClient({"tags": tags})

        result_with = asyncio.run(self._run(genre_processor, with_bogus_genre))
        result_without = asyncio.run(
            self._run(genre_processor, without_genre_field)
        )

        assert result_with is not None
        assert result_without is not None
        assert result_with.primary == result_without.primary == "Deutschrap"
        assert result_with.source == result_without.source == "lastfm_prioritized"
        assert result_with.secondary == result_without.secondary
        assert result_with.raw_tags == result_without.raw_tags == tags


class TestMusicBrainzGenrePrioritizationCharacterization:
    """
    ARCH-012 Phase 3A/3B (docs/archive/arch/MusicBot_ARCH-012_Genre_Logic_Characterization.md).

    Phase 3A hatte empirisch belegt (gegen den echten GenreMapper): der
    fruehere zweistufige determine_genre()-Aufruf im MusicBrainz-Pfad war
    fuer Multi-Tag-Eingaben strukturell fehlerhaft -
    GenreMapper.normalize_genre_name() ist fuer EINEN einzelnen Genre-
    String ausgelegt, nicht fuer eine kommagetrennte Mehrfach-Tag-Liste,
    und lieferte bei >1 Tag den kompletten, title-gecasten Tag-String
    statt eines Einzelgenres (z. B. "Ruhrpott Rap, Hip Hop, Trap").

    Phase 3B hat das behoben (Variante A): MusicBrainzClient liefert seit
    dieser Phase nur noch rohe Tags, genre_processor._fetch_genre_from_musicbrainz()
    priorisiert sie ueber die bestehende prioritize_genres()-Logik (analog
    zum Last.fm-Pfad). Diese Tests charakterisieren das NEUE, korrigierte
    Verhalten gegen den echten GenreMapper/GenreProcessor (nur der
    netzwerkgebundene MusicBrainzClient wird per FakeMusicBrainzClient
    ersetzt, Regel 7) und dienen als Regressionsschutz fuer die
    Phase-3B-Umsetzung.
    """

    UNKNOWN_ARTIST = "Totally Unknown Artist XYZ"

    @staticmethod
    def _client_genre_value(genre_processor, tags):
        """
        Repliziert die VOR Phase 3B im Client durchgefuehrte
        genre_value-Berechnung (GenreMapper.determine_genre() auf dem
        kommagetrennten Tag-String) - dient hier nur noch dazu, das in
        Phase 3A dokumentierte GenreMapper-Verhalten selbst
        nachzuweisen (GenreMapper wurde in Phase 3B NICHT veraendert).
        Kein Bezug mehr zu MusicBrainzClient, der diese Berechnung seit
        Phase 3B nicht mehr durchfuehrt.
        """
        mb_tags_str = ", ".join(tags) if tags else ""
        artist = TestMusicBrainzGenrePrioritizationCharacterization.UNKNOWN_ARTIST
        if mb_tags_str:
            r = genre_processor.genre_mapper.determine_genre(
                raw_genre=mb_tags_str, artist_name=artist
            )
        else:
            r = genre_processor.genre_mapper.determine_genre(
                raw_genre="", artist_name=artist, channel_name=artist
            )
        return r.primary if (r and r.primary) else "unknown"

    async def _run_musicbrainz_path(self, genre_processor, mb_response, artist=None):
        return await genre_processor.determine_genre_with_fallbacks(
            track_metadata={"title": "Some Song"},
            artist_name=artist or self.UNKNOWN_ARTIST,
            channel_name="SomeUnknownChannel",
            mb_client=FakeMusicBrainzClient(mb_response),
            lfm_client=None,
        )

    def test_genre_mapper_still_collapses_a_joined_multi_tag_string(
        self, genre_processor
    ):
        """
        GenreMapper selbst wurde in Phase 3B bewusst NICHT veraendert -
        das in Phase 3A dokumentierte Verhalten (ein kommagetrennter
        Multi-Tag-String wird nur title-gecast, nicht pro Tag ausgewertet)
        besteht als Eigenschaft von GenreMapper.determine_genre() weiter.
        Genau deshalb liegt die Genre-Priorisierung seit Phase 3B nicht
        mehr bei GenreMapper.determine_genre(), sondern bei
        prioritize_genres() (siehe folgende Tests).
        """
        tags = ["ruhrpott rap", "hip hop", "trap"]

        client_genre_value = self._client_genre_value(genre_processor, tags)

        assert client_genre_value == "Ruhrpott Rap, Hip Hop, Trap"

    def test_musicbrainz_path_now_prioritizes_raw_tags_instead_of_a_collapsed_string(
        self, genre_processor
    ):
        """
        Kern-Regressionstest fuer Phase 3B: derselbe Multi-Tag-Input, der
        vor Phase 3B ueber den Client-Zwischenwert zu
        "Ruhrpott Rap, Hip Hop, Trap" (source="normalized") fuehrte,
        ergibt jetzt ueber die rohen "tags" + prioritize_genres() ein
        sauberes Einzelgenre mit korrekt gerankten Sekundaer-Genres.
        Ein eventuell im Response-Dict verbliebenes "genre"-Feld (Artefakt
        eines alten Client-Formats) wird bewusst mitgegeben, um zu
        beweisen, dass es nicht mehr gelesen wird.
        """
        tags = ["ruhrpott rap", "hip hop", "trap"]

        mb_response = {
            "genre": "Ruhrpott Rap, Hip Hop, Trap",  # altes Format, muss ignoriert werden
            "tags": tags,
            "recording_id": "abc-123",
        }
        result = asyncio.run(self._run_musicbrainz_path(genre_processor, mb_response))

        assert result is not None
        assert result.primary == "Ruhrpott Rap"
        assert result.secondary == ["Hip Hop"]
        assert result.source == "musicbrainz_prioritized"
        assert result.raw_tags == tags
        assert result.mb_ids["recording_id"] == "abc-123"

    def test_single_known_tag_resolves_to_a_clean_genre(self, genre_processor):
        """Gegenprobe: bereits ein einzelnes, in der Hierarchie bekanntes
        Tag ergibt ein sauberes Einzelgenre - unveraendert gegenueber vor
        Phase 3B (Einzeltags waren nie vom in Phase 3A dokumentierten
        Fehler betroffen)."""
        mb_response = {"tags": ["ruhrpott rap"], "recording_id": "abc-123"}
        result = asyncio.run(self._run_musicbrainz_path(genre_processor, mb_response))

        assert result is not None
        assert result.primary == "Ruhrpott Rap"
        assert result.source == "musicbrainz_prioritized"

    def test_no_tags_falls_back_to_ids_only_sentinel(self, genre_processor):
        """Ohne Tags, aber mit vorhandenen MBIDs: wie zuvor der
        musicbrainz_ids_only-Sentinel - unveraendert durch Phase 3B."""
        mb_response = {"tags": [], "recording_id": "abc-123"}
        result = asyncio.run(self._run_musicbrainz_path(genre_processor, mb_response))

        assert result is not None
        assert result.primary == ""
        assert result.source == "musicbrainz_ids_only"
        assert result.mb_ids["recording_id"] == "abc-123"

    def test_known_artist_shields_against_musicbrainz_tags(self, genre_processor):
        """Gegenprobe: ein Artist mit manuellem Mapping-Eintrag
        (artist_genre.yaml) erhaelt sein Genre bereits in Schritt 1 der
        Gesamt-Pipeline (determine_genre_with_fallbacks) - MusicBrainz
        wird dann nur noch fuer mb_ids ausgewertet, die MusicBrainz-Tags
        wirken sich auf das Endergebnis nicht aus. Unveraendert durch
        Phase 3B."""
        known_artist = next(iter(genre_processor.genre_mapper.artist_map))
        expected_primary = genre_processor.genre_mapper.artist_map[known_artist].primary

        mb_response = {
            "tags": ["ruhrpott rap", "hip hop", "trap"],
            "recording_id": "abc-123",
        }
        result = asyncio.run(
            self._run_musicbrainz_path(genre_processor, mb_response, artist=known_artist)
        )

        assert result.primary == expected_primary
        assert result.source == "artist_exact_manual"
