# services/library_health/group_analysis.py
# -*- coding: utf-8 -*-
"""
Group-Analyse (Prompt Abschnitt 17-19 / Phase 1C — PR 2).

Reine Funktion: (list[FileHealth], file_sha256) -> list[Issue].
Kein Dateisystem-Zugriff — die einzige Datei-I/O (SHA-256 der Bytes, nur
fuer groessengleiche Kandidaten) macht scanner.py und uebergibt das
Ergebnis als Mapping.

Wiederverwendung der bestehenden POST-DOWNLOAD-Duplicate-Domain
(services/duplicate/classification.py): dieselbe Identitaets-Normalisierung
wie DuplicateDetector, inkl. DUP-03-Schutz (Remix/Live/Version bilden KEINE
gemeinsame Gruppe). Der Scanner ERKENNT Duplicate-Kandidaten und loest sie
NIE auf — resolution.py/execution.py werden hier NICHT importiert.
"""

from __future__ import annotations

from collections import defaultdict

from services.duplicate.classification import (
    build_candidate,
    group_candidates_by_identity,
    has_album_context_risk,
    normalize_artist_for_identity,
)

from .models import AnalysisState, FileHealth, Issue, LibrarySection
from .issues import make_issue


def _blank(v) -> bool:
    return v is None or not str(v).strip()


def _distinct_nonblank(values) -> list[str]:
    seen: dict[str, str] = {}
    for v in values:
        if _blank(v):
            continue
        seen.setdefault(str(v).strip().lower(), str(v).strip())
    return sorted(seen.values())


