# services/library_repair/executor.py
# -*- coding: utf-8 -*-
"""
Repair Executor — Level 1 (SAFE_AUTOMATIC), Tag-Reparaturen.

Prompt Abschnitt 13/14/15/17: DRY-RUN ist Default; jede Änderung durchläuft
eine Safety-Prüfung; jede Änderung wird mit Before/After + Backup + Journal
dokumentiert; die Audio-Essenz wird vor/nach verglichen (ein Tag-Schreib-
vorgang darf den Ton nicht verändern).

Nur die vier deterministischen, verlustfreien Tag-Fixes:

  GENRE_DELIMITER_INCONSISTENT   ©gen:  ' / ' -> '; '
  MULTI_ARTIST_SUSPICIOUS        ©ART + ARTISTS-Freeform kanonisch splitten
  MULTI_ARTIST_INCONSISTENT      ©ART an gesplittete ARTISTS-Liste angleichen
  MULTI_ARTIST_DUPLICATE         doppelten Namen entfernen
  META_ALBUM_ARTIST_MISSING      aART = Haupt-Artist
  ALBUM_ARTIST_INCONSISTENT      aART aller Tracks = Verzeichnis-Artist

KEIN Rename (separater L1-Schritt), KEIN externer Dienst, KEIN Re-Encoding.
Der eigentliche Schreibvorgang: auf einer temporären Sibling-Kopie taggen,
erst bei erfolgreicher Verifikation atomar per Path.replace() übernehmen —
dasselbe Muster wie services/metadata/tag_writer.py.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .journal import JournalEntry, RepairJournal
from .models import RepairCandidate
from . import cover_repairs, external_metadata, rename_repairs, replaygain_repairs, tag_repairs

_ARTISTS_FREEFORM_ATOM = "----:com.apple.iTunes:ARTISTS"
_SUPPORTED = (".m4a", ".mp4", ".m4v")


def _blank(v) -> bool:
    return v is None or not str(v).strip()

# Welche Issue-Codes dieser Executor bearbeitet (Rest wird übersprungen).
L1_TAG_CODES = frozenset({
    "GENRE_DELIMITER_INCONSISTENT",
    "MULTI_ARTIST_SUSPICIOUS",
    "MULTI_ARTIST_INCONSISTENT",
    "MULTI_ARTIST_DUPLICATE",
    "META_ALBUM_ARTIST_MISSING",
    "ALBUM_ARTIST_INCONSISTENT",
})

L1_RENAME_CODES = frozenset({
    "FILENAME_TITLE_MISMATCH",
    "FILENAME_SUSPICIOUS",
})


@dataclass
class ExecOutcome:
    file: str
    issue_code: str
    action: str
    status: str                 # SUCCESS | FAILED | SKIPPED | DRY_RUN
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    reason: Optional[str] = None
    backup_path: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────
# Safety (Prompt Abschnitt 14)
# ─────────────────────────────────────────────────────────────────────────


def safety_check(path: Path, library_root: Path) -> Optional[str]:
    """Gibt einen Ablehnungsgrund zurück oder None, wenn die Datei sicher
    bearbeitet werden darf."""
    try:
        if path.is_symlink():
            return "Symlink"
        resolved = path.resolve(strict=True)
    except OSError as e:
        return f"nicht auflösbar ({e})"
    root = library_root.resolve()
    if root != resolved and root not in resolved.parents:
        return f"außerhalb der Library ({resolved})"
    if not resolved.is_file():
        return "kein reguläres File"
    if resolved.suffix.lower() not in _SUPPORTED:
        return f"nicht unterstütztes Format ({resolved.suffix})"
    try:
        if resolved.stat().st_size == 0:
            return "leere Datei"
    except OSError as e:
        return f"stat fehlgeschlagen ({e})"
    return None


# ─────────────────────────────────────────────────────────────────────────
# Hashes
# ─────────────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _audio_essence_md5(path: Path) -> str:
    """Hasht NUR den dekodierten Audio-Stream (kein Container/Tags) —
    verbindlicher Beweis, dass der Tag-Schreibvorgang den Ton nicht
    verändert hat (identisch zu reprocess_artist_metadata.py)."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
            capture_output=True, text=True, timeout=120, check=True,
        )
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


# ─────────────────────────────────────────────────────────────────────────
# Tag-Lesen/-Schreiben (nur die betroffenen Atome)
# ─────────────────────────────────────────────────────────────────────────


def _read_atoms(path: Path) -> dict:
    from mutagen.mp4 import MP4

    tags = MP4(path).tags or {}

    def _txt(values):
        return [
            v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            for v in (values or [])
        ]

    return {
        "genre": _txt(tags.get("©gen")),
        "artist": _txt(tags.get("©ART")),
        "album_artist": _txt(tags.get("aART")),
        "artists_freeform": _txt(tags.get(_ARTISTS_FREEFORM_ATOM)),
    }


