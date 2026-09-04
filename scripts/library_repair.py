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
    --allow-delete        wird mit klarer Meldung abgelehnt (Exit 2)

Cover / L3 / L2 laufen NIE im Default-`--apply`, nur auf ausdrueckliche
Anforderung per --level bzw. --issue.
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
    parser.add_argument(
        "--apply", action="store_true",
        help="Level-1-Tag-Reparaturen tatsaechlich ausfuehren (mit Per-Datei-"
             "Backup, Journal, Before/After, Verification-Scan). Ohne dieses "
             "Flag: nur Plan (DRY-RUN).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Explizit nur Plan/Vorschau (Default-Verhalten).")
    parser.add_argument("--backup-dir", default=None,
                        help="Verzeichnis fuer Rollback-Kopien "
                             "(Default: <library>/../.library_repair_backups, "
                             "ausserhalb der Library).")
    parser.add_argument("--allow-delete", dest="allow_delete", action="store_true",
                        help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.allow_delete:
        print(
            "ERROR: --allow-delete existiert noch nicht. Destruktive "
            "Reparaturen (Duplicate-Loeschung) sind noch nicht implementiert "
            "und werden ein eigenes, separat geschuetztes Flag bekommen.",
            file=sys.stderr,
        )
        return 2

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
            plan, artist=args.artist, issue_code=args.issue_code,
            severity=args.severity, level=args.level,
        )

    print(render_plan_text(plan))

    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\n📄 Plan: {out}")

    if not args.apply:
        return 0

    # ── Ausfuehrung ─────────────────────────────────────────────────────
    from services.library_repair.executor import (
        ALBUM_COVER_CODES, COVER_ISSUE_CODES, EXTERNAL_MB_CODES,
        L1_RENAME_CODES, L1_TAG_CODES, L2_CODES,
        apply_album_cover_unify, apply_cover_repairs, apply_external_metadata,
        apply_level1, apply_level1_rename, apply_level2,
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
    cover_cands = [c for c in plan.candidates if c.issue_code in COVER_ISSUE_CODES] \
        if cover_requested else []
    album_cover_cands = [c for c in plan.candidates if c.issue_code in ALBUM_COVER_CODES] \
        if album_cover_requested else []
    # L3 MusicBrainz-IDs: extern/rate-limited -> nur auf ausdrueckliche Anforderung
    mb_requested = _lvl == "EXTERNAL_METADATA" or args.issue_code in EXTERNAL_MB_CODES
    mb_cands = [c for c in plan.candidates if c.issue_code in EXTERNAL_MB_CODES] \
        if mb_requested else []
    # L2 volle Neuverarbeitung: langsam (Genius/MusicBrainz/Cover pro Datei) und
    # mit breitem Effekt (Titel/Album/Genre/Lyrics/Cover/MB-IDs/Rename +
    # Auto-Learn-Mapping-Update) -> nur auf ausdrueckliche Anforderung.
    l2_requested = _lvl == "METADATA_REPROCESSING" or args.issue_code in L2_CODES
    l2_cands = [c for c in plan.candidates if c.issue_code in L2_CODES] \
        if l2_requested else []

    if not (l1_tags or l1_rename or cover_cands or album_cover_cands or mb_cands or l2_cands):
        print("\nKeine ausfuehrbaren Reparaturen im (gefilterten) Plan.")
        return 0

    mode = "DRY-RUN (keine Datei wird veraendert)" if execute_dry else "EXECUTE"
    print(f"\n{'=' * 70}\nREPAIR {mode} — {len(l1_tags)} Tag-Fixes + "
          f"{len(l1_rename)} Renames + {len(cover_cands)} Cover + "
          f"{len(album_cover_cands)} Album-Cover + {len(mb_cands)} MB-IDs + "
          f"{len({c.path for c in l2_cands})} L2-Neuverarbeitung\n{'=' * 70}")
    if l2_cands and not execute_dry:
        print("⚠️  L2 EXECUTE: die volle Pipeline aktualisiert dabei auch die "
              "Auto-Learn-Mappings (mapping/auto_learned_*) mit den beobachteten "
              "Feature-Artists/Genres der Tracks — wie bei einem frischen Download.")

    outcomes = apply_level1(l1_tags, library_root, journal, dry_run=execute_dry,
                            backup_dir=backup_dir)
    outcomes += apply_level1_rename(l1_rename, library_root, journal, dry_run=execute_dry)

    if cover_cands:
        outcomes += apply_cover_repairs(
            cover_cands, library_root, journal, _build_cover_fetcher(config, logger),
            dry_run=execute_dry, backup_dir=backup_dir,
        )
    if album_cover_cands:
        outcomes += apply_album_cover_unify(
            album_cover_cands, library_root, journal,
            dry_run=execute_dry, backup_dir=backup_dir,
        )
    if mb_cands:
        outcomes += apply_external_metadata(
            mb_cands, library_root, journal, _build_mb_lookup(logger),
            dry_run=execute_dry, backup_dir=backup_dir,
        )
    if l2_cands:
        outcomes += apply_level2(
            l2_cands, library_root, journal, _build_reprocess(config, logger),
            dry_run=execute_dry, backup_dir=backup_dir,
        )
    journal.flush()

    for oc in outcomes:
        print(f"\nFILE:   {oc.file}\nISSUE:  {oc.issue_code}\nACTION: {oc.action}")
        if oc.before or oc.after:
            print(f"BEFORE: {oc.before}\nAFTER:  {oc.after}")
        print(f"STATUS: {oc.status}" + (f"  ({oc.reason})" if oc.reason else ""))

    from collections import Counter
    tally = Counter(o.status for o in outcomes)
    print(f"\n{tally.get('SUCCESS', 0)} success · {tally.get('DRY_RUN', 0)} would-change · "
          f"{tally.get('SKIPPED', 0)} skipped · {tally.get('FAILED', 0)} failed  "
          f"→  Journal: {journal_path}")

    if execute_dry:
        return 0
    touched = {o.issue_code for o in outcomes if o.status == "SUCCESS"}
    if mb_cands and any(o.status == "SUCCESS" for o in outcomes
                        if o.issue_code in EXTERNAL_MB_CODES):
        touched |= set(EXTERNAL_MB_CODES)
    if l2_cands and any(o.status == "SUCCESS" for o in outcomes
                        if o.action == "METADATA_REPROCESS"):
        # eine L2-Neuverarbeitung berührt potenziell jeden METADATA_REPROCESSING-Code
        touched |= set(L2_CODES)
    return _verification_scan(report, library_root, config, logger, touched)


def _build_cover_fetcher(config, logger):
    """Injiziert den bestehenden CoverProcessor als reinen Callable
    ctx-dict -> (bytes | None, source | None). Cover-Suche wird IMMER
    ausgefuehrt (auch bei vorhandenem Cover) — die only-if-better-
    Entscheidung trifft cover_repairs.decide_cover_action()."""
    from services.metadata.cover_processor import CoverProcessor

    fanart_key = getattr(config, "FANART_API_KEY", None)
    cp = CoverProcessor(fanart_api_key=fanart_key,
                        logger=get_module_logger("library_repair.cover"))

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

    def _reprocess(path, artist_root, dry_run):
        return asyncio.run(
            process_file(path, artist_root, processor, mb_client, lfm_client, log,
                         dry_run=dry_run)
        )

    return _reprocess


def _verification_scan(before_report, library_root, config, logger, touched_codes) -> int:
    """Prompt Abschnitt 16: nach der Reparatur erneut scannen und Before/After
    vergleichen. Ein Repair darf keine Probleme verstecken — die Ziel-Codes
    muessen sinken, es duerfen keine NEUEN Issue-Codes auftauchen."""
    from services.library_health.scanner import run_scan

    after = run_scan(
        library_root,
        supported_extensions=tuple(config.SUPPORTED_FORMATS),
        expected_extension=f".{config.AUDIO_FORMAT.lstrip('.')}",
        genre_mapping_dir=config.GENRE_MAPPING_DIR,
        logger=logger,
    )
    b = before_report["statistics"]["issues_by_code"]
    a = after["statistics"]["issues_by_code"]
    print(f"\n{'=' * 70}\nVERIFICATION SCAN\n{'=' * 70}")
    print(f"Health:  {before_report['health']['score']}  ->  {after['health']['score']}")
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
