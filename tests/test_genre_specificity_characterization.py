# tests/test_genre_specificity_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-014 - Genre Specificity / Longest-Match.

Phase 1 (docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md)
charakterisierte, dass GenreProcessor.normalize_genre_name()s
Wortgrenzen-Teilstring-Match (ARCH-013 Phase 5) beim ERSTEN gueltigen
Treffer in Dict-Iterationsreihenfolge zurueckkehrte, ohne Spezifitaet zu
beruecksichtigen - ein generischer Alias (z.B. "pop") konnte einen
spezifischeren Alias (z.B. "tech house") ueberstimmen, wenn beide in
einem dekorierten String (z.B. "tech house mix") gueltige
Wortgrenzen-Treffer waren. 55 betroffene Alias-Paare wurden identifiziert.

Phase 2 (docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md,
Abschnitt "Phase 2 - Umsetzung") hat die daraus abgeleitete Regel
umgesetzt: bei mehreren gueltigen Wortgrenzen-Treffern gewinnt der Treffer
mit der groessten Zeichenlaenge des Alias-Keys, mit der bestehenden
Hierarchie-Tiefe (self.GENRE_PRIORITY) als Tie-Breaker bei Gleichstand.

Diese Datei dokumentiert seit Phase 2 das KORRIGIERTE Soll-Verhalten -
nicht mehr den Bug. Assertions wurden invertiert (spezifischer statt
generischer Wert erwartet), nicht geloescht (etabliertes Muster aus
ARCH-012/013).
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


def _all_specificity_pairs(genre_processor):
    """
    Leitet alle Alias-Paare her, bei denen ein generischerer Alias
    (fruehere Iterationsposition, kuerzer) als Wortgrenzen-Teilstring in
    einem spezifischeren Alias vorkommt und beide auf unterschiedliche
    Zielgenres normalisieren. Identischer Erkennungsmechanismus wie in
    ARCH-014 Phase 1 (docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md,
    Abschnitt 4) - programmatisch, nicht hartkodiert, damit der Test bei
    YAML-Aenderungen automatisch die aktuelle Paarmenge prueft.
    """
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
            if genre_processor._contains_alias_as_whole_word(specific, generic):
                if norm_map[generic] != norm_map[specific]:
                    pairs.append((specific, generic))
    return pairs


class TestSpecificAliasNowOutranksGenericAlias:
    """
    ARCH-014 Phase 2: bei einem dekorierten String, der sowohl einen
    generischen als auch einen spezifischeren Alias als gueltigen
    Wortgrenzen-Treffer enthaelt, gewinnt seit Phase 2 der laengere
    (spezifischere) Alias-Key.
    """

    @pytest.mark.parametrize(
        "decorated_input,expected_specific_value,previously_wrong_generic_value",
        [
            ("tech house mix", "Tech House", "House"),
            ("k-pop revival", "K-Pop", "Pop"),
            ("christian rock ballad", "Gospel", "Rock"),
            ("indie rock legend", "Indie", "Rock"),
            ("bedroom pop vibes", "Indie", "Pop"),
            ("country pop hit", "Country Pop", "Pop"),
            ("progressive house anthem", "Progressive House", "House"),
            ("west coast hip hop classic", "West Coast Hip Hop", "Hip Hop"),
            ("symphonic metal choir", "Metal", "Klassik"),
        ],
    )
    def test_decorated_input_resolves_to_specific_alias(
        self,
        genre_processor,
        decorated_input,
        expected_specific_value,
        previously_wrong_generic_value,
    ):
        result = genre_processor.normalize_genre_name(decorated_input)
        assert result == expected_specific_value
        # Gegenprobe: der vor Phase 2 zurueckgegebene generische Wert
        # gewinnt jetzt nicht mehr.
        assert result != previously_wrong_generic_value

    def test_undecorated_specific_alias_still_resolves_correctly(
        self, genre_processor
    ):
        # Exakter Match (Schritt 1) war nie betroffen und bleibt
        # unveraendert korrekt.
        for key, expected in [
            ("tech house", "Tech House"),
            ("k-pop", "K-Pop"),
            ("indie rock", "Indie"),
        ]:
            assert genre_processor.normalize_genre_name(key) == expected

    def test_all_55_characterized_pairs_resolve_to_specific_value(
        self, genre_processor
    ):
        """
        Vollstaendiger Soll-Verhalten-Test ueber alle programmatisch
        hergeleiteten Kollisionspaare (ARCH-014 Phase 1, Abschnitt 4) -
        keiner der Faelle darf nach Phase 2 noch den generischen Wert
        liefern, wenn der spezifischere Alias als gueltiger
        Wortgrenzen-Treffer vorhanden ist.
        """
        pairs = _all_specificity_pairs(genre_processor)
        assert len(pairs) == 55

        still_generic = []
        for specific_key, generic_key in pairs:
            specific_value = genre_processor.GENRE_NORMALIZATION[specific_key]
            generic_value = genre_processor.GENRE_NORMALIZATION[generic_key]
            result = genre_processor.normalize_genre_name(specific_key + " extra")
            if result != specific_value:
                still_generic.append(
                    (specific_key, generic_key, specific_value, generic_value, result)
                )

        assert still_generic == [], (
            f"{len(still_generic)} von 55 Paaren liefern weiterhin den "
            f"generischen statt des spezifischen Werts: {still_generic}"
        )


