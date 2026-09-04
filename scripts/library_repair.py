#!/usr/bin/env python3
# scripts/library_repair.py
# -*- coding: utf-8 -*-
"""
Smart Library Repair — CLI (Phase 2, Prompt Abschnitt 5/12/13/18/19).

    python scripts/library_repair.py                 # nur PLAN (read-only)
    python scripts/library_repair.py --report r.json # Plan aus vorhandenem Health-Report
    python scripts/library_repair.py --artist 01099
    python scripts/library_repair.py --issue LOUDNESS_TAG_MISSING
    python scripts/library_repair.py --severity ERROR
    python scripts/library_repair.py --level SAFE_AUTOMATIC
    python scripts/library_repair.py --json plan.json

DRY-RUN ist Standard (Prompt Abschnitt 13). Ohne Executor macht dieses
Script AUSSCHLIESSLICH einen Plan — es veraendert, verschiebt, loescht
nichts und ruft keinen externen Dienst. Der Health-Scan selbst
(`--report` weggelassen) ist ebenfalls vollstaendig read-only.

`--apply` / `--allow-delete` werden aktuell mit klarer Meldung abgelehnt —
der Repair Executor folgt als eigener, explizit geschuetzter Phase-2-Schritt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from logger import get_module_logger  # noqa: E402
from services.library_repair.planner import filter_plan, plan_repairs  # noqa: E402
from services.library_repair.report import render_plan_text  # noqa: E402


def _load_or_scan_report(args, config, logger) -> dict:
    if args.report:
        path = Path(args.report)
        if not path.is_file():
            raise FileNotFoundError(f"Health-Report nicht gefunden: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    # kein Report angegeben -> frischen read-only Scan fahren
    from services.library_health.scanner import run_scan

    library_root = Path(args.library) if args.library else Path(config.LIBRARY_DIR)
    if not library_root.is_dir():
        raise NotADirectoryError(f"Library-Verzeichnis nicht gefunden: {library_root}")
    return run_scan(
        library_root,
        supported_extensions=tuple(config.SUPPORTED_FORMATS),
        expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
        genre_mapping_dir=config.GENRE_MAPPING_DIR,
        logger=logger,
        verbose=args.verbose,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="library_repair.py",
        description="Smart Library Repair — erzeugt einen Reparaturplan (read-only).",
    )
    parser.add_argument("--library", default=None,
                        help="Library-Wurzel fuer den Scan (Default: config.Config.LIBRARY_DIR).")
    parser.add_argument("--report", default=None,
                        help="Vorhandenen Health-Report (JSON) verwenden statt neu zu scannen.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Reparaturplan als JSON schreiben.")
    parser.add_argument("--artist", default=None, help="Nur diesen Artist.")
    parser.add_argument("--issue", dest="issue_code", default=None,
                        help="Nur diesen Issue-Code (z. B. LOUDNESS_TAG_MISSING).")
    parser.add_argument("--severity", default=None,
                        help="Nur diese Severity (INFO/WARNING/ERROR/CRITICAL).")
    parser.add_argument("--level", default=None,
                        help="Nur diese Reparaturstufe (z. B. SAFE_AUTOMATIC).")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-delete", dest="allow_delete", action="store_true",
                        help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.apply or args.allow_delete:
        print(
            "ERROR: der Repair Executor ist noch nicht implementiert.\n"
            "Aktuell erzeugt dieses Script AUSSCHLIESSLICH einen Reparaturplan "
            "(read-only). --apply/--allow-delete folgen als eigener, explizit "
            "geschuetzter Phase-2-Schritt.",
            file=sys.stderr,
        )
        return 2

    config = Config()
    logger = get_module_logger("library_repair")

    try:
        report = _load_or_scan_report(args, config, logger)
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"❌ SCHWERER FEHLER: {e!r}", file=sys.stderr)
        return 3

    plan = plan_repairs(report)
    if any((args.artist, args.issue_code, args.severity, args.level)):
        plan = filter_plan(
            plan, artist=args.artist, issue_code=args.issue_code,
            severity=args.severity, level=args.level,
        )

    text = render_plan_text(plan)
    print(text)

    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\n📄 Plan: {out}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nabgebrochen", file=sys.stderr)
        sys.exit(130)
