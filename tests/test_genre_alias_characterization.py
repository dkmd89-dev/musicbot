# tests/test_genre_alias_characterization.py
# -*- coding: utf-8 -*-
"""
ARCH-013 Phase 1 - Characterization-Tests fuer die doppelte
Alias-Repraesentation (POST-ARCH-012-Audit, Befund E.6).

`mapping/genre_aliases.yaml` wird von zwei unabhaengigen Klassen geladen
und mit zwei unabhaengigen Algorithmen normalisiert:

  - utils.genre_map.GenreMapper.normalize_genre_name()
  - services.metadata.genre_processor.GenreProcessor.normalize_genre_name()

Diese Tests frieren das AKTUELLE Verhalten beider Implementierungen fest -
sie bewerten NICHT, welches Verhalten "richtig" ist, und sie aendern keine
Produktionslogik. Alle Werte sind gegen die echten YAML-Dateien in
mapping/ verifiziert (siehe
docs/MusicBot_ARCH-013_Genre_Alias_Characterization.md).

ARCH-013 Phase 3 (docs/MusicBot_ARCH-013_Genre_Alias_Decision.md, Abschnitt
7/9) hat den Mixed-Case-/Whitespace-Befund (Punkt 1 unten, urspruengliche
Fassung) als fachlich unstrittigen Bug behoben: GenreMapper lowercased
genre_aliases.yaml-Keys seither beim Laden (utils/genre_map.py,
_load_all_mappings). TestAliasLoadingDivergence dokumentiert seit Phase 3
das KORRIGIERTE Verhalten, nicht mehr den Bug - siehe die
Klassen-Docstring dort fuer den Vorher/Nachher-Vergleich. Alle anderen
Kernbefunde (2/3 unten) sind von Phase 3 ausdruecklich NICHT beruehrt.

ARCH-013 Phase 4 (docs/MusicBot_ARCH-013_Genre_Alias_Decision.md,
Abschnitt 4/8/9) hat Kernbefund 2 unten (die 4 Override-vs-Alias-
Wertkonflikte) aufgeloest: mapping/genre_aliases.yaml und
mapping/genre_overrides.yaml wurden per hierarchie-basierter
Einzelfallregel so korrigiert, dass beide Dateien fuer alle 4 Genres
denselben Wert enthalten. TestOverrideAliasConflictsResolvedInPhase4
(vormals TestOverrideLayerOnlyAffectsGenreMapper) dokumentiert seit Phase
4 das KORRIGIERTE Verhalten. Kernbefund 3 (Teilstring-Match) ist von
Phase 4 ausdruecklich NICHT beruehrt (das war ARCH-013 Phase 5).

ARCH-013 Phase 5 (docs/MusicBot_ARCH-013_Genre_Alias_Decision.md,
Abschnitt 5) hat Kernbefund 3 unten (Teilstring-Match) auf Wortgrenzen-
Matching eingeschraenkt: ein Alias matcht nur noch als eigenstaendiges
Wort/eigenstaendige Wortfolge (begrenzt durch Leerzeichen, Satzzeichen
oder Stringanfang/-ende), nicht mehr als Zeichenfolge innerhalb eines
laengeren Einzelworts. TestSubstringMatchingOnlyInGenreProcessor
dokumentiert seit Phase 5 das KORRIGIERTE Verhalten.

Kernbefunde, die hier eingefroren werden:

1. (Stand vor ARCH-013 Phase 3, siehe TestAliasLoadingDivergence fuer das
   aktuelle, korrigierte Verhalten) GenreMapper lud genre_aliases.yaml
   ohne die Keys zu lowercasen; GenreProcessor lowercased sie explizit
   beim Laden (services/metadata/genre_processor.py:757). Die beiden
   Mixed-Case-Keys im YAML ("Hip-Hop", "Hip - Hop") waren dadurch in
   GenreMapper ueber den regulaeren (stets lowercased suchenden)
   Lookup-Pfad nicht erreichbar.
2. (Stand vor ARCH-013 Phase 4, siehe
   TestOverrideAliasConflictsResolvedInPhase4 fuer das aktuelle,
   korrigierte Verhalten) GenreMapper konsultierte zusaetzlich
   mapping/genre_overrides.yaml MIT Vorrang vor genre_aliases.yaml
   (utils/genre_map.py, Schritt 1 vor Schritt 2 in
   normalize_genre_name(), Code-Vorrang unveraendert bestehend).
   GenreProcessor kennt genre_overrides.yaml weiterhin ueberhaupt nicht.
   Es gab 4 echte Wertkonflikte zwischen beiden YAML-Dateien fuer
   denselben Schluessel (electropop, chamber pop, tech house, ruhrpott
   rap) - diese 4 Genres wurden von GenreMapper und GenreProcessor
   unterschiedlich normalisiert, bis die YAML-Werte in Phase 4
   angeglichen wurden.
3. (Stand vor ARCH-013 Phase 5, siehe
   TestSubstringMatchingOnlyInGenreProcessor fuer das aktuelle,
   korrigierte Verhalten) GenreProcessor.normalize_genre_name() hatte
   einen zusaetzlichen Teilstring-Match-Schritt, den GenreMapper nicht
   besitzt - ein beliebiger String, der einen bekannten Alias als
   Zeichenfolge (auch ohne Wortgrenzen) enthielt, wurde darueber
   normalisiert, auch wenn er selbst kein Alias war (z.B. "britpop" wurde
   ueber den eingebetteten Alias "pop" zu "Pop"). Seit Phase 5 gilt eine
   Wortgrenzen-Bedingung; GenreMapper besitzt weiterhin ueberhaupt kein
   Teilstring-Matching.

Bewusst NICHT Teil dieser Datei: GENRE-002 (mapping/genre_rules.yaml
Schema-Mismatch, siehe tests/test_genre_mapper_advanced.py) - das ist ein
bereits entschiedener, separater Punkt, keine Alias-Repraesentationsfrage.
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


class TestAliasLoadingDivergence:
    """
    Charakterisiert die unterschiedliche interne Repraesentation derselben
    genre_aliases.yaml-Datei.

    ARCH-013 Phase 3: bis einschliesslich Phase 2 lud GenreMapper die
    genre_aliases.yaml-Keys UNVERAENDERT (Mixed-Case-Keys "Hip-Hop"/
    "Hip - Hop" blieben bestehen), waehrend GenreProcessor sie beim Laden
    explizit lowercased hat - dadurch war "Hip - Hop" in GenreMapper ueber
    den regulaeren (stets lowercased suchenden) Lookup nicht erreichbar und
    fiel auf einen fehlerhaften Title-Case-Fallback zurueck ("Hip  Hop",
    doppeltes Leerzeichen). Seit Phase 3 lowercased GenreMapper die Keys
    beim Laden ebenfalls (utils/genre_map.py, _load_all_mappings, analog
    zum bereits bestehenden GENRE-003-Muster fuer die Hierarchie-Keys) -
    diese Klasse dokumentiert ab hier das KORRIGIERTE Verhalten.
    """

    def test_genre_mapper_lowercases_all_keys_at_load_time(
        self, genre_mapper
    ):
        mixed_case_keys = [
            k for k in genre_mapper.genre_aliases if k != k.lower()
        ]
        assert mixed_case_keys == []

    def test_genre_processor_lowercases_all_keys_at_load_time(
        self, genre_processor
    ):
        mixed_case_keys = [
            k for k in genre_processor.GENRE_NORMALIZATION if k != k.lower()
        ]
        assert mixed_case_keys == []

    def test_previously_mixed_case_yaml_entry_now_reachable_in_genre_mapper(
        self, genre_mapper
    ):
        # Vor Phase 3: genre_mapper.genre_aliases["Hip - Hop"] existierte
        # als eigener Mixed-Case-Key und war ueber normalize_genre_name()
        # nicht erreichbar (KeyError bei diesem exakten Key-Zugriff, da der
        # Key seit dem Lowercase-Fix als "hip - hop" gespeichert ist).
        assert "Hip - Hop" not in genre_mapper.genre_aliases
        assert genre_mapper.genre_aliases["hip - hop"] == "Hip Hop"
        assert genre_mapper.normalize_genre_name("Hip - Hop") == "Hip Hop"

    def test_hip_hop_case_and_whitespace_variants_all_normalize_identically(
        self, genre_mapper
    ):
        variants = [
            "Hip-Hop", "Hip - Hop", "hip-hop", "HIP-HOP",
            "Hip  Hop", "hiphop", "Hip Hop", "HIP - HOP", "hip - hop",
        ]
        for variant in variants:
            assert genre_mapper.normalize_genre_name(variant) == "Hip Hop", (
                f"{variant!r} normalisiert nicht auf 'Hip Hop'"
            )

    def test_normalize_genre_name_is_idempotent_for_the_fixed_alias(
        self, genre_mapper
    ):
        for raw in ["Hip-Hop", "Hip - Hop"]:
            once = genre_mapper.normalize_genre_name(raw)
            twice = genre_mapper.normalize_genre_name(once)
            assert once == twice == "Hip Hop"

    def test_mixed_case_yaml_entry_resolves_correctly_in_genre_processor(
        self, genre_processor
    ):
        # Derselbe Input trifft in GenreProcessor den (lowercased
        # geladenen) Key direkt und liefert das korrekte YAML-Ergebnis.
        assert genre_processor.normalize_genre_name("Hip - Hop") == "Hip Hop"


class TestOverrideAliasConflictsResolvedInPhase4:
    """
    ARCH-013 Phase 4 (docs/MusicBot_ARCH-013_Genre_Alias_Decision.md,
    Abschnitt 4/8/9) hat die 4 in Phase 1 gefundenen Wertkonflikte zwischen
    mapping/genre_aliases.yaml und mapping/genre_overrides.yaml per
    hierarchie-basierter Einzelfallregel aufgeloest:

      - electropop/chamber pop/tech house: Override gewann bereits vorher
        (DATA-002-Praezedenzfall + reale Consumer in artist_genre.yaml/
        channel_genre.yaml) - genre_aliases.yaml wurde auf denselben,
        granularen Wert korrigiert.
      - ruhrpott rap: umgekehrt - genre_aliases.yaml hatte bereits den mit
        genre_hierarchy.yaml konsistenten granularen Wert
        ("Ruhrpott Rap"); genre_overrides.yaml wurde von "Deutschrap" auf
        "Ruhrpott Rap" korrigiert (einziger von 18 strukturell
        gleichartigen Regional-Rap-Eintraegen mit abweichendem Override,
        kein realer Consumer haengt vom alten Wert ab, siehe Phase-2-
        Konfliktanalyse 3.4 - vom Nutzer vor der Umsetzung ausdruecklich
        bestaetigt).

    Diese Klasse dokumentierte bis Phase 4 die (bewusst nur bis dahin
    geltende) Divergenz zwischen GenreMapper und GenreProcessor fuer diese
    4 Eingaben. Sie haelt jetzt das KORRIGIERTE Verhalten fest: beide
    Implementierungen liefern fuer alle 4 dasselbe Ergebnis, weil die
    zugrunde liegenden YAML-Dateien nicht mehr widersprechen. GenreMapper
    prueft mapping/genre_overrides.yaml weiterhin mit Vorrang vor
    mapping/genre_aliases.yaml (Code unveraendert) - der Vorrang ist nur
    seit Phase 4 fuer diese 4 Schluessel folgenlos, weil beide Dateien
    denselben Wert enthalten.
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
    def test_genre_mapper_and_genre_processor_now_agree(
        self, genre_mapper, genre_processor, raw_genre, expected
    ):
        gm_result = genre_mapper.normalize_genre_name(raw_genre)
        gp_result = genre_processor.normalize_genre_name(raw_genre)

        assert gm_result == expected
        assert gp_result == expected
        assert gm_result == gp_result

    def test_genre_processor_has_no_knowledge_of_overrides_file(
        self, genre_processor
    ):
        # Unveraendert durch Phase 4: GenreProcessor liest
        # genre_overrides.yaml weiterhin nicht - die Uebereinstimmung
        # oben kommt daher, dass beide YAML-Dateien jetzt denselben Wert
        # enthalten, nicht daher, dass GenreProcessor die Override-Datei
        # neu kennengelernt haette.
        assert not hasattr(genre_processor, "overrides")
        assert "genre_overrides" not in genre_processor.__dict__


