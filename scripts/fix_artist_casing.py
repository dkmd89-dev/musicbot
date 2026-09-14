#!/usr/bin/env python3
# scripts/fix_artist_casing.py
# -*- coding: utf-8 -*-
"""
Normalisiert die Gross-/Kleinschreibung von Artist-Namen in ©ART und
ARTISTS (.m4a) anhand der bestehenden Mapping-Dateien.

Quellen der Wahrheit (Prioritaet absteigend):
  1. mapping/artist_overrides.json
  2. mapping/case_preserve.yaml

Es werden NUR reine Casing-Normalisierungen angewendet
(key.casefold() == value.casefold()). Namens-Erweiterungen wie
"miksu" -> "Miksu & Macloud" werden bewusst ausgefiltert — die sind
Aufgabe des ArtistIdentityResolver, nicht dieses Tools.

Safety-Modell (identisch zu remove_legacy_genre_atom.py):
  - Dry-Run ist Default
  - Backup pro Datei ausserhalb der Library
  - Audio-Essenz-MD5-Verifikation
  - Atom-Fingerprint: alle anderen Atome muessen unveraendert bleiben
  - Append-Only Journal

Nutzung:
  python scripts/fix_artist_casing.py --artist makko
  python scripts/fix_artist_casing.py --artist makko --apply
  python scripts/fix_artist_casing.py --all
  python scripts/fix_artist_casing.py --all --apply
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
from mutagen.mp4 import MP4, MP4FreeForm

# ── Konstanten ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_ATOMS = {"\xa9ART", "----:com.apple.iTunes:ARTISTS"}
JOURNAL = Path("/tmp/musicbot_test/fix_artist_casing_journal.jsonl")
BACKUP_DIR = Path(Config.LIBRARY_DIR).parent / ".library_repair_backups"


# ── Casing-Map aufbauen ─────────────────────────────────────────────────
def load_casing_map() -> dict[str, str]:
    """Liest artist_overrides.json + case_preserve.yaml und liefert
    {casefold(name): canonical_name} fuer reine Casing-Mappings."""
    m: dict[str, str] = {}

    # 1) case_preserve.yaml (Fallback)
    cp_path = PROJECT_ROOT / "mapping" / "case_preserve.yaml"
    if cp_path.exists():
        import yaml
        data = yaml.safe_load(cp_path.read_text(encoding="utf-8")) or {}
        for k, v in (data.get("case_preserve") or {}).items():
            if isinstance(k, str) and isinstance(v, str):
                if k.casefold() == v.casefold():
                    m[k.casefold()] = v

    # 2) artist_overrides.json (ueberschreibt)
    ao_path = PROJECT_ROOT / "mapping" / "artist_overrides.json"
    if ao_path.exists():
        data = json.loads(ao_path.read_text(encoding="utf-8")) or {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                if k.casefold() == v.casefold():
                    m[k.casefold()] = v

    return m


# ── Atom-Werte normalisieren ────────────────────────────────────────────
def _to_str(x) -> str:
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)


def normalize_values(values: list, casing_map: dict) -> tuple[list, list]:
    """Wendet Casing-Map auf eine Liste von Werten an.
    Returns: (neue_liste, [(alt, neu), ...])."""
    new: list = []
    changes: list[tuple[str, str]] = []
    for v in values:
        s = _to_str(v)
        canon = casing_map.get(s.casefold())
        if canon and canon != s:
            new.append(canon)
            changes.append((s, canon))
        else:
            new.append(s)
    return new, changes


# ── Safety ──────────────────────────────────────────────────────────────
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


def essence_md5(path: Path) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def tags_fingerprint(tags: dict, exclude: set) -> str:
    """Stabiler Hash ueber alle Atome ausser 'exclude' — fuer den Beweis,
    dass nur ©ART/ARTISTS geaendert wurden."""
    h = hashlib.sha256()
    for k in sorted(tags.keys()):
        if k in exclude:
            continue
        h.update(k.encode("utf-8"))
        h.update(b"\x01")
        v = tags[k]
        items = v if isinstance(v, list) else [v]
        for item in items:
            if isinstance(item, bytes):
                h.update(item)
            elif isinstance(item, str):
                h.update(item.encode("utf-8"))
            else:
                h.update(str(item).encode("utf-8"))
            h.update(b"\x00")
        h.update(b"\x02")
    return h.hexdigest()


# ── Pro-Datei-Verarbeitung ──────────────────────────────────────────────
def fix_one(path: Path, *, dry_run: bool, library_root: Path,
            casing_map: dict) -> dict:
    result: dict = {"path": str(path), "status": "UNKNOWN", "reason": None}

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

    tags = dict(mp4.tags or {})
    art_before = [_to_str(x) for x in (tags.get("\xa9ART") or [])]
    artists_before = [_to_str(x) for x in (tags.get("----:com.apple.iTunes:ARTISTS") or [])]

    art_after, art_changes = normalize_values(art_before, casing_map)
    artists_after, artists_changes = normalize_values(artists_before, casing_map)

    if not art_changes and not artists_changes:
        result["status"] = "UNCHANGED"
        return result

    result["changes"] = art_changes + artists_changes
    result["art_before"] = art_before
    result["art_after"] = art_after
    result["artists_before"] = artists_before
    result["artists_after"] = artists_after

    if dry_run:
        result["status"] = "DRY_RUN"
        return result

    # ── ECHTER SCHREIBVORGANG ───────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"{resolved.stem}_{stamp}{resolved.suffix}"
    shutil.copy2(resolved, backup)

    essence_before = essence_md5(resolved)
    sha_before = hashlib.sha256(resolved.read_bytes()).hexdigest()
    others_before = tags_fingerprint(tags, exclude=TARGET_ATOMS)

    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    shutil.copy2(resolved, tmp)
    try:
        mp4_tmp = MP4(tmp)
        if art_after:
            mp4_tmp.tags["\xa9ART"] = art_after
        else:
            mp4_tmp.tags.pop("\xa9ART", None)
        if artists_after:
            # Freeform-Atom erwartet MP4FreeForm/bytes, nicht str
            mp4_tmp.tags["----:com.apple.iTunes:ARTISTS"] = [
                MP4FreeForm(x.encode("utf-8")) for x in artists_after
            ]
        else:
            mp4_tmp.tags.pop("----:com.apple.iTunes:ARTISTS", None)
        mp4_tmp.save()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        result["status"] = "FAILED"
        result["reason"] = f"Schreibfehler: {e}"
        return result

    # Verifikation: Zielwerte + alle anderen Atome + Audio-Essenz
    try:
        verify = MP4(tmp)
        v_tags = dict(verify.tags or {})
        v_art = [_to_str(x) for x in (v_tags.get("\xa9ART") or [])]
        v_artists_raw = v_tags.get("----:com.apple.iTunes:ARTISTS") or []
        v_artists = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in v_artists_raw]
        if v_art != art_after:
            raise ValueError(f"©ART falsch: {v_art!r} != {art_after!r}")
        if v_artists != artists_after:
            raise ValueError(f"ARTISTS falsch: {v_artists!r} != {artists_after!r}")
        others_after = tags_fingerprint(v_tags, exclude=TARGET_ATOMS)
        if others_after != others_before:
            raise ValueError("Andere Atome wurden veraendert (Fingerprint-Diff)")
        if essence_md5(tmp) != essence_before:
            raise ValueError("Audio-Essenz geaendert")
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
            "changes": result["changes"],
            "art_before": art_before,
            "art_after": art_after,
            "artists_before": artists_before,
            "artists_after": artists_after,
            "audio_essence_before": essence_before,
            "audio_essence_after": essence_after,
            "sha256_before": sha_before,
            "sha256_after": sha_after,
            "backup": str(backup),
        }, ensure_ascii=False) + "\n")

    result["status"] = "SUCCESS"
    result["backup"] = str(backup)
    return result


# ── CLI-Targets ─────────────────────────────────────────────────────────
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


# ── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--artist", help="Artist-Verzeichnis unterhalb der Library")
    g.add_argument("--path", help="Einzelne Datei oder Verzeichnis")
    g.add_argument("--all", action="store_true", help="Ganze Library (Vorsicht!)")

    parser.add_argument("--apply", action="store_true",
                        help="Echtes Schreiben (Default: Dry-Run)")
    args = parser.parse_args()

    casing_map = load_casing_map()
    if not casing_map:
        raise SystemExit("❌ Keine Casing-Mappings gefunden "
                         "(artist_overrides.json / case_preserve.yaml fehlen oder leer).")

    print(f"🎤 fix_artist_casing — Casing-Map: {len(casing_map)} Eintraege")
    print(f"   Beispiele: " + ", ".join(
        f"{k!r}→{v!r}" for k, v in list(casing_map.items())[:5]))

    targets, library_root = collect_targets(args)
    if not targets:
        raise SystemExit("❌ Keine .m4a-Dateien gefunden.")

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    print()
    print(f"🎤 fix_artist_casing — {mode}")
    print(f"   Library: {library_root}")
    print(f"   Ziele:   {len(targets)} Datei(en)")
    print("─" * 70)

    results = []
    for f in targets:
        r = fix_one(f, dry_run=dry_run, library_root=library_root,
                    casing_map=casing_map)
        results.append(r)
        if r["status"] in ("SUCCESS", "DRY_RUN"):
            rel = f.relative_to(library_root) if library_root in f.parents else f.name
            icon = "✅" if r["status"] == "SUCCESS" else "🔍"
            print(f"{icon} {rel}")
            for old, new in r["changes"]:
                print(f"     {old!r} → {new!r}")

    from collections import Counter
    tally = Counter(r["status"] for r in results)
    print("─" * 70)
    print(" ".join(f"{k}:{v}" for k, v in tally.items()))

    if any(r["status"] == "FAILED" for r in results):
        print("\n⚠️  FAILED-Dateien:")
        for r in results:
            if r["status"] == "FAILED":
                print(f"   {r['path']}: {r['reason']}")
        sys.exit(1)


if __name__ == "__main__":
    main()