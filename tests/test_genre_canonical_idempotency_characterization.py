# tests/test_genre_canonical_idempotency_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-015 - Genre Canonical-Value / Idempotency Characterization.

Phase 1 (docs/MusicBot_ARCH-015_Genre_Canonical_Idempotency_Characterization.md)
charakterisierte, dass GenreProcessor.normalize_genre_name() fuer 3 der 115
damals erreichbaren kanonischen Genre-Werte NICHT idempotent war, d.h.
normalize(normalize(x)) != normalize(x):

  Klasse A1 (generischer Teilwort-Alias ueberstimmte bei erneuter
  Normalisierung einen kanonischen Mehrwort-Wert, der selbst keinen
  Self-Alias-Key besass):
    "New York Drill"   -> "Hip Hop"        (ueber generischen Alias "drill")
    "Aggro Deutschrap"  -> "Deutschrap"     (ueber generischen Alias "deutschrap")

  Klasse B (Title-Case-Fallback-Kapitalisierung ohne Self-Alias-Key,
  strukturell unabhaengig von Klasse A - kein Substring-Match beteiligt):
    "NDW" -> "Ndw"

Phase 2 (docs/MusicBot_ARCH-015_Genre_Canonical_Idempotency_Characterization.md,
Abschnitt "Phase 2 - Self-Alias-Implementierung") hat gemaess der in Phase 1
empfohlenen Variante A die beiden fehlenden Self-Alias-Keys
"new york drill": "New York Drill" und "aggro deutschrap": "Aggro
Deutschrap" in mapping/genre_aliases.yaml ergaenzt. Klasse A1 ist damit
behoben. Klasse B ("NDW") wurde bewusst NICHT bearbeitet (explizite
Scope-Grenze von Phase 2) und bleibt weiterhin instabil.

Diese Datei dokumentiert seit Phase 2 das KORRIGIERTE Soll-Verhalten fuer
Klasse A1 - nicht mehr den Bug. Assertions wurden invertiert (stabil statt
instabil erwartet), nicht geloescht (etabliertes Muster aus
ARCH-012/013/014). Klasse B bleibt unveraendert als aktuelles (weiterhin
fehlerhaftes) Verhalten dokumentiert.

Zusaetzlich wird GenreMapper.normalize_genre_name() (utils/genre_map.py) -
eine strukturell unabhaengige zweite Normalisierungs-Implementierung ohne
Wortgrenzen-Substring-Matching - direkt gegengeprueft: sie war fuer
Klasse A1 nie betroffen (kein Substring-Matching vorhanden), teilt aber
weiterhin denselben Klasse-B-Mechanismus (str.capitalize()) fuer "NDW".
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


class TestClassA1StableAfterSelfAliasFix:
    """
    Seit ARCH-015 Phase 2 besitzen "New York Drill" und "Aggro
    Deutschrap" eigene Self-Alias-Keys in genre_aliases.yaml
    ("new york drill", "aggro deutschrap"). Der Direkt-Match-Zweig in
    normalize_genre_name() (Zeile 356-357) greift dadurch VOR dem
    Wortgrenzen-Substring-Matching - der zuvor auslösende generische
    Alias ("drill", "deutschrap") wird nicht mehr erreicht.
    """

    @pytest.mark.parametrize(
        "alias_key,expected_canonical",
        [
            ("ny drill", "New York Drill"),
            ("aggro rap", "Aggro Deutschrap"),
        ],
    )
    def test_second_normalization_now_stable(
        self, genre_processor, alias_key, expected_canonical
    ):
        first = genre_processor.normalize_genre_name(alias_key)
        assert first == expected_canonical

        second = genre_processor.normalize_genre_name(first)
        assert second == first, (
            f"Erwartete Stabilitaet fuer {alias_key!r} seit ARCH-015 "
            f"Phase 2: {first!r} sollte sich bei erneuter Normalisierung "
            f"NICHT mehr aendern."
        )

    def test_new_york_drill_direct_reentry(self, genre_processor):
        """Direkter zweiter Durchlauf ausgehend vom kanonischen Wert selbst."""
        assert (
            genre_processor.normalize_genre_name("New York Drill")
            == "New York Drill"
        )

    def test_aggro_deutschrap_direct_reentry(self, genre_processor):
        """Direkter zweiter Durchlauf ausgehend vom kanonischen Wert selbst."""
        assert (
            genre_processor.normalize_genre_name("Aggro Deutschrap")
            == "Aggro Deutschrap"
        )

    def test_neue_self_alias_keys_existieren(self, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        assert norm_map.get("new york drill") == "New York Drill"
        assert norm_map.get("aggro deutschrap") == "Aggro Deutschrap"

    def test_direkter_match_greift_vor_substring_matching(self, genre_processor):
        """
        Verifiziert den Fix-Mechanismus: der Direkt-Match liefert das
        korrekte Ergebnis, OBWOHL der generische Alias ("drill",
        "deutschrap") weiterhin als Wortgrenzen-Kandidat vorhanden waere
        - er wird schlicht nicht mehr erreicht, weil der Direkt-Match-
        Zweig frueher im Code liegt und zuerst greift.
        """
        norm_map = genre_processor.GENRE_NORMALIZATION

        candidates_ny = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word("new york drill", k)
        ]
        assert "drill" in candidates_ny
        assert "new york drill" in candidates_ny
        assert genre_processor.normalize_genre_name("new york drill") == (
            "New York Drill"
        )

        candidates_aggro = [
            k
            for k in norm_map
            if genre_processor._contains_alias_as_whole_word(
                "aggro deutschrap", k
            )
        ]
        assert "deutschrap" in candidates_aggro
        assert "aggro deutschrap" in candidates_aggro
        assert genre_processor.normalize_genre_name("aggro deutschrap") == (
            "Aggro Deutschrap"
        )


