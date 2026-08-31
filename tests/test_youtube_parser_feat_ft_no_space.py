"""
META-01 (docs/archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md, Read-Only-Audit
vom 2026-08-26): utils/youtube_parser.py verlangte in _extract_features()
(alle drei Klammer-/Plain-Varianten) und in _parse_artist_and_title()'s
feat_in_artist_pattern nach dem optionalen Punkt bei "feat"/"ft" zwingend
mindestens ein Leerzeichen (\\s+). Dadurch wurde eine gueltige
Featuring-Angabe NICHT erkannt, wenn kein Leerzeichen nach dem Punkt folgt
("feat.Artist"/"ft.Artist") - der komplette, unaufgeteilte String landete
stattdessen unveraendert im Artist-Feld bzw. blieb im Titel stehen.

Direktes Pendant zu DUP-04 (services/duplicate/detector.py, bereits in
dieser Session gefixt) - dort betraf es nur den Duplicate-Vergleich, hier
betrifft es die tatsaechliche Artist/Title-Extraktion, die in Tag und
Dateiname landet.

Fix: dieselbe Alternation wie bei DUP-04 - nach "feat"/"ft" entweder (a)
ein Punkt gefolgt von optionalem Whitespace, oder (b) mindestens ein
Leerzeichen (ohne Punkt). "featuring"/"with"/"pres" bleiben bei ihrer
bisherigen Logik (volles Wort + Pflicht-Leerzeichen bzw. optionaler
Punkt+Leerzeichen bei "pres."), da dort kein Bug nachgewiesen wurde.

Nutzt dieselbe Teststruktur wie das bestehende tests/test_youtube_parser.py
(TestExtractFeatures, TestParseYoutubeTitle) und denselben
Ueberkorrektur-Schutz-Fall ("Featherweight") wie
tests/test_duplicate_detector_feat_ft_normalization.py (DUP-04).
"""

import logging

import pytest

from utils.youtube_parser import _extract_features, parse_youtube_title


def _logger():
    return logging.getLogger("test_youtube_parser_feat_ft_no_space")


class TestExtractFeaturesNoSpaceAfterDot:
    def test_feat_dot_no_space_in_parens_is_recognized(self):
        title, features = _extract_features("Song (feat.Artist)", _logger())
        assert features == ["Artist"]
        assert title == "Song"

    def test_ft_dot_no_space_in_parens_is_recognized(self):
        title, features = _extract_features("Song (ft.Artist)", _logger())
        assert features == ["Artist"]
        assert title == "Song"

    def test_ft_dot_no_space_plain_is_recognized(self):
        title, features = _extract_features("Song ft.Artist", _logger())
        assert features == ["Artist"]
        assert title == "Song"

    def test_feat_dot_no_space_in_brackets_is_recognized(self):
        title, features = _extract_features("Song [feat.Artist]", _logger())
        assert features == ["Artist"]
        assert title == "Song"


class TestExtractFeaturesDoesNotOvercorrect:
    def test_featherweight_in_parens_is_not_treated_as_featuring(self):
        """Ueberkorrektur-Schutz (DUP-04-Pendant): 'Featherweight' beginnt
        zufaellig mit 'Feat', ist aber kein Featuring-Credit - weder vor
        noch nach dem Fix darf hier etwas extrahiert werden."""
        title, features = _extract_features("Song (Featherweight Mix)", _logger())
        assert features == []
        assert title == "Song (Featherweight Mix)"

    def test_existing_spaced_variant_still_works(self):
        """Regressionsschutz: die bereits vorher funktionierende,
        durch Leerzeichen getrennte Variante bleibt unveraendert."""
        title, features = _extract_features("Song (feat. Artist)", _logger())
        assert features == ["Artist"]
        assert title == "Song"


class TestParseYoutubeTitleFeatInArtistNoSpaceAfterDot:
    def test_feat_dot_no_space_before_separator_is_split_like_spaced_variant(self):
        """META-01-Kernfall: 'feat.Inez' (kein Leerzeichen) im Artist-Teil
        (vor dem Trennzeichen) muss zum selben Ergebnis fuehren wie die
        bereits funktionierende Leerzeichen-Variante 'feat. Inez'."""
        spaced = parse_youtube_title("Peter Fox feat. Inez - Zukunft Pink")
        no_space = parse_youtube_title("Peter Fox feat.Inez - Zukunft Pink")

        assert no_space["artist"] == spaced["artist"] == "Peter Fox"
        assert no_space["all_artists"] == spaced["all_artists"] == ["Peter Fox", "Inez"]
        assert no_space["song_title"] == spaced["song_title"] == "Zukunft Pink"

    def test_ft_dot_no_space_before_separator_is_split_like_spaced_variant(self):
        spaced = parse_youtube_title("Travis Scott ft. Drake - SICKO MODE")
        no_space = parse_youtube_title("Travis Scott ft.Drake - SICKO MODE")

        assert no_space["artist"] == spaced["artist"] == "Travis Scott"
        assert no_space["all_artists"] == spaced["all_artists"] == [
            "Travis Scott",
            "Drake",
        ]

    def test_feat_dot_no_space_after_separator_is_recognized_as_featuring(self):
        """META-01, zweiter Call-Site: 'feat.Inez' NACH dem Trennzeichen
        (im Titel-Teil, ohne Klammern) muss ueber die 'plain'-Variante von
        _extract_features als Featuring erkannt werden."""
        result = parse_youtube_title("Peter Fox - Zukunft Pink feat.Inez")
        assert result["artist"] == "Peter Fox"
        assert result["song_title"] == "Zukunft Pink"
        assert result["featuring"] == ["Inez"]


class TestParseYoutubeTitleDoesNotOvercorrect:
    def test_featherweight_remix_title_is_unaffected(self):
        """Ueberkorrektur-Schutz auf Gesamt-Parsing-Ebene: ein Artist mit
        einem 'Feat'-praefigierten, aber unrelated Namen darf nicht als
        Featuring-Split fehlinterpretiert werden."""
        result = parse_youtube_title("DJ Featherweight - Night Drive")
        assert result["artist"] == "DJ Featherweight"
        assert result["all_artists"] == ["DJ Featherweight"]
        assert result["featuring"] == []
