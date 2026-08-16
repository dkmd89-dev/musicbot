"""
Characterization-Tests fuer GenreMapper.determine_genre() gegen die echte
mapping/-Dir - Phase 2, deckt Pfade ab, die tests/test_genre_processor.py
(Phase 1) nicht beruehrt: Fuzzy-Matching, Regex-Regeln, Hierarchie-Fallback.

Zwei der hier charakterisierten Verhalten sind bekannte, bewusst
zurueckgestellte Bugs (siehe docs/MusicBot_ENGINEERING_BASELINE.md):

- GENRE-002: mapping/genre_rules.yaml hat keinen Top-Level-Key "GENRE_RULES"
  (nur keyword_rules/artist_rules/title_rules) - GenreMapper.rules ist mit
  der echten Datei daher immer leer, _apply_rules() liefert immer None.
- GENRE-003: GenreMapper.get_main_genre() lowercased den Suchschluessel,
  aber self.hierarchy-Keys werden aus dem YAML unveraendert (Title-Case)
  geladen - der Hierarchie-Lookup trifft praktisch nie, source="hierarchy"
  wird faktisch nie erreicht.

Diese Tests frieren das AKTUELLE (fehlerhafte) Verhalten ein, ohne es zu
fixen - das ist eine bewusste Nutzerentscheidung (Regel 3: Mapping-
Aenderungen wie Codeaenderungen behandeln, kein Nebenbei-Fix).
"""

import pytest

from utils.genre_map import GenreMapper


@pytest.fixture
def genre_mapper(config):
    return GenreMapper(str(config.GENRE_MAPPING_DIR))


class TestFuzzyMatching:
    """
    Beispiele empirisch gegen die echte mapping/artist_genre.yaml verifiziert
    (rapidfuzz WRatio, Schwelle 85 fuer Artists).
    """

    def test_artist_fuzzy_match_above_threshold(self, genre_mapper):
        result = genre_mapper.determine_genre(artist_name="Baussa")
        assert result is not None
        assert result.source == "artist_fuzzy"
        assert result.primary == "Hip Hop"
        assert result.confidence == 0.85

    def test_artist_typo_below_threshold_returns_none(self, genre_mapper):
        result = genre_mapper.determine_genre(artist_name="Basua")
        assert result is None

    def test_exact_artist_match_takes_priority_over_fuzzy(self, genre_mapper):
        result = genre_mapper.determine_genre(artist_name="bausa")
        assert result.source == "artist_exact"


class TestRegexRulesSchemaMismatch:
    """GENRE-002: charakterisiert, dass die Regex-Regel-Pipeline mit der
    echten YAML-Datei aktuell tot ist."""

    def test_rules_list_is_empty_with_real_mapping_dir(self, genre_mapper):
        assert genre_mapper.rules == []

    def test_apply_rules_always_returns_none(self, genre_mapper):
        # Selbst ein Genre-String, der inhaltlich zu vorhandenen Kategorien
        # passen wuerde, kann die (leere) Regelliste nicht treffen.
        assert genre_mapper._apply_rules("deutschrap") is None
        assert genre_mapper._apply_rules("schlager") is None

    def test_determine_genre_never_returns_source_rule(self, genre_mapper):
        # Ohne Artist-/Channel-Match und mit einem raw_genre, der KEIN
        # Override/Alias-Treffer ist, waere "source=rule" der naechste
        # Fallback-Schritt vor der Normalisierung - der wird aber nie
        # erreicht, weil self.rules leer ist.
        result = genre_mapper.determine_genre(raw_genre="some totally novel genre term")
        assert result.source != "rule"
        assert result.source == "normalized"


class TestHierarchyCaseMismatch:
    """GENRE-003: charakterisiert, dass der Hierarchie-Fallback
    (source="hierarchy") mit den echten YAML-Daten faktisch nie greift."""

    def test_ruhrpott_rap_resolves_via_override_not_hierarchy(self, genre_mapper):
        # "ruhrpott rap" steht in mapping/genre_overrides.yaml direkt auf
        # "Deutschrap" - das greift VOR jedem Hierarchie-Lookup. Die
        # tatsaechliche Hierarchie-Beziehung (Ruhrpott Rap -> Deutschrap in
        # genre_hierarchy.yaml) wird fuer dieses Beispiel also gar nicht
        # gebraucht, illustriert aber, dass der Pfad "normalized" das
        # tatsaechliche Ergebnis liefert, nicht "hierarchy".
        result = genre_mapper.determine_genre(raw_genre="Ruhrpott Rap")
        assert result.primary == "Deutschrap"
        assert result.source == "normalized"

    def test_get_main_genre_misses_due_to_case_mismatch(self, genre_mapper):
        # self.hierarchy-Keys sind Title-Case (z.B. "Deutschrap"), aber
        # get_main_genre() sucht mit .lower(). Ein direkter Aufruf mit dem
        # Hierarchie-Key in Original-Schreibweise zeigt den Miss:
        assert "Deutschrap" in genre_mapper.hierarchy
        assert genre_mapper.get_main_genre("Deutschrap") == "Deutschrap"  # Miss: gibt Input unveraendert zurueck, weil "deutschrap" (lowercased) kein Hierarchie-Key ist
