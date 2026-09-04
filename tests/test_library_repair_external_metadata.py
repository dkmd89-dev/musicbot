# tests/test_library_repair_external_metadata.py
# -*- coding: utf-8 -*-
"""Level-3 MusicBrainz-ID-Nachtrag — reine Entscheidung. Prompt Abschnitt 8."""

import pytest

from services.library_repair import external_metadata as em

_REC = "12345678-1234-1234-1234-1234567890ab"
_REL = "abcdef01-2345-6789-abcd-ef0123456789"
_ISRC = "DEA123456789"


def _mb(**over):
    base = {"title": "Real Song", "artist": "Real Artist",
            "recording_id": _REC, "artist_id": _REC, "release_id": _REL,
            "release_group_id": _REL, "isrc": _ISRC}
    base.update(over)
    return base


def test_adds_only_missing_fields():
    current = {"recording_id": None, "artist_id": "already-there-uuid",
               "release_id": None, "release_group_id": None, "isrc": None}
    w = em.plan_id_writes(current, _mb(), file_title="Real Song")
    added = {k.split(":")[-1] for k in w}
    assert "MusicBrainz Recording Id" in added
    assert "MusicBrainz Artist Id" not in added   # bereits vorhanden -> nicht angefasst


def test_no_match_no_writes():
    current = {"recording_id": None, "artist_id": None, "release_id": None,
               "release_group_id": None, "isrc": None}
    assert em.plan_id_writes(current, {}, file_title="Real Song") == {}


def test_unsafe_title_blocks_all_writes():
    current = {"recording_id": None, "artist_id": None, "release_id": None,
               "release_group_id": None, "isrc": None}
    assert em.plan_id_writes(current, _mb(), file_title="Gelb prod. Xarbeats") == {}
    assert em.plan_id_writes(current, _mb(), file_title='F*cked Up') == {}


def test_mb_title_mismatch_blocks_writes():
    current = {"recording_id": None, "artist_id": None, "release_id": None,
               "release_group_id": None, "isrc": None}
    # MB lieferte einen komplett anderen Titel -> nicht uebernehmen
    assert em.plan_id_writes(current, _mb(title="Total Anderer Song"),
                             file_title="Mein Lied") == {}


def test_invalid_id_format_is_rejected():
    current = {"recording_id": None, "artist_id": None, "release_id": None,
               "release_group_id": None, "isrc": None}
    w = em.plan_id_writes(current, _mb(recording_id="not-a-uuid", isrc="BADISRC"),
                          file_title="Real Song")
    assert "----:com.apple.iTunes:MusicBrainz Recording Id" not in w
    assert "----:com.apple.iTunes:ISRC" not in w
    assert "----:com.apple.iTunes:MusicBrainz Release Id" in w   # der bleibt gueltig


def test_title_trust():
    assert em.title_is_trustworthy("Blauer Tag")
    assert not em.title_is_trustworthy("Song prod. Someone")
    assert not em.title_is_trustworthy("x" * 200)
    assert not em.title_is_trustworthy("")


def test_handled_codes():
    assert em.HANDLED_ISSUE_CODES == frozenset(
        {"META_MB_RECORDING_MISSING", "META_MB_RELEASE_MISSING", "META_ISRC_MISSING"})
