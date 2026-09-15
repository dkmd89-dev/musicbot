# tests/test_genre_revalidation.py
# -*- coding: utf-8 -*-
"""
services/library_repair/genre_revalidation.py — kontrollierte Genre-
Revalidierung (Library Genre Management v2, Chat-Charakterisierung
2026-09-15).

Testmuster identisch zu tests/test_genre_processor_revalidation_gap.py/
tests/test_auto_learn_genre_confidence_audit.py: eigene isolierte
mapping_dir pro Test (tmp_path), SingletonMixin._instances.clear() vor
jedem Test (GenreMapper/ArtistNormalizer sind Singletons - ohne Clear
wuerde ein Test die Instanz eines vorherigen Tests mit ANDEREM
mapping_dir wiederverwenden). Last.fm wird IMMER gemockt (patch.object
auf GenreProcessor._fetch_genre_from_lastfm) - kein echter externer
API-Call in dieser Testdatei.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from services.library_repair.genre_revalidation import (
    OUTCOME_BLOCKED_MANUAL,
    OUTCOME_NO_CANDIDATE,
    OUTCOME_OVERTURN_ALLOWED,
    OUTCOME_OVERTURN_REJECTED,
    OUTCOME_SAME_GENRE,
    run_genre_revalidation,
)
from services.metadata.auto_learn import AutoLearnManager
from services.metadata.genre_processor import GenreProcessor
from utils.singleton import SingletonMixin


def run(coro):
    return asyncio.run(coro)


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir
        self.LIBRARY_DIR = str(mapping_dir.parent / "library")
        self.ARTIST_OVERRIDE_FILE = str(mapping_dir / "artist_overrides.json")


def _genre_result(primary, secondary=None):
    return SimpleNamespace(primary=primary, secondary=list(secondary or []), source="lastfm", raw_tags=[])


@pytest.fixture(autouse=True)
def _clear_singletons():
    SingletonMixin._instances.clear()
    yield
    SingletonMixin._instances.clear()


@pytest.fixture
def mapping_dir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    (d / "artist_genre.yaml").write_text(yaml.safe_dump({"ARTIST_GENRE_MAP": {}}), encoding="utf-8")
    (d / "channel_genre.yaml").write_text(yaml.safe_dump({"CHANNEL_GENRE_MAP": {}}), encoding="utf-8")
    (d / "genre_hierarchy.yaml").write_text(yaml.safe_dump({"GENRE_HIERARCHY": {}}), encoding="utf-8")
    (d / "genre_overrides.yaml").write_text(yaml.safe_dump({"GENRE_OVERRIDES": {}}), encoding="utf-8")
    (d / "genre_aliases.yaml").write_text(yaml.safe_dump({"GENRE_ALIASES": {}}), encoding="utf-8")
    (d / "genre_rules.yaml").write_text(yaml.safe_dump({"GENRE_RULES": []}), encoding="utf-8")
    return d


def _learn_n_times(config, artist, primary, n):
    from utils.artist_map import ArtistConfig, ArtistNormalizer
    from utils.genre_map import GenreMapper

    genre_mapper = GenreMapper(mapping_dir=str(config.GENRE_MAPPING_DIR))
    artist_normalizer = ArtistNormalizer(
        ArtistConfig(library_dir=Path(config.LIBRARY_DIR), override_file=Path(config.ARTIST_OVERRIDE_FILE),
                     mapping_dir=Path(config.GENRE_MAPPING_DIR))
    )
    manager = AutoLearnManager(config=config, artist_normalizer=artist_normalizer, genre_mapper=genre_mapper)
    for _ in range(n):
        run(manager.learn_genre(artist, _genre_result(primary)))
    # SingletonMixin-Reset (GenreMapper/ArtistNormalizer sind Singletons):
    # ohne diesen Reset wuerde run_genre_revalidation()'s eigener
    # GenreMapper(...)-Aufruf danach die HIER bereits konstruierte
    # Instanz wiederverwenden (SingletonMixin ignoriert Konstruktor-Args
    # nach der ersten Instanziierung) - deren artist_map wurde aber vor
    # den obigen learn_genre()-Schreibvorgaengen gebaut und wird von
    # ihnen nicht automatisch aktualisiert (learn_genre() ruft nur
    # clear_caches(), nicht reload() - siehe genre_revalidation.py-
    # Kommentar zum reload()-Bug). Identisches Prinzip wie
    # tests/test_genre_processor_revalidation_gap.py::
    # _reload_genre_processor().
    SingletonMixin._instances.clear()


class TestManualMappingProtected:
    def test_manual_mapping_blocks_revalidation(self, mapping_dir):
        (mapping_dir / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {
                "metallica": {"primary": "Heavy Metal", "secondary": [], "description": "manual"},
            }}), encoding="utf-8",
        )
        config = _Config(mapping_dir)

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm") as mock_fetch:
            result = run(run_genre_revalidation("Metallica", apply=False, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_BLOCKED_MANUAL
        assert result.manual_mapping_protected is True
        assert result.current_primary == "Heavy Metal"
        mock_fetch.assert_not_called()

    def test_manual_mapping_never_mutated_even_with_apply(self, mapping_dir):
        (mapping_dir / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {
                "metallica": {"primary": "Heavy Metal", "secondary": [], "description": "manual"},
            }}), encoding="utf-8",
        )
        config = _Config(mapping_dir)

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm") as mock_fetch:
            result = run(run_genre_revalidation("Metallica", apply=True, config=config, lfm_client=object()))

        assert result.mutated is False
        mock_fetch.assert_not_called()


class TestNoCandidate:
    async def _no_result(self, *a, **kw):
        return None

    def test_lastfm_returns_nothing(self, mapping_dir):
        config = _Config(mapping_dir)
        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=self._no_result):
            result = run(run_genre_revalidation("Unknown Artist", apply=False, config=config, lfm_client=object()))
        assert result.outcome == OUTCOME_NO_CANDIDATE
        assert result.candidate_primary is None

    def test_lastfm_fetch_raises_is_no_candidate_not_crash(self, mapping_dir):
        async def _boom(*a, **kw):
            raise RuntimeError("network down")

        config = _Config(mapping_dir)
        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_boom):
            result = run(run_genre_revalidation("Some Artist", apply=False, config=config, lfm_client=object()))
        assert result.outcome == OUTCOME_NO_CANDIDATE
        assert result.error_message is not None


class TestSameGenre:
    def test_candidate_matches_locked_genre_no_change(self, mapping_dir):
        config = _Config(mapping_dir)
        _learn_n_times(config, "Bausa", "Deutschrap", 3)  # locks in ("Deutschrap")

        async def _same(*a, **kw):
            return _genre_result("Deutschrap")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_same):
            result = run(run_genre_revalidation("Bausa", apply=False, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_SAME_GENRE
        assert result.candidate_primary == "Deutschrap"
        assert result.current_primary == "Deutschrap"


class TestOverturnRejected:
    def test_challenger_not_strong_enough_rejected(self, mapping_dir):
        config = _Config(mapping_dir)
        # 3x "Rock" lockt "Rock" (Threshold=3). Ein einzelner "Pop"-Kandidat
        # (1 < 3x3=9 fuer Overturn) darf den Lock NICHT umstossen.
        _learn_n_times(config, "Bausa", "Rock", 3)

        async def _challenger(*a, **kw):
            return _genre_result("Pop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_challenger):
            result = run(run_genre_revalidation("Bausa", apply=False, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_OVERTURN_REJECTED
        assert result.candidate_primary == "Pop"
        assert result.locked_primary == "Rock"

    def test_overturn_rejected_does_not_mutate_even_with_apply(self, mapping_dir):
        config = _Config(mapping_dir)
        _learn_n_times(config, "Bausa", "Rock", 3)

        async def _challenger(*a, **kw):
            return _genre_result("Pop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_challenger):
            result = run(run_genre_revalidation("Bausa", apply=True, config=config, lfm_client=object()))

        assert result.mutated is False

        auto_file = mapping_dir / "auto_learned_genre.json"
        data = json.loads(auto_file.read_text(encoding="utf-8"))
        # Lock bleibt "Rock" - kein Primary-Wechsel durch den abgelehnten Versuch.
        assert data["ARTIST_GENRE_MAP"]["Bausa"]["locked_primary"] == "Rock"


class TestOverturnAllowed:
    def test_enough_challenger_observations_allowed(self, mapping_dir):
        """Abgelehnte Revalidierungs-Versuche hinterlassen bewusst KEINE
        Beobachtung (Auftrag §14: "keine Mutation" bei nicht zulaessigem
        Overturn - auch keine stille Zaehler-Erhoehung). Der realistische
        Weg zu genug Herausforderer-Beobachtungen ist der NORMALE
        Auto-Learn-Pfad (z. B. 8 echte Downloads mit "Pop"-Tag) - danach
        reicht EINE einzelne Revalidierung mit der 9. "Pop"-Beobachtung,
        um die Overturn-Schwelle (challenger >= 3x locked_count) zu
        erreichen."""
        config = _Config(mapping_dir)
        _learn_n_times(config, "Bausa", "Rock", 3)  # locked_primary=Rock, count=3
        _learn_n_times(config, "Bausa", "Pop", 8)  # 8 < 3*3=9 -> Lock bleibt Rock

        async def _challenger(*a, **kw):
            return _genre_result("Pop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_challenger):
            result = run(run_genre_revalidation("Bausa", apply=False, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_OVERTURN_ALLOWED
        assert result.candidate_primary == "Pop"

    def test_apply_true_writes_new_observation(self, mapping_dir):
        config = _Config(mapping_dir)
        # Kein Lock noch (0 Beobachtungen) - erste Last.fm-Beobachtung
        # "gewinnt" sofort (Vorlock-Phase, siehe _compute_genre_lock_decision()).

        async def _candidate(*a, **kw):
            return _genre_result("Hip Hop", ["Deutschrap"])

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_candidate):
            result = run(run_genre_revalidation("Frischer Artist", apply=True, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_OVERTURN_ALLOWED
        assert result.mutated is True

        auto_file = mapping_dir / "auto_learned_genre.json"
        data = json.loads(auto_file.read_text(encoding="utf-8"))
        assert data["ARTIST_GENRE_MAP"]["Frischer Artist"]["primary"] == "Hip Hop"

    def test_dry_run_does_not_write(self, mapping_dir):
        config = _Config(mapping_dir)

        async def _candidate(*a, **kw):
            return _genre_result("Hip Hop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_candidate):
            result = run(run_genre_revalidation("Frischer Artist", apply=False, config=config, lfm_client=object()))

        assert result.outcome == OUTCOME_OVERTURN_ALLOWED
        assert result.mutated is False
        auto_file = mapping_dir / "auto_learned_genre.json"
        assert not auto_file.exists()


class TestCurrentGenreDisplay:
    def test_current_genre_reflects_locked_auto_learned_value(self, mapping_dir):
        config = _Config(mapping_dir)
        _learn_n_times(config, "Bausa", "Deutschrap", 2)  # LEARNED, kein Lock noetig fuer Anzeige

        async def _same(*a, **kw):
            return _genre_result("Deutschrap")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_same):
            result = run(run_genre_revalidation("Bausa", apply=False, config=config, lfm_client=object()))

        assert result.current_primary == "Deutschrap"

    def test_current_genre_none_when_completely_unknown(self, mapping_dir):
        config = _Config(mapping_dir)

        async def _none(*a, **kw):
            return None

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_none):
            result = run(run_genre_revalidation("Ganz Unbekannt", apply=False, config=config, lfm_client=object()))

        assert result.current_primary is None


class TestRunTracking:
    def test_successful_apply_writes_run_record(self, mapping_dir, monkeypatch):
        import services.library_repair.run_tracking as rt

        monkeypatch.setattr(rt.Config, "DATA_DIR", mapping_dir.parent / "data")
        config = _Config(mapping_dir)

        async def _candidate(*a, **kw):
            return _genre_result("Hip Hop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_candidate):
            run(run_genre_revalidation("Frischer Artist", apply=True, triggered_by="telegram:1", config=config, lfm_client=object()))

        runs = rt.load_repair_history()
        matching = [r for r in runs if r.get("level") == "GENRE_REVALIDATION"]
        assert len(matching) == 1
        assert matching[0]["kind"] == "maintenance"
        assert matching[0]["artist"] == "Frischer Artist"
        assert matching[0]["status"] == "SUCCESS"
        assert matching[0]["triggered_by"] == "telegram:1"

    def test_rejected_overturn_writes_no_run_record(self, mapping_dir, monkeypatch):
        import services.library_repair.run_tracking as rt

        monkeypatch.setattr(rt.Config, "DATA_DIR", mapping_dir.parent / "data")
        config = _Config(mapping_dir)
        _learn_n_times(config, "Bausa", "Rock", 3)

        async def _challenger(*a, **kw):
            return _genre_result("Pop")

        with patch.object(GenreProcessor, "_fetch_genre_from_lastfm", new=_challenger):
            run(run_genre_revalidation("Bausa", apply=True, config=config, lfm_client=object()))

        assert not rt.runs_index_path().exists()
