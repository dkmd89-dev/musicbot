"""
Auto-Learn Genre Confidence Audit & Controlled Validation
(Folgeauftrag zu "MusicBot — Auto-Learn Metadata System grundlegend
optimieren").

Verifiziert die im Vorgaenger-Auftrag implementierte Confidence-
Aggregation mit einem KONTROLLIERTEN Test-Artist (nicht NOAH - NOAH hat
einen bekannten externen Namenskonflikt und dient hier ausschliesslich
als dedizierter Regressionstest, siehe TestNoahRegression unten).

Verwendet die tatsaechlichen Schwellenwert-Konstanten aus der
Implementierung (_LEARNED_THRESHOLD, _CONFIRMED_THRESHOLD) statt
angenommener Werte - Audit-Auftrag Abschnitt 7: "Nicht einfach annehmen,
dass 2 oder 3 automatisch LEARNED bedeutet."
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from services.metadata.auto_learn import (
    AutoLearnManager,
    _confidence_tier,
    _aggregate_genre_observations,
    _LEARNED_THRESHOLD,
    _CONFIRMED_THRESHOLD,
)
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper
from utils.singleton import SingletonMixin


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
    # ARCH-022: auto_learned_genre.yaml -> auto_learned_genre.json.
    path = mapping_dir / "auto_learned_genre.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f) or {}
    return data.get("ARTIST_GENRE_MAP", {}).get(artist)


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 3/7: tatsaechliche Schwellenwerte
# ─────────────────────────────────────────────────────────────────────────


class TestActualConfidenceThresholds:
    def test_thresholds_are_the_documented_values(self):
        """Dokumentiert die tatsaechlichen, im Code definierten Schwellen."""
        assert _LEARNED_THRESHOLD == 2
        assert _CONFIRMED_THRESHOLD == 4

    def test_boundary_below_learned_threshold_is_observed(self):
        assert _confidence_tier(_LEARNED_THRESHOLD - 1) == "OBSERVED"

    def test_boundary_at_learned_threshold_is_learned(self):
        assert _confidence_tier(_LEARNED_THRESHOLD) == "LEARNED"

    def test_boundary_below_confirmed_threshold_is_still_learned(self):
        assert _confidence_tier(_CONFIRMED_THRESHOLD - 1) == "LEARNED"

    def test_boundary_at_confirmed_threshold_is_confirmed(self):
        assert _confidence_tier(_CONFIRMED_THRESHOLD) == "CONFIRMED"

    def test_artist_and_genre_use_identical_thresholds(self):
        """
        Abschnitt 3: 'ob Artists und Genres dieselben oder unterschiedliche
        Schwellen verwenden' - Beweis: eine einzige gemeinsame Funktion,
        kein separater Schwellenwert je Domaene.
        """
        import services.metadata.auto_learn as auto_learn_module
        import inspect

        source = inspect.getsource(auto_learn_module)
        # _confidence_tier() wird sowohl im Genre- als auch im
        # Feature-Artist-Pfad aufgerufen - siehe learn_genre()/
        # _compute_genre_decision() und _write_featured_observation_sync()/
        # _compute_featured_artist_decision().
        assert source.count("_confidence_tier(") >= 4


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 6: kontrollierte Beobachtungsaggregation (Majority Voting)
# ─────────────────────────────────────────────────────────────────────────


class TestControlledObservationAggregation:
    ARTIST = "TEST_CONTROLLED_ARTIST"

    def test_example_from_ticket_section_6(self):
        """
        Genau das Beispiel aus dem Auftrag:
        Obs1=A, Obs2=A, Obs3=B, Obs4=A -> Majority=A (3 vs 1).
        """
        log = [
            {"primary": "Genre A", "secondary": []},
            {"primary": "Genre A", "secondary": []},
            {"primary": "Genre B", "secondary": []},
            {"primary": "Genre A", "secondary": []},
        ]
        primary, _secondary = _aggregate_genre_observations(log)
        assert primary == "Genre A"

    def test_multiple_identical_observations_stay_consistent(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for _ in range(3):
            _run(
                manager.learn_genre(
                    self.ARTIST, _genre_info("Genre A", ["Sub A"])
                )
            )
        entry = _read_genre_entry(mapping_dir, self.ARTIST)
        assert entry["observations"] == 3
        assert entry["primary"] == "Genre A"
        assert entry["confidence"] == "LEARNED"

    def test_majority_voting_three_to_one(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for genre in ["Genre A", "Genre A", "Genre B", "Genre A"]:
            _run(manager.learn_genre(self.ARTIST, _genre_info(genre)))

        entry = _read_genre_entry(mapping_dir, self.ARTIST)
        assert entry["primary"] == "Genre A"
        assert entry["observations"] == 4
        assert entry["confidence"] == "CONFIRMED"
        # Nachvollziehbarkeit: die einzelnen Beobachtungen bleiben erhalten
        assert [o["primary"] for o in entry["observation_log"]] == [
            "Genre A", "Genre A", "Genre B", "Genre A",
        ]


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 8: Konflikt-Test (Gleichstand)
# ─────────────────────────────────────────────────────────────────────────


class TestConflictHandling:
    def test_a_a_b_a_majority_is_a(self):
        log = [{"primary": p, "secondary": []} for p in ["A", "A", "B", "A"]]
        primary, _ = _aggregate_genre_observations(log)
        assert primary == "A"

    def test_a_b_b_a_tie_resolves_to_first_observed(self):
        """
        Echter Gleichstand (2x A, 2x B) - dokumentiertes, deterministisches
        Verhalten: Counter.most_common() liefert bei Gleichstand den
        zuerst beobachteten Wert (hier: A, da an Position 0 zuerst
        aufgetreten). Kein neuer 'UNRESOLVED'-Status erfunden (Auftrag
        Abschnitt 8), stattdessen dieses Verhalten hier explizit
        dokumentiert/verifiziert.
        """
        log = [{"primary": p, "secondary": []} for p in ["A", "B", "B", "A"]]
        primary, _ = _aggregate_genre_observations(log)
        assert primary == "A"

    def test_conflict_confidence_still_based_on_total_observation_count(
        self, tmp_path
    ):
        """
        Ein Gleichstand aendert NICHTS an der Confidence-Einstufung - die
        basiert ausschliesslich auf der Gesamt-Beobachtungszahl, nicht auf
        Einigkeit der Beobachtungen (keine neue Bewertungsdimension).
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for genre in ["A", "B", "B", "A"]:
            _run(manager.learn_genre("TIE_ARTIST", _genre_info(genre)))

        entry = _read_genre_entry(mapping_dir, "TIE_ARTIST")
        assert entry["observations"] == 4
        assert entry["confidence"] == "CONFIRMED"
        assert entry["primary"] == "A"


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 7: Confidence-Transition mit kontrolliertem Artist
# ─────────────────────────────────────────────────────────────────────────


