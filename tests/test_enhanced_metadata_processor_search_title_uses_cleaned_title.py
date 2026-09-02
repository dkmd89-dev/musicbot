"""
Live-Fund 2026-09-02 (Nutzer-Report, echter Testdownload im Anschluss an
die TitleCleaner-Fixes fuer Produzenten-Credits/umschliessende
Anfuehrungszeichen): der finale Titel-Tag wird korrekt bereinigt
('"ADLIBS" prod. Safecall777' -> 'ADLIBS'), aber MusicBrainz (Genre- UND
Album-Suche) sucht weiterhin mit dem UNBEREINIGTEN Titel
('"ADLIBS" prod. Safecall777') - live im Bot-Log bestaetigt:

    [GENREPROCESSOR] 🎵 MusicBrainz Suche fuer: makko - "ADLIBS" prod. Safecall777
    [MUSICBRAINZCLIENT] fetch_metadata(): artist='makko', title='"ADLIBS" prod. Safecall777'

waehrend Lyrics/Cover zur selben Zeit bereits korrekt den bereinigten
Titel 'ADLIBS' verwenden.

Root Cause, verifiziert in services/metadata/enhanced_metadata_processor.py
(Schritt 7 "Titel-Bereinigung"): `search_title_for_genre` (an
GenreProcessor UND AlbumProcessor.fetch_album_from_musicbrainz()
weitergereicht) wird ueber `TitleCleaner.build_search_title()` NEU aus
den ROHEN Quellen (`youtube_parsed.get("song_title")`/`raw_title`)
berechnet - EIN separater Pfad, der von light_title_cleanup() (und
dessen Produzenten-Credit-/Anfuehrungszeichen-Fixes) nie profitiert.
`clean_title` (der TATSAECHLICH final geschriebene, bereits vollstaendig
bereinigte Titel) wird fuer Lyrics/Cover verwendet, aber nicht fuer die
Genre-/Album-MusicBrainz-Suche.

Fix: search_title_for_genre wird jetzt aus dem bereits bereinigten
clean_title abgeleitet (build_search_title() macht darauf weiterhin
seine eigene, zusaetzliche Versions-/Remaster-Bereinigung) statt aus den
rohen Quellen neu zu rechnen - DRY, keine doppelte/abweichende
Bereinigungslogik.
"""

import asyncio
from pathlib import Path

import pytest

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.audio_enhancer import AudioEnhancer


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


class RecordingMusicBrainzClient:
    """Zeichnet jeden fetch_metadata()-Aufruf auf (title/artist), liefert
    'kein Treffer' - fuer den Beweis, WELCHEN Titel MusicBrainz
    tatsaechlich zur Suche erhaelt."""

    def __init__(self):
        self.calls = []

    async def fetch_metadata(self, title, artist):
        self.calls.append({"title": title, "artist": artist})
        return {}


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

    mb_recorder = RecordingMusicBrainzClient()
    proc._mb_client = mb_recorder
    proc._mb_recorder = mb_recorder  # fuer den Test direkt zugaenglich
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
    from utils.filenamefixer import FilenameFixerTool

    return FilenameFixerTool(happy_path_config)


def test_musicbrainz_search_uses_cleaned_title_not_raw_producer_credit(
    processor, filename_fixer, tmp_path
):
    """Kernfall, real via Live-Download reproduziert."""
    source = tmp_path / "adlibs.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

    track_metadata = {
        "title": 'makko & Beslik Meister - "ADLIBS" prod. Safecall777',
        "artist": "makko",
        "uploader": "makko",
        "channel": "makko",
        "id": "WrkE_VsdmLE",
        "filepath": str(source),
        "genre": "Hip Hop",
    }

    asyncio.run(
        processor.process_single_track(
            track_metadata=track_metadata,
            filename_fixer=filename_fixer,
        )
    )

    assert processor._mb_recorder.calls, "MusicBrainz wurde nie aufgerufen"
    for call in processor._mb_recorder.calls:
        assert '"' not in call["title"], (
            f"MusicBrainz-Suche enthielt noch Anfuehrungszeichen: {call['title']!r}"
        )
        assert "prod." not in call["title"].lower(), (
            f"MusicBrainz-Suche enthielt noch den Produzenten-Credit: "
            f"{call['title']!r}"
        )
