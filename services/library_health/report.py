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

from .file_analysis import _split_genres
from .issues import REGISTRY
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
PENDING_ANALYSES: tuple[str, ...] = ()


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

    genre_counter: Counter = Counter()
    for fh in file_healths:
        if fh.genre:
            genre_counter.update(_split_genres(fh.genre))

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
        "genre_distribution": dict(sorted(genre_counter.items())),
    }


def build_report_dict(
    *,
    library_root: str,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    file_healths: list[FileHealth],
    group_issues: list[Issue] | None = None,
    health_section: dict | None = None,
) -> dict:
    group_issues = sorted(group_issues or [], key=lambda i: i.sort_key())
    file_healths = sorted(file_healths, key=lambda fh: fh.record.relative_path)
    all_issues: list[Issue] = list(group_issues)
    for fh in file_healths:
        all_issues.extend(fh.issues)
    all_issues.sort(key=lambda i: i.sort_key())

    stats = build_statistics(file_healths, all_issues, group_issues)

    health_section = health_section or {}
    file_scores: dict = health_section.get("file_scores", {})

    files_out = []
    for fh in file_healths:
        entry = fh.to_dict()
        entry["file_health_score"] = file_scores.get(fh.record.relative_path)
        files_out.append(entry)

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
            "score": health_section.get("score"),
            "status": health_section.get("status", "UNSCORED"),
            "weights": health_section.get("weights"),
        },
        "statistics": stats,
        "issues": [i.to_dict() for i in all_issues],
        "artists": health_section.get("artists", []),
        "albums": health_section.get("albums", []),
        "files": files_out,
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
    h = report["health"]
    add(f"HEALTH SCORE: {h['score']}  ({h['status']})")
    worst_artists = sorted(
        (a for a in report.get("artists", []) if a["health_score"] is not None),
        key=lambda a: a["health_score"],
    )[:10]
    if worst_artists:
        add("  schwaechste Artists:")
        for a in worst_artists:
            add(f"    {a['health_score']:>5}  {a['artist']}  "
                f"({a['file_count']} Dateien, {a['album_count']} Alben)")
    worst_albums = sorted(
        (al for al in report.get("albums", []) if al["health_score"] is not None),
        key=lambda al: al["health_score"],
    )[:10]
    if worst_albums:
        add("  schwaechste Alben:")
        for al in worst_albums:
            add(f"    {al['health_score']:>5}  {al['artist']} — {al['album']}")
    add("")
    add("Issues by severity:")
    for sev, count in s["issues_by_severity"].items():
        add(f"  {sev:<9}: {count}")
    add("")
    add("Issues by code:")
    for code, count in s["issues_by_code"].items():
        add(f"  {code:<32}: {count}")
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


# ─────────────────────────────────────────────────────────────────────────
# Markdown-Zusammenfassung (library_health_summary.md)
# ─────────────────────────────────────────────────────────────────────────
#
# Reines Rendering eines bereits fertigen `report`-Dicts (kein Scan, keine
# I/O, keine Fachlogik) - identisches Prinzip wie render_text() oben.
# Enthaelt bewusst KEINE aktuellen Library-Werte (Kuenstlernamen, Pfade,
# Zahlen) - alles wird ausschliesslich aus dem uebergebenen `report`
# gelesen, damit dieselbe Funktion bei jeder beliebigen Library ein
# korrektes Ergebnis liefert (siehe Tests: Determinismus + "keine
# Hardcodes").

_SEVERITY_RECOMMENDATION: dict[str, str] = {
    "CRITICAL": "sofort prüfen",
    "ERROR": "zeitnah korrigieren",
    "WARNING": "prüfen / validieren",
    "INFO": "optionale Datenanreicherung",
}

# Kurze, stabile Zusatz-Hinweise fuer einzelne, bereits im Registry
# etablierte Issue-Codes (services/library_health/issues.py) - keine
# aktuellen Befunde, nur generische Handlungsempfehlung pro Code-Klasse.
# Ein Code ohne Eintrag hier faellt auf die reine Severity-Empfehlung
# zurueck (_SEVERITY_RECOMMENDATION) - kein Crash, keine Sonderbehandlung
# noetig.
_CODE_RECOMMENDATION: dict[str, str] = {
    "ALBUM_TRACK_GAP": (
        "Review erforderlich - fehlende Tracknummern können auch "
        "beabsichtigt sein (z. B. kuratierte Auswahl, Vinyl-Rip)."
    ),
    "ALBUM_DUPLICATE_TRACK_NUMBER": (
        "Handlungsbedarf - Tracknummern-Konflikt im Album prüfen und "
        "korrigieren."
    ),
    "ARTWORK_MISSING": "Cover-Reparatur prüfen (z. B. über Library Repair).",
    "ARTWORK_INVALID": (
        "Handlungsbedarf - eingebettetes Cover ist beschädigt/nicht "
        "dekodierbar."
    ),
    "DUPLICATE_EXACT": (
        "Handlungsbedarf - byte-identische Datei, Duplikat-Bereinigung "
        "prüfen."
    ),
    "DUPLICATE_RECORDING": (
        "Review erforderlich - keine automatische Löschung empfehlen, "
        "manuell prüfen."
    ),
    "DUPLICATE_SUSPECTED": (
        "Verdachtsfall - reine Beobachtung, keine automatische Aktion."
    ),
}

