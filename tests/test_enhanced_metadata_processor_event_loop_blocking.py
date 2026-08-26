"""
AE-12 (docs/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md): TagWriter.write_tags()
(Schritt 17 der Metadaten-Pipeline) lief synchron und ungewrappt direkt im
Event-Loop-Thread. Seit dem AE-11-Fix (Copy+Tag+Replace statt In-Place-Save)
real gegen 10-100MB-Dateien gemessen: 0 von 0 moeglichen Heartbeat-Ticks bei
jeder getesteten Groesse, mit Laufzeiten bis 1,6s unter realer I/O-Last
(Podcast-Klasse-Dateien) - der gesamte Bot war waehrenddessen fuer ALLE
Telegram-Nutzer eingefroren.

Fix: der einzige Aufruf (enhanced_metadata_processor.py:858) wurde ueber
asyncio.to_thread() geroutet - kein Lock noetig, da TagWriter (anders als
AE-10s ChartRenderer/matplotlib.pyplot) keinen globalen mutierbaren
Zustand haelt (im Audit deterministisch mit 5 gleichzeitigen Threads auf
unterschiedlichen Dateien verifiziert, siehe
tests/test_tag_writer_write_tags_concurrent_safety.py).

Testmethodik wie bei FINDING-1/FINDING-7/AE-10/backup_handler-P1/
enhanced_status_handler-P1: deterministischer Routing-Beweis (Patch +
Aufzeichnung, kein Timing) plus ein Heartbeat-Test fuer echte
Event-Loop-Responsivitaet.

Wiederverwendet die etablierten Fixtures aus
tests/test_metadata_processor_happy_path.py (echte Sub-Prozessoren, nur
externe Dienste gefaked - siehe dortiger Moduldocstring fuer die
Begruendung).
"""

import asyncio
import time
from pathlib import Path

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


def _make_track_metadata(source: Path, video_id: str = "AE12TEST1"):
    return {
        "title": "AE12 Artist - AE12 Song (Official Video)",
        "artist": "AE12 Artist",
        "uploader": "AE12 Artist",
        "channel": "AE12 Artist",
        "id": video_id,
        "filepath": str(source),
        "genre": "Hip Hop",
    }


class TestWriteTagsRoutedThroughExecutor:
    def test_process_single_track_routes_write_tags_through_to_thread(
        self, processor, filename_fixer, tmp_path
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        calls = []
        real_to_thread = asyncio.to_thread

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        import services.metadata.enhanced_metadata_processor as emp_module

        original = emp_module.asyncio.to_thread
        emp_module.asyncio.to_thread = recording_to_thread
        try:
            result = asyncio.run(
                processor.process_single_track(
                    track_metadata=_make_track_metadata(source),
                    filename_fixer=filename_fixer,
                )
            )
        finally:
            emp_module.asyncio.to_thread = original

        assert result.success is True
        assert processor.tag_writer.write_tags in calls, (
            "write_tags() wurde nicht ueber asyncio.to_thread() aufgerufen - "
            "der Aufruf wuerde damit wieder direkt im Event-Loop-Thread "
            "laufen und diesen fuer alle Telegram-Nutzer blockieren."
        )


class TestEventLoopStaysResponsiveDuringWriteTags:
    def test_event_loop_stays_responsive_during_process_single_track(
        self, processor, filename_fixer, tmp_path, monkeypatch
    ):
        """
        Misst Heartbeat-Ticks NUR innerhalb des exakten Zeitfensters des
        (gepatchten, blockierenden) write_tags()-Aufrufs selbst - nicht
        ueber die gesamte Pipeline hinweg. process_single_track() enthaelt
        vor/nach Schritt 17 mehrere echte await-Punkte (u.a. Cover-Art-
        Lookup), die dem Heartbeat unabhaengig von write_tags() bereits
        reichlich Gelegenheit zum Ticken geben wuerden - ein Test ueber die
        Gesamtlaufzeit waere nicht diskriminierend fuer die hier zu
        beweisende Eigenschaft.
        """
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        SLEEP_SECONDS = 0.3
        TICK_INTERVAL = 0.02
        window = {}

        def blocking_write_tags(self, *args, **kwargs):
            window["start"] = time.perf_counter()
            time.sleep(SLEEP_SECONDS)
            window["end"] = time.perf_counter()

        monkeypatch.setattr(
            processor.tag_writer.__class__, "write_tags", blocking_write_tags
        )

        heartbeat_ticks = []

        async def heartbeat():
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                heartbeat_ticks.append(time.perf_counter())

        async def run_with_heartbeat():
            hb_task = asyncio.create_task(heartbeat())
            try:
                return await processor.process_single_track(
                    track_metadata=_make_track_metadata(source),
                    filename_fixer=filename_fixer,
                )
            finally:
                hb_task.cancel()

        result = asyncio.run(run_with_heartbeat())

        assert result.success is True
        assert "start" in window and "end" in window, (
            "blocking_write_tags() wurde nie aufgerufen - Test-Setup fehlerhaft"
        )
        ticks_during_window = [
            t for t in heartbeat_ticks if window["start"] <= t <= window["end"]
        ]
        expected_min_ticks = (SLEEP_SECONDS / TICK_INTERVAL) * 0.5
        assert len(ticks_during_window) >= expected_min_ticks, (
            f"Event-Loop blieb waehrend write_tags() (Fenster "
            f"{window['end'] - window['start']:.3f}s) nicht responsiv: nur "
            f"{len(ticks_during_window)} Heartbeat-Ticks INNERHALB dieses "
            f"Fensters (erwartet mind. {expected_min_ticks:.0f}) - der "
            f"blockierende Call laeuft offenbar direkt im Event-Loop-Thread "
            f"statt im Executor."
        )
