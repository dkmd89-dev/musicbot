#!/usr/bin/env python3
# scripts/remove_legacy_genre_atom.py
# -*- coding: utf-8 -*-
"""
Entfernt das Legacy-Freeform-Atom '----:com.apple.iTunes:GENRE'
aus .m4a-Dateien, WENN ein kanonisches '©gen' existiert.

Sicherheitsmodell:
  - Dry-Run ist Default
  - Backup pro Datei ausserhalb der Library
  - Audio-Essenz-MD5-Verifikation (Audio byte-identisch)
  - Append-Only Journal
  - Nur Dateien, bei denen ©gen bereits vorhanden ist

Nutzung:
  python scripts/remove_legacy_genre_atom.py --artist "Eli Preiss"
  python scripts/remove_legacy_genre_atom.py --artist "Eli Preiss" --apply
  python scripts/remove_legacy_genre_atom.py --all              # ganze Library (Vorsicht!)
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config
from mutagen.mp4 import MP4

LEGACY_ATOM = "----:com.apple.iTunes:GENRE"
CANONICAL_ATOM = "\xa9gen"
JOURNAL = Path("/tmp/musicbot_test/remove_legacy_genre_journal.jsonl")
BACKUP_DIR = Path(Config.LIBRARY_DIR).parent / ".library_repair_backups"


def essence_md5(path: Path) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def safety_check(path: Path, library_root: Path) -> str | None:
    if path.is_symlink():
        return "symlink"
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return "nicht aufloesbar"
    if library_root.resolve() not in resolved.parents:
        return "ausserhalb der Library"
    if not resolved.is_file():
        return "keine regulaere Datei"
    if resolved.suffix.lower() != ".m4a":
        return f"kein .m4a ({resolved.suffix})"
    if resolved.stat().st_size == 0:
        return "leere Datei"
    return None


def fix_one(path: Path, *, dry_run: bool, library_root: Path) -> dict:
    result = {"path": str(path), "status": "UNKNOWN", "reason": None}

    reason = safety_check(path, library_root)
    if reason:
        result["status"] = "SKIPPED"
        result["reason"] = reason
        return result

    resolved = path.resolve()
    try:
        mp4 = MP4(resolved)
    except Exception as e:
        result["status"] = "SKIPPED"
        result["reason"] = f"mutagen-Lesefehler: {e}"
        return result

    tags = mp4.tags or {}
    legacy = tags.get(LEGACY_ATOM)
    canonical = tags.get(CANONICAL_ATOM)

    if legacy is None:
        result["status"] = "SKIPPED"
        result["reason"] = "kein Legacy-Atom"
        return result

    if not canonical:
        result["status"] = "SKIPPED"
        result["reason"] = "kein ©gen vorhanden (würde Information verlieren)"
        return result

    # Legacy-Wert normalisieren für Vergleich
    def as_text(v):
        if isinstance(v, list) and v:
            x = v[0]
            if isinstance(x, bytes):
                return x.decode("utf-8", errors="replace")
            return str(x)
        return str(v)

    legacy_text = as_text(legacy)
    legacy_normalized = legacy_text.replace(", ", "; ").replace(" / ", "; ")
    canonical_text = canonical[0] if canonical else ""

    if legacy_normalized != canonical_text:
        # Inhaltliche Abweichung — trotzdem entfernen, aber im Journal markieren
        pass

    if dry_run:
        result["status"] = "DRY_RUN"
        result["legacy"] = legacy_text
        result["canonical"] = canonical_text
        return result

    # ── ECHTER SCHREIBVORGANG ──────────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"{resolved.stem}_{stamp}{resolved.suffix}"
    shutil.copy2(resolved, backup)

    essence_before = essence_md5(resolved)
    sha_before = hashlib.sha256(resolved.read_bytes()).hexdigest()

    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    shutil.copy2(resolved, tmp)
    try:
        mp4_tmp = MP4(tmp)
        mp4_tmp.tags.pop(LEGACY_ATOM, None)
        mp4_tmp.save()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        result["status"] = "FAILED"
        result["reason"] = f"Schreibfehler: {e}"
        return result

    # Verifikation
    try:
        verify = MP4(tmp)
        if verify.tags.get(LEGACY_ATOM) is not None:
            raise ValueError("Legacy-Atom noch vorhanden")
        if verify.tags.get(CANONICAL_ATOM) != canonical:
            raise ValueError("©gen verändert")
        if essence_md5(tmp) != essence_before:
            raise ValueError("Audio-Essenz geändert")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        result["status"] = "FAILED"
        result["reason"] = f"Verifikation fehlgeschlagen: {e} (Backup: {backup})"
        return result

    tmp.replace(resolved)

    essence_after = essence_md5(resolved)
    sha_after = hashlib.sha256(resolved.read_bytes()).hexdigest()

    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": datetime.now().isoformat(),
            "path": str(resolved),
            "legacy_removed": legacy_text,
            "canonical_kept": canonical_text,
            "audio_essence_before": essence_before,
            "audio_essence_after": essence_after,
            "sha256_before": sha_before,
            "sha256_after": sha_after,
            "backup": str(backup),
        }, ensure_ascii=False) + "\n")

    result["status"] = "SUCCESS"
    result["legacy"] = legacy_text
    result["canonical"] = canonical_text
    result["backup"] = str(backup)
    return result


def collect_targets(args) -> tuple[list[Path], Path]:
    library_root = Path(Config.LIBRARY_DIR)
    if args.path:
        p = Path(args.path).resolve()
        if p.is_file():
            return [p], library_root
        if p.is_dir():
            return sorted(p.rglob("*.m4a")), library_root
        raise SystemExit(f"❌ Pfad existiert nicht: {p}")
    if args.artist:
        artist_dir = library_root / args.artist
        if not artist_dir.is_dir():
            raise SystemExit(f"❌ Artist-Verzeichnis nicht gefunden: {artist_dir}")
        return sorted(artist_dir.rglob("*.m4a")), library_root
    if args.all:
        return sorted(library_root.rglob("*.m4a")), library_root
    raise SystemExit("❌ --artist, --path oder --all angeben")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--artist", help="Artist-Verzeichnis")
    g.add_argument("--path", help="Einzelne Datei oder Verzeichnis")
    g.add_argument("--all", action="store_true", help="Ganze Library (Vorsicht!)")

    parser.add_argument("--apply", action="store_true",
                        help="Echtes Schreiben (Default: Dry-Run)")
    args = parser.parse_args()

    targets, library_root = collect_targets(args)
    if not targets:
        raise SystemExit("❌ Keine .m4a-Dateien gefunden.")

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    print(f"🧹 remove_legacy_genre_atom — {mode}")
    print(f"   Library: {library_root}")
    print(f"   Ziele:   {len(targets)} Datei(en)")
    print("─" * 70)

    results = []
    for f in targets:
        r = fix_one(f, dry_run=dry_run, library_root=library_root)
        results.append(r)
        if r["status"] in ("SUCCESS", "DRY_RUN"):
            rel = f.relative_to(library_root) if library_root in f.parents else f.name
            icon = "✅" if r["status"] == "SUCCESS" else "🔍"
            print(f"{icon} {rel}")
            print(f"     legacy:    {r['legacy']!r}")
            print(f"     ©gen:      {r['canonical']!r}")

    from collections import Counter
    tally = Counter(r["status"] for r in results)
    print("─" * 70)
    print(" ".join(f"{k}:{v}" for k, v in tally.items()))

    # SKIPPED-Gründe zusammenfassen
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    if skipped:
        reasons = Counter(r.get("reason") for r in skipped)
        print("\nÜbersprungen (Gründe):")
        for reason, count in reasons.most_common():
            print(f"  {count:4d}  {reason}")

    if any(r["status"] == "FAILED" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
