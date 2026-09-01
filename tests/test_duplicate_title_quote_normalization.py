# tests/test_duplicate_title_quote_normalization.py
# -*- coding: utf-8 -*-
"""
MusicBot — Duplicate Resolution Phase 2.2: False-Negative-Fix
(Anführungszeichen-Normalisierung).

Phase 2.1 (Real Findings Audit) hat belegt, dass zwei reale Duplicate-
Paare (makko / "Bequem", makko / "Grad mal ein Jahr") NIE als gemeinsame
Duplicate-Gruppe erkannt wurden, weil der Single-Tag ein umschließendes
Anführungszeichen-Paar trägt ('"Bequem"'), der Album-Tag jedoch nicht
('Bequem') - beide Kopien tragen dieselbe MusicBrainz Recording ID und
identische Duration (siehe docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md).

Dieser Test deckt:
  - services/duplicate/classification.py::normalize_title_for_identity()
    (Positiv-/Negativfälle, Auftrag Abschnitt 5)
  - Parität zu services/duplicate/detector.py::_clean_title_for_comparison()
    (Auftrag Abschnitt 4 - gleiche Eingabe -> gleiche relevante Identität)
  - den realen Regressionsfall über resolve_group() (Auftrag Abschnitt 5,
    "Realer Regressionstest")
  - dass die bereits bekannten kritischen Fälle (Dein Lügner/Pueblo/
    Nachts wach) durch den Fix unverändert bleiben
"""

from pathlib import Path

import pytest

from services.duplicate.classification import (
    Candidate,
    Classification,
    normalize_artist_for_identity,
    normalize_title_for_identity,
)
from services.duplicate.detector import DuplicateDetector
from services.duplicate.resolution import GroupAction, resolve_group


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


@pytest.fixture
def detector(tmp_path):
    return DuplicateDetector(FakeConfig(tmp_path))


# ─────────────────────────────────────────────────────────────────────────
# Positivfälle (Auftrag Abschnitt 5): semantisch identische Titel trotz
# unterschiedlicher umschließender Anführungszeichen müssen dieselbe
# Identity ergeben.
# ─────────────────────────────────────────────────────────────────────────

QUOTE_VARIANTS = [
    "Bequem",
    '"Bequem"',
    "'Bequem'",
    "„Bequem“",
    "“Bequem”",
]


class TestPositiveQuoteVariantsCollapseToSameIdentity:
    @pytest.mark.parametrize("variant", QUOTE_VARIANTS)
    def test_variant_normalizes_to_plain_title(self, variant):
        assert normalize_title_for_identity(variant, "makko") == "Bequem"

    def test_all_variants_produce_identical_normalized_title(self):
        normalized = {normalize_title_for_identity(v, "makko") for v in QUOTE_VARIANTS}
        assert normalized == {"Bequem"}


# ─────────────────────────────────────────────────────────────────────────
# Negativfälle (Auftrag Abschnitt 5): echte Titelbestandteile/andere
# Aufnahmen dürfen NICHT kollabieren.
# ─────────────────────────────────────────────────────────────────────────


class TestNegativeCasesDoNotCollapse:
    @pytest.mark.parametrize(
        "suffix", ["Live", "Remix", "Acoustic", "Extended", "Version", "Instrumental"]
    )
    def test_version_suffix_remains_distinct_from_plain_title(self, suffix):
        base = normalize_title_for_identity("Bequem")
        variant = normalize_title_for_identity(f"Bequem {suffix}")
        assert variant != base

    def test_internal_apostrophe_not_stripped(self):
        """"Rock 'n' Roll" beginnt/endet nicht mit einem Anführungszeichen
        - darf unveraendert bleiben (kein Entfernen interner Apostrophe)."""
        assert normalize_title_for_identity("Rock 'n' Roll") == "Rock 'n' Roll"

    def test_only_leading_quote_without_matching_trailing_quote_unaffected(self):
        assert normalize_title_for_identity('"Bequem (Remix)') == '"Bequem (Remix)'

    def test_mismatched_quote_pair_not_stripped(self):
        """Erstes und letztes Zeichen sind Anführungszeichen, aber KEIN
        zusammenpassendes Paar (z.B. " am Anfang, ' am Ende) - bewusst
        NICHT entfernt, um kein falsches Paar zu unterstellen."""
        text = '"Bequem\''
        assert normalize_title_for_identity(text) == text

    def test_quote_only_title_not_collapsed_to_empty(self):
        assert normalize_title_for_identity('""') != "Unknown"

    def test_dup03_live_version_regression_still_holds(self):
        """DUP-03-Nichtregression (Modul-Docstring classification.py):
        weiterhin unterschiedliche Identity trotz des neuen Quote-Fixes."""
        base = normalize_title_for_identity("Hello")
        assert normalize_title_for_identity("Hello (Live at Glastonbury 2016)") != base
        assert normalize_title_for_identity("Hello (Remix)") != base
        assert normalize_title_for_identity("Hello (Radio Version)") != base


# ─────────────────────────────────────────────────────────────────────────
# Detector-Parität (Auftrag Abschnitt 4): gleiche Eingabe muss in
# classification.py UND detector.py dieselbe relevante Identität ergeben.
# ─────────────────────────────────────────────────────────────────────────


