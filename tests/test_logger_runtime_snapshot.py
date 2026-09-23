# -*- coding: utf-8 -*-
"""
CC-LOGGER-L5.1 — Tests für Runtime-Snapshot
(`services/logger_admin.py::write_runtime_snapshot` / `read_runtime_snapshot`).

Kernverträge, die diese Tests pinnen:

1. Der Snapshot wird aus dem **tatsächlichen Runtime-Zustand** gelesen
   (logging.getLogger(name).level/handlers/disabled), NICHT aus der
   persistenten Config.
2. Ein Schreib-Fehler stoppt den Bot nicht (Observability, nicht
   Lifecycle-kritisch).
3. `read_runtime_snapshot()` liefert niemals einen Fake-State: bei
   fehlendem Snapshot `status="missing"`, bei korruptem JSON
   `status="corrupt"`, bei unvollständigem Snapshot ebenfalls
   `status="corrupt"`.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from logger import _module_loggers, get_module_logger
from services.logger_admin import (
    SNAPSHOT_FILE_NAME,
    SNAPSHOT_SCHEMA_VERSION,
    read_runtime_snapshot,
    write_runtime_snapshot,
)


class FakeConfig:
    def __init__(self, data_dir: Path):
        self.DATA_DIR = str(data_dir)


@pytest.fixture
def cfg(tmp_path: Path) -> FakeConfig:
    return FakeConfig(tmp_path)


_TEST_MODULE_NAMES = (
    "SnapshotTest_ModA",
    "SnapshotTest_ModB",
    "SnapshotTest_ModDisabled",
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Stellt sicher, dass Test-Logger und _module_loggers-Einträge nach
    jedem Test entfernt werden — logging.Logger ist ein globales
    Singleton pro Name, und _module_loggers ist prozessweit."""
    yield
    for name in _TEST_MODULE_NAMES:
        _module_loggers.pop(name, None)
        real = logging.getLogger(name)
        for h in real.handlers[:]:
            real.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        real.setLevel(logging.NOTSET)
        real.disabled = False


def _make_module_logger(
    name: str,
    *,
    level: int,
    with_file: bool = False,
    with_stream: bool = False,
    disabled: bool = False,
):
    """Erzeugt einen echten EnhancedLogger-Eintrag in _module_loggers
    mit konfigurierten Handlern/Leveln — simuliert exakt das, was die
    echte Bot-Startup-Sequenz über get_module_logger() tut."""
    enhanced = get_module_logger(name)
    real = enhanced.logger
    real.setLevel(level)
    real.disabled = disabled
    if with_file:
        # os.devnull ist portabel (Linux /dev/null, Windows nul) und
        # erzeugt einen echten FileHandler-Typ, den der Snapshot erkennt.
        real.addHandler(logging.FileHandler(os.devnull))
    if with_stream:
        real.addHandler(logging.StreamHandler())
    return enhanced


def _read_snapshot(cfg: FakeConfig) -> dict:
    return json.loads((Path(cfg.DATA_DIR) / SNAPSHOT_FILE_NAME).read_text(encoding="utf-8"))


# =====================================================================
# Write
# =====================================================================

