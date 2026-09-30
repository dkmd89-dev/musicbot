# -*- coding: utf-8 -*-
"""
Genre-Hierarchie (genre-hierarchy): Validierung, Plan/Preview und zeilenweiser
Writer von services/mapping_hierarchy.py — gegen eine KOPIE der echten
mapping/genre_hierarchy.yaml (Produktionsdaten) und kleine synthetische Baeume.
"""
from __future__ import annotations

import difflib
import shutil
from pathlib import Path

import pytest
import yaml

from services import mapping_admin as ma
from services import mapping_backups
from services import mapping_hierarchy as mh

_REAL = Path(__file__).resolve().parent.parent / "mapping" / "genre_hierarchy.yaml"

_SMALL = """---
GENRE_HIERARCHY:
  # Wurzeln
  Pop: null
  Rock: null   # bewusst ohne Unterteilung

  # Pop
  Indie Pop: Pop
  Synth Pop: Pop
  # Rock
  Punk: Rock
  Hardcore Punk: Punk
"""


def _mdir(tmp_path: Path, text: str) -> Path:
    d = tmp_path / "mapping"
    d.mkdir(exist_ok=True)
    (d / "genre_hierarchy.yaml").write_text(text, encoding="utf-8")
    return d


@pytest.fixture
def real_dir(tmp_path):
    return _mdir(tmp_path, _REAL.read_text(encoding="utf-8"))


@pytest.fixture
def small_dir(tmp_path):
    return _mdir(tmp_path, _SMALL)


def _payload(mdir: Path):
    entries = mh.get_hierarchy_state(mdir)[0]
    return [{"genre": e.genre, "parent": e.parent} for e in entries]


def _files(mdir: Path):
    """Dateien im Mapping-Verzeichnis ohne die Sperrdatei (.lock, gitignored)."""
    return sorted(p.name for p in mdir.iterdir() if not p.name.endswith(".lock"))


def _text(mdir: Path) -> str:
    return (mdir / "genre_hierarchy.yaml").read_text(encoding="utf-8")


def _set_parent(payload, genre, parent):
    for item in payload:
        if item["genre"] == genre:
            item["parent"] = parent
    return payload


def _diff_lines(before: str, after: str):
    return [ln for ln in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
            if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]


# ── Bestand: echte Datei ─────────────────────────────────────────────────


def test_real_file_state(real_dir):
    entries, etag, warnings = mh.get_hierarchy_state(real_dir)
    by = {e.genre: e for e in entries}

    assert len(entries) == 187 and len(etag) == 16 and warnings == []
    assert by["Hip Hop"].parent is None and by["Hip Hop"].depth == 0
    assert by["Drill"].parent == "Hip Hop" and by["Drill"].depth == 1 and by["Drill"].children == 4
    assert by["UK Drill"].parent == "Drill" and by["UK Drill"].depth == 2 and by["UK Drill"].children == 0


def test_real_file_saved_unchanged_is_a_noop(real_dir):
    before = _text(real_dir)
    etag = mh.get_hierarchy_state(real_dir)[1]

    plan, result = mh.apply_hierarchy_update(_payload(real_dir), real_dir, expected_etag=etag)

    assert plan.change == "unchanged" and result.written is False and result.unchanged is True
    assert _text(real_dir) == before


def test_describe_hierarchy_marks_roots(small_dir):
    assert mh.describe_hierarchy(small_dir) == {
        "Pop": "Wurzel", "Rock": "Wurzel", "Indie Pop": "Pop", "Synth Pop": "Pop",
        "Punk": "Rock", "Hardcore Punk": "Punk",
    }


# ── Validierung ──────────────────────────────────────────────────────────


def test_valid_hierarchy_normalizes(small_dir):
    assert mh.normalize_entries(_payload(small_dir))["Hardcore Punk"] == "Punk"


def test_blank_parent_means_root():
    result = mh.normalize_entries([{"genre": "A", "parent": ""}, {"genre": "B", "parent": None}, {"genre": "C"}])
    assert result == {"A": None, "B": None, "C": None}


