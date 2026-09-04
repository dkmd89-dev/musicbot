#!/usr/bin/env python3
# scripts/library_health_check.py
# -*- coding: utf-8 -*-
"""
Music Library Health Scanner — CLI (Prompt "Phase 1", Abschnitt 29).

Analysiert die konfigurierte Music-Library VOLLSTAENDIG READ-ONLY und
erzeugt einen strukturierten Health-Report (JSON + human-readable Text).

    python scripts/library_health_check.py
    python scripts/library_health_check.py --library /pfad/zur/library
    python scripts/library_health_check.py --json /pfad/report.json --output /pfad/report.txt
    python scripts/library_health_check.py --verbose

Dieses Script ist ausschliesslich:  CLI -> Config -> Scanner -> Report.
Keine Fachlogik hier (die liegt in services/library_health/).

READ-ONLY (Prompt Abschnitt 2): der Scanner veraendert die Library unter
keinen Umstaenden — kein Umbenennen, Verschieben, Loeschen, Tag-/Cover-/
Lyrics-Schreiben, kein Re-Encoding. Es gibt bewusst KEINE Mutations-Flags
(--fix/--repair/--delete/--execute/--apply werden mit Fehler abgelehnt).
Der einzige Schreibzugriff sind die beiden Report-Dateien ausserhalb der
Library. tests/test_library_health_readonly_safety.py weist das technisch
nach (SHA256/mtime/size/Pfade vorher == nachher, Writer-Import-Graph-Check).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from logger import get_module_logger  # noqa: E402
from services.library_health.report import render_text  # noqa: E402
from services.library_health.scanner import run_scan  # noqa: E402

_FORBIDDEN_FLAGS = ("--fix", "--repair", "--delete", "--execute", "--apply")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="library_health_check.py",
        description="Read-only Music Library Health Scanner (rein diagnostisch).",
    )
    parser.add_argument(
        "--library", type=str, default=None,
        help="Zu analysierende Library-Wurzel (Default: config.Config.LIBRARY_DIR).",
    )
    parser.add_argument(
        "--json", dest="json_path", type=str, default=None,
        help="Zielpfad des JSON-Reports "
             "(Default: <BASE_DIR>/cache/data/library_health_report.json).",
    )
    parser.add_argument(
        "--output", dest="text_path", type=str, default=None,
        help="Zielpfad des human-readable Text-Reports "
             "(Default: neben dem JSON-Report, .txt).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Pro-Datei-Logging (DEBUG).",
    )
    parser.add_argument(
        "--max-issues", type=int, default=200,
        help="Maximale Anzahl Issues im Text-Report (JSON enthaelt immer alle).",
    )
    parser.add_argument(
        "--fail-on-error", action="store_true",
        help="Exit-Code 1, wenn ERROR-/CRITICAL-Issues gefunden wurden "
             "(fuer Scripting/CI). Ohne dieses Flag ist ein abgeschlossener "
             "Scan immer Exit-Code 0.",
    )
    # Bewusst abgelehnte Mutations-Flags — mit klarer Fehlermeldung statt
    # stiller Ignorierung (identisches Muster wie scripts/resolve_duplicates.py).
    for flag in _FORBIDDEN_FLAGS:
        parser.add_argument(flag, action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    used_forbidden = [f for f in _FORBIDDEN_FLAGS if getattr(args, f.lstrip("-").replace("-", "_"))]
    if used_forbidden:
        print(
            f"ERROR: {', '.join(used_forbidden)} existiert nicht — der Library "
            f"Health Scanner ist ausschliesslich diagnostisch und veraendert "
            f"nie eine Datei.",
            file=sys.stderr,
        )
        return 2

    config = Config()
    library_root = Path(args.library) if args.library else Path(config.LIBRARY_DIR)

    if not library_root.is_dir():
        print(f"ERROR: Library-Verzeichnis nicht gefunden: {library_root}", file=sys.stderr)
        return 2

    json_path = (
        Path(args.json_path)
        if args.json_path
        else Path(config.DATA_DIR) / "library_health_report.json"
    )
    text_path = Path(args.text_path) if args.text_path else json_path.with_suffix(".txt")

    logger = get_module_logger("library_health")

    try:
        report = run_scan(
            library_root,
            supported_extensions=tuple(config.SUPPORTED_FORMATS),
            expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
            genre_mapping_dir=config.GENRE_MAPPING_DIR,
            logger=logger,
            verbose=args.verbose,
        )
    except Exception as e:  # noqa: BLE001
        print(f"❌ SCHWERER FEHLER waehrend des Scans: {e!r}", file=sys.stderr)
        return 3

    text = render_text(report, max_issues=args.max_issues)

    for target in (json_path, text_path):
        target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(json_path, json.dumps(report, indent=2, ensure_ascii=False))
    _write_atomic(text_path, text)

    print(text)
    print(f"\n📄 JSON: {json_path}")
    print(f"📄 Text: {text_path}")

    if args.fail_on_error:
        sev = report["statistics"]["issues_by_severity"]
        if sev.get("ERROR", 0) or sev.get("CRITICAL", 0):
            return 1
    return 0


def _write_atomic(path: Path, content: str) -> None:
    """tmp-Datei im selben Verzeichnis, dann atomarer replace() — identisches
    Muster wie services/duplicate/cache.py::_write_json_atomic()."""
    import time as _t

    tmp = path.with_name(f".{path.name}.tmp_{int(_t.time() * 1000)}")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nabgebrochen", file=sys.stderr)
        sys.exit(130)
