"""
Genre-Lock-in-Regel (2026-09-03).

Live-Fund im Anschluss an ARCH-022: reines Mehrheitsvotum
(_aggregate_genre_observations()) berechnet primary bei JEDER neuen
Beobachtung neu - fuer einen Artist mit vielen Tracks und wechselnden
Last.fm-Tags (Beispiel: Toobrokeforfiji) fuehrt das nie zu einem stabilen,
artist-weiten Genre-Mapping. Diese Tests verifizieren die neue Lock-in-Regel:
sobald ein Genre 3x als primary beobachtet wurde, wird es dauerhaft gelockt
(_GENRE_LOCK_THRESHOLD). Ein Herausforderer-Genre uebernimmt den Lock erst,
wenn seine Beobachtungszahl das 3-fache (_GENRE_LOCK_OVERTURN_MULTIPLIER) der
LIVE (nicht eingefrorenen) Beobachtungszahl des aktuell gelockten Werts
erreicht/uebersteigt. Ein durch die Lock-Regel abgelehnter/ueberstimmter Wert
erscheint per Nutzerentscheidung explizit in secondary.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from services.metadata.auto_learn import (
    AutoLearnManager,
    _GENRE_LOCK_THRESHOLD,
    _GENRE_LOCK_OVERTURN_MULTIPLIER,
    _MAX_OBSERVATION_LOG,
    _compute_genre_lock_decision,
    _derive_genre_primary_secondary,
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


# ─────────────────────────────────────────────────────────────────────────
# _compute_genre_lock_decision() isoliert
# ─────────────────────────────────────────────────────────────────────────


class TestComputeGenreLockDecisionIsolated:
    def test_thresholds_are_the_documented_values(self):
        assert _GENRE_LOCK_THRESHOLD == 3
        assert _GENRE_LOCK_OVERTURN_MULTIPLIER == 3

    def test_no_lock_below_threshold(self):
        counts = {"A": 1}
        new_locked, updated = _compute_genre_lock_decision(counts, None, "A")
        assert new_locked is None
        assert updated["A"] == 2, "erst die DRITTE Beobachtung loest den Lock aus"

    def test_lock_engages_at_exactly_the_threshold(self):
        counts = {"A": 2}
        new_locked, updated = _compute_genre_lock_decision(counts, None, "A")
        assert updated["A"] == _GENRE_LOCK_THRESHOLD
        assert new_locked == "A"

    def test_locked_value_holds_against_a_weak_challenger(self):
        """Gelockt bei 3, Herausforderer erreicht nur 2 - deutlich unter der
        3x-Schwelle (waere 9) - Lock bleibt bestehen."""
        counts = {"A": 3, "B": 1}
        new_locked, updated = _compute_genre_lock_decision(counts, "A", "B")
        assert new_locked == "A"
        assert updated["B"] == 2

    def test_locked_value_holds_one_below_the_overturn_multiplier(self):
        """Gelockt bei 3 (locked_count=3), Herausforderer bei 8 (naechster
        Aufruf bringt ihn auf 8) - Schwelle ist 3*3=9, 8 < 9 -> kein Overturn."""
        counts = {"A": 3, "B": 7}
        new_locked, updated = _compute_genre_lock_decision(counts, "A", "B")
        assert updated["B"] == 8
        assert new_locked == "A", "8 < 3x3=9 - der Lock darf noch NICHT wechseln"

    def test_challenger_overturns_at_exactly_the_multiplier(self):
        """Gelockt bei 3, Herausforderer erreicht mit diesem Aufruf genau 9
        (3x3) - Grenzfall: >= loest den Wechsel aus."""
        counts = {"A": 3, "B": 8}
        new_locked, updated = _compute_genre_lock_decision(counts, "A", "B")
        assert updated["B"] == 9
        assert new_locked == "B"

    def test_reconfirming_the_locked_value_raises_its_own_live_count(self):
        """Der gelockte Wert bleibt Lock, sein Zaehler steigt aber weiter -
        ein spaeterer Herausforderer muss dadurch eine hoehere absolute
        Zahl erreichen (live, nicht eingefroren bei 3)."""
        counts = {"A": 3}
        new_locked, updated = _compute_genre_lock_decision(counts, "A", "A")
        assert new_locked == "A"
        assert updated["A"] == 4

        # ein Herausforderer, der jetzt bei 8 steht, ueberholt NICHT mehr,
        # da die Schwelle mit dem live A-Zaehler auf 4*3=12 gestiegen ist.
        counts2 = {"A": 4, "B": 7}
        new_locked2, updated2 = _compute_genre_lock_decision(counts2, "A", "B")
        assert updated2["B"] == 8
        assert new_locked2 == "A", "Schwelle ist inzwischen 4*3=12, 8 < 12"


# ─────────────────────────────────────────────────────────────────────────
# _derive_genre_primary_secondary() isoliert
# ─────────────────────────────────────────────────────────────────────────


class TestDerivePrimarySecondaryIsolated:
    def test_prelock_phase_behaves_exactly_like_pure_majority_vote(self):
        """Vor Erreichen des Locks (< 3 Beobachtungen eines Werts) ist das
        Ergebnis identisch zum bisherigen reinen Mehrheitsvotum - keine
        Verhaltensaenderung in dieser Phase."""
        log = [
            {"primary": "Deutschpop", "secondary": ["Pop"]},
            {"primary": "Deutschpop", "secondary": ["Hip Hop"]},
            {"primary": "Pop", "secondary": ["Hip Hop"]},
        ]
        result = _derive_genre_primary_secondary(None, log, "Pop")
        assert result["primary"] == "Deutschpop"
        assert result["locked_primary"] is None
        assert result["genre_counts"] == {"Deutschpop": 2, "Pop": 1}

    def test_lock_engages_and_rejected_challenger_appears_in_secondary(self):
        """Nutzerentscheidung: ein durch den Lock abgelehnter Wert erscheint
        explizit in secondary, nicht nur implizit in genre_counts."""
        existing_entry = {
            "locked_primary": None,
            "genre_counts": {"Deutschrap": 2},
        }
        log = [
            {"primary": "Deutschrap", "secondary": []},
            {"primary": "Deutschrap", "secondary": []},
            {"primary": "Deutschrap", "secondary": []},
        ]
        result = _derive_genre_primary_secondary(existing_entry, log, "Deutschrap")
        assert result["primary"] == "Deutschrap"
        assert result["locked_primary"] == "Deutschrap"

        existing_entry_2 = {
            "locked_primary": "Deutschrap",
            "genre_counts": {"Deutschrap": 3},
        }
        log_2 = log + [{"primary": "Pop", "secondary": []}]
        result_2 = _derive_genre_primary_secondary(existing_entry_2, log_2, "Pop")
        assert result_2["primary"] == "Deutschrap", "Lock bleibt bestehen (1 < 3x3=9)"
        assert "Pop" in result_2["secondary"], (
            "abgelehnter Herausforderer muss explizit in secondary erscheinen"
        )

    def test_legacy_entry_without_genre_counts_is_backfilled_from_log(self):
        """Migrations-Backfill: ein Alt-Eintrag (vor Einfuehrung des
        Lock-in geschrieben) hat kein genre_counts-Feld - es wird aus
        observation_log[:-1] rekonstruiert (die aktuelle Beobachtung ist
        bereits als letztes Element enthalten, nicht doppelt zaehlen)."""
        existing_entry = {"primary": "Deutschrap", "secondary": []}  # kein genre_counts
        log = [
            {"primary": "Deutschrap", "secondary": []},
            {"primary": "Deutschrap", "secondary": []},
            {"primary": "Deutschrap", "secondary": []},  # aktuelle Beobachtung
        ]
        result = _derive_genre_primary_secondary(existing_entry, log, "Deutschrap")
        assert result["genre_counts"] == {"Deutschrap": 3}
        assert result["locked_primary"] == "Deutschrap"


# ─────────────────────────────────────────────────────────────────────────
# Pflicht-Testpaar: genre_counts ueberlebt die observation_log-Kappung
# ─────────────────────────────────────────────────────────────────────────


class TestGenreCountsSurviveObservationLogCap:
    ARTIST = "Toobrokeforfiji"

    def test_genre_counts_survive_observation_log_cap_pop_does_not_overturn_at_eight(
        self, tmp_path
    ):
        """
        3x Deutschrap (Lock) + 8x Pop = 11 Rohbeobachtungen. Der
        observation_log-Cap (_MAX_OBSERVATION_LOG=10) wirft die aelteste
        Deutschrap-Beobachtung aus dem Log - genre_counts (ungekappt) bleibt
        trotzdem korrekt: primary bleibt 'Deutschrap' (8 Pop < 3x3=9 Schwelle),
        secondary enthaelt 'Pop'.
        """
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for _ in range(3):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Deutschrap")))
        for _ in range(8):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Pop")))

        entry = _read_genre_entry(mapping_dir, self.ARTIST)
        assert len(entry["observation_log"]) == _MAX_OBSERVATION_LOG, (
            "observation_log muss bei 10 gekappt sein (11 Rohbeobachtungen)"
        )
        assert entry["genre_counts"] == {"Deutschrap": 3, "Pop": 8}, (
            "genre_counts ist ungekappt und muss die volle Historie zeigen"
        )
        assert entry["locked_primary"] == "Deutschrap"
        assert entry["primary"] == "Deutschrap", "8 Pop < 3x3=9 - noch kein Overturn"
        assert "Pop" in entry["secondary"]

    def test_ninth_pop_observation_overturns_the_lock(self, tmp_path):
        """Fortsetzung des Kappungsbeispiels: die 9. Pop-Beobachtung
        erreicht die 3x-Schwelle (3 gelockte Deutschrap-Beobachtungen * 3 =
        9) und uebernimmt den Lock."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for _ in range(3):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Deutschrap")))
        for _ in range(9):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Pop")))

        entry = _read_genre_entry(mapping_dir, self.ARTIST)
        assert entry["genre_counts"] == {"Deutschrap": 3, "Pop": 9}
        assert entry["locked_primary"] == "Pop"
        assert entry["primary"] == "Pop"
        assert "Deutschrap" in entry["secondary"], (
            "der abgeloeste, vormals gelockte Wert erscheint explizit in secondary"
        )


