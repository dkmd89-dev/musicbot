"""
DUP-02 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md /
docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md): DuplicateDetector.
check_for_duplicates() hasht Artist/Titel ausschliesslich nach Normalisierung
(_normalize_artist_for_comparison/_clean_title_for_comparison), waehrend
register_download() bisher die vom Aufrufer uebergebenen Rohwerte direkt
gehasht hat. Fuer dieselbe Aufnahme konnte der beim Registrieren gespeicherte
Content-Hash dadurch strukturell vom Hash abweichen, den ein spaeterer Check
fuer denselben Content berechnet (z.B. Artist-Suffix " - Topic" oder
Titel-Zusatz "(Official Video)") - die durch Finding 1 (Baseline v5) erst
erreichbar gemachte Content-/Parser-Ebene konnte dadurch versagen.

Fix: register_download() wendet dieselbe Normalisierung wie
check_for_duplicates() an, bevor der Eintrag gehasht/gespeichert wird.

Nutzt dieselbe FakeConfig/handler-Fixture-Struktur wie
tests/test_duplicate_handler.py. Stand P1 (docs/audits/
P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md): self.
artist_normalizer/self.artist_processor sind seit dem P1-Fix immer
gesetzt (kein hasattr(config, "artist_config")-Gate mehr) - die hier
gepruefte Hash-Konsistenz gilt unveraendert ueber den jetzt echten
ArtistProcessor-Pfad.
"""

import shutil
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        # P1-Fix: ohne GENRE_MAPPING_DIR faellt ArtistNormalizer intern auf
        # das echte, relative mapping/-Verzeichnis zurueck (ISOLATION-001-
        # Muster, siehe conftest.py) und koennte echte Mapping-Dateien
        # beschreiben (z.B. case_preserve.yaml Auto-Save).
        mapping_dest = tmp_path / "mapping"
        if not mapping_dest.exists():
            shutil.copytree(
                Path(__file__).resolve().parent.parent / "mapping", mapping_dest
            )
        self.GENRE_MAPPING_DIR = mapping_dest


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


class TestRegistrationHashMatchesCheckTimeHash:
    def test_stored_entry_hash_matches_a_fresh_check_time_hash(self, handler):
        """Test 1 (Hash-Konsistenz): der beim Registrieren tatsaechlich im
        Cache verwendete Schluessel muss dem Schluessel entsprechen, den ein
        Check fuer dieselbe (bereinigte) Aufnahme unabhaengig berechnet."""
        cache = handler.duplicate_cache
        handler.register_download(
            "https://www.youtube.com/watch?v=GGG777",
            "Artist Name - Topic",
            "Cool Song (feat. Someone) [Lyrics]",
        )

        normalized_artist = handler._normalize_artist_for_comparison("Artist Name")
        cleaned_title = handler._clean_title_for_comparison(
            "Cool Song", normalized_artist
        )
        expected_hash = cache.get_content_hash(normalized_artist, cleaned_title)

        assert expected_hash in cache.content_cache

    def test_title_with_official_video_suffix_registered_matches_clean_reupload_check(
        self, handler
    ):
        """Test 2 (unterschiedliche Rohdarstellung - Titel-Suffix): Original-
        Upload hat "(Official Video)" im Titel, ein spaeterer Reupload/Check
        liefert bereits den bereinigten Titel."""
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111",
            "Some Artist",
            "Some Song (Official Video)",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="Some Artist",
            raw_title="Some Song",
        )

        assert is_dup is True
        assert reason == "content"

    def test_artist_topic_suffix_registered_matches_clean_artist_check(self, handler):
        """Test 2 (unterschiedliche Rohdarstellung - Artist-Suffix): YouTube
        haengt an automatisch generierte Kanaele haeufig " - Topic" an."""
        handler.register_download(
            "https://www.youtube.com/watch?v=CCC333",
            "Some Artist - Topic",
            "Some Song",
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=DDD444",
            raw_artist="Some Artist",
            raw_title="Some Song",
        )

        assert is_dup is True
        assert reason == "content"

    def test_check_register_check_lifecycle_detects_duplicate_on_second_check(
        self, handler
    ):
        """Test 3 (Duplicate Lifecycle): Check (kein Duplikat) -> simulierter
        erfolgreicher Download -> Registration (mit denselben Rohwerten wie
        ein echter Aufrufer, klassen/download_handler.py::
        handle_single_track_success(), sie uebergeben wuerde) -> erneuter
        Check fuer einen Reupload -> muss jetzt als Duplikat erkannt werden."""
        url1 = "https://www.youtube.com/watch?v=EEE555"

        is_dup, entry, reason = handler.check_for_duplicates(
            url1, raw_artist="Fresh Artist", raw_title="Fresh Song (Official Video)"
        )
        assert is_dup is False
        assert reason == "none"

        handler.register_download(url1, "Fresh Artist", "Fresh Song (Official Video)")

        url2 = "https://www.youtube.com/watch?v=FFF666"
        is_dup2, entry2, reason2 = handler.check_for_duplicates(
            url2, raw_artist="Fresh Artist", raw_title="Fresh Song"
        )

        assert is_dup2 is True
        assert reason2 == "content"

    def test_matching_simple_strings_without_special_formatting_still_work(
        self, handler
    ):
        """Regressionsschutz: fuer bereits einfache Strings (kein
        Suffix/Klammerzusatz) ist die Normalisierung ein No-op - deckt sich
        mit den bestehenden Tests in test_duplicate_handler.py."""
        handler.register_download(
            "https://www.youtube.com/watch?v=HHH888", "Plain Artist", "Plain Title"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=III999",
            raw_artist="Plain Artist",
            raw_title="Plain Title",
        )

        assert is_dup is True
        assert reason == "content"
        assert entry.artist == "Plain Artist"
        assert entry.title == "Plain Title"
