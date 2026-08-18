"""
Unit-Tests für split_main_and_featuring()
(services/downloader/utils/metadata/models.py).

Diese Funktion hatte vor ARTISTNORM-002 KEINE direkte Testabdeckung
(nur indirekt ueber ArtistProcessor.determine_best_artist() in
tests/test_metadata_modules.py, mit unauffaelligen Namen).

Regressionstest fuer ARTISTNORM-002: dasselbe Wortgrenzen-Problem wie bei
ARTISTNORM-001 (utils/artist_map.py) - das feat/ft-Pattern matchte "ft"
als reinen Teilstring. split_main_and_featuring("Hardenacke trifft Jemand")
lieferte faelschlich ("Hardenacke trif", ["Jemand"]) statt den unsplitteten
Namen zu erhalten. Diese Funktion wird von ArtistProcessor.
determine_best_artist() genutzt (P0-Pfad, siehe ARTIST-001).
"""

import pytest

from services.downloader.utils.metadata.models import split_main_and_featuring


class TestFeatKeywordSplitting:
    def test_feat_with_period(self):
        assert split_main_and_featuring("1986zig feat. GReeeN") == (
            "1986zig",
            ["GReeeN"],
        )

    def test_ft_with_period_and_ampersand_in_features(self):
        assert split_main_and_featuring("1986zig ft. GReeeN & Sido") == (
            "1986zig",
            ["GReeeN", "Sido"],
        )

    def test_featuring_full_word(self):
        assert split_main_and_featuring("Artist featuring Other") == (
            "Artist",
            ["Other"],
        )

    def test_with_keyword(self):
        assert split_main_and_featuring("Artist with Other") == (
            "Artist",
            ["Other"],
        )

    def test_case_insensitive(self):
        assert split_main_and_featuring("Artist FEAT Other") == (
            "Artist",
            ["Other"],
        )


class TestNoFeatKeywordFallsBackToCommaAmpersand:
    def test_comma_separated(self):
        assert split_main_and_featuring("1986zig, Greeen") == (
            "1986zig",
            ["Greeen"],
        )

    def test_single_artist_unchanged(self):
        assert split_main_and_featuring("1986zig") == ("1986zig", [])

    def test_empty_string(self):
        assert split_main_and_featuring("") == ("", [])

    def test_none_like_whitespace_only(self):
        assert split_main_and_featuring("   ") == ("", [])


class TestArtistnorm002WordBoundaryFix:
    """
    Regressionstest: Woerter, die "ft"/"feat" nur als Teilstring enthalten,
    duerfen nicht mehr faelschlich als Featuring-Trenner erkannt werden.
    """

    def test_trifft_is_not_mistaken_for_ft_keyword(self):
        assert split_main_and_featuring("Hardenacke trifft Jemand") == (
            "Hardenacke trifft Jemand",
            [],
        )

    def test_kraftklub_is_not_split(self):
        assert split_main_and_featuring("Kraftklub") == ("Kraftklub", [])

    def test_draft_is_not_split(self):
        assert split_main_and_featuring("Draft Punk") == ("Draft Punk", [])

    def test_genuine_feat_after_ft_containing_word_still_splits(self):
        # Kombinierter Fall: ein Wort mit "ft"-Teilstring VOR einem echten
        # "feat."-Keyword darf das echte Splitten nicht verhindern.
        assert split_main_and_featuring("Kraftklub feat. Marteria") == (
            "Kraftklub",
            ["Marteria"],
        )
