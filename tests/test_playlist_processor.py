"""
Unit-Tests für PlaylistProcessor (services/downloader/playlist_processor.py)
— vorher 0 Tests, live in EnhancedDownloadProcessor verdrahtet
(download_utils.py:116 `self.playlist_processor = PlaylistProcessor(...)`),
gefunden über die systematische Ungetestet-Prüfung.

Die meisten Tests umgehen `__init__` bewusst via `object.__new__`, da das
echte `__init__` intern `from config import Config; config = Config()` und
einen echten `ArtistNormalizer` (Library-Scan!) aufbaut - fuer isolierte
Method-Tests reicht die direkte Attribut-Injektion (etabliertes Muster aus
BUG-009/test_progress_tracker.py). Ein eigener TestInit-Block deckt das
echte __init__-Verhalten (Erfolgs- und Fallback-Pfad) gesondert ab.

BUG-012: _extract_year_from_playlist() hatte fuer upload_date/release_date
(yt-dlp-Format YYYYMMDD) denselben \b-Wortgrenzen-Bug wie BUG-010 in
YearResolver - siehe TestExtractYearFromPlaylist.test_year_from_upload_date.

LEGACY-012: die vormals hier definierte Standalone-Funktion
_determine_dominant_year_from_playlist() wurde entfernt - keine Aufrufer
ausserhalb dieser Datei, download_utils.py definiert eine eigene,
gleichnamige Ersatzfunktion, die an YearResolver delegiert.
"""

from unittest.mock import Mock

import pytest

from services.downloader import playlist_processor as pp_module
from services.downloader.playlist_processor import PlaylistProcessor


def make_processor(artist_normalizer=None, enhanced=True, threshold=0.6):
    proc = object.__new__(PlaylistProcessor)
    proc.logger = Mock()
    proc.logger_factory = None
    proc.dominant_artist_threshold = threshold
    proc.artist_normalizer = artist_normalizer
    proc.enhanced_processing_enabled = enhanced
    return proc


# ─────────────────────────────────────────────────────────────────────────
# __init__ – echter Konstruktionspfad
# ─────────────────────────────────────────────────────────────────────────


class TestInit:
    def test_init_success_path_enables_enhanced_processing(self, monkeypatch):
        fake_normalizer_instance = Mock()
        fake_normalizer_cls = Mock(return_value=fake_normalizer_instance)
        monkeypatch.setattr(pp_module, "ArtistNormalizer", fake_normalizer_cls)

        proc = PlaylistProcessor(logger_factory=lambda name: Mock())

        assert proc.artist_normalizer is fake_normalizer_instance
        assert proc.enhanced_processing_enabled is True

    def test_init_falls_back_gracefully_when_artist_normalizer_construction_fails(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            pp_module,
            "ArtistNormalizer",
            Mock(side_effect=RuntimeError("boom")),
        )

        proc = PlaylistProcessor(logger_factory=lambda name: Mock())

        assert proc.artist_normalizer is None
        assert proc.enhanced_processing_enabled is False

    def test_init_without_logger_factory_uses_default_logger(self, monkeypatch):
        monkeypatch.setattr(
            pp_module, "ArtistNormalizer", Mock(side_effect=RuntimeError("boom"))
        )

        proc = PlaylistProcessor()

        assert proc.logger is not None


# ─────────────────────────────────────────────────────────────────────────
# determine_dominant_artist
# ─────────────────────────────────────────────────────────────────────────


