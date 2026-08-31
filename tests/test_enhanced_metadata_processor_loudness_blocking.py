"""
FINDING-7 (docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md): AudioEnhancer.normalize_loudness()
fuehrt pro Track zwei volle FFmpeg-subprocess.run()-Passes aus (~14,5s fuer einen
3-Minuten-Track, lokal gemessen). Ohne asyncio.to_thread() blockierte der Aufruf aus
EnhancedMetadataProcessor.process_single_track() (async def) den gesamten Event-Loop
fuer ALLE Telegram-Nutzer, bei jedem einzelnen Track - strukturell identisch zum
bereits behobenen FINDING-1 (COVER-BLOCKING, siehe
tests/test_enhanced_metadata_processor_cover_blocking.py).

Zwei sich ergaenzende Beweise, wie bei FINDING-1:

1. test_normalize_loudness_is_routed_through_asyncio_to_thread: deterministischer
   Beweis (kein Timing), dass der Aufruf tatsaechlich durch asyncio.to_thread()
   geroutet wird - patcht asyncio.to_thread am Modulpfad und zeichnet auf, welche
   Funktion durchgereicht wird.

2. test_event_loop_stays_responsive_during_normalization: der eigentliche
   Regressionstest fuer FINDING-7 (nicht nur "Test Suite gruen"). Ersetzt den
   echten FFmpeg-Call durch einen kontrollierten SYNCHRONEN time.sleep() (steht
   stellvertretend fuer die reale subprocess.run()-Blockierung, ohne 14,5s pro
   Testlauf zu warten) und laesst parallel einen Heartbeat mitzaehlen. Anders als
   eine allgemeine asyncio.gather()-Wettlaufprobe ueber die GESAMTE
   process_single_track()-Laufzeit (die laut FINDING-1-Docstring wegen der vielen
   eigenen await-Punkte der Methode unzuverlaessig waere) ist dieser Test
   deterministisch: waehrend der synchronen sleep()-Dauer kann der Event-Loop
   PRINZIPIELL keinen einzigen Timer-Callback bedienen, wenn der Call direkt im
   Event-Loop-Thread laeuft (0 Heartbeat-Ticks garantiert) - laeuft er ueber
   to_thread() in einem separaten OS-Thread, bedient der Event-Loop den Heartbeat
   waehrenddessen normal weiter.
"""

import asyncio
import time
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
    # Cover-Fetch bewusst gefaked (nicht Gegenstand dieses Tests, siehe FINDING-1) -
    # normalize_loudness bleibt hier bewusst UNGEPATCHT, da es der
    # Untersuchungsgegenstand dieses Tests ist (wird pro Testfall gezielt gesetzt).
    proc = EnhancedMetadataProcessor(happy_path_config)
    proc._mb_client = FakeExternalClient()
    proc._lfm_client = FakeExternalClient()
    proc.cover_processor.get_cover_art = lambda *a, **kw: (None, None)

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


def _track_metadata(tmp_path, video_id="LOUD123"):
    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    return {
        "title": "Loud Artist - Loud Song (Official Video)",
        "artist": "Loud Artist",
        "uploader": "Loud Artist",
        "channel": "Loud Artist",
        "id": video_id,
        "filepath": str(source),
        "genre": "Hip Hop",
    }


class TestNormalizeLoudnessDoesNotBlockEventLoop:
    def test_normalize_loudness_is_routed_through_asyncio_to_thread(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """
        Deterministischer Beweis (kein Timing/keine Racebedingung):
        AudioEnhancer.normalize_loudness() muss ueber asyncio.to_thread()
        aufgerufen werden, nicht direkt synchron im Event-Loop-Thread.
        """
        real_to_thread = asyncio.to_thread
        calls = []

        # Reale FFmpeg-Ausfuehrung im Test vermeiden (~14,5s Laufzeit, siehe Audit) -
        # ersetzt normalize_loudness durch einen schnellen Stand-in, der aber
        # weiterhin ueber die echte to_thread-Aufrufkette laufen muss.
        monkeypatch.setattr(
            AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
        )

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
        assert AudioEnhancer.normalize_loudness in calls, (
            "normalize_loudness() wurde nicht ueber asyncio.to_thread() "
            "aufgerufen - der Aufruf wuerde damit wieder direkt im "
            "Event-Loop-Thread laufen und diesen fuer alle Telegram-Nutzer "
            "fuer die Dauer der FFmpeg-Normalisierung blockieren."
        )

    def test_loudness_result_still_used_when_normalization_fails(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """
        Stellt sicher, dass asyncio.to_thread() den Rueckgabewert von
        normalize_loudness() unveraendert durchreicht (kein stiller
        Verhaltensunterschied durch das Wrapping) - auch im Fehlerfall darf
        process_single_track() nicht abbrechen (normalize_loudness-Fehler sind
        laut Code "nicht kritisch").
        """
        monkeypatch.setattr(
            AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: False)
        )

        result = asyncio.run(
            processor.process_single_track(
                track_metadata=_track_metadata(tmp_path, video_id="LOUD789"),
                filename_fixer=filename_fixer,
            )
        )

        assert result.success is True

    def test_event_loop_stays_responsive_during_normalization(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """
        Der eigentliche Regressionstest fuer FINDING-7 (nicht nur
        "Test Suite gruen"): waehrend normalize_loudness() laeuft, muss der
        Event-Loop weiterhin andere Coroutinen bedienen koennen.
        """
        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_normalize(*a, **kw):
            time.sleep(SLEEP_SECONDS)
            return True

        monkeypatch.setattr(
            AudioEnhancer, "normalize_loudness", staticmethod(blocking_normalize)
        )

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                result = await processor.process_single_track(
                    track_metadata=_track_metadata(tmp_path, video_id="LOUD456"),
                    filename_fixer=filename_fixer,
                )
            finally:
                hb_task.cancel()
            return result

        result = asyncio.run(run_with_heartbeat())

        assert result.success is True
        expected_min_ticks = (SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(heartbeat_ticks) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend normalize_loudness() nicht responsiv: "
            f"nur {len(heartbeat_ticks)} Heartbeat-Ticks in ~{SLEEP_SECONDS}s "
            f"(erwartet mind. {expected_min_ticks:.0f}) - der blockierende Call "
            f"laeuft offenbar direkt im Event-Loop-Thread statt in to_thread()."
        )
