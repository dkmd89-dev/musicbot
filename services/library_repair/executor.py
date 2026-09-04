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
from . import rename_repairs, tag_repairs

_ARTISTS_FREEFORM_ATOM = "----:com.apple.iTunes:ARTISTS"
_SUPPORTED = (".m4a", ".mp4", ".m4v")

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

    tmp = src.with_name(f".{src.name}.repairtmp_{int(time.time() * 1000)}")
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
