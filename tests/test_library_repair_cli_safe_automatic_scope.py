# tests/test_library_repair_cli_safe_automatic_scope.py
# -*- coding: utf-8 -*-
"""Nachprüf-Durchgang 2026-09-09 (aktualisiert in CC-LIB-FINAL): der
Telegram-Doctor-/Repair-MusicBot-Pfad ruft `scripts/library_repair.py`
ausschliesslich mit `--level SAFE_AUTOMATIC --apply` auf
(services/library_repair/doctor_runner.py::run_safe_automatic_repair,
services/library_repair/repair_service.py::execute_safe_automatic_repair).
Diese Tests pinnen die Sicherheitsgrenze: über diesen Weg wird nur L1
ausgeführt.

CC-LIB-FINAL: Die volle Neuverarbeitung (frueher `apply_level2()`, L2
METADATA_REPROCESSING) wurde entfernt. Auch ein expliziter L2-Aufruf
(`--level METADATA_REPROCESSING` bzw. `--issue LYRICS_MISSING`) darf
KEINEN Executor mehr erreichen — die Findings sind MANUAL_REVIEW bzw.
bei Lyrics NOT_REPAIRABLE (Korrektur 2026-09-27, kein Lyrics-Editor im
Control Center).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "library_repair.py"

_spec = importlib.util.spec_from_file_location("library_repair_cli_scope", MODULE_PATH)
lr = importlib.util.module_from_spec(_spec)
sys.modules["library_repair_cli_scope"] = lr
_spec.loader.exec_module(lr)


_REPORT = {
    "library": {"root": "/fake/library"},
    "health": {"score": 90.0},
    "issues": [
        {
            "issue_code": "GENRE_DELIMITER_INCONSISTENT",  # -> SAFE_AUTOMATIC (L1)
            "severity": "WARNING",
            "scope": "file",
            "path": "A/Singles/2020 - x.m4a",
            "artist": "A",
            "title": "x",
        },
        {
            "issue_code": "LYRICS_MISSING",  # -> NOT_REPAIRABLE (frueher L2, kein Lyrics-Editor)
            "severity": "INFO",
            "scope": "file",
            "path": "A/Singles/2020 - x.m4a",
            "artist": "A",
            "title": "x",
        },
        {
            "issue_code": "GENRE_INVALID",  # -> MANUAL_REVIEW (frueher L2)
            "severity": "INFO",
            "scope": "file",
            "path": "A/Singles/2020 - y.m4a",
            "artist": "A",
            "title": "y",
        },
    ],
}


@pytest.fixture
def report_file(tmp_path):
    p = tmp_path / "health_report.json"
    p.write_text(json.dumps(_REPORT), encoding="utf-8")
    return p


@pytest.fixture
def spies(monkeypatch):
    """Ersetzt die echten Executoren durch Aufruf-Spione und neutralisiert
    Verification-Scan + Navidrome-Trigger (kein echter Datei-/Netzwerk-I/O)."""
    calls = {"level1": 0, "level1_rename": 0}

    import services.library_repair.executor as executor

    def _spy_l1(*a, **k):
        calls["level1"] += 1
        return []

    def _spy_l1_rename(*a, **k):
        calls["level1_rename"] += 1
        return []

    monkeypatch.setattr(executor, "apply_level1", _spy_l1)
    monkeypatch.setattr(executor, "apply_level1_rename", _spy_l1_rename)
    monkeypatch.setattr(lr, "_verification_scan", lambda *a, **k: 0)
    monkeypatch.setattr(lr, "_trigger_navidrome_scan", lambda *a, **k: None)
    return calls


def test_doctor_cli_args_run_only_level1(report_file, spies):
    """Die exakten Doctor-/Repair-MusicBot-Argumente."""
    exit_code = lr.main(
        [
            "--level",
            "SAFE_AUTOMATIC",
            "--apply",
            "--report",
            str(report_file),
            "--library",
            "/fake/library",
        ]
    )
    assert exit_code == 0
    # L1-Executoren laufen weiterhin (der Doctor repariert die
    # verlustfreien Tag-/Rename-Fixes).
    assert spies["level1"] == 1
    assert spies["level1_rename"] == 1


def test_executor_has_no_level2_entrypoint():
    """CC-LIB-FINAL: es gibt keinen L2-Executor mehr, den ein Spy oder die
    CLI erreichen koennte."""
    import services.library_repair.executor as executor

    assert not hasattr(executor, "apply_level2")


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--issue", "LYRICS_MISSING"],
        ["--issue", "GENRE_INVALID"],
        ["--level", "METADATA_REPROCESSING"],
    ],
)
def test_former_l2_selection_reaches_no_executor(report_file, spies, extra_args):
    """Auch ein ausdruecklicher Aufruf mit dem frueheren L2-Selektor darf
    nichts mehr ausfuehren: die Codes sind MANUAL_REVIEW bzw. bei Lyrics
    NOT_REPAIRABLE, der Plan enthaelt fuer diesen Selektor keine
    ausfuehrbaren Reparaturen."""
    exit_code = lr.main(
        [
            *extra_args,
            "--apply",
            "--report",
            str(report_file),
            "--library",
            "/fake/library",
        ]
    )
    assert exit_code == 0
    assert spies["level1"] == 0
    assert spies["level1_rename"] == 0
