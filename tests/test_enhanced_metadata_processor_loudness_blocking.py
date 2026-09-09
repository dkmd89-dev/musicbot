"""
FINDING-7 (docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md) + Pipeline-
Optimierung 2026-09-09: Schritt 15b der process_single_track()-Pipeline führt
einen blockierenden `subprocess.run()` aus.

Früher: AudioEnhancer.normalize_loudness() (zwei FFmpeg-Passes, ~14,5 s,
verlustbehafteter Re-Encode). Seit der Optimierung:
services.metadata.loudness_replaygain.apply_replaygain_tags() — ein EBU-R128-
Scan (rsgain ~1,5 s / FFmpeg-Analyse ~9 s), der einen ReplayGain-Tag schreibt,
ohne das Audio neu zu kodieren. Der Aufruf bleibt ein blockierender
subprocess.run() und MUSS weiterhin über asyncio.to_thread() laufen, sonst
friert der Event-Loop für ALLE Telegram-Nutzer ein.

Zwei sich ergänzende Beweise, wie bei FINDING-1:

1. test_replaygain_scan_is_routed_through_asyncio_to_thread: deterministischer
   Beweis (kein Timing), dass der Aufruf durch asyncio.to_thread() geroutet wird.

2. test_event_loop_stays_responsive_during_replaygain_scan: der eigentliche
   Regressionstest — kontrollierter SYNCHRONER time.sleep() stellvertretend für
   die reale subprocess.run()-Blockierung, parallel ein Heartbeat.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
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
    # Cover-Fetch gefaked (nicht Gegenstand dieses Tests) - apply_replaygain_tags
    # bleibt hier bewusst UNGEPATCHT (Untersuchungsgegenstand, pro Testfall gesetzt).
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


class TestReplayGainScanDoesNotBlockEventLoop:
    def test_replaygain_scan_is_routed_through_asyncio_to_thread(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """Deterministischer Beweis: apply_replaygain_tags() läuft über
        asyncio.to_thread(), nicht direkt synchron im Event-Loop-Thread."""
        real_to_thread = asyncio.to_thread
        calls = []

        fake_scan = lambda *a, **kw: (True, -5.0)  # noqa: E731
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain.apply_replaygain_tags", fake_scan
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
        assert fake_scan in calls, (
            "apply_replaygain_tags() wurde nicht über asyncio.to_thread() "
            "aufgerufen - der blockierende rsgain-/FFmpeg-subprocess.run() würde "
            "damit wieder direkt im Event-Loop-Thread laufen und diesen für alle "
            "Telegram-Nutzer für die Dauer des Scans blockieren."
        )

    def test_result_still_used_when_replaygain_scan_fails(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """asyncio.to_thread() reicht den Rückgabewert unverändert durch - auch
        bei fehlgeschlagenem Scan darf process_single_track() nicht abbrechen
        (ReplayGain-Fehler sind laut Code 'nicht kritisch')."""
        monkeypatch.setattr(
            "services.metadata.loudness_replaygain.apply_replaygain_tags",
            lambda *a, **kw: (False, None),
        )

        result = asyncio.run(
            processor.process_single_track(
                track_metadata=_track_metadata(tmp_path, video_id="LOUD789"),
                filename_fixer=filename_fixer,
            )
        )

        assert result.success is True
        assert result.loudness_normalized is False

    def test_event_loop_stays_responsive_during_replaygain_scan(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """Regressionstest für FINDING-7: während des Scans muss der
        Event-Loop weiterhin andere Coroutinen bedienen können."""
        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02

        def blocking_scan(*a, **kw):
            time.sleep(SLEEP_SECONDS)
            return (True, -5.0)

        monkeypatch.setattr(
            "services.metadata.loudness_replaygain.apply_replaygain_tags", blocking_scan
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
            f"Event-Loop blieb während apply_replaygain_tags() nicht responsiv: "
            f"nur {len(heartbeat_ticks)} Heartbeat-Ticks in ~{SLEEP_SECONDS}s "
            f"(erwartet mind. {expected_min_ticks:.0f})."
        )
