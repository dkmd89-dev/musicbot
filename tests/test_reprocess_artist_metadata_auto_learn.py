"""
Auto-Learn-Integration von scripts/reprocess_artist_metadata.py (Auto-Learn-
Auftrag Abschnitt 21/23/24: Dry-Run-Sichtbarkeit, echte
AutoLearnManager-Anbindung, konkreter Testfall "Gustav - Luftballon.m4a").

Nutzt denselben importlib-Modul-Ladepfad und dieselben Fixtures wie
tests/test_reprocess_artist_metadata.py (scripts/ ist kein Package).
"""

import asyncio
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from mutagen.mp4 import MP4

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "reprocess_artist_metadata.py"

if "reprocess_artist_metadata" in sys.modules:
    rpam = sys.modules["reprocess_artist_metadata"]
else:
    _spec = importlib.util.spec_from_file_location("reprocess_artist_metadata", MODULE_PATH)
    rpam = importlib.util.module_from_spec(_spec)
    sys.modules["reprocess_artist_metadata"] = rpam
    _spec.loader.exec_module(rpam)

from services.metadata.tag_writer import TagWriter
from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG_AVAILABLE and FFPROBE_AVAILABLE), reason="ffmpeg/ffprobe nicht auf PATH verfuegbar"
)

METADATEN_ROOT = rpam.DEFAULT_METADATEN_ROOT


def _make_real_m4a(path: Path, duration_seconds: int = 1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.fixture
def isolated_artist_dir():
    import uuid

    artist_dir = METADATEN_ROOT / f"_pytest_reprocess_al_{uuid.uuid4().hex[:8]}"
    singles_dir = artist_dir / "Singles"
    singles_dir.mkdir(parents=True)
    yield artist_dir
    shutil.rmtree(artist_dir, ignore_errors=True)


@pytest.fixture
def gustav_luftballon(isolated_artist_dir):
    """
    Reproduziert exakt den Auto-Learn-Auftrag-Testfall (Abschnitt 24):
    Primary Artist 'Gustav' (bereits bekannt), Featured Artist 'Noah'
    (bislang unbekannt), als Multi-Artist-Freeform-Tag ('Gustav; Noah'),
    identisch zur bestehenden TAG-01-Konvention.
    """
    path = isolated_artist_dir / "Singles" / "2026 - Luftballon.m4a"
    _make_real_m4a(path)
    audio = MP4(path)
    audio["©nam"] = ["Luftballon"]
    audio["©ART"] = ["Gustav; Noah"]
    audio["aART"] = ["Gustav"]
    audio["©alb"] = ["Luftballon"]
    audio["©day"] = ["2026"]
    audio.save()
    return path


class DummyGenreResult:
    def __init__(self, primary=None, secondary=None, source="unit_test"):
        self.primary = primary
        self.secondary = secondary or []
        self.source = source
        self.mb_ids = {}


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _make_processor_with_real_auto_learn(mapping_dir: Path, genre_primary="Pop"):
    """
    Wie make_processor_stub() in test_reprocess_artist_metadata.py, aber mit
    einem ECHTEN AutoLearnManager + ArtistNormalizer (statt gemockt) - fuer
    die dedizierte Auto-Learn-Integrationspruefung.
    """
    processor = Mock()
    real_normalizer = ArtistNormalizer(
        ArtistConfig(
            library_dir=mapping_dir.parent / "library",
            override_file=mapping_dir / "artist_overrides.json",
            mapping_dir=mapping_dir,
        )
    )
    processor.artist_normalizer.normalize.side_effect = real_normalizer.normalize
    processor.title_cleaner.light_title_cleanup.side_effect = lambda title, artist: title
    processor.title_cleaner.build_search_title.side_effect = (
        lambda parsed_title, original_title, final_artist: original_title
    )
    processor.genre_processor.determine_genre_with_fallbacks = AsyncMock(
        return_value=DummyGenreResult(primary=genre_primary, secondary=["Rock"])
    )
    processor.lyrics_processor.fetch_lyrics_with_fallback = AsyncMock(
        return_value=(None, None)
    )
    processor.cover_processor.get_cover_art = Mock(return_value=(None, None))
    processor.tag_writer = TagWriter(logger=Mock())

    genre_mapper = GenreMapper(mapping_dir=mapping_dir)
    processor.auto_learn_manager = AutoLearnManager(
        config=_Config(mapping_dir),
        artist_normalizer=real_normalizer,
        genre_mapper=genre_mapper,
    )
    return processor


@requires_ffmpeg
class TestReprocessToolAutoLearnDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_reports_feature_artist_without_writing(
        self, gustav_luftballon, isolated_artist_dir, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        processor = _make_processor_with_real_auto_learn(mapping_dir)

        result = await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=True,
        )

        feat = result["auto_learn"]["featured_artists"]
        assert len(feat) == 1
        assert feat[0]["canonical"] == "Noah"
        assert feat[0]["decision"] == "WOULD_LEARN"
        assert not (mapping_dir / "auto_learned_featured_artists.yaml").exists(), (
            "Dry-Run darf keine Datei schreiben"
        )

    @pytest.mark.asyncio
    async def test_dry_run_genre_prediction_matches_live_outcome(
        self, gustav_luftballon, isolated_artist_dir, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        processor = _make_processor_with_real_auto_learn(mapping_dir, genre_primary="Indie Pop")

        dry_result = await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "dry.log"),
            dry_run=True,
        )
        predicted = dry_result["auto_learn"]["genre"]
        assert predicted["decision"] == "WOULD_LEARN"
        assert predicted["predicted_primary"] == "Indie Pop"
        assert not (mapping_dir / "auto_learned_genre.yaml").exists()

        # Zweiter, echter Lauf (gleicher, unveraenderter mapping_dir) muss
        # exakt das vom Dry-Run vorhergesagte Ergebnis erzeugen.
        live_result = await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "live.log"),
            dry_run=False,
        )
        assert live_result["auto_learn"]["genre"]["decision"] == "WOULD_LEARN"
        with open(mapping_dir / "auto_learned_genre.yaml") as f:
            data = yaml.safe_load(f)
        assert data["ARTIST_GENRE_MAP"]["Gustav"]["primary"] == "Indie Pop"


