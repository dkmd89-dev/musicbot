# tests/test_duplicate_classification.py
# -*- coding: utf-8 -*-
"""
Tests für services/duplicate/classification.py (Duplicate Resolution
Phase 1). Reine Domain-Logik-Tests - keine Telegram-/FFmpeg-Abhängigkeit,
kein Dateisystem-Scan nötig (classify_by_path()/normalize_*() operieren
auf reinen Path-/String-Werten).

CLAUDE.md Abschnitt 7/8: importiert die echte Produktionsimplementierung,
kein Nachbau in der Testdatei.
"""

from pathlib import Path

from services.duplicate.classification import (
    Candidate,
    Classification,
    Confidence,
    DURATION_CONSISTENT_TOLERANCE_SECONDS,
    METADATA_COMPLETENESS_FIELDS,
    build_candidate,
    candidate_confidence,
    classify_by_path,
    compare_isrc_identity,
    compare_recording_identity_ids,
    compute_metadata_completeness,
    group_candidates_by_identity,
    has_album_context_risk,
    has_collision_suffix,
    has_strong_identity_confirmation,
    is_duration_consistent,
    normalize_artist_for_identity,
    normalize_title_for_identity,
)


class TestClassifyByPath:
    def test_singles_folder_is_single(self):
        assert (
            classify_by_path(Path("Artist/Singles/2025 - Track.m4a"))
            == Classification.SINGLE
        )

    def test_singles_folder_case_insensitive(self):
        assert (
            classify_by_path(Path("Artist/singles/2025 - Track.m4a"))
            == Classification.SINGLE
        )
        assert (
            classify_by_path(Path("Artist/SINGLES/2025 - Track.m4a"))
            == Classification.SINGLE
        )

    def test_year_album_folder_is_album_like(self):
        assert (
            classify_by_path(Path("Artist/2025 - Album/01 - Track.m4a"))
            == Classification.ALBUM_LIKE
        )

    def test_year_album_folder_without_track_number_still_album_like(self):
        """Test 10 (Auftrag Abschnitt 22): Album-Track ohne trkn bleibt
        ALBUM_LIKE - reine Pfad-Entscheidung, siehe auch
        tests/test_reprocess_artist_metadata.py::TestAlbumVsSinglesFilenameConvention."""
        assert (
            classify_by_path(Path("Artist/2025 - Album/Track.m4a"))
            == Classification.ALBUM_LIKE
        )

    def test_ep_folder_is_album_like_not_separate_category(self):
        """EP faellt gemaess Architecture Audit unter ALBUM_LIKE - kein
        separates EP-System in dieser Phase."""
        assert (
            classify_by_path(Path("Artist/2022 - Remix EP/02 - Track.m4a"))
            == Classification.ALBUM_LIKE
        )

    def test_unrelated_folder_is_ambiguous(self):
        assert (
            classify_by_path(Path("Artist/SomethingElse/Track.m4a"))
            == Classification.AMBIGUOUS
        )

    def test_special_channel_style_path_is_ambiguous(self):
        """Spezialkanal-/Compilation-Pfade (category/canonical_channel/...)
        matchen weder "Singles" noch das Jahr-Bindestrich-Muster."""
        assert (
            classify_by_path(Path("Podcast/Some Show/episode.m4a"))
            == Classification.AMBIGUOUS
        )

    def test_no_filesystem_access_pure_synthetic_path(self):
        """Funktioniert identisch fuer einen komplett nicht-existierenden
        Pfad - beweist, dass keine .exists()/.stat()-Abhaengigkeit besteht."""
        fake = Path("/this/path/does/not/exist/Artist/Singles/Track.m4a")
        assert classify_by_path(fake) == Classification.SINGLE