class TestWriteRuntimeSnapshot:
    def test_creates_file_with_expected_fields(self, cfg: FakeConfig) -> None:
        _make_module_logger("SnapshotTest_ModA", level=logging.DEBUG)
        path = write_runtime_snapshot(cfg)
        assert path is not None
        assert path.exists()
        data = _read_snapshot(cfg)
        for key in (
            "schema_version",
            "startup_id",
            "runtime_applied_at",
            "root_level",
            "effective_levels",
            "handlers",
            "disabled",
        ):
            assert key in data, f"fehlendes Pflichtfeld: {key}"
        assert data["schema_version"] == SNAPSHOT_SCHEMA_VERSION
        assert isinstance(data["startup_id"], str) and data["startup_id"]

    def test_effective_levels_reflect_runtime_state(self, cfg: FakeConfig) -> None:
        _make_module_logger("SnapshotTest_ModA", level=logging.DEBUG)
        _make_module_logger("SnapshotTest_ModB", level=logging.ERROR)
        write_runtime_snapshot(cfg)
        levels = _read_snapshot(cfg)["effective_levels"]
        assert levels["SnapshotTest_ModA"] == "DEBUG"
        assert levels["SnapshotTest_ModB"] == "ERROR"

    def test_effective_levels_do_not_reflect_config(self, cfg: FakeConfig) -> None:
        """Kernvertrag: Der Snapshot liest Runtime, NICHT die Config.
        Wir setzen den Runtime-Level explizit auf WARNING und prüfen,
        dass genau dieser Wert im Snapshot steht — nicht ein eventueller
        Config-Wert (es gibt hier gar keine Config, also keine Chance
        auf versehentliche Rekonstruktion)."""
        _make_module_logger("SnapshotTest_ModA", level=logging.WARNING)
        write_runtime_snapshot(cfg)
        levels = _read_snapshot(cfg)["effective_levels"]
        assert levels["SnapshotTest_ModA"] == "WARNING"

    def test_handlers_reflect_runtime_state(self, cfg: FakeConfig) -> None:
        _make_module_logger(
            "SnapshotTest_ModA",
            level=logging.INFO,
            with_file=True,
            with_stream=True,
        )
        write_runtime_snapshot(cfg)
        handlers = _read_snapshot(cfg)["handlers"]["SnapshotTest_ModA"]
        assert "FileHandler" in handlers
        assert "StreamHandler" in handlers

    def test_disabled_modules_listed(self, cfg: FakeConfig) -> None:
        _make_module_logger(
            "SnapshotTest_ModDisabled", level=logging.INFO, disabled=True
        )
        write_runtime_snapshot(cfg)
        assert "SnapshotTest_ModDisabled" in _read_snapshot(cfg)["disabled"]

    def test_write_is_atomic_no_tmp_left(self, cfg: FakeConfig) -> None:
        _make_module_logger("SnapshotTest_ModA", level=logging.INFO)
        write_runtime_snapshot(cfg)
        tmps = list(Path(cfg.DATA_DIR).glob("*.tmp*"))
        assert tmps == []

    def test_write_failure_returns_none_and_does_not_raise(
        self, cfg: FakeConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kernvertrag: Schreib-Fehler stoppt den Bot NICHT."""
        from services import logger_admin

        def _boom(path, data):
            raise OSError("simulated write failure")

        monkeypatch.setattr(logger_admin, "_atomic_write_json", _boom)
        _make_module_logger("SnapshotTest_ModA", level=logging.INFO)
        result = write_runtime_snapshot(cfg)
        assert result is None  # kein Raise


# =====================================================================
# Read
# =====================================================================

class TestReadRuntimeSnapshot:
    def test_missing_returns_status_missing(self, cfg: FakeConfig) -> None:
        result = read_runtime_snapshot(cfg)
        assert result["status"] == "missing"
        assert "snapshot" not in result

    def test_available_returns_snapshot(self, cfg: FakeConfig) -> None:
        _make_module_logger("SnapshotTest_ModA", level=logging.INFO)
        write_runtime_snapshot(cfg)
        result = read_runtime_snapshot(cfg)
        assert result["status"] == "available"
        assert result["snapshot"]["schema_version"] == SNAPSHOT_SCHEMA_VERSION

    def test_corrupt_json_returns_corrupt(self, cfg: FakeConfig) -> None:
        (Path(cfg.DATA_DIR) / SNAPSHOT_FILE_NAME).write_text("{ nope", encoding="utf-8")
        assert read_runtime_snapshot(cfg)["status"] == "corrupt"

    def test_non_object_returns_corrupt(self, cfg: FakeConfig) -> None:
        (Path(cfg.DATA_DIR) / SNAPSHOT_FILE_NAME).write_text("[1, 2, 3]", encoding="utf-8")
        assert read_runtime_snapshot(cfg)["status"] == "corrupt"

    def test_incomplete_returns_corrupt(self, cfg: FakeConfig) -> None:
        # fehlende schema_version/startup_id/runtime_applied_at
        (Path(cfg.DATA_DIR) / SNAPSHOT_FILE_NAME).write_text(
            json.dumps({"root_level": "INFO"}), encoding="utf-8"
        )
        assert read_runtime_snapshot(cfg)["status"] == "corrupt"

    def test_read_never_fabricates_state(self, cfg: FakeConfig) -> None:
        """Kein Fake-State bei fehlendem Snapshot."""
        result = read_runtime_snapshot(cfg)
        assert result["status"] == "missing"
        assert "effective_levels" not in result
        assert "handlers" not in result
        assert "root_level" not in result