class TestDetermineDominantArtist:
    def test_empty_playlist_returns_none(self):
        proc = make_processor(enhanced=False)
        assert proc.determine_dominant_artist([]) is None

    def test_no_valid_artists_returns_none(self):
        proc = make_processor(enhanced=False)
        tracks = [{"artist": "", "uploader": ""}, {"artist": None, "uploader": None}]
        assert proc.determine_dominant_artist(tracks) is None

    def test_dominant_artist_above_threshold_without_normalizer(self):
        proc = make_processor(artist_normalizer=None, enhanced=False)
        tracks = [
            {"artist": "Some Artist"},
            {"artist": "Some Artist"},
            {"artist": "Some Artist"},
            {"artist": "Other Artist"},
        ]
        result = proc.determine_dominant_artist(tracks)
        assert result == "Some Artist"

    def test_no_dominant_artist_below_threshold(self):
        proc = make_processor(artist_normalizer=None, enhanced=False)
        tracks = [
            {"artist": "Artist A"},
            {"artist": "Artist B"},
            {"artist": "Artist C"},
        ]
        result = proc.determine_dominant_artist(tracks)
        assert result is None

    def test_uses_normalizer_when_enhanced_and_available(self):
        normalizer = Mock()
        normalizer.normalize.side_effect = lambda name: f"Normalized {name}"
        # keine Kollaboration / kein bekannter Artist -> Override-Pfad liefert None
        normalizer.library_artists = set()
        normalizer.overrides = {}
        proc = make_processor(artist_normalizer=normalizer, enhanced=True)
        tracks = [{"artist": "Raw Artist"}] * 3 + [{"artist": "Other"}]

        result = proc.determine_dominant_artist(tracks)

        assert result == "Normalized Raw Artist"

    def test_uses_youtube_parser_candidate_when_enhanced(self, monkeypatch):
        monkeypatch.setattr(
            pp_module,
            "parse_youtube_title",
            Mock(return_value={"artist": "Parsed Artist"}),
        )
        proc = make_processor(artist_normalizer=None, enhanced=True)
        tracks = [{"title": "Parsed Artist - Song", "artist": None, "uploader": "Channel X"}] * 3

        result = proc.determine_dominant_artist(tracks)

        assert result == "Parsed Artist"

    def test_youtube_parser_exception_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            pp_module,
            "parse_youtube_title",
            Mock(side_effect=RuntimeError("boom")),
        )
        proc = make_processor(artist_normalizer=None, enhanced=True)
        tracks = [{"title": "X - Y", "artist": "Fallback Artist"}] * 3

        result = proc.determine_dominant_artist(tracks)

        assert result == "Fallback Artist"

    def test_override_priority_wins_even_below_normal_threshold(self):
        normalizer = Mock()
        normalizer.normalize.side_effect = lambda name: name
        normalizer.library_artists = {"Known Artist"}
        normalizer.overrides = {}
        proc = make_processor(artist_normalizer=normalizer, enhanced=True, threshold=0.6)
        # "Known Artist" hat nur 33% (< 0.6 Standard-Schwelle), aber >= 0.3
        # Override-Schwelle UND ist in library_artists bekannt.
        tracks = [
            {"artist": "Known Artist"},
            {"artist": "Unknown One"},
            {"artist": "Unknown Two"},
        ]

        result = proc.determine_dominant_artist(tracks)

        assert result == "Known Artist"


# ─────────────────────────────────────────────────────────────────────────
# _extract_collaboration_artists
# ─────────────────────────────────────────────────────────────────────────


