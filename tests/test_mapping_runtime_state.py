# -*- coding: utf-8 -*-
"""
Runtime-Status der Mapping-Dateien: "gespeichert" vs. "vom Bot angewendet".

Der Bot meldet im Laufzeit-Snapshot die beim Start gesehenen SHA-256 der
Mapping-Dateien; das Control Center vergleicht sie mit dem aktuellen
Datei-Stand. Nichts wird geraten: fehlt der Snapshot oder der Abschnitt, ist
der Zustand "unknown".
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services import mapping_admin as ma
from services import mapping_runtime_state as mrs

_FILES = {
    "channel-genre": "channel_genre.yaml", "genre-aliases": "genre_aliases.yaml", "genre-overrides": "genre_overrides.yaml",
    "genre-filters": "genre_filters.yaml", "special-channels": "special_channel.yaml",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def mdir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    for mapping_id, filename in _FILES.items():
        (d / filename).write_text(f"# {mapping_id}\nKEY: 1\n", encoding="utf-8")
    return d


def _snapshot(hashes, status="available", started="2026-09-30T08:00:00+00:00", section=True, age=5.0):
    sections = {"mapping_files": {"hashes": hashes, "hashed_at": started}} if section else {}
    return {"status": status, "age_seconds": age, "message": None,
            "snapshot": {"bot_started_at": started, "sections": sections}}


def _by_id(statuses):
    return {s.mapping_id: s for s in statuses}


# ── Hashen (Bot-Seite) ───────────────────────────────────────────────────


def test_allowlist_covers_exactly_the_five_administrated_files():
    assert ma.mapping_file_names() == _FILES


def test_hash_mapping_files_hashes_raw_bytes_and_marks_missing_files(mdir):
    (mdir / "genre_filters.yaml").unlink()

    hashes = mrs.hash_mapping_files(mdir)

    assert set(hashes) == set(_FILES.values())
    assert hashes["genre_aliases.yaml"] == _sha("# genre-aliases\nKEY: 1\n")
    assert hashes["genre_filters.yaml"] is None


def test_snapshot_section_carries_hashes_but_no_paths(mdir):
    section = mrs.build_snapshot_section(mrs.hash_mapping_files(mdir), "2026-09-30T08:00:00+00:00")

    assert set(section) == {"hashes", "hashed_at"}
    assert str(mdir) not in repr(section)


# ── Vergleich (Control-Center-Seite) ─────────────────────────────────────


def test_unchanged_files_are_applied(mdir):
    result = mrs.evaluate(mdir, _snapshot(mrs.hash_mapping_files(mdir)))

    assert {s.state for s in result.statuses} == {"applied"}
    assert result.bot_running is True and result.snapshot_status == "available"


def test_saved_change_is_pending_restart_only_for_that_file(mdir):
    loaded = mrs.hash_mapping_files(mdir)
    (mdir / "genre_aliases.yaml").write_text("# neu\nKEY: 2\n", encoding="utf-8")

    statuses = _by_id(mrs.evaluate(mdir, _snapshot(loaded)).statuses)

    assert statuses["genre-aliases"].state == "pending_restart"
    assert "Neustart" in statuses["genre-aliases"].message
    assert statuses["genre-aliases"].saved_sha256 != statuses["genre-aliases"].loaded_sha256
    assert all(s.state == "applied" for k, s in statuses.items() if k != "genre-aliases")


def test_restoring_the_loaded_bytes_makes_it_applied_again(mdir):
    original = (mdir / "genre_aliases.yaml").read_text(encoding="utf-8")
    loaded = mrs.hash_mapping_files(mdir)
    (mdir / "genre_aliases.yaml").write_text("anders\n", encoding="utf-8")
    assert _by_id(mrs.evaluate(mdir, _snapshot(loaded)).statuses)["genre-aliases"].state == "pending_restart"

    (mdir / "genre_aliases.yaml").write_text(original, encoding="utf-8")

    assert _by_id(mrs.evaluate(mdir, _snapshot(loaded)).statuses)["genre-aliases"].state == "applied"


@pytest.mark.parametrize("status", ["missing", "corrupt"])
def test_missing_or_corrupt_snapshot_is_unknown_never_guessed(mdir, status):
    result = mrs.evaluate(mdir, {"status": status, "snapshot": None, "age_seconds": None, "message": "x"})

    assert {s.state for s in result.statuses} == {"unknown"}
    assert result.bot_running is False
    assert all(s.loaded_sha256 is None for s in result.statuses)


def test_snapshot_without_mapping_section_is_unknown_with_hint(mdir):
    result = mrs.evaluate(mdir, _snapshot({}, section=False))

    assert {s.state for s in result.statuses} == {"unknown"}
    assert "meldet" in result.statuses[0].message and "Neustart" in result.statuses[0].message


def test_stale_snapshot_still_compares_but_says_bot_is_not_running(mdir):
    loaded = mrs.hash_mapping_files(mdir)
    (mdir / "genre_filters.yaml").write_text("neu\n", encoding="utf-8")

    result = mrs.evaluate(mdir, _snapshot(loaded, status="stale", age=900.0))
    statuses = _by_id(result.statuses)

    assert result.bot_running is False and result.snapshot_status == "stale"
    assert statuses["genre-filters"].state == "pending_restart"
    assert "läuft nicht" in statuses["genre-filters"].message


def test_missing_file_is_unavailable(mdir):
    loaded = mrs.hash_mapping_files(mdir)
    (mdir / "special_channel.yaml").unlink()

    assert _by_id(mrs.evaluate(mdir, _snapshot(loaded)).statuses)["special-channels"].state == "unavailable"


def test_file_missing_at_bot_start_but_present_now_is_pending(mdir):
    hashes = mrs.hash_mapping_files(mdir)
    hashes["genre_aliases.yaml"] = None  # Bot hat beim Start keine Datei gesehen

    assert _by_id(mrs.evaluate(mdir, _snapshot(hashes)).statuses)["genre-aliases"].state == "pending_restart"


def test_special_channels_carry_a_note_about_partial_live_reading(mdir):
    statuses = _by_id(mrs.evaluate(mdir, _snapshot(mrs.hash_mapping_files(mdir))).statuses)

    assert statuses["special-channels"].note and "je Aufruf" in statuses["special-channels"].note
    assert statuses["genre-aliases"].note is None


def test_evaluation_never_exposes_paths_or_full_hashes(mdir):
    result = mrs.evaluate(mdir, _snapshot(mrs.hash_mapping_files(mdir)))

    for s in result.statuses:
        assert len(s.saved_sha256) == 12 and len(s.loaded_sha256) == 12
        assert str(mdir) not in repr(s)
