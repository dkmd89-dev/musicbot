"""
Characterization-Tests für utils/youtube_parser.py (P0-Pfad: Titel-/Artist-
Parsing, eingebunden in enhanced_metadata_processor.py, download_utils.py,
playlist_processor.py, duplicate_handler.py) — vorher 0 dedizierte Tests
(gefunden über eine systematische Ungetestet-Prüfung aller Quelldateien
gegen tests/-Referenzen).

Die 7 Fälle in TestParseYoutubeTitleDocumentedExamples sind direkt aus dem
eingebauten Selbsttest-Block (`if __name__ == "__main__":`) am Ende der
Produktionsdatei übernommen — vor dem Schreiben dieser Tests per
`python3 utils/youtube_parser.py` verifiziert, dass alle 7 tatsächlich
bestehen (dokumentiertes Soll-Verhalten, kein geratenes).

ARTISTNORM-002 hat bereits nachgewiesen, dass die vier feat/ft-Patterns in
diesem Modul (Zeilen 192/194/196/254) strukturell sicher gegen den
Wortgrenzen-Bug aus ARTISTNORM-001 sind (zwingendes `\\s+` statt `\\s*` vor
der feat/ft-Alternation) — TestFeatFtSubstringSafety verankert das als
dauerhaften Regressionsschutz.
"""

import pytest

from utils.youtube_parser import (
    parse_youtube_title,
    quick_parse,
    _normalize_string,
    _clean_bracket_content,
    _clean_title_suffixes,
    _split_multi_artists,
    _extract_features,
    _parse_artist_and_title,
    _get_default_logger,
)


class TestParseYoutubeTitleDocumentedExamples:
    """Aus dem eingebauten Selbsttest-Block der Produktionsdatei übernommen."""

    def test_t_low_slash_artists_no_featuring(self):
        result = parse_youtube_title(
            "t-low x Miksu/Macloud - Nur ein Trost (Official Video)"
        )
        assert result["all_artists"] == ["t-low", "Miksu", "Macloud"]
        assert result["song_title"] == "Nur ein Trost"
        assert result["featuring"] == []

    def test_t_low_comma_separated_no_x_keyword_is_not_split_on_bare_hyphen(self):
        """YTPARSE-01 (Live-Fund 2026-09-02): ohne ein " x "/"feat"-Keyword,
        das dem generischen Trennzeichen-Loop in _parse_artist_and_title()
        zuvorkommt (siehe test_t_low_slash_artists_no_featuring oben, wo das
        x-Pattern frueher greift), landete "t-low" im letzten Komma-Feld vor
        dem eigentlichen " - "-Trenner und wurde am BAREN Bindestrich in
        "t-low" selbst gesplittet: Artist-Liste enthielt faelschlich ein
        isoliertes "t" statt "t-low", der Titel begann mit dem Leak "low - ".
        """
        result = parse_youtube_title(
            "Miksu/Macloud, makko, t-low - Ich will (Official Video)"
        )
        assert result["all_artists"] == ["Miksu", "Macloud", "makko", "t-low"]
        assert result["song_title"] == "Ich will"
        assert result["featuring"] == []

    def test_peter_fox_with_remix_and_feat(self):
        result = parse_youtube_title(
            "Peter Fox - Zukunft Pink (NoooN Remix) feat. Inéz"
        )
        assert result["all_artists"] == ["Peter Fox"]
        assert result["song_title"] == "Zukunft Pink"
        assert result["featuring"] == ["Inéz"]

    def test_peter_fox_with_feat_in_parens(self):
        result = parse_youtube_title("Peter Fox - Zukunft Pink (feat. Inéz)")
        assert result["all_artists"] == ["Peter Fox"]
        assert result["song_title"] == "Zukunft Pink"
        assert result["featuring"] == ["Inéz"]

    def test_zartmann_duplicate_artist_pattern(self):
        result = parse_youtube_title(
            "Zartmann - Zartmann x Ski Aggu - wie du manchmal fehlst (prod. by Dauner)"
        )
        assert result["all_artists"] == ["Zartmann", "Ski Aggu"]
        assert result["song_title"] == "wie du manchmal fehlst"
        assert result["featuring"] == []

    def test_comma_separated_equal_artists(self):
        result = parse_youtube_title("Ski Aggu, Sido - Mein Block (Official Video) [4K]")
        assert result["all_artists"] == ["Ski Aggu", "Sido"]
        assert result["song_title"] == "Mein Block"
        assert result["featuring"] == []

    def test_x_separated_equal_artists_with_prod(self):
        result = parse_youtube_title("CIVO x Esther Graf - Gute Kinder (Prod. by Maxe)")
        assert result["all_artists"] == ["CIVO", "Esther Graf"]
        assert result["song_title"] == "Gute Kinder"
        assert result["featuring"] == []

    def test_ft_keyword_at_end_is_featuring(self):
        result = parse_youtube_title("Travis Scott - SICKO MODE (Audio) ft. Drake")
        assert result["all_artists"] == ["Travis Scott"]
        assert result["song_title"] == "SICKO MODE"
        assert result["featuring"] == ["Drake"]


