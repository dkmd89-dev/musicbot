"""
Characterization-Tests fuer ArtistNormalizer.normalize() (utils/artist_map.py),
Phase 2 - bislang nur indirekt ueber ArtistProcessor.determine_best_artist
mit unauffaelligen Strings getestet (tests/test_metadata_modules.py).

Enthaelt auch die Charakterisierung von ArtistNormalizer.normalize()s
Collaboration-Verhalten direkt (unveraendert): normalize() selbst kennt
weiterhin kein Konzept von Haupt- vs. Feature-Artist und flacht jeden
Collaboration-String (z.B. "&" + "feat.") zu einer gleichrangigen
Komma-Liste ab, inkl. Verlust stilisierter Schreibweisen (z.B. "GReeeN"
-> "Green"). ARTIST-001 selbst (die daraus resultierende Fehlklassifizierung
von Feature-Artists) ist inzwischen behoben - aber NICHT durch eine
Aenderung an normalize() (das wird von 13+ unabhaengigen Stellen im Repo
genutzt), sondern indem ArtistProcessor.determine_best_artist() Haupt-/
Feature-Artist bereits VOR dem Aufruf von normalize() trennt und nur den
Hauptteil normalisiert (siehe tests/test_metadata_modules.py,
test_determine_best_artist_keeps_compound_main_artist_with_mixed_separators).
Die hier charakterisierten Tests bleiben als Beleg fuer normalize()s
eigenes, weiterhin unveraendertes Verhalten bestehen.

WICHTIG: ArtistConfig.mapping_dir wird IMMER explizit auf tmp_path gesetzt.
Ohne das faellt ArtistNormalizer._load_case_preserve()/_load_auto_learned()
auf die bare relative Pfadangabe Path("mapping") zurueck, die - da pytest
vom Repo-Root aus laeuft - auf das ECHTE mapping/-Verzeichnis zeigt. Die
ALL-CAPS-/Prefix-Regeln in _standard_normalization() persistieren neu
gelernte Eintraege dort (case_preserve.yaml) - ohne mapping_dir-Override
haette bereits ein einziger Testlauf reale Mapping-Daten veraendert
(passiert bei der ersten Version dieser Datei tatsaechlich, siehe
git-Historie/Commit-Message - seither immer mapping_dir setzen).
"""

import json

import pytest

from utils.artist_map import ArtistConfig, ArtistNormalizer


