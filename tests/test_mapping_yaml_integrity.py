"""
Regressionstest fuer DATA-001/DATA-002 (docs/MusicBot_ENGINEERING_BASELINE.md):
mehrere mapping/*.yaml-Dateien hatten doppelte Top-Level-Keys unter ihrem
jeweiligen Wurzel-Key (z.B. ARTIST_GENRE_MAP, GENRE_OVERRIDES). PyYAML
behaelt beim Laden standardmaessig nur den JEWEILS LETZTEN Wert pro Key -
die erste Definition wird still verworfen, ohne Fehler oder Warnung.

DATA-001 (artist_genre.yaml, 12 Keys): alle Faelle hatten identisches
"primary", nur "description"/vereinzelt "secondary" unterschieden sich -
risikofrei zusammengefuehrt (jeweils vollstaendigere Version behalten).

DATA-002 (genre_hierarchy.yaml 1, genre_overrides.yaml 8, genre_aliases.yaml
13 Keys): einige Faelle waren echte Klassifizierungs-Konflikte, keine
reinen Text-Duplikate - einzeln mit Nutzer-Entscheidung aufgeloest:
- Metal: war sowohl als Top-Level-Genre (Zeile 20, explizite
  ROOT-LEVEL-Sektion) als auch als Rock-Subgenre (Zeile 175, inmitten
  eines "X: Metal"-Subgenre-Blocks - wirkte wie Tippfehler) definiert.
  Entscheidung: Top-Level (aendert Verhalten: get_main_genre("metal")
  liefert jetzt "Metal" statt vorher "Rock").
- tech house/progressive house/hardstyle/electropop: waren sowohl grob
  zusammengefasst (House/Dance/Pop) als auch granular als eigenes Genre
  definiert. Entscheidung: granular behalten (= bereits aktives
  Verhalten, keine Aenderung).
- indie rock (Alias): war sowohl "Rock" als auch "Indie". Entscheidung:
  Indie (= bereits aktives Verhalten, keine Aenderung).
"""

import json
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


MAPPING_FILES_TO_CHECK = [p.name for p in sorted(MAPPING_DIR.glob("*.yaml"))]


class TestNoDuplicateKeysInGenreMappingFiles:
    """
    Ueberdeckt inzwischen ALLE mapping/*.yaml-Dateien (nicht mehr nur die vier
    urspruenglich in DATA-001/DATA-002 gefundenen), damit auch kuenftig neu
    hinzukommende Mapping-Dateien automatisch gegen dasselbe stille
    PyYAML-Duplikat-Problem geschuetzt sind. Stand bei Einfuehrung: alle
    zusaetzlich geprueften Dateien (genre_filters, channel_genre,
    case_preserve, auto_learned_artists, auto_learned_genre, known_artists,
    special_channel, podcast_rss_feeds, genre_rules) waren bereits sauber.
    """

    @pytest.mark.parametrize("filename", MAPPING_FILES_TO_CHECK)
    def test_no_duplicate_keys(self, filename):
        duplicates = _load_and_find_duplicate_keys(MAPPING_DIR / filename)
        assert duplicates == [], (
            f"{filename} hat doppelte Keys: {duplicates} - PyYAML wuerde "
            "beim Laden nur den letzten Wert behalten, die anderen(n) "
            "Definition(en) gehen still verloren (siehe DATA-001/DATA-002)."
        )

    def test_artist_genre_yaml_regression_specific_keys_deduplicated(self):
        """Direkter Regressionstest fuer die 12 in DATA-001 gefundenen Keys."""
        duplicates = _load_and_find_duplicate_keys(
            MAPPING_DIR / "artist_genre.yaml"
        )
        previously_duplicated = {
            "dominic fike", "eminem", "herzchen", "majan", "dasha",
            "sarah engels", "taylor swift", "calvin harris", "riton",
            "one-t", "fayan", "The Weeknd",
        }
        assert not (previously_duplicated & set(duplicates))

    def test_data_002_previously_duplicated_keys_deduplicated(self):
        """Direkter Regressionstest fuer die 22 in DATA-002 gefundenen Keys
        (ueber die drei betroffenen Dateien hinweg)."""
        for filename, previously_duplicated in [
            ("genre_hierarchy.yaml", {"Metal"}),
            (
                "genre_overrides.yaml",
                {
                    "hiphop", "hip hop", "edm", "tech house",
                    "progressive house", "hardstyle", "electro house",
                    "electropop",
                },
            ),
            (
                "genre_aliases.yaml",
                {
                    "ruhrpott rap", "berliner rap", "hamburger rap",
                    "hamburger schule", "kölsch rap", "münchner rap",
                    "stuttgarter rap", "österreichischer rap",
                    "schweizer rap", "indie rock", "techno", "house",
                    "afro house",
                },
            ),
        ]:
            duplicates = _load_and_find_duplicate_keys(MAPPING_DIR / filename)
            assert not (previously_duplicated & set(duplicates)), (
                f"{filename}: {previously_duplicated & set(duplicates)} "
                "wieder dupliziert"
            )