_MD_ESCAPE_CHARS = ("\\", "*", "_", "`", "[", "]", "|")


def _md_escape(text: object) -> str:
    """Neutralisiert Markdown-Sonderzeichen in freiem Text (Artist/Album/
    Titel/Message) - verhindert, dass z.B. ein '*' im Artist-Namen als
    Formatierung interpretiert wird. Unicode bleibt unveraendert."""
    if text is None:
        return ""
    s = str(text)
    for ch in _MD_ESCAPE_CHARS:
        s = s.replace(ch, "\\" + ch)
    return s.replace("\n", " ").replace("\r", " ")


def _md_code(text: object) -> str:
    """Wrappt Pfade/Dateinamen als Inline-Code - nutzt einen breiteren
    Backtick-Zaun, falls der Text selbst ein Backtick enthaelt."""
    if text is None:
        return "`-`"
    s = str(text).replace("\n", " ").replace("\r", " ")
    fence = "``" if "`" in s else "`"
    return f"{fence}{s}{fence}"


def _format_duration(seconds: object) -> str:
    if seconds is None:
        return "-"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m {rest}s"


def _format_score(score: object) -> str:
    if score is None:
        return "–"
    try:
        return f"{float(score):.1f}"
    except (TypeError, ValueError):
        return "–"


def _issue_recommendation(code: str, severity: str) -> str:
    return _CODE_RECOMMENDATION.get(code) or _SEVERITY_RECOMMENDATION.get(
        severity, "prüfen"
    )


def _issue_description(code: str) -> str:
    """Bedeutungstext fuer INFO-Aggregation - kommt aus der bestehenden
    Issue-Registry (Single Source of Truth), niemals neu erfunden. Nur
    fuer der Registry unbekannte Codes ein stabiler, generischer
    Fallback-Text (kein Rate-Text, keine aktuellen Befunde)."""
    spec = REGISTRY.get(code)
    if spec is not None:
        return spec.description
    return "Keine Beschreibung in der Issue-Registry hinterlegt."


def _group_issues_by_code(issues: list[dict]) -> "dict[str, list[dict]]":
    """Erhaelt die bereits im Report etablierte Reihenfolge (Severity
    absteigend, dann Code, dann Pfad) - da alle Issues eines Codes durch
    diese Sortierung bereits zusammenhaengend sind, ergibt ein einfacher
    Insertion-Order-Dict automatisch stabil sortierte Gruppen."""
    grouped: "dict[str, list[dict]]" = {}
    for issue in issues:
        grouped.setdefault(issue.get("issue_code", "UNKNOWN"), []).append(issue)
    return grouped


def _render_issue_detail(issue: dict) -> list[str]:
    """Rendert einen einzelnen Issue-Fund als Detail-Block (Abschnitt 5
    der Aufgabe: Artist/Album/Titel/Pfad/Message/Details/Related Files/
    Confidence) - robust gegenueber fehlenden optionalen Feldern."""
    out: list[str] = []
    if issue.get("artist"):
        out.append(f"**Artist:** {_md_escape(issue['artist'])}")
    if issue.get("album"):
        out.append(f"**Album:** {_md_escape(issue['album'])}")
    if issue.get("title"):
        out.append(f"**Titel:** {_md_escape(issue['title'])}")
    if issue.get("path"):
        out.append(f"**Datei:** {_md_code(issue['path'])}")
    related = issue.get("related_files") or []
    if related:
        out.append("")
        out.append("Betroffene Dateien:")
        out.append("")
        for rel in related:
            out.append(f"- {_md_code(rel)}")
    out.append("")
    if issue.get("message"):
        out.append(f"**Problem:** {_md_escape(issue['message'])}")
    details = issue.get("details") or {}
    if details:
        rendered_details = ", ".join(
            f"{_md_escape(k)}: {_md_escape(v)}" for k, v in sorted(details.items())
        )
        out.append(f"**Details:** {rendered_details}")
    if issue.get("confidence"):
        out.append(f"**Confidence-Hinweis:** {_md_escape(issue['confidence'])}")
    out.append(
        f"**Bewertung:** {_issue_recommendation(issue.get('issue_code', ''), issue.get('severity', ''))}"
    )
    return out


