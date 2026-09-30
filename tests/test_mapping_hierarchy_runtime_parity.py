# -*- coding: utf-8 -*-
"""
Runtime-Paritaet der Genre-Hierarchie: Was die Administration schreibt, muss die
ECHTE Runtime (GenreProcessor -> GENRE_PRIORITY, GenreMapper) so laden, wie es die
Vorschau verspricht. Gelesen wird mit den Produktionsklassen; das Mapping-
Verzeichnis ist eine Kopie der echten mapping/genre_hierarchy.yaml in tmp_path.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import mapping_hierarchy as mh
from services.metadata.genre_processor import GenreProcessor
from utils.genre_map import GenreMapper

_MAPPING_DIR = Path(__file__).resolve().parent.parent / "mapping"


@pytest.fixture
def mdir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    (d / "genre_hierarchy.yaml").write_text((_MAPPING_DIR / "genre_hierarchy.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    # GenreMapper laedt alle Mapping-Dateien; die uebrigen bleiben echt, nur die Hierarchie ist die Kopie.
    for name in ("artist_genre.yaml", "channel_genre.yaml", "genre_aliases.yaml", "genre_overrides.yaml", "genre_rules.yaml"):
        if (_MAPPING_DIR / name).exists():
            (d / name).write_text((_MAPPING_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return d


def _priority(mdir: Path):
    return GenreProcessor(SimpleNamespace(GENRE_MAPPING_DIR=mdir), MagicMock()).GENRE_PRIORITY


def _payload(mdir: Path):
    return [{"genre": e.genre, "parent": e.parent} for e in mh.get_hierarchy_state(mdir)[0]]


def _save(mdir: Path, payload):
    return mh.apply_hierarchy_update(payload, mdir, expected_etag=mh.get_hierarchy_state(mdir)[1])


def test_admin_depths_equal_the_runtime_priority_for_every_genre(mdir):
    """Die in der Administration angezeigte Tiefe IST die Runtime-Prioritaet."""
    priority = _priority(mdir)

    entries = mh.get_hierarchy_state(mdir)[0]

    assert len(entries) == 187
    assert {e.genre.lower(): e.depth for e in entries} == priority


def test_reparenting_changes_the_runtime_priority_exactly_as_previewed(mdir):
    before = _priority(mdir)
    payload = [dict(p, parent="Drill") if p["genre"] == "Hardstyle" else p for p in _payload(mdir)]
    plan = mh.plan_hierarchy_update(payload, mdir)

    _save(mdir, payload)
    after = _priority(mdir)

    change = next(c for c in plan.changes if c.genre == "Hardstyle")
    assert (before["hardstyle"], after["hardstyle"]) == (change.old_depth, change.new_depth) == (1, 2)
    assert after["rawstyle"] == before["rawstyle"] + 1  # Unterbaum wandert mit
    assert {g for g in before if before[g] != after[g]} == {"hardstyle", *(a.lower() for a in change.affected)}


def test_new_genre_is_known_to_processor_and_mapper(mdir):
    payload = _payload(mdir) + [{"genre": "Kabarett Pop", "parent": "Pop"}]

    _save(mdir, payload)

    assert _priority(mdir)["kabarett pop"] == 1
    mapper = GenreMapper(str(mdir))
    assert mapper.get_main_genre("Kabarett Pop") == "Pop"
    assert mapper.hierarchy["kabarett pop"] == "Pop"


def test_removed_genre_is_gone_from_the_runtime_but_others_are_untouched(mdir):
    before = _priority(mdir)

    _save(mdir, [p for p in _payload(mdir) if p["genre"] != "Partyschlager"])

    after = _priority(mdir)
    assert "partyschlager" not in after
    assert {g: d for g, d in before.items() if g != "partyschlager"} == after


def test_unchanged_save_leaves_the_runtime_identical(mdir):
    before = _priority(mdir)
    text = (mdir / "genre_hierarchy.yaml").read_bytes()

    plan, result = _save(mdir, _payload(mdir))

    assert result.written is False and (mdir / "genre_hierarchy.yaml").read_bytes() == text
    assert _priority(mdir) == before


def test_genre_processor_still_prefers_the_deeper_genre_after_an_edit(mdir):
    """Characterization: bei mehreren Tags gewinnt das spezifischere (tiefere) Genre —
    das gilt nach einer Aenderung an einer anderen Stelle des Baums unveraendert."""
    _save(mdir, _payload(mdir) + [{"genre": "Kabarett Pop", "parent": "Pop"}])
    priority = _priority(mdir)

    assert priority["uk drill"] > priority["drill"] > priority["hip hop"]
