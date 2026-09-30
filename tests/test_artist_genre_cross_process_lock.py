# -*- coding: utf-8 -*-
"""AR-1: artist_genre.yaml wird von Control Center, Telegram und CLI im
Read-Modify-Write geschrieben. Der gemeinsame Writer muss den
prozessuebergreifenden Datei-Lock (utils/file_lock) nutzen, sonst ueberschreiben
sich zwei Prozesse gegenseitig (Lost Update).

Simuliert den zweiten Prozess, indem der Test den Datei-Lock selbst haelt: ein
Schreibzugriff darf dann erst nach Freigabe durchlaufen.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml

from services.library_repair.genre import (
    apply_manual_genre_mapping,
    get_genre_mapping,
    save_manual_genre_mapping,
)
from utils.file_lock import cross_process_lock

_YAML = """ARTIST_GENRE_MAP:
  kygo:
    primary: House
    secondary: []
    description: x
"""


@pytest.fixture()
def mapping_dir(tmp_path: Path) -> Path:
    (tmp_path / "artist_genre.yaml").write_text(_YAML, encoding="utf-8")
    return tmp_path


def _run_blocked(mapping_dir: Path, action) -> tuple[bool, bool]:
    """Fuehrt `action` in einem Thread aus, waehrend der Datei-Lock extern
    gehalten wird. Rueckgabe: (waehrend Lock fertig?, nach Freigabe fertig?)."""
    done = threading.Event()
    errors: list = []

    def target() -> None:
        try:
            action()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            done.set()

    with cross_process_lock(mapping_dir / "artist_genre.yaml"):
        t = threading.Thread(target=target)
        t.start()
        finished_while_locked = done.wait(timeout=0.5)
    finished_after_release = done.wait(timeout=5)
    t.join(timeout=5)
    assert not errors, errors
    return finished_while_locked, finished_after_release


def test_save_waits_for_foreign_file_lock(mapping_dir) -> None:
    during, after = _run_blocked(
        mapping_dir,
        lambda: save_manual_genre_mapping("kygo", "Pop", mapping_dir, dry_run=False),
    )
    assert not during, "Writer ignorierte den prozessuebergreifenden Lock"
    assert after
    data = yaml.safe_load((mapping_dir / "artist_genre.yaml").read_text(encoding="utf-8"))
    assert data["ARTIST_GENRE_MAP"]["kygo"]["primary"] == "Pop"


def test_apply_waits_for_foreign_file_lock(mapping_dir) -> None:
    _, etag = get_genre_mapping("kygo", mapping_dir)
    during, after = _run_blocked(
        mapping_dir,
        lambda: apply_manual_genre_mapping(
            "kygo", "Pop", [], mapping_dir, expected_etag=etag
        ),
    )
    assert not during
    assert after


def test_apply_detects_change_made_by_other_process_while_waiting(mapping_dir) -> None:
    """Etag-Pruefung liegt INNERHALB des Datei-Locks: aendert ein anderer
    Prozess den Eintrag, waehrend apply wartet, gibt es 409 statt Lost Update."""
    from services.library_repair.genre import GenreMappingConflictError

    _, etag = get_genre_mapping("kygo", mapping_dir)
    result: list = []

    def target() -> None:
        try:
            apply_manual_genre_mapping("kygo", "Pop", [], mapping_dir, expected_etag=etag)
            result.append("ok")
        except GenreMappingConflictError:
            result.append("conflict")

    with cross_process_lock(mapping_dir / "artist_genre.yaml"):
        t = threading.Thread(target=target)
        t.start()
        time.sleep(0.2)
        path = mapping_dir / "artist_genre.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["ARTIST_GENRE_MAP"]["kygo"]["primary"] = "Techno"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
    t.join(timeout=5)
    assert result == ["conflict"]
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["ARTIST_GENRE_MAP"]["kygo"]["primary"] == "Techno"


def test_apply_does_not_deadlock_on_its_own_lock(mapping_dir) -> None:
    """Regression: apply -> save darf denselben Datei-Lock nicht doppelt anfordern."""
    _, etag = get_genre_mapping("kygo", mapping_dir)
    done = threading.Event()
    threading.Thread(
        target=lambda: (apply_manual_genre_mapping("kygo", "Pop", [], mapping_dir, expected_etag=etag), done.set()),
        daemon=True,
    ).start()
    assert done.wait(timeout=5)
