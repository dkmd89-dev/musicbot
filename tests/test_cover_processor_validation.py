"""
Regressionstest fuer eine in Phase 3 gefundene Validierungsluecke in
CoverProcessor._validate_and_score() (services/metadata/cover_processor.py),
siehe docs/MusicBot_ENGINEERING_BASELINE.md.

_analyze_image_quality() faengt PIL-Parse-Fehler ab und liefert dann
width=0, height=0 zurueck (kein Crash). Die alte Bedingung
"if w > 0 and (w < 100 or h < 100): ignorieren" ueberprang den
Aufloesungs-Check komplett, wenn w == 0 war - ein Nicht-Bild-Blob
(z.B. eine mit HTTP 200 zurueckgegebene HTML-Fehlerseite oder sonstiger
Muell), der nur die Mindestgroesse (_MIN_IMAGE_BYTES = 5000 Bytes) erfuellt,
rutschte dadurch durch und konnte als "Cover Art" in die Audiodatei
eingebettet werden.
"""

import io
from unittest.mock import MagicMock

from PIL import Image

from services.metadata.cover_processor import (
    CoverCandidate,
    CoverProcessor,
    ScoreThreshold,
    _EARLY_EXIT_MIN_DIM,
    _MIN_IMAGE_BYTES,
)


def make_jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    if len(data) < _MIN_IMAGE_BYTES:
        data += b"\x00" * (_MIN_IMAGE_BYTES - len(data) + 100)
    return data


def make_processor():
    return CoverProcessor(cache_enabled=False)


