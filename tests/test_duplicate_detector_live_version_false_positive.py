"""
DUP-03 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md /
docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md):
DuplicateDetector._clean_title_for_comparison() entfernte bisher jeglichen
Inhalt in Klammern, die mit "Live" beginnen oder mit "Version" enden, sowie
den exakten Zusatz "(Remix)" - unabhaengig davon, ob dieser Inhalt eine
bedeutungslose Marketing-Angabe oder eine echte Versions-/Aufnahme-
Kennzeichnung war. Dadurch wurden z.B. "Hello" und
"Hello (Live at Glastonbury 2016)" auf denselben bereinigten Titel
("Hello") reduziert -> identischer Content-Hash -> falsches Duplikat.

Fix: die drei zu breiten Muster (r"\\(.*?Version\\)", r"\\(Live.*?\\)",
r"\\(Remix\\)") wurden ersatzlos aus patterns_to_remove entfernt - keine
neue Regex, keine Positivliste. "(Official Video)"/"(Official Audio)"/
"[Lyrics]"/"(feat. X)"/"(ft. X)" bleiben unveraendert strippbar (separate,
nicht beruehrte Muster).

Nutzt dieselbe FakeConfig/handler-Fixture-Struktur wie
tests/test_duplicate_detector_hash_consistency.py (DUP-02).
"""

from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


class TestLiveAndVersionSuffixesAreNotFalsePositives:
    def test_live_recording_is_not_treated_as_duplicate_of_studio_version(
        self, handler
    ):
        """Test 1 (Kernfall des Bug-Reports): Studio-Original registriert,
        eine Live-Aufnahme mit spezifischer Ortsangabe darf NICHT als
        Duplikat erkannt werden."""
        handler.register_download(
            "https://www.youtube.com/watch?v=LIVE001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=LIVE002",
            raw_artist="Some Artist",
            raw_title="Hello (Live at Glastonbury 2016)",
        )

        assert is_dup is False

    def test_live_version_suffix_is_not_treated_as_duplicate(self, handler):
        """Test 2: generischer '(Live Version)'-Zusatz darf ebenfalls
        nicht zur Kollision mit dem Studio-Original fuehren."""
        handler.register_download(
            "https://www.youtube.com/watch?v=LIVEV001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=LIVEV002",
            raw_artist="Some Artist",
            raw_title="Hello (Live Version)",
        )

        assert is_dup is False

    def test_remix_is_not_treated_as_duplicate_of_original(self, handler):
        """Test 3: ein Remix ist musikalisch eine eigenstaendige Aufnahme."""
        handler.register_download(
            "https://www.youtube.com/watch?v=REMIX001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=REMIX002",
            raw_artist="Some Artist",
            raw_title="Hello (Remix)",
        )

        assert is_dup is False

    def test_radio_version_is_not_treated_as_duplicate(self, handler):
        """Test 4: '(Radio Version)' ist eine eigene Edit-Kennzeichnung,
        kein bedeutungsloser Marketing-Zusatz."""
        handler.register_download(
            "https://www.youtube.com/watch?v=RADIO001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=RADIO002",
            raw_artist="Some Artist",
            raw_title="Hello (Radio Version)",
        )

        assert is_dup is False

    def test_two_identical_live_recordings_are_still_detected_as_duplicate(
        self, handler
    ):
        """Test 5 (Regressionsschutz gegen Ueberkorrektur): zwei Reuploads
        DERSELBEN Live-Aufnahme muessen weiterhin als Duplikat erkannt
        werden - der Fix darf die grundsaetzliche Content-Matching-
        Faehigkeit fuer identische Rohtitel nicht zerstoeren."""
        handler.register_download(
            "https://www.youtube.com/watch?v=SAMELIVE1",
            "Some Artist",
            "Hello (Live at Glastonbury 2016)",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=SAMELIVE2",
            raw_artist="Some Artist",
            raw_title="Hello (Live at Glastonbury 2016)",
        )

        assert is_dup is True
        assert reason == "content"

    def test_official_video_suffix_still_detected_as_duplicate(self, handler):
        """Test 6 (Nicht-Regressions-Guard): '(Official Video)' bleibt ein
        bedeutungsloser Marketing-Zusatz und muss weiterhin gestrippt
        werden - lokale Absicherung dieser Datei, ergaenzend zu den
        bestehenden DUP-02-Tests."""
        handler.register_download(
            "https://www.youtube.com/watch?v=OFFV001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=OFFV002",
            raw_artist="Some Artist",
            raw_title="Hello (Official Video)",
        )

        assert is_dup is True
        assert reason == "content"

    def test_official_audio_suffix_still_detected_as_duplicate(self, handler):
        """Test 7 (Nicht-Regressions-Guard): '(Official Audio)' bleibt
        ebenfalls strippbar."""
        handler.register_download(
            "https://www.youtube.com/watch?v=OFFA001", "Some Artist", "Hello"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=OFFA002",
            raw_artist="Some Artist",
            raw_title="Hello (Official Audio)",
        )

        assert is_dup is True
        assert reason == "content"
