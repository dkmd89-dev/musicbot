# -*- coding: utf-8 -*-
"""AR-3: auto_learned_genre.json wird vom Bot-Prozess (Download-Pfad) UND vom
Revalidierungs-Subprozess (scripts/revalidate_genre.py) per Read-Modify-Write
geschrieben. Der Schreibpfad muss den prozessuebergreifenden Datei-Lock
(utils/file_lock) nutzen, sonst geht eine Beobachtung verloren (Lost Update).

Den zweiten Prozess simuliert der Test, indem er den Datei-Lock selbst haelt.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistConfig, ArtistNormalizer
from utils.file_lock import cross_process_lock
from utils.genre_map import GenreMapper
from utils.singleton import SingletonMixin


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _manager(mapping_dir: Path) -> AutoLearnManager:
    SingletonMixin._instances.clear()
    artist_config = ArtistConfig(
        library_dir=mapping_dir.parent / "library",
        override_file=mapping_dir / "artist_overrides.json",
        mapping_dir=mapping_dir,
    )
    return AutoLearnManager(
        config=_Config(mapping_dir),
        artist_normalizer=ArtistNormalizer(artist_config),
        genre_mapper=GenreMapper(mapping_dir=mapping_dir),
    )


def _info(primary: str):
    return SimpleNamespace(primary=primary, secondary=[], source="lastfm", raw_tags=[])


def _signal_on_enter(manager: AutoLearnManager) -> threading.Event:
    """Setzt ein Event, sobald der Schreibpfad betreten wird. Damit prueft der
    Test das Blockieren erst, nachdem der Worker sicher vor dem Lock steht -
    unabhaengig von der Geschwindigkeit des Rechners."""
    entered = threading.Event()
    original = manager._write_genre_observation_sync

    def wrapper(*args, **kwargs):
        entered.set()
        return original(*args, **kwargs)

    manager._write_genre_observation_sync = wrapper
    return entered


def _observations(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["ARTIST_GENRE_MAP"]["Some Artist"]["observations"]


def test_genre_observation_write_waits_for_foreign_file_lock(tmp_path) -> None:
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    manager = _manager(mapping_dir)
    entered = _signal_on_enter(manager)
    path = mapping_dir / "auto_learned_genre.json"

    done = threading.Event()
    errors: list = []

    def target() -> None:
        try:
            asyncio.run(manager.learn_genre("Some Artist", _info("Pop")))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            done.set()

    with cross_process_lock(path):
        t = threading.Thread(target=target)
        t.start()
        assert entered.wait(timeout=5), "Writer erreichte den Schreibpfad nicht"
        finished_while_locked = done.wait(timeout=0.5)
    assert done.wait(timeout=5)
    t.join(timeout=5)

    assert not errors, errors
    assert not finished_while_locked, "Writer ignorierte den prozessuebergreifenden Lock"
    assert _observations(path) == 1


def test_no_lost_update_when_other_process_writes_while_waiting(tmp_path) -> None:
    """Ein anderer Prozess schreibt eine Beobachtung, waehrend der Bot-Writer
    auf den Lock wartet: nach Freigabe liest der Writer den NEUEN Stand und
    haengt an (2 Beobachtungen statt Lost Update auf 1)."""
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    manager = _manager(mapping_dir)
    entered = _signal_on_enter(manager)
    path = mapping_dir / "auto_learned_genre.json"

    done = threading.Event()

    def target() -> None:
        try:
            asyncio.run(manager.learn_genre("Some Artist", _info("Pop")))
        finally:
            done.set()

    with cross_process_lock(path):
        t = threading.Thread(target=target)
        t.start()
        assert entered.wait(timeout=5), "Writer erreichte den Schreibpfad nicht"
        assert not done.wait(timeout=0.5)
        # "anderer Prozess" schreibt unter dem gehaltenen Lock
        other = _manager(mapping_dir)
        other._write_json_atomic(path, {"ARTIST_GENRE_MAP": {"Some Artist": {
            "primary": "Pop", "secondary": [], "observations": 1, "confidence": "OBSERVED",
            "observation_log": [{"primary": "Pop", "secondary": []}],
            "locked_primary": None, "genre_counts": {"Pop": 1},
        }}})
    assert done.wait(timeout=5)
    t.join(timeout=5)
    assert _observations(path) == 2


def test_genre_write_does_not_deadlock_and_still_writes(tmp_path) -> None:
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    manager = _manager(mapping_dir)
    done = threading.Event()
    errors: list = []

    def target() -> None:
        try:
            asyncio.run(manager.learn_genre("Some Artist", _info("Pop")))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            done.set()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    assert done.wait(timeout=5), "Writer haengt (Deadlock auf eigenem Lock?)"
    t.join(timeout=5)
    assert not errors, errors
    assert _observations(mapping_dir / "auto_learned_genre.json") == 1
