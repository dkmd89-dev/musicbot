# -*- coding: utf-8 -*-
"""
YAML-Editor der Mapping-Administration (Service-Ebene): Rohtext vom Client.

Sicherheit zuerst: der Text wird nie mit einem unsicheren Loader gelesen und
nie ungeprueft geschrieben. Erlaubt ist genau ein YAML-Dokument ohne Anker,
Aliase, Tags und doppelte Keys, mit dem erwarteten Root-Key, begrenzter Groesse
und Tiefe. Danach greifen dieselben fachlichen Validatoren wie im Visual
Editor. Geschrieben wird der validierte Text unveraendert (Kommentare bleiben).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from services import mapping_admin as ma
from services import mapping_backups as mb
from services import mapping_yaml as my

REPO_MAPPING = Path(__file__).resolve().parent.parent / "mapping"

ALIASES = "# Aliase\nGENRE_ALIASES:\n  rnb: R&B  # klassisch\n  hiphop: Hip Hop\n"


@pytest.fixture
def dirs(tmp_path):
    mdir, bdir = tmp_path / "mapping", tmp_path / "data" / "mapping_backups"
    mdir.mkdir()
    (mdir / "genre_aliases.yaml").write_text(ALIASES, encoding="utf-8")
    return mdir, bdir


def _plan(text, mdir, mapping_id=ma.MAPPING_ID_GENRE_ALIASES):
    return my.plan_raw_update(mapping_id, text, mdir)


def _invalid(text, mdir, mapping_id=ma.MAPPING_ID_GENRE_ALIASES) -> str:
    with pytest.raises(ma.MappingInvalidInputError) as info:
        _plan(text, mdir, mapping_id)
    return str(info.value)


# ── Lesen ────────────────────────────────────────────────────────────────


def test_read_raw_returns_text_verbatim_with_comments_and_etag(dirs):
    mdir, _ = dirs
    raw = my.read_raw(ma.MAPPING_ID_GENRE_ALIASES, mdir)

    assert raw.text == ALIASES and raw.filename == "genre_aliases.yaml"
    assert len(raw.etag) == 16 and raw.max_bytes == my.MAX_RAW_BYTES


def test_unknown_mapping_id_is_rejected(dirs):
    mdir, _ = dirs
    with pytest.raises(ma.MappingUnknownIdError):
        my.read_raw("../evil", mdir)


# ── Sicheres Parsen ──────────────────────────────────────────────────────


@pytest.mark.parametrize("text,fragment", [
    ("GENRE_ALIASES:\n  a: !!python/object/apply:os.system ['echo pwn']\n", "Tags"),
    ("GENRE_ALIASES:\n  a: !!str Jazz\n", "Tags"),
    ("GENRE_ALIASES:\n  a: &x Jazz\n  b: *x\n", "Anker"),
    ("GENRE_ALIASES:\n  base: &b {a: Jazz}\n  other:\n    <<: *b\n", "Anker"),
    ("GENRE_ALIASES:\n  <<: {a: Jazz}\n", "Merge"),
    ("GENRE_ALIASES:\n  a: Jazz\n---\nGENRE_ALIASES:\n  b: Pop\n", "ein YAML-Dokument"),
    ("GENRE_ALIASES:\n  a: Jazz\n  a: Pop\n", "Doppelter Key"),
    ("GENRE_ALIASES: {a: [[[[[[[x]]]]]]]}\n", "verschachtelt"),
    ("? [a, b]\n: c\n", "Key muss ein einfacher Text"),
    ("GENRE_ALIASES: [unclosed\n", "kein gültiges YAML"),
])
def test_unsafe_or_ambiguous_yaml_is_rejected_with_reason(dirs, text, fragment):
    mdir, _ = dirs

    assert fragment in _invalid(text, mdir)


def test_python_object_tag_never_executes(dirs, tmp_path):
    mdir, _ = dirs
    marker = tmp_path / "pwned"
    _invalid(f"GENRE_ALIASES:\n  a: !!python/object/apply:pathlib.Path.touch [!!python/object/apply:pathlib.Path ['{marker}']]\n", mdir)

    assert not marker.exists()


def test_size_limit(dirs):
    mdir, _ = dirs
    big = "GENRE_ALIASES:\n" + "".join(f"  k{n}: Jazz\n" for n in range(my.MAX_RAW_BYTES // 10))

    assert "zu groß" in _invalid(big, mdir)


@pytest.mark.parametrize("text", ["GENRE_ALIASES:\n  a: Ja\x00zz\n", "GENRE_ALIASES:\n  a: Ja\x07zz\n"])
def test_control_characters_are_rejected(dirs, text):
    mdir, _ = dirs

    assert "Steuerzeichen" in _invalid(text, mdir)


def test_non_string_text_is_rejected(dirs):
    mdir, _ = dirs
    with pytest.raises(ma.MappingInvalidInputError):
        my.plan_raw_update(ma.MAPPING_ID_GENRE_ALIASES, None, mdir)  # type: ignore[arg-type]


# ── Struktur ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,fragment", [
    ("", "leer"),
    ("- a\n- b\n", "Mapping"),
    ("OTHER:\n  a: Jazz\n", "GENRE_ALIASES"),
    ("GENRE_ALIASES:\n  a: Jazz\nEXTRA:\n  b: Pop\n", "EXTRA"),
    ("GENRE_ALIASES: [a, b]\n", "Mapping"),
])
def test_wrong_structure_is_rejected(dirs, text, fragment):
    mdir, _ = dirs

    assert fragment in _invalid(text, mdir)


# ── Fachliche Validierung je Typ ─────────────────────────────────────────


def test_alias_entries_are_validated_like_in_the_visual_editor(dirs):
    mdir, _ = dirs
    message = _invalid('GENRE_ALIASES:\n  "' + "x" * 201 + '": Jazz\n  ok: "Ja\\nzz"\n  leer: ""\n  zahl: 5\n', mdir)

    assert "zu lang" in message and "Steuerzeichen" in message and "Text sein" in message
    assert message.count("\n") >= 3  # mehrere Fehler auf einmal, nicht nur der erste


def test_override_entries_and_uppercase_key_warning(dirs):
    mdir, _ = dirs
    (mdir / "genre_overrides.yaml").write_text("GENRE_OVERRIDES:\n  a: Jazz\n", encoding="utf-8")

    plan = _plan("GENRE_OVERRIDES:\n  a: Jazz\n  Trip Hop: Downtempo\n", mdir, ma.MAPPING_ID_GENRE_OVERRIDES)

    assert plan.change == "update" and any("greift zur Laufzeit nicht" in w for w in plan.warnings)
    assert "Text sein" in _invalid("GENRE_OVERRIDES:\n  a: 5\n", mdir, ma.MAPPING_ID_GENRE_OVERRIDES)
    assert "Text sein" in _invalid("GENRE_OVERRIDES:\n  2020: Jazz\n", mdir, ma.MAPPING_ID_GENRE_OVERRIDES)
    assert "Text sein" in _invalid("GENRE_OVERRIDES:\n  jn: yes\n", mdir, ma.MAPPING_ID_GENRE_OVERRIDES)   # YAML liest yes als Bool


def test_channel_genre_entries(dirs):
    mdir, _ = dirs
    (mdir / "channel_genre.yaml").write_text("CHANNEL_GENRE_MAP:\n  x:\n    primary: Pop\n", encoding="utf-8")
    ok = "CHANNEL_GENRE_MAP:\n  x:\n    primary: Pop\n    secondary: [Rock]\n    description: d\n"

    assert _plan(ok, mdir, ma.MAPPING_ID_CHANNEL_GENRE).change == "update"
    assert "primary fehlt" in _invalid("CHANNEL_GENRE_MAP:\n  x:\n    secondary: [Rock]\n", mdir, ma.MAPPING_ID_CHANNEL_GENRE)
    assert "Unbekanntes Feld" in _invalid("CHANNEL_GENRE_MAP:\n  x:\n    primary: Pop\n    farbe: rot\n", mdir, ma.MAPPING_ID_CHANNEL_GENRE)
    assert "Zu viele" in _invalid("CHANNEL_GENRE_MAP:\n  x:\n    primary: Pop\n    secondary: [" + ",".join(f"G{n}" for n in range(25)) + "]\n", mdir, ma.MAPPING_ID_CHANNEL_GENRE)
    assert "muss ein Mapping" in _invalid("CHANNEL_GENRE_MAP:\n  x: Pop\n", mdir, ma.MAPPING_ID_CHANNEL_GENRE)


def test_filter_list_validation_and_normalisation_warning(dirs):
    mdir, _ = dirs
    (mdir / "genre_filters.yaml").write_text("IGNORE_SECONDARY:\n- rock\n", encoding="utf-8")

    plan = _plan("IGNORE_SECONDARY:\n- rock\n- Indie\n- indie\n", mdir, ma.MAPPING_ID_GENRE_FILTERS)

    assert plan.change == "update" and any("nicht normalisiert" in w for w in plan.warnings)
    assert "Liste" in _invalid("IGNORE_SECONDARY: {a: b}\n", mdir, ma.MAPPING_ID_GENRE_FILTERS)
    assert _invalid("IGNORE_SECONDARY:\n- 5\n", mdir, ma.MAPPING_ID_GENRE_FILTERS)


def test_special_channels_validation_and_cross_category_warning(dirs):
    mdir, _ = dirs
    (mdir / "special_channel.yaml").write_text("SPECIAL_CHANNELS:\n  Podcast:\n  - A\n", encoding="utf-8")

    plan = _plan("SPECIAL_CHANNELS:\n  Podcast:\n  - A\n  Playlist:\n  - A\n", mdir, ma.MAPPING_ID_SPECIAL_CHANNELS)

    assert plan.change == "update" and any("A" in w and "Podcast" in w for w in plan.warnings)
    assert _invalid("SPECIAL_CHANNELS:\n  Podcast: []\n", mdir, ma.MAPPING_ID_SPECIAL_CHANNELS)


@pytest.mark.parametrize("filename,mapping_id", [
    ("channel_genre.yaml", ma.MAPPING_ID_CHANNEL_GENRE), ("genre_aliases.yaml", ma.MAPPING_ID_GENRE_ALIASES),
    ("genre_overrides.yaml", ma.MAPPING_ID_GENRE_OVERRIDES), ("genre_filters.yaml", ma.MAPPING_ID_GENRE_FILTERS),
    ("special_channel.yaml", ma.MAPPING_ID_SPECIAL_CHANNELS),
])
def test_the_real_repository_files_are_valid(tmp_path, filename, mapping_id):
    mdir = tmp_path / "mapping"
    mdir.mkdir()
    shutil.copy(REPO_MAPPING / filename, mdir / filename)
    text = (REPO_MAPPING / filename).read_text(encoding="utf-8")

    plan = _plan(text, mdir, mapping_id)

    assert plan.change == "unchanged"   # Rohtext == aktuelle Datei (auch ohne Schlusszeilenumbruch)


# ── Plan / Diff ──────────────────────────────────────────────────────────


def test_plan_reports_semantic_diff_and_text_diff(dirs):
    mdir, _ = dirs
    plan = _plan("# Aliase\nGENRE_ALIASES:\n  rnb: Rhythm and Blues\n  neo: Neo Soul\n", mdir)

    assert plan.change == "update"
    assert any("neo" in a for a in plan.added) and any("hiphop" in r for r in plan.removed)
    assert any("rnb" in c and "Rhythm and Blues" in c for c in plan.changed)
    assert any(line.startswith("+") and "Neo Soul" in line for line in plan.text_diff)
    assert plan.etag == my.read_raw(ma.MAPPING_ID_GENRE_ALIASES, mdir).etag


def test_comment_only_change_is_a_format_change(dirs):
    mdir, _ = dirs

    plan = _plan("# ganz neuer Kommentar\nGENRE_ALIASES:\n  rnb: R&B\n  hiphop: Hip Hop\n", mdir)

    assert plan.change == "format" and plan.added == plan.removed == plan.changed == []
    assert any("Kommentar" in line for line in plan.text_diff)


def test_identical_text_is_unchanged_and_crlf_is_normalised(dirs):
    mdir, _ = dirs

    assert _plan(ALIASES, mdir).change == "unchanged"
    assert _plan(ALIASES.replace("\n", "\r\n"), mdir).change == "unchanged"


# ── Schreiben ────────────────────────────────────────────────────────────


def _apply(text, mdir, bdir, etag=None, **kw):
    etag = etag or my.read_raw(ma.MAPPING_ID_GENRE_ALIASES, mdir).etag
    return my.apply_raw_update(ma.MAPPING_ID_GENRE_ALIASES, text, mdir, expected_etag=etag, backup_dir=bdir, **kw)


def test_write_keeps_text_verbatim_including_comments_and_backs_up_the_old_file(dirs):
    mdir, bdir = dirs
    new = "# Neuer Kopf\nGENRE_ALIASES:\n  rnb: R&B  # bleibt\n  neo: Neo Soul\n"

    plan, result = _apply(new, mdir, bdir)

    assert result.written is True and (mdir / "genre_aliases.yaml").read_text(encoding="utf-8") == new
    versions = mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES)
    assert len(versions) == 1 and mb.read_version(bdir, ma.MAPPING_ID_GENRE_ALIASES, versions[0].version_id) == ALIASES
    assert result.new_etag == my.read_raw(ma.MAPPING_ID_GENRE_ALIASES, mdir).etag != plan.etag


def test_stale_etag_is_conflict_and_changes_nothing(dirs):
    mdir, bdir = dirs
    stale = my.read_raw(ma.MAPPING_ID_GENRE_ALIASES, mdir).etag
    (mdir / "genre_aliases.yaml").write_text(ALIASES + "  neu: Pop\n", encoding="utf-8")   # anderer Schreiber

    with pytest.raises(ma.MappingConflictError):
        _apply("GENRE_ALIASES:\n  x: Jazz\n", mdir, bdir, etag=stale)

    assert "neu: Pop" in (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")


def test_invalid_text_is_never_written(dirs):
    mdir, bdir = dirs

    with pytest.raises(ma.MappingInvalidInputError):
        _apply("GENRE_ALIASES:\n  a: !!python/object/apply:os.system ['x']\n", mdir, bdir)

    assert (mdir / "genre_aliases.yaml").read_text(encoding="utf-8") == ALIASES
    assert mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES) == []


def test_unchanged_text_writes_and_backs_up_nothing(dirs):
    mdir, bdir = dirs

    _, result = _apply(ALIASES, mdir, bdir)

    assert result.written is False and result.unchanged is True
    assert mb.list_versions(bdir, ma.MAPPING_ID_GENRE_ALIASES) == []


def test_failed_backup_aborts_the_write(dirs, tmp_path):
    mdir, _ = dirs
    blocker = tmp_path / "kein_verzeichnis"
    blocker.write_text("x", encoding="utf-8")

    with pytest.raises(ma.MappingBackupError):
        _apply("GENRE_ALIASES:\n  x: Jazz\n", mdir, blocker / "b")

    assert (mdir / "genre_aliases.yaml").read_text(encoding="utf-8") == ALIASES


def test_written_file_is_loaded_by_the_visual_editor_api(dirs):
    mdir, bdir = dirs
    _apply("GENRE_ALIASES:\n  neo soulish: Neo Soul\n", mdir, bdir)

    entry, _ = ma.get_mapping_entry(ma.MAPPING_ID_GENRE_ALIASES, "neo soulish", mdir)

    assert entry.canonical == "Neo Soul"


def test_special_and_filter_values_must_be_text(dirs):
    mdir, _ = dirs
    (mdir / "special_channel.yaml").write_text("SPECIAL_CHANNELS:\n  Podcast:\n  - A\n", encoding="utf-8")
    (mdir / "genre_filters.yaml").write_text("IGNORE_SECONDARY:\n- rock\n", encoding="utf-8")

    assert "Text sein" in _invalid("SPECIAL_CHANNELS:\n  Podcast:\n  - 2020\n", mdir, ma.MAPPING_ID_SPECIAL_CHANNELS)
    assert "Liste" in _invalid("SPECIAL_CHANNELS:\n  Podcast: A\n", mdir, ma.MAPPING_ID_SPECIAL_CHANNELS)
    assert "Text sein" in _invalid("IGNORE_SECONDARY:\n- true\n", mdir, ma.MAPPING_ID_GENRE_FILTERS)