class TestSubstringMatchingOnlyInGenreProcessor:
    """
    GenreProcessor.normalize_genre_name() hat einen Teilstring-Match-
    Schritt, der GenreMapper fehlt.

    ARCH-013 Phase 5 (docs/MusicBot_ARCH-013_Genre_Alias_Decision.md,
    Abschnitt 5) hat diesen Schritt auf Wortgrenzen-Matching eingeschraenkt:
    ein bekannter Alias matcht nur noch, wenn er im Eingabestring als
    eigenstaendiges Wort/eigenstaendige Wortfolge vorkommt (begrenzt durch
    Leerzeichen, Satzzeichen oder Stringanfang/-ende) - nicht mehr, wenn er
    nur als Zeichenfolge innerhalb eines laengeren Einzelworts auftritt
    (vorheriger Bug: "pop" traf faelschlich auch in "britpop").
    GenreMapper besitzt weiterhin ueberhaupt kein Teilstring-Matching
    (Klassenname bezieht sich auf diesen Unterschied, nicht auf
    Wortgrenzen).
    """

    def test_unknown_genre_containing_alias_only_embedded_in_a_word_is_not_matched(
        self, genre_mapper, genre_processor
    ):
        # "britpop" ist selbst KEIN Eintrag in genre_aliases.yaml und
        # enthaelt "pop" nur als Zeichenfolge INNERHALB des Einzelworts
        # "britpop" (kein Leerzeichen/Satzzeichen davor) - seit Phase 5
        # matcht das nicht mehr, in KEINER der beiden Implementierungen.
        assert "britpop" not in genre_mapper.genre_aliases
        assert "britpop" not in genre_processor.GENRE_NORMALIZATION

        assert genre_mapper.normalize_genre_name("britpop") == "Britpop"
        assert genre_processor.normalize_genre_name("britpop") == "Britpop"

    def test_free_text_containing_known_alias_as_whole_word_still_matches(
        self, genre_mapper, genre_processor
    ):
        # "hip hop" kommt in "some hip hop music" als eigenstaendige
        # Wortfolge vor (durch Leerzeichen begrenzt) - matcht unveraendert,
        # Wortgrenzen-Regel aendert hier nichts.
        text = "some hip hop music"
        assert genre_mapper.normalize_genre_name(text) == "Some Hip Hop Music"
        assert genre_processor.normalize_genre_name(text) == "Hip Hop"

    def test_alias_embedded_between_word_boundaries_still_matches(
        self, genre_processor
    ):
        # "ruhrpott rap" ist durch ein Leerzeichen (davor: Stringanfang,
        # danach: Leerzeichen) begrenzt - Wortgrenzen-Regel erlaubt diesen
        # Treffer weiterhin (Phase-2 Fall B/D, "korrekter Teilstring-Treffer").
        assert genre_processor.normalize_genre_name(
            "ruhrpott rap fanpage"
        ) == "Ruhrpott Rap"
        assert genre_processor.normalize_genre_name(
            "deutschrap only"
        ) == "Deutschrap"

    def test_alias_embedded_after_hyphen_still_counts_as_word_boundary(
        self, genre_processor
    ):
        # Bindestriche zaehlen laut Phase-2-Spezifikation als
        # "Satzzeichen"-Wortgrenze, nicht nur Leerzeichen - reales
        # MusicBrainz-/Last.fm-Tag-Beispiel: durchgekoppelte Tags wie
        # "deutsch-hip-hop" sollen den Alias weiterhin finden.
        assert genre_processor.normalize_genre_name(
            "deutsch-hip-hop"
        ) == "Hip Hop"


