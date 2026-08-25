# tests/test_genre_canonical_idempotency_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-015 Phase 1 - Genre Canonical-Value / Idempotency Characterization.

POST-ARCH-014 (docs/POST-ARCH-014_Services_Genre_Architecture_Audit.md)
identifizierte, dass GenreProcessor.normalize_genre_name() fuer 3 der 115
aktuell erreichbaren kanonischen Genre-Werte NICHT idempotent ist, d.h.
normalize(normalize(x)) != normalize(x):

  Klasse A1 (generischer Teilwort-Alias ueberstimmt bei erneuter
  Normalisierung einen kanonischen Mehrwort-Wert, der selbst keinen
  Self-Alias-Key besitzt):
    "New York Drill"   -> "Hip Hop"        (ueber generischen Alias "drill")
    "Aggro Deutschrap"  -> "Deutschrap"     (ueber generischen Alias "deutschrap")

  Klasse B (Title-Case-Fallback-Kapitalisierung ohne Self-Alias-Key,
  strukturell unabhaengig von Klasse A - kein Substring-Match beteiligt):
    "NDW" -> "Ndw"

Diese Datei dokumentiert AUSSCHLIESSLICH das aktuelle (fehlerhafte)
Verhalten als Beweismittel fuer eine spaetere Entscheidungsphase
(moegliches ARCH-015 Phase 2). Es werden KEINE Aenderungen an
GenreProcessor, GenreMapper oder den YAML-Mapping-Dateien vorgenommen.
Kein gewuenschtes Zukunftsverhalten wird hier festgeschrieben.

Zusaetzlich wird GenreMapper.normalize_genre_name() (utils/genre_map.py) -
eine strukturell unabhaengige zweite Normalisierungs-Implementierung ohne
Wortgrenzen-Substring-Matching - direkt gegengeprueft: sie ist fuer
Klasse A1 NICHT betroffen (kein Substring-Matching vorhanden), teilt aber
denselben Klasse-B-Mechanismus (str.capitalize()) fuer "NDW".
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


