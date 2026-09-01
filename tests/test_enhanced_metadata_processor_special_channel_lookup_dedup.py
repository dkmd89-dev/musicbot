# tests/test_enhanced_metadata_processor_special_channel_lookup_dedup.py
# -*- coding: utf-8 -*-
"""
Characterization-/Regressionstest fuer einen im Rahmen des
process_single_track()-Characterization-Audits gefundenen Befund
(docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md):

EnhancedMetadataProcessor.process_single_track() rief
load_special_channels_merged(self.config) VORHER zweimal pro Track auf -
einmal beim Spezialkanal-Pre-Check (Schritt 5.5) und ein zweites Mal bei
der Auto-Learn-Sonderkanal-Ausschlusspruefung (Schritt 19b), mit exakt
demselben self.config-Argument und ohne dass self.config oder das
Zwischenergebnis zwischen beiden Aufrufen veraendert wird.

load_special_channels_merged() liest und parst dabei jedes Mal
mapping/special_channel.yaml neu von der Platte (utils/filenamefixer.py::
load_special_channels_from_yaml(), kein Caching) - eine reine, unnoetig
wiederholte synchrone Datei-I/O innerhalb eines async-Pfads. Fix: das
bereits bei Schritt 5.5 berechnete Ergebnis wird bei Schritt 19b
wiederverwendet, statt es ein zweites Mal zu berechnen.

Nutzt dieselbe Test-Infrastruktur wie test_metadata_processor_happy_path.py/
test_autolearn_special_channel_gate.py (echte Sub-Prozessoren, echte
Mapping-Dateien aus einer tmp-Kopie von mapping/, nur externe Dienste
gefaked).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import services.metadata.enhanced_metadata_processor as emp_module
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool, load_special_channels_merged


class DedupTestConfig:
    def __init__(self, tmp_path: Path, mapping_dir: Path):
        self.LIBRARY_DIR = tmp_path / "library"
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
def dedup_config(tmp_path, mapping_dir_copy):
    return DedupTestConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(dedup_config, monkeypatch):
    monkeypatch.setattr(
        AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
    )

    proc = EnhancedMetadataProcessor(dedup_config)
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
    monkeypatch.setattr(proc.auto_learn_manager, "learn_artist", AsyncMock())

    return proc


@pytest.fixture
def filename_fixer(dedup_config):
    return FilenameFixerTool(dedup_config)


def test_load_special_channels_merged_is_called_exactly_once_per_track(
    processor, filename_fixer, tmp_path, monkeypatch
):
    """
    Vor dem Fix: 2 Aufrufe (Schritt 5.5 + Schritt 19b, identisches Ergebnis,
    reine Wiederholung derselben Datei-I/O). Nach dem Fix: 1 Aufruf - das bei
    Schritt 5.5 berechnete Ergebnis wird bei Schritt 19b wiederverwendet.
    """
    call_count = 0
    real_fn = load_special_channels_merged

    def counting_wrapper(config):
        nonlocal call_count
        call_count += 1
        return real_fn(config)

    monkeypatch.setattr(emp_module, "load_special_channels_merged", counting_wrapper)

    source = tmp_path / "DEDUP1.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    track_metadata = {
        "title": "Normaler Kanal - Irgendein Titel",
        "artist": "Normaler Kanal",
        "uploader": "Normaler Kanal",
        "channel": "Normaler Kanal",
        "id": "DEDUP1",
        "filepath": str(source),
    }

    result = asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert result.success is True
    assert call_count == 1, (
        f"load_special_channels_merged() wurde {call_count}x aufgerufen, "
        f"erwartet: genau 1x (Schritt 5.5-Ergebnis muss bei Schritt 19b "
        f"wiederverwendet werden statt die special_channel.yaml erneut zu lesen)."
    )