class TestNormalizeTitleForIdentity:
    def test_official_video_suffix_stripped(self):
        assert normalize_title_for_identity("Song (Official Video)") == "Song"

    def test_feat_notation_stripped_test7(self):
        """Test 7 (Auftrag Abschnitt 22): Feature-Artist darf nicht falsch
        aufgespalten werden / kein False Positive durch den Klammerinhalt."""
        assert normalize_title_for_identity("Song (feat. X)") == "Song"
        assert normalize_title_for_identity("Song (ft. X)") == "Song"

    def test_live_remix_acoustic_not_collapsed_dup03(self):
        """Test 8 (Auftrag Abschnitt 22) / DUP-03-Regressionsschutz: Live/
        Remix/Version-Zusaetze duerfen NICHT auf denselben normalisierten
        Titel wie das Original kollabieren."""
        base = normalize_title_for_identity("Hello")
        assert normalize_title_for_identity("Hello (Live at Glastonbury 2016)") != base
        assert normalize_title_for_identity("Hello (Remix)") != base
        assert normalize_title_for_identity("Hello (Radio Version)") != base
        assert normalize_title_for_identity("Hello (Acoustic)") != base
        assert normalize_title_for_identity("Hello (Extended Mix)") != base

    def test_whitespace_and_case_variant_normalized(self):
        """Test 6 (Auftrag Abschnitt 22): unterschiedliche Schreibweise."""
        assert normalize_title_for_identity("  Song   Title  ") == "Song Title"

    def test_empty_title_returns_unknown(self):
        assert normalize_title_for_identity("") == "Unknown"
        assert normalize_title_for_identity(None) == "Unknown"


class TestNormalizeArtistForIdentity:
    def test_topic_suffix_stripped_without_normalizer(self):
        assert normalize_artist_for_identity("Some Artist - Topic") == "Some Artist"

    def test_vevo_suffix_stripped(self):
        assert normalize_artist_for_identity("Some Artist VEVO") == "Some Artist"

    def test_empty_artist_returns_unknown(self):
        assert normalize_artist_for_identity("") == "Unknown"
        assert normalize_artist_for_identity(None) == "Unknown"

    def test_injected_normalizer_used_when_provided(self):
        class FakeNormalizer:
            def normalize(self, artist):
                return "Canonical Name"

        assert (
            normalize_artist_for_identity("raw name", FakeNormalizer())
            == "Canonical Name"
        )

    def test_injected_normalizer_exception_falls_back(self):
        class BrokenNormalizer:
            def normalize(self, artist):
                raise RuntimeError("boom")

        assert (
            normalize_artist_for_identity("Some Artist VEVO", BrokenNormalizer())
            == "Some Artist"
        )


class TestHasCollisionSuffix:
    def test_detects_numbered_suffix(self):
        """Test 9 (Auftrag Abschnitt 22)."""
        assert has_collision_suffix(Path("Singles/2025 - Track (1).m4a")) is True
        assert has_collision_suffix(Path("Singles/2025 - Track (2).m4a")) is True

    def test_no_suffix_on_plain_path(self):
        assert has_collision_suffix(Path("Singles/2025 - Track.m4a")) is False

    def test_parenthetical_content_that_is_not_a_number_not_flagged(self):
        assert has_collision_suffix(Path("Singles/2025 - Track (Live).m4a")) is False


class TestMetadataCompleteness:
    def test_fixed_field_set_documented(self):
        assert METADATA_COMPLETENESS_FIELDS == (
            "artist", "title", "album", "album_artist", "year", "genre",
            "track_number", "mb_recording_id", "mb_artist_id",
            "mb_release_id", "isrc", "lyrics_present", "cover_present",
        )

    def test_counts_only_defined_fields_not_arbitrary_extra_keys(self):
        fields = {
            "artist": "A", "title": "T", "some_unrelated_key": "should not count",
        }
        assert compute_metadata_completeness(fields) == 2

    def test_empty_and_zero_and_none_not_counted(self):
        fields = {"artist": "A", "title": "", "year": None, "track_number": 0}
        assert compute_metadata_completeness(fields) == 1

    def test_bool_fields_counted_correctly(self):
        fields = {"lyrics_present": True, "cover_present": False}
        assert compute_metadata_completeness(fields) == 1

    def test_full_set_counts_thirteen(self):
        fields = {k: "x" for k in METADATA_COMPLETENESS_FIELDS}
        assert compute_metadata_completeness(fields) == len(METADATA_COMPLETENESS_FIELDS)