class TestNonImageBlobIsRejected:
    def test_html_error_page_is_rejected_despite_meeting_size_minimum(self):
        processor = make_processor()
        # Groesser als _MIN_IMAGE_BYTES, aber kein gueltiges Bild.
        fake_html_error_page = b"<html><body>Not Found</body></html>" + b" " * _MIN_IMAGE_BYTES

        result = processor._validate_and_score("test_source", fake_html_error_page)

        assert result is None

    def test_random_bytes_above_size_minimum_are_rejected(self):
        processor = make_processor()
        garbage = b"\x00\x01\x02\x03" * (_MIN_IMAGE_BYTES // 2)

        result = processor._validate_and_score("test_source", garbage)

        assert result is None


class TestValidImageStillPasses:
    def test_real_image_above_min_resolution_is_accepted(self):
        processor = make_processor()
        data = make_jpeg_bytes(200, 200)

        result = processor._validate_and_score("test_source", data)

        assert result is not None
        assert result.width == 200
        assert result.height == 200

    def test_real_image_below_min_resolution_is_rejected(self):
        processor = make_processor()
        data = make_jpeg_bytes(50, 50)

        result = processor._validate_and_score("test_source", data)

        assert result is None


class TestBug003EarlyExitThresholdWasUnreachable:
    """
    Regressionstest fuer BUG-003 (docs/MusicBot_ENGINEERING_BASELINE.md):
    ScoreThreshold.EARLY_EXIT war auf 170 gesetzt, aber _calculate_score()
    deckelt den Score auf maximal 150 (min(150, ...)). Der Schwellenwert
    war dadurch strukturell unerreichbar - get_cover_art() durchlief immer
    ALLE konfigurierten Quellen, obwohl der Code explizit einen Kurzschluss
    vorsieht, sobald ein exzellentes Cover bereits gefunden wurde (reiner
    Effizienzverlust, keine falschen Cover-Auswahlen).
    """

    def test_max_possible_score_is_150(self):
        processor = make_processor()
        score = processor._calculate_score(
            source="coverartarchive",
            width=6000,
            height=6000,
            file_size=2_000_000,
            jpeg_quality=95,
            color_count=200_000,
            sharpness=1.0,
            is_square=True,
        )
        assert score == 150

    def test_early_exit_threshold_is_reachable(self):
        assert ScoreThreshold.EARLY_EXIT <= 150

    def test_top_tier_source_at_min_early_exit_resolution_meets_threshold(self):
        processor = make_processor()
        score = processor._calculate_score(
            source="coverartarchive",
            width=_EARLY_EXIT_MIN_DIM,
            height=_EARLY_EXIT_MIN_DIM,
            file_size=200_000,
            is_square=True,
        )
        assert score >= ScoreThreshold.EARLY_EXIT

    def test_get_cover_art_actually_stops_after_early_exit_candidate(self):
        """
        Orchestrierungs-Beweis: sobald die hoechstpriorisierte Quelle
        (Cover Art Archive) ein Ergebnis liefert, das die Early-Exit-
        Schwelle erreicht, duerfen NIEDRIGER priorisierte Quellen gar
        nicht erst aufgerufen werden.
        """
        processor = CoverProcessor(
            fanart_api_key="fake-key",
            lastfm_api_key="fake-key",
            cache_enabled=False,
        )

        excellent_candidate = CoverCandidate(
            source="coverartarchive",
            data=b"fake-image-bytes",
            width=_EARLY_EXIT_MIN_DIM,
            height=_EARLY_EXIT_MIN_DIM,
            total_score=150,
            is_square=True,
        )
        processor._fetch_coverartarchive = MagicMock(return_value=excellent_candidate)
        processor._fetch_fanart_album = MagicMock()
        processor._fetch_apple_music = MagicMock()
        processor._fetch_deezer = MagicMock()
        processor._fetch_fanart_artist = MagicMock()
        processor._fetch_lastfm = MagicMock()
        processor._fetch_youtube = MagicMock()

        data, source = processor.get_cover_art(
            video_id="abc123",
            release_id="rel-1",
            release_group_mbid="rg-1",
            artist_mbid="artist-1",
            artist_name="Some Artist",
            track_title="Some Title",
        )

        assert source == "coverartarchive"
        assert data == b"fake-image-bytes"
        processor._fetch_fanart_album.assert_not_called()
        processor._fetch_apple_music.assert_not_called()
        processor._fetch_deezer.assert_not_called()
        processor._fetch_fanart_artist.assert_not_called()
        processor._fetch_lastfm.assert_not_called()
        processor._fetch_youtube.assert_not_called()


class TestBuildPriorityTaskList:
    """
    Charakterisiert, welche Quellen abhaengig von verfuegbaren IDs/Keys
    aktiviert werden - jede Quelle hat eigene Mindestanforderungen.
    """

    def test_no_ids_available_yields_no_tasks(self):
        processor = make_processor()
        tasks = processor._build_priority_task_list(
            video_id=None, release_id=None, release_group_mbid=None,
            artist_mbid=None, artist_name=None, track_title=None,
        )
        assert tasks == []

    def test_fanart_sources_require_api_key_even_with_ids_present(self):
        processor = CoverProcessor(fanart_api_key=None, cache_enabled=False)
        tasks = processor._build_priority_task_list(
            video_id=None, release_id=None, release_group_mbid="rg-1",
            artist_mbid="artist-1", artist_name=None, track_title=None,
        )
        labels = [label for _, label, _ in tasks]
        assert "Fanart.tv Album" not in labels
        assert "Fanart.tv Artist" not in labels

    def test_fanart_sources_activate_with_api_key_and_ids(self):
        processor = CoverProcessor(fanart_api_key="fake-key", cache_enabled=False)
        tasks = processor._build_priority_task_list(
            video_id=None, release_id=None, release_group_mbid="rg-1",
            artist_mbid="artist-1", artist_name=None, track_title=None,
        )
        labels = [label for _, label, _ in tasks]
        assert "Fanart.tv Album" in labels
        assert "Fanart.tv Artist" in labels

    def test_apple_music_and_deezer_require_both_artist_and_title(self):
        processor = make_processor()
        tasks = processor._build_priority_task_list(
            video_id=None, release_id=None, release_group_mbid=None,
            artist_mbid=None, artist_name="Some Artist", track_title=None,
        )
        labels = [label for _, label, _ in tasks]
        assert "Apple Music" not in labels
        assert "Deezer" not in labels

    def test_youtube_produces_one_task_per_variant(self):
        from services.metadata.cover_processor import _YT_VARIANTS

        processor = make_processor()
        tasks = processor._build_priority_task_list(
            video_id="abc123", release_id=None, release_group_mbid=None,
            artist_mbid=None, artist_name=None, track_title=None,
        )
        youtube_labels = [label for _, label, _ in tasks if label.startswith("YouTube")]
        assert len(youtube_labels) == len(_YT_VARIANTS)

    def test_coverartarchive_only_needs_release_id(self):
        processor = make_processor()
        tasks = processor._build_priority_task_list(
            video_id=None, release_id="rel-1", release_group_mbid=None,
            artist_mbid=None, artist_name=None, track_title=None,
        )
        labels = [label for _, label, _ in tasks]
        assert labels == ["Cover Art Archive"]
