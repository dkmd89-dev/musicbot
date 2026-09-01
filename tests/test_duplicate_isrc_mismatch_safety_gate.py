# tests/test_duplicate_isrc_mismatch_safety_gate.py
# -*- coding: utf-8 -*-
"""
MusicBot — Duplicate Resolution Phase 2.3 (Identity & Classification
Robustness Audit): ISRC-Mismatch-Safety-Gate-Fix.

FINDING (Audit Case E): Vor diesem Fix konnte ein reiner ISRC-Mismatch
zwischen zwei Kandidaten (gleicher Artist+Titel, konsistente Duration,
kein Remix-/Live-Album-Kontext) einen automatischen REMOVE-Vorschlag
NICHT verhindern - obwohl ISRC laut
services/duplicate/classification.py::has_strong_identity_confirmation()
ein zur MusicBrainz Recording ID GLEICHWERTIGES Industriestandard-
Identitätssignal ist. `_evaluate_safety_gate()` prüfte einen
MB-Recording-ID-Mismatch unbedingt blockierend (Regel 2), besaß aber
keine symmetrische Regel für einen ISRC-Mismatch (Regel 2b, in Phase 2.3
ergänzt).

Root Cause: services/duplicate/resolution.py::_evaluate_safety_gate()
berechnete zwar `musicbrainz_match`, aber nie `isrc_match` - ein
ISRC-Widerspruch blieb dadurch strukturell unsichtbar für die
Safety-Gate-Entscheidung.

Severity: Kategorie 1 (Safety Problem, Auftrag Phase 2.3 Abschnitt 9) -
ein reproduzierbarer False-Positive-Vektor, kein reiner False Negative.
Nicht in der aktuellen Testbibliothek (/tmp/musicbot_test/library) aktiv
ausgelöst (keine der 5 realen Duplicate-Gruppen hängt aktuell an einem
ISRC-Mismatch), aber strukturell jederzeit auslösbar - siehe
docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md Abschnitt 22.
"""

from pathlib import Path

from services.duplicate.classification import (
    Candidate,
    Classification,
    normalize_artist_for_identity,
    normalize_title_for_identity,
)
from services.duplicate.resolution import GroupAction, resolve_group


def _candidate(
    path, artist="Artist", title="Title", classification=Classification.SINGLE,
    duration_seconds=None, mb_recording_id=None, isrc=None, album=None,
):
    return Candidate(
        path=Path(path),
        artist=artist,
        title=title,
        normalized_artist=normalize_artist_for_identity(artist),
        normalized_title=normalize_title_for_identity(title, artist),
        classification=classification,
        duration_seconds=duration_seconds,
        mb_recording_id=mb_recording_id,
        isrc=isrc,
        album=album,
    )


class TestIsrcMismatchBlocksRemove:
    def test_isrc_mismatch_with_consistent_duration_blocks_remove(self):
        """Der zentrale Regressionsfall (Audit Case E): OHNE den Fix wäre
        dies faelschlich RESOLVED/REMOVE PROPOSAL gewesen."""
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0, isrc="ISRC0000001",
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            duration_seconds=100.0, isrc="ISRC0000002",
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []
        assert "ISRC" in decision.reason

    def test_isrc_mismatch_blocks_unconditionally_even_without_duration_data(self):
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            isrc="ISRC0000001",
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            isrc="ISRC0000002",
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.remove_proposals == []

    def test_evidence_reports_isrc_match_false(self):
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0, isrc="ISRC0000001",
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            duration_seconds=100.0, isrc="ISRC0000002",
        )
        decision = resolve_group([album, single])
        assert decision.evidence[0].isrc_match is False
        assert decision.evidence[0].blocked is True


class TestIsrcMismatchDoesNotRegressExistingBehavior:
    def test_matching_isrc_still_resolves(self):
        """Nichtregression: identische ISRC bleibt weiterhin eine starke
        Bestätigung (Auftrag Phase 2 Abschnitt 6/7)."""
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0, isrc="ISRC0000001",
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            duration_seconds=105.0, isrc="ISRC0000001",
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.RESOLVED
        assert decision.evidence[0].isrc_match is True

    def test_missing_isrc_on_either_side_stays_unknown_not_blocking(self):
        """INV-D11 (Auftrag Phase 2.3 Abschnitt 11): fehlende Evidenz
        bleibt UNKNOWN, niemals FALSE - Gruppe 'Pueblo' (kein ISRC/MB-ID
        vorhanden) muss weiterhin auflösbar bleiben."""
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0,
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            duration_seconds=100.0,
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.RESOLVED
        assert decision.evidence[0].isrc_match is None

    def test_mb_id_match_and_isrc_mismatch_together_still_blocks(self):
        """Ein widersprechendes Signal (ISRC) darf nicht durch ein
        anderes, zufaellig uebereinstimmendes Signal (MB-ID) uebersteuert
        werden - beide Regeln sind unabhaengig blockierend."""
        album = _candidate(
            "A/2025 - Album/01.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=100.0, mb_recording_id="MB1", isrc="ISRC0000001",
        )
        single = _candidate(
            "A/Singles/x.m4a", classification=Classification.SINGLE,
            duration_seconds=100.0, mb_recording_id="MB1", isrc="ISRC0000002",
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.remove_proposals == []

    def test_real_pueblo_case_regression(self):
        """Realer Regressionsfall (Phase 2.1): kein ISRC/MB-ID auf
        beiden Seiten, konsistente Duration - muss weiterhin RESOLVED
        liefern."""
        album = _candidate(
            "makko/2023 - Lieb mich oder lass es, Pt.1+2/14 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.ALBUM_LIKE,
            duration_seconds=214.227302,
        )
        single = _candidate(
            "makko/Singles/2023 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.SINGLE,
            duration_seconds=214.227302,
        )
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]
