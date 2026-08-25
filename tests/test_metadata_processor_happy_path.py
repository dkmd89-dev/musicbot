"""
E2E-001: Reproduzierbarer Happy Path durch die Metadata-Pipeline.

Verkettet echte Produktionsklassen end-to-end:
    DuplicateDetector.check_for_duplicates (kein Duplikat)
        -> EnhancedMetadataProcessor.process_single_track
        -> FilenameFixerTool.move_to_library (intern aufgerufen)
        -> DuplicateDetector.register_download + erneuter Check (jetzt Duplikat)

Gefakt werden ausschliesslich externe Dienste (MusicBrainz, Last.fm,
Genius/Lyrics, Cover-Art-Netzwerk-Lookup, FFmpeg-Subprocess) - siehe
Regel 7 ("Externe Services in Unit-Tests mocken/faken"). Alle
Sub-Prozessoren (ArtistProcessor, TitleCleaner, GenreProcessor,
AlbumProcessor, GenreMapper, ArtistNormalizer, FilenameFixerTool) laufen
echt, inklusive echter YAML-Genre-/Artist-Regeln aus einer tmp-Kopie von
mapping/ (siehe conftest.py: mapping_dir_copy) - damit AutoLearnManager
niemals die echten Mapping-Dateien im Repo veraendert.

Kein echtes, dekodierbares Audio noetig: AudioEnhancer.normalize_loudness
ist gefakt (FFmpeg ist eine Umgebungsabhaengigkeit, kein fuer diesen Test
relevanter Kern-Pfad - ein Fehlschlag dort ist laut Code ohnehin nicht
kritisch), move_to_library macht ein reines Dateisystem-Move, und der
MP3-Tag-Schreibpfad in _write_metadata_to_file_with_lyrics faengt ein
ungueltiges ID3-Header ab und schreibt stattdessen einen leeren
ID3()-Tag - funktioniert nachweislich auch auf einer Dummy-Datei.
"""

import asyncio
from pathlib import Path

import pytest

from services.duplicate.detector import DuplicateDetector
from services.metadata.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


class HappyPathConfig:
    """Config-Attribute, die EnhancedMetadataProcessor._do_init,
    FilenameFixerTool._do_init und DuplicateDetector tatsaechlich
    lesen - alle Verzeichnisse zeigen auf tmp_path, GENRE_MAPPING_DIR auf
    eine tmp-Kopie des echten mapping/-Verzeichnisses (siehe Modul-Docstring)."""

    def __init__(self, tmp_path: Path, mapping_dir: Path):
        self.LIBRARY_DIR = tmp_path / "library"
        self.DOWNLOAD_DIR = tmp_path / "downloads"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.TEMP_DIR = tmp_path / "temp"
        self.LOG_DIR = tmp_path / "logs"
        self.GENRE_MAPPING_DIR = mapping_dir
        self.ARTIST_OVERRIDE_FILE = tmp_path / "artist_overrides.json"
        self.METADATA_CACHE_DIR = tmp_path / "metadata_cache"
        self.DUPLICATE_CACHE_DIR = tmp_path / "duplicate_cache"
        self.FANART_API_KEY = None


class FakeExternalClient:
    """Faked MusicBrainz-/Last.fm-Client: liefert 'kein Treffer'."""

    async def fetch_metadata(self, *args, **kwargs):
        return {}


class CountingFakeExternalClient(FakeExternalClient):
    """Wie FakeExternalClient, zaehlt aber Aufrufe - fuer den TEST-003-Beweis,
    dass ein Cache-Hit externe Service-Aufrufe tatsaechlich ueberspringt."""

    def __init__(self):
        self.call_count = 0

    async def fetch_metadata(self, *args, **kwargs):
        self.call_count += 1
        return await super().fetch_metadata(*args, **kwargs)


@pytest.fixture
def happy_path_config(tmp_path, mapping_dir_copy):
    return HappyPathConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(happy_path_config, monkeypatch):
    monkeypatch.setattr(
        AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
    )

    proc = EnhancedMetadataProcessor(happy_path_config)

    proc._mb_client = FakeExternalClient()
    proc._lfm_client = FakeExternalClient()

    async def fake_fetch_lyrics(*args, **kwargs):
        return None, None

    async def fake_fetch_album_from_musicbrainz(*args, **kwargs):
        return None

    monkeypatch.setattr(
        proc.lyrics_processor, "fetch_lyrics_with_fallback", fake_fetch_lyrics
    )
    monkeypatch.setattr(
        proc.album_processor,
        "fetch_album_from_musicbrainz",
        fake_fetch_album_from_musicbrainz,
    )

    return proc


@pytest.fixture
def filename_fixer(happy_path_config):
    return FilenameFixerTool(happy_path_config)


@pytest.fixture
def duplicate_handler(happy_path_config):
    return DuplicateDetector(happy_path_config)