def _render_code_groups(
    grouped: "dict[str, list[dict]]", *, max_examples_per_code: int
) -> list[str]:
    out: list[str] = []
    for code, code_issues in grouped.items():
        out.append(f"### {code} ({len(code_issues)} Befund(e))")
        out.append("")
        shown = code_issues[:max_examples_per_code]
        for idx, issue in enumerate(shown):
            out.extend(_render_issue_detail(issue))
            if idx < len(shown) - 1:
                out.append("")
                out.append("---")
                out.append("")
        remaining = len(code_issues) - len(shown)
        if remaining > 0:
            out.append("")
            out.append(
                f"... {remaining} weitere {code}-Befund(e) (siehe JSON-Report)."
            )
        out.append("")
    return out


# Statuswerte, die ein annotiertes Issue tragen kann (siehe
# services/library_health/findings.py::annotate_issues_with_findings()).
# Hier bewusst nicht aus findings.py importiert, um report.py frei von
# einer Abhaengigkeit auf das Findings-Schema zu halten (report.py bleibt
# reines Rendering, kennt nur die additiven String-Felder auf dem Issue-
# Dict) - beide Module muessen bei einer kuenftigen Statuswert-Aenderung
# gemeinsam aktualisiert werden.
_FINDING_STATUS_RESOLVED = "RESOLVED"
_FINDING_STATUS_FALSE_POSITIVE = "FALSE_POSITIVE"