class TestCandidateConfidence:
    def _candidate(self, classification, normalized_artist="Artist", normalized_title="Title"):
        return Candidate(
            path=Path("x.m4a"), artist="Artist", title="Title",
            normalized_artist=normalized_artist, normalized_title=normalized_title,
            classification=classification,
        )

    def test_single_is_high(self):
        assert candidate_confidence(self._candidate(Classification.SINGLE)) == Confidence.HIGH

    def test_album_like_is_high(self):
        assert candidate_confidence(self._candidate(Classification.ALBUM_LIKE)) == Confidence.HIGH

    def test_ambiguous_is_medium(self):
        assert candidate_confidence(self._candidate(Classification.AMBIGUOUS)) == Confidence.MEDIUM

    def test_missing_identity_is_unknown(self):
        c = self._candidate(Classification.SINGLE, normalized_artist="Unknown")
        assert candidate_confidence(c) == Confidence.UNKNOWN
        c2 = self._candidate(Classification.SINGLE, normalized_title="Unknown")
        assert candidate_confidence(c2) == Confidence.UNKNOWN


class TestBuildCandidate:
    def test_builds_from_raw_fields(self):
        fields = {
            "album": "Some Album", "track_number": 3, "artist": "Artist", "title": "Title",
        }
        candidate = build_candidate(
            path=Path("Artist/2025 - Some Album/03 - Title.m4a"),
            artist="Artist", title="Title", fields=fields,
        )
        assert candidate.classification == Classification.ALBUM_LIKE
        assert candidate.normalized_artist == "Artist"
        assert candidate.normalized_title == "Title"
        assert candidate.album == "Some Album"
        assert candidate.track_number == 3
        assert candidate.collision_suffix is False


class TestGroupCandidatesByIdentity:
    def _candidate(self, path, artist, title, classification=Classification.SINGLE):
        return Candidate(
            path=Path(path), artist=artist, title=title,
            normalized_artist=normalize_artist_for_identity(artist),
            normalized_title=normalize_title_for_identity(title),
            classification=classification,
        )

    def test_same_identity_grouped_together(self):
        a = self._candidate("A/Singles/x.m4a", "Artist", "Title")
        b = self._candidate("A/2025 - Album/x.m4a", "Artist", "Title", Classification.ALBUM_LIKE)
        groups = group_candidates_by_identity([a, b])
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2

    def test_different_identity_separate_groups(self):
        a = self._candidate("A/Singles/x.m4a", "Artist", "Title One")
        b = self._candidate("A/Singles/y.m4a", "Artist", "Title Two")
        groups = group_candidates_by_identity([a, b])
        assert len(groups) == 2

    def test_unknown_identity_excluded_from_grouping(self):
        """Test 'Empty/missing metadata' (Auftrag Abschnitt 22 Kontext):
        zwei Dateien ohne Artist/Titel duerfen NICHT faelschlich als
        Duplikat-Gruppe zusammengefasst werden."""
        a = self._candidate("A/Singles/x.m4a", "", "")
        b = self._candidate("A/Singles/y.m4a", "", "")
        groups = group_candidates_by_identity([a, b])
        assert len(groups) == 0

    def test_grouping_independent_of_input_order(self):
        a = self._candidate("A/Singles/x.m4a", "Artist", "Title")
        b = self._candidate("A/2025 - Album/x.m4a", "Artist", "Title", Classification.ALBUM_LIKE)
        groups_1 = group_candidates_by_identity([a, b])
        groups_2 = group_candidates_by_identity([b, a])
        key = ("Artist", "Title")
        assert {c.path for c in groups_1[key]} == {c.path for c in groups_2[key]}


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Safety-Gate-Evidenz-Primitiven
# (MusicBot — Duplicate Resolution Phase 2, Abschnitt 3/4/5/6)
# ─────────────────────────────────────────────────────────────────────────


class TestHasAlbumContextRisk:
    def test_remix_keyword_flagged(self):
        assert has_album_context_risk("Nachts wach (Remix EP)") is True

    def test_live_keyword_flagged(self):
        assert has_album_context_risk("Live at Wembley") is True

    def test_normal_album_name_not_flagged(self):
        assert has_album_context_risk("HEUTE ODER GESTERN") is False
        assert has_album_context_risk("Lieb mich oder lass es, Pt.1+2") is False

    def test_none_and_empty_not_flagged(self):
        assert has_album_context_risk(None) is False
        assert has_album_context_risk("") is False

    def test_word_boundary_prevents_false_positive_substring_match(self):
        """"Mix" darf nicht als Teilstring in unrelated Woertern
        matchen (z. B. "Mixtape")."""
        assert has_album_context_risk("Summer Mixtape Vol. 1") is False


