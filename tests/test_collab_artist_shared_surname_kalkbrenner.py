"""
Live-Fund 2026-09-09 (End-to-End-Testdownload über den echten Test-Bot,
docs/FINDINGS_INDEX.md): "Fritz & Paul Kalkbrenner - Sky and Sand" landete
im Library-Ordner "Fritz/" mit Genre "Indie".

Ursache (mit den echten Produktionsklassen nachvollzogen):
  1. utils/youtube_parser.py::_split_multi_artists() behandelt "&"/"x"/"/"/
     "und" überall als Kollaborations-Trenner (korrektes, an vielen Titeln
     gebrauchtes Verhalten) und zerlegt "Fritz & Paul Kalkbrenner" in
     all_artists = ["Fritz", "Paul Kalkbrenner"].
  2. Der abgeschnittene Primär-Künstler "Fritz" ist ein ANDERER, realer
     Künstler (australische Band). determine_best_artist() übernimmt ihn,
     der ArtistIdentityResolver findet keinen Override → source="parser".
  3. Last.fm-Tags für die Band "Fritz" ("shoegaze", "dream pop",
     "indie rock", …) → Genre "Indie", Ordner "Fritz/Singles/…".

Ein generischer Split-Heuristik-Fix ("gemeinsamer Nachname → zusammen-
lassen") ist NICHT sicher: "Macklemore & Ryan Lewis", "Jay-Z & Kanye
West", "Tyler, The Creator & Kali Uchis" sind echte Doppel-Primär-Acts.
Gleiche Fehlerklasse wie Finding B/D → gezielter mapping/-Override.

Fix (analog tests/test_artist_overrides_miksu_macloud_duo.py):
  * mapping/artist_overrides.json bekommt die Kollab-Schreibweisen von
    "Fritz & Paul Kalkbrenner" → "Fritz Kalkbrenner" (Nutzer-Entscheid:
    Primär "Fritz Kalkbrenner", Paul als Zweit-Artist) plus den
    Self-Eintrag "fritz kalkbrenner" → "Fritz Kalkbrenner".
  * EnhancedMetadataProcessor Schritt 6a prüft den UNGESPLITTETEN
    Roh-Artist-String (raw_artist_string bzw. die stabile Komma-Form
    ", ".join(all_artists)) gegen die Override-Stufe des Resolvers; greift
    ein Override, das eine Erweiterung des abgeschnittenen ersten
    Künstlers ist, wird all_artists[0] ersetzt.

Isolationsstruktur: eigener EMP-Aufbau (Override-Datei muss VOR der
Processor-Konstruktion existieren), Fake-externe-Dienste wie in
tests/test_metadata_processor_happy_path.py.
"""

import asyncio
import json
from pathlib import Path

import pytest

from services.metadata.artist_identity_resolver import ArtistIdentityResolver
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.artist_map import ArtistConfig, ArtistNormalizer
from utils.filenamefixer import FilenameFixerTool

from tests.test_metadata_processor_happy_path import (
    FakeExternalClient,
    HappyPathConfig,
)

# Exakt die Einträge, die diesem PR in mapping/artist_overrides.json
# hinzugefügt wurden.
KALKBRENNER_OVERRIDES = {
    "fritz & paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz, paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz / paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz/paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz x paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz und paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz&paul kalkbrenner": "Fritz Kalkbrenner",
    "fritz kalkbrenner": "Fritz Kalkbrenner",
}


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def cfg(tmp_path, mapping_dir_copy):
    return HappyPathConfig(tmp_path, mapping_dir_copy)


def _build_processor(cfg, monkeypatch, overrides):
    """EMP mit gefakten externen Diensten; die Override-Datei wird VOR der
    Konstruktion geschrieben, damit ArtistNormalizer/Resolver sie laden."""
    Path(cfg.ARTIST_OVERRIDE_FILE).write_text(
        json.dumps(overrides), encoding="utf-8"
    )
    monkeypatch.setattr(
        "services.metadata.loudness_replaygain.apply_replaygain_tags",
        lambda *a, **kw: (True, -5.0),
    )
    proc = EnhancedMetadataProcessor(cfg)
    proc._mb_client = FakeExternalClient()
    proc._lfm_client = FakeExternalClient()

    async def _no_lyrics(*a, **kw):
        return None, None

    async def _no_album(*a, **kw):
        return None

    monkeypatch.setattr(
        proc.lyrics_processor, "fetch_lyrics_with_fallback", _no_lyrics
    )
    monkeypatch.setattr(
        proc.album_processor, "fetch_album_from_musicbrainz", _no_album
    )
    return proc


def _capture_tag_write(processor):
    captured = {}
    original = processor.tag_writer.write_tags

    def _spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    processor.tag_writer.write_tags = _spy
    return captured


def _md(source, title):
    return {
        "title": title,
        "artist": "",
        "uploader": "SomeUploadChannel",
        "channel": "SomeUploadChannel",
        "id": "KALKBR" + str(abs(hash(title)) % 100).zfill(2),
        "filepath": str(source),
        "cover_art": b"fake-cover-bytes",
        "genre": "Electronic",
    }