def test_unknown_parent_is_rejected():
    with pytest.raises(ma.MappingInvalidInputError, match="existiert nicht"):
        mh.normalize_entries([{"genre": "R", "parent": None}, {"genre": "X", "parent": "Nope"}])


def test_parent_must_match_case_exactly_and_the_error_hints_at_the_key():
    with pytest.raises(ma.MappingInvalidInputError, match="Meinten Sie 'Hip Hop'"):
        mh.normalize_entries([{"genre": "Hip Hop", "parent": None}, {"genre": "Drill", "parent": "hip hop"}])


def test_self_reference_is_rejected():
    with pytest.raises(ma.MappingInvalidInputError, match="sein eigener Eltern-Eintrag"):
        mh.normalize_entries([{"genre": "R", "parent": None}, {"genre": "A", "parent": "A"}])


def test_cycle_is_rejected_and_reported_once():
    payload = [{"genre": "R", "parent": None}, {"genre": "A", "parent": "B"},
               {"genre": "B", "parent": "C"}, {"genre": "C", "parent": "A"}]
    with pytest.raises(ma.MappingInvalidInputError) as info:
        mh.normalize_entries(payload)
    assert str(info.value).count("Zyklus") == 1 and "A → B → C → A" in str(info.value)


def test_hierarchy_without_any_root_is_rejected():
    with pytest.raises(ma.MappingInvalidInputError, match="kein Wurzel-Genre"):
        mh.normalize_entries([{"genre": "A", "parent": "B"}, {"genre": "B", "parent": "A"}])


@pytest.mark.parametrize("payload, message", [
    ([{"genre": "R", "parent": None}, {"genre": "R", "parent": None}], "Doppeltes Genre"),
    ([{"genre": "R", "parent": None}, {"genre": "r", "parent": None}], "Doppeltes Genre"),
    ([{"genre": "", "parent": None}], "nicht leer"),
    ([{"genre": "   ", "parent": None}], "nicht leer"),
    ([{"genre": None, "parent": None}], "nicht leer"),
    ([{"genre": "A;B", "parent": None}], "';'"),
    ([{"genre": "A: B", "parent": None}], "erlaubt sind"),
    ([{"genre": "#tag", "parent": None}], "erlaubt sind"),
    ([{"genre": "-x", "parent": None}], "erlaubt sind"),
    ([{"genre": "Yes", "parent": None}], "nicht als Text"),
    ([{"genre": "2020", "parent": None}], "nicht als Text"),
    ([{"genre": "x" * 101, "parent": None}], "l(ae|ä)nger als"),
    ([], "nicht leer"),
    ("kein liste", "Liste"),
    (["kein objekt"], "Objekt"),
])
def test_invalid_payloads_are_rejected(payload, message):
    with pytest.raises(ma.MappingInvalidInputError, match=message):
        mh.normalize_entries(payload)


def test_too_many_entries_are_rejected():
    payload = [{"genre": f"G{i}", "parent": None} for i in range(mh.MAX_ENTRIES + 1)]
    with pytest.raises(ma.MappingInvalidInputError, match="Zu viele"):
        mh.normalize_entries(payload)


def test_all_errors_are_reported_together():
    payload = [{"genre": "R", "parent": None}, {"genre": "A", "parent": "Nope"}, {"genre": "B", "parent": "Nada"}]
    with pytest.raises(ma.MappingInvalidInputError) as info:
        mh.normalize_entries(payload)
    assert len(str(info.value).splitlines()) == 2


def test_umlauts_and_ampersand_names_are_allowed():
    assert mh.normalize_entries([{"genre": "R&B", "parent": None}, {"genre": "Kölsch Rap", "parent": "R&B"}])


# ── Plan / Preview ───────────────────────────────────────────────────────


