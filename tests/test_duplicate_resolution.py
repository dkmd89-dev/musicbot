# tests/test_duplicate_resolution.py
# -*- coding: utf-8 -*-
"""
Tests für services/duplicate/resolution.py (Duplicate Resolution Phase 1).

Deckt die Decision Matrix (Architecture Audit Abschnitt 9), den
Tie-Breaker (Abschnitt 7.1/10-12), das Safety Gate (Abschnitt 15) und die
Determinismus-Anforderung (Abschnitt 13) ab - inklusive des dokumentierten
Badchieff-Realfalls (Auftrag Abschnitt 23) als Regressionstest, hier mit
den exakt real gemessenen Tag-Werten (siehe
docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md, Abschnitt 6.3)
nachgebildet - kein Hardcoding der Pfad-Strings als Erkennungslogik,
sondern derselbe allgemeine Code-Pfad wie für jeden anderen Fall.
"""

import random
from pathlib import Path

from services.duplicate.classification import (
    Candidate,
    Classification,
    normalize_artist_for_identity,
    normalize_title_for_identity,
)
from services.duplicate.resolution import GroupAction, resolve_group


def _candidate(
    path,
    artist="Artist",
    title="Title",
    classification=Classification.SINGLE,
    metadata_completeness=0,
    bitrate=None,
    collision_suffix=False,
):
    return Candidate(
        path=Path(path),
        artist=artist,
        title=title,
        normalized_artist=normalize_artist_for_identity(artist),
        normalized_title=normalize_title_for_identity(title),
        classification=classification,
        metadata_completeness=metadata_completeness,
        bitrate=bitrate,
        collision_suffix=collision_suffix,
    )


class TestNoDuplicateSingleCandidate:
    def test_single_candidate_is_no_duplicate(self):
        """Test 16 (Auftrag Abschnitt 22)."""
        decision = resolve_group([_candidate("A/Singles/x.m4a")])
        assert decision.action == GroupAction.NO_DUPLICATE
        assert decision.keep is None
        assert decision.remove_proposals == []

    def test_empty_list_is_no_duplicate(self):
        decision = resolve_group([])
        assert decision.action == GroupAction.NO_DUPLICATE


class TestExactDuplicate:
    def test_two_identical_singles_high_confidence_resolved(self):
        """Test 1 (Auftrag Abschnitt 22): exaktes Duplicate -> HIGH,
        deterministischer Gewinner."""
        a = _candidate("A/Singles/2025 - track.m4a")
        b = _candidate("A/Singles/2025 - Track.m4a")
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is not None
        assert len(decision.remove_proposals) == 1


class TestAlbumVsSingle:
    def test_album_wins_over_single(self):
        """Test 2 (Auftrag Abschnitt 22): Album vs Single -> Album KEEP."""
        single = _candidate("A/Singles/2025 - Track.m4a", classification=Classification.SINGLE)
        album = _candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE
        )
        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]
        assert decision.reason == "ALBUM_LIKE > SINGLE"

    def test_album_wins_even_with_worse_audio_quality(self):
        """Test 5 (Auftrag Abschnitt 22): Album-Prioritaet gilt VOR dem
        Qualitaets-Tie-Breaker - Kategorie-Rang hat immer Vorrang."""
        single = _candidate(
            "A/Singles/2025 - Track.m4a",
            classification=Classification.SINGLE, bitrate=320000,
        )
        album = _candidate(
            "A/2025 - Album/01 - Track.m4a",
            classification=Classification.ALBUM_LIKE, bitrate=128000,
        )
        decision = resolve_group([single, album])
        assert decision.keep is album
        assert decision.remove_proposals == [single]