class TestParseYoutubeTitleBareTrailingResolutionMarker:
    """Live-Fund 2026-09-02 (Nutzer-Report, Album 'Zartmann - 11 bis 2'):
    3 von 6 Playlist-Tracks wurden mit einer angehängten Auflösungsangabe
    ("4K"/"4k") als Songtitel getaggt, weil diese im Original-Titel NICHT
    in eigenen Klammern stand ("[Official Video] 4K", kein "[4K]") - siehe
    _clean_bracket_content()-Fix in utils/youtube_parser.py."""

    def test_mama_4k(self):
        result = parse_youtube_title(
            "Zartmann - Mama (prod. by Drumla) [Official Video] 4K"
        )
        assert result["song_title"] == "Mama"

    def test_ritalin_4k(self):
        result = parse_youtube_title(
            "Zartmann - Ritalin (prod. by Drumla) [Official Video] 4K"
        )
        assert result["song_title"] == "Ritalin"

    def test_easy_4k_lowercase_and_multi_artist(self):
        result = parse_youtube_title(
            "Zartmann x XAVER x Emileo - Easy (prod. by Drumla) [Official Video] 4k"
        )
        assert result["all_artists"] == ["Zartmann", "XAVER", "Emileo"]
        assert result["song_title"] == "Easy"


class TestParseYoutubeTitleEdgeCases:
    def test_empty_string_returns_zero_confidence(self):
        result = parse_youtube_title("")
        assert result["artist"] is None
        assert result["confidence"] == 0.0
        assert result["all_artists"] == []

    def test_none_returns_zero_confidence(self):
        result = parse_youtube_title(None)
        assert result["artist"] is None
        assert result["confidence"] == 0.0

    def test_no_separator_falls_back_to_none_artist(self):
        # parse_youtube_title()s Top-Level-Fallback (Schritt 3) ueberschreibt
        # die von _parse_artist_and_title() intern gelieferte confidence=0.3
        # hart mit 0.0 - siehe TestParseArtistAndTitle fuer die interne Stufe.
        result = parse_youtube_title("JustASingleWordTitle")
        assert result["artist"] is None
        assert result["confidence"] == 0.0
        assert result["song_title"] == "JustASingleWordTitle"

    def test_by_separator_uses_title_first_direction(self):
        result = parse_youtube_title("Some Song by Some Artist")
        assert result["artist"] == "Some Artist"
        assert result["song_title"] == "Some Song"

    def test_pipe_separator(self):
        result = parse_youtube_title("Artist Name | Song Title")
        assert result["artist"] == "Artist Name"
        assert result["song_title"] == "Song Title"

    def test_confidence_increases_with_multiple_artists(self):
        single = parse_youtube_title("Solo Artist - Some Song")
        multi = parse_youtube_title("Artist One, Artist Two - Some Song")
        assert multi["confidence"] >= single["confidence"]