class TestWordBoundaryNegativeCasesStillExcluded:
    """
    ARCH-013 Phase 5 (Wortgrenzen-Bedingung) bleibt durch die
    Spezifitaetsregel unveraendert - ein Alias, der nur als Zeichenfolge
    innerhalb eines laengeren Einzelworts auftritt (keine Wortgrenze),
    matcht weiterhin NICHT, unabhaengig von seiner Laenge.
    """

    def test_alias_only_embedded_in_a_word_is_not_matched(self, genre_processor):
        # "pop" ist kein gueltiger Wortgrenzen-Treffer in "britpop" -
        # unveraendert seit ARCH-013 Phase 5.
        assert genre_processor.normalize_genre_name("britpop") == "Britpop"
        assert (
            genre_processor.normalize_genre_name("britpop revival")
            == "Britpop Revival"
        )

    def test_alias_embedded_between_word_boundaries_still_matches(
        self, genre_processor
    ):
        assert (
            genre_processor.normalize_genre_name("ruhrpott rap fanpage")
            == "Ruhrpott Rap"
        )
        assert genre_processor.normalize_genre_name("deutschrap only") == "Deutschrap"


class TestArch013RulesPreserved:
    """
    ARCH-013s bereits etablierte Regeln (Alias-Konflikte, Mixed-Case/
    Whitespace, Multi-Tag-Priorisierung) duerfen durch die
    Spezifitaetsregel nicht regressieren.
    """

    @pytest.mark.parametrize(
        "raw_genre,expected",
        [
            ("electropop", "Electropop"),
            ("chamber pop", "Chamber Pop"),
            ("tech house", "Tech House"),
            ("ruhrpott rap", "Ruhrpott Rap"),
        ],
    )
    def test_alias_conflicts_resolved_in_phase4_still_hold(
        self, genre_mapper, genre_processor, raw_genre, expected
    ):
        assert genre_mapper.normalize_genre_name(raw_genre) == expected
        assert genre_processor.normalize_genre_name(raw_genre) == expected

    @pytest.mark.parametrize(
        "raw_genre",
        ["Hip-Hop", "Hip - Hop", "hip-hop", "HIP-HOP", "Hip  Hop", "hip - hop"],
    )
    def test_mixed_case_and_whitespace_still_normalize_to_hip_hop(
        self, genre_mapper, raw_genre
    ):
        assert genre_mapper.normalize_genre_name(raw_genre) == "Hip Hop"

    @pytest.mark.parametrize(
        "tags,expected_primary",
        [
            (["ruhrpott rap", "deutschrap"], "Ruhrpott Rap"),
            (["ruhrpott rap", "hip hop", "trap"], "Ruhrpott Rap"),
            (["electropop", "pop"], "Electropop"),
            (["chamber pop", "indie"], "Chamber Pop"),
            (["tech house", "house", "electronic"], "Tech House"),
        ],
    )
    def test_multi_tag_prioritization_from_phase4_unchanged(
        self, genre_processor, tags, expected_primary
    ):
        primary, _secondary = genre_processor.prioritize_genres(tags)
        assert primary == expected_primary