class TestDetectorParity:
    @pytest.mark.parametrize("variant", QUOTE_VARIANTS)
    def test_detector_and_classification_agree_on_quote_variants(self, detector, variant):
        normalized_artist = detector._normalize_artist_for_comparison("makko")
        detector_result = detector._clean_title_for_comparison(variant, normalized_artist)
        classification_result = normalize_title_for_identity(variant, "makko")
        assert detector_result == classification_result

    @pytest.mark.parametrize(
        "title", ["Bequem Live", "Bequem Remix", "Hello (Live at Glastonbury 2016)"]
    )
    def test_detector_and_classification_agree_on_version_suffixes(self, detector, title):
        normalized_artist = detector._normalize_artist_for_comparison("makko")
        detector_result = detector._clean_title_for_comparison(title, normalized_artist)
        classification_result = normalize_title_for_identity(title, "makko")
        assert detector_result == classification_result


# ─────────────────────────────────────────────────────────────────────────
# Realer Regressionstest (Auftrag Abschnitt 5): die beiden bisher
# unsichtbaren Duplicate-Paare müssen jetzt korrekt aufgelöst werden.
# ─────────────────────────────────────────────────────────────────────────


def _candidate(path, title, classification, mb_recording_id=None, duration_seconds=None):
    return Candidate(
        path=Path(path),
        artist="makko",
        title=title,
        normalized_artist=normalize_artist_for_identity("makko"),
        normalized_title=normalize_title_for_identity(title, "makko"),
        classification=classification,
        mb_recording_id=mb_recording_id,
        duration_seconds=duration_seconds,
    )


class TestRealBequemAndGradMalEinJahrRegression:
    """Reale Tag-Werte aus Phase 2.1 (Real Findings Audit): Single-Tag
    trägt Anführungszeichen, Album-Tag nicht; beide teilen dieselbe
    MusicBrainz Recording ID und identische Duration."""

    def test_bequem_now_forms_shared_identity_and_resolves(self):
        single = _candidate(
            "makko/Singles/2021 - Bequem.m4a", '"Bequem"',
            Classification.SINGLE, mb_recording_id="5b72dd3a-49b0-46af-84cf-632137d31fa4",
            duration_seconds=205.101859,
        )
        album = _candidate(
            "makko/2021 - Leb es oder lass es 2/11 - Bequem.m4a", "Bequem",
            Classification.ALBUM_LIKE, mb_recording_id="5b72dd3a-49b0-46af-84cf-632137d31fa4",
            duration_seconds=205.101859,
        )
        assert single.identity_key() == album.identity_key()

        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]
        assert decision.evidence[0].strong_identity_confirmed is True
        assert decision.evidence[0].blocked is False

    def test_grad_mal_ein_jahr_now_forms_shared_identity_and_resolves(self):
        single = _candidate(
            "makko/Singles/2021 - Grad mal ein Jahr.m4a", '"Grad mal ein Jahr"',
            Classification.SINGLE, mb_recording_id="a8cfbd40-0131-44b8-93b9-c507f97840e2",
            duration_seconds=153.065941,
        )
        album = _candidate(
            "makko/2021 - Leb es oder lass es 2/02 - Grad mal ein Jahr.m4a", "Grad mal ein Jahr",
            Classification.ALBUM_LIKE, mb_recording_id="a8cfbd40-0131-44b8-93b9-c507f97840e2",
            duration_seconds=153.065941,
        )
        assert single.identity_key() == album.identity_key()

        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]


# ─────────────────────────────────────────────────────────────────────────
# Bestehende kritische Fälle (Auftrag Abschnitt 5): müssen durch den Fix
# unverändert bleiben.
# ─────────────────────────────────────────────────────────────────────────


class TestExistingCriticalCasesUnaffectedByQuoteFix:
    def test_dein_luegner_still_resolves(self):
        """Realer Fall: BEIDE Kopien (Album+Single) tragen konsistent
        dasselbe Anführungszeichen-Paar ('"Dein Lügner"') - muss weiterhin
        RESOLVED liefern, exakt wie vor dem Fix."""
        single = _candidate(
            "makko/Singles/2023 - Dein Lügner.m4a", '"Dein Lügner"',
            Classification.SINGLE, mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96",
            duration_seconds=131.587483,
        )
        album = _candidate(
            "makko/2023 - Lieb mich oder lass es, Pt.1+2/15 - Dein Lügner.m4a", '"Dein Lügner"',
            Classification.ALBUM_LIKE, mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96",
            duration_seconds=131.587483,
        )
        decision = resolve_group([single, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert decision.remove_proposals == [single]

    def test_nachts_wach_still_manual_review(self):
        track_02 = _candidate(
            "makko/2022 - Nachts wach (Remix EP)/02 - Nachts wach.m4a", "Nachts wach",
            Classification.ALBUM_LIKE, duration_seconds=185.341678,
        )
        track_02.album = "Nachts wach (Remix EP)"
        track_04 = _candidate(
            "makko/2022 - Nachts wach (Remix EP)/04 - Nachts wach.m4a", "Nachts wach",
            Classification.ALBUM_LIKE, duration_seconds=185.782857,
        )
        track_04.album = "Nachts wach (Remix EP)"
        decision = resolve_group([track_02, track_04])
        assert decision.action == GroupAction.MANUAL_REVIEW
        assert decision.remove_proposals == []

    def test_badchieff_album_vs_single_still_resolves(self):
        single_1 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS (1).m4a", "GUT AUS", Classification.SINGLE,
        )
        single_2 = _candidate(
            "Badchieff/Singles/2025 - GUT AUS.m4a", "GUT AUS", Classification.SINGLE,
        )
        album = _candidate(
            "Badchieff/2025 - HEUTE ODER GESTERN/12 - GUT AUS.m4a", "GUT AUS",
            Classification.ALBUM_LIKE,
        )
        decision = resolve_group([single_1, single_2, album])
        assert decision.action == GroupAction.RESOLVED
        assert decision.keep is album
        assert set(decision.remove_proposals) == {single_1, single_2}