def test_reparent_with_children_lists_affected_descendants_and_priority_shift(real_dir):
    payload = _set_parent(_payload(real_dir), "Hardstyle", "Drill")  # Tiefe 1 -> 2, 8 Kinder 2 -> 3

    plan = mh.plan_hierarchy_update(payload, real_dir)

    assert plan.change == "update" and plan.changed == ["Hardstyle: Electronic → Drill"] or plan.changed
    change = next(c for c in plan.changes if c.genre == "Hardstyle")
    assert change.kind == "parent_changed" and (change.old_depth, change.new_depth) == (1, 2)
    assert change.affected_count == 8 and len(change.affected) == 8
    assert any("Genre-Priorität" in w and "9 Genre" in w for w in plan.warnings)


def test_same_depth_move_reports_descendants_but_no_priority_shift(real_dir):
    payload = _set_parent(_payload(real_dir), "Drill", "Deutschrap")  # Tiefe bleibt 1

    plan = mh.plan_hierarchy_update(payload, real_dir)

    change = plan.changes[0]
    assert (change.old_depth, change.new_depth) == (1, 1) and change.affected_count == 4
    assert not any("Priorität" in w for w in plan.warnings)


def test_added_and_removed_are_listed(small_dir):
    payload = [p for p in _payload(small_dir) if p["genre"] != "Synth Pop"]
    payload.append({"genre": "Emo", "parent": "Rock"})

    plan = mh.plan_hierarchy_update(payload, small_dir)

    assert plan.added == ["Emo: Rock"] and plan.removed == ["Synth Pop: Pop"]
    assert any("Aliasen" in w for w in plan.warnings)


def test_removing_a_parent_but_keeping_its_children_is_rejected(small_dir):
    payload = [p for p in _payload(small_dir) if p["genre"] != "Punk"]  # Hardcore Punk hinge an Punk

    with pytest.raises(ma.MappingInvalidInputError, match="'Hardcore Punk'.*'Punk' existiert nicht"):
        mh.plan_hierarchy_update(payload, small_dir)


def test_removing_a_whole_subtree_is_allowed_but_flagged(small_dir):
    payload = [p for p in _payload(small_dir) if p["genre"] not in ("Punk", "Hardcore Punk")]

    plan = mh.plan_hierarchy_update(payload, small_dir)

    assert sorted(g.split(":")[0] for g in plan.removed) == ["Hardcore Punk", "Punk"]
    assert any("untergeordneten Genres entfernt: Punk" in w for w in plan.warnings)


def test_unchanged_plan_and_state_etag_agree(small_dir):
    entries, etag, _ = mh.get_hierarchy_state(small_dir)
    plan = mh.plan_hierarchy_update(_payload(small_dir), small_dir)
    assert plan.change == "unchanged" and plan.etag == etag == ma.get_current_etag("genre-hierarchy", small_dir)


# ── Writer: minimaler Diff, Kommentare, Reihenfolge ──────────────────────


def test_reparent_changes_exactly_one_line_and_keeps_comments(small_dir):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]

    mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Punk", "Pop"), small_dir, expected_etag=etag)

    assert _diff_lines(before, _text(small_dir)) == ["-  Punk: Rock", "+  Punk: Pop"]


def test_reparent_keeps_the_trailing_comment_of_the_line(tmp_path):
    mdir = _mdir(tmp_path, "GENRE_HIERARCHY:\n  Pop: null\n  Rock: null\n  Punk: Rock   # frueh\n")
    etag = mh.get_hierarchy_state(mdir)[1]

    mh.apply_hierarchy_update(_set_parent(_payload(mdir), "Punk", "Pop"), mdir, expected_etag=etag)

    assert "  Punk: Pop   # frueh\n" in _text(mdir)


def test_root_becomes_child_and_child_becomes_root(small_dir):
    etag = mh.get_hierarchy_state(small_dir)[1]
    payload = _set_parent(_set_parent(_payload(small_dir), "Rock", "Pop"), "Indie Pop", None)

    mh.apply_hierarchy_update(payload, small_dir, expected_etag=etag)

    parsed = yaml.safe_load(_text(small_dir))["GENRE_HIERARCHY"]
    assert parsed["Rock"] == "Pop" and parsed["Indie Pop"] is None


