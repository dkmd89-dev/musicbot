"""
Characterization-Tests fuer GenreMapper.determine_genre() gegen die echte
mapping/-Dir - Phase 2, deckt Pfade ab, die tests/test_genre_processor.py
(Phase 1) nicht beruehrt: Fuzzy-Matching, Regex-Regeln, Hierarchie-Fallback.

Zwei bekannte Bugs wurden hier gefunden (siehe docs/MusicBot_ENGINEERING_BASELINE.md):

- GENRE-002: mapping/genre_rules.yaml hat keinen Top-Level-Key "GENRE_RULES"
  (nur keyword_rules/artist_rules/title_rules) - GenreMapper.rules ist mit
  der echten Datei daher immer leer, _apply_rules() liefert immer None.
  Bewusst NICHT gefixt (Regel 3) - die echte YAML-Struktur beschreibt eine
  ganz andere, umfangreichere Regel-Engine als der Loader implementiert;
  das ist eine Produktentscheidung, kein mechanischer Fix. TestRegexRulesSchemaMismatch
  friert das aktuelle (fehlerhafte) Verhalten ein.
- GENRE-003: GenreMapper.get_main_genre() lowercased den Suchschluessel,
  aber self.hierarchy-Keys wurden aus dem YAML unveraendert (Title-Case)
  geladen - der Hierarchie-Lookup traf praktisch nie, source="hierarchy"
  wurde faktisch nie erreicht. GEFIXT: Hierarchie-Keys werden jetzt beim
  Laden lowercased (utils/genre_map.py, _load_all_mappings), und
  get_main_genre() faengt den Sonderfall ab, dass Top-Level-Genres im
  Hierarchie-Dict als Key mit Wert None vorliegen. TestHierarchyCaseFix
  verifiziert das neue, korrigierte Verhalten.
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


class TestHierarchyCaseFix:
    """
    GENRE-003 wurde in Phase 2 (Fortsetzung) gefixt: self.hierarchy-Keys
    werden jetzt beim Laden lowercased (analog zu artist_map/channel_map),
    und get_main_genre() behandelt einen vorhandenen None-Wert (Top-Level-
    Genres wie "Deutschrap: null" in genre_hierarchy.yaml) genauso wie
    einen fehlenden Key - vorher haette .get(key, sub_genre) den None-Wert
    zurueckgegeben statt des Fallbacks, sobald die Case-Normalisierung
    Top-Level-Keys ueberhaupt erst matchbar gemacht haette.

    Diese Tests verifizieren den Fix, nicht mehr den Bug.
    """

    def test_ruhrpott_rap_still_resolves_via_override(self, genre_mapper):
        # "ruhrpott rap" steht in mapping/genre_overrides.yaml direkt auf
        # "Deutschrap" - das greift weiterhin VOR jedem Hierarchie-Lookup,
        # unabhaengig vom GENRE-003-Fix.
        result = genre_mapper.determine_genre(raw_genre="Ruhrpott Rap")
        assert result.primary == "Deutschrap"
        assert result.source == "normalized"

    def test_subgenre_without_override_now_resolves_via_hierarchy(
        self, genre_mapper
    ):
        # "Berliner Rap" hat KEINEN Eintrag in genre_overrides.yaml/
        # genre_aliases.yaml, aber IST ein Kind von "Deutschrap" in
        # genre_hierarchy.yaml - erreicht jetzt tatsaechlich source="hierarchy".
        result = genre_mapper.determine_genre(raw_genre="Berliner Rap")
        assert result.primary == "Deutschrap"
        assert result.source == "hierarchy"

    def test_get_main_genre_resolves_subgenre_case_insensitively(self, genre_mapper):
        assert genre_mapper.get_main_genre("Ruhrpott Rap") == "Deutschrap"
        assert genre_mapper.get_main_genre("ruhrpott rap") == "Deutschrap"

    def test_top_level_genre_is_returned_unchanged_not_none(self, genre_mapper):
        # Regressionstest fuer die durch den Case-Fix erst sichtbar gewordene
        # Falle: "Deutschrap" ist im Hierarchie-Dict ein Key mit Wert None
        # (kein Parent). get_main_genre() darf dafuer NICHT None
        # zurueckgeben, sondern muss auf den Input zurueckfallen.
        assert genre_mapper.hierarchy.get("deutschrap") is None
        assert "deutschrap" in genre_mapper.hierarchy  # Key existiert (Wert None)
        assert genre_mapper.get_main_genre("Deutschrap") == "Deutschrap"
