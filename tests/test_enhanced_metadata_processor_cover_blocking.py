"""
FINDING-1 (Post-Baseline-Triage, COVER-BLOCKING): CoverProcessor.get_cover_art()
ist eine synchrone Methode, die pro Track bis zu 6 Quellen sequenziell mit je
timeout=8s abfragt (worst case ~48s). Ohne asyncio.to_thread() blockierte der
Aufruf aus EnhancedMetadataProcessor.process_single_track() (async def) den
gesamten Event-Loop fuer ALLE Telegram-Nutzer, bei jedem einzelnen Track -
strukturell identisch zum bereits behobenen yt-dlp-Blocking-Fund (siehe
tests/test_download_executor.py::TestExtractInfoAsyncDoesNotBlockEventLoop).

WICHTIG zur Testmethodik: eine reine asyncio.gather()-Wettlaufprobe (wie beim
yt-dlp-Fund, wo extract_info_async() isoliert getestet wird) ist hier NICHT
zuverlaessig, da process_single_track() vor/nach dem Cover-Schritt bereits
etliche eigene await-Punkte durchlaeuft (Cache-Check, Genre-/Lyrics-Fetch
auf gefakten async-Clients) - eine parallele Coroutine koennte darueber
"ticken", unabhaengig davon, ob get_cover_art() selbst blockiert. Der
eigentliche Beweis erfolgt daher deterministisch: asyncio.to_thread() wird
am Modulpfad gepatcht und aufgezeichnet, ob get_cover_art() tatsaechlich
dort hindurch aufgerufen wird - kein Timing, kein Flackerrisiko.

Nutzt dieselbe HappyPathConfig/processor-Fixture-Struktur wie
tests/test_metadata_processor_happy_path.py (E2E-001), um process_single_track()
end-to-end mit echten Produktionsklassen laufen zu lassen - nur
cover_processor.get_cover_art() wird gefaked (Regel 7: externe Dienste
mocken).
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


class HappyPathConfig:
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
    async def fetch_metadata(self, *args, **kwargs):
        return {}


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


def _track_metadata(tmp_path, video_id="COVER123"):
    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    return {
        "title": "Cover Artist - Cover Song (Official Video)",
        "artist": "Cover Artist",
        "uploader": "Cover Artist",
        "channel": "Cover Artist",
        "id": video_id,
        "filepath": str(source),
        "genre": "Hip Hop",
    }


class TestGetCoverArtDoesNotBlockEventLoop:
    def test_get_cover_art_is_routed_through_asyncio_to_thread(
        self, processor, filename_fixer, tmp_path
    ):
        """
        Deterministischer Beweis (kein Timing/keine Racebedingung):
        get_cover_art() muss ueber asyncio.to_thread() aufgerufen werden,
        nicht direkt synchron im Event-Loop-Thread. asyncio.to_thread wird
        am Modulpfad von enhanced_metadata_processor.py gepatcht und
        zeichnet auf, welche Funktion durchgereicht wird - der echte
        asyncio.to_thread fuehrt den Aufruf danach unveraendert aus, damit
        process_single_track() weiterhin ein valides Ergebnis erhaelt.
        """
        real_to_thread = asyncio.to_thread
        calls = []

        def fake_get_cover_art(*args, **kwargs):
            return None, None

        processor.cover_processor.get_cover_art = fake_get_cover_art

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch(
            "services.metadata.enhanced_metadata_processor.asyncio.to_thread",
            side_effect=recording_to_thread,
        ):
            result = asyncio.run(
                processor.process_single_track(
                    track_metadata=_track_metadata(tmp_path),
                    filename_fixer=filename_fixer,
                )
            )

        assert result.success is True
        assert fake_get_cover_art in calls, (
            "get_cover_art() wurde nicht ueber asyncio.to_thread() aufgerufen "
            "- der Aufruf wuerde damit wieder direkt im Event-Loop-Thread "
            "laufen und diesen fuer alle Telegram-Nutzer blockieren."
        )

    def test_cover_art_result_still_used_when_found(
        self, processor, filename_fixer, tmp_path
    ):
        """
        Stellt sicher, dass asyncio.to_thread() das Ergebnis von
        get_cover_art() unveraendert durchreicht (kein stiller
        Verhaltensunterschied durch das Wrapping).
        """
        processor.cover_processor.get_cover_art = (
            lambda *a, **kw: (b"fake-cover-bytes", "coverartarchive")
        )

        result = asyncio.run(
            processor.process_single_track(
                track_metadata=_track_metadata(tmp_path, video_id="COVER456"),
                filename_fixer=filename_fixer,
            )
        )

        assert result.success is True
        assert result.cover_embedded is True