def analyze_groups(
    file_healths: list[FileHealth],
    *,
    file_sha256: dict[str, str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(_album_consistency(file_healths))
    issues.extend(_artist_consistency(file_healths))
    issues.extend(_duplicate_analysis(file_healths, file_sha256 or {}))
    issues.sort(key=lambda i: i.sort_key())
    return issues


# ─────────────────────────────────────────────────────────────────────────
# Album-Konsistenz (Prompt Abschnitt 18)
# ─────────────────────────────────────────────────────────────────────────


def _album_consistency(file_healths: list[FileHealth]) -> list[Issue]:
    groups: dict[tuple[str, str], list[FileHealth]] = defaultdict(list)
    for fh in file_healths:
        r = fh.record
        if r.library_section is LibrarySection.MUSIC and r.album_directory and r.artist_directory:
            groups[(r.artist_directory, r.album_directory)].append(fh)

    issues: list[Issue] = []
    for (artist_dir, album_dir), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        rel = sorted(m.record.relative_path for m in members)
        ctx = {"artist": artist_dir, "album": album_dir, "related_files": rel}

        # Bewusst ausgeschrieben (jeder Issue-Code als Literal —
        # tests/test_library_health_issues.py verifiziert die Registrierung
        # ueber genau dieses Muster).
        names = _distinct_nonblank(m.album for m in members)
        if len(names) > 1:
            issues.append(make_issue(
                "ALBUM_NAME_INCONSISTENT",
                message=f"Unterschiedliche Album-Tags im selben Ordner: {names}",
                details={"values": names}, **ctx))
        album_artists = _distinct_nonblank(m.album_artist for m in members)
        if len(album_artists) > 1:
            issues.append(make_issue(
                "ALBUM_ARTIST_INCONSISTENT",
                message=f"Unterschiedliche Album-Artist-Tags: {album_artists}",
                details={"values": album_artists}, **ctx))
        years = _distinct_nonblank(m.year for m in members)
        if len(years) > 1:
            issues.append(make_issue(
                "ALBUM_YEAR_INCONSISTENT",
                message=f"Unterschiedliche Jahr-Tags: {years}",
                details={"values": years}, **ctx))
        genres = _distinct_nonblank(m.genre for m in members)
        if len(genres) > 1:
            issues.append(make_issue(
                "ALBUM_GENRE_INCONSISTENT",
                message=f"Unterschiedliche Genre-Tags (kann legitim sein): {genres}",
                details={"values": genres}, **ctx))
        release_ids = _distinct_nonblank(m.mb_release_id for m in members)
        if len(release_ids) > 1:
            issues.append(make_issue(
                "ALBUM_RELEASE_ID_INCONSISTENT",
                message=f"Unterschiedliche MusicBrainz Release IDs: {release_ids}",
                details={"values": release_ids}, **ctx))

        covers = {m.cover_sha256 for m in members if m.cover_sha256}
        if len(covers) > 1:
            issues.append(make_issue(
                "ALBUM_COVER_INCONSISTENT",
                message=f"{len(covers)} unterschiedliche eingebettete Cover im Album",
                details={"cover_hashes": sorted(covers)}, **ctx))

        issues.extend(_track_number_issues(members, ctx))
    return issues


def _track_number_issues(members: list[FileHealth], ctx: dict) -> list[Issue]:
    by_disc: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for m in members:
        if m.track_number is None:
            continue
        by_disc[m.disc_number or 1].append((m.track_number, m.record.relative_path))

    out: list[Issue] = []
    for disc, entries in sorted(by_disc.items()):
        nums = [n for n, _ in entries]
        # Doppelte Tracknummer
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        if dupes:
            out.append(make_issue(
                "ALBUM_DUPLICATE_TRACK_NUMBER",
                message=f"Disc {disc}: Tracknummer(n) {dupes} mehrfach vergeben",
                details={"disc": disc, "duplicate_track_numbers": dupes},
                **ctx))
        # Luecke
        uniq = sorted(set(nums))
        if len(uniq) >= 2:
            expected = set(range(uniq[0], uniq[-1] + 1))
            missing = sorted(expected - set(uniq))
            if missing:
                out.append(make_issue(
                    "ALBUM_TRACK_GAP",
                    message=f"Disc {disc}: fehlende Tracknummer(n) {missing} "
                            f"(vorhanden: {uniq[0]}–{uniq[-1]})",
                    details={"disc": disc, "missing": missing, "present": uniq},
                    **ctx))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Artist-Konsistenz (Prompt Abschnitt 19)
# ─────────────────────────────────────────────────────────────────────────


def _artist_consistency(file_healths: list[FileHealth]) -> list[Issue]:
    by_dir: dict[str, list[FileHealth]] = defaultdict(list)
    for fh in file_healths:
        r = fh.record
        if r.library_section is LibrarySection.MUSIC and r.artist_directory:
            by_dir[r.artist_directory].append(fh)

    issues: list[Issue] = []

    # (a) Verzeichnisname vs. dominanter Artist-Tag
    for artist_dir, members in sorted(by_dir.items()):
        tag_artists = _distinct_nonblank(m.artist for m in members)
        if not tag_artists:
            continue
        # dominanter Tag-Artist (haeufigster)
        counts: dict[str, int] = defaultdict(int)
        for m in members:
            if not _blank(m.artist):
                counts[m.artist.strip()] += 1
        dominant = max(counts, key=counts.get)
        if normalize_artist_for_identity(artist_dir).lower() != \
                normalize_artist_for_identity(dominant).lower():
            issues.append(make_issue(
                "ARTIST_DIR_TAG_MISMATCH", artist=artist_dir,
                message=f"Verzeichnis {artist_dir!r} vs. dominanter Artist-Tag "
                        f"{dominant!r}",
                details={"directory": artist_dir, "dominant_tag_artist": dominant,
                         "all_tag_artists": tag_artists},
                related_files=sorted(m.record.relative_path for m in members)[:20],
            ))

    # (b) mehrere Verzeichnisse -> selber normalisierter Name
    norm_to_dirs: dict[str, list[str]] = defaultdict(list)
    for artist_dir in by_dir:
        norm_to_dirs[normalize_artist_for_identity(artist_dir).lower()].append(artist_dir)
    for norm, dirs in sorted(norm_to_dirs.items()):
        if len(dirs) > 1:
            issues.append(make_issue(
                "ARTIST_NAME_VARIANTS",
                message=f"Wahrscheinlich derselbe Artist in mehreren Ordnern: {sorted(dirs)}",
                details={"normalized": norm, "directories": sorted(dirs)},
            ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# Duplicate-Analyse (Prompt Abschnitt 17)
# ─────────────────────────────────────────────────────────────────────────


def _fields_from(fh: FileHealth) -> dict:
    return {
        "artist": fh.artist, "title": fh.title, "album": fh.album,
        "album_artist": fh.album_artist, "year": fh.year, "genre": fh.genre,
        "track_number": fh.track_number,
        "mb_recording_id": fh.mb_recording_id, "mb_artist_id": None,
        "mb_release_id": fh.mb_release_id, "isrc": fh.isrc,
        "lyrics_present": fh.states.get("lyrics") == AnalysisState.PRESENT,
        "cover_present": fh.cover_sha256 is not None,
    }


def _duplicate_analysis(
    file_healths: list[FileHealth], file_sha256: dict[str, str]
) -> list[Issue]:
    issues: list[Issue] = []

    # (1) EXACT — byte-identisch
    exact_sets: list[frozenset[str]] = []
    by_hash: dict[str, list[str]] = defaultdict(list)
    for rel, digest in file_sha256.items():
        by_hash[digest].append(rel)
    for digest, rels in sorted(by_hash.items()):
        if len(rels) > 1:
            group = frozenset(rels)
            exact_sets.append(group)
            issues.append(make_issue(
                "DUPLICATE_EXACT",
                message=f"{len(rels)} byte-identische Dateien (SHA-256 {digest[:12]}…)",
                details={"sha256": digest}, related_files=sorted(rels),
            ))

    # (2) RECORDING — gleiche MB Recording ID bzw. ISRC
    recording_sets: list[frozenset[str]] = []
    for key_kind, attr in (("MusicBrainz Recording ID", "mb_recording_id"), ("ISRC", "isrc")):
        by_id: dict[str, list[str]] = defaultdict(list)
        for fh in file_healths:
            val = getattr(fh, attr)
            if not _blank(val):
                by_id[val.strip()].append(fh.record.relative_path)
        for val, rels in sorted(by_id.items()):
            if len(rels) > 1:
                group = frozenset(rels)
                if any(group <= es for es in exact_sets):
                    continue  # schon als EXACT gemeldet
                if any(group == rs for rs in recording_sets):
                    continue
                recording_sets.append(group)
                issues.append(make_issue(
                    "DUPLICATE_RECORDING",
                    message=f"{len(rels)} Dateien mit identischer {key_kind}",
                    details={key_kind: val}, related_files=sorted(rels),
                ))

    # (3) SUSPECTED — identischer normalisierter Artist+Titel (DUP-03: Remix/
    #     Live/Version bleiben getrennt). Was bereits als EXACT/RECORDING
    #     gemeldet ist, wird hier nicht doppelt aufgefuehrt.
    candidates = []
    cand_to_rel: dict[int, str] = {}
    for fh in file_healths:
        c = build_candidate(
            path=fh.record.absolute_path, artist=fh.artist, title=fh.title,
            fields=_fields_from(fh), bitrate=fh.bitrate,
            duration_seconds=fh.duration_seconds, cover_sha256=fh.cover_sha256,
        )
        candidates.append(c)
        cand_to_rel[id(c)] = fh.record.relative_path

    for key, group in sorted(group_candidates_by_identity(candidates).items()):
        if len(group) < 2:
            continue
        rels = frozenset(cand_to_rel[id(c)] for c in group)
        if any(rels <= es for es in exact_sets) or any(rels <= rs for rs in recording_sets):
            continue
        risk = any(has_album_context_risk(c.album) for c in group)
        issues.append(make_issue(
            "DUPLICATE_SUSPECTED",
            artist=key[0], title=key[1],
            message=f"{len(group)} Dateien mit identischem normalisiertem "
                    f"Artist+Titel {key[0]!r} / {key[1]!r}"
                    + (" (Album-Kontext deutet auf Remix/Live/Version hin)" if risk else ""),
            details={"normalized_artist": key[0], "normalized_title": key[1],
                     "album_context_risk": risk},
            related_files=sorted(rels),
            confidence="album_context_risk" if risk else None,
        ))
    return issues
