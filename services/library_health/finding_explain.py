# services/library_health/finding_explain.py
# -*- coding: utf-8 -*-
"""
Finding-Erklaerung: WARUM ist ein Finding offen? (read-only)

Die persistierte Findings-Registry speichert nur `message` und die
Anzeigefelder eines Findings, nicht die Scanner-`details`
(services/library_health/findings.py::Finding). Fuer die Diagnose braucht der
Nutzer aber die Belege, auf denen die Entscheidung beruhte (bei
FILENAME_TITLE_MISMATCH: Dateiname-Stamm, Titel-Tag und die *normalisierten*
Werte, die tatsaechlich verglichen werden).

Diese Funktion rekonstruiert die Belege bei Bedarf **frisch von der Platte**:

    Finding (Registry)  ->  Datei (Pfad-Guard)  ->  read_tags()
        ->  compare_filename_to_title()  (dieselbe Funktion wie der Scanner)

Eigenschaften:
- Rein lesend: kein Registry-Write, kein Tag-Write, kein Scan, kein Netzwerk.
- Eine Quelle der Wahrheit: der Vergleich stammt aus
  file_analysis.compare_filename_to_title(), die auch der Scanner benutzt —
  die Erklaerung kann keine andere Entscheidung treffen als der Scan.
- Frisch statt gespeichert: hat sich die Datei seit dem Scan geaendert, zeigt
  die Erklaerung den aktuellen Stand (`matches=True` heisst dann: Finding
  ist veraltet). Der Titel zum Scan-Zeitpunkt steht als `title_at_scan` dabei.
- Kein Telegram-/Web-Bezug: Web (control_center/routers/findings.py) und
  Telegram sind gleichrangige duenne Clients dieser Service-Funktion.
- Nur der `finding_id` kommt vom Client; der Dateipfad stammt aus der
  Registry und wird trotzdem gegen die Library-Wurzel geprueft
  (Defense-in-Depth, Symlinks werden aufgeloest).

Erweiterbar: weitere Codes werden in `_EXPLAINERS` registriert. Unbekannte
Codes liefern `supported=False` (keine Fake-Analyse).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .file_analysis import compare_filename_to_title
from .findings import Finding
from .models import AnalysisState
from .tag_reader import TagData, read_tags

# file_status
FILE_OK = "ok"
FILE_NOT_APPLICABLE = "not_applicable"  # Code ohne Detailanalyse
FILE_NO_PATH = "no_path"
FILE_OUTSIDE_LIBRARY = "outside_library"
FILE_MISSING = "missing"
FILE_TAGS_UNREADABLE = "tags_unreadable"
FILE_NO_TITLE_TAG = "no_title_tag"

EVIDENCE_FILENAME_TITLE = "filename_title"

# Obergrenze fuer die Diff-Berechnung (SequenceMatcher ist superlinear);
# Titel-/Dateinamen liegen weit darunter.
_DIFF_MAX_CHARS = 2000


@dataclass
class FindingExplanation:
    finding_id: str
    code: str
    supported: bool
    file_status: str
    path: Optional[str] = None
    message: Optional[str] = None
    evidence_kind: Optional[str] = None
    evidence: Optional[dict] = None


def diff_segments(a: str, b: str) -> list[dict]:
    """Zeichengenauer Diff als Segmentliste
    `{"op": equal|replace|delete|insert, "a": <Teil aus a>, "b": <Teil aus b>}`.
    Reine Anzeigehilfe; `a`/`b` werden auf _DIFF_MAX_CHARS gekappt."""
    a, b = a[:_DIFF_MAX_CHARS], b[:_DIFF_MAX_CHARS]
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return [
        {"op": op, "a": a[i1:i2], "b": b[j1:j2]}
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
    ]


def _resolve_in_library(rel_path: object, library_root: Path) -> Optional[Path]:
    """Loest `rel_path` relativ zur Library-Wurzel auf und liefert das Ziel
    NUR, wenn es echt darunter liegt. Wirft nie."""
    if not isinstance(rel_path, str) or not rel_path or Path(rel_path).is_absolute():
        return None
    try:
        root = Path(library_root).resolve()
        target = (root / rel_path).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if target == root or root not in target.parents:
        return None
    return target


def _explain_filename_title(
    finding: Finding, target: Path, tag_reader: Callable[[Path], TagData]
) -> FindingExplanation:
    base = dict(
        finding_id=finding.finding_id, code=finding.code, supported=True, path=finding.path
    )
    tags = tag_reader(target)
    if tags.state in (AnalysisState.NOT_ANALYZABLE, AnalysisState.MISSING):
        return FindingExplanation(
            **base,
            file_status=FILE_TAGS_UNREADABLE,
            message=f"Tags nicht lesbar: {tags.error or tags.state.value}",
        )
    if tags.title is None or not str(tags.title).strip():
        return FindingExplanation(
            **base,
            file_status=FILE_NO_TITLE_TAG,
            message="Kein Titel-Tag gesetzt — der Titel-Vergleich entfaellt.",
        )
    comparison = compare_filename_to_title(target.stem, tags.title)
    evidence = dict(comparison)
    evidence["segments"] = diff_segments(
        comparison["normalized_remainder"], comparison["normalized_title"]
    )
    evidence["title_at_scan"] = finding.title
    return FindingExplanation(
        **base,
        file_status=FILE_OK,
        evidence_kind=EVIDENCE_FILENAME_TITLE,
        evidence=evidence,
    )


# Finding-Code -> Erklaerer. Neue Codes hier registrieren.
_EXPLAINERS: dict[str, Callable[[Finding, Path, Callable[[Path], TagData]], FindingExplanation]] = {
    "FILENAME_TITLE_MISMATCH": _explain_filename_title,
}


def supported_codes() -> tuple[str, ...]:
    return tuple(sorted(_EXPLAINERS))


def explain_finding(
    finding: Finding,
    library_root: Path,
    *,
    tag_reader: Optional[Callable[[Path], TagData]] = None,
) -> FindingExplanation:
    """Siehe Modul-Docstring. Wirft nie (`read_tags` faengt Container-Fehler
    selbst ab). `tag_reader=None` -> `read_tags` (zur Aufrufzeit aufgeloest,
    damit Tests es ersetzen koennen)."""
    tag_reader = tag_reader or read_tags
    explainer = _EXPLAINERS.get(finding.code)
    if explainer is None:
        return FindingExplanation(
            finding_id=finding.finding_id,
            code=finding.code,
            supported=False,
            file_status=FILE_NOT_APPLICABLE,
            path=finding.path,
            message="Fuer diesen Finding-Code gibt es keine Detailanalyse.",
        )

    base = dict(
        finding_id=finding.finding_id, code=finding.code, supported=True, path=finding.path
    )
    if not finding.path:
        return FindingExplanation(
            **base, file_status=FILE_NO_PATH, message="Das Finding hat keinen Dateipfad."
        )
    target = _resolve_in_library(finding.path, Path(library_root))
    if target is None:
        return FindingExplanation(
            **base,
            file_status=FILE_OUTSIDE_LIBRARY,
            message="Der Pfad liegt nicht innerhalb der Library.",
        )
    if not target.is_file():
        return FindingExplanation(
            **base,
            file_status=FILE_MISSING,
            message="Datei nicht mehr vorhanden (seit dem Scan verschoben, umbenannt oder geloescht).",
        )
    return explainer(finding, target, tag_reader)
