#!/usr/bin/env python3
# scripts/library_health_review.py
# -*- coding: utf-8 -*-
"""
Interaktive Review-CLI für die persistente Library-Health-Findings-Registry
(services/library_health/findings.py).

Zeigt alle aktuell OFFENEN Findings nacheinander an und fragt pro Finding
eine Aktion ab:

    python scripts/library_health_review.py

    [R] Resolve         -> Status RESOLVED  (+ optionale Notiz)
    [F] False Positive  -> Status FALSE_POSITIVE  (+ optionale Notiz)
    [S] Skip            -> unverändert, nächstes Finding
    [Q] Quit            -> Abbruch, bereits getroffene Entscheidungen bleiben
                           gespeichert (Registry wird nach jeder einzelnen
                           Review-Aktion sofort atomar gespeichert - kein
                           Verlust bei Abbruch mitten in der Sitzung)

Dieses Script ist bewusst dünn (CLAUDE.md §4 Schichtgrenzen, Aufgabe
Abschnitt 1/28): die gesamte Fachlogik (Finding-Identität, Merge, Review-
Status, Persistenz) liegt in services/library_health/findings.py. Ein
künftiger Telegram-Handler würde dieselbe FindingsRegistry-API aufrufen -
niemals die JSON-Datei direkt.

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
    Finding,
    FindingsRegistry,
    FindingsRegistryError,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="library_health_review.py",
        description="Interaktive Prüfung offener Library-Health-Findings.",
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
    return parser


def _finding_location(finding: Finding) -> str:
    parts = [p for p in (finding.artist, finding.album, finding.title) if p]
    if parts:
        return " / ".join(parts)
    return finding.path or "-"


def _prompt_note() -> Optional[str]:
    note = input("    Notiz (optional, Enter zum Überspringen): ").strip()
    return note or None


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

    open_findings = sorted(
        registry.get_open_findings(),
        key=lambda f: (
            f.code,
            f.artist or "",
            f.album or "",
            f.title or "",
            f.path or "",
        ),
    )

    if not open_findings:
        print("✅ Keine offenen Befunde - nichts zu prüfen.")
        return 0

    print(f"Library Health – {len(open_findings)} offene(r) Befund(e)\n")

    reviewed = 0
    for idx, finding in enumerate(open_findings, start=1):
        print(f"[{idx}/{len(open_findings)}] {finding.code}")
        print(f"    {_finding_location(finding)}")
        if finding.path:
            print(f"    Datei: {finding.path}")
        if finding.message:
            print(f"    {finding.message}")
        if finding.occurrences > 1:
            print(
                f"    (bereits {finding.occurrences}x erkannt, "
                f"zuerst am {finding.first_seen})"
            )
        print()

        action = input("Aktion [R]esolve / [F]alse Positive / [S]kip / [Q]uit: ").strip().lower()

        if action == "q":
            print("\nAbgebrochen - bisherige Bewertungen bleiben gespeichert.")
            break

        if action == "r":
            note = _prompt_note()
            registry.review_finding(
                finding.finding_id, STATUS_RESOLVED, note=note, reviewed_by=reviewer
            )
            registry.save()
            reviewed += 1
            print("    → RESOLVED gespeichert.\n")
        elif action == "f":
            note = _prompt_note()
            registry.review_finding(
                finding.finding_id, STATUS_FALSE_POSITIVE, note=note, reviewed_by=reviewer
            )
            registry.save()
            reviewed += 1
            print("    → FALSE_POSITIVE gespeichert.\n")
        else:
            print("    → übersprungen.\n")

    print(f"Fertig. {reviewed} von {len(open_findings)} Befund(en) bewertet.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nabgebrochen", file=sys.stderr)
        sys.exit(130)