class TestClassA1CounterExamplesStableWithoutSelfKey:
    """
    Gegenbeispiele zur reinen Self-Alias-Hypothese: "Drum & Bass" und
    "Liquid Drum & Bass" besitzen weiterhin KEINEN Self-Alias-Key (nicht
    Teil von ARCH-015 Phase 2), sind aber trotzdem stabil, weil keiner
    ihrer Wortbestandteile ("drum", "bass", "liquid") selbst als
    generischer Alias-Key registriert ist - der Title-Case-Fallback
    reproduziert den Wert unveraendert.
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


class TestClassBFallbackCapitalizationStillOpen:
    """
    "NDW" ist strukturell unabhaengig von Klasse A und war NICHT
    Bestandteil von ARCH-015 Phase 2 (explizite Scope-Grenze). Es
    existiert weiterhin kein Self-Alias-Key UND keine
    Wortgrenzen-Kandidaten - der Wert faellt weiterhin komplett durch
    bis zur Title-Case-Fallback-Kapitalisierung (str.capitalize()), die
    aus "NDW" faelschlich "Ndw" macht.
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

    def test_ndw_second_pass_still_becomes_ndw_titlecase(self, genre_processor):
        first = genre_processor.normalize_genre_name("neue deutsche welle")
        assert first == "NDW"

        second = genre_processor.normalize_genre_name(first)
        assert second == "Ndw"
        assert second != first

    def test_ndw_is_still_the_only_affected_value_in_genre_processor(
        self, genre_processor
    ):
        """
        Vollstaendigkeits-Beleg: unter allen aktuell erreichbaren
        kanonischen Werten ist "NDW" weiterhin der einzige, der
        ausschliesslich ueber den Fallback-Pfad (keine Substring-
        Kandidaten) instabil wird. Regressionswaechter fuer zukuenftige
        YAML-Aenderungen.
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
    Sie war fuer Klasse A1 nie betroffen - reale Multi-Pass-Risiko-
    Reduktion, da die "lokale Genre"-Pipeline (determine_genre) ueber
    GenreMapper laeuft, nicht ueber GenreProcessor.normalize_genre_name().
    Bleibt nach dem ARCH-015-Phase-2-Fix unveraendert stabil.
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
        betroffen, nicht nur in GenreProcessor. Unveraendert seit
        ARCH-015 Phase 2 (Klasse B ausdruecklich nicht bearbeitet).
        """
        result = genre_mapper.normalize_genre_name("NDW")
        assert result == "Ndw"
        assert result != "NDW"


class TestFullCanonicalValueIdempotencyInventory:
    """
    Vollstaendiger Bestandsbeweis ueber alle aktuell in
    GenreProcessor.GENRE_NORMALIZATION erreichbaren eindeutigen
    kanonischen Werte: seit ARCH-015 Phase 2 ist nur noch "NDW"
    (Klasse B) instabil. Regressionswaechter - aendert sich diese Zahl
    durch eine YAML-Aenderung, muss ARCH-015 neu bewertet werden.
    """

    def test_exactly_one_unstable_canonical_value(self, genre_processor):
        canonical_values = _all_canonical_values(genre_processor)
        unstable = {
            v: genre_processor.normalize_genre_name(v)
            for v in canonical_values
            if genre_processor.normalize_genre_name(v) != v
        }
        assert unstable == {
            "NDW": "Ndw",
        }
