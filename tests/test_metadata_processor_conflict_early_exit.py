"""
D.13-Follow-up: Ein unterlegener Download (move_to_library() liefert
renamed_due_to_conflict=True, weil ein paralleler Lauf denselben Zielnamen
zuerst belegt hat) darf danach keine persistierenden Folgeaktionen mehr
ausloesen.

Ohne Frueh-Return in EnhancedMetadataProcessor.process_single_track() lief der
Verlierer weiter durch Schritt 19 (MetadataCache-Store), 19b (learn_genre/
learn_artist), 19c (Feature-Artist-Beobachtung) und 19d (Resolver-Refresh):

  * der Cache-Store ueberschrieb den Eintrag des Gewinners (gleicher
    Artist/Titel-Schluessel, video_id-Index) mit dem Pfad der kollidierten
    " (1)"-Kopie, die der Aufrufer anschliessend als Duplikat loescht,
  * derselbe physische Track zaehlte doppelt als Auto-Learn-Beobachtung.

Der Konflikt wird deterministisch ueber die echte O_EXCL-Logik von
FilenameFixerTool.move_to_library() erzeugt: der "Gewinner"-Lauf belegt den
Zielnamen, der "Verlierer"-Lauf (andere video_id, gleicher Artist/Titel,
damit der video_id-Cache nicht trifft) kollidiert real damit.

Gefakt werden nur externe Dienste (siehe test_metadata_processor_happy_path.py).
"""

import asyncio
from pathlib import Path

import pytest

from services.downloader import download_pipeline_core as pipeline_core
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.genre_map import GenreResult
from utils.filenamefixer import FilenameFixerTool

ARTIST = "Conflict Artist"


class ConflictConfig:
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
def config(tmp_path, mapping_dir_copy):
    return ConflictConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(config, monkeypatch):
    monkeypatch.setattr(
        "services.metadata.loudness_replaygain.apply_replaygain_tags",
        lambda *a, **kw: (True, -5.0),
    )
    proc = EnhancedMetadataProcessor(config)
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
    monkeypatch.setattr(
        proc.cover_processor, "get_cover_art", lambda *a, **kw: (None, None)
    )
    return proc


@pytest.fixture
def filename_fixer(config):
    return FilenameFixerTool(config)


@pytest.fixture
def calls(processor, monkeypatch):
    """Zaehlt die persistierenden Folgeaktionen nach move_to_library().
    Der Cache-Store laeuft real durch (Ueberschreiben des Gewinner-Eintrags
    ist Teil des Beweises), die Auto-Learn-Aufrufe werden nur gezaehlt."""
    counts = {"store": 0, "learn_genre": 0, "learn_artist": 0, "observe_feat": 0}

    real_store = processor.cache_handler.store

    def counting_store(*a, **kw):
        counts["store"] += 1
        return real_store(*a, **kw)

    async def counting_learn_genre(*a, **kw):
        counts["learn_genre"] += 1
        return False

    async def counting_learn_artist(*a, **kw):
        counts["learn_artist"] += 1
        return False

    async def counting_observe(*a, **kw):
        counts["observe_feat"] += 1
        return []

    # Ein lernbares Genre erzwingen (Quelle lastfm, nicht auto_learn_disabled),
    # damit learn_genre() fuer JEDEN Lauf erreichbar ist - sonst waere die
    # Aussage "Verlierer ruft learn_genre() nicht auf" nicht diskriminierend
    # (das lokale Hip-Hop-Genre ist auto_learn_disabled).
    async def learnable_genre(*a, **kw):
        return GenreResult(primary="Pop", secondary=[], source="lastfm")

    monkeypatch.setattr(processor, "_determine_genre_with_stats", learnable_genre)
    monkeypatch.setattr(processor.cache_handler, "store", counting_store)
    monkeypatch.setattr(
        processor.auto_learn_manager, "learn_genre", counting_learn_genre
    )
    monkeypatch.setattr(
        processor.auto_learn_manager, "learn_artist", counting_learn_artist
    )
    monkeypatch.setattr(
        processor.auto_learn_manager, "observe_featured_artists", counting_observe
    )
    return counts


def _track(tmp_path: Path, video_id: str) -> dict:
    source = tmp_path / f"{video_id}.mp3"
    source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
    return {
        "title": f"{ARTIST} - Conflict Song (Official Video)",
        "artist": ARTIST,
        "uploader": ARTIST,
        "channel": ARTIST,
        "id": video_id,
        "filepath": str(source),
        "genre": "Hip Hop",
    }


def _run(processor, filename_fixer, track):
    return asyncio.run(
        processor.process_single_track(
            track_metadata=track, filename_fixer=filename_fixer
        )
    )


def test_winner_keeps_full_cache_and_auto_learn_path(
    processor, filename_fixer, calls, tmp_path
):
    result = _run(processor, filename_fixer, _track(tmp_path, "WIN1"))

    assert result.success is True
    assert result.renamed_due_to_conflict is False
    assert calls["store"] == 1
    # Testannahme: dieser Input erreicht Auto-Learn ueberhaupt (sonst waere
    # "kein learn_* beim Verlierer" nicht aussagekraeftig).
    assert calls["learn_genre"] == 1
    cached = processor.cache_handler.check({"id": "WIN1"}, None)
    assert cached is not None
    assert Path(cached.library_path) == Path(result.library_path)


class TestLoserOfFileConflict:
    @pytest.fixture
    def outcome(self, processor, filename_fixer, calls, tmp_path):
        winner = _run(processor, filename_fixer, _track(tmp_path, "WIN1"))
        assert winner.renamed_due_to_conflict is False
        for key in calls:
            calls[key] = 0

        loser = _run(processor, filename_fixer, _track(tmp_path, "LOSE1"))
        return winner, loser

    def test_conflict_is_real_and_reported_unchanged(self, outcome):
        winner, loser = outcome
        assert loser.success is True
        assert loser.renamed_due_to_conflict is True
        assert Path(loser.library_path) != Path(winner.library_path)
        assert Path(loser.library_path).name.endswith(" (1).mp3")
        assert Path(loser.library_path).exists()
        assert loser.artist == winner.artist
        assert loser.title == winner.title

    def test_loser_does_not_write_metadata_cache(self, outcome, calls, processor):
        winner, _loser = outcome
        assert calls["store"] == 0
        # Der Cache-Eintrag des Gewinners bleibt unveraendert.
        cached = processor.cache_handler.check({"id": "WIN1"}, None)
        assert cached is not None
        assert Path(cached.library_path) == Path(winner.library_path)
        # Der Verlierer hat keinen eigenen video_id-Eintrag erhalten.
        assert processor.cache_handler.check({"id": "LOSE1"}, None) is None

    def test_loser_does_not_trigger_auto_learn(self, outcome, calls):
        assert calls["learn_genre"] == 0
        assert calls["learn_artist"] == 0
        assert calls["observe_feat"] == 0

    def test_existing_conflict_handling_still_resolves_loser_as_duplicate(
        self, outcome
    ):
        winner, loser = outcome
        loser_path = Path(loser.library_path)
        res = {
            "success": True,
            "renamed_due_to_conflict": loser.renamed_due_to_conflict,
            "library_path": str(loser_path),
            "title": loser.title,
            "artist": loser.artist,
        }

        class _Log:
            def __getattr__(self, _name):
                return lambda *a, **kw: None

        entry = pipeline_core.resolve_file_conflict_as_duplicate(
            res, "https://x", _Log()
        )

        assert entry.artist == loser.artist
        assert entry.title == loser.title
        assert not loser_path.exists()
        assert Path(winner.library_path).exists()