class TestGenreClassificationDecisions:
    """
    Regressionstests fuer die per Nutzer-Entscheidung aufgeloesten
    DATA-002-Konflikte (siehe Modul-Docstring).
    """

    def test_metal_is_top_level_genre_not_rock_subgenre(self):
        with open(MAPPING_DIR / "genre_hierarchy.yaml", encoding="utf-8") as f:
            hierarchy = yaml.safe_load(f)["GENRE_HIERARCHY"]
        assert hierarchy["Metal"] is None
        assert hierarchy["Heavy Metal"] == "Metal"

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("tech house", "Tech House"),
            ("progressive house", "Progressive House"),
            ("hardstyle", "Hardstyle"),
            ("electropop", "Electropop"),
        ],
    )
    def test_edm_subgenres_stay_granular(self, key, expected):
        with open(MAPPING_DIR / "genre_overrides.yaml", encoding="utf-8") as f:
            overrides = yaml.safe_load(f)["GENRE_OVERRIDES"]
        assert overrides[key] == expected

    def test_indie_rock_classified_as_indie(self):
        with open(MAPPING_DIR / "genre_aliases.yaml", encoding="utf-8") as f:
            aliases = yaml.safe_load(f)["GENRE_ALIASES"]
        assert aliases["indie rock"] == "Indie"


def _find_duplicate_keys_in_json(json_path: Path) -> list:
    """json.load() hat dasselbe stille 'letzter Key gewinnt'-Verhalten wie
    PyYAML - Python's json-Modul wirft standardmaessig keinen Fehler bei
    doppelten Objekt-Keys. object_pairs_hook faengt sie ab, bevor sie
    stillschweigend verworfen werden."""
    def _collect(pairs):
        keys = [k for k, _ in pairs]
        counts = Counter(keys)
        duplicate_keys.extend(k for k, n in counts.items() if n > 1)
        return dict(pairs)

    duplicate_keys: list = []
    with open(json_path, encoding="utf-8") as f:
        json.load(f, object_pairs_hook=_collect)
    return duplicate_keys


MAPPING_JSON_FILES_TO_CHECK = [p.name for p in sorted(MAPPING_DIR.glob("*.json"))]


class TestNoDuplicateKeysInMappingJsonFiles:
    @pytest.mark.parametrize("filename", MAPPING_JSON_FILES_TO_CHECK)
    def test_no_duplicate_keys(self, filename):
        duplicates = _find_duplicate_keys_in_json(MAPPING_DIR / filename)
        assert duplicates == [], (
            f"{filename} hat doppelte Keys: {duplicates} - json.load() "
            "behaelt beim Laden nur den letzten Wert, fruehere Definitionen "
            "gehen still verloren (analog zu DATA-001/DATA-002 bei YAML)."
        )