class TestBothImplementationsAgreeOnUnambiguousAliases:
    """
    Gegenprobe: fuer Aliase, die NICHT von den beiden oben charakterisierten
    Divergenzquellen (Mixed-Case-Key, Override-Konflikt, Teilstring-
    Zufallstreffer) betroffen sind, liefern beide Implementierungen
    identische Ergebnisse - die Duplikation ist nicht grundsaetzlich
    inkonsistent, sondern divergiert nur in den dokumentierten Randfaellen.
    """

    @pytest.mark.parametrize(
        "raw_genre,expected",
        [
            ("deutschrap", "Deutschrap"),
            ("DEUTSCHRAP", "Deutschrap"),
            ("hip-hop", "Hip Hop"),
            ("hiphop", "Hip Hop"),
            ("r&b", "R&B"),
            ("r'n'b", "R&B"),
            ("k-pop", "K-Pop"),
            ("trap", "Hip Hop"),
        ],
    )
    def test_identical_result_for_unambiguous_aliases(
        self, genre_mapper, genre_processor, raw_genre, expected
    ):
        assert genre_mapper.normalize_genre_name(raw_genre) == expected
        assert genre_processor.normalize_genre_name(raw_genre) == expected

    def test_empty_input_diverges_in_return_type_semantics(
        self, genre_mapper, genre_processor
    ):
        # Kein Alias-Befund, sondern eine allgemeine Signatur-Divergenz:
        # GenreMapper gibt bei leerem Input einen leeren String zurueck,
        # GenreProcessor den Platzhalter "Unknown".
        assert genre_mapper.normalize_genre_name("") == ""
        assert genre_processor.normalize_genre_name("") == "Unknown"