class TestSingleVsSingleTieBreaker:
    def test_more_complete_metadata_wins(self):
        """Test 3 (Auftrag Abschnitt 22)."""
        poor = _candidate(
            "A/Singles/2025 - Track.m4a",
            classification=Classification.SINGLE, metadata_completeness=2,
        )
        rich = _candidate(
            "A/Singles/2025 - Track (1).m4a",
            classification=Classification.SINGLE, metadata_completeness=8,
        )
        decision = resolve_group([poor, rich])
        assert decision.keep is rich

    def test_higher_bitrate_wins_when_metadata_tied(self):
        low_br = _candidate(
            "A/Singles/2025 - Track.m4a",
            classification=Classification.SINGLE, metadata_completeness=5, bitrate=128000,
        )
        high_br = _candidate(
            "A/Singles/2025 - Track (1).m4a",
            classification=Classification.SINGLE, metadata_completeness=5, bitrate=256000,
        )
        decision = resolve_group([low_br, high_br])
        assert decision.keep is high_br

    def test_unknown_bitrate_does_not_artificially_favor_either_candidate(self):
        """Auftrag Abschnitt 11: bei unbekannter Bitrate nicht kuenstlich
        bevorzugen, sondern zur naechsten Tie-Breaker-Stufe weitergehen."""
        known = _candidate(
            "A/Singles/2025 - Track (1).m4a",
            classification=Classification.SINGLE, metadata_completeness=5, bitrate=256000,
            collision_suffix=True,
        )
        unknown = _candidate(
            "A/Singles/2025 - Track.m4a",
            classification=Classification.SINGLE, metadata_completeness=5, bitrate=None,
            collision_suffix=False,
        )
        # Stufe 2 wird uebersprungen (eine Seite unbekannt) -> Stufe 3
        # (kein Collision-Suffix) entscheidet: "Track.m4a" ohne "(1)" gewinnt,
        # UNABHAENGIG davon, dass "known" eine (im Vergleich zu "None")
        # hoehere Bitrate hat - genau das beweist, dass Stufe 2 hier nicht
        # angewendet wurde.
        decision = resolve_group([known, unknown])
        assert decision.keep is unknown

    def test_collision_suffix_loses_test9(self):
        """Test 9 (Auftrag Abschnitt 22): "(1)" verliert beim Tie-Breaker."""
        plain = _candidate(
            "A/Singles/2025 - Track.m4a",
            classification=Classification.SINGLE, collision_suffix=False,
        )
        suffixed = _candidate(
            "A/Singles/2025 - Track (1).m4a",
            classification=Classification.SINGLE, collision_suffix=True,
        )
        decision = resolve_group([suffixed, plain])
        assert decision.keep is plain
        assert decision.remove_proposals == [suffixed]

    def test_final_tiebreaker_is_lexicographically_smallest_path(self):
        a = _candidate("A/Singles/2025 - AAA.m4a", classification=Classification.SINGLE)
        b = _candidate("A/Singles/2025 - ZZZ.m4a", classification=Classification.SINGLE)
        # gleiche Identitaet erzwingen (Titel unterschiedlich, aber Test
        # ruft resolve_group direkt ohne Gruppierung auf - Identitaet ist
        # hier irrelevant fuer den Tie-Breaker selbst)
        decision = resolve_group([b, a])
        assert decision.keep is a