class TestFeatFtSubstringSafety:
    """
    Regressionsschutz fuer den bei ARTISTNORM-001/002 gefundenen und
    andernorts gefixten Wortgrenzen-Bug: diese vier Patterns in
    youtube_parser.py verlangen bereits zwingendes \\s+ statt \\s* vor der
    feat/ft-Alternation und sind daher strukturell sicher - dieser Test
    haelt das dauerhaft fest, falls die Patterns spaeter angepasst werden.
    """

    def test_word_containing_ft_substring_is_not_treated_as_featuring(self):
        result = parse_youtube_title("Hardenacke trifft Jemand - Episode 1")
        assert result["all_artists"] == ["Hardenacke trifft Jemand"]
        assert result["featuring"] == []

    def test_kraftklub_is_not_mangled(self):
        result = parse_youtube_title("Kraftklub - Ich will nicht nach Berlin")
        assert result["all_artists"] == ["Kraftklub"]
        assert result["song_title"] == "Ich will nicht nach Berlin"


class TestSplitMultiArtists:
    def test_ampersand_separator(self):
        assert _split_multi_artists("A & B") == ["A", "B"]

    def test_x_separator(self):
        assert _split_multi_artists("A x B") == ["A", "B"]

    def test_slash_separator(self):
        assert _split_multi_artists("A/B") == ["A", "B"]

    def test_und_separator(self):
        assert _split_multi_artists("A und B") == ["A", "B"]

    def test_duplicates_are_removed_case_insensitively(self):
        assert _split_multi_artists("Zartmann, zartmann") == ["Zartmann"]

    def test_empty_string_returns_empty_list(self):
        assert _split_multi_artists("") == []

    def test_single_artist_no_separator(self):
        assert _split_multi_artists("Solo Artist") == ["Solo Artist"]


class TestExtractFeatures:
    def _logger(self):
        return _get_default_logger()

    def test_feat_in_parens(self):
        title, features = _extract_features("Song (feat. Artist)", self._logger())
        assert title == "Song"
        assert features == ["Artist"]

    def test_ft_without_parens_at_end(self):
        title, features = _extract_features("Song ft. Artist", self._logger())
        assert title == "Song"
        assert features == ["Artist"]

    def test_no_feature_keyword_returns_unchanged_title(self):
        title, features = _extract_features("Just A Song Title", self._logger())
        assert title == "Just A Song Title"
        assert features == []

    def test_multiple_features_split_correctly(self):
        title, features = _extract_features(
            "Song (feat. Artist A & Artist B)", self._logger()
        )
        assert title == "Song"
        assert features == ["Artist A", "Artist B"]


class TestParseArtistAndTitle:
    def _logger(self):
        return _get_default_logger()

    def test_dash_separator(self):
        artist, title, confidence = _parse_artist_and_title(
            "Artist - Song", self._logger()
        )
        assert artist == "Artist"
        assert title == "Song"
        assert confidence == 1.0

    def test_no_match_returns_none_artist_with_low_confidence(self):
        artist, title, confidence = _parse_artist_and_title(
            "NoSeparatorHere", self._logger()
        )
        assert artist is None
        assert confidence == 0.3


class TestCleanBracketContent:
    def test_removes_official_video_tag(self):
        assert _clean_bracket_content("Title (Official Video)") == "Title"

    def test_removes_4k_hd_tags(self):
        assert _clean_bracket_content("Title [4K] [HD]") == "Title"

    def test_removes_bare_trailing_resolution_marker(self):
        """Live-Fund 2026-09-02 (Nutzer-Report): "4K" nach "[Official
        Video]" steht NICHT in eigenen Klammern - das "\\[4k\\]"-Pattern
        greift dann nicht, "4K" blieb bisher als freistehendes Suffix
        zurück (z.B. "Zartmann - Mama (prod. by Drumla) [Official Video]
        4K" → Titel "Mama 4K" statt "Mama")."""
        assert _clean_bracket_content("Title [Official Video] 4K") == "Title"
        assert _clean_bracket_content("Title [Official Video] 4k") == "Title"
        assert _clean_bracket_content("Title 1080p") == "Title"

    def test_does_not_strip_resolution_marker_that_is_part_of_a_word(self):
        """Nur ein durch Whitespace abgetrennter, freistehender Marker am
        Titelende wird entfernt - kein Teilstring-Treffer innerhalb eines
        längeren Worts."""
        assert _clean_bracket_content("Title Ahead") == "Title Ahead"

    def test_preserves_remix_by_default(self):
        result = _clean_bracket_content("Title (Cool Remix)", preserve_remix=True)
        assert "Remix" in result

    def test_removes_remix_when_not_preserved(self):
        result = _clean_bracket_content("Title (Cool Remix)", preserve_remix=False)
        assert "Remix" not in result

    def test_does_not_remove_feat_content(self):
        # _clean_bracket_content ist bewusst NICHT fuer (feat...) zustaendig -
        # das macht _extract_features danach (siehe Kommentar in der Quelle).
        result = _clean_bracket_content("Title (feat. Artist)")
        assert "feat" in result.lower()