# ─────────────────────────────────────────────────────────────────────────
# Override-Mechanismus (Resolver-Ebene)
# ─────────────────────────────────────────────────────────────────────────
class TestKalkbrennerOverrideMechanism:
    @pytest.fixture
    def resolver(self, tmp_path):
        ovr = tmp_path / "artist_overrides.json"
        ovr.write_text(json.dumps(KALKBRENNER_OVERRIDES), encoding="utf-8")
        lib = tmp_path / "lib"
        lib.mkdir()
        mapping_dir = tmp_path / "mapping"
        normalizer = ArtistNormalizer(
            ArtistConfig(
                library_dir=lib, override_file=ovr, mapping_dir=mapping_dir
            )
        )
        return ArtistIdentityResolver(normalizer, mapping_dir)

    @pytest.mark.parametrize(
        "raw",
        [
            "Fritz & Paul Kalkbrenner",
            "Fritz, Paul Kalkbrenner",
            "Fritz / Paul Kalkbrenner",
            "Fritz/Paul Kalkbrenner",
            "Fritz und Paul Kalkbrenner",
        ],
    )
    def test_collab_variants_resolve_to_primary_kalkbrenner(self, resolver, raw):
        ident = resolver.resolve(raw)
        assert ident.canonical == "Fritz Kalkbrenner"
        assert ident.source == "artist_override"
        assert ident.known is True

    def test_bare_fritz_is_NOT_touched(self, resolver):
        """Die alleinstehende Band "Fritz" darf NICHT auf Kalkbrenner
        umgebogen werden (nur der volle Kollab-String greift)."""
        ident = resolver.resolve("Fritz")
        assert ident.canonical == "Fritz"
        assert ident.source == "parser"
        assert ident.known is False

    def test_corrected_primary_is_known(self, resolver):
        ident = resolver.resolve("Fritz Kalkbrenner")
        assert ident.canonical == "Fritz Kalkbrenner"
        assert ident.source == "artist_override"


# ─────────────────────────────────────────────────────────────────────────
# End-to-End durch die Metadata-Pipeline (EMP Schritt 6a)
# ─────────────────────────────────────────────────────────────────────────
class TestKalkbrennerCollabEndToEnd:
    def test_shared_surname_collab_primary_is_expanded_and_paul_is_second(
        self, cfg, monkeypatch, tmp_path
    ):
        """Diskriminierend: OHNE den Fix ist result.artist == "Fritz"
        (abgeschnittener all_artists[0], Quelle parser). MIT dem Fix greift
        der Kollab-Override → "Fritz Kalkbrenner", Paul Kalkbrenner bleibt
        als Zweit-/Feature-Artist erhalten."""
        proc = _build_processor(cfg, monkeypatch, KALKBRENNER_OVERRIDES)
        ff = FilenameFixerTool(cfg)
        captured = _capture_tag_write(proc)

        src = tmp_path / "skyandsand.mp3"
        src.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        result = asyncio.run(
            proc.process_single_track(
                track_metadata=_md(
                    src,
                    "Fritz & Paul Kalkbrenner - Sky and Sand (Original Mix)",
                ),
                filename_fixer=ff,
            )
        )

        assert result.success is True
        assert result.artist == "Fritz Kalkbrenner"
        assert result.artist_known is True

        feat = captured.get("feat_artists") or []
        assert any(
            f.lower() == "paul kalkbrenner" for f in feat
        ), f"'Paul Kalkbrenner' fehlt als Zweit-Artist: {feat!r}"

    def test_genuine_dual_primary_collab_without_override_is_untouched(
        self, cfg, monkeypatch, tmp_path
    ):
        """Regressions-Guard: ein echtes Doppel-Primär-Duo OHNE Override
        ("Macklemore & Ryan Lewis") darf von Schritt 6a nicht angefasst
        werden – der abgeschnittene erste Name bleibt Primär-Künstler wie
        vor dem Fix."""
        proc = _build_processor(cfg, monkeypatch, KALKBRENNER_OVERRIDES)
        ff = FilenameFixerTool(cfg)

        src = tmp_path / "thriftshop.mp3"
        src.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        result = asyncio.run(
            proc.process_single_track(
                track_metadata=_md(
                    src, "Macklemore & Ryan Lewis - Thrift Shop"
                ),
                filename_fixer=ff,
            )
        )

        assert result.success is True
        assert result.artist == "Macklemore"


# ─────────────────────────────────────────────────────────────────────────
# Daten-Integrität gegen die real ausgelieferte mapping-Datei
# ─────────────────────────────────────────────────────────────────────────
class TestRealArtistOverridesFileHasKalkbrennerEntries:
    """Schützt die vom Nutzer bestätigte Korrektur gegen versehentliches
    Entfernen (CLAUDE.md Abschnitt 10)."""

    def test_all_expected_variants_are_present_and_correct(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        for key, expected in KALKBRENNER_OVERRIDES.items():
            assert data.get(key) == expected, f"Override für '{key}' fehlt/falsch"