@requires_ffmpeg
class TestReprocessToolAutoLearnLive:
    @pytest.mark.asyncio
    async def test_live_run_learns_featured_artist_noah(
        self, gustav_luftballon, isolated_artist_dir, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        processor = _make_processor_with_real_auto_learn(mapping_dir)

        result = await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        feat = result["auto_learn"]["featured_artists"]
        assert feat[0]["canonical"] == "Noah"
        assert feat[0]["decision"] == "LEARNED"
        assert feat[0]["observations"] == 1
        assert feat[0]["confidence"] == "OBSERVED"

        with open(mapping_dir / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        entry = data["featured_artists"]["Noah"]
        assert entry["role"] == "featured_artist"
        assert entry["primary_artists"] == ["Gustav"]

    @pytest.mark.asyncio
    async def test_live_run_does_not_write_genre_for_featured_artist_noah(
        self, gustav_luftballon, isolated_artist_dir, tmp_path
    ):
        """Abschnitt 16: Noah darf NICHT automatisch Gustavs Genre erben."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        processor = _make_processor_with_real_auto_learn(mapping_dir, genre_primary="Indie Pop")

        await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )

        genre_file = mapping_dir / "auto_learned_genre.yaml"
        if genre_file.exists():
            with open(genre_file) as f:
                data = yaml.safe_load(f) or {}
            genre_map = data.get("ARTIST_GENRE_MAP", {})
            assert "Noah" not in genre_map

    @pytest.mark.asyncio
    async def test_no_audio_or_directory_changes_from_auto_learn(
        self, gustav_luftballon, isolated_artist_dir, tmp_path
    ):
        """Safety: Auto-Learn beruehrt ausschliesslich mapping/-Dateien."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        processor = _make_processor_with_real_auto_learn(mapping_dir)

        files_before = sorted(
            p.name for p in isolated_artist_dir.rglob("*") if p.suffix != ".log"
        )
        await rpam.process_file(
            gustav_luftballon, isolated_artist_dir, processor, Mock(), Mock(),
            rpam.ReprocessLogger(isolated_artist_dir / "test.log"),
            dry_run=False,
        )
        files_after = sorted(
            p.name for p in isolated_artist_dir.rglob("*") if p.suffix != ".log"
        )
        assert files_before == files_after
