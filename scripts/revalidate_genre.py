#!/usr/bin/env python3
# scripts/revalidate_genre.py
# -*- coding: utf-8 -*-
"""
Kontrollierte Genre-Revalidierung — CLI (Library Genre Management v2,
Chat-Charakterisierung 2026-09-15).

    python scripts/revalidate_genre.py --artist "Toobrokeforfiji" --dry-run
    python scripts/revalidate_genre.py --artist "Toobrokeforfiji" --apply

Schliesst die in ARCH-022 charakterisierte Luecke
(tests/test_genre_processor_revalidation_gap.py): ein einmal LEARNED/
CONFIRMED gelerntes Genre wird vom normalen Download-Pfad nie wieder mit
frischen Last.fm-Tags abgeglichen. Dieses Script fragt GEZIELT, manuell
ausgeloest, Last.fm fuer EINEN Artist erneut ab und wendet dieselbe
Overturn-Regel wie das bestehende Auto-Learning an - keine zweite
Entscheidungslogik, siehe services/library_repair/genre_revalidation.py.

OPT-IN / EXPLIZIT / PREVIEW-BASIERT (Auftrag Abschnitt 14): Standard ist
immer read-only (--dry-run, auch implizit ohne das Flag - nur --apply
schreibt tatsaechlich). Der automatische Download-Pfad
(GenreProcessor.determine_genre_with_fallbacks()) wird von diesem Script
NICHT beruehrt und bleibt vollstaendig unveraendert.

Manuelles Mapping (artist_genre.yaml) wird IMMER geschuetzt - eine
Revalidierung fuer einen manuell gemappten Artist mutiert nie etwas
(outcome=BLOCKED_MANUAL), unabhaengig von --apply.

Nutzt config.Config (ECHTE Produktions-mapping/ - anders als z. B.
scripts/reprocess_artist_metadata.py, das auf einer isolierten
Testbibliothek arbeitet): dieses Script schreibt ausschliesslich in
mapping/auto_learned_genre.json (eine Config-/Mapping-Datei, identisch
zur bereits etablierten Argumentation fuer
--update-manual-mapping/scripts/library_repair.py), NIE in eine
Library-Audiodatei - kein Tag-/Dateinamen-Zugriff, daher kein
Path-Safety-Sandbox-Modell wie bei den Library-mutierenden Scripts
noetig.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from services.library_repair.genre_revalidation import (  # noqa: E402
    OUTCOME_BLOCKED_MANUAL,
    OUTCOME_NO_CANDIDATE,
    OUTCOME_OVERTURN_ALLOWED,
    OUTCOME_OVERTURN_REJECTED,
    OUTCOME_SAME_GENRE,
    RevalidationResult,
    run_genre_revalidation,
)

_OUTCOME_LABELS = {
    OUTCOME_BLOCKED_MANUAL: "BLOCKED (manuelles Mapping)",
    OUTCOME_NO_CANDIDATE: "NO CANDIDATE",
    OUTCOME_SAME_GENRE: "NO CHANGE (bestätigt aktuelles Genre)",
    OUTCOME_OVERTURN_REJECTED: "CHANGE REJECTED (Overturn-Regel nicht erfüllt)",
    OUTCOME_OVERTURN_ALLOWED: "CHANGE ALLOWED",
}


def _render(result: RevalidationResult, *, applied: bool) -> str:
    lines = [
        "Genre Revalidation Preview" if not applied else "Genre Revalidation",
        "",
        f"Artist: {result.artist}",
        "",
        "Current:",
        f"  {result.current_primary or '(kein Genre)'}"
        + (f" / {', '.join(result.current_secondary)}" if result.current_secondary else ""),
        "",
    ]
    if result.candidate_primary:
        lines += [
            "Candidate:",
            f"  {result.candidate_primary}"
            + (f" / {', '.join(result.candidate_secondary)}" if result.candidate_secondary else ""),
            "",
            f"Source: {result.candidate_source}",
        ]
    if result.learning_status:
        lines.append(f"Learning Status: {result.learning_status}")
    if result.locked_primary:
        lines.append(f"Locked Primary: {result.locked_primary}")
    lines.append(f"Observations: {result.observation_count}")
    lines.append("")
    lines.append(f"Decision: {_OUTCOME_LABELS.get(result.outcome, result.outcome)}")
    lines.append(f"Reason: {result.reason}")
    lines.append("")

    if applied:
        lines.append("✅ Mutation durchgeführt." if result.mutated else "ℹ️ Keine Mutation durchgeführt.")
    else:
        lines.append("No mutation performed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Kontrollierte Genre-Revalidierung für EINEN Artist "
                     "(Last.fm erneut abfragen, bestehende Overturn-Regel anwenden).",
    )
    parser.add_argument("--artist", required=True, help="Artist-Name (exakt wie im Mapping/in auto_learned_genre.json).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explizit (Default-Verhalten ohnehin immer Dry-Run, sofern --apply fehlt).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Schreibt die Beobachtung tatsächlich (nur wenn Overturn-Regel erfüllt ist).",
    )
    parser.add_argument(
        "--json", dest="json_path", type=str, default=None,
        help="Zielpfad für strukturiertes JSON-Ergebnis (Default: "
             "<BASE_DIR>/cache/data/genre_revalidation_result.json) - genutzt "
             "vom Telegram-Subprozess-Wrapper "
             "(services/library_repair/genre_revalidation_runner.py).",
    )
    for forbidden_flag in ("--fix", "--repair", "--force", "--execute"):
        parser.add_argument(forbidden_flag, action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.fix or args.repair or args.force or args.execute:
        print(
            "ERROR: Mutation ist ausschließlich über --apply verfügbar "
            "(--fix/--repair/--force/--execute existieren hier nicht).",
            file=sys.stderr,
        )
        return 2

    if not args.artist.strip():
        print("ERROR: --artist darf nicht leer sein.", file=sys.stderr)
        return 2

    try:
        result = asyncio.run(
            run_genre_revalidation(
                args.artist, apply=args.apply, triggered_by="cli", config=Config,
            )
        )
    except Exception as e:  # noqa: BLE001
        print(f"❌ Schwerer Fehler: {e!r}", file=sys.stderr)
        return 3

    print(_render(result, applied=args.apply))

    json_path = Path(args.json_path) if args.json_path else Path(Config.DATA_DIR) / "genre_revalidation_result.json"
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = json_path.with_suffix(f"{json_path.suffix}.tmp")
        tmp.write_text(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(json_path)
    except OSError as e:
        print(f"⚠️  JSON-Ergebnis konnte nicht geschrieben werden: {e}", file=sys.stderr)

    if result.error_message:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
