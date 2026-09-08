# tests/test_library_repair_cli_safe_automatic_scope.py
# -*- coding: utf-8 -*-
"""Nachprüf-Durchgang 2026-09-09: der Telegram-Doctor-/Repair-MusicBot-Pfad
ruft `scripts/library_repair.py` ausschliesslich mit
`--level SAFE_AUTOMATIC --apply` auf (services/library_repair/doctor_runner.py::
run_safe_automatic_repair, services/library_repair/repair_service.py::
execute_safe_automatic_repair). Diese Tests pinnen die Sicherheitsgrenze:
über diesen Weg wird NIE `apply_level2()` (die volle Neuverarbeitung inkl.
`process_file(requested_issue=…)`) erreicht — weder über den
Planner-Level-Filter noch über das `l2_requested`-Gate in `main()`.

Doppelte Absicherung, deshalb zwei Ebenen:
  1. `filter_plan(level="SAFE_AUTOMATIC")` lässt L2-Kandidaten nicht durch.
  2. `l2_requested` in `main()` ist nur bei `--level METADATA_REPROCESSING`
     oder einem L2-`--issue` wahr — nicht bei `--level SAFE_AUTOMATIC`.
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
            "issue_code": "LYRICS_MISSING",  # -> METADATA_REPROCESSING (L2)
            "severity": "INFO",
            "scope": "file",
            "path": "A/Singles/2020 - x.m4a",
            "artist": "A",
            "title": "x",
        },
        {
            "issue_code": "GENRE_INVALID",  # -> METADATA_REPROCESSING (L2)
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
    calls = {"level1": 0, "level1_rename": 0, "level2": 0}

    import services.library_repair.executor as executor

    def _spy_l1(*a, **k):
        calls["level1"] += 1
        return []

    def _spy_l1_rename(*a, **k):
        calls["level1_rename"] += 1
        return []

    def _spy_l2(*a, **k):
        calls["level2"] += 1
        return []

    monkeypatch.setattr(executor, "apply_level1", _spy_l1)
    monkeypatch.setattr(executor, "apply_level1_rename", _spy_l1_rename)
    monkeypatch.setattr(executor, "apply_level2", _spy_l2)
    monkeypatch.setattr(lr, "_verification_scan", lambda *a, **k: 0)
    monkeypatch.setattr(lr, "_trigger_navidrome_scan", lambda *a, **k: None)
    return calls


def test_doctor_cli_args_never_invoke_level2(report_file, spies):
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
    assert spies["level2"] == 0
    # L1-Executoren laufen weiterhin (der Doctor repariert die
    # verlustfreien Tag-/Rename-Fixes).
    assert spies["level1"] == 1
    assert spies["level1_rename"] == 1


def test_explicit_l2_issue_still_reaches_level2(report_file, spies):
    """Gegenprobe: der CLI-only-Weg über einen L2-`--issue` erreicht
    `apply_level2()` weiterhin — die Grenze gilt nur für SAFE_AUTOMATIC."""
    exit_code = lr.main(
        [
            "--issue",
            "LYRICS_MISSING",
            "--apply",
            "--report",
            str(report_file),
            "--library",
            "/fake/library",
        ]
    )
    assert exit_code == 0
    assert spies["level2"] == 1
