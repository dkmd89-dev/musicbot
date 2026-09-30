# -*- coding: utf-8 -*-
"""AR-2: GenreProcessor darf gelernte Eintraege (auto_learned_genre.json,
ab LEARNED in GenreMapper.artist_map gemergt) nicht als "manuell" ausgeben.

Manuell = artist_genre.yaml -> source "artist_exact_manual".
Gelernt = auto_learned_genre.json -> source "artist_exact_learned".
auto_learn_disabled bleibt in beiden Faellen True (bestehendes, separat
charakterisiertes Verhalten, siehe test_genre_processor_revalidation_gap.py).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

from services.metadata.genre_processor import GenreProcessor
from utils.genre_map import GenreMapper
from utils.singleton import SingletonMixin


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _processor(mapping_dir: Path) -> GenreProcessor:
    SingletonMixin._instances.clear()
    return GenreProcessor(_Config(mapping_dir), GenreMapper(mapping_dir=mapping_dir))


def _write_mappings(mapping_dir: Path, learned_confidence: str = "LEARNED") -> None:
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (mapping_dir / "artist_genre.yaml").write_text(
        yaml.safe_dump({"ARTIST_GENRE_MAP": {"manual artist": {"primary": "Rock", "secondary": []}}}),
        encoding="utf-8",
    )
    (mapping_dir / "auto_learned_genre.json").write_text(
        json.dumps({"ARTIST_GENRE_MAP": {
            "Learned Artist": {"primary": "Pop", "secondary": [], "confidence": learned_confidence},
            # gleicher Key wie manuell: manuell hat Vorrang, Eintrag bleibt inaktiv
            "Manual Artist": {"primary": "Schlager", "secondary": [], "confidence": "LEARNED"},
        }}),
        encoding="utf-8",
    )


def _resolve(processor: GenreProcessor, artist: str):
    return asyncio.run(
        processor.determine_genre_with_fallbacks(
            track_metadata={"title": f"{artist} - Song"}, artist_name=artist, channel_name="X",
        )
    )


def test_learned_entry_is_labelled_learned_not_manual(tmp_path) -> None:
    _write_mappings(tmp_path / "mapping")
    result = _resolve(_processor(tmp_path / "mapping"), "Learned Artist")
    assert result.primary == "Pop"
    assert result.source == "artist_exact_learned"
    assert result.auto_learn_disabled is True


def test_manual_entry_keeps_manual_label(tmp_path) -> None:
    _write_mappings(tmp_path / "mapping")
    result = _resolve(_processor(tmp_path / "mapping"), "Manual Artist")
    assert result.primary == "Rock"  # manuell schlaegt gelernt
    assert result.source == "artist_exact_manual"
    assert result.auto_learn_disabled is True


def test_mapper_tracks_only_merged_learned_keys(tmp_path) -> None:
    _write_mappings(tmp_path / "mapping")
    SingletonMixin._instances.clear()
    mapper = GenreMapper(mapping_dir=tmp_path / "mapping")
    assert mapper.learned_artist_keys == {"learned artist"}


def test_observed_entry_is_not_active_and_not_tracked(tmp_path) -> None:
    _write_mappings(tmp_path / "mapping", learned_confidence="OBSERVED")
    SingletonMixin._instances.clear()
    mapper = GenreMapper(mapping_dir=tmp_path / "mapping")
    assert "learned artist" not in mapper.learned_artist_keys
    assert mapper.get_artist_entry("learned artist") is None


def test_processor_tolerates_mapper_without_learned_tracking() -> None:
    """Fakes/aeltere Mapper ohne learned_artist_keys -> Label bleibt 'manual'."""
    from types import SimpleNamespace

    from utils.genre_map import GenreMapping

    fake = SimpleNamespace(get_artist_entry=lambda k: GenreMapping(primary="Pop"))
    processor = GenreProcessor.__new__(GenreProcessor)
    processor.genre_mapper = fake
    assert processor._manual_or_learned_source("x") == "artist_exact_manual"
