# tests/test_mapping_additions_2026_09_08.py
# -*- coding: utf-8 -*-
"""
Characterization der manuellen Mapping-Ergaenzungen aus Commit d895834
(PR #177, 2026-09-08), die dort ohne eigene Testabdeckung als
"chore(mapping): update metadata mappings" eingecheckt wurden.

CLAUDE.md Abschnitt 10 / 28: YAML-Mapping-Dateien sind Fachlogik -
Aenderungen brauchen konkrete Beispiele (Input -> erwartetes Ergebnis)
und einen Test, der gegen die echten Dateien in mapping/ prueft.

Manuell ergaenzt wurden (jeweils aus Live-Testdownloads deutscher
Pop-Artists abgeleitet):

  mapping/genre_aliases.yaml   "new wave" / "new-wave" / "neue welle" -> "Pop"
  mapping/genre_hierarchy.yaml "Piano Pop" -> Parent "Pop"
  mapping/case_preserve.yaml   "lea" -> "LEA"
  mapping/known_artists.yaml   + LEA, Tom Odell, Unheilig, Xavier Naidoo

Dieser Test bewertet NICHT, ob die Zuordnungen fachlich optimal sind - er
friert das aktuelle Verhalten ein und schuetzt gegen ein versehentliches
Zuruecksetzen der Eintraege.
"""

from pathlib import Path

import pytest
import yaml

from utils.genre_map import GenreMapper

_MAPPING_DIR = Path(__file__).resolve().parent.parent / "mapping"


@pytest.fixture
def genre_mapper(config):
    return GenreMapper(str(config.GENRE_MAPPING_DIR))


# ─────────────────────────────────────────────────────────────────────────
# genre_aliases.yaml — "new wave" und Schreibvarianten -> "Pop"
# ─────────────────────────────────────────────────────────────────────────
class TestNewWaveGenreAlias:
    @pytest.mark.parametrize(
        "raw",
        ["new wave", "New Wave", "new-wave", "neue welle", "Neue Welle"],
    )
    def test_new_wave_variants_normalize_to_pop(self, genre_mapper, raw):
        assert genre_mapper.normalize_genre_name(raw) == "Pop"

    def test_new_wave_alias_is_idempotent(self, genre_mapper):
        once = genre_mapper.normalize_genre_name("new wave")
        assert genre_mapper.normalize_genre_name(once) == once == "Pop"


# ─────────────────────────────────────────────────────────────────────────
# genre_hierarchy.yaml — "Piano Pop" ist ein Pop-Subgenre
# ─────────────────────────────────────────────────────────────────────────
class TestPianoPopHierarchy:
    def test_piano_pop_resolves_to_pop_main_genre(self, genre_mapper):
        assert genre_mapper.get_main_genre("Piano Pop") == "Pop"

    def test_piano_pop_registered_in_hierarchy(self, genre_mapper):
        assert genre_mapper.hierarchy.get("piano pop") == "Pop"


# ─────────────────────────────────────────────────────────────────────────
# case_preserve.yaml — "lea" -> "LEA" (Kuenstlername vollstaendig
# grossgeschrieben)
# ─────────────────────────────────────────────────────────────────────────
class TestLeaCasePreserve:
    def test_lea_entry_present_in_real_case_preserve_file(self):
        data = yaml.safe_load((_MAPPING_DIR / "case_preserve.yaml").read_text("utf-8"))
        assert data["case_preserve"]["lea"] == "LEA"


# ─────────────────────────────────────────────────────────────────────────
# known_artists.yaml — neue Bestandsartists
# ─────────────────────────────────────────────────────────────────────────
class TestKnownArtistsAdditions:
    @pytest.mark.parametrize("name", ["LEA", "Tom Odell", "Unheilig", "Xavier Naidoo"])
    def test_artist_present_in_real_known_artists_file(self, name):
        data = yaml.safe_load((_MAPPING_DIR / "known_artists.yaml").read_text("utf-8"))
        assert name in data["known_artists"]

    def test_known_artists_list_has_no_duplicate_entries(self):
        data = yaml.safe_load((_MAPPING_DIR / "known_artists.yaml").read_text("utf-8"))
        entries = data["known_artists"]
        assert len(entries) == len(set(entries))