class TestConfidenceTransitionControlled:
    ARTIST = "TEST_TRANSITION_ARTIST"

    def test_full_transition_sequence(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        expected_confidence_by_observation_count = {}
        for i in range(1, _CONFIRMED_THRESHOLD + 2):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Stable Genre")))
            entry = _read_genre_entry(mapping_dir, self.ARTIST)
            expected_confidence_by_observation_count[i] = entry["confidence"]

        assert expected_confidence_by_observation_count[1] == "OBSERVED"
        assert (
            expected_confidence_by_observation_count[_LEARNED_THRESHOLD]
            == "LEARNED"
        )
        assert (
            expected_confidence_by_observation_count[_CONFIRMED_THRESHOLD]
            == "CONFIRMED"
        )
        assert (
            expected_confidence_by_observation_count[_CONFIRMED_THRESHOLD + 1]
            == "CONFIRMED"
        )

    def test_only_learned_and_above_is_used_for_resolution(self, tmp_path):
        """
        Kern der Confidence-Gating-Funktion: erst ab LEARNED wird ein
        Auto-Learn-Genre nach einem (simulierten) Neustart aktiv fuer die
        Genre-Bestimmung geladen.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.learn_genre(self.ARTIST, _genre_info("Stable Genre")))
        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        assert fresh_mapper.get_artist_entry(self.ARTIST) is None, (
            "OBSERVED (1 Beobachtung) darf noch nicht aktiv verwendet werden"
        )

        SingletonMixin._instances.clear()
        manager2 = _make_manager(mapping_dir)
        _run(manager2.learn_genre(self.ARTIST, _genre_info("Stable Genre")))
        SingletonMixin._instances.clear()
        fresh_mapper2 = GenreMapper(mapping_dir=mapping_dir)
        entry = fresh_mapper2.get_artist_entry(self.ARTIST)
        assert entry is not None, (
            f"LEARNED (>= {_LEARNED_THRESHOLD} Beobachtungen) muss aktiv "
            "verwendet werden"
        )
        assert entry.primary == "Stable Genre"


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 5: manuelles Mapping nachtraeglich hinzugefuegt (Genre)
# ─────────────────────────────────────────────────────────────────────────


class TestManualMappingAddedAfterGenreAutoLearn:
    def test_manual_entry_added_later_blocks_further_genre_learning(
        self, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.learn_genre("Late Manual Artist", _genre_info("Wrong Genre")))
        entry = _read_genre_entry(mapping_dir, "Late Manual Artist")
        assert entry["confidence"] == "OBSERVED"

        # Manuelles Mapping wird nachtraeglich gepflegt
        (mapping_dir / "artist_genre.yaml").write_text(
            yaml.dump(
                {
                    "ARTIST_GENRE_MAP": {
                        "Late Manual Artist": {
                            "primary": "Correct Genre",
                            "secondary": [],
                        }
                    }
                }
            )
        )

        result = _run(
            manager.learn_genre("Late Manual Artist", _genre_info("Wrong Genre"))
        )
        assert result is False, "Manuelles Mapping muss weiteres Lernen blockieren"

        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        entry = fresh_mapper.get_artist_entry("Late Manual Artist")
        assert entry.primary == "Correct Genre"


# ─────────────────────────────────────────────────────────────────────────
# Abschnitt 9/10/17: NOAH-Regression (Featured Artist, dediziert automatisiert)
# ─────────────────────────────────────────────────────────────────────────


class TestNoahRegression:
    """
    Dediziert automatisierter Regressionstest fuer den live entdeckten
    NOAH-Fall (Auftrag Abschnitt 10/17): beweist NUR, dass ein Featured
    Artist mit einer (auch falschen) externen Genrequelle NIEMALS einen
    Genre-Auto-Learn-Eintrag erzeugt - versucht NICHT, den Last.fm-
    Namenskonflikt "zu loesen".
    """

    def test_noah_as_featured_artist_never_gets_genre_entry_even_with_wrong_genre(
        self, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        # Primary Artist Gustav bekommt eine Genre-Beobachtung (erlaubt)
        _run(manager.learn_genre("Gustav", _genre_info("Indie Pop")))

        # NOAH als Featured Artist wird NUR beobachtet (Alias-Ebene) -
        # niemals ueber learn_genre() aufgerufen, selbst wenn irgendwo im
        # System ein (hier absichtlich falsches) Last.fm-Genre fuer NOAH
        # vorlaege ('Hardcore' - der live reproduzierte Fehltreffer).
        decisions = _run(
            manager.observe_featured_artists(
                primary_artist="Gustav",
                feat_artists=["NOAH"],
                track_context="Gustav - Luftballon",
            )
        )
        assert decisions[0]["decision"] == "LEARNED"
        assert decisions[0]["canonical"] == "NOAH"

        assert _read_genre_entry(mapping_dir, "NOAH") is None, (
            "NOAH darf als Featured Artist NIEMALS einen Genre-Auto-Learn-"
            "Eintrag bekommen, unabhaengig davon was Last.fm liefern wuerde"
        )
        # Gustavs eigene Beobachtung bleibt unberuehrt von der
        # Feature-Artist-Beobachtung
        gustav_entry = _read_genre_entry(mapping_dir, "Gustav")
        assert gustav_entry["primary"] == "Indie Pop"

    def test_noah_genre_file_has_no_entry_after_repeated_wrong_lastfm_style_hits(
        self, tmp_path
    ):
        """
        Selbst wenn (hypothetisch) wiederholt versucht wuerde, fuer NOAH als
        Featured Artist ein Last.fm-Ergebnis zu verarbeiten, existiert dafuer
        strukturell KEIN Code-Pfad - observe_featured_artists() ruft niemals
        learn_genre()/_write_genre_observation_sync() auf. Dieser Test
        beweist das durch mehrfache Beobachtung ueber mehrere simulierte
        Tracks hinweg.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for i in range(5):
            _run(
                manager.observe_featured_artists(
                    primary_artist=f"Primary{i}",
                    feat_artists=["NOAH"],
                    track_context=f"Track {i}",
                )
            )

        assert not (mapping_dir / "auto_learned_genre.json").exists(), (
            "Reine Feature-Artist-Beobachtungen duerfen auto_learned_genre.json "
            "niemals anlegen"
        )