class TestIdempotency:
    """
    Normalisierung muss idempotent bleiben (ARCH-014 Phase 1, Invariante
    6). Fuer 54 der 55 charakterisierten Paare ist das nach Phase 2
    gegeben.
    """

    @pytest.mark.parametrize(
        "decorated_input",
        [
            "tech house mix",
            "k-pop revival",
            "christian rock ballad",
            "indie rock legend",
            "progressive house anthem",
            "symphonic metal choir",
        ],
    )
    def test_repeated_normalization_is_stable(self, genre_processor, decorated_input):
        once = genre_processor.normalize_genre_name(decorated_input)
        twice = genre_processor.normalize_genre_name(once)
        assert once == twice

    def test_known_non_idempotent_exception_ny_drill(self, genre_processor):
        """
        Dokumentierte, bewusst NICHT behobene Ausnahme (ARCH-014 Phase 2,
        "Verbleibende Edge Cases"): "ny drill" -> "New York Drill" ist der
        einzige der 55 Faelle, bei dem der kanonische Zielwert selbst
        nicht auf sich selbst zurueck-normalisiert. Ursache: "New York
        Drill" ist in mapping/genre_aliases.yaml kein eigener Alias-Key
        (nur "ny drill" fuehrt dorthin) - beim zweiten Normalisierungs-
        durchlauf greift stattdessen der im eigenen kanonischen Text
        enthaltene generische Wortgrenzen-Treffer "drill" -> "Hip Hop".
        Kein Bug der Spezifitaetsregel selbst (die 54 anderen Faelle sind
        idempotent), sondern eine vorbestehende, durch diese Phase nur
        sichtbar gewordene Datenluecke in genre_aliases.yaml. Nicht
        behoben (Scope-Grenze: keine Alias-Daten-Aenderung in dieser
        Phase).
        """
        once = genre_processor.normalize_genre_name("ny drill extra")
        assert once == "New York Drill"

        twice = genre_processor.normalize_genre_name(once)
        assert twice == "Hip Hop"
        assert once != twice


class TestSpecificityPairCountRegressionGuard:
    """
    Zaehlt die Anzahl der Alias-Paare, bei denen ein generischerer Alias
    (fruehere Iterationsposition, kuerzer) als Wortgrenzen-Teilstring in
    einem spezifischeren Alias vorkommt. Dient als Regressionswaechter
    fuer kuenftige YAML-Aenderungen (siehe
    docs/MusicBot_ARCH-014_Genre_Specificity_Characterization.md,
    Abschnitt 4, fuer die vollstaendige Liste). Seit Phase 2 werden diese
    Paare korrekt aufgeloest (siehe TestSpecificAliasNowOutranksGenericAlias) -
    dieser Test prueft nur die STRUKTURELLE Paarmenge, nicht mehr, ob sie
    fehlerhaft behandelt wird.
    """

    def test_known_pair_count(self, genre_processor):
        pairs = _all_specificity_pairs(genre_processor)
        assert len(pairs) == 55, (
            f"Erwartete 55 bekannte Spezifitaets-Paare, gefunden: "
            f"{len(pairs)}. Wenn dies durch eine bewusste YAML-Aenderung "
            f"verursacht wurde, ist das kein Fehler - die ARCH-014-"
            f"Dokumentation und diese Zahl sollten dann gemeinsam "
            f"aktualisiert werden."
        )
