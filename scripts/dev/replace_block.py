#!/usr/bin/env python3
"""
replace_block.py — Sichere Block-Ersetzung in Textdateien.

Verwendung:
    replace_block.py <ziel> <alt.txt> <neu.txt>
                     [--verify <datei>:<marker>]...
                     [--dry-run] [--no-backup] [--allow-multiple]

Beispiel:
    replace_block.py tests/test_control_center_ui.py \\
                     /tmp/old_block.txt /tmp/new_block.txt \\
                     --verify control_center/templates/overview.html:'id="system-status-bar"'

Exit-Codes:
    0 — angewendet oder bereits angewendet (idempotent)
    1 — Verify-Marker in Referenzdatei fehlt (Fix passt nicht)
    2 — alter Block nicht gefunden (Datei unerwartet geaendert)
    3 — Argument-/IO-Fehler
"""
import argparse
import shutil
import sys
from pathlib import Path


def parse_verify(spec):
    """'pfad:marker' -> (Path, str). Marker darf ':' enthalten."""
    if ":" not in spec:
        raise argparse.ArgumentTypeError(
            "verify braucht Format '<datei>:<marker>'"
        )
    path, marker = spec.split(":", 1)
    return Path(path), marker


def main():
    parser = argparse.ArgumentParser(
        description="Sichere Block-Ersetzung in Textdateien.",
    )
    parser.add_argument("target", type=Path, help="Datei, die geaendert wird")
    parser.add_argument("old_file", type=Path, help="Datei mit altem Block")
    parser.add_argument("new_file", type=Path, help="Datei mit neuem Block")
    parser.add_argument(
        "--verify", action="append", default=[], type=parse_verify,
        metavar="DATEI:MARKER",
        help="Vor dem Ersetzen pruefen, dass DATEI MARKER enthaelt. "
             "Mehrfach angebbar.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur anzeigen, nichts schreiben")
    parser.add_argument("--no-backup", action="store_true",
                        help="Kein .bak anlegen")
    parser.add_argument("--allow-multiple", action="store_true",
                        help="Mehrere Treffer erlauben (sonst Fehler)")
    args = parser.parse_args()

    # 1. Alle Dateien lesen
    for p in (args.target, args.old_file, args.new_file):
        if not p.exists():
            print("FEHLER: nicht gefunden: " + str(p), file=sys.stderr)
            return 3

    old_block = args.old_file.read_text(encoding="utf-8")
    new_block = args.new_file.read_text(encoding="utf-8")
    target_text = args.target.read_text(encoding="utf-8")

    # 2. Verify-Marker pruefen
    for ref_path, marker in args.verify:
        if not ref_path.exists():
            print("FEHLER: verify-Referenz fehlt: " + str(ref_path),
                  file=sys.stderr)
            return 3
        ref_text = ref_path.read_text(encoding="utf-8")
        if marker not in ref_text:
            print("ABBRUCH: Marker nicht gefunden in " + str(ref_path),
                  file=sys.stderr)
            print("  Marker: " + marker, file=sys.stderr)
            print("  -> Der Fix passt nicht zum aktuellen Zustand.",
                  file=sys.stderr)
            return 1

    # 3. Idempotenz-Check
    if new_block in target_text and old_block not in target_text:
        print("OK: neuer Block bereits vorhanden, nichts zu tun.")
        return 0

    # 4. Alter Block muss vorkommen
    count = target_text.count(old_block)
    if count == 0:
        print("ABBRUCH: alter Block nicht gefunden in " + str(args.target),
              file=sys.stderr)
        print("  -> Datei wurde unerwartet geaendert, oder der "
              "Block-Text stimmt nicht exakt (Whitespace?).",
              file=sys.stderr)
        return 2
    if count > 1 and not args.allow_multiple:
        print("ABBRUCH: alter Block kommt " + str(count) + "x vor, "
              "eindeutig erwartet.", file=sys.stderr)
        print("  -> Block vergroessern (mehr Kontext) oder "
              "--allow-multiple nutzen.", file=sys.stderr)
        return 2

    # 5. Dry-Run?
    if args.dry_run:
        print("DRY-RUN — wuerde ersetzen:")
        print("  Datei:    " + str(args.target))
        print("  Alt:      " + str(len(old_block)) + " Zeichen")
        print("  Neu:      " + str(len(new_block)) + " Zeichen")
        print("  Vorkommen: " + str(count))
        return 0

    # 6. Backup
    if not args.no_backup:
        backup = args.target.with_suffix(args.target.suffix + ".bak")
        shutil.copy2(args.target, backup)
        print("Backup: " + str(backup))

    # 7. Ersetzen
    new_text = target_text.replace(old_block, new_block, 1)
    args.target.write_text(new_text, encoding="utf-8")
    print("Angepasst: " + str(args.target))

    return 0


if __name__ == "__main__":
    sys.exit(main())