def _split_issues_by_finding_status(
    issues: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Trennt Issues nach `finding_status` in (offen, repariert, akzeptiert)
    — im Report gerendert als 🔴 Offen / 🟢 Repariert / ⚪ Akzeptiert
    (`RESOLVED` bzw. `FALSE_POSITIVE`, siehe docs/LIBRARY_HEALTH.md §1a).

    Ein Issue OHNE `finding_status`-Feld gilt als offen - das ist der
    Normalfall fuer jeden Report, der (noch) keine Findings-Registry-
    Integration durchlaufen hat (siehe CLI), und macht render_summary_markdown()
    dadurch byte-kompatibel zum Verhalten vor Einfuehrung des
    Findings-Systems."""
    open_: list[dict] = []
    resolved: list[dict] = []
    false_positive: list[dict] = []
    for issue in issues:
        status = issue.get("finding_status")
        if status == _FINDING_STATUS_RESOLVED:
            resolved.append(issue)
        elif status == _FINDING_STATUS_FALSE_POSITIVE:
            false_positive.append(issue)
        else:
            open_.append(issue)
    return open_, resolved, false_positive


def render_summary_markdown(report: dict, *, max_examples_per_code: int = 20) -> str:
    """Rendert eine menschlich lesbare Markdown-Zusammenfassung aus einem
    bereits fertigen Health-Report-Dict (siehe build_report_dict()).

    Reines Rendering, keine Scan-Logik, keine I/O - identisches Prinzip
    wie render_text(). Alle Werte kommen ausschliesslich aus `report`,
    keine aktuellen Library-Werte sind hier hardcodiert (siehe Modul-
    Docstring dieses Abschnitts).
    """
    scan = report.get("scan") or {}
    health = report.get("health") or {}
    library = report.get("library") or {}
    stats = report.get("statistics") or {}
    issues = report.get("issues") or []
    sev_counts = stats.get("issues_by_severity") or {}

    # Findings-Review-Integration (siehe services/library_health/findings.py):
    # report["findings"] existiert nur, wenn der Aufrufer (CLI) die Issues
    # zuvor per annotate_issues_with_findings() mit "finding_status"
    # anreichert hat. Fehlt dieses Feld komplett (z.B. alle bisherigen
    # Tests/Aufrufer dieser Funktion, oder ein Report ohne Findings-
    # Integration), verhaelt sich diese Funktion BYTE-IDENTISCH zum
    # bisherigen Stand: open_issues == issues, keine der neuen
    # Status-Sektionen wird gerendert (siehe _split_issues_by_finding_status()).
    findings_meta = report.get("findings")
    open_issues, resolved_issues, false_positive_issues = (
        _split_issues_by_finding_status(issues)
    )

    lines: list[str] = []
    add = lines.append

    add("# Library Health – Zusammenfassung")
    add("")
    add(f"**Scan:** {scan.get('started_at', '-')} → {scan.get('completed_at', '-')}")
    add(f"**Dauer:** {_format_duration(scan.get('duration_seconds'))}")
    add("")
    add(
        f"**Score:** {_format_score(health.get('score'))} / 100 — "
        f"{health.get('status', 'UNSCORED')}"
    )
    add("")
    add(f"**Dateien:** {library.get('files', stats.get('total_files', 0))}")
    add(f"**Artists:** {library.get('artists', stats.get('total_artists', 0))}")
    add(f"**Alben:** {library.get('albums', stats.get('total_albums', 0))}")
    add("")

    add("## Gesamtbild")
    add("")
    add(f"- {stats.get('healthy_files', 0)} healthy")
    add(f"- {sev_counts.get('CRITICAL', 0)} critical")
    add(f"- {sev_counts.get('ERROR', 0)} error")
    add(f"- {sev_counts.get('WARNING', 0)} warnings")
    add(f"- {sev_counts.get('INFO', 0)} info")
    dup_kinds = stats.get("duplicate_groups_by_kind") or {}
    if stats.get("duplicate_groups"):
        add(
            f"- {stats.get('duplicate_groups', 0)} Duplikat-Gruppen "
            f"(exact {dup_kinds.get('exact', 0)}, "
            f"recording {dup_kinds.get('recording', 0)}, "
            f"suspected {dup_kinds.get('suspected', 0)})"
        )
    add("")

    if findings_meta:
        add("## 📋 Befundstatus")
        add("")
        add("| Status | Anzahl |")
        add("|---|---:|")
        add(f"| 🔴 Offen | {len(open_issues)} |")
        add(f"| 🟢 Repariert | {len(resolved_issues)} |")
        add(f"| ⚪ Akzeptiert | {len(false_positive_issues)} |")
        add("")

    # ── Buckets bestimmen (Abschnitt 6/7 der Aufgabe: dynamisch, nicht
    # per "if issue_code == ..."). Ein Code landet in "confidence", sobald
    # MINDESTENS ein OFFENES Issue dieses Codes ein confidence-Feld
    # traegt - verhindert, dass derselbe Code je nach Einzelinstanz in
    # zwei verschiedenen Abschnitten auftaucht. Ab hier wird bewusst nur
    # noch mit `open_issues` gearbeitet (Abschnitt 15/17 der Aufgabe:
    # bereits bewertete Befunde bekommen eigene, kompakte Abschnitte
    # weiter unten statt hier erneut als "zu bearbeiten" aufzutauchen) -
    # ohne Findings-Integration ist open_issues == issues, also identisch
    # zum bisherigen Verhalten.
    codes_with_confidence = {
        i.get("issue_code") for i in open_issues if i.get("confidence")
    }

    errors: list[dict] = []
    confidence_issues: list[dict] = []
    warnings: list[dict] = []
    info_issues: list[dict] = []
    for issue in open_issues:
        sev = issue.get("severity")
        code = issue.get("issue_code")
        if sev in ("CRITICAL", "ERROR"):
            errors.append(issue)
        elif code in codes_with_confidence:
            confidence_issues.append(issue)
        elif sev == "WARNING":
            warnings.append(issue)
        else:
            info_issues.append(issue)

    if errors:
        add("## 🔴 Offene Fehler" if findings_meta else "## 🔴 Fehler")
        add("")
        lines.extend(
            _render_code_groups(
                _group_issues_by_code(errors),
                max_examples_per_code=max_examples_per_code,
            )
        )

    if warnings:
        add("## 🟠 Offene Warnungen" if findings_meta else "## 🟠 Warnungen")
        add("")
        lines.extend(
            _render_code_groups(
                _group_issues_by_code(warnings),
                max_examples_per_code=max_examples_per_code,
            )
        )

    if confidence_issues:
        add(
            "## 🔎 Offene Vermutete / Confidence-Befunde"
            if findings_meta
            else "## 🔎 Vermutete / Confidence-Befunde"
        )
        add("")
        add(
            "Keine gesicherten Fehler - reine Beobachtungen mit "
            "Unsicherheit, keine automatische Aktion empfohlen."
        )
        add("")
        lines.extend(
            _render_code_groups(
                _group_issues_by_code(confidence_issues),
                max_examples_per_code=max_examples_per_code,
            )
        )

    if info_issues:
        add("## ℹ️ INFO / Datenanreicherung")
        add("")
        add("| Issue | Anzahl | Bedeutung |")
        add("|---|---:|---|")
        info_grouped = _group_issues_by_code(info_issues)
        for code, code_issues in sorted(
            info_grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            add(
                f"| {_md_code(code)} | {len(code_issues)} | "
                f"{_md_escape(_issue_description(code))} |"
            )
        add("")

    if resolved_issues:
        add("## 🟢 Reparierte Befunde")
        add("")
        add("| Issue | Anzahl | Zuletzt geprüft |")
        add("|---|---:|---|")
        for code, code_issues in sorted(
            _group_issues_by_code(resolved_issues).items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        ):
            reviewed_at = next(
                (i.get("finding_reviewed_at") for i in code_issues if i.get("finding_reviewed_at")),
                None,
            )
            add(f"| {_md_code(code)} | {len(code_issues)} | {_md_escape(reviewed_at or '-')} |")
        add("")

    if false_positive_issues:
        add("## ⚪ Akzeptierte Befunde")
        add("")
        add("| Issue | Anzahl | Notiz |")
        add("|---|---:|---|")
        for code, code_issues in sorted(
            _group_issues_by_code(false_positive_issues).items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        ):
            note = next(
                (i.get("finding_review_note") for i in code_issues if i.get("finding_review_note")),
                None,
            )
            add(f"| {_md_code(code)} | {len(code_issues)} | {_md_escape(note or '-')} |")
        add("")

    genre_distribution = stats.get("genre_distribution") or {}
    if genre_distribution:
        top_genres = sorted(
            genre_distribution.items(), key=lambda kv: (-kv[1], kv[0])
        )[:5]
        add("## 🎵 Top 5 Genres")
        add("")
        for idx, (genre, count) in enumerate(top_genres, start=1):
            add(f"{idx}. {_md_escape(genre)} — {count}")
        add("")

    add("## 📋 Priorität / Empfehlung")
    add("")
    priority_tiers = [
        (
            "CRITICAL",
            [i for i in errors if i.get("severity") == "CRITICAL"],
            "sofort prüfen",
        ),
        (
            "ERROR",
            [i for i in errors if i.get("severity") == "ERROR"],
            "zeitnah korrigieren",
        ),
        ("WARNING", warnings, "prüfen / validieren"),
        (
            "VERDACHTSFALL",
            confidence_issues,
            "manuelle Prüfung, keine automatische Aktion",
        ),
        ("INFO", info_issues, "optionale Datenanreicherung"),
    ]
    priority_lines = []
    for label, tier_issues, hint in priority_tiers:
        if not tier_issues:
            continue
        codes = sorted({i.get("issue_code", "?") for i in tier_issues})
        priority_lines.append(
            f"{label}: {hint} ({len(tier_issues)} Befund(e): {', '.join(codes)})"
        )
    if priority_lines:
        for idx, line in enumerate(priority_lines, start=1):
            add(f"{idx}. {line}")
    else:
        add("Keine dringenden Maßnahmen erforderlich.")
    add("")

    add("## Fazit")
    add("")
    total_critical = sev_counts.get("CRITICAL", 0)
    total_error = sev_counts.get("ERROR", 0)
    total_warning = sev_counts.get("WARNING", 0)
    total_info = sev_counts.get("INFO", 0)
    status = health.get("status", "UNSCORED")
    score_text = _format_score(health.get("score"))
    if total_critical or total_error:
        fazit = (
            f"Die Library befindet sich in einem {status}-Zustand "
            f"(Score {score_text}/100) mit {total_critical} kritischen und "
            f"{total_error} Fehler-Befunden, die Handlungsbedarf anzeigen."
        )
    elif total_warning or confidence_issues:
        fazit = (
            f"Die Library befindet sich in einem {status}-Zustand "
            f"(Score {score_text}/100). Keine kritischen Fehler, aber "
            f"{total_warning} Warnungen"
            + (f" und {len(confidence_issues)} Verdachtsfälle" if confidence_issues else "")
            + " sollten geprüft werden."
        )
    else:
        fazit = (
            f"Die Library befindet sich in einem {status}-Zustand "
            f"(Score {score_text}/100). Keine Fehler oder Warnungen "
            f"gefunden."
        )
    if total_info:
        fazit += f" {total_info} INFO-Hinweise sind optionale Datenanreicherung."
    if findings_meta:
        reviewed_count = len(resolved_issues) + len(false_positive_issues)
        if reviewed_count:
            fazit += (
                f" Von {len(issues)} erkannten Befunden sind {reviewed_count} "
                f"bereits bewertet ({len(resolved_issues)} repariert, "
                f"{len(false_positive_issues)} akzeptiert) und "
                f"{len(open_issues)} weiterhin offen."
            )
    add(fazit)
    add("")

    return "\n".join(lines)