def test_new_child_is_inserted_after_its_last_sibling(small_dir):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]
    payload = _payload(small_dir) + [{"genre": "Dream Pop", "parent": "Pop"}]

    mh.apply_hierarchy_update(payload, small_dir, expected_etag=etag)

    assert _diff_lines(before, _text(small_dir)) == ["+  Dream Pop: Pop"]
    lines = _text(small_dir).splitlines()
    assert lines.index("  Dream Pop: Pop") == lines.index("  Synth Pop: Pop") + 1


def test_new_root_is_inserted_after_the_last_root(small_dir):
    etag = mh.get_hierarchy_state(small_dir)[1]
    payload = _payload(small_dir) + [{"genre": "Jazz", "parent": None}]

    mh.apply_hierarchy_update(payload, small_dir, expected_etag=etag)

    lines = _text(small_dir).splitlines()
    assert lines.index("  Jazz: null") == lines.index("  Rock: null   # bewusst ohne Unterteilung") + 1


def test_child_of_a_parent_without_children_goes_to_the_end_of_the_block(small_dir):
    etag = mh.get_hierarchy_state(small_dir)[1]
    payload = _payload(small_dir) + [{"genre": "Grunge", "parent": "Rock"}, {"genre": "Post Punk", "parent": "Hardcore Punk"}]

    mh.apply_hierarchy_update(payload, small_dir, expected_etag=etag)

    parsed = yaml.safe_load(_text(small_dir))["GENRE_HIERARCHY"]
    assert parsed["Grunge"] == "Rock" and parsed["Post Punk"] == "Hardcore Punk"
    assert _text(small_dir).endswith("  Post Punk: Hardcore Punk\n")


def test_removed_leaf_loses_only_its_line(small_dir):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]

    mh.apply_hierarchy_update([p for p in _payload(small_dir) if p["genre"] != "Synth Pop"], small_dir, expected_etag=etag)

    assert _diff_lines(before, _text(small_dir)) == ["-  Synth Pop: Pop"]


def test_real_file_edit_keeps_all_section_comments_and_touches_few_lines(real_dir):
    before = _text(real_dir)
    etag = mh.get_hierarchy_state(real_dir)[1]
    payload = _set_parent(_payload(real_dir), "Drill", "Deutschrap") + [{"genre": "Kabarett Pop", "parent": "Pop"}]

    mh.apply_hierarchy_update(payload, real_dir, expected_etag=etag)

    after = _text(real_dir)
    assert [ln for ln in before.splitlines() if ln.strip().startswith("#")] == \
        [ln for ln in after.splitlines() if ln.strip().startswith("#")]
    assert sorted(_diff_lines(before, after)) == sorted(["-  Drill: Hip Hop", "+  Drill: Deutschrap", "+  Kabarett Pop: Pop"])
    assert after.startswith("---\nGENRE_HIERARCHY:\n")


def test_file_without_trailing_newline_stays_valid(tmp_path):
    mdir = _mdir(tmp_path, "GENRE_HIERARCHY:\n  Pop: null\n  Rock: null")
    etag = mh.get_hierarchy_state(mdir)[1]

    mh.apply_hierarchy_update(_payload(mdir) + [{"genre": "Punk", "parent": "Rock"}], mdir, expected_etag=etag)

    assert yaml.safe_load(_text(mdir))["GENRE_HIERARCHY"]["Punk"] == "Rock"


# ── Sicherheit des Schreibens ────────────────────────────────────────────


def test_validation_failure_leaves_the_file_byte_identical(small_dir):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]

    with pytest.raises(ma.MappingInvalidInputError):
        mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Pop", "Indie Pop"), small_dir, expected_etag=etag)

    assert _text(small_dir) == before
    assert _files(small_dir) == ["genre_hierarchy.yaml"]


def test_stale_etag_is_a_conflict_and_writes_nothing(small_dir):
    before = _text(small_dir)

    with pytest.raises(ma.MappingConflictError):
        mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Punk", "Pop"), small_dir, expected_etag="0" * 16)

    assert _text(small_dir) == before


