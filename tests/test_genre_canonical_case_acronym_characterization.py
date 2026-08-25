# tests/test_genre_canonical_case_acronym_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-016 Phase 1 - Genre Canonical-Case / Acronym Characterization.

ARCH-015 Phase 2 (docs/MusicBot_ARCH-015_Genre_Canonical_Idempotency_Characterization.md)
behob Klasse A1 (New York Drill, Aggro Deutschrap) durch Self-Alias-Keys,
liess aber Klasse B ("NDW" -> "Ndw") bewusst unbehandelt - strukturell
unabhaengiger Mechanismus (Title-Case-Fallback-Kapitalisierung statt
Wortgrenzen-Substring-Matching).

ARCH-016 Phase 1 untersucht systematisch, ob "NDW" ein isolierter
Datenfehler ist oder Ausdruck einer allgemeineren Klasse von Problemen
bei kanonischen Genre-Werten mit besonderer Gross-/Kleinschreibung bzw.
Akronymen. Ergebnis (docs/MusicBot_ARCH-016_Genre_Canonical_Case_Acronym_Characterization.md):

  - Unter allen 115 aktuell erreichbaren kanonischen Werten haben 10 eine
    "besondere" Case-Struktur (Akronym/Bindestrich-Grossbuchstabe/&):
    C-Pop, G-Funk, G-House, J-Pop, K-Pop, Lo-Fi, NDW, R&B, UK Drill,
    UK Rap.
  - 9 davon sind stabil, weil sie einen eigenen Self-Alias-Key besitzen
    (Direkt-Match-Kurzschluss, ARCH-013/014/015-Muster).
  - Nur "NDW" besitzt KEINEN Self-Alias-Key UND keine
    Wortgrenzen-Substring-Kandidaten - faellt komplett bis zum
    Title-Case-Fallback (str.capitalize()) durch, der Akronyme nicht
    erkennt.
  - Zusaetzlich existieren 3 kanonische Werte ohne Self-Alias-Key, die
    TROTZDEM stabil sind (Klasse C): "Afro", "Drum & Bass", "Liquid Drum
    & Bass" - weil ihr Fallback-Ergebnis (normale Woerter,
    str.capitalize() funktioniert hier korrekt) zufaellig mit dem
    Original uebereinstimmt.

  => "NDW" ist der EINZIGE instabile kanonische Wert unter allen 115 -
     kein isolierter Zufall im Sinne von "einziges geprueftes Beispiel",
     sondern durch vollstaendige Pruefung aller kanonischen Werte
     bestaetigt als tatsaechlich einziger Fall dieser Klasse (Klasse B).

