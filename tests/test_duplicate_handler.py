"""
Characterization-Tests fuer die Duplicate-Detection-Pipeline
(services/duplicate/detector.py::DuplicateDetector), Phase 1 der
Engineering Baseline.

ARCH-018 Phase 2 (docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md):
der hier getestete fachliche Kern lebte urspruenglich in
handlers/duplicate_handler.py::EnhancedDuplicateHandler und wurde nach
services/duplicate/ (DuplicateCache, DuplicateDetector) extrahiert - reiner
Import-Pfad-Wechsel, Verhalten und Testkoerper unveraendert (wie in der
Characterization als Migrationspfad vorgesehen).

Vor diesem Test existierte fuer diesen Bereich ueberhaupt keine
Testabdeckung (siehe docs/archive/musicbot_REVERSE_ENGINEERED_DOCUMENTATION.md,
Abschnitt 23/27F) - schlimmer als der bekannte GenreProcessor-Fall, wo
zumindest eine (Fake-)Implementierung getestet wurde.

Waehrend der Exploration wurde ausserdem ein bislang unbekannter Bug in
check_library_duplicate() (Layer 4, "Library-Fallback") gefunden: die
Methode ruft re.sub() auf, obwohl "re" im Modul nirgends importiert war.
Jeder Aufruf loeste einen NameError aus, der vom umgebenden
"except Exception" verschluckt wurde - die Schicht lieferte in Produktion
IMMER None, unabhaengig vom tatsaechlichen Library-Inhalt. Der fehlende
Import wurde als Teil von Phase 1 ergaenzt (heute in
services/duplicate/detector.py, Import-Block); test_check_library_duplicate_finds_existing_file
und test_check_for_duplicates_end_to_end_library_fallback sind die
Regressionstests dafuer.
"""

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector
from services.downloader.models import DuplicateEntry


class FakeConfig:
    """Minimale Config-Attribute, die DuplicateDetector/DuplicateCache
    tatsaechlich lesen (getattr mit Fallback). Seit dem P1-Fix (docs/audits/
    P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md) wird
    self.artist_normalizer/self.artist_processor unconditional konstruiert -
    kein artist_config-Attribut mehr noetig (LIBRARY_DIR/ARTIST_OVERRIDE_FILE
    reichen, mit denselben Fallbacks wie in EnhancedMetadataProcessor).
    GENRE_MAPPING_DIR zeigt bewusst auf eine isolierte Kopie (nicht das
    echte mapping/) - ohne sie faellt ArtistNormalizer intern auf das
    echte, relative mapping/-Verzeichnis zurueck (ISOLATION-001-Muster,
    siehe conftest.py) und koennte echte Mapping-Dateien beschreiben."""

    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")
        mapping_dest = tmp_path / "mapping"
        if not mapping_dest.exists():
            shutil.copytree(
                Path(__file__).resolve().parent.parent / "mapping", mapping_dest
            )
        self.GENRE_MAPPING_DIR = mapping_dest