def test_external_change_between_preview_and_save_is_a_conflict(small_dir):
    etag = mh.get_hierarchy_state(small_dir)[1]
    payload = _set_parent(_payload(small_dir), "Punk", "Pop")
    (small_dir / "genre_hierarchy.yaml").write_text(_SMALL + "  Ska: Rock\n", encoding="utf-8")

    with pytest.raises(ma.MappingConflictError):
        mh.apply_hierarchy_update(payload, small_dir, expected_etag=etag)


def test_failed_atomic_replace_keeps_the_file_and_leaves_no_tmp(small_dir, monkeypatch):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]
    monkeypatch.setattr("utils.atomic_file.os.replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(OSError):
        mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Punk", "Pop"), small_dir, expected_etag=etag)

    assert _text(small_dir) == before
    assert _files(small_dir) == ["genre_hierarchy.yaml"]


def test_backup_is_created_before_writing_and_holds_the_old_text(small_dir, tmp_path):
    backups = tmp_path / "backups"
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]

    mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Punk", "Pop"), small_dir, expected_etag=etag, backup_dir=backups)

    versions = mapping_backups.list_versions(backups, "genre-hierarchy")
    assert len(versions) == 1
    assert mapping_backups.read_version(backups, "genre-hierarchy", versions[0].version_id) == before


def test_backup_failure_writes_nothing(small_dir, tmp_path, monkeypatch):
    before = _text(small_dir)
    etag = mh.get_hierarchy_state(small_dir)[1]
    monkeypatch.setattr(mapping_backups, "snapshot", lambda *a, **k: (_ for _ in ()).throw(OSError("voll")))

    with pytest.raises(ma.MappingBackupError):
        mh.apply_hierarchy_update(_set_parent(_payload(small_dir), "Punk", "Pop"), small_dir,
                                  expected_etag=etag, backup_dir=tmp_path / "backups")

    assert _text(small_dir) == before


@pytest.mark.parametrize("text, message", [
    ("GENRE_HIERARCHY:\n  Pop: null\n  'Rock': null\n", "Format"),
    ("GENRE_HIERARCHY:\n  Pop: null\n  Rock: null\n  Rock: Pop\n", "Doppelter Key"),
    ("GENRE_HIERARCHY:\r\n  Pop: null\r\n  Rock: null\r\n", "Windows-Zeilenenden"),
])
def test_unsupported_file_layout_is_refused_without_rewriting(tmp_path, text, message):
    mdir = _mdir(tmp_path, text)
    etag = mh.get_hierarchy_state(mdir)[1] if "Rock: Pop" not in text else "x"
    payload = [{"genre": "Pop", "parent": None}, {"genre": "Rock", "parent": "Pop"}]

    with pytest.raises((ma.MappingUnavailableError, ma.MappingConflictError)) as info:
        mh.apply_hierarchy_update(payload, mdir, expected_etag=etag)

    assert (mdir / "genre_hierarchy.yaml").read_bytes() == text.encode("utf-8")
    if isinstance(info.value, ma.MappingUnavailableError):
        assert message in str(info.value)


def test_missing_file_is_unavailable(tmp_path):
    with pytest.raises(ma.MappingUnavailableError):
        mh.get_hierarchy_state(tmp_path)


def test_broken_file_reports_warnings_instead_of_failing(tmp_path):
    mdir = _mdir(tmp_path, "GENRE_HIERARCHY:\n  Pop: null\n  Punk: Rock\n  A: B\n  B: A\n")

    entries, _etag, warnings = mh.get_hierarchy_state(mdir)

    assert len(entries) == 4
    assert any("'Rock' existiert nicht" in w for w in warnings) and any("Zyklus" in w for w in warnings)


def test_check_text_rejects_invalid_versions():
    with pytest.raises(ma.MappingInvalidInputError, match="Zyklus"):
        mh.check_text("GENRE_HIERARCHY:\n  R: null\n  A: B\n  B: A\n")
    with pytest.raises(ma.MappingInvalidInputError):
        mh.check_text("kein: hierarchie\n")
    mh.check_text(_SMALL)