class TestCleanTitleSuffixes:
    def test_removes_prod_in_parens(self):
        assert _clean_title_suffixes("Title (prod. by XY)") == "Title"

    def test_removes_feat_in_parens(self):
        assert _clean_title_suffixes("Title (feat. Artist)") == "Title"

    def test_no_suffix_returns_unchanged(self):
        assert _clean_title_suffixes("Just A Title") == "Just A Title"

    def test_removes_prod_with_hyphen_separator(self):
        """Bereits vorher erkannte Form: Bindestrich vor 'prod'."""
        assert _clean_title_suffixes("Title - prod. XY") == "Title"


class TestCleanTitleSuffixesBareProdForm:
    """
    docs/FINDINGS_INDEX.md (P3, Nebenfund derselben Untersuchung wie der
    bereits gefixte reprocess_artist_metadata.py/title_cleaner.py-Fund):
    _clean_title_suffixes() deckte bisher nur die geklammerte
    ("(prod...)") und die Bindestrich-getrennte ("- prod...") Form ab -
    die klammerlose, TRENNERLOSE Form am Titelende ("Titel prod. X", ohne
    Bindestrich) wurde nicht erkannt. Live reproduziert (Artist "makko",
    Track '"ADLIBS" prod. Safecall777') - betraf auch die volle
    parse_youtube_title()-Pipeline, per Direktaufruf verifiziert.

    Analog zum bereits etablierten Fix in title_cleaner.py::
    light_title_cleanup() (dort fuer den finalen Titel-Tag bereits geloest,
    hier fuer die vorgelagerte Artist-/Titel-PARSING-Stufe) - \\bprod\\b
    mit zwingendem "."/Whitespace danach verhindert Fehltreffer in
    Woertern wie "Producer"/"Production".
    """

    def test_bare_prod_form_without_hyphen_is_removed(self):
        assert (
            _clean_title_suffixes('"ADLIBS" prod. Safecall777') == '"ADLIBS"'
        )

    def test_bare_prod_form_without_dot(self):
        assert _clean_title_suffixes("Some Song prod Safecall777") == "Some Song"

    def test_producer_word_is_not_falsely_matched(self):
        """Sicherheitsfall: 'Producer'/'Production' duerfen nicht als
        'prod'-Suffix fehlinterpretiert werden."""
        assert (
            _clean_title_suffixes("Music Producer Interview")
            == "Music Producer Interview"
        )
        assert (
            _clean_title_suffixes("Production Diary")
            == "Production Diary"
        )

    def test_end_to_end_via_parse_youtube_title_real_reproduced_case(self):
        """Der real reproduzierte Bug-Fall (docs/FINDINGS_INDEX.md) end-to-end
        ueber die volle parse_youtube_title()-Pipeline, nicht nur die
        isolierte Helper-Funktion."""
        result = parse_youtube_title('makko - "ADLIBS" prod. Safecall777')
        assert result["song_title"] == '"ADLIBS"'

    def test_empty_string_returns_empty(self):
        assert _clean_title_suffixes("") == ""


class TestNormalizeString:
    def test_collapses_multiple_spaces(self):
        assert _normalize_string("A   B") == "A B"

    def test_strips_leading_trailing_whitespace(self):
        assert _normalize_string("  A B  ") == "A B"

    def test_empty_string_returns_empty(self):
        assert _normalize_string("") == ""

    def test_none_returns_empty(self):
        assert _normalize_string(None) == ""


class TestQuickParse:
    def test_returns_artist_and_title_tuple(self):
        artist, title = quick_parse("Artist - Song")
        assert artist == "Artist"
        assert title == "Song"

    def test_empty_title_returns_none_tuple(self):
        artist, title = quick_parse("")
        assert artist is None
