# tests/test_genre_specificity_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-014 Phase 1 - Characterization-Tests fuer das in
docs/POST-ARCH-013_Services_Architecture_Audit.md (Abschnitt G/L)
identifizierte Spezifitaets-/Longest-Match-Problem in
GenreProcessor.normalize_genre_name().

WICHTIG: Diese Tests frieren das AKTUELLE (fachlich suboptimale)
Verhalten ein - sie testen NICHT eine gewuenschte zukuenftige Loesung.
Der Wortgrenzen-Teilstring-Match (ARCH-013 Phase 5) kehrt beim ERSTEN
gueltigen Treffer in Dict-Iterationsreihenfolge zurueck, ohne Spezifitaet
zu beruecksichtigen - ein generischer Alias (z.B. "pop"), der VOR einem
spezifischeren Alias (z.B. "tech house") in mapping/genre_aliases.yaml
steht, gewinnt bei einem dekorierten String (z.B. "tech house mix"),
obwohl der spezifischere Alias ebenfalls als Wortgrenzen-Treffer vorliegt.

Diese Datei ist ausschliesslich Beweismittel fuer die ARCH-014-Analyse
(siehe docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md).
Keine Produktionscodeaenderung. Sobald eine fachliche Entscheidung fuer
eine Spezifitaetsregel getroffen und umgesetzt wird, MUESSEN diese
Assertions aktualisiert werden (Muster: analog zu allen bisherigen
ARCH-012/013-Phasen, Tests umbenennen/anpassen statt loeschen).
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


class TestGenericAliasCurrentlyOutranksSpecificAlias:
    """
    Eingefrorenes AKTUELLES Verhalten: bei einem dekorierten String, der
    sowohl einen generischen als auch einen spezifischeren Alias als
    gueltigen Wortgrenzen-Treffer enthaelt, gewinnt der generische Alias,
    weil er in mapping/genre_aliases.yaml vor dem spezifischeren steht.
    Das ist fachlich nicht das erwuenschte Ergebnis (siehe ARCH-014-Doku),
    aber das nachweisbar aktuelle.
    """

    @pytest.mark.parametrize(
        "decorated_input,current_result,fachlich_erwarteter_wert",
        [
            ("tech house mix", "House", "Tech House"),
            ("k-pop revival", "Pop", "K-Pop"),
            ("christian rock ballad", "Rock", "Gospel"),
            ("indie rock legend", "Rock", "Indie"),
            ("bedroom pop vibes", "Pop", "Indie"),
            ("country pop hit", "Pop", "Country Pop"),
            ("progressive house anthem", "House", "Progressive House"),
            ("west coast hip hop classic", "Hip Hop", "West Coast Hip Hop"),
            ("symphonic metal choir", "Klassik", "Metal"),
        ],
    )
    def test_current_behavior_prefers_generic_over_specific_alias(
        self, genre_processor, decorated_input, current_result, fachlich_erwarteter_wert
    ):
        assert genre_processor.normalize_genre_name(decorated_input) == current_result
        # Gegenprobe: der spezifischere Wert ist NICHT das aktuelle
        # Ergebnis - dokumentiert den Abstand zum fachlich erwarteten Wert.
        assert current_result != fachlich_erwarteter_wert

    def test_undecorated_specific_alias_still_resolves_correctly(
        self, genre_processor
    ):
        # Ohne Dekoration (exakter Match) ist das Ergebnis unveraendert
        # korrekt - das Problem betrifft ausschliesslich den
        # Teilstring-Match-Pfad fuer NICHT-exakte Eingaben.
        for key, expected in [
            ("tech house", "Tech House"),
            ("k-pop", "K-Pop"),
            ("indie rock", "Indie"),
        ]:
            assert genre_processor.normalize_genre_name(key) == expected


class TestCurrentBehaviorIsIdempotentDespiteBeingSuboptimal:
    """
    Das aktuelle (generische) Ergebnis ist stabil reproduzierbar - kein
    Idempotenz-Verstoss, nur ein Korrektheitsproblem (siehe ARCH-014-Doku
    Abschnitt 8, Invariante "Normalisierung muss idempotent bleiben").
    """

    @pytest.mark.parametrize(
        "decorated_input",
        ["tech house mix", "k-pop revival", "christian rock ballad"],
    )
    def test_repeated_normalization_is_stable(self, genre_processor, decorated_input):
        once = genre_processor.normalize_genre_name(decorated_input)
        twice = genre_processor.normalize_genre_name(once)
        assert once == twice


class TestSpecificityCollisionCountRegressionGuard:
    """
    Zaehlt die Anzahl der Alias-Paare, bei denen ein generischerer Alias
    (fruehere Iterationsposition, kuerzer) einen spezifischeren Alias
    (Wortgrenzen-Teilstring, unterschiedlicher Zielwert) potenziell
    ueberstimmen kann. Dient als Regressionswaechter: eine kuenftige
    YAML-Aenderung, die neue Kollisionen einfuehrt oder bestehende
    beseitigt, aendert diese Zahl - ohne dass dieser Test automatisch
    "kaputt" ist (er dokumentiert nur den aktuellen Stand, siehe
    ARCH-014-Doku Abschnitt 4 fuer die vollstaendige Liste aller Paare).
    """

    def test_known_collision_pair_count(self, genre_mapper, genre_processor):
        norm_map = genre_processor.GENRE_NORMALIZATION
        keys_in_order = list(norm_map.keys())
        key_index = {k: i for i, k in enumerate(keys_in_order)}

        pairs = []
        for specific in keys_in_order:
            for generic in keys_in_order:
                if generic == specific:
                    continue
                if key_index[generic] >= key_index[specific]:
                    continue
                if len(generic) >= len(specific):
                    continue
                if genre_processor._contains_alias_as_whole_word(
                    specific, generic
                ):
                    if norm_map[generic] != norm_map[specific]:
                        pairs.append((specific, generic))

        assert len(pairs) == 55, (
            f"Erwartete 55 bekannte Spezifitaets-Kollisionspaare "
            f"(siehe docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md), "
            f"gefunden: {len(pairs)}. Wenn dies durch eine bewusste "
            f"YAML-Aenderung verursacht wurde, ist das kein Fehler - "
            f"die ARCH-014-Dokumentation und diese Zahl sollten dann "
            f"gemeinsam aktualisiert werden."
        )
