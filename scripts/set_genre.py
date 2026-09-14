#!/usr/bin/env python3
# scripts/set_genre.py
# -*- coding: utf-8 -*-
"""
Setzt den Genre-Tag gezielt fuer eine Datei, ein Verzeichnis oder einen
Artist - an der Symfonium-Konvention ausgerichtet.

Konvention (siehe Chat-Diagnose):
  - Nur ©gen wird geschrieben (kein Freeform-GENRE-Atom!)
  - Mehrere Genres: getrennt durch "; " (Semikolon + Leerzeichen)
  - Symfonium/Navidrome splitten daran zu Multi-Genre

Zwei Modi:
  --genre "A; B"      Manuell eingegebener Genre-Wert
  --from-mapping      Genre-Wert aus mapping/artist_genre.yaml
                      (primary + secondary fuer den Artist)

Safety-Modell (identisch zu remove_legacy_genre_atom.py / fix_artist_casing.py):
  - Dry-Run ist Default
  - Backup pro Datei ausserhalb der Library
  - Audio-Essenz-MD5-Verifikation
  - Atom-Fingerprint: alle anderen Atome unveraendert
  - Append-Only Journal

Nutzung:
  # Aus Mapping (empfohlen)
  python scripts/set_genre.py --artist Klangspiel --from-mapping
  python scripts/set_genre.py --artist Klangspiel --from-mapping --apply

  # Manuell
  python scripts/set_genre.py --artist Filow --genre "Deutschrap; Hip Hop" --apply
  python scripts/set_genre.py --path "/pfad/zu/datei.m4a" --genre "Pop" --apply

  # Nur wenn Genre fehlt
  python scripts/set_genre.py --artist Filow --from-mapping --only-if-missing --apply
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAPPING_FILE = PROJECT_ROOT / "mapping" / "artist_genre.yaml"
CANONICAL_ATOM = "\xa9gen"
LEGACY_ATOM = "----:com.apple.iTunes:GENRE"
TARGET_ATOMS = {CANONICAL_ATOM, LEGACY_ATOM}
JOURNAL = Path("/tmp/musicbot_test/set_genre_journal.jsonl")
BACKUP_DIR = Path(Config.LIBRARY_DIR).parent / ".library_repair_backups"


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


# ── Genre-Normalisierung ────────────────────────────────────────────────
def normalize_genre_input(raw: str) -> str:
    """Akzeptiert 'A; B' / 'A, B' / 'A / B' und liefert 'A; B'."""
    s = raw.strip()
    for sep in (" / ", ", "):
        if sep in s:
            s = s.replace(sep, "; ")
    parts = [p.strip() for p in s.split(";") if p.strip()]
    return "; ".join(parts)


# ── Mapping-Lookup (NEU) ────────────────────────────────────────────────
def genre_from_mapping(artist: str, *, mapping_path: Path = MAPPING_FILE) -> str | None:
    """Liest primary+secondary aus artist_genre.yaml fuer einen Artist
    (case-insensitive). Liefert 'A; B; C' oder None."""
    import yaml
    if not mapping_path.exists():
        return None
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    mapping = data.get("ARTIST_GENRE_MAP") or {}

    key = artist.casefold()
    entry = None
    for k, v in mapping.items():
        if isinstance(k, str) and k.casefold() == key:
            entry = v
            break

    if not entry or not isinstance(entry, dict):
        return None

    primary = (entry.get("primary") or "").strip()
    secondary = entry.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []

    parts = [primary] + [str(x).strip() for x in secondary if str(x).strip()]
    seen = set()
    uniq = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return "; ".join(uniq) if uniq else None


def _known_artist_keys(mapping_path: Path) -> list[str]:
    """Hilfsfunktion fuer Fehlermeldung, wenn Artist nicht gefunden."""
    import yaml
    if not mapping_path.exists():
        return []
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    return sorted(k for k in (data.get("ARTIST_GENRE_MAP") or {}).keys()
                  if isinstance(k, str))


# ── Pro-Datei-Verarbeitung ──────────────────────────────────────────────
def set_one(path: Path, *, genre: str, dry_run: bool, library_root: Path,
            only_if_missing: bool) -> dict:
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
    cur_genre_raw = tags.get(CANONICAL_ATOM)
    cur_genre = (cur_genre_raw[0] if cur_genre_raw else "") or ""
    cur_legacy = tags.get(LEGACY_ATOM)

    if only_if_missing and cur_genre:
        result["status"] = "SKIPPED"
        result["reason"] = f"Genre existiert bereits ({cur_genre!r})"
        return result

    if cur_genre == genre and not cur_legacy:
        result["status"] = "UNCHANGED"
        return result

    result["before"] = cur_genre
    result["after"] = genre
    result["legacy_will_be_removed"] = bool(cur_legacy)

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
        mp4_tmp.tags[CANONICAL_ATOM] = [genre]
        mp4_tmp.tags.pop(LEGACY_ATOM, None)
        mp4_tmp.save()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        result["status"] = "FAILED"
        result["reason"] = f"Schreibfehler: {e}"
        return result

    try:
        verify = MP4(tmp)
        v_tags = dict(verify.tags or {})
        v_genre = v_tags.get(CANONICAL_ATOM)
        v_genre_str = (v_genre[0] if v_genre else "") or ""
        if v_genre_str != genre:
            raise ValueError(f"©gen falsch: {v_genre_str!r} != {genre!r}")
        if v_tags.get(LEGACY_ATOM) is not None:
            raise ValueError("Legacy-Atom wieder aufgetaucht")
        others_after = tags_fingerprint(v_tags, exclude=TARGET_ATOMS)
        if others_after != others_before:
            raise ValueError("Andere Atome wurden veraendert")
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
            "genre_before": cur_genre,
            "genre_after": genre,
            "legacy_removed": bool(cur_legacy),
            "audio_essence_before": essence_before,
            "audio_essence_after": essence_after,
            "sha256_before": sha_before,
            "sha256_after": sha_after,
            "backup": str(backup),
        }, ensure_ascii=False) + "\n")

    result["status"] = "SUCCESS"
    result["backup"] = str(backup)
    return result


# ── Manual-Mapping-Update ───────────────────────────────────────────────
def update_manual_mapping(artist: str, genre: str, *, dry_run: bool) -> None:
    import yaml
    path = MAPPING_FILE
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
        "description": (existing or {}).get("description", "Manuell gesetzt via set_genre.py"),
    }

    if existing == new_entry:
        print(f"ℹ️  {key} bereits in artist_genre.yaml mit identischem Eintrag")
        return

    if dry_run:
        print(f"📝 [DRY-RUN] wuerde {key} -> {new_entry} in {path} eintragen "
              f"(bisher: {existing!r})")
        return

    mapping[key] = new_entry
    data["ARTIST_GENRE_MAP"] = mapping
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.replace(path)
    print(f"✅ {key} -> {new_entry} in {path} eingetragen")


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

    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--genre", help='Genre-Wert, z.B. "Hip Hop; Rap"')
    src.add_argument("--from-mapping", action="store_true",
                     help="Genre aus mapping/artist_genre.yaml lesen (erfordert --artist)")

    parser.add_argument("--only-if-missing", action="store_true",
                        help="Nur schreiben, wenn noch KEIN Genre-Tag existiert")
    parser.add_argument("--update-manual-mapping", action="store_true",
                        help="Artist in mapping/artist_genre.yaml eintragen "
                             "(nur mit --artist und --genre)")
    parser.add_argument("--apply", action="store_true",
                        help="Echtes Schreiben (Default: Dry-Run)")
    args = parser.parse_args()

    # ── Modus-Konsistenz ────────────────────────────────────────────────
    if args.from_mapping and not args.artist:
        raise SystemExit("❌ --from-mapping erfordert --artist (kein Mapping-Lookup "
                         "fuer --path/--all moeglich).")
    if args.from_mapping and args.update_manual_mapping:
        raise SystemExit("❌ --from-mapping und --update-manual-mapping sind "
                         "redundant — das Mapping kommt ja gerade von dort.")

    # ── Genre bestimmen ─────────────────────────────────────────────────
    if args.from_mapping:
        genre = genre_from_mapping(args.artist)
        if not genre:
            known = _known_artist_keys(MAPPING_FILE)
            msg = (f"❌ Artist {args.artist!r} nicht in {MAPPING_FILE} gefunden "
                   f"(case-insensitive Lookup).\n")
            if known:
                msg += (f"   Verfuegbare Keys ({len(known)}): "
                        f"{', '.join(known[:15])}"
                        + (" …" if len(known) > 15 else ""))
            raise SystemExit(msg)
        print(f"📖 Genre aus Mapping fuer {args.artist!r}: {genre!r}")
    else:
        genre = normalize_genre_input(args.genre)
        if not genre:
            raise SystemExit("❌ --genre ist leer nach Normalisierung.")

    targets, library_root = collect_targets(args)
    if not targets:
        raise SystemExit("❌ Keine .m4a-Dateien gefunden.")

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    print(f"🎼 set_genre — {mode}")
    print(f"   Library: {library_root}")
    print(f"   Genre:   {genre!r}")
    print(f"   Ziele:   {len(targets)} Datei(en)")
    if args.only_if_missing:
        print(f"   Modus:   --only-if-missing (bestehende Genres werden NICHT ueberschrieben)")
    print("─" * 70)

    results = []
    for f in targets:
        r = set_one(f, genre=genre, dry_run=dry_run,
                    library_root=library_root,
                    only_if_missing=args.only_if_missing)
        results.append(r)
        rel = f.relative_to(library_root) if library_root in f.parents else f.name
        icon = {"SUCCESS": "✅", "DRY_RUN": "🔍", "UNCHANGED": "⏭️",
                "SKIPPED": "⏭️", "FAILED": "❌"}[r["status"]]
        line = f"{icon} {r['status']:<10} {rel}"
        if r.get("reason"):
            line += f"  ({r['reason']})"
        elif r["status"] in ("SUCCESS", "DRY_RUN"):
            line += f"  {r.get('before', '')!r} → {r.get('after', '')!r}"
            if r.get("legacy_will_be_removed"):
                line += "  [Legacy-GENRE wird entfernt]"
        print(line)

    from collections import Counter
    tally = Counter(r["status"] for r in results)
    print("─" * 70)
    print(" ".join(f"{k}:{v}" for k, v in tally.items()))

    if args.update_manual_mapping and args.artist and args.genre:
        print()
        update_manual_mapping(args.artist, genre, dry_run=dry_run)

    if any(r["status"] == "FAILED" for r in results):
        print("\n⚠️  FAILED-Dateien:")
        for r in results:
            if r["status"] == "FAILED":
                print(f"   {r['path']}: {r['reason']}")
        sys.exit(1)


if __name__ == "__main__":
    main()