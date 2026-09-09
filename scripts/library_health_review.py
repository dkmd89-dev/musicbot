#!/usr/bin/env python3
# scripts/library_health_review.py
# -*- coding: utf-8 -*-
"""
Interaktive Review-CLI für die persistente Library-Health-Findings-Registry
(services/library_health/findings.py).

Offene Findings werden zunächst nach `issue_code` gruppiert (Kategorien),
absteigend nach Severity-Stufe (CRITICAL > ERROR > WARNING > SUSPECTED/
CONFIDENCE > INFO). Pro Kategorie stehen drei Aktionen zur Verfügung:

    python scripts/library_health_review.py

    [Y] Kategorie einzeln bearbeiten   -> Einzelreview jedes offenen Findings
    [F] Kategorie -> FALSE_POSITIVE    -> Batch-Aktion, verlangt Bestätigung
    [S] Kategorie überspringen         -> keine Änderung, nächste Kategorie

Während der Einzelbearbeitung (Y):

    [R] Resolve          -> Status RESOLVED  (+ optionale Notiz)
    [F] False Positive   -> Status FALSE_POSITIVE  (+ optionale Notiz)
    [S] Skip             -> keine Änderung, nächstes Finding
    [Q] Quit             -> beendet den GESAMTEN Review sofort

Jede Statusänderung wird sofort atomar über die zentrale
FindingsRegistry gespeichert - kein Verlust bei Abbruch mitten in der
Sitzung. Nur Findings mit Status OPEN werden zur Bearbeitung angeboten;
bereits RESOLVED/FALSE_POSITIVE Findings werden nie erneut vorgeschlagen.

Dieses Script ist bewusst dünn (CLAUDE.md §4 Schichtgrenzen, Aufgabe
"Library Health Review" Abschnitt 1/28): die gesamte Fachlogik (Finding-
Identität, Merge, Kategorie-Gruppierung, Batch-/Einzel-Review-Status,
Persistenz) liegt in services/library_health/findings.py. Ein künftiger
Telegram-Handler verwendet dieselbe FindingsRegistry-/Review-Service-API
(group_open_findings_by_category(), batch_review_category(),
review_finding()) - niemals die JSON-Datei direkt.

Führt selbst KEINEN Scan durch (das macht weiterhin ausschließlich
scripts/library_health_check.py) und modifiziert NIEMALS eine Datei in
der Music Library - ausschließlich die Findings-Registry außerhalb der
Library wird geschrieben (siehe Read-only-Garantie in
docs/LIBRARY_HEALTH.md).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from logger import get_module_logger  # noqa: E402
from services.library_health.findings import (  # noqa: E402
    DEFAULT_FILENAME,
    STATUS_FALSE_POSITIVE,
    STATUS_RESOLVED,
    CategoryGroup,
    Finding,
    FindingsRegistry,
    FindingsRegistryError,
    accept_finding,
    batch_review_category,
    get_accepted_findings,
    get_review_summary,
    group_open_findings_by_category,
    unaccept_finding,
)

_POSITIVE_CONFIRM = {"y", "yes", "j", "ja"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="library_health_review.py",
        description="Interaktive, nach Kategorie gruppierte Prüfung offener "
                     "Library-Health-Findings.",
    )
    parser.add_argument(
        "--registry", dest="registry_path", type=str, default=None,
        help="Pfad zur Findings-Registry "
             "(Default: <BASE_DIR>/cache/data/library_health_findings.json, "
             "identisch zum Default von library_health_check.py).",
    )
    parser.add_argument(
        "--reviewer", type=str, default=None,
        help="Kennung des Prüfenden für 'reviewed_by' "
             "(Default: 'cli:<OS-Benutzername>').",
    )

    # ── Nicht-interaktive Direktaktionen (Library-Closure-Phase,
    #    Auftrag §15-22). Ohne eines dieser Flags läuft der bisherige
    #    interaktive, kategoriebasierte Review (Default, unverändert). ──
    direct = parser.add_argument_group(
        "Direktaktionen (nicht-interaktiv, je genau eine pro Aufruf)"
    )
    direct.add_argument(
        "--accept", metavar="FINDING_ID", default=None,
        help="Finding bewusst akzeptieren (== FALSE_POSITIVE). "
             "Erfordert --reason.",
    )
    direct.add_argument(
        "--reason", type=str, default=None,
        help="Grund für --accept (Pflicht bei --accept, wird gespeichert).",
    )
    direct.add_argument(
        "--unaccept", metavar="FINDING_ID", default=None,
        help="Acceptance zurücknehmen — Finding wird wieder OPEN.",
    )
    direct.add_argument(
        "--accepted", metavar="ISSUE_CODE", nargs="?", const="", default=None,
        help="Akzeptierte Findings auflisten; optional auf einen Issue-Code "
             "gefiltert (z. B. --accepted ALBUM_TRACK_GAP).",
    )
    direct.add_argument(
        "--show", metavar="FINDING_ID", default=None,
        help="Ein Finding mit voller Review-Historie anzeigen.",
    )
    direct.add_argument(
        "--summary", action="store_true",
        help="Tri-State-Zusammenfassung (🔴 Offen / 🟢 Repariert / "
             "⚪ Akzeptiert) ausgeben und beenden.",
    )
    return parser


def _finding_location(finding: Finding) -> str:
    parts = [p for p in (finding.artist, finding.album, finding.title) if p]
    if parts:
        return " / ".join(parts)
    return finding.path or "-"


def _prompt_note() -> Optional[str]:
    note = input("    Notiz (optional, Enter zum Überspringen): ").strip()
    return note or None


def _print_finding(finding: Finding, index: int, total: int) -> None:
    print(f"[{index}/{total}] {finding.code}\n")
    print(f"    {_finding_location(finding)}")
    if finding.path:
        print(f"    Datei: {finding.path}")
    if finding.message:
        print(f"    {finding.message}")
    if finding.occurrences > 1:
        print(f"    Bereits {finding.occurrences}x erkannt")
        print(f"    Erstmals: {finding.first_seen}")
    print()


def _run_single_review(
    registry: FindingsRegistry, findings: list[Finding], tally: dict, reviewer: str,
) -> bool:
    """Arbeitet die übergebenen (bereits als OPEN bekannten) Findings einer
    Kategorie einzeln ab. Gibt True zurück, wenn der Nutzer [Q]uit gewählt
    hat (beendet den GESAMTEN Review, nicht nur diese Kategorie)."""
    total = len(findings)
    for idx, finding in enumerate(findings, start=1):
        _print_finding(finding, idx, total)
        action = input(
            "Aktion [R]esolve / [F]alse Positive / [S]kip / [Q]uit: "
        ).strip().lower()

        if action == "q":
            print("\nReview beendet - bisherige Bewertungen bleiben gespeichert.")
            return True

        if action == "r":
            note = _prompt_note()
            registry.review_finding(
                finding.finding_id, STATUS_RESOLVED, note=note, reviewed_by=reviewer
            )
            registry.save()
            tally["bearbeitet"] += 1
            tally["resolved"] += 1
            print("    → RESOLVED gespeichert.\n")
        elif action == "f":
            note = _prompt_note()
            registry.review_finding(
                finding.finding_id, STATUS_FALSE_POSITIVE, note=note, reviewed_by=reviewer
            )
            registry.save()
            tally["bearbeitet"] += 1
            tally["false_positive"] += 1
            print("    → FALSE_POSITIVE gespeichert.\n")
        else:
            tally["skipped"] += 1
            print("    → übersprungen.\n")

    return False


def _prompt_category_action(group: CategoryGroup) -> str:
    print(f"{group.code} ({group.open_count} Befund(e))\n")
    print("Bearbeiten [Y]")
    print("[F]alse Positive – komplette Kategorie")
    print("[S]kip\n")
    return input("Auswahl: ").strip().lower()


def _confirm_batch_false_positive(group: CategoryGroup) -> bool:
    print("\n⚠️ ACHTUNG\n")
    print(f"{group.open_count} Findings werden als FALSE_POSITIVE markiert.\n")
    print("Kategorie:")
    print(f"{group.code}\n")
    print("Diese Aktion betrifft die komplette Kategorie.\n")
    answer = input("Fortfahren? [Y/N]: ").strip().lower()
    return answer in _POSITIVE_CONFIRM


# ─────────────────────────────────────────────────────────────────────────
# Nicht-interaktive Direktaktionen (Auftrag §15-22). Jede ruft ausschliesslich
# die zentrale findings.py-API — kein Direktzugriff auf die JSON-Datei.
# ─────────────────────────────────────────────────────────────────────────


def _render_finding_detail(finding: Finding) -> None:
    print(f"Finding-ID:  {finding.finding_id}")
    print(f"Code:        {finding.code}  "
          f"(Scope {finding.scope}, Severity {finding.severity or '-'})")
    print(f"Status:      {finding.status}")
    print(f"Ort:         {_finding_location(finding)}")
    if finding.path:
        print(f"Datei:       {finding.path}")
    if finding.message:
        print(f"Meldung:     {finding.message}")
    print(f"Erstmals:    {finding.first_seen}")
    print(f"Zuletzt:     {finding.last_seen}  ({finding.occurrences}x erkannt)")
    print(f"Im letzten Scan erkannt: {'ja' if finding.present_in_latest_scan else 'nein'}")
    if finding.reviewed_at:
        print(f"Bewertet:    {finding.reviewed_at} von {finding.reviewed_by or '-'}")
    if finding.review_note:
        print(f"Notiz:       {finding.review_note}")
    if finding.history:
        print("\nHistorie:")
        for h in finding.history:
            print(f"  {h.timestamp}  {h.status}"
                  + (f"  – {h.note}" if h.note else ""))


def _cmd_summary(registry: FindingsRegistry) -> int:
    s = get_review_summary(registry)
    print("Library Health Review – Zusammenfassung\n")
    print(f"🔴 Offen:      {s.open}")
    print(f"🟢 Repariert:  {s.repaired}")
    stale = f"  (davon {s.accepted_stale} nicht mehr erkannt)" if s.accepted_stale else ""
    print(f"⚪ Akzeptiert: {s.accepted}{stale}")
    if s.resolved_by_scan:
        print(f"   vom Scanner nicht mehr erkannt (unbestätigt): {s.resolved_by_scan}")
    print(f"\nGesamt in Registry: {s.total}")
    return 0


def _cmd_show(registry: FindingsRegistry, finding_id: str) -> int:
    finding = registry.get(finding_id)
    if finding is None:
        print(f"❌ Kein Finding mit ID {finding_id!r}.", file=sys.stderr)
        return 1
    _render_finding_detail(finding)
    return 0


def _cmd_accepted(registry: FindingsRegistry, issue_code: Optional[str]) -> int:
    findings = get_accepted_findings(registry, issue_code=issue_code)
    if not findings:
        scope = f" für {issue_code}" if issue_code else ""
        print(f"Keine akzeptierten Findings{scope}.")
        return 0
    title = f"⚪ Akzeptierte Findings ({len(findings)})"
    if issue_code:
        title += f" – gefiltert auf {issue_code}"
    print(title + "\n")
    current_code = None
    for f in findings:
        if f.code != current_code:
            current_code = f.code
            print(f.code)
        stale = "  ⚠️ nicht mehr erkannt" if not f.present_in_latest_scan else ""
        print(f"  {f.finding_id}  {_finding_location(f)}{stale}")
        if f.review_note:
            print(f"      Grund: {f.review_note}")
    return 0


def _cmd_accept(
    registry: FindingsRegistry, finding_id: str, reason: Optional[str], reviewer: str
) -> int:
    if not reason or not reason.strip():
        print("❌ --accept erfordert --reason \"<Grund>\".", file=sys.stderr)
        return 2
    try:
        finding = accept_finding(
            registry, finding_id, reason=reason, reviewed_by=reviewer
        )
    except KeyError:
        print(f"❌ Kein Finding mit ID {finding_id!r}.", file=sys.stderr)
        return 1
    registry.save()
    print(f"✅ {finding_id} akzeptiert ({finding.code}).")
    print(f"   Grund: {finding.review_note}")
    return 0


def _cmd_unaccept(registry: FindingsRegistry, finding_id: str, reviewer: str) -> int:
    try:
        finding = unaccept_finding(registry, finding_id, reviewed_by=reviewer)
    except KeyError:
        print(f"❌ Kein Finding mit ID {finding_id!r}.", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    registry.save()
    print(f"↩️  {finding_id} reaktiviert – Status wieder OPEN ({finding.code}).")
    return 0


def _run_direct_action(args, registry: FindingsRegistry, reviewer: str) -> Optional[int]:
    """Gibt einen Exit-Code zurück, wenn eine Direktaktion angefordert wurde,
    sonst None (→ interaktiver Review)."""
    selected = [
        name for name, active in (
            ("--summary", args.summary),
            ("--show", args.show is not None),
            ("--accepted", args.accepted is not None),
            ("--accept", args.accept is not None),
            ("--unaccept", args.unaccept is not None),
        ) if active
    ]
    if not selected:
        return None
    if len(selected) > 1:
        print(f"❌ Nur eine Direktaktion pro Aufruf ({', '.join(selected)}).",
              file=sys.stderr)
        return 2
    if args.summary:
        return _cmd_summary(registry)
    if args.show is not None:
        return _cmd_show(registry, args.show)
    if args.accepted is not None:
        return _cmd_accepted(registry, args.accepted or None)
    if args.accept is not None:
        return _cmd_accept(registry, args.accept, args.reason, reviewer)
    return _cmd_unaccept(registry, args.unaccept, reviewer)


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = Config()
    registry_path = (
        Path(args.registry_path)
        if args.registry_path
        else Path(config.DATA_DIR) / DEFAULT_FILENAME
    )
    reviewer = args.reviewer or f"cli:{getpass.getuser()}"

    logger = get_module_logger("library_health_review")

    try:
        registry = FindingsRegistry(registry_path, logger=logger)
    except FindingsRegistryError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    direct_exit = _run_direct_action(args, registry, reviewer)
    if direct_exit is not None:
        return direct_exit

    groups = group_open_findings_by_category(registry)

    if not groups:
        print("✅ Keine offenen Befunde - nichts zu prüfen.")
        return 0

    total_open = sum(g.open_count for g in groups)
    print(f"Library Health Review – {total_open} offene(r) Befund(e) in "
          f"{len(groups)} Kategorie(n)\n")

    tally = {"bearbeitet": 0, "resolved": 0, "false_positive": 0, "skipped": 0}

    for group in groups:
        action = _prompt_category_action(group)

        if action == "y":
            quit_requested = _run_single_review(registry, group.findings, tally, reviewer)
            if quit_requested:
                break
        elif action == "f":
            if _confirm_batch_false_positive(group):
                count = group.open_count
                batch_review_category(
                    registry, group.code, STATUS_FALSE_POSITIVE, reviewed_by=reviewer,
                )
                registry.save()
                tally["bearbeitet"] += count
                tally["false_positive"] += count
                print(f"\n✅ {count} Findings als FALSE_POSITIVE markiert.\n")
            else:
                print("\nAbgebrochen - keine Änderung.\n")
        else:
            print("→ Kategorie übersprungen.\n")

    remaining_open = len(registry.get_open_findings())

    print("═" * 38)
    print("Library Health Review abgeschlossen")
    print("═" * 38)
    print()
    print(f"Bearbeitet:      {tally['bearbeitet']}")
    print(f"Resolved:        {tally['resolved']}")
    print(f"False Positive:  {tally['false_positive']}")
    print(f"Skipped:         {tally['skipped']}")
    print()
    print(f"Offene Findings: {remaining_open}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nabgebrochen", file=sys.stderr)
        sys.exit(130)