# ─────────────────────────────────────────────────────────────────────────
# End-to-End ueber learn_genre() / Dry-Run-Konsistenz
# ─────────────────────────────────────────────────────────────────────────


class TestEndToEndViaLearnGenre:
    def test_three_identical_observations_lock_the_genre(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for _ in range(3):
            _run(
                manager.learn_genre(
                    "Toobrokeforfiji", _genre_info("Deutschrap", ["Hip Hop"])
                )
            )
        entry = _read_genre_entry(mapping_dir, "Toobrokeforfiji")
        assert entry["locked_primary"] == "Deutschrap"
        assert entry["primary"] == "Deutschrap"

        # eine vierte, abweichende Beobachtung darf primary NICHT mehr aendern
        _run(manager.learn_genre("Toobrokeforfiji", _genre_info("Pop")))
        entry_after = _read_genre_entry(mapping_dir, "Toobrokeforfiji")
        assert entry_after["primary"] == "Deutschrap", (
            "nach dem Lock darf eine einzelne abweichende Beobachtung primary "
            "nicht mehr veraendern (Kernanliegen des Auftrags)"
        )
        assert "Pop" in entry_after["secondary"]

    def test_dry_run_genre_prediction_matches_live_outcome(self, tmp_path):
        """Dry-Run (preview_genre_learning) und echter Schreibpfad
        (learn_genre) muessen fuer dieselbe Beobachtungssequenz identisch
        entscheiden - beide rufen _derive_genre_primary_secondary() ueber
        denselben Weg auf."""
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        manager = _make_manager(mapping_dir)

        for genre in ["Deutschrap", "Deutschrap", "Deutschrap", "Pop"]:
            _run(manager.learn_genre("Toobrokeforfiji", _genre_info(genre)))

        # Dry-Run fuer die naechste (fuenfte) Beobachtung
        preview = manager.preview_genre_learning(
            "Toobrokeforfiji", _genre_info("Pop")
        )
        assert preview["predicted_primary"] == "Deutschrap"
        assert preview["predicted_locked_primary"] == "Deutschrap"

        # tatsaechlicher Schreibvorgang muss identisch entscheiden
        _run(manager.learn_genre("Toobrokeforfiji", _genre_info("Pop")))
        entry = _read_genre_entry(mapping_dir, "Toobrokeforfiji")
        assert entry["primary"] == preview["predicted_primary"]
        assert entry["locked_primary"] == preview["predicted_locked_primary"]