class TestExtractCollaborationArtists:
    def test_empty_string_returns_empty_list(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("") == []

    def test_single_artist_no_collaboration(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("Solo Artist") == ["Solo Artist"]

    def test_comma_separated(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("Artist A, Artist B") == [
            "Artist A",
            "Artist B",
        ]

    def test_x_separator_lowercase_and_uppercase(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("Artist A x Artist B") == [
            "Artist A",
            "Artist B",
        ]
        assert proc._extract_collaboration_artists("Artist A X Artist B") == [
            "Artist A",
            "Artist B",
        ]

    def test_ampersand_separator(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("Artist A & Artist B") == [
            "Artist A",
            "Artist B",
        ]

    def test_lowercase_feat_dot_separator(self):
        proc = make_processor()
        assert proc._extract_collaboration_artists("Artist A feat. Artist B") == [
            "Artist A",
            "Artist B",
        ]

    def test_capitalized_feat_is_not_recognized_as_separator(self):
        """
        Charakterisierung einer bestehenden Lücke: separators enthaelt nur
        " feat. " (klein), keine Grossschreibvariante ("Feat.") - anders als
        beim " x "/" X "-Paar, das beide Faelle abdeckt. Grossgeschriebenes
        "Feat." wird daher NICHT als Kollaborations-Trenner erkannt.
        """
        proc = make_processor()
        result = proc._extract_collaboration_artists("Artist A Feat. Artist B")
        assert result == ["Artist A Feat. Artist B"]


# ─────────────────────────────────────────────────────────────────────────
# _clean_artist_name
# ─────────────────────────────────────────────────────────────────────────


class TestCleanArtistName:
    def test_empty_returns_empty_string(self):
        proc = make_processor()
        assert proc._clean_artist_name("") == ""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Some Artist - Topic", "Some Artist"),
            ("Some Artist VEVO", "Some Artist"),
            ("Some Artist Official", "Some Artist"),
            ("Some Artist Music", "Some Artist"),
            ("Some Artist Records", "Some Artist"),
            ("Various Artists", ""),
        ],
    )
    def test_suffix_cleanup(self, raw, expected):
        proc = make_processor()
        assert proc._clean_artist_name(raw) == expected

    def test_collapses_whitespace(self):
        proc = make_processor()
        assert proc._clean_artist_name("Some    Artist") == "Some Artist"


# ─────────────────────────────────────────────────────────────────────────
# _is_artist_known / _find_dominant_override_artist / _normalize_with_override_priority
# ─────────────────────────────────────────────────────────────────────────


class TestIsArtistKnown:
    def test_no_normalizer_returns_false(self):
        proc = make_processor(artist_normalizer=None)
        assert proc._is_artist_known("X", "X") is False

    def test_known_via_library_artists(self):
        normalizer = Mock()
        normalizer.library_artists = {"Known Artist"}
        normalizer.overrides = {}
        proc = make_processor(artist_normalizer=normalizer)
        assert proc._is_artist_known("raw", "Known Artist") is True

    def test_known_via_override_key(self):
        normalizer = Mock()
        normalizer.library_artists = set()
        normalizer.overrides = {"Raw Name": "Canonical"}
        proc = make_processor(artist_normalizer=normalizer)
        assert proc._is_artist_known("raw name", "Canonical Whatever") is True

    def test_unknown_returns_false(self):
        normalizer = Mock()
        normalizer.library_artists = set()
        normalizer.overrides = {}
        proc = make_processor(artist_normalizer=normalizer)
        assert proc._is_artist_known("X", "X") is False

    def test_exception_is_swallowed_and_returns_false(self):
        normalizer = Mock()
        type(normalizer).library_artists = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        proc = make_processor(artist_normalizer=normalizer)
        assert proc._is_artist_known("X", "X") is False


class TestNormalizeWithOverridePriority:
    def test_no_normalizer_falls_back_to_clean_artist_name(self):
        proc = make_processor(artist_normalizer=None)
        result = proc._normalize_with_override_priority("Some Artist - Topic")
        assert result == "Some Artist"

    def test_direct_normalize_hit(self):
        normalizer = Mock()
        normalizer.normalize.return_value = "Canonical Artist"
        proc = make_processor(artist_normalizer=normalizer)
        result = proc._normalize_with_override_priority("Raw Artist")
        assert result == "Canonical Artist"

    def test_unknown_normalize_result_falls_through_to_collaboration_check(self):
        normalizer = Mock()
        normalizer.normalize.side_effect = lambda name: (
            "unknown" if " x " in name.lower() else name
        )
        normalizer.library_artists = set()
        normalizer.overrides = {}
        proc = make_processor(artist_normalizer=normalizer)

        result = proc._normalize_with_override_priority("Artist A x Artist B")

        # "unknown" fuer den gesamten String -> Kollaborationspfad -> kein
        # bekannter Artist -> Fallback: ersten Artist der Kollaboration
        # normalisieren ("Artist A" wird individuell normalisiert = nicht
        # "unknown", da kein " x " mehr enthalten).
        assert result == "Artist A"


# ─────────────────────────────────────────────────────────────────────────
# clean_track_title
# ─────────────────────────────────────────────────────────────────────────


class TestCleanTrackTitle:
    def test_empty_title_returns_placeholder(self):
        proc = make_processor(enhanced=False)
        assert proc.clean_track_title("") == "Unbekannter Titel"

    def test_youtube_parser_result_used_when_enhanced(self, monkeypatch):
        monkeypatch.setattr(
            pp_module,
            "parse_youtube_title",
            Mock(return_value={"song_title": "Clean Song Title"}),
        )
        proc = make_processor(enhanced=True)
        result = proc.clean_track_title("Some Raw Title (Official Video)")
        assert result == "Clean Song Title"

    def test_youtube_parser_exception_falls_back_to_regex_cleanup(self, monkeypatch):
        monkeypatch.setattr(
            pp_module, "parse_youtube_title", Mock(side_effect=RuntimeError("boom"))
        )
        proc = make_processor(enhanced=True)
        result = proc.clean_track_title("Song Title (Official Video)")
        assert result == "Song Title"

    def test_fallback_removes_artist_prefix(self):
        proc = make_processor(enhanced=False)
        result = proc.clean_track_title("Artist Name - Song Title", artist="Artist Name")
        assert result == "Song Title"

    def test_fallback_removes_feat_parenthetical(self):
        proc = make_processor(enhanced=False)
        result = proc.clean_track_title("Song Title (feat. Other Artist)")
        assert result == "Song Title"

    def test_fallback_too_short_result_returns_original(self):
        proc = make_processor(enhanced=False)
        # Nach Entfernen von "(Official Video)" bleibt "X" - unter 2 Zeichen
        # nicht moeglich hier, also erzwingen wir ueber Topic-Pattern:
        result = proc.clean_track_title("- Topic")
        # "- Topic" -> Topic-Pattern matcht "- Topic" -> "" -> zu kurz -> Original
        assert result == "- Topic"


# ─────────────────────────────────────────────────────────────────────────
# process_playlist_metadata
# ─────────────────────────────────────────────────────────────────────────


class TestProcessPlaylistMetadata:
    def test_full_run_with_dominant_artist(self, monkeypatch):
        monkeypatch.setattr(
            pp_module,
            "parse_youtube_title",
            Mock(return_value={"song_title": None}),
        )
        proc = make_processor(artist_normalizer=None, enhanced=False)
        tracks = [
            {"artist": "Dominant Artist", "title": "Song One (Official Video)"},
            {"artist": "Dominant Artist", "title": "Song Two (Official Video)"},
            {"artist": "Dominant Artist", "title": "Song Three (Official Video)"},
        ]
        playlist_info = {"title": "My Playlist 2021"}

        result = proc.process_playlist_metadata(tracks, playlist_info)

        assert result["dominant_artist"] == "Dominant Artist"
        assert result["has_dominant_artist"] is True
        assert result["track_count"] == 3
        assert result["album"] == "My Playlist 2021"
        assert result["album_artist"] == "Dominant Artist"
        assert result["year"] == 2021
        assert result["tracks"][0]["track_number"] == 1
        assert result["tracks"][0]["original_youtube_title"] == "Song One (Official Video)"
        assert result["tracks"][0]["artist"] == "Dominant Artist"

    def test_no_dominant_artist_uses_various_artists(self):
        proc = make_processor(artist_normalizer=None, enhanced=False)
        tracks = [
            {"artist": "Artist A", "title": "Song A"},
            {"artist": "Artist B", "title": "Song B"},
        ]
        result = proc.process_playlist_metadata(tracks, {"title": "Mix"})

        assert result["dominant_artist"] is None
        assert result["has_dominant_artist"] is False
        assert result["album_artist"] == "Various Artists"
        # Ohne dominanten Artist wird pro Track der bereinigte Roh-Artist genutzt
        assert result["tracks"][0]["artist"] == "Artist A"
        assert result["tracks"][1]["artist"] == "Artist B"


# ─────────────────────────────────────────────────────────────────────────
# _extract_year_from_playlist
# ─────────────────────────────────────────────────────────────────────────


class TestExtractYearFromPlaylist:
    def test_year_from_title(self):
        proc = make_processor()
        year = proc._extract_year_from_playlist({"title": "Best of 2019 Mix"})
        assert year == 2019

    def test_year_from_upload_date(self):
        proc = make_processor()
        year = proc._extract_year_from_playlist({"upload_date": "20180512"})
        assert year == 2018

    def test_no_year_found_returns_none(self):
        proc = make_processor()
        assert proc._extract_year_from_playlist({"title": "No Year Here"}) is None

    def test_priority_title_before_upload_date(self):
        proc = make_processor()
        year = proc._extract_year_from_playlist(
            {"title": "Compiled in 2015", "upload_date": "20200101"}
        )
        assert year == 2015
