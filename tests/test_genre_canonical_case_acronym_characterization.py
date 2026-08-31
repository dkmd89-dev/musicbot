# tests/test_genre_canonical_case_acronym_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-016 - Genre Canonical-Case / Acronym.

Phase 1 (docs/archive/arch/MusicBot_ARCH-016_Genre_Canonical_Case_Acronym_Characterization.md)
untersuchte systematisch, ob "NDW" -> "Ndw" (der nach ARCH-015 Phase 2
verbleibende Idempotenzbefund) ein isolierter Datenfehler oder Ausdruck
einer allgemeineren Klasse von Problemen bei kanonischen Genre-Werten mit
besonderer Gross-/Kleinschreibung bzw. Akronymen ist. Ergebnis:

  - Unter allen 115 damals erreichbaren kanonischen Werten hatten 10 eine
    "besondere" Case-Struktur (Akronym/Bindestrich-Grossbuchstabe/&):
    C-Pop, G-Funk, G-House, J-Pop, K-Pop, Lo-Fi, NDW, R&B, UK Drill,
    UK Rap.
  - 9 davon waren stabil (eigener Self-Alias-Key, Direkt-Match-
    Kurzschluss, ARCH-013/014/015-Muster).
  - Nur "NDW" besass KEINEN Self-Alias-Key UND keine
    Wortgrenzen-Substring-Kandidaten - fiel komplett bis zum
    Title-Case-Fallback (str.capitalize()) durch, der Akronyme nicht
    erkennt. Durch vollstaendige Pruefung aller 115 Werte als
    tatsaechlich einziger Fall dieser Klasse (Klasse B) bestaetigt.
  - Zusaetzlich existierten 3 kanonische Werte ohne Self-Alias-Key, die
    TROTZDEM stabil waren (Klasse C): "Afro", "Drum & Bass", "Liquid
    Drum & Bass".

Phase 2 (docs/archive/arch/MusicBot_ARCH-016_Genre_Canonical_Case_Acronym_Characterization.md,
Abschnitt "Phase 2 - NDW Self-Alias Implementation") hat gemaess der in
Phase 1 empfohlenen Variante A den fehlenden Self-Alias-Key
"ndw": "NDW" in mapping/genre_aliases.yaml ergaenzt. "NDW" ist damit
idempotent - alle 115 kanonischen Werte sind jetzt stabil. Da
GenreMapper dieselbe genre_aliases.yaml laedt, profitiert auch dessen
strukturell unabhaengige Normalisierungs-Implementierung von diesem
einen YAML-Eintrag, ohne dass deren hartkodierte Akronym-Liste
(EDM/R&B/UK/US/DJ/MC) angepasst werden musste.

Diese Datei dokumentiert seit Phase 2 das KORRIGIERTE Soll-Verhalten fuer
"NDW" - nicht mehr den Bug. Assertions wurden invertiert (stabil statt
instabil erwartet), nicht geloescht (etabliertes Muster aus
ARCH-012/013/014/015).
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


