"""
MB-01 (entdeckt via Live-Test-Download am 2026-08-26, Metadata Quality
Phase Folgeanalyse): MusicBrainzClient._get_best_match() gewichtete
Titel-Aehnlichkeit mit 70%, Artist-Aehnlichkeit nur mit 30%
(score = title_sim*0.7 + artist_sim*0.3). Ein exakter Titeltreffer
(title_sim=1.0) allein liefert dadurch bereits 0.7 - GENAU die
Config.MUSICBRAINZ_MIN_SIMILARITY-Schwelle (0.7) - unabhaengig vom
Kuenstler. Ein voellig falscher Kuenstlername konnte die Schwelle daher
allein durch einen zufaellig hohen difflib.SequenceMatcher-Score
ueberwinden.

Live reproduziert: YouTube-Titel "Yearboox - Graceland (Club Edit)"
(echter Kuenstler "Yearboox") wurde mit MusicBrainz-Aufnahme
"sweetbox - Graceland" (ein komplett anderer, unverwandter Kuenstler,
zufaellig ebenfalls mit einem Song "Graceland") gematcht:

    similarity("Graceland", "Graceland")   = 1.0  (title_sim)
    similarity("Yearboox", "sweetbox")     = 0.5  (artist_sim, nur
                                                    zufaellige "box"-
                                                    Endungs-Uebereinstimmung,
                                                    keine echte Verwandtschaft)
    score = 1.0*0.7 + 0.5*0.3 = 0.85  >= 0.70-Schwelle  -> FALSCH akzeptiert

Konsequenz im echten Testlauf: die MusicBrainz-IDs (recording/release/
release_group/artist) des Tracks gehoerten alle zu sweetbox statt zu
Yearboox - dadurch wurden Cover-Art UND Jahr ueber die falschen IDs
aufgeloest (Cover-Art-Quelle: coverartarchive via sweetbox-release_group).

Fix: zusaetzliche, harte Mindestschwelle fuer artist_sim
(Config.MUSICBRAINZ_MIN_ARTIST_SIMILARITY = 0.55, kalibriert gegen
reale Kollaborations-/Schreibweisen-Faelle wie "Travis Scott" vs.
"Travis Scott feat. Drake" [0.667] oder "Peter Fox" vs. "Peter Fox, Inez"
[0.75], die weiterhin durchgelassen werden muessen) - ein Kandidat mit
artist_sim darunter wird verworfen, AUSSER die kanonisierten
(ArtistNormalizer-normalisierten) Namen stimmen exakt ueberein (staerkeres
Signal als reine Rohstring-Aehnlichkeit).

Nutzt dieselbe Teststruktur wie tests/test_musicbrainz_client.py
(TestGetBestMatch, _make_client()-Helper).
"""

from unittest.mock import MagicMock, patch

import services.clients.musicbrainz_client as mb_module
from services.clients.musicbrainz_client import MusicBrainzClient, similarity


def _make_client(artist_normalizer=None):
    with patch.object(
        mb_module, "_get_artist_normalizer", return_value=artist_normalizer or MagicMock()
    ), patch("musicbrainzngs.set_useragent"):
        return MusicBrainzClient()


class TestGetBestMatchRejectsUnrelatedArtistWithMatchingTitle:
    def test_yearboox_sweetbox_live_case_is_rejected(self):
        """MB-01-Kernfall, real via Live-Download reproduziert."""
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Graceland", "artist-credit-phrase": "sweetbox"},
        ]
        best = client._get_best_match(recordings, "Graceland", "Yearboox")
        assert best is None

    def test_similarity_of_the_live_case_is_exactly_as_documented(self):
        """Regressionsschutz fuer die Wurzelursachen-Analyse selbst -
        stellt sicher, dass die im Docstring dokumentierten Zahlen bei
        einer difflib-Aenderung nicht stillschweigend veralten."""
        assert similarity("Graceland", "Graceland") == 1.0
        assert similarity("Yearboox", "sweetbox") == 0.5

    def test_correct_artist_with_same_title_still_wins_over_wrong_artist(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Graceland", "artist-credit-phrase": "sweetbox"},
            {"title": "Graceland (Club Edit)", "artist-credit-phrase": "Yearboox"},
        ]
        best = client._get_best_match(recordings, "Graceland", "Yearboox")
        assert best is not None
        assert best["artist-credit-phrase"] == "Yearboox"


class TestGetBestMatchStillAcceptsRealWorldNearMatches:
    """Ueberkorrektur-Schutz: legitime Schreibweisen-/Kollaborations-
    Abweichungen duerfen durch die neue Untergrenze nicht verworfen
    werden."""

    def test_featuring_credit_difference_still_matches(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {
                "title": "SICKO MODE",
                "artist-credit-phrase": "Travis Scott feat. Drake",
            }
        ]
        best = client._get_best_match(recordings, "SICKO MODE", "Travis Scott")
        assert best is not None

    def test_collaboration_credit_difference_still_matches(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Zukunft Pink", "artist-credit-phrase": "Peter Fox, Inez"}
        ]
        best = client._get_best_match(recordings, "Zukunft Pink", "Peter Fox")
        assert best is not None

    def test_case_and_spacing_variant_still_matches(self):
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [{"title": "Song", "artist-credit-phrase": "DJ SNAKE"}]
        best = client._get_best_match(recordings, "Song", "Dj Snake")
        assert best is not None

    def test_normalized_exact_match_bypasses_raw_similarity_floor(self):
        """Auch bei niedriger Rohstring-Aehnlichkeit muss ein exakter
        Treffer auf normalisierter (kanonischer) Ebene weiterhin
        durchgelassen werden - staerkeres Signal als die Heuristik."""
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: "Canonical Name"
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Song", "artist-credit-phrase": "Very Different Raw String"}
        ]
        best = client._get_best_match(recordings, "Song", "Totally Other Spelling")
        assert best is not None

    def test_existing_documented_high_scoring_case_still_works(self):
        """Deckungsgleich mit
        test_musicbrainz_client.py::TestGetBestMatch::test_selects_highest_scoring_recording_above_threshold."""
        normalizer = MagicMock()
        normalizer.normalize.side_effect = lambda x: x
        client = _make_client(artist_normalizer=normalizer)

        recordings = [
            {"title": "Totally Different Song", "artist-credit-phrase": "Nobody"},
            {"title": "Bohemian Rhapsody", "artist-credit-phrase": "Queen"},
        ]
        best = client._get_best_match(recordings, "Bohemian Rhapsody", "Queen")
        assert best["title"] == "Bohemian Rhapsody"
