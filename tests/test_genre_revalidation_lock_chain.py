# -*- coding: utf-8 -*-
"""Genre-Revalidierung: Runner + Subprozess-Skript teilen sich EINEN Repair-Lock.

Regression (Fund bei der Control-Center-Anbindung): genre_revalidation_runner.
run_genre_revalidation_subprocess() nimmt den globalen Repair-Lock und startet
dann scripts/revalidate_genre.py. Bei --apply nahm das Kind
(genre_revalidation.run_genre_revalidation) denselben Lock ein zweites Mal ->
RepairAlreadyRunningError, Exit-Code 3, keine Ergebnisdatei: jede Anwendung ueber
den Runner (Telegram, jetzt auch Control Center) scheiterte. Nur die Vorschau (ohne
Lock im Kind) und der direkte CLI-Aufruf (ohne Runner) funktionierten — in der
Repair-History stehen bisher ausschliesslich `cli`-Laeufe.

Diese Tests fahren die GANZE Kette: Runner (echt) -> Skript-main() (echt, im
Thread als "Subprozess") -> run_genre_revalidation() (echt). Nur Last.fm und die
Pfade sind ersetzt.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from config import Config
from services.library_repair import genre_revalidation_runner as runner
from services.library_repair.genre_revalidation import run_genre_revalidation
from services.library_repair.run_tracking import (
    RepairAlreadyRunningError,
    acquire_repair_lock,
    is_repair_running,
    load_repair_history,
    release_repair_lock,
)
from services.metadata.genre_processor import GenreProcessor
from utils.singleton import SingletonMixin

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "revalidate_genre.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("revalidate_genre_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clear_singletons():
    SingletonMixin._instances.clear()
    yield
    SingletonMixin._instances.clear()


@pytest.fixture
def env(tmp_path, monkeypatch):
    mapping = tmp_path / "mapping"
    mapping.mkdir()
    for name, content in {
        "artist_genre.yaml": {"ARTIST_GENRE_MAP": {}}, "channel_genre.yaml": {"CHANNEL_GENRE_MAP": {}},
        "genre_hierarchy.yaml": {"GENRE_HIERARCHY": {}}, "genre_overrides.yaml": {"GENRE_OVERRIDES": {}},
        "genre_aliases.yaml": {"GENRE_ALIASES": {}}, "genre_rules.yaml": {"GENRE_RULES": []},
    }.items():
        (mapping / name).write_text(yaml.safe_dump(content), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "library").mkdir()
    monkeypatch.setattr(Config, "DATA_DIR", data)
    monkeypatch.setattr(Config, "GENRE_MAPPING_DIR", mapping)
    monkeypatch.setattr(Config, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(Config, "ARTIST_OVERRIDE_FILE", str(mapping / "artist_overrides.json"))

    async def candidate(*a, **k):
        return SimpleNamespace(primary="Hip Hop", secondary=["Deutschrap"], source="lastfm", raw_tags=[])

    monkeypatch.setattr(GenreProcessor, "_fetch_genre_from_lastfm", candidate)
    import services.clients.lastfm_client as lfm

    monkeypatch.setattr(lfm, "LastFMClient", lambda *a, **k: object())
    return SimpleNamespace(mapping=mapping, data=data)


def _in_process_subprocess(observed: dict):
    """Ersetzt _run_subprocess: fuehrt scripts/revalidate_genre.py::main() real aus
    (im Thread, weil main() asyncio.run() nutzt) und liefert dessen Exit-Code."""
    script = _load_script()

    async def fake_run_subprocess(cmd, timeout):
        observed["cmd"] = list(cmd)
        buf_out, buf_err = io.StringIO(), io.StringIO()

        def call():
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                try:
                    return script.main(list(cmd[2:]))
                except SystemExit as e:  # argparse-Fehler
                    return int(e.code or 0)

        code = await asyncio.to_thread(call)
        observed["lock_held_after_child"] = is_repair_running()
        return code, buf_out.getvalue(), buf_err.getvalue(), None, False

    return fake_run_subprocess


@pytest.mark.asyncio
async def test_apply_through_the_runner_does_not_deadlock_and_writes(env):
    observed = {}
    with patch.object(runner, "_run_subprocess", _in_process_subprocess(observed)):
        result = await runner.run_genre_revalidation_subprocess("Frischer Artist", apply=True)

    assert result.success, (result.exit_code, result.stderr_tail)
    assert result.outcome == "OVERTURN_ALLOWED" and result.mutated is True
    data = json.loads((env.mapping / "auto_learned_genre.json").read_text(encoding="utf-8"))
    assert data["ARTIST_GENRE_MAP"]["Frischer Artist"]["primary"] == "Hip Hop"
    assert is_repair_running() is False                      # Runner gibt den Lock am Ende frei


@pytest.mark.asyncio
async def test_child_never_releases_the_lock_it_does_not_own(env):
    observed = {}
    with patch.object(runner, "_run_subprocess", _in_process_subprocess(observed)):
        await runner.run_genre_revalidation_subprocess("Frischer Artist", apply=True)

    assert observed["lock_held_after_child"] is True         # Kind darf den Runner-Lock nicht freigeben


@pytest.mark.asyncio
async def test_preview_through_the_runner_still_writes_nothing(env):
    observed = {}
    with patch.object(runner, "_run_subprocess", _in_process_subprocess(observed)):
        result = await runner.run_genre_revalidation_subprocess("Frischer Artist", apply=False)

    assert result.success and result.outcome == "OVERTURN_ALLOWED" and result.mutated is False
    assert not (env.mapping / "auto_learned_genre.json").exists()
    assert "--apply" not in observed["cmd"]


@pytest.mark.asyncio
async def test_run_record_carries_the_real_initiator_instead_of_cli(env):
    observed = {}
    with patch.object(runner, "_run_subprocess", _in_process_subprocess(observed)):
        await runner.run_genre_revalidation_subprocess(
            "Frischer Artist", apply=True, triggered_by="control_center:42")

    records = [r for r in load_repair_history() if r.get("level") == "GENRE_REVALIDATION"]
    assert records and records[-1]["triggered_by"] == "control_center:42"
    assert records[-1]["artist"] == "Frischer Artist" and records[-1]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_default_triggered_by_stays_cli_for_existing_callers(env):
    observed = {}
    with patch.object(runner, "_run_subprocess", _in_process_subprocess(observed)):
        await runner.run_genre_revalidation_subprocess("Frischer Artist", apply=True)

    assert [r for r in load_repair_history() if r.get("level") == "GENRE_REVALIDATION"][-1]["triggered_by"] == "cli"


@pytest.mark.asyncio
async def test_a_second_run_while_the_runner_holds_the_lock_is_rejected(env):
    acquire_repair_lock()                                    # z. B. laufender Repair
    try:
        with pytest.raises(RepairAlreadyRunningError):
            await runner.run_genre_revalidation_subprocess("Frischer Artist", apply=True)
    finally:
        release_repair_lock()


def test_direct_cli_call_without_runner_still_takes_its_own_lock(env):
    """Der direkte CLI-Weg (kein Runner) behaelt seinen Lock-Schutz unveraendert."""
    acquire_repair_lock()
    try:
        with pytest.raises(RepairAlreadyRunningError):
            asyncio.run(run_genre_revalidation("Frischer Artist", apply=True, config=Config, lfm_client=object()))
    finally:
        release_repair_lock()


def test_direct_cli_call_releases_its_lock_after_writing(env):
    result = asyncio.run(run_genre_revalidation("Frischer Artist", apply=True, config=Config, lfm_client=object()))
    assert result.mutated is True and is_repair_running() is False
