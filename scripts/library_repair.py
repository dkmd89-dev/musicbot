#!/usr/bin/env python3
# scripts/library_repair.py
# -*- coding: utf-8 -*-
"""
Smart Library Repair — CLI (Phase 2, Prompt Abschnitt 5/12/13/18/19).

    python scripts/library_repair.py                 # nur PLAN (read-only)
    python scripts/library_repair.py --report r.json # Plan aus vorhandenem Health-Report
    python scripts/library_repair.py --artist 01099
    python scripts/library_repair.py --issue LOUDNESS_OFF_TARGET
    python scripts/library_repair.py --severity ERROR
    python scripts/library_repair.py --level SAFE_AUTOMATIC
    python scripts/library_repair.py --json plan.json

DRY-RUN ist Standard (Prompt Abschnitt 13). Ohne `--apply` macht dieses
Script AUSSCHLIESSLICH einen Plan — es veraendert, verschiebt, loescht
nichts und ruft keinen externen Dienst. Der Health-Scan selbst
(`--report` weggelassen) ist ebenfalls vollstaendig read-only.

    --apply               L1-Tag-Fixes + L1-Renames ausfuehren (DRY-RUN,
                          solange --dry-run gesetzt ist)
    --apply --dry-run     Vorschau aller ausfuehrbaren Reparaturen
    --level COVER         zusaetzlich Cover-Executor (extern, langsam)
    --level EXTERNAL_METADATA   zusaetzlich L3 MusicBrainz-IDs (extern)
    --level METADATA_REPROCESSING   zusaetzlich L2 volle Neuverarbeitung
                          ueber die echte Pipeline (extern, langsam,
                          aktualisiert Auto-Learn-Mappings)
    --level LOUDNESS      zusaetzlich Loudness-Executor — schreibt einen
                          verlustfreien replaygain_track_gain-Tag (Ziel -16
                          LUFS, Audio byte-identisch), setzt einen
                          `--measure-loudness`-Report voraus
    --allow-delete --artist X [--dry-run]
                          Duplicate-Aufloesung fuer EINEN Artist — dockt
                          als Subprozess an scripts/resolve_duplicates.py
                          an (kein eigener Loesch-Code, siehe dortiges
                          --execute/--confirm-production-execute-Modell).
                          Ohne --artist abgelehnt (nie der ganze Root).

Cover / L3 / L2 / Loudness laufen NIE im Default-`--apply`, nur auf
ausdrueckliche Anforderung per --level bzw. --issue. --allow-delete ist
ein eigener, von --apply unabhaengiger Pfad (siehe oben).

Library-Maintenance-Actions (ARCH-032 Phase 3D) — Command-getrieben,
KEIN Health-Finding-Bezug (ARCH-031 B.1), loest
scripts/fix_artist_casing.py / scripts/remove_legacy_genre_atom.py /
scripts/set_genre.py ab (siehe docs/LIBRARY_REPAIR.md §11):

    --maintenance-action artist-casing --artist X [--apply]
    --maintenance-action legacy-genre-cleanup --artist X [--apply]
    --maintenance-action set-genre --artist X --genre "A; B" [--apply]
    --maintenance-action set-genre --artist X --from-mapping [--apply]
    --maintenance-action set-genre --artist X --from-mapping \
        --only-if-missing --apply
    --maintenance-action artist-casing --all [--apply]   # ganze Library
    --maintenance-action artist-casing --path <Datei/Verzeichnis>

Wie beim Rest dieses Scripts ist --apply erforderlich fuer echtes
Schreiben (Default: DRY-RUN). --update-manual-mapping (nur mit
set-genre + --artist + --genre) traegt den Wert zusaetzlich in
mapping/artist_genre.yaml ein — bleibt CLI-only, kein Telegram-Trigger
(ARCH-031 A.4).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from logger import get_module_logger  # noqa: E402
from services.library_repair.planner import filter_plan, plan_repairs  # noqa: E402
from services.library_repair.report import render_plan_text  # noqa: E402

RESOLVE_DUPLICATES_SCRIPT = Path(__file__).resolve().parent / "resolve_duplicates.py"


def _run_duplicate_resolution(args) -> int:
    """`--allow-delete`-Pfad: dockt als eigenstaendiger Subprozess an das
    bereits gehaertete scripts/resolve_duplicates.py an (Zwei-Stufen-
    Sicherheit: Execution-Plan + Fingerprint-/TOCTOU-Pre-Delete-
    Revalidierung, siehe dortiger Modul-Docstring) — kein eigener
    Loesch-/Klassifikations-Code in diesem Script. Fuehrt DESHALB seine
    EIGENE Duplicate-Erkennung (normalisierter Artist+Titel,
    Album-vs-Single-Prioritaet) — unabhaengig vom Health-Scanner-Report,
    der hier bewusst NICHT geladen wird.

    Ohne `--dry-run` wird tatsaechlich gelöscht: `resolve_duplicates.py
    --execute --confirm-production-execute` (dessen eigene Zusatzsperre —
    verlangt zwingend einen konkreten Unterordner, niemals den gesamten
    Produktions-Root). Mit `--dry-run`: reiner read-only Scan (auch ohne
    --allow-delete bereits moeglich, siehe scripts/resolve_duplicates.py
    ALLOWED_READONLY_ROOTS)."""
    if not args.artist:
        print(
            "ERROR: --allow-delete erfordert --artist <Name> — nie der "
            "gesamte Library-Root (siehe scripts/resolve_duplicates.py "
            "--confirm-production-execute).",
            file=sys.stderr,
        )
        return 2

    config = Config()
    library_root = Path(args.library) if args.library else Path(config.LIBRARY_DIR)
    target = library_root / args.artist
    if not target.is_dir():
        print(f"ERROR: Artist-Verzeichnis nicht gefunden: {target}", file=sys.stderr)
        return 2

    cmd = [sys.executable, str(RESOLVE_DUPLICATES_SCRIPT), "--path", str(target)]
    if args.backup_dir:
        cmd += ["--backup-dir", str(args.backup_dir)]
    if not args.dry_run:
        cmd += ["--execute", "--confirm-production-execute"]
        print(
            f"⚠️  DUPLICATE EXECUTE gegen Produktion: {target}\n"
            f"    (Backup vor jedem Delete, Fingerprint-/TOCTOU-Revalidierung, "
            f"Manifest + Audit-Log unter /tmp/musicbot_test/duplicate_execution_*)"
        )
    else:
        print(f"🔍 DUPLICATE DRY-RUN (read-only): {target}")

    result = subprocess.run(cmd)
    return result.returncode


# ─────────────────────────────────────────────────────────────────────────
# Library-Maintenance-Actions (ARCH-032 Phase 3D) — Command-getrieben,
# KEIN Health-Scan/Planner-Bezug (ARCH-031 B.1). Ruft services/library_repair/
# artist.py + genre.py (Domain) und executor.py (Mutation) DIREKT auf -
# genau wie der Rest dieses Scripts fuer L1/L2/L3/Cover/Loudness bereits
# tut (kein Lock/Run-Index hier, identische Asymmetrie CLI-vs-Telegram
# wie beim bestehenden Health-Finding-Flow: nur der Telegram-Pfad
# (services/library_repair/maintenance_service.py) nutzt den geteilten
# Lock + Run-Index, ARCH-031 B.6). Ersetzt scripts/fix_artist_casing.py /
# scripts/remove_legacy_genre_atom.py / scripts/set_genre.py.
# ─────────────────────────────────────────────────────────────────────────


def _collect_maintenance_targets(args, library_root: Path) -> list:
    """--artist/--path/--all-Zielauswahl - identische Semantik zu den
    abgeloesten Original-Scripts (collect_targets())."""
    from services.library_repair.maintenance_service import artist_targets

    if args.path:
        p = Path(args.path).resolve()
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.m4a"))
        else:
            raise SystemExit(f"❌ Pfad existiert nicht: {p}")
        return [
            str(f.relative_to(library_root)) if library_root in f.parents else str(f)
            for f in files
        ]
    if args.all:
        return sorted(str(f.relative_to(library_root)) for f in library_root.rglob("*.m4a"))
    if args.artist:
        return artist_targets(args.artist, library_root=library_root)
    raise SystemExit("❌ --artist, --path oder --all angeben")


def _update_manual_genre_mapping(
    artist: str, genre: str, mapping_dir: Path, *, dry_run: bool
) -> None:
    """CLI-only (ARCH-031 A.4): traegt den geschriebenen Genre-Wert
    zusaetzlich in mapping/artist_genre.yaml ein - unveraendert aus
    scripts/set_genre.py::update_manual_mapping() uebernommen. Kein
    Backup-/Journal-Muster wie der Executor (fachliche Config-Aenderung,
    keine Library-Datei-Mutation)."""
    import yaml

    path = mapping_dir / "artist_genre.yaml"
    if not path.exists():
        print(f"⚠️  {path} fehlt — Mapping-Update uebersprungen")
        return

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mapping = data.get("ARTIST_GENRE_MAP") or {}

    parts = [p.strip() for p in genre.split(";") if p.strip()]
    primary = parts[0] if parts else genre
    secondary = parts[1:] if len(parts) > 1 else []

    key = artist.lower()
    existing = mapping.get(key)
    new_entry = {
        "primary": primary,
        "secondary": secondary,
        "description": (existing or {}).get(
            "description",
            "Manuell gesetzt via library_repair.py --maintenance-action set-genre",
        ),
    }

    if existing == new_entry:
        print(f"ℹ️  {key} bereits in artist_genre.yaml mit identischem Eintrag")
        return

    if dry_run:
        print(
            f"📝 [DRY-RUN] wuerde {key} -> {new_entry} in {path} eintragen "
            f"(bisher: {existing!r})"
        )
        return

    mapping[key] = new_entry
    data["ARTIST_GENRE_MAP"] = mapping
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    tmp.replace(path)
    print(f"✅ {key} -> {new_entry} in {path} eingetragen")


def _run_maintenance_action(args) -> int:
    from services.library_repair import artist as artist_domain
    from services.library_repair.executor import (
        apply_artist_casing,
        apply_legacy_genre_cleanup,
        apply_set_genre,
    )
    from services.library_repair.journal import RepairJournal
    from services.library_repair.maintenance_service import (
        MaintenanceServiceError,
        resolve_target_genre,
    )

    config = Config()
    logger = get_module_logger("library_repair.maintenance")
    library_root = Path(args.library) if args.library else Path(config.LIBRARY_DIR)
    mapping_dir = Path(config.GENRE_MAPPING_DIR)

    try:
        targets = _collect_maintenance_targets(args, library_root)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    if not targets:
        print("❌ Keine .m4a-Dateien gefunden.", file=sys.stderr)
        return 2

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"🛠️  Maintenance-Action: {args.maintenance_action} — {mode}")
    print(f"   Library: {library_root}")
    print(f"   Ziele:   {len(targets)} Datei(en)")

    journal_path = Path(config.DATA_DIR) / "library_repair_journal.jsonl"
    journal = RepairJournal(journal_path)

    target_genre = None
    if args.maintenance_action == "artist-casing":
        casing_map = artist_domain.load_casing_map(mapping_dir)
        if not casing_map:
            print(
                "❌ Keine Casing-Mappings gefunden "
                "(artist_overrides.json / case_preserve.yaml fehlen oder leer).",
                file=sys.stderr,
            )
            return 2
        outcomes = apply_artist_casing(
            targets, library_root, journal, casing_map=casing_map, dry_run=dry_run,
        )
    elif args.maintenance_action == "legacy-genre-cleanup":
        outcomes = apply_legacy_genre_cleanup(targets, library_root, journal, dry_run=dry_run)
    elif args.maintenance_action == "set-genre":
        try:
            target_genre = resolve_target_genre(
                args.artist or "", genre=args.genre, from_mapping=args.from_mapping,
                mapping_dir=mapping_dir,
            )
        except MaintenanceServiceError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
        print(f"   Genre:   {target_genre!r}")
        outcomes = apply_set_genre(
            targets, library_root, journal, target_genre=target_genre,
            only_if_missing=args.only_if_missing, dry_run=dry_run,
        )
    else:  # pragma: no cover - von argparse choices bereits ausgeschlossen
        print(f"❌ Unbekannte --maintenance-action: {args.maintenance_action}", file=sys.stderr)
        return 2

    print("─" * 70)
    journal.flush()

    for oc in outcomes:
        icon = {"SUCCESS": "✅", "DRY_RUN": "🔍", "SKIPPED": "⏭️", "FAILED": "❌"}.get(
            oc.status, "•"
        )
        print(f"{icon} {oc.status:<10} {oc.file}")
        if oc.before or oc.after:
            print(f"     {oc.before} → {oc.after}")
        if oc.reason:
            print(f"     ({oc.reason})")

    from collections import Counter

    tally = Counter(o.status for o in outcomes)
    print("─" * 70)
    print(
        f"{tally.get('SUCCESS', 0)} success · {tally.get('DRY_RUN', 0)} would-change · "
        f"{tally.get('SKIPPED', 0)} skipped · {tally.get('FAILED', 0)} failed"
        f"  →  Journal: {journal_path}"
    )

    if args.update_manual_mapping:
        if args.maintenance_action != "set-genre":
            print("⚠️  --update-manual-mapping nur mit --maintenance-action set-genre wirksam.")
        elif not (args.artist and args.genre):
            print("⚠️  --update-manual-mapping erfordert --artist UND --genre (kein --from-mapping).")
        else:
            print()
            _update_manual_genre_mapping(args.artist, target_genre, mapping_dir, dry_run=dry_run)

    return 1 if any(o.status == "FAILED" for o in outcomes) else 0


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
    parser.add_argument(
        "--library",
        default=None,
        help="Library-Wurzel fuer den Scan (Default: config.Config.LIBRARY_DIR).",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Vorhandenen Health-Report (JSON) verwenden statt neu zu scannen.",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="Reparaturplan als JSON schreiben.",
    )
    parser.add_argument("--artist", default=None, help="Nur diesen Artist.")
    parser.add_argument(
        "--issue",
        dest="issue_code",
        default=None,
        help="Nur diesen Issue-Code (z. B. LOUDNESS_OFF_TARGET).",
    )
    parser.add_argument(
        "--severity",
        default=None,
        help="Nur diese Severity (INFO/WARNING/ERROR/CRITICAL).",
    )
    parser.add_argument(
        "--level", default=None, help="Nur diese Reparaturstufe (z. B. SAFE_AUTOMATIC)."
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Level-1-Tag-Reparaturen tatsaechlich ausfuehren (mit Per-Datei-"
        "Backup, Journal, Before/After, Verification-Scan). Ohne dieses "
        "Flag: nur Plan (DRY-RUN).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explizit nur Plan/Vorschau (Default-Verhalten).",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Verzeichnis fuer Rollback-Kopien "
        "(Default: <library>/../.library_repair_backups, "
        "ausserhalb der Library).",
    )
    parser.add_argument(
        "--allow-delete",
        dest="allow_delete",
        action="store_true",
        help="Duplicate-Aufloesung ausfuehren (destruktiv) - dockt an das "
        "bestehende, bereits gehaertete scripts/resolve_duplicates.py "
        "an (kein eigener Loesch-Code). Erfordert --artist (nie der "
        "gesamte Library-Root). Ohne --dry-run wird tatsaechlich "
        "gelöscht (mit Backup + Rollback), mit --dry-run nur Vorschau.",
    )
    parser.add_argument(
        "--no-navidrome-scan",
        dest="no_navidrome_scan",
        action="store_true",
        help="Automatischen Navidrome-Scan nach einem --apply-Lauf mit "
        "echten Aenderungen unterdruecken (Phase 3, P1.2). Ohne dieses "
        "Flag wird nach mindestens einem SUCCESS-Outcome automatisch "
        "NavidromeScanTrigger.run_scan() aufgerufen; bei --dry-run "
        "(bzw. ohne --apply) nie.",
    )
    parser.add_argument(
        "--maintenance-action",
        dest="maintenance_action",
        choices=["artist-casing", "legacy-genre-cleanup", "set-genre"],
        default=None,
        help="Library-Maintenance-Action statt Health-Finding-Flow "
        "(ARCH-032 Phase 3D) - kein Health-Scan, keine Planner-Nutzung. "
        "Erfordert --artist, --path oder --all.",
    )
    parser.add_argument(
        "--path", default=None,
        help="Maintenance-Action: einzelne Datei oder Verzeichnis (CLI-only).",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Maintenance-Action: ganze Library (CLI-only, Vorsicht!).",
    )
    parser.add_argument(
        "--genre", default=None,
        help='Maintenance-Action set-genre: manueller Genre-Wert, z. B. "Hip Hop; Rap".',
    )
    parser.add_argument(
        "--from-mapping", dest="from_mapping", action="store_true",
        help="Maintenance-Action set-genre: Genre aus mapping/artist_genre.yaml "
        "lesen (erfordert --artist).",
    )
    parser.add_argument(
        "--only-if-missing", dest="only_if_missing", action="store_true",
        help="Maintenance-Action set-genre: nur schreiben, wenn noch kein "
        "Genre-Tag existiert (CLI-only).",
    )
    parser.add_argument(
        "--update-manual-mapping", dest="update_manual_mapping", action="store_true",
        help="Maintenance-Action set-genre: Artist zusaetzlich in "
        "mapping/artist_genre.yaml eintragen (nur mit --artist und --genre, "
        "CLI-only, kein Telegram-Trigger, ARCH-031 A.4).",
    )

    args = parser.parse_args(argv)

    if args.maintenance_action:
        return _run_maintenance_action(args)

    if args.allow_delete:
        return _run_duplicate_resolution(args)

    config = Config()
    logger = get_module_logger("library_repair")
    library_root = Path(args.library) if args.library else Path(config.LIBRARY_DIR)

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
            plan,
            artist=args.artist,
            issue_code=args.issue_code,
            severity=args.severity,
            level=args.level,
        )

    print(render_plan_text(plan))

    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(plan.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\n📄 Plan: {out}")

    if not args.apply:
        return 0

    # ── Ausfuehrung ─────────────────────────────────────────────────────
    from services.library_repair.executor import (
        ALBUM_COVER_CODES,
        COVER_ISSUE_CODES,
        EXTERNAL_MB_CODES,
        L1_RENAME_CODES,
        L1_TAG_CODES,
        L2_CODES,
        LOUDNESS_ISSUE_CODES,
        apply_album_cover_unify,
        apply_cover_repairs,
        apply_external_metadata,
        apply_level1,
        apply_level1_rename,
        apply_level2,
        apply_replaygain,
    )
    from services.library_repair.journal import RepairJournal

    execute_dry = args.dry_run
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    journal_path = Path(config.DATA_DIR) / "library_repair_journal.jsonl"
    journal = RepairJournal(journal_path)

    l1_tags = [c for c in plan.candidates if c.issue_code in L1_TAG_CODES]
    l1_rename = [c for c in plan.candidates if c.issue_code in L1_RENAME_CODES]
    # Cover ist EXTERN (Netzwerk) und langsam -> nur auf ausdrueckliche
    # Anforderung (--level COVER oder --issue ARTWORK_*), nie im Default-Lauf.
    _lvl = (args.level or "").upper()
    cover_requested = _lvl == "COVER" or args.issue_code in COVER_ISSUE_CODES
    album_cover_requested = _lvl == "COVER" or args.issue_code in ALBUM_COVER_CODES
    cover_cands = (
        [c for c in plan.candidates if c.issue_code in COVER_ISSUE_CODES]
        if cover_requested
        else []
    )
    album_cover_cands = (
        [c for c in plan.candidates if c.issue_code in ALBUM_COVER_CODES]
        if album_cover_requested
        else []
    )
    # L3 MusicBrainz-IDs: extern/rate-limited -> nur auf ausdrueckliche Anforderung
    mb_requested = _lvl == "EXTERNAL_METADATA" or args.issue_code in EXTERNAL_MB_CODES
    mb_cands = (
        [c for c in plan.candidates if c.issue_code in EXTERNAL_MB_CODES]
        if mb_requested
        else []
    )
    # L2 volle Neuverarbeitung: langsam (Genius/MusicBrainz/Cover pro Datei) und
    # mit breitem Effekt (Titel/Album/Genre/Lyrics/Cover/MB-IDs/Rename +
    # Auto-Learn-Mapping-Update) -> nur auf ausdrueckliche Anforderung.
    l2_requested = _lvl == "METADATA_REPROCESSING" or args.issue_code in L2_CODES
    l2_cands = (
        [c for c in plan.candidates if c.issue_code in L2_CODES] if l2_requested else []
    )
    # Loudness: verlustfreier RG-Tag -> nur auf ausdrueckliche Anforderung
    # (setzt einen --measure-loudness-Report voraus)
    loudness_requested = _lvl == "LOUDNESS" or args.issue_code in LOUDNESS_ISSUE_CODES
    loudness_cands = (
        [c for c in plan.candidates if c.issue_code in LOUDNESS_ISSUE_CODES]
        if loudness_requested
        else []
    )

    if not (
        l1_tags
        or l1_rename
        or cover_cands
        or album_cover_cands
        or mb_cands
        or l2_cands
        or loudness_cands
    ):
        print("\nKeine ausfuehrbaren Reparaturen im (gefilterten) Plan.")
        return 0

    mode = "DRY-RUN (keine Datei wird veraendert)" if execute_dry else "EXECUTE"
    print(
        f"\n{'=' * 70}\nREPAIR {mode} — {len(l1_tags)} Tag-Fixes + "
        f"{len(l1_rename)} Renames + {len(cover_cands)} Cover + "
        f"{len(album_cover_cands)} Album-Cover + {len(mb_cands)} MB-IDs + "
        f"{len({c.path for c in l2_cands})} L2-Neuverarbeitung + "
        f"{len(loudness_cands)} Loudness\n{'=' * 70}"
    )
    if l2_cands and not execute_dry:
        print(
            "⚠️  L2 EXECUTE: die volle Pipeline aktualisiert dabei auch die "
            "Auto-Learn-Mappings (mapping/auto_learned_*) mit den beobachteten "
            "Feature-Artists/Genres der Tracks — wie bei einem frischen Download."
        )
    if loudness_cands and not execute_dry:
        print(
            "ℹ️  LOUDNESS EXECUTE: schreibt einen verlustfreien "
            "replaygain_track_gain-/_peak-Tag (Ziel -16 LUFS) — Audio "
            "byte-identisch. Wirksam nur in ReplayGain-fähigen Playern "
            "(Navidrome). Per-Datei-Backup + Rollback."
        )

    outcomes = apply_level1(
        l1_tags, library_root, journal, dry_run=execute_dry, backup_dir=backup_dir
    )
    outcomes += apply_level1_rename(
        l1_rename, library_root, journal, dry_run=execute_dry
    )

    if cover_cands:
        outcomes += apply_cover_repairs(
            cover_cands,
            library_root,
            journal,
            _build_cover_fetcher(config, logger),
            dry_run=execute_dry,
            backup_dir=backup_dir,
        )
    if album_cover_cands:
        outcomes += apply_album_cover_unify(
            album_cover_cands,
            library_root,
            journal,
            dry_run=execute_dry,
            backup_dir=backup_dir,
        )
    if mb_cands:
        outcomes += apply_external_metadata(
            mb_cands,
            library_root,
            journal,
            _build_mb_lookup(logger),
            dry_run=execute_dry,
            backup_dir=backup_dir,
        )
    if l2_cands:
        outcomes += apply_level2(
            l2_cands,
            library_root,
            journal,
            _build_reprocess(config, logger),
            dry_run=execute_dry,
            backup_dir=backup_dir,
        )
    if loudness_cands:
        outcomes += apply_replaygain(
            loudness_cands,
            library_root,
            journal,
            _build_lufs_measure(),
            dry_run=execute_dry,
            backup_dir=backup_dir,
        )
    journal.flush()

    for oc in outcomes:
        print(f"\nFILE:   {oc.file}\nISSUE:  {oc.issue_code}\nACTION: {oc.action}")
        if oc.before or oc.after:
            print(f"BEFORE: {oc.before}\nAFTER:  {oc.after}")
        print(f"STATUS: {oc.status}" + (f"  ({oc.reason})" if oc.reason else ""))

    from collections import Counter

    tally = Counter(o.status for o in outcomes)
    unresolved_line = (
        f" · {tally['UNRESOLVED']} unresolved" if tally.get("UNRESOLVED") else ""
    )
    print(
        f"\n{tally.get('SUCCESS', 0)} success · {tally.get('DRY_RUN', 0)} would-change · "
        f"{tally.get('SKIPPED', 0)} skipped · {tally.get('FAILED', 0)} failed"
        f"{unresolved_line}  →  Journal: {journal_path}"
    )
    if tally.get("UNRESOLVED"):
        print(
            "⚠️  UNRESOLVED: geschrieben, aber der Health-Check erkennt den Befund "
            "weiterhin (siehe Datei-Ausgabe oben) — nicht als behoben gewertet."
        )

    if execute_dry:
        return 0

    # Phase 3, P1.2: Navidrome-Auto-Scan nach echter Aenderung. Wiederverwendet
    # bewusst exakt den bereits oben berechneten, ungefilterten `tally`-Wert
    # (Z. "tally = Counter(o.status for o in outcomes)") statt einer neuen,
    # eigenen SUCCESS-Definition - keine abweichende/breitere Interpretation
    # von "es gab eine Aenderung" gegenueber dem Rest dieses Scripts.
    # "geschrieben" = SUCCESS ODER UNRESOLVED (beide haben die Datei auf der
    # Platte veraendert; nur die Verifikation unterscheidet sie) — Navidrome
    # soll die geaenderte Datei so oder so erneut einlesen.
    wrote_to_disk = tally.get("SUCCESS", 0) + tally.get("UNRESOLVED", 0)
    if wrote_to_disk > 0 and not args.no_navidrome_scan:
        _trigger_navidrome_scan(logger)

    touched = {
        o.issue_code for o in outcomes if o.status in ("SUCCESS", "UNRESOLVED")
    }
    _wrote = ("SUCCESS", "UNRESOLVED")
    if mb_cands and any(
        o.status in _wrote for o in outcomes if o.issue_code in EXTERNAL_MB_CODES
    ):
        touched |= set(EXTERNAL_MB_CODES)
    if l2_cands and any(
        o.status == "SUCCESS" for o in outcomes if o.action == "METADATA_REPROCESS"
    ):
        # eine L2-Neuverarbeitung berührt potenziell jeden METADATA_REPROCESSING-Code
        touched |= set(L2_CODES)
    if loudness_cands and any(
        o.status in _wrote for o in outcomes if o.action == "LOUDNESS_NORMALIZE"
    ):
        touched |= set(LOUDNESS_ISSUE_CODES)
    return _verification_scan(
        report,
        library_root,
        config,
        logger,
        touched,
        measure_loudness=bool(loudness_cands),
    )


def _trigger_navidrome_scan(logger) -> None:
    """Phase 3, P1.2: loest nach einem --apply-Lauf mit echten Aenderungen
    (mind. ein SUCCESS-Outcome) automatisch einen Navidrome-Scan aus.

    Ein fehlschlagender/nicht konfigurierter Scan darf den Exit-Code dieses
    Repair-Laufs NICHT beeinflussen - der Repair-Erfolg selbst ist davon
    unabhaengig. Deshalb wird hier jede Exception abgefangen und nur
    geloggt, nicht weitergereicht."""
    import asyncio

    from utils.navidrome_scan_trigger import NavidromeScanTrigger

    try:
        result = asyncio.run(NavidromeScanTrigger.run_scan())
        if result.success:
            print(f"\n🔄 Navidrome-Scan automatisch ausgeloest (Erfolg).")
        else:
            print(
                f"\n⚠️  Navidrome-Scan automatisch ausgeloest, aber "
                f"fehlgeschlagen (Return Code {result.returncode}) - "
                f"Repair-Ergebnis davon unberuehrt."
            )
    except Exception as e:  # noqa: BLE001 - Scan-Fehler duerfen den Repair-Exit-Code nicht aendern
        logger.warning(f"Automatischer Navidrome-Scan nach Repair fehlgeschlagen: {e}")
        print(
            f"\n⚠️  Automatischer Navidrome-Scan fehlgeschlagen ({e}) - "
            f"Repair-Ergebnis davon unberuehrt."
        )


def _build_cover_fetcher(config, logger):
    """Injiziert den bestehenden CoverProcessor als reinen Callable
    ctx-dict -> (bytes | None, source | None). Cover-Suche wird IMMER
    ausgefuehrt (auch bei vorhandenem Cover) — die only-if-better-
    Entscheidung trifft cover_repairs.decide_cover_action()."""
    from services.metadata.cover_processor import CoverProcessor

    fanart_key = getattr(config, "FANART_API_KEY", None)
    cp = CoverProcessor(
        fanart_api_key=fanart_key, logger=get_module_logger("library_repair.cover")
    )

    def _fetch(ctx: dict):
        return cp.get_cover_art(
            artist_name=ctx.get("artist"),
            track_title=ctx.get("title"),
            release_id=ctx.get("mb_release_id"),
            release_group_mbid=ctx.get("mb_release_group_id"),
            artist_mbid=ctx.get("mb_artist_id"),
            recording_id=ctx.get("mb_recording_id"),
            isrc=ctx.get("isrc"),
        )

    return _fetch


def _build_mb_lookup(logger):
    """Injiziert MusicBrainzClient als reinen Callable (artist, title) ->
    fetch_metadata()-dict. Die Eindeutigkeit des Matches prueft der Client
    selbst (Config.MUSICBRAINZ_MIN_SIMILARITY, MB-01)."""
    import asyncio

    from services.clients.musicbrainz_client import MusicBrainzClient

    client = MusicBrainzClient(logger=get_module_logger("library_repair.mb"))

    def _lookup(artist: str, title: str) -> dict:
        try:
            return asyncio.run(client.fetch_metadata(title=title, artist=artist)) or {}
        except Exception:  # noqa: BLE001
            return {}

    return _lookup


def _build_reprocess(config, logger):
    """Injiziert die echte Pro-Datei-Pipeline (track_reprocessor.process_file)
    als Callable (path, artist_root, dry_run) -> result-dict. Konstruiert
    EnhancedMetadataProcessor + MB-/LastFM-Client EINMAL mit der echten
    config.Config (dieses CLI ist ein eigener Prozess — First-Mover-Singleton
    ist damit die reale Instanz, identisch zum Health-Scan in derselben
    Ausführung)."""
    import asyncio

    from services.clients.lastfm_client import LastFMClient
    from services.clients.musicbrainz_client import MusicBrainzClient
    from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
    from services.metadata.track_reprocessor import NullReprocessLog, process_file

    processor = EnhancedMetadataProcessor(config=config)
    mb_client = MusicBrainzClient(logger=get_module_logger("library_repair.l2.mb"))
    lfm_client = LastFMClient(logger=get_module_logger("library_repair.l2.lfm"))
    log = NullReprocessLog()

    def _reprocess(path, artist_root, dry_run, requested_issue=None):
        return asyncio.run(
            process_file(
                path,
                artist_root,
                processor,
                mb_client,
                lfm_client,
                log,
                dry_run=dry_run,
                requested_issue=requested_issue,
            )
        )

    return _reprocess


def _build_lufs_measure():
    """measure_fn (path -> (integrierte Lautheit | None, true_peak dBTP | None))
    fuer apply_replaygain — EINE read-only FFmpeg-loudnorm-Analyse wie der
    Health-Scanner, LUFS + True Peak in einem Durchlauf."""
    from services.library_health.tag_reader import measure_loudness

    def _measure(path):
        ld = measure_loudness(path)
        return ld.integrated_lufs, ld.true_peak

    return _measure


def _verification_scan(
    before_report,
    library_root,
    config,
    logger,
    touched_codes,
    *,
    measure_loudness=False,
) -> int:
    """Prompt Abschnitt 16: nach der Reparatur erneut scannen und Before/After
    vergleichen. Ein Repair darf keine Probleme verstecken — die Ziel-Codes
    muessen sinken, es duerfen keine NEUEN Issue-Codes auftauchen."""
    from services.library_health.scanner import run_scan

    after = run_scan(
        library_root,
        supported_extensions=tuple(config.SUPPORTED_FORMATS),
        expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
        genre_mapping_dir=config.GENRE_MAPPING_DIR,
        measure_loudness=measure_loudness,
        logger=logger,
    )
    b = before_report["statistics"]["issues_by_code"]
    a = after["statistics"]["issues_by_code"]
    print(f"\n{'=' * 70}\nVERIFICATION SCAN\n{'=' * 70}")
    print(
        f"Health:  {before_report['health']['score']}  ->  {after['health']['score']}"
    )
    for code in sorted(touched_codes):
        print(f"  {code}: {b.get(code, 0)} -> {a.get(code, 0)}")
    new_codes = set(a) - set(b)
    if new_codes:
        print(f"  ⚠️  NEUE Issue-Codes nach der Reparatur: {sorted(new_codes)}")
        return 1
    regressed = [c for c in a if c not in touched_codes and a[c] > b.get(c, 0)]
    if regressed:
        print(f"  ⚠️  gestiegene Issue-Codes: {regressed}")
        return 1
    print("  ✅ keine neuen/gestiegenen Issues — Reparatur hat nichts versteckt")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nabgebrochen", file=sys.stderr)
        sys.exit(130)
