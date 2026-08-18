"""
Regressionstest fuer AUTOLEARN-001 (docs/MusicBot_ENGINEERING_BASELINE.md):
EnhancedMetadataProcessor.process_single_track() prueft beim Auto-Learning-
Schritt (19b) den Kanal nur gegen eine hartcodierte 2-Namen-Podcast-Liste
(_is_podcast_channel = {"backstage boxengasse", "sky sport formel 1"}),
waehrend download_utils.py fuer seinen (mittlerweile entfernten, redundanten)
externen learn_artist()-Aufruf die vollstaendige special_channel.yaml-
Konfiguration abfragte (get_special_category/load_special_channels_merged).

Fuer Sonderkanaele wie "Gemischtes Hack" oder "Hardenacke trifft" (beide in
mapping/special_channel.yaml als Podcast gelistet, aber NICHT in der
hartcodierten 2-Namen-Liste) haette process_single_track() vor dem Fix
faelschlich einen Artist-Alias gelernt. Der Fix erweitert die interne
Ausschluss-Pruefung um dieselbe breite special_channel.yaml-Abfrage (nur
zusaetzlich einschraenkend, nie lockernd - siehe Kommentar im Produktions-
code direkt an der Fix-Stelle).

Nutzt dieselbe Test-Infrastruktur wie tests/test_metadata_processor_happy_path.py
(echte Sub-Prozessoren, echte Mapping-Dateien aus einer tmp-Kopie von mapping/,
nur externe Dienste gefaked).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from services.downloader.utils.enhanced_metadata_processor import (
    EnhancedMetadataProcessor,
)
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


class GateTestConfig:
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
def gate_config(tmp_path, mapping_dir_copy):
    return GateTestConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(gate_config, monkeypatch):
    monkeypatch.setattr(
        AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
    )

    proc = EnhancedMetadataProcessor(gate_config)
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
def filename_fixer(gate_config):
    return FilenameFixerTool(gate_config)


def _run(processor, filename_fixer, tmp_path, channel: str, video_id: str):
    source = tmp_path / f"{video_id}.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": f"{channel} - Irgendein Titel",
        "artist": channel,
        "uploader": channel,
        "channel": channel,
        "id": video_id,
        "filepath": str(source),
    }
    return asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            file_utils=None,
            filename_fixer=filename_fixer,
        )
    )


class TestSpecialChannelSkipsAutoLearn:
    @pytest.mark.parametrize("channel", ["Gemischtes Hack", "Mordlust"])
    def test_channel_from_special_channel_yaml_is_excluded(
        self, processor, filename_fixer, tmp_path, channel
    ):
        """
        Regressionstest: 'Gemischtes Hack'/'Mordlust' stehen in
        mapping/special_channel.yaml (Kategorie Podcast), sind aber NICHT
        in der hartcodierten _is_podcast_channel-Liste. Vor dem Fix haette
        process_single_track() hierfuer trotzdem learn_artist() aufgerufen.

        Bewusst NICHT 'Hardenacke trifft' als Beispiel verwendet: beim
        Schreiben dieses Tests aufgefallener, unabhaengiger Befund -
        ArtistNormalizer.normalize() mangelt "Hardenacke trifft" zu
        "Hardenacke Trif" (die Collaboration-Split-Logik scheint das "ft"
        in "tri-ft-t" faelschlich als Featuring-Marker zu erkennen), wodurch
        der Kanalname bereits VOR der hier getesteten Sonderkanal-Pruefung
        veraendert wird. Eigenstaendiger, hier nicht behobener Befund -
        siehe Baseline-Eintrag ARTISTNORM-001.
        """
        result = _run(processor, filename_fixer, tmp_path, channel, "SPECIAL1")

        assert result.success is True
        processor.auto_learn_manager.learn_artist.assert_not_called()

    def test_hardcoded_podcast_channel_is_still_excluded(
        self, processor, filename_fixer, tmp_path
    ):
        """
        Regressionsschutz: die urspruengliche, hartcodierte Pruefung
        (_is_podcast_channel) darf durch die Erweiterung nicht verloren
        gehen - 'Backstage Boxengasse' war schon vorher ausgeschlossen.
        """
        result = _run(
            processor, filename_fixer, tmp_path, "Backstage Boxengasse", "PODCAST1"
        )

        assert result.success is True
        processor.auto_learn_manager.learn_artist.assert_not_called()

    def test_normal_channel_not_in_any_special_list_still_triggers_learning(
        self, processor, filename_fixer, tmp_path
    ):
        """
        Gegenprobe: ein ganz gewoehnlicher Kanalname (nicht in
        special_channel.yaml, kein hartcodierter Podcast) muss weiterhin
        normal zum Auto-Learning-Aufruf fuehren - der Fix darf legitimes
        Lernen nicht unterdruecken.
        """
        result = _run(
            processor, filename_fixer, tmp_path, "Ganz Normaler Musikkanal", "NORMAL1"
        )

        assert result.success is True
        processor.auto_learn_manager.learn_artist.assert_called_once()
