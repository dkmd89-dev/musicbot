# -*- coding: utf-8 -*-
"""Genre-Mapping bearbeiten (Primary + Secondary) — Service-Ebene.

services/library_repair/genre.py: save_manual_genre_mapping() (gemeinsamer
Writer fuer CLI, Telegram und Control Center) plus die neuen Funktionen
read_genre_mapping_entry / normalize_genre_fields / plan_manual_genre_mapping /
apply_manual_genre_mapping.

Regression (Produktionsdaten): mapping/artist_genre.yaml enthaelt Keys mit
Grossschreibung ("Dua Lipa", "Billie Eilish", ...). save_manual_genre_mapping()
schrieb immer `artist.lower()` und legte dadurch einen ZWEITEN Key an — set-genre
las weiter den alten Eintrag (erster casefold-Treffer), GenreMapper (lowercased
Keys) den neuen. Eine Genre-Korrektur blieb wirkungslos bzw. inkonsistent.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from services.library_repair.genre import (
    GenreDomainError,
    GenreMappingConflictError,
    GenreMappingUnavailableError,
    apply_manual_genre_mapping,
    genre_from_mapping,
    get_genre_mapping,
    known_genres,
    normalize_genre_fields,
    plan_manual_genre_mapping,
    read_genre_mapping_entry,
    save_manual_genre_mapping,
)

_YAML = """ARTIST_GENRE_MAP:
  Dua Lipa:
    primary: Pop
    secondary:
    - Dance Pop
    - Disco
    description: Britische Popsaengerin
  apache 207:
    primary: Hip Hop
    secondary:
    - Deutschrap
    - Trap
    description: Rapper
  kygo:
    primary: House
    secondary:
    - Tropical House
    description: DJ