def _compute_repair(code: str, cur: dict, directory_artist: Optional[str]) -> Optional[dict]:
    """Neue Atom-Werte oder None (nichts zu tun / nicht eindeutig)."""
    if code == "GENRE_DELIMITER_INCONSISTENT":
        raw = cur["genre"][0] if cur["genre"] else None
        new = tag_repairs.repair_genre_delimiter(raw)
        return {"genre": [new]} if new is not None else None

    if code in ("MULTI_ARTIST_SUSPICIOUS", "MULTI_ARTIST_INCONSISTENT", "MULTI_ARTIST_DUPLICATE"):
        res = tag_repairs.repair_multi_artist(cur["artist"], cur["artists_freeform"])
        if res is None:
            return None
        new_primary, new_freeform = res
        return {"artist": new_primary, "artists_freeform": new_freeform}

    if code in ("META_ALBUM_ARTIST_MISSING", "ALBUM_ARTIST_INCONSISTENT"):
        cur_aa = cur["album_artist"][0] if cur["album_artist"] else None
        new_aa = tag_repairs.repair_album_artist(
            cur_aa, cur["artist"], directory_artist=directory_artist
        )
        return {"album_artist": [new_aa]} if new_aa is not None else None

    return None


def _write_atoms(src: Path, new_atoms: dict) -> Path:
    """Auf einer temporären Sibling-Kopie schreiben, Pfad zurückgeben
    (noch NICHT übernommen)."""
    from mutagen.mp4 import MP4, MP4FreeForm

    tmp = src.with_name(f".{src.stem}.repairtmp_{int(time.time() * 1000)}{src.suffix}")
    shutil.copy2(src, tmp)
    audio = MP4(tmp)
    if "genre" in new_atoms:
        audio["©gen"] = list(new_atoms["genre"])
    if "artist" in new_atoms:
        audio["©ART"] = list(new_atoms["artist"])
    if "artists_freeform" in new_atoms:
        vals = new_atoms["artists_freeform"]
        if vals:
            audio[_ARTISTS_FREEFORM_ATOM] = [MP4FreeForm(v.encode("utf-8")) for v in vals]
        elif _ARTISTS_FREEFORM_ATOM in audio:
            del audio[_ARTISTS_FREEFORM_ATOM]
    if "album_artist" in new_atoms:
        audio["aART"] = list(new_atoms["album_artist"])
    audio.save()
    return tmp


# ─────────────────────────────────────────────────────────────────────────
# Orchestrierung
# ─────────────────────────────────────────────────────────────────────────


def _directory_artist(rel_path: str) -> Optional[str]:
    parts = Path(rel_path).parts
    return parts[0] if len(parts) >= 2 else None


