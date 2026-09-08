# tests/test_youtube_parser_feat_video_marker.py
# -*- coding: utf-8 -*-
"""
Finding F (Download-Pipeline-Testlauf 2026-09-09): ein Video-/Marketing-
Marker, der HINTER dem Feature-Namen im Titel steht
("Marteria - Verstrahlt feat. Yasha (Offizielles Musikvideo)"), landete
komplett im Feature-Artist-Namen: featuring == ['Yasha Offizielles
Musikvideo'].

Ursache: das klammerlose Feature-Pattern in _extract_features() faengt
`(.+?)$` bis Stringende (inkl. eines nachfolgenden "(...)"-Blocks); die
anschliessende Bereinigung entfernte nur die Klammer-ZEICHEN, nicht den
Marker-TEXT.

Vor dem Artist-Identity-Fix (PR #180) fiel das nicht auf, weil
feat_artists im EnhancedMetadataProcessor ohnehin verworfen wurden - seit
PR #180 landet der kaputte Wert sichtbar im ARTISTS-Tag.

Der Titel selbst wird bereits korrekt bereinigt (siehe
tests/test_title_cleaner_german_compound_video_suffix.py) - hier geht es
ausschliesslich um den Feature-Namen.
"""

from utils.youtube_parser import _extract_features, parse_youtube_title


def _log():
    import logging

    lg = logging.getLogger("test_feat_video_marker")
    if not lg.handlers:
        lg.addHandler(logging.NullHandler())
    return lg


class TestExtractFeaturesStripsTrailingMarker:
    def test_german_video_marker_after_feature_name_is_removed(self):
        title, features = _extract_features(
            "Verstrahlt feat. Yasha (Offizielles Musikvideo)", _log()
        )
        assert title == "Verstrahlt"
        assert features == ["Yasha"]

    def test_english_bracket_marker_after_feature_name_is_removed(self):
        title, features = _extract_features("Song ft. Drake [Official Video]", _log())
        assert title == "Song"
        assert features == ["Drake"]

    def test_multiple_trailing_marker_groups_are_removed(self):
        title, features = _extract_features(
            "Track feat. Someone (Official Video) (4K)", _log()
        )
        assert title == "Track"
        assert features == ["Someone"]

    # ── Regression-Guards: bereits korrekte Faelle bleiben unveraendert ──
    def test_feat_in_parens_still_works(self):
        title, features = _extract_features("Song (feat. Artist)", _log())
        assert title == "Song"
        assert features == ["Artist"]

    def test_multi_feature_split_still_works(self):
        title, features = _extract_features("Song (feat. Artist A & Artist B)", _log())
        assert title == "Song"
        assert features == ["Artist A", "Artist B"]

    def test_plain_trailing_feature_without_marker_unchanged(self):
        title, features = _extract_features("Song ft. Drake", _log())
        assert title == "Song"
        assert features == ["Drake"]


class TestParseYoutubeTitleFeatVideoMarker:
    def test_marteria_verstrahlt_feat_yasha_offizielles_musikvideo(self):
        r = parse_youtube_title(
            "Marteria - Verstrahlt feat. Yasha (Offizielles Musikvideo)"
        )
        assert r["song_title"] == "Verstrahlt"
        assert r["featuring"] == ["Yasha"]

    def test_akon_smack_that_ft_eminem_still_clean(self):
        r = parse_youtube_title("Akon - Smack That (Official Music Video) ft. Eminem")
        assert r["song_title"] == "Smack That"
        assert r["featuring"] == ["Eminem"]