class TestMusicBrainzAndIsrcComparison:
    def _candidate(self, mb_recording_id=None, isrc=None):
        return Candidate(
            path=Path("x.m4a"), artist="A", title="T",
            normalized_artist="A", normalized_title="T",
            classification=Classification.SINGLE,
            mb_recording_id=mb_recording_id, isrc=isrc,
        )

    def test_identical_mb_recording_id_is_match(self):
        a = self._candidate(mb_recording_id="abc-123")
        b = self._candidate(mb_recording_id="abc-123")
        assert compare_recording_identity_ids(a, b) is True

    def test_different_mb_recording_id_is_mismatch(self):
        a = self._candidate(mb_recording_id="abc-123")
        b = self._candidate(mb_recording_id="xyz-999")
        assert compare_recording_identity_ids(a, b) is False

    def test_missing_mb_recording_id_on_either_side_is_unknown(self):
        a = self._candidate(mb_recording_id="abc-123")
        b = self._candidate(mb_recording_id=None)
        assert compare_recording_identity_ids(a, b) is None
        assert compare_recording_identity_ids(b, a) is None
        assert compare_recording_identity_ids(b, b) is None

    def test_isrc_comparison_mirrors_mb_recording_id(self):
        a = self._candidate(isrc="DEQ322500136")
        b = self._candidate(isrc="DEQ322500136")
        c = self._candidate(isrc="US1234567890")
        assert compare_isrc_identity(a, b) is True
        assert compare_isrc_identity(a, c) is False
        assert compare_isrc_identity(a, self._candidate(isrc=None)) is None

    def test_strong_identity_confirmation_via_mb_id(self):
        a = self._candidate(mb_recording_id="abc-123")
        b = self._candidate(mb_recording_id="abc-123")
        assert has_strong_identity_confirmation(a, b) is True

    def test_strong_identity_confirmation_via_isrc_alone(self):
        a = self._candidate(isrc="DEQ322500136")
        b = self._candidate(isrc="DEQ322500136")
        assert has_strong_identity_confirmation(a, b) is True

    def test_no_strong_identity_confirmation_when_both_missing(self):
        a = self._candidate()
        b = self._candidate()
        assert has_strong_identity_confirmation(a, b) is False

    def test_no_strong_identity_confirmation_on_mismatch_alone(self):
        """Ein MB-ID-MISMATCH allein zaehlt NICHT als Bestaetigung -
        wird separat in resolution.py als eigener Widerspruch behandelt."""
        a = self._candidate(mb_recording_id="abc-123")
        b = self._candidate(mb_recording_id="xyz-999")
        assert has_strong_identity_confirmation(a, b) is False


class TestDurationConsistency:
    def _candidate(self, duration_seconds=None):
        return Candidate(
            path=Path("x.m4a"), artist="A", title="T",
            normalized_artist="A", normalized_title="T",
            classification=Classification.SINGLE,
            duration_seconds=duration_seconds,
        )

    def test_identical_duration_is_consistent(self):
        a = self._candidate(131.587483)
        b = self._candidate(131.587483)
        assert is_duration_consistent(a, b) is True

    def test_small_delta_within_tolerance_is_consistent(self):
        """Reales Badchieff-Beispiel: Resample 44100->48000 aendert die
        Duration geringfuegig (~0.06s), bleibt aber innerhalb der
        Toleranz."""
        a = self._candidate(180.00)
        b = self._candidate(180.00 + DURATION_CONSISTENT_TOLERANCE_SECONDS - 0.01)
        assert is_duration_consistent(a, b) is True

    def test_delta_beyond_tolerance_is_inconsistent(self):
        """Reales Nachts-wach-Beispiel: 0.441179s Abweichung, deutlich
        ueber der Toleranz."""
        a = self._candidate(185.341678)
        b = self._candidate(185.782857)
        assert is_duration_consistent(a, b) is False

    def test_missing_duration_on_either_side_is_unknown_not_inconsistent(self):
        a = self._candidate(180.0)
        b = self._candidate(None)
        assert is_duration_consistent(a, b) is None
        assert is_duration_consistent(b, a) is None
