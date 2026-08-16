"""
Characterization-Tests fuer die Duplicate-Detection-Pipeline
(handlers/duplicate_handler.py), Phase 1 der Engineering Baseline.

Vor diesem Test existierte fuer diesen Bereich ueberhaupt keine
Testabdeckung (siehe docs/musicbot_REVERSE_ENGINEERED_DOCUMENTATION.md,
Abschnitt 23/27F) - schlimmer als der bekannte GenreProcessor-Fall, wo
zumindest eine (Fake-)Implementierung getestet wurde.

Waehrend der Exploration wurde ausserdem ein bislang unbekannter Bug in
check_library_duplicate() (Layer 4, "Library-Fallback") gefunden: die
Methode ruft re.sub() auf, obwohl "re" im Modul nirgends importiert war.
Jeder Aufruf loeste einen NameError aus, der vom umgebenden
"except Exception" verschluckt wurde - die Schicht lieferte in Produktion
IMMER None, unabhaengig vom tatsaechlichen Library-Inhalt. Der fehlende
Import wurde als Teil von Phase 1 ergaenzt (siehe handlers/duplicate_handler.py,
Import-Block); test_check_library_duplicate_finds_existing_file und
test_check_for_duplicates_end_to_end_library_fallback sind die
Regressionstests dafuer.
"""

from datetime import datetime
from pathlib import Path

import pytest

from handlers.duplicate_handler import DuplicateEntry, EnhancedDuplicateHandler


class FakeConfig:
    """Minimale Config-Attribute, die EnhancedDuplicateHandler/DuplicateCache
    tatsaechlich lesen (getattr mit Fallback) - bewusst kein artist_config,
    damit self.artist_normalizer None bleibt und die reine String-basierte
    Normalisierung charakterisiert wird."""

    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


@pytest.fixture
def handler(tmp_path):
    return EnhancedDuplicateHandler(FakeConfig(tmp_path))


# ─────────────────────────────────────────────────────────────────────────
# Layer 1: URL-Duplikat
# ─────────────────────────────────────────────────────────────────────────


class TestUrlDuplicate:
    def test_same_url_is_detected(self, handler):
        url = "https://www.youtube.com/watch?v=ABC123"
        handler.register_download(url, "Artist", "Title")

        is_dup, entry, reason = handler.check_for_duplicates(url)

        assert is_dup is True
        assert reason == "url"
        assert entry.artist == "Artist"

    def test_same_video_id_different_query_params_is_detected(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=ABC123", "Artist", "Title"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=ABC123&list=PLxyz"
        )

        assert is_dup is True
        assert reason == "url"

    def test_different_url_form_same_video_id_is_detected(self, handler):
        handler.register_download(
            "https://youtu.be/ABC123", "Artist", "Title"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=ABC123"
        )

        assert is_dup is True
        assert reason == "url"

    def test_different_video_id_is_not_a_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=ABC123", "Artist", "Title"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=XYZ999"
        )

        assert is_dup is False
        assert reason == "none"


# ─────────────────────────────────────────────────────────────────────────
# Layer 2: Content-Duplikat (Artist + Titel)
# ─────────────────────────────────────────────────────────────────────────


class TestContentDuplicate:
    def test_same_artist_and_title_is_detected(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="Some Artist",
            raw_title="Some Song",
        )

        assert is_dup is True
        assert reason == "content"

    def test_case_and_whitespace_variants_are_detected(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="  SOME artist  ",
            raw_title="  some SONG  ",
        )

        assert is_dup is True
        assert reason == "content"

    def test_different_title_same_artist_is_not_a_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="Some Artist",
            raw_title="A Completely Different Song",
        )

        assert is_dup is False
        assert reason == "none"

    def test_different_artist_same_title_is_not_a_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            raw_artist="A Totally Different Artist",
            raw_title="Some Song",
        )

        assert is_dup is False
        assert reason == "none"


# ─────────────────────────────────────────────────────────────────────────
# Layer 3: Parser-Fallback (kein raw_artist/raw_title, nur roher YT-Titel)
# ─────────────────────────────────────────────────────────────────────────


class TestParserFallback:
    def test_parsed_artist_and_title_from_raw_youtube_title_is_detected(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=AAA111", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=BBB222",
            track_metadata={"title": "Some Artist - Some Song (Official Video)"},
        )

        assert is_dup is True
        assert reason == "parsed_content"


# ─────────────────────────────────────────────────────────────────────────
# Layer 4: Library-Fallback
# ─────────────────────────────────────────────────────────────────────────


class TestLibraryFallback:
    def test_check_library_duplicate_finds_existing_file(self, handler, tmp_path):
        artist_dir = Path(handler.config.LIBRARY_DIR) / "Some Artist"
        artist_dir.mkdir(parents=True)
        (artist_dir / "Some Song.mp3").touch()

        found = handler.check_library_duplicate("Some Artist", "Some Song")

        assert found is not None
        assert found.name == "Some Song.mp3"

    def test_check_for_duplicates_end_to_end_library_fallback(self, handler):
        artist_dir = Path(handler.config.LIBRARY_DIR) / "Library Artist"
        artist_dir.mkdir(parents=True)
        (artist_dir / "Library Song.mp3").touch()

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/watch?v=NEWID1",
            raw_artist="Library Artist",
            raw_title="Library Song",
        )

        assert is_dup is True
        assert reason == "library"
        assert entry.file_path.name == "Library Song.mp3"

    def test_no_matching_library_file_returns_none(self, handler):
        found = handler.check_library_duplicate("Unknown Artist", "Unknown Song")
        assert found is None
