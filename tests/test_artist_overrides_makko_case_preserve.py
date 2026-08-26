"""
META-04 (docs/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md, Read-Only-Audit
vom 2026-08-26): case-sensitive Artist-Ordner-Duplikate in der realen
Library (makko/Makko, t-Low/T-Low). Root Cause fuer den Fall "makko" war
KEIN Bug im ArtistNormalizer-Mechanismus selbst - der Fallback auf
Title-Case fuer unbekannte Namen (_normalize_rest()'s .capitalize(),
bereits durch tests/test_artist_normalizer.py::
test_plain_lowercase_name_falls_back_to_title_case charakterisiert) ist
bewusstes, an vielen Stellen bewaehrtes Verhalten. Der eigentliche Fehler
war ein falscher Eintrag in mapping/artist_overrides.json: "makko" wurde
explizit auf "Makko" (grossgeschrieben) gemappt, obwohl "makko" laut
Nutzerbestaetigung sein tatsaechlicher, bewusst kleingeschriebener
Kuenstlername ist. Dieser Override ueberschreibt fuer JEDEN Download
(unabhaengig von der im YouTube-Titel/Kanalnamen vorkommenden
Gross-/Kleinschreibung) den Case-Preserve-Mechanismus und erzeugte so
konsistent "Makko"-Ordner - die vorhandene "makko"-Library-Instanz (1
Album) muss vor der Korrektur dieses Overrides entstanden sein (Altlast).

Vor der Korrektur charakterisiert (gegen die echten Mapping-Dateien):
    normalize("makko") == "Makko"   (alle Case-Varianten des Inputs)

Fix: mapping/artist_overrides.json - "makko": "Makko" -> "makko":"makko".

Nutzt dieselbe tmp_path-Isolationsstruktur wie
tests/test_artist_normalizer.py (siehe dortiger Modul-Docstring fuer die
Begruendung: ArtistConfig.mapping_dir IMMER explizit setzen, sonst wuerden
Tests das echte mapping/-Verzeichnis lesen/beschreiben).
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
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"makko": "makko"}), encoding="utf-8")
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


class TestMakkoCasePreserveOverrideMechanism:
    """Mechanismus-Test (isoliert, echtes mapping/ unberuehrt): ein
    Override mit kleingeschriebenem Zielwert wird case-insensitiv
    gegenueber dem Input respektiert, statt vom .capitalize()-Fallback
    ueberschrieben zu werden."""

    def test_lowercase_input_stays_lowercase(self, normalizer):
        assert normalizer.normalize("makko") == "makko"

    def test_capitalized_input_is_still_normalized_to_lowercase_override(
        self, normalizer
    ):
        assert normalizer.normalize("Makko") == "makko"

    def test_all_caps_input_is_still_normalized_to_lowercase_override(
        self, normalizer
    ):
        assert normalizer.normalize("MAKKO") == "makko"


class TestRealArtistOverridesFileHasCorrectMakkoCasing:
    """Daten-Integritaetstest gegen die tatsaechlich ausgelieferte
    mapping/artist_overrides.json - schuetzt gezielt gegen ein
    versehentliches Zuruecksetzen dieser vom Nutzer bestaetigten
    Korrektur (CLAUDE.md Abschnitt 10: Mapping-Aenderungen wie
    Codeaenderungen behandeln)."""

    def test_makko_override_value_is_lowercase(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("makko") == "makko"
