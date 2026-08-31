"""
META-04 (docs/archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md, Read-Only-Audit
vom 2026-08-26), Fortsetzung von PHASE 3 (siehe
docs/archive/MusicBot_METADATA_QUALITY_PHASE3_META04_AUDIT.md, dort noch als
offene Rueckfrage markiert): mapping/artist_overrides.json enthielt einen
expliziten Eintrag "t-low": "t-Low" (kleines t, grosses L). Nutzer hat
bestaetigt: die tatsaechliche Eigenschreibweise des Kuenstlers ist
"t-low" (durchgehend kleingeschrieben). Identische Root Cause wie beim
"makko"-Fix (tests/test_artist_overrides_makko_case_preserve.py) - kein
Bug im ArtistNormalizer-Mechanismus selbst, nur ein falscher Override-Wert.

Vor der Korrektur charakterisiert (gegen die echten Mapping-Dateien):
    normalize("t-low"/"t-Low"/"T-Low"/"T-LOW") == "t-Low" (alle Faelle)

Fix: mapping/artist_overrides.json - "t-low": "t-Low" -> "t-low":"t-low".

Nutzt dieselbe tmp_path-Isolationsstruktur wie
tests/test_artist_normalizer.py und tests/test_artist_overrides_makko_case_preserve.py.
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
    path.write_text(json.dumps({"t-low": "t-low"}), encoding="utf-8")
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


class TestTLowCasePreserveOverrideMechanism:
    def test_lowercase_input_stays_lowercase(self, normalizer):
        assert normalizer.normalize("t-low") == "t-low"

    def test_mixed_case_input_is_still_normalized_to_lowercase_override(
        self, normalizer
    ):
        assert normalizer.normalize("t-Low") == "t-low"
        assert normalizer.normalize("T-Low") == "t-low"

    def test_all_caps_input_is_still_normalized_to_lowercase_override(
        self, normalizer
    ):
        assert normalizer.normalize("T-LOW") == "t-low"


class TestRealArtistOverridesFileHasCorrectTLowCasing:
    """Daten-Integritaetstest gegen die tatsaechlich ausgelieferte
    mapping/artist_overrides.json - schuetzt gezielt gegen ein
    versehentliches Zuruecksetzen dieser vom Nutzer bestaetigten
    Korrektur (CLAUDE.md Abschnitt 10)."""

    def test_t_low_override_value_is_fully_lowercase(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("t-low") == "t-low"