def test_happy_path_end_to_end(
    processor, filename_fixer, duplicate_handler, happy_path_config, tmp_path
):
    url = "https://www.youtube.com/watch?v=HAPPY123"
    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Happy Artist - Happy Song (Official Video)",
        "artist": "Happy Artist",
        "uploader": "Happy Artist",
        "channel": "Happy Artist",
        "id": "HAPPY123",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    # Schritt 1: Duplicate-Check vor dem ersten Download - kein Duplikat.
    is_dup, _entry, reason = duplicate_handler.check_for_duplicates(
        url, raw_artist="Happy Artist", raw_title="Happy Song"
    )
    assert is_dup is False
    assert reason == "none"

    # Schritt 2: Volle Metadata-Pipeline.
    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert result.error is None
    assert result.from_cache is False
    assert result.is_duplicate is False
    assert result.artist == "Happy Artist"
    assert result.title

    assert result.library_path is not None
    library_path = Path(result.library_path)
    assert library_path.exists()
    assert library_path.is_relative_to(happy_path_config.LIBRARY_DIR)

    # Schritt 3: Nach erfolgreichem Download registrieren - ein zweiter
    # Versuch derselben URL muss jetzt als Duplikat erkannt werden.
    duplicate_handler.register_download(
        url, result.artist, result.title, file_path=library_path
    )
    is_dup_again, entry, reason_again = duplicate_handler.check_for_duplicates(url)
    assert is_dup_again is True
    assert reason_again == "url"
    assert entry.artist == result.artist


def test_second_call_with_same_video_id_is_a_cache_hit(
    processor, filename_fixer, tmp_path
):
    """
    TEST-003-Beweis: process_single_track() zweimal mit identischer
    track_metadata["id"] aufrufen. Der zweite Aufruf muss ein echter
    Cache-Hit sein (from_cache=True) UND die externen Service-Clients duerfen
    NICHT erneut aufgerufen werden - das ist der eigentliche Zweck des Fixes
    (vorher lief bei jedem Aufruf immer die volle Pipeline).

    Die urspruengliche Quelldatei existiert beim zweiten Aufruf bereits
    nicht mehr (move_to_library() hat sie beim ersten Durchlauf real in die
    Library verschoben) - ein Cache-Hit kehrt in process_single_track()
    aber schon in Schritt 2 (von 20) zurueck, lange vor dem erneuten
    Dateisystem-Zugriff in Schritt 14. Dass der zweite Aufruf trotzdem
    erfolgreich ist, beweist, dass die volle Pipeline tatsaechlich
    uebersprungen wurde.
    """
    source = tmp_path / "cache_test.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": "Cache Artist - Cache Song (Official Video)",
        "artist": "Cache Artist",
        "uploader": "Cache Artist",
        "channel": "Cache Artist",
        "id": "CACHEHIT123",
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Hip Hop",
    }

    mb_client = CountingFakeExternalClient()
    processor._mb_client = mb_client

    first_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )
    assert first_result.success is True
    assert first_result.from_cache is False
    assert mb_client.call_count >= 1
    calls_after_first_run = mb_client.call_count

    assert not source.exists()  # von move_to_library() bereits verschoben

    second_result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert second_result.success is True
    assert second_result.from_cache is True
    assert second_result.title == first_result.title
    assert second_result.artist == first_result.artist
    assert mb_client.call_count == calls_after_first_run


def test_missing_filepath_returns_graceful_failure(processor, filename_fixer):
    """
    Charakterisiert das globale try/except in process_single_track: ein
    fehlender 'filepath'-Schluessel loest intern ein ValueError aus, das
    NICHT nach aussen dringt, sondern als MetadataResult(success=False)
    zurueckkommt - wichtige Sicherheitsnetz-Eigenschaft der Pipeline.
    """
    track_metadata = {
        "title": "Some Artist - Some Song",
        "artist": "Some Artist",
        "uploader": "Some Artist",
        "channel": "Some Artist",
        "id": "NOFILE1",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False


def test_error_after_move_to_library_cleans_up_orphaned_source_file(
    processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
):
    """
    Temp-Cleanup Strategie C (primaer, siehe
    services/downloader/download_artifact_cleanup.py): schlaegt
    move_to_library() fehl, nachdem original_path (Schritt 14) bereits
    gebunden wurde, muss der aeussere except-Block die verwaiste
    Quelldatei in DOWNLOAD_DIR gezielt aufraeumen - vorher gab es dafuer
    keinen einzigen Cleanup-Aufruf in der gesamten Pipeline.
    """
    download_dir = happy_path_config.DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)
    source = download_dir / "orphan_candidate.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulierter move_to_library-Fehler")

    monkeypatch.setattr(filename_fixer.__class__, "move_to_library", _boom)

    track_metadata = {
        "title": "Orphan Artist - Orphan Song (Official Video)",
        "artist": "Orphan Artist",
        "uploader": "Orphan Artist",
        "channel": "Orphan Artist",
        "id": "ORPHAN1",
        "filepath": str(source),
        "genre": "Hip Hop",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False
    assert not source.exists()  # Strategie C hat die verwaiste Datei entfernt


def test_missing_filepath_error_does_not_crash_cleanup(processor, filename_fixer):
    """
    Gegenstueck zu test_missing_filepath_returns_graceful_failure: der
    Fehler tritt VOR Schritt 14 auf, original_path ist zu diesem Zeitpunkt
    noch None. Der Cleanup-Aufruf im except-Block muss das als No-op
    behandeln, ohne selbst eine Exception zu werfen.
    """
    track_metadata = {
        "title": "Some Artist - Some Song",
        "artist": "Some Artist",
        "uploader": "Some Artist",
        "channel": "Some Artist",
        "id": "NOFILE2",
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is False
    assert result.error
