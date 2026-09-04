# services/library_health/report.py
# -*- coding: utf-8 -*-
"""
Report-Aufbau + Serialisierung (Prompt Abschnitt 24-26 / Phase 1F).

Erzeugt eine stabile, versionierte, maschinenlesbare Struktur (dict, direkt
json.dump-faehig) plus einen human-readable Text-Report.

Determinismus (Prompt Abschnitt 35): Dateien nach relative_path, Issues
nach (Severity desc, Code, Pfad). Zeitstempel duerfen variieren, der
Analyseinhalt nicht.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import (
    SCANNER_VERSION,
    SCHEMA_VERSION,
    AnalysisState,
    FileHealth,
    Issue,
    Severity,
    severity_rank,
)

# Analysen, die erst in spaeteren PRs dieses Phase-1-Zweigs dazukommen —
# im Report ausdruecklich als "noch nicht analysiert" ausgewiesen, statt
# irrefuehrend 0 zu melden.
PENDING_ANALYSES = (
    "health_score",
)


def _max_severity(issues: Iterable[Issue]) -> Severity | None:
    best: Severity | None = None
    for issue in issues:
        if best is None or severity_rank(issue.severity) > severity_rank(best):
            best = issue.severity
    return best


def _file_bucket(fh: FileHealth) -> str:
    not_analyzable = any(
        fh.states.get(k) == AnalysisState.NOT_ANALYZABLE for k in ("metadata", "audio")
    )
    if not_analyzable:
        return "not_analyzable"
    sev = _max_severity(fh.issues)
    if sev in (Severity.ERROR, Severity.CRITICAL):
        return "errors"
    if sev == Severity.WARNING:
        return "warnings"
    return "healthy"  # keine Issues oder nur INFO


def build_statistics(
    file_healths: list[FileHealth],
    all_issues: list[Issue],
    group_issues: list[Issue] | None = None,
) -> dict:
    group_issues = group_issues or []
    artists = {fh.record.artist_directory for fh in file_healths if fh.record.artist_directory}
    albums = {
        (fh.record.artist_directory, fh.record.album_directory)
        for fh in file_healths
        if fh.record.album_directory
    }

    buckets = Counter(_file_bucket(fh) for fh in file_healths)
    code_counter = Counter(i.code for i in all_issues)
    sev_counter = Counter(i.severity.value for i in all_issues)

    def _count_state(dimension: str, *states: AnalysisState) -> int:
        return sum(1 for fh in file_healths if fh.states.get(dimension) in states)

    def _count_code(code: str) -> int:
        return code_counter.get(code, 0)

    return {
        "total_files": len(file_healths),
        "total_artists": len(artists),
        "total_albums": len(albums),
        "healthy_files": buckets.get("healthy", 0),
        "files_with_warnings": buckets.get("warnings", 0),
        "files_with_errors": buckets.get("errors", 0),
        "files_not_analyzable": buckets.get("not_analyzable", 0),
        "missing_metadata": _count_state(
            "metadata", AnalysisState.MISSING, AnalysisState.PARTIAL
        ),
        "missing_artwork": _count_code("ARTWORK_MISSING"),
        "missing_lyrics": _count_code("LYRICS_MISSING"),
        "missing_loudness": _count_code("LOUDNESS_TAG_MISSING"),
        "structure_problems": _count_code("STRUCTURE_INVALID_PATH")
        + _count_code("STRUCTURE_FILE_OUTSIDE_HIERARCHY"),
        "audio_problems": _count_code("AUDIO_NOT_ANALYZABLE")
        + _count_code("AUDIO_NO_STREAM")
        + _count_code("AUDIO_CORRUPT"),
        "duplicate_groups": sum(
            1 for i in group_issues
            if i.code in ("DUPLICATE_EXACT", "DUPLICATE_RECORDING", "DUPLICATE_SUSPECTED")
        ),
        "duplicate_groups_by_kind": {
            "exact": sum(1 for i in group_issues if i.code == "DUPLICATE_EXACT"),
            "recording": sum(1 for i in group_issues if i.code == "DUPLICATE_RECORDING"),
            "suspected": sum(1 for i in group_issues if i.code == "DUPLICATE_SUSPECTED"),
        },
        "album_inconsistencies": sum(1 for i in group_issues if i.code.startswith("ALBUM_")),
        "artist_inconsistencies": sum(1 for i in group_issues if i.code.startswith("ARTIST_")),
        "issues_by_code": dict(sorted(code_counter.items())),
        "issues_by_severity": {
            sev.value: sev_counter.get(sev.value, 0)
            for sev in (Severity.CRITICAL, Severity.ERROR, Severity.WARNING, Severity.INFO)
        },
    }


def build_report_dict(
    *,
    library_root: str,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    file_healths: list[FileHealth],
    group_issues: list[Issue] | None = None,
) -> dict:
    group_issues = sorted(group_issues or [], key=lambda i: i.sort_key())
    file_healths = sorted(file_healths, key=lambda fh: fh.record.relative_path)
    all_issues: list[Issue] = list(group_issues)
    for fh in file_healths:
        all_issues.extend(fh.issues)
    all_issues.sort(key=lambda i: i.sort_key())

    stats = build_statistics(file_healths, all_issues, group_issues)

    return {
        "schema_version": SCHEMA_VERSION,
        "scanner_version": SCANNER_VERSION,
        "scan": {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round(duration_seconds, 3),
            "pending_analyses": list(PENDING_ANALYSES),
        },
        "library": {
            "root": library_root,
            "files": stats["total_files"],
            "artists": stats["total_artists"],
            "albums": stats["total_albums"],
        },
        "health": {
            "score": None,             # PENDING_ANALYSES (PR3)
            "status": "UNSCORED",
        },
        "statistics": stats,
        "issues": [i.to_dict() for i in all_issues],
        "files": [fh.to_dict() for fh in file_healths],
    }


# ─────────────────────────────────────────────────────────────────────────
# Human-readable
# ─────────────────────────────────────────────────────────────────────────


def render_text(report: dict, *, max_issues: int = 200) -> str:
    s = report["statistics"]
    lines: list[str] = []
    add = lines.append

    add("=" * 70)
    add("MUSIC LIBRARY HEALTH REPORT")
    add("=" * 70)
    add(f"Schema:     {report['schema_version']}  (scanner {report['scanner_version']})")
    add(f"Library:    {report['library']['root']}")
    add(f"Scanned:    {report['scan']['started_at']} → {report['scan']['completed_at']}"
        f"  ({report['scan']['duration_seconds']}s)")
    add("")
    add(f"Files:      {s['total_files']}")
    add(f"Artists:    {s['total_artists']}")
    add(f"Albums:     {s['total_albums']}")
    add("")
    add(f"  healthy (INFO only) : {s['healthy_files']}")
    add(f"  with warnings       : {s['files_with_warnings']}")
    add(f"  with errors         : {s['files_with_errors']}")
    add(f"  not analyzable      : {s['files_not_analyzable']}")
    add("")
    add("Missing / problems:")
    add(f"  metadata incomplete : {s['missing_metadata']}")
    add(f"  artwork missing     : {s['missing_artwork']}")
    add(f"  lyrics missing      : {s['missing_lyrics']}")
    add(f"  loudness tag missing: {s['missing_loudness']}")
    add(f"  structure problems  : {s['structure_problems']}")
    add(f"  audio problems      : {s['audio_problems']}")
    add("")
    add("Groups:")
    add(f"  duplicate groups    : {s['duplicate_groups']}  "
        f"(exact {s['duplicate_groups_by_kind']['exact']}, "
        f"recording {s['duplicate_groups_by_kind']['recording']}, "
        f"suspected {s['duplicate_groups_by_kind']['suspected']})")
    add(f"  album inconsistencies : {s['album_inconsistencies']}")
    add(f"  artist inconsistencies: {s['artist_inconsistencies']}")
    add("")
    add("Issues by severity:")
    for sev, count in s["issues_by_severity"].items():
        add(f"  {sev:<9}: {count}")
    add("")
    add("Issues by code:")
    for code, count in s["issues_by_code"].items():
        add(f"  {code:<32}: {count}")
    add("")
    add(f"Health score: {report['health']['status']} "
        f"(pending: {', '.join(report['scan']['pending_analyses'])})")
    add("")
    add("-" * 70)
    add(f"ISSUES (top {max_issues} of {len(report['issues'])}, most severe first)")
    add("-" * 70)
    for issue in report["issues"][:max_issues]:
        loc = issue["path"] or issue["artist"] or issue["album"] or "-"
        add(f"[{issue['severity']:<8}] {issue['issue_code']:<30} {loc}")
        add(f"           {issue['message']}")
    if len(report["issues"]) > max_issues:
        add(f"... {len(report['issues']) - max_issues} weitere Issues (siehe JSON-Report)")
    add("")
    return "\n".join(lines)
