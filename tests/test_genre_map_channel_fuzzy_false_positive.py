# tests/test_genre_map_channel_fuzzy_false_positive.py
# -*- coding: utf-8 -*-
"""
Finding B (Download-Pipeline-Testlauf 2026-09-09): der Fuzzy-Channel-Match
in GenreMapper._find_best_match() (rapidfuzz WRatio, Schwelle 75 fuer
Channels) matchte einen ARTIST-/Nicht-Musik-Channel-Namen gegen eine
channel_genre.yaml-Regel und vergab dadurch ein falsches "lokales Genre",
das die restliche Fallback-Kette (MusicBrainz/Last.fm) kurzschliesst.

Zwei reale Fehltreffer:
  * channel='Akon'             -> 'kontor.tv'  (WRatio 77.1) -> Electronic
    (partial_ratio auf einer 4-Zeichen-Query matcht fast ueberall)
  * channel='Digster Pop Music'-> 'vibe music' (WRatio 85.5) -> Electronic
    (WRatio belohnt das gemeinsame Wort "music" - jedes "<X> Music" gegen
     jedes "<Y> Music" liegt bei ~85)

Beides sind Deutschrap-/Pop-Kuenstler, definitiv nicht Electronic.

Fix: Channel-Fuzzy-Schwelle 75 -> 90. Echte Channel-Namensvarianten
(Kontor.TV / kontortv / "trap nation official") liegen bei >= 90, die
Fehltreffer darunter. Verifiziert gegen die echte mapping/-Dir.
"""

import pytest

from utils.genre_map import GenreMapper


@pytest.fixture
def genre_mapper(config):
    return GenreMapper(str(config.GENRE_MAPPING_DIR))


class TestChannelFuzzyFalsePositives:
    def test_artist_name_as_channel_does_not_fuzzy_match_kontor(self, genre_mapper):
        """channel='Akon' darf NICHT ueber kontor.tv zu Electronic werden."""
        result = genre_mapper.determine_genre(artist_name="Akon", channel_name="Akon")
        assert not (
            result and result.source == "channel_fuzzy"
        ), f"Fehltreffer: {result}"

    def test_generic_music_channel_does_not_fuzzy_match_vibe_music(self, genre_mapper):
        """channel='Digster Pop Music' darf NICHT ueber 'vibe music' zu
        Electronic werden (gemeinsames Wort 'music')."""
        result = genre_mapper.determine_genre(
            artist_name="Andreas Bourani", channel_name="Digster Pop Music"
        )
        assert not (
            result and result.source == "channel_fuzzy"
        ), f"Fehltreffer: {result}"

    def test_generic_universal_music_does_not_fuzzy_match(self, genre_mapper):
        result = genre_mapper.determine_genre(channel_name="Universal Music")
        assert not (
            result and result.source == "channel_fuzzy"
        ), f"Fehltreffer: {result}"


class TestChannelFuzzyStillMatchesRealVariants:
    def test_exact_channel_key_still_matches(self, genre_mapper):
        result = genre_mapper.determine_genre(channel_name="Kontor.TV")
        assert result is not None
        assert result.source == "channel_exact"
        assert result.primary == "Electronic"

    def test_close_channel_variant_still_fuzzy_matches(self, genre_mapper):
        """'kontortv' (ohne Punkt) ist WRatio ~94 gegen 'kontor.tv' -
        muss weiterhin greifen."""
        result = genre_mapper.determine_genre(channel_name="kontortv")
        assert result is not None
        assert result.source in ("channel_exact", "channel_fuzzy")
        assert result.primary == "Electronic"

    def test_channel_with_official_suffix_still_matches(self, genre_mapper):
        """'trap nation official' ist WRatio 100 (Substring) gegen
        'trap nation'."""
        result = genre_mapper.determine_genre(channel_name="trap nation official")
        assert result is not None
        assert result.source in ("channel_exact", "channel_fuzzy")
        assert result.primary == "Hip Hop"