@pytest.fixture
def library_dir(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


@pytest.fixture
def override_file(tmp_path):
    return tmp_path / "overrides.json"


@pytest.fixture
def mapping_dir(tmp_path):
    return tmp_path / "mapping"


def make_normalizer(library_dir, override_file, mapping_dir):
    return ArtistNormalizer(
        ArtistConfig(
            library_dir=library_dir,
            override_file=override_file,
            mapping_dir=mapping_dir,
        )
    )


@pytest.fixture
def normalizer(library_dir, override_file, mapping_dir):
    return make_normalizer(library_dir, override_file, mapping_dir)


class TestOverrides:
    def test_library_dir_subdirectory_becomes_an_override(
        self, library_dir, override_file, mapping_dir
    ):
        (library_dir / "Bausa").mkdir()
        normalizer = make_normalizer(library_dir, override_file, mapping_dir)
        assert normalizer.normalize("bausa") == "Bausa"

    def test_override_file_entry_is_used_case_insensitively(
        self, library_dir, override_file, mapping_dir
    ):
        override_file.write_text(
            json.dumps({"lil kex": "Lil Kex"}), encoding="utf-8"
        )
        normalizer = make_normalizer(library_dir, override_file, mapping_dir)
        assert normalizer.normalize("lil kex") == "Lil Kex"
        assert normalizer.normalize("LIL KEX") == "Lil Kex"

    def test_construction_writes_override_file_from_library_dir(
        self, library_dir, override_file, mapping_dir
    ):
        (library_dir / "Bausa").mkdir()
        assert not override_file.exists()

        make_normalizer(library_dir, override_file, mapping_dir)

        assert override_file.exists()

    def test_missing_override_file_does_not_crash(self, normalizer):
        # override_file existierte beim Konstruieren nicht (nur die
        # normalizer-Fixture ohne vorherigen library_dir-Eintrag) -
        # normalize() muss trotzdem funktionieren (Fallback-Pfad).
        assert normalizer.normalize("kollegah") == "Kollegah"

    def test_corrupt_override_file_falls_back_silently(
        self, library_dir, override_file, mapping_dir
    ):
        override_file.write_text("{not valid json", encoding="utf-8")
        normalizer = make_normalizer(library_dir, override_file, mapping_dir)
        # Kein Crash, normalize faellt auf die Standard-Normalisierung zurueck.
        assert normalizer.normalize("kollegah") == "Kollegah"


class TestStandardNormalizationRules:
    def test_all_caps_short_name_is_kept_unchanged(self, normalizer):
        assert normalizer.normalize("UFO361") == "UFO361"

    def test_prefix_rule_capitalizes_rest_after_short_uppercase_prefix(
        self, normalizer
    ):
        assert normalizer.normalize("DJ stylewarz") == "DJ Stylewarz"

    def test_plain_lowercase_name_falls_back_to_title_case(self, normalizer):
        assert normalizer.normalize("kollegah") == "Kollegah"

    def test_none_or_empty_returns_unknown(self, normalizer):
        assert normalizer.normalize("") == "Unknown"
        assert normalizer.normalize(None) == "Unknown"


class TestCollaborationArchitectureCharacterization:
    """
    normalize() selbst laeuft weiterhin auf dem unaufgeteilten Collaboration-
    String (bewusst unveraendert, siehe Modul-Docstring). ARTIST-001 ist auf
    determine_best_artist()-Ebene behoben, nicht hier.
    """

    def test_single_feat_keyword_preserves_order_but_loses_styled_casing(
        self, normalizer
    ):
        # "1986zig feat. GReeeN" -> Reihenfolge bleibt erhalten (1986zig zuerst),
        # aber die stilisierte Schreibweise "GReeeN" wird zu "Greeen" verkuerzt.
        result = normalizer.normalize("1986zig feat. GReeeN")
        assert result == "1986zig, Greeen"

    def test_mixed_ampersand_and_feat_flattens_main_artist_to_peer(
        self, normalizer
    ):
        # "GReeeN & 1986zig feat. Bausa": split_main_and_featuring wuerde
        # main="GReeeN & 1986zig", feat=["Bausa"] liefern (Haupt-Artist bleibt
        # zusammengesetzt). normalize() behandelt stattdessen ALLE drei Teile
        # als gleichrangige Peers, weil "&" und "feat." beide zu "," werden,
        # bevor irgendeine Haupt-/Feature-Unterscheidung stattfindet -
        # "1986zig" verliert seinen Platz im Haupt-Artist.
        result = normalizer.normalize("GReeeN & 1986zig feat. Bausa")
        assert result == "Greeen, 1986zig, Bausa"


class TestArtistnorm001FeatFtWordBoundaryFix:
    """
    Regressionstest fuer ARTISTNORM-001: das Featuring-Pattern
    (r"\\s*(?:feat\\.?|ft\\.?)\\s*") matchte "ft"/"feat" bisher als reinen
    Teilstring ohne Wortgrenzen - Woerter, die diese Buchstabenfolge nur
    zufaellig enthalten, wurden verstuemmelt. Gefunden beim Testen von
    AUTOLEARN-001 mit dem echten Kanalnamen "Hardenacke trifft"
    (mapping/special_channel.yaml).
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Hardenacke trifft", "Hardenacke Trifft"),
            ("Kraftklub", "Kraftklub"),
            ("Draft", "Draft"),
            ("Wefts", "Wefts"),
            ("Softi", "Softi"),
        ],
    )
    def test_words_containing_ft_substring_are_not_mangled(
        self, normalizer, raw, expected
    ):
        assert normalizer.normalize(raw) == expected

    def test_genuine_feat_keyword_still_splits_correctly(self, normalizer):
        # Regressionsschutz: der eigentliche Zweck des Patterns (echte
        # "Artist feat. Other"-Trennung) darf durch die \b-Ergaenzung nicht
        # verloren gehen - bereits oben in
        # test_single_feat_keyword_preserves_order_but_loses_styled_casing
        # abgedeckt, hier zusaetzlich ohne Punkt und in Grossschreibung.
        assert normalizer.normalize("Artist FT Other") == "Artist, Other"
        assert normalizer.normalize("Artist ft Other") == "Artist, Other"