class TestYamlSourceCollisions:
    """
    Charakterisiert Konflikte, die bereits in den YAML-Quelldateien selbst
    angelegt sind (unabhaengig davon, welche Klasse sie laedt).
    """

    def test_genre_aliases_and_genre_overrides_have_no_known_conflicts(self):
        # ARCH-013 Phase 4: die 4 in Phase 1 gefundenen Konflikte
        # (electropop, chamber pop, tech house, ruhrpott rap) wurden durch
        # gezielte YAML-Korrekturen aufgeloest (siehe
        # TestOverrideAliasConflictsResolvedInPhase4). Dieser Test
        # verifiziert das nicht nur fuer die 4 bekannten Faelle, sondern
        # als generische Regressionssicherung gegen JEDEN kuenftigen
        # stillen Konflikt zwischen den beiden Dateien.
        import yaml
        from pathlib import Path

        mapping_dir = Path(Config().GENRE_MAPPING_DIR)
        with open(mapping_dir / "genre_aliases.yaml", encoding="utf-8") as f:
            aliases = yaml.safe_load(f)["GENRE_ALIASES"]
        with open(mapping_dir / "genre_overrides.yaml", encoding="utf-8") as f:
            overrides = yaml.safe_load(f)["GENRE_OVERRIDES"]

        aliases_lower = {k.lower(): v for k, v in aliases.items()}
        overrides_lower = {str(k).lower(): v for k, v in overrides.items()}

        common_keys = set(aliases_lower) & set(overrides_lower)
        conflicts = {
            k
            for k in common_keys
            if aliases_lower[k] != overrides_lower[k]
        }

        assert conflicts == set(), (
            f"Neue(r) Konflikt(e) zwischen genre_aliases.yaml und "
            f"genre_overrides.yaml gefunden: {conflicts} - siehe ARCH-013 "
            f"Phase 2 fuer die zu verwendende Entscheidungsregel "
            f"(hierarchie-basiert, docs/MusicBot_ARCH-013_Genre_Alias_Decision.md)."
        )

    def test_synth_pop_and_synthpop_are_distinct_keys_with_different_targets(
        self,
    ):
        # Kein Konflikt im engeren Sinn (unterschiedliche Schluessel), aber
        # eine Kollisionsfalle: zwei fast identische Schreibweisen desselben
        # Wortes fuehren bewusst zu unterschiedlichen Zielgenres.
        import yaml
        from pathlib import Path

        mapping_dir = Path(Config().GENRE_MAPPING_DIR)
        with open(mapping_dir / "genre_aliases.yaml", encoding="utf-8") as f:
            aliases = yaml.safe_load(f)["GENRE_ALIASES"]

        assert aliases["synth-pop"] == "Pop"
        assert aliases["synthpop"] == "Electronic"