"""


@pytest.fixture
def mapping_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mapping"
    d.mkdir()
    (d / "artist_genre.yaml").write_text(_YAML, encoding="utf-8")
    return d


def _map(mapping_dir: Path) -> dict:
    return yaml.safe_load((mapping_dir / "artist_genre.yaml").read_text(encoding="utf-8"))["ARTIST_GENRE_MAP"]


# ── Regression: gemischte Schreibweise ────────────────────────────────────

def test_save_updates_existing_mixed_case_key_in_place_without_creating_a_duplicate(mapping_dir) -> None:
    result = save_manual_genre_mapping("Dua Lipa", "Pop; Synthpop", mapping_dir, dry_run=False)

    m = _map(mapping_dir)
    assert [k for k in m if k.casefold() == "dua lipa"] == ["Dua Lipa"]   # kein zweiter Key
    assert m["Dua Lipa"]["primary"] == "Pop" and m["Dua Lipa"]["secondary"] == ["Synthpop"]
    assert m["Dua Lipa"]["description"] == "Britische Popsaengerin"          # bleibt erhalten
    assert result.artist_key == "Dua Lipa" and result.written is True


def test_save_matches_existing_key_case_insensitively(mapping_dir) -> None:
    save_manual_genre_mapping("DUA LIPA", "Pop; Disco", mapping_dir, dry_run=False)
    m = _map(mapping_dir)
    assert [k for k in m if k.casefold() == "dua lipa"] == ["Dua Lipa"]


def test_set_genre_lookup_and_writer_now_agree_on_the_same_entry(mapping_dir) -> None:
    save_manual_genre_mapping("Dua Lipa", "Pop; Synthpop", mapping_dir, dry_run=False)
    assert genre_from_mapping("Dua Lipa", mapping_dir / "artist_genre.yaml") == "Pop; Synthpop"


def test_save_new_artist_still_uses_lowercase_key(mapping_dir) -> None:
    result = save_manual_genre_mapping("Metallica", "Heavy Metal", mapping_dir, dry_run=False)
    assert result.artist_key == "metallica"
    assert "metallica" in _map(mapping_dir)


def test_save_dry_run_reports_the_real_key_and_writes_nothing(mapping_dir) -> None:
    before = (mapping_dir / "artist_genre.yaml").read_text(encoding="utf-8")
    result = save_manual_genre_mapping("Dua Lipa", "Pop", mapping_dir, dry_run=True)
    assert result.artist_key == "Dua Lipa" and result.written is False and result.dry_run is True
    assert (mapping_dir / "artist_genre.yaml").read_text(encoding="utf-8") == before


def test_save_default_description_can_be_overridden_for_new_entries_only(mapping_dir) -> None:
    save_manual_genre_mapping("Metallica", "Heavy Metal", mapping_dir, dry_run=False,
                              default_description="Manuell gesetzt via Control Center")
    save_manual_genre_mapping("kygo", "House; Deep House", mapping_dir, dry_run=False,
                              default_description="Manuell gesetzt via Control Center")
    m = _map(mapping_dir)
    assert m["metallica"]["description"] == "Manuell gesetzt via Control Center"
    assert m["kygo"]["description"] == "DJ"                                    # Bestand bleibt


def test_save_default_description_unchanged_when_not_given(mapping_dir) -> None:
    save_manual_genre_mapping("Metallica", "Heavy Metal", mapping_dir, dry_run=False)
    assert "library_repair.py" in _map(mapping_dir)["metallica"]["description"]


# ── normalize_genre_fields ───────────────────────────────────────────────

def test_normalize_trims_dedupes_and_drops_primary_from_secondary() -> None:
    primary, secondary = normalize_genre_fields("  Hip  Hop ", ["Deutschrap", "deutschrap", " Trap ", "", "hip hop"])
    assert primary == "Hip Hop"
    assert secondary == ["Deutschrap", "Trap"]


def test_normalize_keeps_user_casing_and_order() -> None:
    assert normalize_genre_fields("Pop", ["Zeta", "Alpha"]) == ("Pop", ["Zeta", "Alpha"])


def test_normalize_allows_empty_secondary() -> None:
    assert normalize_genre_fields("Pop", []) == ("Pop", [])


@pytest.mark.parametrize("primary", ["", "   ", None])
def test_normalize_rejects_empty_primary(primary) -> None:
    with pytest.raises(GenreDomainError):
        normalize_genre_fields(primary, ["x"])


@pytest.mark.parametrize("bad", ["Pop; Rock", "Pop\nRock", "a\x00b", "x" * 101])
def test_normalize_rejects_separators_control_chars_and_overlong_values(bad) -> None:
    with pytest.raises(GenreDomainError):
        normalize_genre_fields(bad, [])
    with pytest.raises(GenreDomainError):
        normalize_genre_fields("Pop", [bad])


def test_normalize_rejects_too_many_secondary() -> None:
    with pytest.raises(GenreDomainError):
        normalize_genre_fields("Pop", [f"G{i}" for i in range(21)])


# ── read / known_genres ─────────────────────────────────────────────────

def test_read_entry_is_case_insensitive_and_returns_the_real_key(mapping_dir) -> None:
    e = read_genre_mapping_entry("dua lipa", mapping_dir / "artist_genre.yaml")
    assert (e.key, e.primary, e.secondary) == ("Dua Lipa", "Pop", ["Dance Pop", "Disco"])
    assert e.description == "Britische Popsaengerin"


def test_read_entry_missing_artist_and_missing_file(mapping_dir, tmp_path) -> None:
    assert read_genre_mapping_entry("Unbekannt", mapping_dir / "artist_genre.yaml") is None
    assert read_genre_mapping_entry("x", tmp_path / "nope.yaml") is None


def test_known_genres_are_sorted_unique_casefolded_over_primary_and_secondary(mapping_dir) -> None:
    g = known_genres(mapping_dir / "artist_genre.yaml")
    assert g == sorted(set(g), key=str.casefold)
    assert {"Pop", "Dance Pop", "Hip Hop", "Trap", "Tropical House"} <= set(g)


# ── plan ────────────────────────────────────────────────────────────────

def test_plan_update_shows_removed_added_and_primary_change(mapping_dir) -> None:
    plan = plan_manual_genre_mapping("apache 207", "Pop", ["Deutschrap", "Melodic Rap"], mapping_dir)
    assert plan.change == "update" and plan.artist_key == "apache 207"
    assert plan.primary_changed is True
    assert plan.removed == ["Hip Hop", "Trap"]
    assert plan.added == ["Pop", "Melodic Rap"]
    assert plan.existing.primary == "Hip Hop"


def test_plan_secondary_only_edit_leaves_primary_unchanged(mapping_dir) -> None:
    plan = plan_manual_genre_mapping("apache 207", "Hip Hop", ["Deutschrap", "Trap", "Pop Rap"], mapping_dir)
    assert plan.primary_changed is False and plan.removed == [] and plan.added == ["Pop Rap"]


def test_plan_wrong_secondary_removed_and_correct_one_set(mapping_dir) -> None:
    plan = plan_manual_genre_mapping("Dua Lipa", "Pop", ["Dance Pop", "Synthpop"], mapping_dir)
    assert plan.removed == ["Disco"] and plan.added == ["Synthpop"]
    assert plan.change == "update"


def test_plan_unchanged_and_create(mapping_dir) -> None:
    same = plan_manual_genre_mapping("kygo", "House", ["Tropical House"], mapping_dir)
    assert same.change == "unchanged" and same.added == [] and same.removed == []
    new = plan_manual_genre_mapping("Metallica", "Heavy Metal", ["Thrash Metal"], mapping_dir)
    assert new.change == "create" and new.existing is None and new.artist_key == "metallica"


def test_plan_reorder_only_is_an_update_without_added_or_removed(mapping_dir) -> None:
    plan = plan_manual_genre_mapping("apache 207", "Hip Hop", ["Trap", "Deutschrap"], mapping_dir)
    assert plan.change == "update" and plan.added == [] and plan.removed == []


def test_plan_warns_only_about_new_genres_that_appear_nowhere_else(mapping_dir) -> None:
    plan = plan_manual_genre_mapping("apache 207", "Hip Hop", ["Deutschrap", "Trapp"], mapping_dir)
    assert len(plan.warnings) == 1 and "Trapp" in plan.warnings[0]
    known = plan_manual_genre_mapping("apache 207", "Hip Hop", ["Deutschrap", "Disco"], mapping_dir)
    assert known.warnings == []                                    # "Disco" steht bei Dua Lipa


def test_plan_is_read_only(mapping_dir) -> None:
    before = (mapping_dir / "artist_genre.yaml").read_bytes()
    plan_manual_genre_mapping("apache 207", "Pop", [], mapping_dir)
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


def test_plan_missing_or_broken_mapping_file_is_unavailable(tmp_path) -> None:
    with pytest.raises(GenreMappingUnavailableError):
        plan_manual_genre_mapping("x", "Pop", [], tmp_path)
    (tmp_path / "artist_genre.yaml").write_text("ARTIST_GENRE_MAP: [unclosed", encoding="utf-8")
    with pytest.raises(GenreMappingUnavailableError):
        plan_manual_genre_mapping("x", "Pop", [], tmp_path)


@pytest.mark.parametrize("artist", ["", "   ", "a\nb", "a\x00b", "x" * 201])
def test_plan_rejects_invalid_artist_names(mapping_dir, artist) -> None:
    with pytest.raises(GenreDomainError):
        plan_manual_genre_mapping(artist, "Pop", [], mapping_dir)


def test_etag_is_stable_and_changes_with_the_edited_fields(mapping_dir) -> None:
    a = plan_manual_genre_mapping("apache 207", "Pop", [], mapping_dir).etag
    assert a == plan_manual_genre_mapping("apache 207", "Rock", ["x"], mapping_dir).etag   # etag = Ist-Zustand
    save_manual_genre_mapping("apache 207", "Hip Hop; Trap", mapping_dir, dry_run=False)
    assert plan_manual_genre_mapping("apache 207", "Pop", [], mapping_dir).etag != a


# ── apply ───────────────────────────────────────────────────────────────

def test_apply_writes_only_the_edited_entry_and_preserves_everything_else(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("apache 207", "Pop", [], mapping_dir).etag
    before = _map(mapping_dir)

    plan, result = apply_manual_genre_mapping("apache 207", "Hip Hop", ["Deutschrap", "Pop Rap"],
                                              mapping_dir, expected_etag=etag)

    after = _map(mapping_dir)
    assert result.written is True and plan.change == "update"
    assert after["apache 207"]["secondary"] == ["Deutschrap", "Pop Rap"]
    assert after["apache 207"]["description"] == "Rapper"
    assert {k: v for k, v in after.items() if k != "apache 207"} == {k: v for k, v in before.items() if k != "apache 207"}
    assert list(after) == list(before)                                       # Reihenfolge stabil


def test_apply_edits_mixed_case_artist_in_place(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("Dua Lipa", "Pop", [], mapping_dir).etag
    apply_manual_genre_mapping("Dua Lipa", "Pop", ["Dance Pop", "Synthpop"], mapping_dir, expected_etag=etag)
    m = _map(mapping_dir)
    assert [k for k in m if k.casefold() == "dua lipa"] == ["Dua Lipa"]
    assert genre_from_mapping("Dua Lipa", mapping_dir / "artist_genre.yaml") == "Pop; Dance Pop; Synthpop"


def test_apply_rejects_a_stale_etag_and_writes_nothing(mapping_dir) -> None:
    stale = plan_manual_genre_mapping("apache 207", "Pop", [], mapping_dir).etag
    save_manual_genre_mapping("apache 207", "Hip Hop; Trap", mapping_dir, dry_run=False)   # jemand anders aendert
    before = (mapping_dir / "artist_genre.yaml").read_bytes()

    with pytest.raises(GenreMappingConflictError):
        apply_manual_genre_mapping("apache 207", "Pop", ["x"], mapping_dir, expected_etag=stale)

    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


def test_apply_create_requires_the_etag_of_a_missing_entry(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("Metallica", "x", [], mapping_dir).etag
    plan, _ = apply_manual_genre_mapping("Metallica", "Heavy Metal", ["Thrash Metal"], mapping_dir,
                                         expected_etag=etag, default_description="Manuell gesetzt via Control Center")
    assert plan.change == "create"
    with pytest.raises(GenreMappingConflictError):                          # Etag von "nicht vorhanden" ist jetzt veraltet
        apply_manual_genre_mapping("Metallica", "Metal", [], mapping_dir, expected_etag=etag)


def test_apply_unchanged_does_not_rewrite_the_file(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("kygo", "House", ["Tropical House"], mapping_dir).etag
    mtime = (mapping_dir / "artist_genre.yaml").stat().st_mtime_ns
    _, result = apply_manual_genre_mapping("kygo", "House", ["Tropical House"], mapping_dir, expected_etag=etag)
    assert result.written is False and result.unchanged is True
    assert (mapping_dir / "artist_genre.yaml").stat().st_mtime_ns == mtime


def test_apply_invalid_input_writes_nothing(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("kygo", "x", [], mapping_dir).etag
    before = (mapping_dir / "artist_genre.yaml").read_bytes()
    with pytest.raises(GenreDomainError):
        apply_manual_genre_mapping("kygo", "Pop; Rock", [], mapping_dir, expected_etag=etag)
    assert (mapping_dir / "artist_genre.yaml").read_bytes() == before


def test_concurrent_applies_with_the_same_etag_only_one_wins(mapping_dir) -> None:
    etag = plan_manual_genre_mapping("apache 207", "x", [], mapping_dir).etag
    outcomes = []

    def worker(secondary):
        try:
            apply_manual_genre_mapping("apache 207", "Hip Hop", [secondary], mapping_dir, expected_etag=etag)
            outcomes.append("ok")
        except GenreMappingConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=worker, args=(f"G{i}",)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(outcomes) == ["conflict"] * 5 + ["ok"]


# ── Cross-Consistency gegen die ECHTEN Produktionsdaten (Kopie) ───────────

def test_edit_on_a_copy_of_the_real_mapping_is_seen_consistently_by_writer_lookup_and_genre_mapper(tmp_path):
    """Kopie der echten mapping/ (Produktion bleibt unberuehrt). 'Dua Lipa' ist
    dort gemischt geschrieben: nach der Bearbeitung muss es GENAU einen Key
    geben, und set-genre-Lookup (genre_from_mapping) und GenreMapper (Manual-
    Tier, lowercased Keys) muessen dieselbe neue Genre-Liste liefern."""
    import shutil

    from utils.genre_map import GenreMapper

    real = Path(__file__).resolve().parent.parent / "mapping"
    copy = tmp_path / "mapping"
    shutil.copytree(real, copy)
    target = copy / "artist_genre.yaml"
    before_text = target.read_text(encoding="utf-8")

    _, etag = get_genre_mapping("Dua Lipa", copy)
    apply_manual_genre_mapping("Dua Lipa", "Pop", ["Dance Pop", "Synthpop TEST"], copy, expected_etag=etag)

    m = _map(copy)
    assert [k for k in m if k.casefold() == "dua lipa"] == ["Dua Lipa"]
    assert genre_from_mapping("Dua Lipa", target) == "Pop; Dance Pop; Synthpop TEST"
    theirs = GenreMapper(str(copy)).determine_genre(artist_name="Dua Lipa")
    assert theirs is not None and theirs.source == "artist_exact"
    assert [theirs.primary, *theirs.secondary] == ["Pop", "Dance Pop", "Synthpop TEST"]

    # Nur der eine Eintrag hat sich geaendert: alle anderen 156 Eintraege und die
    # Reihenfolge sind identisch, der Textdiff bleibt klein.
    old = yaml.safe_load(before_text)["ARTIST_GENRE_MAP"]
    assert {k: v for k, v in m.items() if k != "Dua Lipa"} == {k: v for k, v in old.items() if k != "Dua Lipa"}
    assert list(m) == list(old)
    import difflib

    changed = [l for l in difflib.unified_diff(before_text.splitlines(), target.read_text(encoding="utf-8").splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    assert 0 < len(changed) <= 12
