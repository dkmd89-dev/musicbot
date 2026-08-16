"""
Characterization-Tests fuer ArtistNormalizer.normalize() (utils/artist_map.py),
Phase 2 - bislang nur indirekt ueber ArtistProcessor.determine_best_artist
mit unauffaelligen Strings getestet (tests/test_metadata_modules.py).

Enthaelt auch die zurueckgestellte Charakterisierung der bekannten
ARTIST-001-Architektur-Inkonsistenz (siehe docs/MusicBot_ENGINEERING_BASELINE.md):
normalize() wird auf unaufgeteilte Collaboration-Strings angewendet, bevor
Haupt-/Feature-Artist getrennt werden, was bei gemischten Trennzeichen
(z.B. "&" + "feat.") den Haupt-Artist-Anteil zu einem Feature degradiert
und stilisierte Schreibweisen (z.B. "GReeeN") einebnet. Dieser Test friert
das aktuelle Verhalten ein, ohne es zu fixen.

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
    ARTIST-001 (zurueckgestellt, nur charakterisiert): normalize() laeuft
    auf dem unaufgeteilten Collaboration-String, bevor irgendeine
    Haupt-/Feature-Trennung stattfindet.
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