Diese Datei dokumentiert AUSSCHLIESSLICH das aktuelle (fuer "NDW"
fehlerhafte) Verhalten als Beweismittel fuer eine spaetere
Entscheidungsphase (moegliches ARCH-016 Phase 2). Es werden KEINE
Aenderungen an GenreProcessor, GenreMapper oder den YAML-Mapping-Dateien
vorgenommen. Kein gewuenschtes Zukunftsverhalten wird hier
festgeschrieben.
"""

import pytest

from config import Config
from services.metadata.genre_processor import GenreProcessor
from utils.genre_map import GenreMapper


@pytest.fixture
def genre_mapper(config):
    return GenreMapper(str(config.GENRE_MAPPING_DIR))


@pytest.fixture
def genre_processor(config, genre_mapper):
    return GenreProcessor(config, genre_mapper)


def _all_canonical_values(genre_processor):
    return sorted(set(genre_processor.GENRE_NORMALIZATION.values()))


SPECIAL_CASE_STABLE_VALUES = [
    "C-Pop",
    "G-Funk",
    "G-House",
    "J-Pop",
    "K-Pop",
    "Lo-Fi",
    "R&B",
    "UK Drill",
    "UK Rap",
]

CLASS_C_STABLE_WITHOUT_SELF_KEY = [
    "Afro",
    "Drum & Bass",
    "Liquid Drum & Bass",
]


class TestNdwCurrentlyUnstable:
    """
    Klasse B: "NDW" besitzt weder einen Self-Alias-Key noch
    Wortgrenzen-Substring-Kandidaten - faellt komplett bis zum
    Title-Case-Fallback (genre_processor.py, Zeile ~393-400) durch,
    dessen str.capitalize() Akronyme nicht erkennt.
    """

    def test_ndw_has_no_self_key(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert "ndw" not in norm_map

    def test_ndw_has_no_substring_candidates(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        candidates = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word("ndw", k)
        ]
        assert candidates == []

    def test_ndw_direct_normalization_becomes_ndw_titlecase(self, genre_processor):
        assert genre_processor.normalize_genre_name("NDW") == "Ndw"

    def test_ndw_via_alias_key_second_pass_diverges(self, genre_processor):
        """
        Vollstaendiger Kontrollfluss: "neue deutsche welle" -> "NDW"
        (erster Lauf, korrekt) -> "Ndw" (zweiter Lauf, instabil).
        """
        first = genre_processor.normalize_genre_name("neue deutsche welle")
        assert first == "NDW"

        second = genre_processor.normalize_genre_name(first)
        assert second == "Ndw"
        assert second != first, (
            "Erwartete bekannte Instabilitaet: 'NDW' sollte sich bei "
            "erneuter Normalisierung aendern (aktueller Befund, kein "
            "Soll-Verhalten)."
        )

    def test_ndw_is_class_b_semantically_same_genre_wrong_case(
        self, genre_processor
    ):
        """
        Abgrenzung zu Klasse A (ARCH-015): der zweite Lauf liefert kein
        anderes Genre, sondern dasselbe Genre in falscher
        Gross-/Kleinschreibung - lowercased sind "NDW" und "Ndw"
        identisch.
        """
        result = genre_processor.normalize_genre_name("NDW")
        assert result.lower() == "ndw"
        assert result != "NDW"


class TestGenreMapperSeparatelyVerifiedForNdw:
    """
    GenreMapper.normalize_genre_name() ist eine strukturell unabhaengige
    zweite Implementierung mit eigenem Fallback (inkl. einer expliziten
    Akronym-Erhaltungsliste EDM/R&B/UK/US/DJ/MC). "NDW" ist nicht in
    dieser Liste enthalten und faellt daher trotz vorhandener
    Akronym-Infrastruktur ebenfalls auf str.capitalize() zurueck -
    unabhaengig vom GenreProcessor-Codepfad separat verifiziert, nicht
    als identisch angenommen.
    """

    def test_genre_mapper_also_produces_ndw_titlecase(self, genre_mapper):
        result = genre_mapper.normalize_genre_name("NDW")
        assert result == "Ndw"
        assert result != "NDW"

    def test_genre_mapper_acronym_list_does_not_include_ndw(self, genre_mapper):
        assert "NDW".upper() not in ("EDM", "R&B", "UK", "US", "DJ", "MC")

    def test_genre_mapper_has_no_exact_key_for_ndw(self, genre_mapper):
        assert "ndw" not in genre_mapper.overrides
        assert "ndw" not in genre_mapper.genre_aliases


class TestSpecialCaseValuesStableViaSelfKey:
    """
    9 der 10 kanonischen Werte mit besonderer Case-Struktur (Akronym,
    Bindestrich-Grossbuchstabe, "&") sind stabil, weil sie - anders als
    "NDW" - jeweils einen eigenen Self-Alias-Key besitzen und damit den
    Direkt-Match-Kurzschluss (genre_processor.py, Zeile 356-357)
    erreichen, bevor Substring-Matching oder Fallback ueberhaupt
    relevant werden.
    """

    @pytest.mark.parametrize("canonical_value", SPECIAL_CASE_STABLE_VALUES)
    def test_special_case_value_has_self_key_and_is_stable(
        self, genre_processor, canonical_value
    ):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert canonical_value.lower() in norm_map, (
            f"{canonical_value!r} sollte einen Self-Alias-Key besitzen"
        )

        once = genre_processor.normalize_genre_name(canonical_value)
        twice = genre_processor.normalize_genre_name(once)
        assert once == canonical_value
        assert twice == canonical_value


class TestClassCStableWithoutSelfKey:
    """
    Klasse C: kanonische Werte ohne Self-Alias-Key, die trotzdem stabil
    sind, weil weder Substring-Kandidaten existieren noch der
    Title-Case-Fallback die Schreibweise veraendert (normale Woerter,
    kein Akronym - str.capitalize() funktioniert hier korrekt). Erweitert
    die in ARCH-015 Phase 1 auf Mehrwort-Werte beschraenkte Pruefung
    ("Drum & Bass", "Liquid Drum & Bass") um den Einwort-Fall ("Afro"),
    der dort nicht erfasst wurde.
    """

    @pytest.mark.parametrize("canonical_value", CLASS_C_STABLE_WITHOUT_SELF_KEY)
    def test_stable_without_self_key_via_fallback(
        self, genre_processor, canonical_value
    ):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert canonical_value.lower() not in norm_map

        candidates = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word(
                canonical_value.lower(), k
            )
        ]
        assert candidates == []

        result = genre_processor.normalize_genre_name(canonical_value)
        assert result == canonical_value


class TestFullCanonicalValueCaseInventory:
    """
    Vollstaendiger Bestandsbeweis: unter allen aktuell erreichbaren
    kanonischen Werten mit besonderer Case-Struktur (Akronym,
    Bindestrich-Grossbuchstabe, "&") ist "NDW" der einzige instabile.
    Regressionswaechter - aendert sich diese Menge oder Zahl durch eine
    YAML-Aenderung, muss ARCH-016 neu bewertet werden.
    """

    def test_exactly_one_unstable_canonical_value_overall(self, genre_processor):
        canonical_values = _all_canonical_values(genre_processor)
        unstable = {
            v: genre_processor.normalize_genre_name(v)
            for v in canonical_values
            if genre_processor.normalize_genre_name(v) != v
        }
        assert unstable == {"NDW": "Ndw"}

    def test_exactly_four_canonical_values_without_self_alias_key(
        self, genre_processor
    ):
        norm_map = genre_processor.GENRE_NORMALIZATION
        without_self_key = sorted(
            v
            for v in _all_canonical_values(genre_processor)
            if v.lower() not in norm_map
        )
        assert without_self_key == [
            "Afro",
            "Drum & Bass",
            "Liquid Drum & Bass",
            "NDW",
        ]