class TestAlbumVsAlbumTieBreaker:
    def test_tie_breaker_applied_between_two_albums(self):
        """Test 4 (Auftrag Abschnitt 22)."""
        a = _candidate(
            "A/2025 - Album One/01 - Track.m4a",
            classification=Classification.ALBUM_LIKE, metadata_completeness=3,
        )
        b = _candidate(
            "A/2025 - Album Two/01 - Track.m4a",
            classification=Classification.ALBUM_LIKE, metadata_completeness=9,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is b
        assert "ALBUM_LIKE Tie-Breaker" in decision.reason


class TestAmbiguousHandling:
    def test_ambiguous_plus_ambiguous_is_keep_both(self):
        """Test 15 (Auftrag Abschnitt 22)."""
        a = _candidate("A/Weird/x.m4a", classification=Classification.AMBIGUOUS)
        b = _candidate("A/Weird2/x.m4a", classification=Classification.AMBIGUOUS)
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.KEEP_BOTH
        assert decision.keep is None
        assert decision.remove_proposals == []

    def test_album_plus_ambiguous_is_manual_review_no_auto_remove(self):
        """Test 13 (Auftrag Abschnitt 22): kein automatisches Remove des
        Ambiguous-Kandidaten - UND kein automatisches Remove ueberhaupt,
        obwohl Album an sich eindeutig waere (Safety Gate)."""
        album = _candidate("A/2025 - Album/01 - x.m4a", classification=Classification.ALBUM_LIKE)
        ambiguous = _candidate("A/Weird/x.m4a", classification=Classification.AMBIGUOUS)
        decision = resolve_group([album, ambiguous])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []
        assert "ALBUM_LIKE" in decision.reason

    def test_single_plus_ambiguous_is_manual_review_no_auto_remove(self):
        """Test 14 (Auftrag Abschnitt 22)."""
        single = _candidate("A/Singles/2025 - x.m4a", classification=Classification.SINGLE)
        ambiguous = _candidate("A/Weird/x.m4a", classification=Classification.AMBIGUOUS)
        decision = resolve_group([single, ambiguous])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []
        assert "SINGLE" in decision.reason

    def test_ambiguous_alone_with_single_high_confidence_never_auto_removes_ambiguous(self):
        """Test 12 (Auftrag Abschnitt 22)."""
        single = _candidate("A/Singles/2025 - x.m4a", classification=Classification.SINGLE)
        ambiguous = _candidate("A/Weird/x.m4a", classification=Classification.AMBIGUOUS)
        decision = resolve_group([single, ambiguous])
        assert ambiguous not in decision.remove_proposals

    def test_three_way_group_with_one_ambiguous_forces_manual_review(self):
        """N-Wege-Verallgemeinerung (Modul-Docstring resolution.py): auch
        wenn zwei von drei Kandidaten eindeutig SAFE waeren, verhindert
        der eine AMBIGUOUS-Kandidat jeden automatischen REMOVE-Vorschlag
        fuer die GESAMTE Gruppe."""
        album = _candidate("A/2025 - Album/01 - x.m4a", classification=Classification.ALBUM_LIKE)
        single = _candidate("A/Singles/2025 - x.m4a", classification=Classification.SINGLE)
        ambiguous = _candidate("A/Weird/x.m4a", classification=Classification.AMBIGUOUS)
        decision = resolve_group([album, single, ambiguous])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.remove_proposals == []


class TestSafetyGate:
    def test_only_high_confidence_can_produce_remove_proposal(self):
        """Architecture Audit Abschnitt 15 (Safety Gate)."""
        album = _candidate("A/2025 - Album/01 - x.m4a", classification=Classification.ALBUM_LIKE)
        single = _candidate("A/Singles/2025 - x.m4a", classification=Classification.SINGLE)
        decision = resolve_group([album, single])
        assert decision.action == GroupAction.RESOLVED
        for candidate in decision.remove_proposals:
            from services.duplicate.classification import candidate_confidence, Confidence

            assert candidate_confidence(candidate) == Confidence.HIGH

    def test_never_more_than_one_keep_candidate(self):
        candidates = [
            _candidate(f"A/Singles/2025 - Track ({i}).m4a", classification=Classification.SINGLE)
            for i in range(5)
        ]
        decision = resolve_group(candidates)
        # genau ein KEEP, alle anderen REMOVE-Vorschlag
        assert decision.keep is not None
        assert len(decision.remove_proposals) == len(candidates) - 1


class TestDeterminism:
    def test_identical_decision_regardless_of_input_order(self):
        """Test 17 (Auftrag Abschnitt 22): identische Kandidaten in
        unterschiedlicher Eingangsreihenfolge -> exakt identische
        Entscheidung."""
        candidates = [
            _candidate("A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
                       metadata_completeness=3),
            _candidate("A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
                       metadata_completeness=7),
            _candidate("A/Singles/2025 - Track (1).m4a", classification=Classification.SINGLE,
                       metadata_completeness=1),
        ]
        reference = resolve_group(candidates)
        rng = random.Random(42)
        for _ in range(20):
            shuffled = candidates[:]
            rng.shuffle(shuffled)
            decision = resolve_group(shuffled)
            assert decision.keep.path == reference.keep.path
            assert {c.path for c in decision.remove_proposals} == {
                c.path for c in reference.remove_proposals
            }
            assert decision.action == reference.action
            assert decision.reason == reference.reason


class TestBadchieffRealCaseRegression:
    """Auftrag Abschnitt 23: der dokumentierte Badchieff-Fall als
    Regressionstest, mit den real gemessenen Tag-Werten (siehe
    docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md Abschnitt 6.3)
    nachgebildet. Beweist die ALLGEMEINE Policy (Pfadstruktur schlaegt
    ©alb-Tag-Inhalt), kein Hardcoding auf den konkreten Dateinamen als
    Erkennungsmerkmal - derselbe classify_by_path()/resolve_group()-Code
    wie in jedem anderen Test hier."""

    def test_album_version_wins_over_both_singles(self):
        single_1 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS (1).m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.SINGLE,
            collision_suffix=True,
        )
        single_2 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS.m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.SINGLE,
            collision_suffix=False,
        )
        album = _candidate(
            "Badchieff/2025 - HEUTE ODER GESTERN/12 - GUT AUS.m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.ALBUM_LIKE,
        )
        decision = resolve_group([single_1, single_2, album])

        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.keep.path == Path(
            "Badchieff/2025 - HEUTE ODER GESTERN/12 - GUT AUS.m4a"
        )
        assert set(decision.remove_proposals) == {single_1, single_2}
        assert decision.reason == "ALBUM_LIKE > SINGLE"

    def test_classification_derived_from_path_not_album_tag(self):
        """Beweist explizit: die Klassifikation haengt an der
        Pfadstruktur, obwohl der ©alb-Tag der Single-Dateien real
        "GUT AUS" (== Titel, Selbsttitel-Platzhalter) lautet - ein reiner
        Tag-Inhalts-Check haette dies faelschlich nicht von einem echten
        Album unterscheiden koennen (Architecture Audit Abschnitt 6.3)."""
        from services.duplicate.classification import classify_by_path

        single_path = Path("Badchieff/Singles/2025 - GUT AUS.m4a")
        # Album-Tag-Inhalt ("GUT AUS") wird von classify_by_path() nicht
        # einmal entgegengenommen - nur der Pfad zaehlt.
        assert classify_by_path(single_path) == Classification.SINGLE

    def test_badchieff_singles_confirmed_by_matching_isrc_and_mb_ids(self):
        """Phase 2 Real Findings Audit: alle drei realen Badchieff-
        Dateien teilen dieselbe ISRC UND dieselbe MusicBrainz Recording
        ID - staerkste beobachtete Evidenz dieses Audits. Safety Gate
        muss PASSED bleiben, Ergebnis unveraendert zu Phase 1."""
        single_1 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS (1).m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.SINGLE, collision_suffix=True,
        )
        single_1.isrc = "DEQ322500136"
        single_1.mb_recording_id = "11111111-1111-1111-1111-111111111111"
        single_2 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS.m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.SINGLE, collision_suffix=False,
        )
        single_2.isrc = "DEQ322500136"
        single_2.mb_recording_id = "11111111-1111-1111-1111-111111111111"
        album = _candidate(
            "Badchieff/2025 - HEUTE ODER GESTERN/12 - GUT AUS.m4a",
            artist="Badchieff", title="GUT AUS",
            classification=Classification.ALBUM_LIKE,
        )
        album.isrc = "DEQ322500136"
        album.mb_recording_id = "11111111-1111-1111-1111-111111111111"

        decision = resolve_group([single_1, single_2, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert set(decision.remove_proposals) == {single_1, single_2}
        assert all(not ev.blocked for ev in decision.evidence)
        assert all(ev.strong_identity_confirmed for ev in decision.evidence)


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Safety Gate (MusicBot — Duplicate Resolution Phase 2)
# ─────────────────────────────────────────────────────────────────────────


def _p2_candidate(
    path, artist="Artist", title="Title", classification=Classification.SINGLE,
    album=None, duration_seconds=None, mb_recording_id=None, isrc=None,
):
    c = _candidate(path, artist=artist, title=title, classification=classification)
    c.album = album
    c.duration_seconds = duration_seconds
    c.mb_recording_id = mb_recording_id
    c.isrc = isrc
    return c


class TestSafetyGateAdversarial:
    """Auftrag Abschnitt 11 (MusicBot — Duplicate Resolution Phase 2):
    Test A-L, gegen die echte resolve_group()-Implementierung."""

    def test_a_identical_recording_same_duration_resolves(self):
        a = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        b = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is b

    def test_b_album_vs_single_keeps_album(self):
        single = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        album = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        decision = resolve_group([single, album])
        assert decision.keep is album

    def test_c_two_singles_tie_breaker_still_applies(self):
        a = _p2_candidate(
            "A/Singles/2025 - AAA.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        b = _p2_candidate(
            "A/Singles/2025 - ZZZ.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        decision = resolve_group([b, a])
        assert decision.keep is a

    def test_d_two_albums_tie_breaker_still_applies(self):
        a = _p2_candidate(
            "A/2025 - Album One/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        a.metadata_completeness = 3
        b = _p2_candidate(
            "A/2025 - Album Two/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        b.metadata_completeness = 9
        decision = resolve_group([a, b])
        assert decision.keep is b

    def test_e_different_duration_no_strong_id_forces_manual_review(self):
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        b = _p2_candidate(
            "A/2025 - Album/02 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=185.0,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []

    def test_f_identical_mb_recording_id_is_strong_confirmation(self):
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0, mb_recording_id="abc-123",
        )
        b = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0, mb_recording_id="abc-123",
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.evidence[0].strong_identity_confirmed is True

    def test_g_different_mb_recording_ids_force_manual_review_unconditionally(self):
        """Auftrag Abschnitt 4: MB-ID-Widerspruch blockiert UNBEDINGT,
        auch wenn die Duration konsistent ist."""
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0, mb_recording_id="abc-123",
        )
        b = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0, mb_recording_id="xyz-999",
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.remove_proposals == []

    def test_h_remix_album_context_plus_duration_mismatch_no_mb_id(self):
        """Realer Nachts-wach-Fall (Phase 1.1 Real Findings Audit) -
        allgemeine Policy, nicht hardcodiert."""
        a = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/02 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.341678,
        )
        b = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/04 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.782857,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []
        assert "Remix" in decision.reason or "Duration" in decision.reason

    def test_i_missing_mb_ids_but_consistent_duration_still_resolves(self):
        """Realer Pueblo-Fall: kein MB-ID auf beiden Seiten, aber
        konsistente Duration - MUSS weiterhin auflösbar bleiben (Auftrag
        Abschnitt 4/10)."""
        a = _p2_candidate(
            "makko/2023 - Lieb mich oder lass es, Pt.1+2/14 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.ALBUM_LIKE,
            album="Lieb mich oder lass es, Pt.1+2", duration_seconds=214.227302,
        )
        b = _p2_candidate(
            "makko/Singles/2023 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.SINGLE,
            duration_seconds=214.227302,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is a
        assert decision.remove_proposals == [b]

    def test_j_replaygain_divergence_alone_is_not_a_blocking_signal(self):
        """Auftrag Abschnitt 11 Test J - bewusst gepruefte Entscheidung:
        ReplayGain ist KEIN Teil des Safety Gate (siehe classification.py
        Modul-Docstring) - kann sich bei DERSELBEN Aufnahme legitim
        aendern (scripts/normalize_test_library_loudness.py normalisiert
        LUFS/ReplayGain absichtlich neu). Bei konsistenter Duration und
        ohne widersprechende MB-ID bleibt die Gruppe daher auflösbar,
        auch wenn (hier nicht als Feld modelliert) ReplayGain stark
        divergieren wuerde."""
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        b = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED

    def test_k_cover_hash_is_informational_only_not_part_of_gate(self):
        """Test K: identisches Cover ist unterstuetzende, aber nicht
        entscheidende Evidenz - cover_sha256 fliesst nicht in blocked
        ein."""
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        a.cover_sha256 = "same-hash"
        b = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        b.cover_sha256 = "same-hash"
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED

    def test_l_differing_cover_hash_does_not_block_resolution_alone(self):
        """Test L: ein abweichendes Cover darf allein KEIN Duplicate
        verhindern."""
        a = _p2_candidate(
            "A/2025 - Album/01 - Track.m4a", classification=Classification.ALBUM_LIKE,
            duration_seconds=180.0,
        )
        a.cover_sha256 = "hash-one"
        b = _p2_candidate(
            "A/Singles/2025 - Track.m4a", classification=Classification.SINGLE,
            duration_seconds=180.0,
        )
        b.cover_sha256 = "hash-two"
        decision = resolve_group([a, b])
        assert decision.action == GroupAction.RESOLVED
        assert decision.remove_proposals == [b]


class TestSafetyGateDeterminism:
    def test_blocked_decision_identical_regardless_of_input_order(self):
        a = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/02 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.341678,
        )
        b = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/04 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.782857,
        )
        reference = resolve_group([a, b])
        rng = random.Random(7)
        for _ in range(10):
            shuffled = [a, b]
            rng.shuffle(shuffled)
            decision = resolve_group(shuffled)
            assert decision.action == reference.action == GroupAction.MANUAL_REVIEW
            assert decision.remove_proposals == []


class TestRealGroupRegressions:
    """Phase 1.1 Real Findings Audit - die drei real vorgefundenen
    Duplicate-Gruppen der Testbibliothek, mit den real gemessenen Werten
    nachgebildet (nicht hardcodiert auf den Dateinamen, derselbe
    allgemeine resolve_group()-Codepfad wie jeder andere Test)."""

    def test_makko_dein_luegner_remains_resolved(self):
        single = _p2_candidate(
            "makko/Singles/2023 - Dein Lügner.m4a",
            artist="makko", title="Dein Lügner", classification=Classification.SINGLE,
            duration_seconds=131.587483,
            mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96",
        )
        album = _p2_candidate(
            "makko/2023 - Lieb mich oder lass es, Pt.1+2/15 - Dein Lügner.m4a",
            artist="makko", title="Dein Lügner", classification=Classification.ALBUM_LIKE,
            album="Lieb mich oder lass es, Pt.1+2", duration_seconds=131.587483,
            mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96",
        )
        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]
        assert decision.evidence[0].musicbrainz_match is True
        assert decision.evidence[0].duration_consistent is True

    def test_makko_pueblo_remains_resolved_without_mb_id(self):
        single = _p2_candidate(
            "makko/Singles/2023 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.SINGLE,
            duration_seconds=214.227302,
        )
        album = _p2_candidate(
            "makko/2023 - Lieb mich oder lass es, Pt.1+2/14 - Pueblo.m4a",
            artist="makko", title="Pueblo", classification=Classification.ALBUM_LIKE,
            album="Lieb mich oder lass es, Pt.1+2", duration_seconds=214.227302,
        )
        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]
        assert decision.evidence[0].musicbrainz_match is None
        assert decision.evidence[0].duration_consistent is True

    def test_makko_nachts_wach_now_manual_review_not_remove(self):
        """Der zentrale Phase-2-Regressionstest: dieser Fall war in
        Phase 1 faelschlich RESOLVED/REMOVE PROPOSAL - Phase 1.1 hat das
        als False-Positive-Risiko belegt. Nach dem Safety Gate MUSS
        dieser Fall MANUAL_REVIEW ergeben, kein REMOVE mehr."""
        track_02 = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/02 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.341678,
        )
        track_04 = _p2_candidate(
            "makko/2022 - Nachts wach (Remix EP)/04 - Nachts wach.m4a",
            artist="makko", title="Nachts wach", classification=Classification.ALBUM_LIKE,
            album="Nachts wach (Remix EP)", duration_seconds=185.782857,
        )
        decision = resolve_group([track_02, track_04])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.keep is None
        assert decision.remove_proposals == []
        ev = decision.evidence[0]
        assert ev.duration_consistent is False
        assert ev.album_context_risk is True
        assert ev.strong_identity_confirmed is False
        assert ev.blocked is True