@pytest.fixture
def handler(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


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


class TestUrlHashConsistencyCache001Fix:
    """
    CACHE-001 (gefixt): get_url_hash() (genutzt von add_entry()/
    invalidate_entry() als Dict-Key) normalisierte URLs frueher nur grob
    (Query-String abschneiden), waehrend check_url_duplicate() ueber
    _normalize_url_for_cache() youtu.be/<id> und watch?v=<id> als
    dieselbe URL erkennt. get_url_hash() nutzt jetzt dieselbe Normalisierung -
    dieser Test verifiziert, dass beide Formen jetzt denselben Hash liefern
    und dass invalidate_entry() eine per anderer URL-Form registrierte
    URL findet.
    """

    def test_equivalent_youtube_urls_produce_the_same_hash(self, handler):
        cache = handler.duplicate_cache
        h1 = cache.get_url_hash("https://youtu.be/ABC123")
        h2 = cache.get_url_hash("https://www.youtube.com/watch?v=ABC123")
        h3 = cache.get_url_hash("https://www.youtube.com/watch?v=ABC123&list=PL999")
        assert h1 == h2 == h3

    def test_invalidate_entry_finds_entry_registered_under_different_url_form(
        self, handler
    ):
        handler.register_download(
            "https://youtu.be/ABC123", "Some Artist", "Some Song"
        )
        assert (
            handler.duplicate_cache.check_url_duplicate(
                "https://www.youtube.com/watch?v=ABC123"
            )
            is not None
        )

        handler.invalidate_entry(url="https://www.youtube.com/watch?v=ABC123")

        assert (
            handler.duplicate_cache.check_url_duplicate(
                "https://youtu.be/ABC123"
            )
            is None
        )


class TestShortsUrlNormalization:
    """
    P0-F (docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md): DuplicateCache.
    _normalize_url_for_cache() erkennt youtu.be/<id>, watch?v=<id> (auch
    ueber m.youtube.com/music.youtube.com, per Teilstring-Match bereits
    korrekt abgedeckt) als dieselbe Video-ID - youtube.com/shorts/<id> war
    davon bislang nicht erfasst und fiel in den generischen
    netloc+path-Zweig, wodurch ein Short und sein aequivalenter
    watch?v=-Link als ZWEI verschiedene URLs galten. Regressionstest fuer
    den P0-F-Fix, der /shorts/<id> genauso wie /watch bzw. youtu.be auf
    "youtube_video:<id>" abbildet.
    """

    def test_shorts_url_normalizes_to_same_key_as_watch_url(self, handler):
        cache = handler.duplicate_cache
        h_watch = cache.get_url_hash("https://www.youtube.com/watch?v=ABC123")
        h_shorts = cache.get_url_hash("https://www.youtube.com/shorts/ABC123")
        assert h_watch == h_shorts

    def test_shorts_reupload_of_a_watch_url_is_detected_as_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/shorts/ABC123"
        )

        assert is_dup is True
        assert reason == "url"

    def test_shorts_url_with_trailing_query_still_matches(self, handler):
        """Shorts-Links tragen z.B. gelegentlich ?feature=share - der
        Query-String darf die Video-ID-Erkennung nicht stoeren, analog zum
        bestehenden Verhalten fuer watch?v=<id>&list=... ."""
        handler.register_download(
            "https://www.youtube.com/shorts/ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/shorts/ABC123?feature=share"
        )

        assert is_dup is True
        assert reason == "url"


class TestEmbedUrlNormalization:
    """
    Charakterisierung (docs/FINDINGS_INDEX.md, 2026-09-03): analog zum
    P0-F-Shorts-Fund faellt youtube.com/embed/<id> bislang in den
    generischen netloc+path-Zweig von _normalize_url_for_cache() und gilt
    dadurch faelschlich als andere URL als der aequivalente
    watch?v=<id>-Link fuer dieselbe Video-ID.
    """

    def test_embed_url_normalizes_to_same_key_as_watch_url(self, handler):
        cache = handler.duplicate_cache
        h_watch = cache.get_url_hash("https://www.youtube.com/watch?v=ABC123")
        h_embed = cache.get_url_hash("https://www.youtube.com/embed/ABC123")
        assert h_watch == h_embed

    def test_embed_reupload_of_a_watch_url_is_detected_as_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/embed/ABC123"
        )

        assert is_dup is True
        assert reason == "url"

    def test_embed_url_with_trailing_query_still_matches(self, handler):
        """Embed-Links tragen z.B. gelegentlich ?start=30 - der
        Query-String darf die Video-ID-Erkennung nicht stoeren."""
        handler.register_download(
            "https://www.youtube.com/embed/ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/embed/ABC123?start=30"
        )

        assert is_dup is True
        assert reason == "url"


class TestLiveUrlNormalization:
    """
    Charakterisierung (docs/FINDINGS_INDEX.md, 2026-09-03): analog zum
    P0-F-Shorts-Fund faellt youtube.com/live/<id> bislang ebenfalls in den
    generischen netloc+path-Zweig von _normalize_url_for_cache() und gilt
    dadurch faelschlich als andere URL als der aequivalente
    watch?v=<id>-Link fuer dieselbe Video-ID (z.B. der spaeter verfuegbare
    VOD-Link eines beendeten Livestreams).
    """

    def test_live_url_normalizes_to_same_key_as_watch_url(self, handler):
        cache = handler.duplicate_cache
        h_watch = cache.get_url_hash("https://www.youtube.com/watch?v=ABC123")
        h_live = cache.get_url_hash("https://www.youtube.com/live/ABC123")
        assert h_watch == h_live

    def test_live_reupload_of_a_watch_url_is_detected_as_duplicate(self, handler):
        handler.register_download(
            "https://www.youtube.com/watch?v=ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/live/ABC123"
        )

        assert is_dup is True
        assert reason == "url"

    def test_live_url_with_trailing_query_still_matches(self, handler):
        """Live-Links tragen z.B. gelegentlich ?feature=share - der
        Query-String darf die Video-ID-Erkennung nicht stoeren."""
        handler.register_download(
            "https://www.youtube.com/live/ABC123", "Some Artist", "Some Song"
        )

        is_dup, entry, reason = handler.check_for_duplicates(
            "https://www.youtube.com/live/ABC123?feature=share"
        )

        assert is_dup is True
        assert reason == "url"


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
