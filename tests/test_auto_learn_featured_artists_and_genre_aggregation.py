"""
Auto-Learn Metadata System - Feature-Artist-Beobachtung + Genre-Observation-
Aggregation (Auto-Learn-Auftrag "MusicBot — Auto-Learn Metadata System
grundlegend optimieren").

Deckt Abschnitt 23 des Auftrags ab:

Artist:
  unknown/known featured artist, multiple featured artists, artist
  normalization, case preservation, manual override wins, auto-learn
  does not overwrite manual mapping, observation aggregation,
  duplicate observation.

Genre:
  unknown/known artist genre, manual artist genre wins, auto-learn genre,
  multiple/conflicting genre observations, genre confidence,
  feature artist does not inherit genre incorrectly.

Safety:
  dry-run, no production writes (reine Mapping-Datei-Isolation ueber
  tmp_path/mapping_dir_copy - echtes mapping/ bleibt unberuehrt),
  mapping persistence, mapping reload.

Verwendet echte Produktionsklassen (AutoLearnManager, ArtistNormalizer,
GenreMapper) statt Nachbauten (CLAUDE.md Abschnitt 7).
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from services.metadata.auto_learn import (
    AutoLearnManager,
    _confidence_tier,
    _aggregate_genre_observations,
)
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper


def _genre_info(primary, secondary=None, source="lastfm"):
    return SimpleNamespace(
        primary=primary, secondary=list(secondary or []), source=source, raw_tags=[]
    )


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _make_manager(mapping_dir: Path, library_dir: Path | None = None) -> AutoLearnManager:
    config = _Config(mapping_dir)
    artist_config = ArtistConfig(
        library_dir=library_dir or (mapping_dir.parent / "library"),
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


# ─────────────────────────────────────────────────────────────────────────
# Confidence-Tier / Aggregations-Helper (reine Funktionen, Abschnitt 17)
# ─────────────────────────────────────────────────────────────────────────


class TestConfidenceTier:
    def test_single_observation_is_observed(self):
        assert _confidence_tier(1) == "OBSERVED"

    def test_two_to_three_observations_is_learned(self):
        assert _confidence_tier(2) == "LEARNED"
        assert _confidence_tier(3) == "LEARNED"

    def test_four_plus_observations_is_confirmed(self):
        assert _confidence_tier(4) == "CONFIRMED"
        assert _confidence_tier(50) == "CONFIRMED"

    def test_zero_observations_is_observed_not_negative(self):
        """Randfall: 0 Beobachtungen darf nicht crashen/negativ werden."""
        assert _confidence_tier(0) == "OBSERVED"


class TestGenreObservationAggregation:
    def test_majority_vote_picks_most_frequent_primary(self):
        """Abschnitt 12: 'last value wins' ist explizit verboten - Mehrheit gewinnt."""
        log = [
            {"primary": "Deutschpop", "secondary": ["Pop"]},
            {"primary": "Pop", "secondary": ["Hip Hop"]},
            {"primary": "Deutschpop", "secondary": ["Hip Hop", "Pop"]},
        ]
        primary, secondary = _aggregate_genre_observations(log)
        assert primary == "Deutschpop"
        # Pop/Hip Hop beide 2x beobachtet, duerfen nicht im Primary auftauchen
        assert primary not in secondary

    def test_empty_log_returns_empty(self):
        assert _aggregate_genre_observations([]) == ("", [])

    def test_secondary_capped_at_five(self):
        log = [
            {"primary": "Pop", "secondary": [f"Genre{i}" for i in range(10)]}
        ]
        _primary, secondary = _aggregate_genre_observations(log)
        assert len(secondary) <= 5


# ─────────────────────────────────────────────────────────────────────────
# Feature-Artist-Beobachtung
# ─────────────────────────────────────────────────────────────────────────


class TestFeaturedArtistObservation:
    def test_unknown_featured_artist_would_learn_in_dry_run(self, tmp_path):
        """Dry-Run: identische Entscheidung wie live, aber kein Schreiben (Abschnitt 21)."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        decisions = manager.preview_featured_artists(
            primary_artist="Gustav", feat_artists=["Noah"], track_context="Gustav - Luftballon"
        )

        assert len(decisions) == 1
        d = decisions[0]
        assert d["decision"] == "WOULD_LEARN"
        assert d["role"] == "featured_artist"
        assert d["predicted_observations"] == 1
        assert d["predicted_confidence"] == "OBSERVED"

        auto_file = mapping_dir / "auto_learned_featured_artists.yaml"
        assert not auto_file.exists(), "Dry-Run darf NICHTS schreiben"

    def test_unknown_featured_artist_gets_learned_live(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        decisions = _run(
            manager.observe_featured_artists(
                primary_artist="Gustav",
                feat_artists=["Noah"],
                track_context="Gustav - Luftballon",
            )
        )

        assert decisions[0]["decision"] == "LEARNED"
        auto_file = mapping_dir / "auto_learned_featured_artists.yaml"
        assert auto_file.exists()
        with open(auto_file) as f:
            data = yaml.safe_load(f)
        entry = data["featured_artists"]["Noah"]
        assert entry["role"] == "featured_artist"
        assert entry["observations"] == 1
        assert entry["status"] == "OBSERVED"
        assert entry["primary_artists"] == ["Gustav"]

    def test_multiple_featured_artists_produce_multiple_decisions(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        decisions = _run(
            manager.observe_featured_artists(
                primary_artist="GReeeN",
                feat_artists=["1986zig", "Sido"],
                track_context="GReeeN - Track",
            )
        )
        assert len(decisions) == 2
        assert {d["decision"] for d in decisions} == {"LEARNED"}
        with open(mapping_dir / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        assert set(data["featured_artists"].keys()) == {"1986zig", "Sido"}

    def test_observation_aggregation_across_multiple_calls(self, tmp_path):
        """Abschnitt 7: mehrere Beobachtungen desselben Artists werden zusammengefuehrt."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.observe_featured_artists("Gustav", ["Noah"], "Track 1"))
        _run(manager.observe_featured_artists("Anderer Artist", ["Noah"], "Track 2"))
        decisions = _run(manager.observe_featured_artists("Dritter", ["Noah"], "Track 3"))

        assert decisions[0]["decision"] == "UPDATED"
        assert decisions[0]["predicted_observations"] == 3
        assert decisions[0]["predicted_confidence"] == "LEARNED"

        with open(mapping_dir / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        entry = data["featured_artists"]["Noah"]
        assert entry["observations"] == 3
        assert entry["status"] == "LEARNED"
        assert sorted(entry["primary_artists"]) == ["Anderer Artist", "Dritter", "Gustav"]

    def test_duplicate_observation_same_primary_still_counts(self, tmp_path):
        """Duplicate Observation: gleicher Primary+Feature mehrfach - observations steigt trotzdem."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.observe_featured_artists("Gustav", ["Noah"], "Track 1"))
        decisions = _run(manager.observe_featured_artists("Gustav", ["Noah"], "Track 1 Remix"))

        assert decisions[0]["predicted_observations"] == 2
        with open(mapping_dir / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        # Gustav darf trotz zweifacher Beobachtung nur EINMAL in primary_artists stehen
        assert data["featured_artists"]["Noah"]["primary_artists"] == ["Gustav"]

    def test_confidence_reaches_confirmed_after_four_observations(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for i in range(4):
            decisions = _run(
                manager.observe_featured_artists(f"Primary{i}", ["Noah"], f"Track {i}")
            )
        assert decisions[0]["predicted_confidence"] == "CONFIRMED"

    def test_case_variants_of_featured_artist_are_normalized_via_case_preserve(
        self, mapping_dir_copy
    ):
        """
        Abschnitt 9: case_preserve.yaml (echtes mapping/) enthaelt bereits
        'noah: NOAH' - Auto-Learn MUSS das verwenden statt roh 'Noah' zu
        lernen.
        """
        manager = _make_manager(mapping_dir_copy)

        decisions = _run(
            manager.observe_featured_artists("Gustav", ["Noah"], "Gustav - Luftballon")
        )
        assert decisions[0]["canonical"] == "NOAH"

        with open(mapping_dir_copy / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        assert "NOAH" in data["featured_artists"]
        assert "Noah" not in data["featured_artists"]

    def test_featured_artist_already_in_overrides_is_skipped(self, mapping_dir_copy):
        """
        Abschnitt 10: manuelle Mappings gewinnen immer. 'gustav' ist bereits
        in artist_overrides.json - als Feature-Artist eines ANDEREN Primary
        darf dafuer kein Auto-Learn-Eintrag entstehen.
        """
        manager = _make_manager(mapping_dir_copy)

        decisions = _run(
            manager.observe_featured_artists("Irgendwer", ["Gustav"], "Track")
        )
        assert decisions[0]["decision"] == "SKIPPED_KNOWN"

        auto_file = mapping_dir_copy / "auto_learned_featured_artists.yaml"
        if auto_file.exists():
            with open(auto_file) as f:
                data = yaml.safe_load(f) or {}
            assert "Gustav" not in data.get("featured_artists", {})

    def test_auto_learn_does_not_overwrite_manual_mapping_added_later(
        self, mapping_dir_copy
    ):
        """
        Abschnitt 10: wird ein zuvor gelernter Feature-Artist SPAETER manuell
        in artist_overrides.json definiert, darf eine erneute Beobachtung
        keinen widerspruechlichen/konkurrierenden Zustand mehr erzeugen -
        die naechste Beobachtung wird geskippt statt weiter zu aggregieren.
        """
        manager = _make_manager(mapping_dir_copy)

        # 1. Zunaechst unbekannt -> wird gelernt
        first = _run(
            manager.observe_featured_artists("Gustav", ["Ganz Neuer Artist"], "Track 1")
        )
        assert first[0]["decision"] == "LEARNED"

        # 2. Jetzt manuell nachtragen (simuliert spaetere manuelle Pflege)
        overrides_file = mapping_dir_copy / "artist_overrides.json"
        import json

        with open(overrides_file) as f:
            overrides = json.load(f)
        overrides["ganz neuer artist"] = "Ganz Neuer Artist"
        with open(overrides_file, "w") as f:
            json.dump(overrides, f)

        # Neuer Manager (frischer Prozess-Neustart-aequivalent, damit die
        # Override-Datei tatsaechlich neu geladen wird - kein Live-Reload
        # mitten im Lauf, Abschnitt 20). ArtistNormalizer/GenreMapper sind
        # SingletonMixin-basiert - der Instanzcache muss explizit geleert
        # werden, um einen echten Prozess-Neustart zu simulieren (sonst
        # liefert ArtistNormalizer(...) die alte, bereits konstruierte
        # Instanz mit der VORHER eingelesenen artist_overrides.json zurueck).
        from utils.singleton import SingletonMixin

        SingletonMixin._instances.clear()
        manager2 = _make_manager(mapping_dir_copy)
        second = _run(
            manager2.observe_featured_artists("Anderer", ["Ganz Neuer Artist"], "Track 2")
        )
        assert second[0]["decision"] == "SKIPPED_KNOWN"

    def test_feature_artist_observation_never_writes_genre_file(self, tmp_path):
        """
        Abschnitt 16: ein Feature-Artist darf NIEMALS automatisch das Genre
        des Primary-Artists erben/lernen - observe_featured_artists() darf
        auto_learned_genre.yaml gar nicht erst beruehren.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(
            manager.observe_featured_artists(
                "Gustav", ["Noah"], "Gustav - Luftballon"
            )
        )
        assert not (mapping_dir / "auto_learned_genre.yaml").exists()


# ─────────────────────────────────────────────────────────────────────────
# Genre-Auto-Learn / Aggregation
# ─────────────────────────────────────────────────────────────────────────


class TestGenreAutoLearnAggregation:
    def test_unknown_artist_genre_would_learn_in_dry_run(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        decision = manager.preview_genre_learning(
            "Neuer Artist", _genre_info("Pop", ["Electronic"])
        )
        assert decision["decision"] == "WOULD_LEARN"
        assert decision["predicted_observations"] == 1
        assert not (mapping_dir / "auto_learned_genre.yaml").exists()

    def test_unknown_artist_genre_learned_live(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        result = _run(
            manager.learn_genre("Neuer Artist", _genre_info("Pop", ["Electronic"]))
        )
        assert result is True
        with open(mapping_dir / "auto_learned_genre.yaml") as f:
            data = yaml.safe_load(f)
        entry = data["ARTIST_GENRE_MAP"]["Neuer Artist"]
        assert entry["primary"] == "Pop"
        assert entry["observations"] == 1
        assert entry["confidence"] == "OBSERVED"

    def test_manual_artist_genre_blocks_auto_learn_permanently(self, mapping_dir_copy):
        """Abschnitt 13/14: 'gustav' ist in artist_genre.yaml manuell gepflegt."""
        manager = _make_manager(mapping_dir_copy)

        decision = manager.preview_genre_learning(
            "gustav", _genre_info("Voellig Anderes Genre")
        )
        assert decision["decision"] == "BLOCKED_MANUAL"

        result = _run(manager.learn_genre("gustav", _genre_info("Voellig Anderes Genre")))
        assert result is False

        auto_file = mapping_dir_copy / "auto_learned_genre.yaml"
        if auto_file.exists():
            with open(auto_file) as f:
                data = yaml.safe_load(f) or {}
            assert "gustav" not in {k.lower() for k in data.get("ARTIST_GENRE_MAP", {})}

    def test_multiple_consistent_observations_reach_confirmed(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for _ in range(4):
            result = _run(
                manager.learn_genre(
                    "Nina Chuba", _genre_info("Deutschrap", ["Pop Rap", "R&B"])
                )
            )
        assert result is True
        with open(mapping_dir / "auto_learned_genre.yaml") as f:
            data = yaml.safe_load(f)
        entry = data["ARTIST_GENRE_MAP"]["Nina Chuba"]
        assert entry["observations"] == 4
        assert entry["confidence"] == "CONFIRMED"
        assert entry["primary"] == "Deutschrap"

    def test_conflicting_genre_observations_use_majority_vote_not_last_value(
        self, tmp_path
    ):
        """
        Abschnitt 11/12: 'last value wins' ist explizit verboten. 2x
        Deutschpop, 1x Pop -> Ergebnis muss Deutschpop bleiben, obwohl Pop
        die zuletzt geschriebene Beobachtung war.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.learn_genre("Nina Chuba", _genre_info("Deutschpop", ["Pop"])))
        _run(manager.learn_genre("Nina Chuba", _genre_info("Deutschpop", ["Hip Hop"])))
        _run(manager.learn_genre("Nina Chuba", _genre_info("Pop", ["Hip Hop"])))

        with open(mapping_dir / "auto_learned_genre.yaml") as f:
            data = yaml.safe_load(f)
        entry = data["ARTIST_GENRE_MAP"]["Nina Chuba"]
        assert entry["primary"] == "Deutschpop", (
            "last value wins waere hier faelschlich 'Pop' - Mehrheitsvotum "
            "muss 'Deutschpop' (2x beobachtet) liefern"
        )
        assert entry["observations"] == 3

    def test_single_observation_is_not_yet_trusted_for_resolution(self, tmp_path):
        """
        AUTOLEARN-GENRE-TRUST: ein Auto-Learn-Eintrag mit nur einer
        Beobachtung (confidence OBSERVED) darf NICHT sofort in die aktive
        artist_map gemerged werden - ein einzelner fehlerhafter Treffer
        (z.B. Namenskollision mit einem gleichnamigen, anderen Kuenstler)
        soll noch keine zukuenftige Genre-Bestimmung beeinflussen koennen.
        Live-Fund: 'NOAH' traf per Last.fm/MusicBrainz faelschlich einen
        gleichnamigen, voellig anderen Kuenstler ('Hardcore' statt
        tatsaechlich 'Deutschrap').
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.learn_genre("Nina Chuba", _genre_info("Deutschrap", ["Pop"])))

        from utils.singleton import SingletonMixin

        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        assert fresh_mapper.get_artist_entry("Nina Chuba") is None, (
            "Eine einzelne, unbestaetigte Beobachtung darf noch nicht aktiv "
            "fuer die Genre-Bestimmung verwendet werden"
        )

    def test_genre_persists_and_reloads_correctly_once_learned(self, tmp_path):
        """
        Mapping Persistence + Reload: erst ab confidence LEARNED (>= 2
        konsistente Beobachtungen) wird ein Auto-Learn-Genre nach Neustart
        (neuer GenreMapper) aktiv fuer die Genre-Bestimmung geladen.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        _run(manager.learn_genre("Nina Chuba", _genre_info("Deutschrap", ["Pop"])))
        _run(manager.learn_genre("Nina Chuba", _genre_info("Deutschrap", ["Pop", "Hip Hop"])))

        # GenreMapper ist SingletonMixin-basiert - Instanzcache leeren, um
        # einen echten Neustart (neu von Disk laden) zu simulieren, statt
        # die bereits konstruierte, veraltete Instanz zurueckzubekommen.
        from utils.singleton import SingletonMixin

        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        entry = fresh_mapper.get_artist_entry("Nina Chuba")
        assert entry is not None
        assert entry.primary == "Deutschrap"

    def test_manual_mapping_always_wins_over_reloaded_auto_learn(self, tmp_path):
        """
        Reload-Priorisierung: liegt fuer denselben Artist SOWOHL ein
        manueller ALS AUCH ein Auto-Learn-Eintrag vor, muss der GELADENE
        GenreMapper den manuellen liefern (Abschnitt 2/13).
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        (mapping_dir / "artist_genre.yaml").write_text(
            yaml.dump(
                {"ARTIST_GENRE_MAP": {"Nina Chuba": {"primary": "Hip Hop", "secondary": []}}}
            )
        )
        manager = _make_manager(mapping_dir)
        # Direkter Low-Level-Schreibzugriff (umgeht den manuellen Block bewusst
        # nicht - simuliert nur eine VOR dem manuellen Eintrag bereits
        # bestehende Auto-Learn-Historie).
        manager._write_genre_observation_sync(
            mapping_dir / "auto_learned_genre.yaml", "Nina Chuba", "Pop", []
        )

        from utils.singleton import SingletonMixin

        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        entry = fresh_mapper.get_artist_entry("Nina Chuba")
        assert entry.primary == "Hip Hop"


# ─────────────────────────────────────────────────────────────────────────
# Isolierter End-to-End-Testfall (Abschnitt 24): Gustav feat. Noah
# ─────────────────────────────────────────────────────────────────────────


class TestGustavLuftballonScenario:
    """
    Reproduziert den konkreten Testfall aus Abschnitt 24 auf Unit-Test-Ebene
    (echte mapping/-Daten via mapping_dir_copy-Fixture): Primary=Gustav
    (bereits bekannt), Featured=Noah (bislang unbekannt).
    """

    def test_gustav_primary_noah_featured_full_flow(self, mapping_dir_copy):
        # ARCH-022: auto_learned_artists.yaml wurde in zwei Dateien
        # aufgeteilt - auto_learned_artist_aliases.yaml (Channel-Aliase)
        # und auto_learned_featured_artists.yaml (Feature-Artist-
        # Beobachtungen). mapping_dir_copy kopiert die echten mapping/-
        # Dateien 1:1, enthaelt also bereits beide neuen Dateien.
        with open(mapping_dir_copy / "auto_learned_artist_aliases.yaml") as f:
            original_channel_aliases = yaml.safe_load(f)["auto_learned"]

        manager = _make_manager(mapping_dir_copy)

        # Vorbedingung wie im Auftrag beschrieben: Noah ist nirgends bekannt
        assert not manager._is_artist_known("Noah")
        assert not manager._is_genre_manually_defined("Noah")

        # Primary-Genre wird wie gewohnt fuer Gustav gelernt (waere hier
        # ohnehin durch artist_genre.yaml manuell blockiert, siehe Test oben) -
        # der eigentliche Fokus ist die Feature-Artist-Beobachtung:
        decisions = _run(
            manager.observe_featured_artists(
                primary_artist="Gustav",
                feat_artists=["Noah"],
                track_context="Gustav - Luftballon",
            )
        )

        assert len(decisions) == 1
        d = decisions[0]
        assert d["canonical"] == "NOAH"  # case_preserve.yaml: noah -> NOAH
        assert d["role"] == "featured_artist"
        assert d["decision"] == "LEARNED"
        assert d["predicted_observations"] == 1
        assert d["predicted_confidence"] == "OBSERVED"

        with open(mapping_dir_copy / "auto_learned_featured_artists.yaml") as f:
            data = yaml.safe_load(f)
        noah_entry = data["featured_artists"]["NOAH"]
        assert noah_entry["primary_artists"] == ["Gustav"]

        # Kein Genre wurde fuer Noah gelernt (Abschnitt 16)
        genre_file = mapping_dir_copy / "auto_learned_genre.yaml"
        if genre_file.exists():
            with open(genre_file) as f:
                gdata = yaml.safe_load(f) or {}
            assert "NOAH" not in gdata.get("ARTIST_GENRE_MAP", {})
            assert "Noah" not in gdata.get("ARTIST_GENRE_MAP", {})

        # Bestehende Channel-Alias-Eintraege bleiben von der Feature-
        # Artist-Beobachtung unberuehrt - jetzt sogar physisch garantiert
        # (eigene Datei statt nur eigener Key in derselben Datei).
        with open(mapping_dir_copy / "auto_learned_artist_aliases.yaml") as f:
            aliases_after = yaml.safe_load(f)["auto_learned"]
        assert aliases_after == original_channel_aliases


# ─────────────────────────────────────────────────────────────────────────
# ARCH-022 — Testluecke: Namespace-Trennung in auto_learned_artists.yaml
# ─────────────────────────────────────────────────────────────────────────
#
# auto_learned_artists.yaml vermischt zwei komplett getrennte Namespaces:
# Top-Level-Key "auto_learned" (Channel-Alias-Learning, geschrieben von
# AutoLearnManager.learn_artist()/_save_alias() UND gelesen von
# utils/artist_map.py::ArtistNormalizer) und Top-Level-Key
# "featured_artists" (Feature-Artist-Beobachtungen, geschrieben von
# AutoLearnManager.observe_featured_artists()). Der Test oben
# (test_gustav_primary_noah_featured_full_flow) deckt bereits eine
# Richtung ab (featured_artists-Schreiben laesst auto_learned
# unveraendert) - hier die bisher fehlende umgekehrte Richtung.


class TestAutoLearnedArtistsNamespaceSeparation:
    """
    ARCH-022: auto_learned_artists.yaml wurde in zwei physisch getrennte
    Dateien aufgeteilt (auto_learned_artist_aliases.yaml fuer
    Channel-Aliase, auto_learned_featured_artists.yaml fuer
    Feature-Artist-Beobachtungen) - vorher zwei Top-Level-Keys in
    derselben Datei. Diese Tests bleiben trotzdem sinnvoll: sie
    garantieren, dass ein Schreibvorgang in der einen Datei die andere
    nicht veraendert (z.B. falls ein zukuenftiger Bug versehentlich den
    falschen Dateinamen verwendet oder beide Schreibpfade eine gemeinsame
    Variable teilen wuerden).
    """

    def test_auto_learned_alias_write_does_not_touch_featured_artists_file(
        self, tmp_path
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        # Vorbedingung: featured_artists-Datei ist bereits befuellt.
        _run(
            manager.observe_featured_artists(
                primary_artist="Some Primary",
                feat_artists=["Some Feature"],
                track_context="Some Primary - Track",
            )
        )
        featured_file = mapping_dir / "auto_learned_featured_artists.yaml"
        with open(featured_file) as f:
            before = yaml.safe_load(f)
        assert "SOME FEATURE" in before["featured_artists"] or any(
            k.lower() == "some feature" for k in before["featured_artists"]
        )

        # Aktion: nur die auto_learned_artist_aliases.yaml wird beschrieben.
        result = _run(
            manager.learn_artist(
                raw_name="Some Channel Name",
                canonical_name="Some Canonical Artist",
                source="youtube_parsed",
            )
        )
        assert result is True

        aliases_file = mapping_dir / "auto_learned_artist_aliases.yaml"
        with open(aliases_file) as f:
            aliases_data = yaml.safe_load(f)
        assert (
            aliases_data["auto_learned"]["Some Channel Name"]
            == "Some Canonical Artist"
        )

        with open(featured_file) as f:
            after = yaml.safe_load(f)
        assert after == before, (
            "Die auto_learned_featured_artists.yaml wurde durch das "
            "Schreiben eines Channel-Alias in auto_learned_artist_"
            "aliases.yaml veraendert - die beiden Dateien sind nicht "
            "sauber getrennt."
        )
