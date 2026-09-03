"""
Genre-Learning unabhaengig vom Artist-Namens-Override (2026-09-03).

Live-Fund im Anschluss an ARCH-022: AutoLearnManager.learn_genre() blockierte
das Schreiben VOLLSTAENDIG, sobald der Artist in mapping/artist_overrides.json
gelistet war (Artist-NAMENS-Normalisierung, raw_name -> canonical_name) -
unabhaengig davon, ob dieser Artist ueberhaupt ein manuelles Genre in
artist_genre.yaml hat. Verifiziert betraf das 78 von 174 Override-Artists
(u.a. Toobrokeforfiji), die dadurch NIE ein artist-weites Auto-Learn-Genre-
Mapping erhalten konnten, obwohl sie kein manuelles Genre besitzen.

Diese Tests beweisen (Pre-Fix-Diskriminierung, CLAUDE.md Abschnitt 6/26):
zum Zeitpunkt der Testerstellung schlaegt der erste Test hier am
UNVERAENDERTEN Code fehl (learn_genre() liefert False), da der Override-
Block noch aktiv ist. Nach dem Fix (Entfernen des Blocks) ist er gruen.

Der SEPARATE Feature-Artist-Override-Check (_is_artist_known()/
_compute_featured_artist_decision()/observe_featured_artists()) bleibt davon
unberuehrt - siehe test_featured_artist_already_in_overrides_is_skipped in
test_auto_learn_featured_artists_and_genre_aggregation.py (dort als direkte
Regression re-verifiziert, hier NICHT dupliziert).

Verwendet echte Produktionsklassen (AutoLearnManager, ArtistNormalizer,
GenreMapper) und die echte mapping/artist_overrides.json ueber die
mapping_dir_copy-Fixture (CLAUDE.md Abschnitt 7).
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper


def _genre_info(primary, secondary=None, source="lastfm"):
    return SimpleNamespace(
        primary=primary, secondary=list(secondary or []), source=source, raw_tags=[]
    )


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _make_manager(mapping_dir: Path) -> AutoLearnManager:
    config = _Config(mapping_dir)
    artist_config = ArtistConfig(
        library_dir=mapping_dir.parent / "library",
        override_file=mapping_dir / "artist_overrides.json",
        mapping_dir=mapping_dir,
    )
    artist_normalizer = ArtistNormalizer(artist_config)
    genre_mapper = GenreMapper(mapping_dir=mapping_dir)
    return AutoLearnManager(
        config=config, artist_normalizer=artist_normalizer, genre_mapper=genre_mapper
    )


def _run(coro):
    return asyncio.run(coro)


def _read_genre_entry(mapping_dir: Path, artist: str):
    path = mapping_dir / "auto_learned_genre.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f) or {}
    return data.get("ARTIST_GENRE_MAP", {}).get(artist)


def _inject_synthetic_override(mapping_dir, raw_key: str, canonical_value: str):
    """
    Ergaenzt die (bereits per mapping_dir_copy isolierte, tmp_path-lokale)
    Kopie von artist_overrides.json um einen synthetischen Testeintrag.

    Bewusst NICHT von der aktuellen, produktiven artist_overrides.json
    abhaengig (die per Bereinigung in dieser Phase auf 19 Whitelist-Eintraege
    reduziert wurde) - der Test muss unabhaengig davon funktionieren, welche
    konkreten Artists dort gerade gelistet sind. Verwendet weiterhin die
    echten Produktionsklassen (AutoLearnManager/ArtistNormalizer/
    GenreMapper), nur die Testdaten sind gezielt ergaenzt (CLAUDE.md
    Abschnitt 7 betrifft Klassen, nicht Testfixture-Daten).
    """
    path = mapping_dir / "artist_overrides.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f) or {}
    data[raw_key] = canonical_value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


class TestGenreLearningIndependentOfNameOverride:
    TEST_ARTIST = "Testoverrideartist"

    def test_artist_with_only_a_name_override_can_still_learn_a_genre(
        self, mapping_dir_copy
    ):
        """
        Ein Artist mit ausschliesslich einem Namens-Override in
        artist_overrides.json (kein manuelles Genre in artist_genre.yaml)
        muss trotzdem ein Auto-Learn-Genre erhalten koennen - der
        Namens-Override ist ein unabhaengiger Mechanismus (Live-Fund:
        Toobrokeforfiji, hier mit einem synthetischen Testartist
        nachgestellt, damit der Test unabhaengig vom aktuellen Inhalt der
        echten artist_overrides.json bleibt).
        """
        _inject_synthetic_override(
            mapping_dir_copy, "testoverrideartist_raw", self.TEST_ARTIST
        )
        with open(mapping_dir_copy / "artist_genre.yaml", encoding="utf-8") as f:
            import yaml

            manual_genres = yaml.safe_load(f) or {}
        manual_map = manual_genres.get("ARTIST_GENRE_MAP", manual_genres)
        assert self.TEST_ARTIST.lower() not in {
            str(k).lower() for k in manual_map
        }, "Testvoraussetzung: kein manuelles Genre fuer diesen Artist"

        manager = _make_manager(mapping_dir_copy)
        result = _run(
            manager.learn_genre(self.TEST_ARTIST, _genre_info("Deutschrap", ["Hip Hop"]))
        )
        assert result is True, (
            "Genre-Learning darf NICHT allein wegen eines Namens-Overrides "
            "blockiert werden"
        )
        entry = _read_genre_entry(mapping_dir_copy, self.TEST_ARTIST)
        assert entry is not None
        assert entry["primary"] == "Deutschrap"

    def test_override_listed_artist_can_reach_a_locked_genre(self, mapping_dir_copy):
        """End-to-End: der urspruengliche Auftrag - ein Override-Artist soll
        nach 3 konsistenten Beobachtungen ein dauerhaft gelocktes,
        artist-weites Genre erhalten (siehe PR 1, Genre-Lock-in-Regel)."""
        _inject_synthetic_override(
            mapping_dir_copy, "testoverrideartist_raw", self.TEST_ARTIST
        )
        manager = _make_manager(mapping_dir_copy)
        for _ in range(3):
            _run(
                manager.learn_genre(
                    self.TEST_ARTIST, _genre_info("Deutschrap", ["Hip Hop"])
                )
            )
        entry = _read_genre_entry(mapping_dir_copy, self.TEST_ARTIST)
        assert entry["locked_primary"] == "Deutschrap"
        assert entry["primary"] == "Deutschrap"
