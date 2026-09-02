"""
DUP-04 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md /
docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md):

DuplicateDetector._clean_title_for_comparison() verlangte in den beiden
"feat"/"ft"-Mustern nach dem optionalen Punkt zwingend mindestens ein
Leerzeichen (\\s+). Dadurch wurden gueltige Kollaborations-Angaben NICHT
erkannt/entfernt, wenn entweder "Featuring" (statt "feat"/"feat.") verwendet
wurde oder kein Leerzeichen nach dem Punkt folgte ("feat.Someone"). Zwei
Aufnahmen, die sich nur durch einen solchen Zusatz unterscheiden, wurden
faelschlich als unterschiedlicher Content gehasht -> False Negative (kein
Duplikat erkannt, obwohl es eines ist).

Fix: die beiden Muster durch eine Alternation ersetzt, die nach "feat"/"ft"
entweder (a) einen Punkt gefolgt von optionalem Whitespace, (b) bei "feat"
zusaetzlich die Zeichenfolge "uring" gefolgt von optionalem Whitespace, oder
(c) mindestens ein Leerzeichen verlangt - jede Alternative konsumiert
mindestens ein echtes, unterscheidendes Zeichen. Dadurch bleibt ein
Klammerinhalt wie "(Featherweight Mix)" unangetastet: nach "Feat" folgt
weder ein Punkt noch "uring" noch Whitespace, keine Alternative matcht,
die Klammer wird nicht entfernt (kein Ueberkorrektur-Risiko, das eine naive
Ersetzung von \\s+ durch \\s* haette).

Nutzt dieselbe FakeConfig/handler-Fixture-Struktur wie
tests/test_duplicate_detector_hash_consistency.py (DUP-02) und
tests/test_duplicate_detector_live_version_false_positive.py (DUP-03).
"""

import shutil
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        # P1-Fix (docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md):
        # DuplicateDetector konstruiert seit dem P1-Fix einen echten
        # ArtistNormalizer/ArtistProcessor - ohne GENRE_MAPPING_DIR faellt
        # ArtistNormalizer intern auf das echte, relative mapping/-Verzeichnis
        # zurueck (ISOLATION-001-Muster, siehe conftest.py) und koennte echte
        # Mapping-Dateien beschreiben (z.B. case_preserve.yaml Auto-Save).
        # Isolierte Kopie statt der conftest.py-mapping_dir_copy-Fixture, um
        # die bestehende Fixture-Signatur dieser Datei nicht anfassen zu muessen.
        mapping_dest = tmp_path / "mapping"
        if not mapping_dest.exists():
            shutil.copytree(
                Path(__file__).resolve().parent.parent / "mapping", mapping_dest
            )
        self.GENRE_MAPPING_DIR = mapping_dest


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


class TestFeatFtVariantsAreRecognizedAsDuplicates:
    def test_1_feat_dot_space_is_recognized(self, handler):
        """Test 1: 'feat. Someone' (bereits vorher funktionierender Fall,
        hier als Ausgangspunkt/Regressionsschutz)."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FEAT001", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FEAT002",
            raw_artist="Some Artist",
            raw_title="Cool Song (feat. Someone)",
        )
        assert is_dup is True
        assert reason == "content"

    def test_2_feat_dot_no_space_is_recognized(self, handler):
        """Test 2 (DUP-04-Kernfall): 'feat.Someone' ohne Leerzeichen nach
        dem Punkt."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FEAT003", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FEAT004",
            raw_artist="Some Artist",
            raw_title="Cool Song (feat.Someone)",
        )
        assert is_dup is True
        assert reason == "content"

    def test_3_ft_space_no_dot_is_recognized(self, handler):
        """Test 3: 'ft Someone' ohne Punkt (bereits vorher funktionierender
        Fall, hier als Ausgangspunkt/Regressionsschutz)."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FT001", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FT002",
            raw_artist="Some Artist",
            raw_title="Cool Song (ft Someone)",
        )
        assert is_dup is True
        assert reason == "content"

    def test_4_ft_dot_no_space_is_recognized(self, handler):
        """Test 4 (DUP-04-Kernfall): 'ft.Someone' ohne Leerzeichen nach dem
        Punkt."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FT003", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FT004",
            raw_artist="Some Artist",
            raw_title="Cool Song (ft.Someone)",
        )
        assert is_dup is True
        assert reason == "content"

    def test_5_featuring_full_word_is_recognized(self, handler):
        """Test 5 (DUP-04-Kernfall): 'Featuring' als volles Wort statt der
        Abkuerzung 'feat'/'feat.'."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FEAT005", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FEAT006",
            raw_artist="Some Artist",
            raw_title="Cool Song (Featuring Someone)",
        )
        assert is_dup is True
        assert reason == "content"

    def test_6_feat_combined_with_lyrics_suffix_is_recognized(self, handler):
        """Test 6: Kombination mit dem bereits bestehenden '[Lyrics]'-Muster
        (DUP-02-Regressionsschutz, beide Muster muessen unabhaengig weiter
        greifen)."""
        handler.register_download(
            "https://www.youtube.com/watch?v=FEAT007", "Some Artist", "Cool Song"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=FEAT008",
            raw_artist="Some Artist",
            raw_title="Cool Song (feat. Someone) [Lyrics]",
        )
        assert is_dup is True
        assert reason == "content"


class TestFeatFtFixDoesNotOvercorrect:
    def test_7_featherweight_mix_is_not_treated_as_featuring_credit(self, handler):
        """Test 7 (Ueberkorrektur-Schutz, DUP-04-Kernrisiko): 'Featherweight
        Mix' beginnt zufaellig mit 'Feat', ist aber kein Kollaborations-
        Credit - zwei unterschiedliche Remixe duerfen nicht kollidieren."""
        handler.register_download(
            "https://www.youtube.com/watch?v=OVER001",
            "Some Artist",
            "Song (Featherweight Mix)",
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=OVER002",
            raw_artist="Some Artist",
            raw_title="Song (Standard Mix)",
        )
        assert is_dup is False

    def test_8_live_version_dup03_protection_is_preserved(self, handler):
        """Test 8 (DUP-03-Regressionsschutz): Live-Aufnahme darf weiterhin
        nicht als Duplikat des Studio-Originals gelten."""
        handler.register_download(
            "https://www.youtube.com/watch?v=DUP03A", "Some Artist", "Hello"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=DUP03B",
            raw_artist="Some Artist",
            raw_title="Hello (Live at Glastonbury 2016)",
        )
        assert is_dup is False

    def test_9_remix_dup03_protection_is_preserved(self, handler):
        """Test 9 (DUP-03-Regressionsschutz): Remix darf weiterhin nicht als
        Duplikat des Originals gelten."""
        handler.register_download(
            "https://www.youtube.com/watch?v=DUP03C", "Some Artist", "Hello"
        )
        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=DUP03D",
            raw_artist="Some Artist",
            raw_title="Hello (Remix)",
        )
        assert is_dup is False