class TestClassA1GenericSubstringInstability:
    """
    "New York Drill" und "Aggro Deutschrap" besitzen keinen eigenen
    Self-Alias-Key in genre_aliases.yaml. Bei erneuter Normalisierung
    greift daher das Wortgrenzen-Substring-Matching (ARCH-013/014) auf
    einen kuerzeren, generischen Alias, der zufaellig als eigenstaendiges
    Wort im ausgeschriebenen kanonischen Text enthalten ist.
    """

    @pytest.mark.parametrize(
        "alias_key,expected_canonical,second_pass_result",
        [
            ("ny drill", "New York Drill", "Hip Hop"),
            ("aggro rap", "Aggro Deutschrap", "Deutschrap"),
        ],
    )
    def test_second_normalization_diverges_from_first(
        self, genre_processor, alias_key, expected_canonical, second_pass_result
    ):
        first = genre_processor.normalize_genre_name(alias_key)
        assert first == expected_canonical

        second = genre_processor.normalize_genre_name(first)
        assert second == second_pass_result
        assert second != first, (
            f"Erwartete bekannte Instabilitaet fuer {alias_key!r}: "
            f"{first!r} sollte sich bei erneuter Normalisierung aendern "
            f"(aktueller Befund, kein Soll-Verhalten)."
        )

    def test_new_york_drill_direct_reentry(self, genre_processor):
        """Direkter zweiter Durchlauf ausgehend vom kanonischen Wert selbst."""
        assert genre_processor.normalize_genre_name("New York Drill") == "Hip Hop"

    def test_aggro_deutschrap_direct_reentry(self, genre_processor):
        """Direkter zweiter Durchlauf ausgehend vom kanonischen Wert selbst."""
        assert genre_processor.normalize_genre_name("Aggro Deutschrap") == "Deutschrap"

    def test_auslösender_generischer_alias_ist_wortgrenzen_treffer(
        self, genre_processor
    ):
        """
        Verifiziert den exakten Mechanismus: der jeweils generische Alias
        ("drill", "deutschrap") ist der EINZIGE Wortgrenzen-Kandidat im
        ausgeschriebenen kanonischen Text - kein Spezifitaets-Tie, kein
        Fehlverhalten der ARCH-014-Regel selbst.
        """
        norm_map = genre_processor.GENRE_NORMALIZATION

        candidates_ny = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word("new york drill", k)
        ]
        assert candidates_ny == ["drill"]

        candidates_aggro = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word(
                "aggro deutschrap", k
            )
        ]
        assert candidates_aggro == ["deutschrap"]

    def test_kanonische_werte_haben_keinen_self_alias_key(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert "new york drill" not in norm_map
        assert "aggro deutschrap" not in norm_map


class TestClassA1CounterExamplesStableWithoutSelfKey:
    """
    Gegenbeispiele zur reinen Self-Alias-Hypothese: "Drum & Bass" und
    "Liquid Drum & Bass" besitzen ebenfalls KEINEN Self-Alias-Key, sind
    aber trotzdem stabil, weil keiner ihrer Wortbestandteile ("drum",
    "bass", "liquid") selbst als generischer Alias-Key registriert ist -
    der Title-Case-Fallback reproduziert den Wert unveraendert.
    """

    @pytest.mark.parametrize(
        "canonical_value",
        ["Drum & Bass", "Liquid Drum & Bass"],
    )
    def test_stable_despite_missing_self_key(self, genre_processor, canonical_value):
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


class TestClassBFallbackCapitalization:
    """
    "NDW" ist strukturell unabhaengig von Klasse A: es existiert kein
    Self-Alias-Key UND keine Wortgrenzen-Kandidaten - der Wert faellt
    komplett durch bis zur Title-Case-Fallback-Kapitalisierung
    (str.capitalize()), die aus "NDW" faelschlich "Ndw" macht.
    """

    def test_ndw_has_no_self_key_and_no_substring_candidates(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert "ndw" not in norm_map
        candidates = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word("ndw", k)
        ]
        assert candidates == []

    def test_ndw_second_pass_becomes_ndw_titlecase(self, genre_processor):
        first = genre_processor.normalize_genre_name("neue deutsche welle")
        assert first == "NDW"

        second = genre_processor.normalize_genre_name(first)
        assert second == "Ndw"
        assert second != first

    def test_ndw_is_the_only_affected_value_in_genre_processor(self, genre_processor):
        """
        Vollstaendigkeits-Beleg: unter allen 115 aktuell erreichbaren
        kanonischen Werten ist "NDW" der einzige, der ausschliesslich
        ueber den Fallback-Pfad (keine Substring-Kandidaten) instabil
        wird. Regressionswaechter fuer zukuenftige YAML-Aenderungen.
        """
        norm_map = genre_processor.GENRE_NORMALIZATION
        fallback_only_unstable = []
        for v in _all_canonical_values(genre_processor):
            if v.lower() in norm_map:
                continue
            candidates = [
                k
                for k in norm_map
                if genre_processor._contains_alias_as_whole_word(v.lower(), k)
            ]
            if candidates:
                continue
            if genre_processor.normalize_genre_name(v) != v:
                fallback_only_unstable.append(v)
        assert fallback_only_unstable == ["NDW"]


class TestGenreMapperNotAffectedByClassA1(object):
    """
    utils/genre_map.py::GenreMapper besitzt eine strukturell unabhaengige
    zweite normalize_genre_name()-Implementierung OHNE
    Wortgrenzen-Substring-Matching (nur exakter Dict-Lookup + Fallback).
    Sie ist daher fuer Klasse A1 NICHT betroffen - reale Multi-Pass-Risiko-
    Reduktion, da die "lokale Genre"-Pipeline (determine_genre) ueber
    GenreMapper laeuft, nicht ueber GenreProcessor.normalize_genre_name().
    """

    @pytest.mark.parametrize(
        "canonical_value",
        ["New York Drill", "Aggro Deutschrap"],
    )
    def test_genre_mapper_stable_for_class_a1_values(
        self, genre_mapper, canonical_value
    ):
        once = genre_mapper.normalize_genre_name(canonical_value)
        twice = genre_mapper.normalize_genre_name(once)
        assert once == canonical_value
        assert twice == canonical_value

    def test_genre_mapper_shares_class_b_mechanism_for_ndw(self, genre_mapper):
        """
        GenreMapper reimplementiert denselben str.capitalize()-Fallback
        unabhaengig - "NDW" ist daher in BEIDEN Implementierungen
        betroffen, nicht nur in GenreProcessor.
        """
        result = genre_mapper.normalize_genre_name("NDW")
        assert result == "Ndw"
        assert result != "NDW"


class TestFullCanonicalValueIdempotencyInventory:
    """
    Vollstaendiger Bestandsbeweis ueber alle 115 aktuell in
    GenreProcessor.GENRE_NORMALIZATION erreichbaren eindeutigen
    kanonischen Werte: genau 3 sind instabil (2x Klasse A1, 1x Klasse B).
    Regressionswaechter - aendert sich diese Zahl durch eine YAML-
    Aenderung, muss ARCH-015 neu bewertet werden.
    """

    def test_exactly_three_unstable_canonical_values(self, genre_processor):
        canonical_values = _all_canonical_values(genre_processor)
        unstable = {
            v: genre_processor.normalize_genre_name(v)
            for v in canonical_values
            if genre_processor.normalize_genre_name(v) != v
        }
        assert unstable == {
            "New York Drill": "Hip Hop",
            "Aggro Deutschrap": "Deutschrap",
            "NDW": "Ndw",
        }