def apply_level1(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """`backup_dir` (Default: `<library_root>/../.library_repair_backups`)
    liegt bewusst AUSSERHALB der Library — die Rollback-Kopien sollen weder
    einen erneuten Scan noch Navidrome stoeren."""
    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []
    # deterministisch: nach Pfad
    todo = sorted(
        (c for c in candidates if c.issue_code in L1_TAG_CODES and c.path),
        key=lambda c: (c.path, c.issue_code),
    )

    for c in todo:
        path = library_root / c.path
        oc = ExecOutcome(file=c.path, issue_code=c.issue_code, action=c.action.value,
                         status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        try:
            cur = _read_atoms(path)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"Tag-Lesen: {e!r}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        new_atoms = _compute_repair(c.issue_code, cur, _directory_artist(c.path))
        if not new_atoms:
            oc.reason = "nichts zu tun / nicht eindeutig"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        oc.before = {k: cur[k] for k in new_atoms}
        oc.after = dict(new_atoms)

        if dry_run:
            oc.status = "DRY_RUN"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        # ── echter Schreibvorgang ────────────────────────────────────────
        sha_before = _sha256(path)
        audio_before = _audio_essence_md5(path)
        backup = backup_dir / f"{c.path}.{int(time.time() * 1000)}.bak"
        tmp = None
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            tmp = _write_atoms(path, new_atoms)
            # Verifikation VOR der Übernahme
            verify = _read_atoms(tmp)
            for k, want in new_atoms.items():
                if verify.get(k) != list(want):
                    raise RuntimeError(f"Verifikation fehlgeschlagen ({k}: {verify.get(k)} != {want})")
            audio_tmp = _audio_essence_md5(tmp)
            if audio_tmp != audio_before or audio_tmp.startswith("ERROR"):
                raise RuntimeError(f"Audio-Essenz verändert ({audio_before} -> {audio_tmp})")
            tmp.replace(path)
            tmp = None
            oc.status = "SUCCESS"
            oc.backup_path = str(backup)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            # Wiederherstellen
            try:
                if backup.exists():
                    backup.replace(path)
            except OSError:
                pass
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        finally:
            if oc.status == "FAILED":
                try:
                    Path(backup).unlink(missing_ok=True)
                except OSError:
                    pass

        je = _je(c, oc, dry_run)
        je.sha256_before = sha_before
        je.sha256_after = _sha256(path)
        je.audio_sha256_before = audio_before
        je.audio_sha256_after = _audio_essence_md5(path) if oc.status == "SUCCESS" else audio_before
        je.backup_path = oc.backup_path
        journal.record(je)
        outcomes.append(oc)

    return outcomes


# ─────────────────────────────────────────────────────────────────────────
# Level 1 — Rename (nur im selben Verzeichnis, Prompt Abschnitt 7/14)
# ─────────────────────────────────────────────────────────────────────────


def _plan_new_name(code: str, path: Path, library_root: Path) -> Optional[str]:
    from services.library_health.discovery import build_file_record
    from services.library_health.tag_reader import read_tags

    rec = build_file_record(path, library_root)
    if code == "FILENAME_SUSPICIOUS":
        return rename_repairs.repair_suspicious_filename(rec.filename_stem, rec.extension)

    tags = read_tags(path)
    return rename_repairs.repair_filename_title_mismatch(
        stem=rec.filename_stem,
        extension=rec.extension,
        title=tags.title,
        year=tags.year,
        track_number=tags.track_number,
        is_singles=rec.is_singles,
        library_section=rec.library_section.value,
    )


def apply_level1_rename(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    *,
    dry_run: bool = True,
) -> list[ExecOutcome]:
    library_root = Path(library_root)
    outcomes: list[ExecOutcome] = []
    todo = sorted(
        (c for c in candidates if c.issue_code in L1_RENAME_CODES and c.path),
        key=lambda c: (c.path, c.issue_code),
    )
    for c in todo:
        path = library_root / c.path
        oc = ExecOutcome(file=c.path, issue_code=c.issue_code, action=c.action.value,
                         status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        try:
            new_name = _plan_new_name(c.issue_code, path, library_root)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"Namensberechnung: {e!r}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        if not new_name or "/" in new_name or "\\" in new_name:
            oc.reason = "kein sicherer neuer Name / nicht eindeutig"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        target = path.with_name(new_name)
        if target == path:
            oc.reason = "Name bereits korrekt"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue
        if target.exists():
            oc.reason = f"Zielname existiert bereits: {new_name}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        rel_target = str(target.relative_to(library_root))
        oc.before = {"path": c.path}
        oc.after = {"path": rel_target}

        if dry_run:
            oc.status = "DRY_RUN"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        sha_before = _sha256(path)
        claim_fd = None
        try:
            # Zielnamen atomar auf OS-Ebene beanspruchen (TOCTOU, auch
            # prozessuebergreifend) — dasselbe Muster wie
            # utils/filenamefixer.py::move_to_library().
            claim_fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(claim_fd)
            claim_fd = None
            os.replace(str(path), str(target))
            # Verifikation
            from mutagen.mp4 import MP4

            MP4(target)  # muss lesbar bleiben
            if _sha256(target) != sha_before:
                raise RuntimeError("Byte-Inhalt nach Rename verändert")
            oc.status = "SUCCESS"
        except FileExistsError:
            oc.reason = f"Zielname wurde parallel belegt: {new_name}"
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            if not path.exists() and target.exists():
                try:
                    os.replace(str(target), str(path))
                except OSError:
                    pass
            else:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

        je = _je(c, oc, dry_run)
        je.sha256_before = sha_before
        je.sha256_after = _sha256(target if oc.status == "SUCCESS" else path)
        journal.record(je)
        outcomes.append(oc)

    return outcomes


# ─────────────────────────────────────────────────────────────────────────
# Cover — externe Suche (CoverProcessor) + only-if-better (Prompt Abschnitt 9)
# ─────────────────────────────────────────────────────────────────────────

COVER_ISSUE_CODES = cover_repairs.HANDLED_ISSUE_CODES


def _image_dims(raw: bytes) -> tuple[Optional[int], Optional[int], Optional[str]]:
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(raw)) as img:
            return img.width, img.height, (img.format or "").upper()
    except Exception:  # noqa: BLE001
        return None, None, None


def _embed_cover(src: Path, raw: bytes, fmt: str) -> Path:
    """covr-Atom auf einer temporaeren Sibling-Kopie setzen."""
    from mutagen.mp4 import MP4, MP4Cover

    image_format = MP4Cover.FORMAT_PNG if fmt == "PNG" else MP4Cover.FORMAT_JPEG
    tmp = src.with_name(f".{src.stem}.repairtmp_{int(time.time() * 1000)}{src.suffix}")
    shutil.copy2(src, tmp)
    audio = MP4(tmp)
    audio["covr"] = [MP4Cover(raw, imageformat=image_format)]
    audio.save()
    return tmp


def apply_cover_repairs(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    cover_fetcher,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """`cover_fetcher(ctx: dict) -> (bytes | None, source | None)` — der
    Aufrufer injiziert den echten CoverProcessor. `ctx` enthaelt artist/
    title/album/mb_recording_id/mb_release_id/mb_artist_id/isrc."""
    from services.library_health.tag_reader import read_artwork, read_tags

    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []
    todo = sorted(
        (c for c in candidates if c.issue_code in COVER_ISSUE_CODES and c.path),
        key=lambda c: (c.path, c.issue_code),
    )
    # Album-Cache: alle Tracks EINES Album-Ordners bekommen dasselbe Cover
    # (verhindert, dass ein per-Track-Repair eine ALBUM_COVER_INCONSISTENT
    # erst erzeugt). Key = (Artist-Ordner, Album-Ordner); Singles nicht gecacht.
    album_cover_cache: dict[tuple, tuple] = {}

    for c in todo:
        path = library_root / c.path
        oc = ExecOutcome(file=c.path, issue_code=c.issue_code, action=c.action.value,
                         status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        try:
            art = read_artwork(path)
            tags = read_tags(path)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"Lesen: {e!r}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        ctx = {
            "artist": tags.artist, "title": tags.title, "album": tags.album,
            "mb_recording_id": tags.mb_recording_id, "mb_release_id": tags.mb_release_id,
            "mb_artist_id": tags.mb_artist_id, "mb_release_group_id": tags.mb_release_group_id,
            "isrc": tags.isrc,
        }
        parts = Path(c.path).parts
        album_key = (parts[0], parts[1]) if len(parts) >= 3 and parts[1].lower() != "singles" else None
        try:
            if album_key is not None and album_key in album_cover_cache:
                new_raw, source = album_cover_cache[album_key]
            else:
                new_raw, source = cover_fetcher(ctx)
                if album_key is not None:
                    album_cover_cache[album_key] = (new_raw, source)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"Cover-Suche: {e!r}"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        cand_w = cand_h = None
        cand_fmt = "JPEG"
        if new_raw:
            cand_w, cand_h, cand_fmt = _image_dims(new_raw)

        action, why = cover_repairs.decide_cover_action(
            c.issue_code,
            current_present=art.present,
            current_state=art.state.value,
            current_w=art.width, current_h=art.height,
            candidate_w=cand_w, candidate_h=cand_h,
        )
        oc.before = {"cover": f"{art.width}x{art.height}" if art.present else "MISSING",
                     "sha256": art.sha256}
        oc.after = {"cover": f"{cand_w}x{cand_h}" if action != "SKIP" else None,
                    "source": source, "decision": action}

        if action == cover_repairs.SKIP:
            oc.reason = why
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        if dry_run:
            oc.status = "DRY_RUN"
            outcomes.append(oc)
            journal.record(_je(c, oc, dry_run))
            continue

        sha_before = _sha256(path)
        audio_before = _audio_essence_md5(path)
        backup = backup_dir / f"{c.path}.{int(time.time() * 1000)}.bak"
        tmp = None
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            tmp = _embed_cover(path, new_raw, cand_fmt or "JPEG")
            verify = read_artwork(tmp)
            if not verify.present or verify.sha256 != hashlib.sha256(new_raw).hexdigest():
                raise RuntimeError("Cover-Verifikation fehlgeschlagen")
            audio_tmp = _audio_essence_md5(tmp)
            if audio_tmp != audio_before or audio_tmp.startswith("ERROR"):
                raise RuntimeError(f"Audio-Essenz veraendert ({audio_before} -> {audio_tmp})")
            tmp.replace(path)
            tmp = None
            oc.status = "SUCCESS"
            oc.backup_path = str(backup)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            try:
                if Path(backup).exists():
                    Path(backup).replace(path)
            except OSError:
                pass
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                Path(backup).unlink(missing_ok=True)
            except OSError:
                pass

        je = _je(c, oc, dry_run)
        je.sha256_before, je.sha256_after = sha_before, _sha256(path)
        je.audio_sha256_before = audio_before
        je.audio_sha256_after = _audio_essence_md5(path) if oc.status == "SUCCESS" else audio_before
        je.backup_path = oc.backup_path
        journal.record(je)
        outcomes.append(oc)

    return outcomes


ALBUM_COVER_CODES = cover_repairs.ALBUM_ISSUE_CODES


def _cover_raw(path: Path) -> tuple[Optional[bytes], str]:
    from services.library_health.tag_reader import _extract_mp4_cover

    try:
        raw, mime = _extract_mp4_cover(path)
    except Exception:  # noqa: BLE001
        return None, "JPEG"
    return raw, ("PNG" if (mime or "").endswith("png") else "JPEG")


def apply_album_cover_unify(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """ALBUM_COVER_INCONSISTENT: alle Tracks eines Albums auf das BESTE
    bereits vorhandene Cover vereinheitlichen (groesste quadratische,
    dekodierbare Bilddatei im Album) — offline, deterministisch, nie
    herunterskaliert. Findet sich kein brauchbares Cover -> SKIP."""
    from services.library_health.tag_reader import read_artwork

    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []

    for c in sorted((c for c in candidates if c.issue_code in ALBUM_COVER_CODES),
                    key=lambda c: (c.artist or "", c.album or "")):
        rels = sorted(set(c.related_files or []))
        if len(rels) < 2:
            continue
        arts: list[dict] = []
        for rel in rels:
            p = library_root / rel
            if safety_check(p, library_root):
                arts.append({"rel": rel, "path": p, "present": False, "decodable": False})
                continue
            a = read_artwork(p)
            arts.append({
                "rel": rel, "path": p,
                "present": a.present, "decodable": a.state.value in ("PRESENT",),
                "w": a.width, "h": a.height, "sha256": a.sha256,
            })

        best_idx = cover_repairs.pick_album_cover(arts)
        if best_idx is None:
            outcomes.append(ExecOutcome(
                file=f"{c.artist}/{c.album}", issue_code=c.issue_code,
                action=c.action.value, status="SKIPPED",
                reason="kein brauchbares (quadratisches, dekodierbares) Cover im Album"))
            journal.record(_je(c, outcomes[-1], dry_run))
            continue

        best = arts[best_idx]
        best_raw, best_fmt = _cover_raw(best["path"])
        if not best_raw:
            outcomes.append(ExecOutcome(
                file=f"{c.artist}/{c.album}", issue_code=c.issue_code,
                action=c.action.value, status="SKIPPED",
                reason="Album-Cover nicht lesbar"))
            journal.record(_je(c, outcomes[-1], dry_run))
            continue

        for tr in arts:
            if tr["rel"] == best["rel"]:
                continue
            oc = ExecOutcome(file=tr["rel"], issue_code=c.issue_code,
                             action=c.action.value, status="SKIPPED",
                             artist=c.artist, album=c.album)
            if not tr.get("decodable") and tr.get("present"):
                oc.reason = "Track-Cover nicht dekodierbar — manuell"
                outcomes.append(oc)
                journal.record(_je_named(tr["rel"], oc, dry_run))
                continue
            action, why = cover_repairs.should_unify_track(
                tr, {"w": best.get("w"), "h": best.get("h"), "sha256": best.get("sha256")})
            oc.before = {"cover": f"{tr.get('w')}x{tr.get('h')}" if tr.get("present") else "MISSING",
                         "sha256": tr.get("sha256")}
            oc.after = {"cover": f"{best.get('w')}x{best.get('h')}", "decision": action,
                        "source": f"album:{best['rel']}"}
            if action == cover_repairs.SKIP:
                oc.reason = why
                outcomes.append(oc)
                journal.record(_je_named(tr["rel"], oc, dry_run))
                continue
            if dry_run:
                oc.status = "DRY_RUN"
                outcomes.append(oc)
                journal.record(_je_named(tr["rel"], oc, dry_run))
                continue
            _do_cover_write(tr["path"], tr["rel"], best_raw, best_fmt, backup_dir, oc, journal, c)
            outcomes.append(oc)

    return outcomes


def _do_cover_write(path, rel, raw, fmt, backup_dir, oc, journal, cand):
    sha_before = _sha256(path)
    audio_before = _audio_essence_md5(path)
    from services.library_health.tag_reader import read_artwork

    backup = Path(backup_dir) / f"{rel}.{int(time.time() * 1000)}.bak"
    tmp = None
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        tmp = _embed_cover(path, raw, fmt)
        v = read_artwork(tmp)
        if not v.present or v.sha256 != hashlib.sha256(raw).hexdigest():
            raise RuntimeError("Cover-Verifikation fehlgeschlagen")
        at = _audio_essence_md5(tmp)
        if at != audio_before or at.startswith("ERROR"):
            raise RuntimeError(f"Audio-Essenz veraendert ({audio_before} -> {at})")
        tmp.replace(path)
        tmp = None
        oc.status = "SUCCESS"
        oc.backup_path = str(backup)
    except Exception as e:  # noqa: BLE001
        oc.status, oc.reason = "FAILED", repr(e)
        try:
            if Path(backup).exists():
                Path(backup).replace(path)
        except OSError:
            pass
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            Path(backup).unlink(missing_ok=True)
        except OSError:
            pass
    je = _je_named(rel, oc, False)
    je.sha256_before, je.sha256_after = sha_before, _sha256(path)
    je.audio_sha256_before = audio_before
    je.audio_sha256_after = _audio_essence_md5(path) if oc.status == "SUCCESS" else audio_before
    je.backup_path = oc.backup_path
    journal.record(je)


EXTERNAL_MB_CODES = external_metadata.HANDLED_ISSUE_CODES


def _write_freeform_atoms(src: Path, atoms: dict[str, list[str]]) -> Path:
    from mutagen.mp4 import MP4, MP4FreeForm

    tmp = src.with_name(f".{src.stem}.repairtmp_{int(time.time() * 1000)}{src.suffix}")
    shutil.copy2(src, tmp)
    audio = MP4(tmp)
    for name, values in atoms.items():
        audio[name] = [MP4FreeForm(str(v).encode("utf-8")) for v in values]
    audio.save()
    return tmp


def apply_external_metadata(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    mb_lookup,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """Fehlende MusicBrainz Recording-/Artist-/Release-/Release-Group-IDs und
    ISRC nachtragen. `mb_lookup(artist, title) -> dict` (leer = kein
    eindeutiger Match). Ergaenzt NUR fehlende Felder, ueberschreibt nie."""
    from services.library_health.tag_reader import read_tags

    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []

    # ein Kandidat pro Datei (die 3 Issue-Codes betreffen oft dieselbe Datei)
    by_path: dict[str, RepairCandidate] = {}
    for c in candidates:
        if c.issue_code in EXTERNAL_MB_CODES and c.path:
            by_path.setdefault(c.path, c)

    for rel, c in sorted(by_path.items()):
        path = library_root / rel
        oc = ExecOutcome(file=rel, issue_code=c.issue_code, action="EXTERNAL_ID_LOOKUP",
                         status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        try:
            tags = read_tags(path)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"Tag-Lesen: {e!r}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        if _blank(tags.artist) or _blank(tags.title):
            oc.reason = "Artist/Titel fehlt — keine externe Suche"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue
        if not external_metadata.title_is_trustworthy(tags.title):
            oc.reason = f"Titel {tags.title!r} zu unsauber fuer eine externe ID-Zuordnung"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        try:
            mb = mb_lookup(tags.artist, tags.title) or {}
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"MusicBrainz-Suche: {e!r}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        current = {
            "recording_id": tags.mb_recording_id, "artist_id": tags.mb_artist_id,
            "release_id": tags.mb_release_id, "release_group_id": tags.mb_release_group_id,
            "isrc": tags.isrc,
        }
        writes = external_metadata.plan_id_writes(current, mb, file_title=tags.title)
        if not writes:
            oc.reason = "kein eindeutiger MusicBrainz-Match / keine neuen IDs"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        oc.before = {"mb_recording_id": tags.mb_recording_id, "mb_release_id": tags.mb_release_id,
                     "isrc": tags.isrc}
        oc.after = {"added": {k.split(":")[-1]: v[0] for k, v in writes.items()},
                    "mb_match": f"{mb.get('artist')} - {mb.get('title')}"}

        if dry_run:
            oc.status = "DRY_RUN"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        sha_before = _sha256(path)
        audio_before = _audio_essence_md5(path)
        backup = backup_dir / f"{rel}.{int(time.time() * 1000)}.bak"
        tmp = None
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            tmp = _write_freeform_atoms(path, writes)
            from mutagen.mp4 import MP4

            v = MP4(tmp).tags or {}
            for name, values in writes.items():
                got = [x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)
                       for x in v.get(name, [])]
                if got != list(values):
                    raise RuntimeError(f"Verifikation {name}: {got} != {values}")
            at = _audio_essence_md5(tmp)
            if at != audio_before or at.startswith("ERROR"):
                raise RuntimeError(f"Audio-Essenz veraendert ({audio_before} -> {at})")
            tmp.replace(path)
            tmp = None
            oc.status = "SUCCESS"
            oc.backup_path = str(backup)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            try:
                if Path(backup).exists():
                    Path(backup).replace(path)
            except OSError:
                pass
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                Path(backup).unlink(missing_ok=True)
            except OSError:
                pass

        je = _je_named(rel, oc, dry_run)
        je.sha256_before, je.sha256_after = sha_before, _sha256(path)
        je.audio_sha256_before = audio_before
        je.audio_sha256_after = _audio_essence_md5(path) if oc.status == "SUCCESS" else audio_before
        je.backup_path = oc.backup_path
        journal.record(je)
        outcomes.append(oc)

    return outcomes


# ─────────────────────────────────────────────────────────────────────────
# Level 2 — METADATA_REPROCESSING (die echte Pipeline, Prompt Abschnitt 6/10)
# ─────────────────────────────────────────────────────────────────────────

# Issue-Codes, die per voller Neuverarbeitung durch die Produktions-Pipeline
# behoben werden — deckungsgleich zu den METADATA_REPROCESSING-Einträgen in
# planner.REGISTRY. Mehrere dieser Codes treffen oft dieselbe Datei; ein
# reprocess()-Lauf pro Datei behebt sie gemeinsam.
L2_CODES = frozenset({
    "META_TITLE_NOT_CLEAN",
    "META_ARTIST_MISSING",
    "META_TITLE_MISSING",
    "META_ALBUM_MISSING",
    "GENRE_INVALID",
    "LYRICS_MISSING",
    "LYRICS_EMPTY",
    "LYRICS_INVALID",
})

# Snapshot-Felder, die als Before/After ins Journal übernommen werden
# (stream_info/audio_essence_md5 sind separat als Integritätsmarker geprüft).
_L2_REPORTED_FIELDS = (
    "filename", "relative_path", "title", "album", "album_artist", "artist",
    "artists_freeform", "year", "genre_tag", "genre_freeform", "mb_ids",
    "lyrics_present", "cover_present", "cover_sha256",
)


def apply_level2(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    reprocess,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """Volle Metadaten-Neuverarbeitung über die ECHTE Produktions-Pipeline
    (`services/metadata/track_reprocessor.process_file`, wie sie auch
    `scripts/reprocess_artist_metadata.py` fährt).

    `reprocess(path, artist_root, dry_run) -> result-dict` wird injiziert
    (der Aufrufer konstruiert `EnhancedMetadataProcessor` + MB-/LastFM-Client
    mit der echten Config und kapselt den `asyncio.run`).

    Sicherheitsmodell wie L1, aber um die Pipeline gelegt: `process_file`
    schreibt IN-PLACE ohne eigenes Backup — deshalb hier VOR dem Aufruf eine
    Per-Datei-Sicherung ausserhalb der Library, danach die verbindliche
    Prüfung, dass die Audio-Essenz (dekodierter Stream, container-unabhängig)
    unverändert ist. Jede Abweichung / jeder Pipeline-Fehler → Rollback.

    Nebeneffekt (bewusst, = echtes Pipeline-Verhalten): im Nicht-Dry-Run
    aktualisiert `process_file` die Auto-Learn-Mappings
    (`mapping/auto_learned_*`) mit den beobachteten Feature-Artists/Genres
    des Tracks — identisch dazu, als wäre der Track frisch heruntergeladen
    worden. Der Aufrufer weist im EXECUTE-Modus darauf hin.
    """
    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []

    by_path: dict[str, RepairCandidate] = {}
    codes_per_path: dict[str, set[str]] = {}
    for c in candidates:
        if c.issue_code in L2_CODES and c.path:
            by_path.setdefault(c.path, c)
            codes_per_path.setdefault(c.path, set()).add(c.issue_code)

    for rel, c in sorted(by_path.items()):
        path = library_root / rel
        codes = ", ".join(sorted(codes_per_path[rel]))
        oc = ExecOutcome(file=rel, issue_code=c.issue_code,
                         action="METADATA_REPROCESS", status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        artist_parts = Path(rel).parts
        if len(artist_parts) < 2:
            oc.reason = "Datei nicht in einer <Artist>/…-Hierarchie"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue
        artist_root = library_root / artist_parts[0]

        # ── DRY-RUN: process_file schreibt nichts, liefert eine Vorhersage ──
        if dry_run:
            try:
                result = reprocess(path, artist_root, True)
            except Exception as e:  # noqa: BLE001
                oc.status, oc.reason = "FAILED", f"Pipeline (dry-run): {e!r}"
                outcomes.append(oc)
                journal.record(_je_named(rel, oc, dry_run))
                continue
            oc.before, oc.after = _l2_before_after(result)
            oc.reason = _l2_unresolved(result) or f"betrifft: {codes}"
            oc.status = "DRY_RUN" if result.get("changes") else "SKIPPED"
            if result.get("status") == "error":
                oc.status, oc.reason = "FAILED", f"Pipeline: {result.get('error')}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        # ── EXECUTE ────────────────────────────────────────────────────────
        sha_before = _sha256(path)
        audio_before = _audio_essence_md5(path)
        backup = backup_dir / f"{rel}.{int(time.time() * 1000)}.bak"
        final_path = path
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)

            result = reprocess(path, artist_root, False)

            ch = result.get("changes") or {}
            rel_change = ch.get("relative_path")
            if rel_change and rel_change.get("after"):
                final_path = library_root / rel_change["after"]

            if result.get("status") == "error":
                raise RuntimeError(f"Pipeline: {result.get('error')}")
            if result.get("audio_essence_changed") or result.get("audio_stream_changed"):
                raise RuntimeError(
                    "Pipeline meldet Audio-Änderung "
                    f"(essence={result.get('audio_essence_changed')}, "
                    f"stream={result.get('audio_stream_changed')})"
                )
            audio_after = _audio_essence_md5(final_path)
            if audio_after != audio_before or audio_after.startswith("ERROR"):
                raise RuntimeError(f"Audio-Essenz verändert ({audio_before} -> {audio_after})")

            oc.before, oc.after = _l2_before_after(result)
            oc.status = "SUCCESS" if result.get("status") == "changed" else "SKIPPED"
            if oc.status == "SKIPPED":
                oc.reason = "Pipeline ließ die Datei unverändert"
            oc.backup_path = str(backup)
            unresolved = _l2_unresolved(result)
            if unresolved:
                oc.reason = (f"{oc.reason}; " if oc.reason else "") + unresolved
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            try:
                if final_path != path and Path(final_path).exists():
                    Path(final_path).unlink()
                if Path(backup).exists():
                    Path(backup).replace(path)
                final_path = path
            except OSError:
                pass
            try:
                Path(backup).unlink(missing_ok=True)
            except OSError:
                pass

        je = _je_named(rel, oc, dry_run)
        je.sha256_before = sha_before
        je.sha256_after = _sha256(final_path)
        je.audio_sha256_before = audio_before
        je.audio_sha256_after = (
            _audio_essence_md5(final_path) if oc.status == "SUCCESS" else audio_before
        )
        je.backup_path = oc.backup_path
        journal.record(je)
        outcomes.append(oc)

    return outcomes


def _l2_before_after(result: dict) -> tuple[dict, dict]:
    ch = result.get("changes") or {}
    before = {k: v.get("before") for k, v in ch.items() if k in _L2_REPORTED_FIELDS}
    after = {k: v.get("after") for k, v in ch.items() if k in _L2_REPORTED_FIELDS}
    return before, after


def _l2_unresolved(result: dict) -> Optional[str]:
    items = result.get("unresolved") or []
    return ("UNRESOLVED: " + " | ".join(items)) if items else None


# ────────────────────────────────────────────────────────────────────────
# Level LOUDNESS — verlustfreier ReplayGain-Tag (kein Re-Encode)
# ────────────────────────────────────────────────────────────────────────

LOUDNESS_ISSUE_CODES = replaygain_repairs.HANDLED_ISSUE_CODES


def apply_replaygain(
    candidates: list[RepairCandidate],
    library_root: Path,
    journal: RepairJournal,
    measure_fn,
    *,
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
) -> list[ExecOutcome]:
    """LOUDNESS_OFF_TARGET beheben, indem ein `replaygain_track_gain`- +
    `replaygain_track_peak`-Freeform-Atom geschrieben wird — das Audio bleibt
    **byte-identisch**. Ein ReplayGain-fähiger Player (Navidrome) bringt die
    Datei damit auf die MusicBot-Ziel-Lautheit (−16 LUFS), ohne verlust-
    behaftetes Re-Encode.

    `measure_fn(path) -> (integrated_lufs | None, true_peak_dbtp | None)` —
    der Aufrufer kapselt EINE `tag_reader.measure_loudness`. Der Gain-Wert
    ergibt sich aus `Ziel − gemessen` (Referenz bewusst −16, nicht die
    RG-2.0-Norm −18: so klingen getaggte Altbestände in Navidrome genauso
    laut wie die frisch heruntergeladenen ungetaggten Dateien).

    Sicherheitsmodell wie L1: `safety_check`, Backup ausserhalb der Library,
    Schreiben auf temp-Sibling + Verifikation (Ziel-Atome gesetzt **und**
    Audio-Essenz-MD5 byte-identisch) + atomarer replace, Rollback bei Fehler,
    Journal, Verification-Scan.
    """
    from mutagen.mp4 import MP4

    library_root = Path(library_root)
    if backup_dir is None:
        backup_dir = library_root.parent / ".library_repair_backups"
    backup_dir = Path(backup_dir)
    outcomes: list[ExecOutcome] = []

    by_path: dict[str, RepairCandidate] = {}
    for c in candidates:
        if c.issue_code in LOUDNESS_ISSUE_CODES and c.path:
            by_path.setdefault(c.path, c)

    for rel, c in sorted(by_path.items()):
        path = library_root / rel
        oc = ExecOutcome(file=rel, issue_code=c.issue_code, action="LOUDNESS_NORMALIZE",
                         status="SKIPPED")

        reason = safety_check(path, library_root)
        if reason:
            oc.reason = f"Safety: {reason}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        try:
            lufs, tp = measure_fn(path)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", f"LUFS-Messung: {e!r}"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        writes = replaygain_repairs.compute_replaygain(lufs, tp)
        oc.before = {"integrated_lufs": round(lufs, 2) if lufs is not None else None}
        if not writes:
            oc.reason = (
                f"bereits auf Ziel ({lufs:.1f} LUFS)" if lufs is not None
                else "keine LUFS-Messung"
            )
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        oc.after = {
            "replaygain_track_gain": writes[replaygain_repairs.GAIN_ATOM][0],
            "replaygain_track_peak": writes[replaygain_repairs.PEAK_ATOM][0],
            "target_lufs": replaygain_repairs.TARGET_LUFS,
        }

        if dry_run:
            oc.status = "DRY_RUN"
            outcomes.append(oc)
            journal.record(_je_named(rel, oc, dry_run))
            continue

        sha_before = _sha256(path)
        audio_before = _audio_essence_md5(path)
        backup = backup_dir / f"{rel}.{int(time.time() * 1000)}.bak"
        tmp = None
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            tmp = _write_freeform_atoms(path, writes)
            v = MP4(tmp).tags or {}
            for name, values in writes.items():
                got = [x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)
                       for x in v.get(name, [])]
                if got != list(values):
                    raise RuntimeError(f"Verifikation {name}: {got} != {values}")
            at = _audio_essence_md5(tmp)
            if at != audio_before or at.startswith("ERROR"):
                raise RuntimeError(f"Audio-Essenz veraendert ({audio_before} -> {at})")
            tmp.replace(path)
            tmp = None
            oc.status = "SUCCESS"
            oc.backup_path = str(backup)
        except Exception as e:  # noqa: BLE001
            oc.status, oc.reason = "FAILED", repr(e)
            try:
                if Path(backup).exists():
                    Path(backup).replace(path)
            except OSError:
                pass
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                Path(backup).unlink(missing_ok=True)
            except OSError:
                pass
            oc.backup_path = None

        je = _je_named(rel, oc, dry_run)
        je.sha256_before, je.sha256_after = sha_before, _sha256(path)
        je.audio_sha256_before = audio_before
        je.audio_sha256_after = _audio_essence_md5(path) if oc.status == "SUCCESS" else audio_before
        je.backup_path = oc.backup_path
        journal.record(je)
        outcomes.append(oc)

    return outcomes



def _je_named(rel: str, oc: ExecOutcome, dry_run: bool) -> JournalEntry:
    return JournalEntry(
        timestamp=RepairJournal.now(), file=rel, issue_code=oc.issue_code,
        action=oc.action, status=oc.status, before=oc.before, after=oc.after,
        error=oc.reason, backup_path=oc.backup_path, dry_run=dry_run,
    )


def _je(c: RepairCandidate, oc: ExecOutcome, dry_run: bool) -> JournalEntry:
    return JournalEntry(
        timestamp=RepairJournal.now(),
        file=oc.file,
        issue_code=oc.issue_code,
        action=oc.action,
        status=oc.status,
        before=oc.before,
        after=oc.after,
        error=oc.reason,
        backup_path=oc.backup_path,
        dry_run=dry_run,
    )
