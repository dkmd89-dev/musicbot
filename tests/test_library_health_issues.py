# tests/test_library_health_issues.py
# -*- coding: utf-8 -*-
"""Issue-Code-Register: Vollstaendigkeit + Stabilitaet (Prompt Abschnitt 20)."""

import re
from pathlib import Path

import pytest

from services.library_health import file_analysis, report
from services.library_health.issues import ALL_CODES, REGISTRY, make_issue
from services.library_health.models import Scope, Severity

_SRC_DIR = Path(file_analysis.__file__).parent


def _codes_referenced_in(module_file: str) -> set[str]:
    text = (_SRC_DIR / module_file).read_text(encoding="utf-8")
    return set(re.findall(r'make_issue\(\s*["\']([A-Z0-9_]+)["\']', text))


_EMITTING_MODULES = ("file_analysis.py", "group_analysis.py")


def _all_referenced() -> set[str]:
    out: set[str] = set()
    for mod in _EMITTING_MODULES:
        out |= _codes_referenced_in(mod)
    return out


def test_every_emitted_code_is_registered():
    referenced = _all_referenced()
    assert referenced, "Regex hat keine make_issue-Aufrufe gefunden"
    unregistered = referenced - ALL_CODES
    assert not unregistered, f"Nicht im Register: {sorted(unregistered)}"


def test_registry_has_no_unused_dead_codes():
    # Der Health-Score (PR 3) fuegt keine Issue-Codes hinzu — jeder
    # registrierte Code muss von file_analysis.py oder group_analysis.py
    # tatsaechlich erzeugt werden.
    dead = ALL_CODES - _all_referenced()
    assert not dead, f"Registriert, aber nirgends erzeugt: {sorted(dead)}"


def test_codes_are_uppercase_snake_and_unique():
    for code in ALL_CODES:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]+", code), code
    assert len(ALL_CODES) == len(REGISTRY)


def test_make_issue_unknown_code_raises():
    with pytest.raises(KeyError):
        make_issue("TOTALLY_UNKNOWN_CODE")


def test_make_issue_defaults_from_registry():
    issue = make_issue("META_ARTIST_MISSING", path="x/y.m4a")
    assert issue.severity == Severity.ERROR
    assert issue.scope == Scope.FILE
    assert issue.path == "x/y.m4a"
    assert issue.message  # nicht leer


def test_severity_override_is_respected():
    issue = make_issue("META_TRACK_NUMBER_MISSING", severity=Severity.WARNING)
    assert issue.severity == Severity.WARNING


def test_loudness_missing_default_is_info():
    # Prompt Abschnitt 16/22: fehlender Loudness-Tag ist bei aktueller
    # Pipeline normal — NIEMALS ein Defect.
    assert REGISTRY["LOUDNESS_TAG_MISSING"].default_severity == Severity.INFO