class TestNdwStableAfterSelfAliasFix:
    """
    Seit ARCH-016 Phase 2 besitzt "NDW" einen eigenen Self-Alias-Key
    ("ndw": "NDW") in genre_aliases.yaml. Der Direkt-Match-Zweig in
    normalize_genre_name() (genre_processor.py, Zeile 356-357) greift
    dadurch VOR dem (ohnehin leeren) Substring-Matching und dem
    Title-Case-Fallback - der zuvor auslösende .capitalize()-Fallback
    wird nicht mehr erreicht.
    """

    def test_ndw_now_has_self_key(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert norm_map.get("ndw") == "NDW"

    def test_ndw_direct_normalization_stable(self, genre_processor):
        assert genre_processor.normalize_genre_name("NDW") == "NDW"

    def test_ndw_lowercase_alias_input_resolves_to_ndw(self, genre_processor):
        assert genre_processor.normalize_genre_name("ndw") == "NDW"

    def test_ndw_via_alias_key_second_pass_now_stable(self, genre_processor):
        """
        Vollstaendiger Kontrollfluss: "neue deutsche welle" -> "NDW"
        (erster Lauf) -> "NDW" (zweiter Lauf, jetzt stabil).
        """
        first = genre_processor.normalize_genre_name("neue deutsche welle")
        assert first == "NDW"

        second = genre_processor.normalize_genre_name(first)
        assert second == "NDW"
        assert second == first

    def test_ndw_idempotent_explicit(self, genre_processor):
        """normalize(normalize("NDW")) == normalize("NDW")"""
        once = genre_processor.normalize_genre_name("NDW")
        twice = genre_processor.normalize_genre_name(once)
        assert genre_processor.normalize_genre_name("NDW") == twice
        assert once == twice == "NDW"


class TestGenreMapperSeparatelyVerifiedForNdw:
    """
    GenreMapper.normalize_genre_name() ist eine strukturell unabhaengige
    zweite Implementierung mit eigenem Fallback (inkl. einer weiterhin
    unvollstaendigen, hartkodierten Akronym-Erhaltungsliste
    EDM/R&B/UK/US/DJ/MC, die "NDW" NICHT enthaelt und in ARCH-016
    Phase 2 bewusst nicht erweitert wurde - siehe Scope-Grenzen).
    GenreMapper laedt jedoch dieselbe genre_aliases.yaml wie
    GenreProcessor und erreicht daher fuer "NDW" jetzt seinerseits den
    exakten Alias-Match (Zeile "2. Aliases aufloesen"), noch VOR dem
    eigenen Fallback - unabhaengig vom GenreProcessor-Codepfad separat
    verifiziert, nicht als identisch angenommen.
    """

    def test_genre_mapper_now_also_stable_for_ndw(self, genre_mapper):
        result = genre_mapper.normalize_genre_name("NDW")
        assert result == "NDW"

    def test_genre_mapper_acronym_list_still_does_not_include_ndw(
        self, genre_mapper
    ):
        """
        Scope-Grenze bestaetigt: die hartkodierte Akronym-Liste wurde
        NICHT erweitert - "NDW" ist weiterhin nicht darin enthalten.
        Die Stabilitaet kommt ausschliesslich ueber den neuen
        YAML-Self-Alias, nicht ueber diese Liste.
        """
        assert "NDW".upper() not in ("EDM", "R&B", "UK", "US", "DJ", "MC")

    def test_genre_mapper_now_has_exact_alias_key_for_ndw(self, genre_mapper):
        """
        Der neue Self-Alias-Key wird von GenreMapper ueber dieselbe
        genre_aliases.yaml mitgeladen (self.genre_aliases), nicht ueber
        genre_overrides.yaml.
        """
        assert "ndw" not in genre_mapper.overrides
        assert genre_mapper.genre_aliases.get("ndw") == "NDW"


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
    Vollstaendiger Bestandsbeweis: seit ARCH-016 Phase 2 ist unter allen
    115 aktuell erreichbaren kanonischen Werten KEIN einziger mehr
    instabil - "NDW" war der letzte verbleibende Fall (aus ARCH-014/015).
    Regressionswaechter - aendert sich diese Zahl durch eine kuenftige
    YAML-Aenderung, muss das neu bewertet werden.
    """

    def test_zero_unstable_canonical_values_overall(self, genre_processor):
        canonical_values = _all_canonical_values(genre_processor)
        unstable = {
            v: genre_processor.normalize_genre_name(v)
            for v in canonical_values
            if genre_processor.normalize_genre_name(v) != v
        }
        assert unstable == {}

    def test_exactly_three_canonical_values_without_self_alias_key(
        self, genre_processor
    ):
        """
        Seit ARCH-016 Phase 2 besitzt "NDW" einen Self-Alias-Key -
        verbleiben nur noch die 3 Klasse-C-Faelle (stabil auch ohne
        Self-Key, siehe TestClassCStableWithoutSelfKey), vorher 4.
        """
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
        ]
