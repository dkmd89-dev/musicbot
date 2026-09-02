"""
Live-Fund 2026-09-02 (End-to-End-Testdownload ueber den echten Test-Bot,
docs/FINDINGS_INDEX.md): das Duo "Miksu & Macloud" wird auf YouTube haeufig
als "Miksu/Macloud" (Kanalname teils "Miksu / Macloud") geschrieben. Der
Schraegstrich wird ueberall im Code bewusst als Kollaborations-Trenner
behandelt (utils/youtube_parser.py::_split_multi_artists(),
utils/artist_map.py-Pattern "Slash-Kollaboration") - das ist an sich
korrektes, an vielen anderen Titeln gebrauchtes Verhalten, zerlegt hier
aber den echten Duo-Namen in zwei Einzelkuenstler.

Konkreter Ablauf des Bugs (nachvollzogen mit den echten Produktionsklassen):
  1. utils/youtube_parser.py::parse_youtube_title() liefert fuer
     "Miksu/Macloud x makko - Nachts wach" den Artist-String bereits
     vor-zerlegt: result["artist"] == "Miksu" (nur artists[0], "Macloud"
     geht als eigenstaendiger Listen-Eintrag verloren).
  2. services/metadata/artist_processor.py::determine_best_artist()
     erhaelt dieses bereits kaputte "Miksu" als parsed_artist - das
     gewinnt laut Prioritaetskette (dominant > parsed > raw > channel)
     GEGEN den korrekten, unzerlegten raw_artist/channel_name
     "Miksu / Macloud" (siehe Live-Log: "raw_artist 'Miksu / Macloud' ==
     uploader/channel -> ignoriert (YT-Parser liefert 'Miksu')").
  3. ArtistNormalizer.normalize("Miksu") hatte VOR diesem Fix keinen
     Override-Treffer und fiel auf Title-Case zurueck -> finaler Artist
     "MIKSU" (Macloud komplett verloren, nicht mal als Feature erhalten).

Der Override-Mechanismus greift schon VOR jeder Pattern-Zerlegung (siehe
ArtistNormalizer._normalize_internal(): Override-Check ist Schritt 1,
Patterns erst danach) und wurde in mapping/artist_overrides.json bereits
fuer die "&"-Schreibweisen genutzt ("miksu & macloud", "miksu&macloud"
-> "Miksu & Macloud") - die Slash-Variante UND die bare-"miksu"-Variante
(die durch den bereits kaputten YT-Parser tatsaechlich als parsed_artist
ankommt) fehlten. Fix: 4 neue Eintraege ("miksu", "miksu / macloud",
"miksu/macloud", "miksu x macloud" -> alle "Miksu & Macloud"), analog zum
bereits etablierten Muster fuer dieses Duo.

Nutzt dieselbe tmp_path-Isolationsstruktur wie
tests/test_artist_overrides_makko_case_preserve.py /
tests/test_artist_overrides_t_low_case_preserve.py.
"""

import json

import pytest

from services.metadata.artist_processor import ArtistProcessor
from utils.artist_map import ArtistConfig, ArtistNormalizer

OVERRIDE_ENTRIES = {
    "miksu": "Miksu & Macloud",
    "miksu & macloud": "Miksu & Macloud",
    "miksu&macloud": "Miksu & Macloud",
    "miksu / macloud": "Miksu & Macloud",
    "miksu/macloud": "Miksu & Macloud",
    "miksu x macloud": "Miksu & Macloud",
}


@pytest.fixture
def library_dir(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


@pytest.fixture
def override_file(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(OVERRIDE_ENTRIES), encoding="utf-8")
    return path


@pytest.fixture
def mapping_dir(tmp_path):
    return tmp_path / "mapping"


@pytest.fixture
def normalizer(library_dir, override_file, mapping_dir):
    return ArtistNormalizer(
        ArtistConfig(
            library_dir=library_dir,
            override_file=override_file,
            mapping_dir=mapping_dir,
        )
    )


class TestMiksuMacloudOverrideMechanism:
    def test_bare_miksu_resolves_to_full_duo_name(self, normalizer):
        assert normalizer.normalize("Miksu") == "Miksu & Macloud"

    def test_slash_variant_with_spaces_resolves_to_full_duo_name(self, normalizer):
        assert normalizer.normalize("Miksu / Macloud") == "Miksu & Macloud"

    def test_slash_variant_without_spaces_resolves_to_full_duo_name(self, normalizer):
        assert normalizer.normalize("Miksu/Macloud") == "Miksu & Macloud"

    def test_x_variant_resolves_to_full_duo_name(self, normalizer):
        assert normalizer.normalize("Miksu x Macloud") == "Miksu & Macloud"


class TestDetermineBestArtistPriorityChainRegression:
    """Reproduziert den echten Live-Fund end-to-end ueber
    ArtistProcessor.determine_best_artist() - nicht nur ueber
    ArtistNormalizer.normalize() isoliert, da der eigentliche Bug erst
    im Zusammenspiel mit der Prioritaetskette (parsed_artist gewinnt vs.
    dem korrekten raw_artist/channel_name) sichtbar wird."""

    def test_broken_parsed_artist_is_corrected_via_override(self, normalizer):
        proc = ArtistProcessor(normalizer)

        artist, source, feat_artists = proc.determine_best_artist(
            raw_artist="Miksu / Macloud",
            parsed_artist="Miksu",  # bereits vom YT-Parser zerlegt (all_artists[0])
            dominant_artist="",
            channel_name="Miksu / Macloud",
        )

        assert artist == "Miksu & Macloud"
        assert source == "youtube_parsed"


class TestRealArtistOverridesFileHasMiksuMacloudEntries:
    """Daten-Integritaetstest gegen die tatsaechlich ausgelieferte
    mapping/artist_overrides.json - schuetzt gegen ein versehentliches
    Entfernen dieser vom Nutzer bestaetigten Korrektur (CLAUDE.md
    Abschnitt 10)."""

    def test_all_expected_variants_are_present_and_correct(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        for key, expected in OVERRIDE_ENTRIES.items():
            assert data.get(key) == expected, f"Override fuer '{key}' fehlt/falsch"
