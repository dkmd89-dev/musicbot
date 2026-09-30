# -*- coding: utf-8 -*-
"""
M7 (Entscheidung: kein Editor): Characterization von mapping/genre_rules.yaml gegen die
ECHTE Datei und die Produktionsklasse GenreMapper. Die Datei ist Runtime-tot
(kein Root-Key GENRE_RULES); keyword_rules ist nur teilweise durch genre_aliases
abgedeckt, artist_rules ist nach artist_genre.yaml migriert, title_rules ist bewusst
nicht aktiv. Diese Tests frieren den Ist-Zustand ein und verhindern, dass die Regeln
versehentlich aktiviert oder über das Control Center bearbeitbar werden.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from services import mapping_admin as ma
from utils.genre_map import GenreMapper

_DIR = Path(__file__).resolve().parent.parent / "mapping"
_RULES = yaml.safe_load((_DIR / "genre_rules.yaml").read_text(encoding="utf-8"))
_ALIASES = {
    str(k).lower(): v
    for k, v in yaml.safe_load((_DIR / "genre_aliases.yaml").read_text(encoding="utf-8"))["GENRE_ALIASES"].items()
}


def test_file_has_only_the_three_unused_groups_and_no_runtime_root_key():
    assert set(_RULES) == {"keyword_rules", "artist_rules", "title_rules"}
    assert "GENRE_RULES" not in _RULES


def test_runtime_loads_no_rules_from_the_real_file():
    mapper = GenreMapper(str(_DIR))
    assert mapper.rules == []
    assert mapper._apply_rules("deutschrap") is None and mapper._apply_rules("party") is None


def test_title_rule_words_never_produce_a_rule_source():
    mapper = GenreMapper(str(_DIR))
    for raw in ("party", "liebe", "herz", "fest"):
        assert mapper.determine_genre(raw_genre=raw).source != "rule"


def test_genre_rules_is_not_editable_in_the_control_center():
    assert "genre_rules.yaml" not in ma.mapping_file_names().values()
    assert not any("rules" in mapping_id for mapping_id in ma.mapping_file_names())


def test_keyword_rules_are_only_partly_covered_by_aliases():
    """Widerspricht der älteren Aussage "1:1 redundant": 9 der 13 Keywords haben einen
    Alias mit demselben Zielgenre, 4 nicht (anderes Ziel oder kein Alias)."""
    covered, uncovered = [], []
    for rule in _RULES["keyword_rules"]:
        for keyword in rule["keywords"]:
            (covered if _ALIASES.get(keyword) == rule["genre"] else uncovered).append(keyword)
    assert sorted(covered) == sorted([
        "schlager", "volkstümlich", "volksmusik", "party schlager",
        "deutschrap", "german hip hop", "german rap", "deutschrock", "rock",
    ])
    assert sorted(uncovered) == sorted(["deutschpop", "german pop", "neue deutsche welle", "german rock"])
    assert _ALIASES["deutschpop"] == "Deutscher Pop" and _ALIASES["neue deutsche welle"] == "NDW"
    assert "german rock" not in _ALIASES


def test_artist_rules_are_covered_by_artist_genre():
    mapper = GenreMapper(str(_DIR))
    for artist in _RULES["artist_rules"]:
        assert mapper.determine_genre(artist_name=artist).source == "artist_exact"
