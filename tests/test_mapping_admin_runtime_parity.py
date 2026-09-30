# -*- coding: utf-8 -*-
"""
Runtime-Paritaet der Mapping-Administration: Was die Admin-API schreibt, muss
die ECHTE Runtime so laden, wie es die Administration verspricht.

Geschrieben wird ueber die Public-API von services/mapping_admin.py (Plan +
Apply mit Etag). Gelesen wird mit den Produktionsklassen GenreProcessor,
GenreMapper und utils.filenamefixer — keine Nachbauten. Externe Dienste
werden nicht angesprochen; das Mapping-Verzeichnis ist ein tmp_path.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from services import mapping_admin as ma
from services.metadata.genre_processor import GenreProcessor
from utils.filenamefixer import load_special_channels_from_yaml
from utils.genre_map import GenreMapper


def _write(path: Path, root_key: str, data) -> None:
    path.write_text(yaml.safe_dump({root_key: data}, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture
def mapping_dir(tmp_path):
    _write(tmp_path / "channel_genre.yaml", "CHANNEL_GENRE_MAP",
           {"16bars": {"primary": "Hip Hop", "secondary": ["Deutschrap"], "description": "German rap channel"}})
    _write(tmp_path / "genre_aliases.yaml", "GENRE_ALIASES", {"rnb": "R&B"})
    _write(tmp_path / "genre_overrides.yaml", "GENRE_OVERRIDES", {"acid techno": "Techno"})
    _write(tmp_path / "genre_filters.yaml", "IGNORE_SECONDARY", ["seen live", "usa"])
    _write(tmp_path / "special_channel.yaml", "SPECIAL_CHANNELS",
           {"Podcast": ["Gemischtes Hack"], "Compilations": ["Deep Territory"], "Playlist": ["Workout"]})
    _write(tmp_path / "genre_hierarchy.yaml", "GENRE_HIERARCHY", {})
    _write(tmp_path / "artist_genre.yaml", "ARTIST_GENRE_MAP", {})
    _write(tmp_path / "genre_rules.yaml", "GENRE_RULES", [])
    return tmp_path


def _processor(mapping_dir: Path) -> GenreProcessor:
    config = SimpleNamespace(GENRE_MAPPING_DIR=mapping_dir)
    return GenreProcessor(config, MagicMock())


def _mapper(mapping_dir: Path) -> GenreMapper:
    return GenreMapper(str(mapping_dir))


def _etag(mapping_id: str, mapping_dir: Path) -> str:
    """Etag wie ihn der Client aus GET/Preview bekommt."""
    if mapping_id == ma.MAPPING_ID_GENRE_FILTERS:
        return ma.get_genre_filter_state(mapping_dir)[1]
    if mapping_id == ma.MAPPING_ID_SPECIAL_CHANNELS:
        return ma.get_special_channels_state(mapping_dir)[1]
    return ma.get_mapping_entry(mapping_id, "__probe__", mapping_dir)[1]


def _save_entry(mapping_id: str, key: str, payload: dict, mapping_dir: Path):
    return ma.apply_mapping_update(mapping_id, key, payload, mapping_dir, _etag(mapping_id, mapping_dir))


# ── genre-filters -> GenreProcessor.IGNORE_SECONDARY ─────────────────────


def test_saved_filters_are_lowercase_and_effective_in_genre_processor(mapping_dir):
    ma.apply_genre_filter_update(
        ["Seen Live", "  Female Vocalists ", "USA", "usa"], mapping_dir,
        expected_etag=_etag(ma.MAPPING_ID_GENRE_FILTERS, mapping_dir),
    )

    ignore = _processor(mapping_dir).IGNORE_SECONDARY

    # Runtime prueft tag.lower().strip() in IGNORE_SECONDARY -> nur kleingeschriebene Werte greifen.
    assert ignore == {"seen live", "female vocalists", "usa"}


# ── genre-aliases -> GenreProcessor + GenreMapper ────────────────────────


def test_saved_alias_is_effective_in_processor_and_mapper(mapping_dir):
    _save_entry(ma.MAPPING_ID_GENRE_ALIASES, "Neo Soulish", {"canonical": "Neo Soul"}, mapping_dir)

    processor = _processor(mapping_dir)
    mapper = _mapper(mapping_dir)

    assert processor.GENRE_NORMALIZATION["neo soulish"] == "Neo Soul"
    assert processor.normalize_genre_name("Neo Soulish") == "Neo Soul"
    assert mapper.genre_aliases["neo soulish"] == "Neo Soul"
    assert mapper.normalize_genre_name("neo soulish") == "Neo Soul"


def test_updating_alias_keeps_original_key_and_runtime_uses_new_target(mapping_dir):
    _save_entry(ma.MAPPING_ID_GENRE_ALIASES, "RNB", {"canonical": "Rhythm and Blues"}, mapping_dir)

    raw = yaml.safe_load((mapping_dir / "genre_aliases.yaml").read_text(encoding="utf-8"))["GENRE_ALIASES"]
    assert list(raw) == ["rnb"]
    assert _mapper(mapping_dir).normalize_genre_name("rnb") == "Rhythm and Blues"


# ── channel-genre -> GenreMapper.channel_map ─────────────────────────────


def test_saved_channel_genre_is_effective_in_mapper(mapping_dir):
    _save_entry(
        ma.MAPPING_ID_CHANNEL_GENRE, "Trap Nation",
        {"primary": "Hip Hop", "secondary": ["Trap"], "description": "Trap channel"}, mapping_dir,
    )

    mapping = _mapper(mapping_dir).channel_map["trap nation"]

    assert mapping.primary == "Hip Hop"
    assert mapping.secondary == ["Trap"]


# ── special-channels -> filenamefixer ────────────────────────────────────


def test_saved_special_channel_order_is_priority_order_in_runtime_loader(mapping_dir):
    categories = [
        {"name": "Compilations", "channels": ["Deep Territory"]},
        {"name": "Podcast", "channels": ["Gemischtes Hack", "Kaulitz Hills"]},
        {"name": "Playlist", "channels": ["Workout"]},
    ]
    ma.apply_special_channels_update(
        categories, mapping_dir, expected_etag=_etag(ma.MAPPING_ID_SPECIAL_CHANNELS, mapping_dir),
    )

    loaded = load_special_channels_from_yaml(mapping_dir)

    assert list(loaded) == ["Compilations", "Podcast", "Playlist"]
    assert loaded["Podcast"] == ["Gemischtes Hack", "Kaulitz Hills"]


# ── genre-overrides -> GenreMapper.overrides (Charakterisierung) ─────────


def test_lowercase_override_key_is_effective_in_mapper(mapping_dir):
    _save_entry(ma.MAPPING_ID_GENRE_OVERRIDES, "trip hop", {"override": "Downtempo"}, mapping_dir)

    assert _mapper(mapping_dir).normalize_genre_name("Trip Hop") == "Downtempo"


def test_non_lowercase_override_key_is_not_reachable_in_runtime_current_behavior(mapping_dir):
    # Charakterisierung des AKTUELLEN Verhaltens: GenreMapper.normalize_genre_name()
    # sucht mit genre_name.strip().lower() im UNVERAENDERTEN Override-Dict. Ein
    # Key mit Grossbuchstaben (die Administration erlaubt ihn bewusst, exact-first)
    # wird zur Laufzeit nie getroffen. In mapping/genre_overrides.yaml betrifft das
    # heute 'Hip-Hop' und 'Hip - Hop'. Aendert sich das Runtime-Verhalten oder die
    # Administration bewusst (Warnung/Normalisierung), muss dieser Test mitwandern.
    _save_entry(ma.MAPPING_ID_GENRE_OVERRIDES, "Trip Hop", {"override": "Downtempo"}, mapping_dir)

    raw = yaml.safe_load((mapping_dir / "genre_overrides.yaml").read_text(encoding="utf-8"))["GENRE_OVERRIDES"]
    assert raw["Trip Hop"] == "Downtempo"
    assert _mapper(mapping_dir).normalize_genre_name("Trip Hop") != "Downtempo"
