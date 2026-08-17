"""
Regressionstest fuer DATA-001 (docs/MusicBot_ENGINEERING_BASELINE.md):
mapping/artist_genre.yaml hatte 12 doppelte Top-Level-Keys unter
ARTIST_GENRE_MAP (z.B. "The Weeknd" zweimal). PyYAML behaelt beim Laden
standardmaessig nur den JEWEILS LETZTEN Wert pro Key - die erste
Definition wird still verworfen, ohne Fehler oder Warnung. Nach der
Bereinigung: keine Duplikate mehr, alle Eintraege behalten die
vollstaendigere der beiden vorherigen Beschreibungen/Sekundaergenres.

Beim Bau dieses generischen Duplicate-Key-Checks wurden zusaetzlich
Duplikate in genre_hierarchy.yaml, genre_overrides.yaml und
genre_aliases.yaml gefunden (DATA-002, siehe Baseline) - bewusst NICHT
Teil dieses Fixes (andere Semantik pro Datei, braucht wie bei
DATA-001 individuelle Inhaltspruefung, keine Bulk-Aenderung ohne
Review). Dieser Test deckt daher gezielt nur artist_genre.yaml ab, nicht
generisch alle mapping/*.yaml-Dateien.
"""

from collections import Counter
from pathlib import Path

import pytest
import yaml

MAPPING_DIR = Path(__file__).resolve().parent.parent / "mapping"


class _DuplicateKeyCollectingLoader(yaml.SafeLoader):
    """SafeLoader-Variante, die doppelte Mapping-Keys sammelt statt sie
    stillschweigend zu ueberschreiben (PyYAML-Default-Verhalten)."""

    duplicate_keys: list


def _construct_mapping_collecting_duplicates(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    counts = Counter(keys)
    dups = [k for k, n in counts.items() if n > 1]
    if dups:
        loader.duplicate_keys.extend(dups)
    values = [loader.construct_object(v, deep=deep) for _, v in node.value]
    return dict(zip(keys, values))


_DuplicateKeyCollectingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_collecting_duplicates,
)


def _load_and_find_duplicate_keys(yaml_path: Path) -> list:
    with open(yaml_path, encoding="utf-8") as f:
        loader = _DuplicateKeyCollectingLoader(f)
        loader.duplicate_keys = []
        try:
            loader.get_single_data()
        finally:
            loader.dispose()
    return loader.duplicate_keys


class TestNoDuplicateKeysInArtistGenreYaml:
    def test_no_duplicate_top_level_keys(self):
        yaml_path = MAPPING_DIR / "artist_genre.yaml"
        duplicates = _load_and_find_duplicate_keys(yaml_path)
        assert duplicates == [], (
            f"{yaml_path.name} hat doppelte Keys: {duplicates} - PyYAML "
            "wuerde beim Laden nur den letzten Wert behalten, die "
            "anderen(n) Definition(en) gehen still verloren (siehe DATA-001)."
        )

    def test_artist_genre_yaml_regression_specific_keys_deduplicated(self):
        """
        Direkter Regressionstest fuer die 12 in DATA-001 gefundenen Keys.
        """
        duplicates = _load_and_find_duplicate_keys(
            MAPPING_DIR / "artist_genre.yaml"
        )
        previously_duplicated = {
            "dominic fike", "eminem", "herzchen", "majan", "dasha",
            "sarah engels", "taylor swift", "calvin harris", "riton",
            "one-t", "fayan", "The Weeknd",
        }
        assert not (previously_duplicated & set(duplicates))
