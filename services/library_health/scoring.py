# services/library_health/scoring.py
# -*- coding: utf-8 -*-
"""
Health-Scoring (Prompt Abschnitt 23 / Phase 1E — PR 3).

Deterministisch, reproduzierbar, dokumentiert, ohne versteckte oder
dynamische Gewichte: dieselbe Library im selben Zustand ergibt denselben
Score.

Modell — bewusst einfach (Prompt Abschnitt 42, Anti-Overengineering):

  Jeder Score startet bei 100 und wird um eine feste Strafe pro Issue
  reduziert, ausschliesslich nach dessen Severity:

      CRITICAL -> -40    (Datei-/Library-Zustand mit funktionaler Bedeutung)
      ERROR    -> -15    (klarer Qualitaetsmangel)
      WARNING  ->  -4    (moeglicherweise problematisch)
      INFO     ->   0    (Beobachtung, KEIN Defekt — Prompt Abschnitt 22/23)

  file_health_score   = clamp(100 - Σ Strafe(Datei-Issues))
  album_health_score  = clamp(Ø file_health_score der Album-Tracks
                              - Σ Strafe(Album-Issues))
  artist_health_score = clamp(Ø file_health_score der Artist-Dateien
                              - Σ Strafe(Artist-Issues))
  library_health_score= clamp(Ø aller file_health_scores
                              - min(15, 0.5 · Σ Strafe(Library-Issues)))

  clamp(x) = auf [0, 100] begrenzt, auf 1 Nachkommastelle gerundet.

Der Library-Issue-Anteil (Duplicate-Gruppen) ist bewusst gedeckelt (max
-15): eine Bibliothek mit vielen erkannten SUSPECTED-Kandidaten (INFO,
Strafe 0) oder einigen EXACT-Dubletten soll dadurch nicht auf 0 fallen —
das sind Aufraeum-Kandidaten, kein Totalschaden.

Status-Baender (nur Darstellung, nicht Teil der Score-Berechnung):
  >= 90 EXCELLENT | >= 75 GOOD | >= 50 FAIR | >= 25 POOR | < 25 CRITICAL
"""

from __future__ import annotations

from collections import defaultdict

from .models import FileHealth, Issue, LibrarySection, Scope, Severity

SEVERITY_PENALTY: dict[Severity, float] = {
    Severity.CRITICAL: 40.0,
    Severity.ERROR: 15.0,
    Severity.WARNING: 4.0,
    Severity.INFO: 0.0,
}

LIBRARY_ISSUE_FACTOR = 0.5
LIBRARY_ISSUE_MAX_DEDUCTION = 15.0

_STATUS_BANDS = ((90, "EXCELLENT"), (75, "GOOD"), (50, "FAIR"), (25, "POOR"), (0, "CRITICAL"))


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _penalty(issues) -> float:
    return sum(SEVERITY_PENALTY[i.severity] for i in issues)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 100.0


def status_for(score: float) -> str:
    for threshold, label in _STATUS_BANDS:
        if score >= threshold:
            return label
    return "CRITICAL"


def file_health_score(fh: FileHealth) -> float:
    return _clamp(100.0 - _penalty(fh.issues))


def build_health_section(
    file_healths: list[FileHealth], group_issues: list[Issue]
) -> dict:
    file_scores: dict[str, float] = {
        fh.record.relative_path: file_health_score(fh) for fh in file_healths
    }

    album_pen: dict[tuple[str, str], float] = defaultdict(float)
    album_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    artist_pen: dict[str, float] = defaultdict(float)
    artist_codes: dict[str, set[str]] = defaultdict(set)
    library_pen = 0.0
    for i in group_issues:
        if i.scope is Scope.ALBUM and i.artist and i.album:
            album_pen[(i.artist, i.album)] += SEVERITY_PENALTY[i.severity]
            album_codes[(i.artist, i.album)].add(i.code)
        elif i.scope is Scope.ARTIST and i.artist:
            artist_pen[i.artist] += SEVERITY_PENALTY[i.severity]
            artist_codes[i.artist].add(i.code)
        elif i.scope is Scope.LIBRARY:
            library_pen += SEVERITY_PENALTY[i.severity]

    album_members: dict[tuple[str, str], list[str]] = defaultdict(list)
    artist_members: dict[str, list[str]] = defaultdict(list)
    artist_album_names: dict[str, set[str]] = defaultdict(set)
    for fh in file_healths:
        r = fh.record
        if r.library_section is not LibrarySection.MUSIC or not r.artist_directory:
            continue
        artist_members[r.artist_directory].append(r.relative_path)
        if r.album_directory:
            album_members[(r.artist_directory, r.album_directory)].append(r.relative_path)
            artist_album_names[r.artist_directory].add(r.album_directory)

    albums = []
    for (artist_dir, album_dir), rels in sorted(album_members.items()):
        base = _mean([file_scores[r] for r in rels])
        albums.append({
            "artist": artist_dir,
            "album": album_dir,
            "file_count": len(rels),
            "health_score": _clamp(base - album_pen.get((artist_dir, album_dir), 0.0)),
            "issue_codes": sorted(album_codes.get((artist_dir, album_dir), set())),
        })

    artists = []
    for artist_dir, rels in sorted(artist_members.items()):
        base = _mean([file_scores[r] for r in rels])
        artists.append({
            "artist": artist_dir,
            "file_count": len(rels),
            "album_count": len(artist_album_names.get(artist_dir, set())),
            "health_score": _clamp(base - artist_pen.get(artist_dir, 0.0)),
            "issue_codes": sorted(artist_codes.get(artist_dir, set())),
        })

    library_base = _mean(list(file_scores.values()))
    library_deduction = min(LIBRARY_ISSUE_MAX_DEDUCTION, LIBRARY_ISSUE_FACTOR * library_pen)
    library_score = _clamp(library_base - library_deduction)

    return {
        "score": library_score,
        "status": status_for(library_score),
        "weights": {
            "severity_penalty": {s.value: p for s, p in SEVERITY_PENALTY.items()},
            "library_issue_factor": LIBRARY_ISSUE_FACTOR,
            "library_issue_max_deduction": LIBRARY_ISSUE_MAX_DEDUCTION,
            "status_bands": {label: threshold for threshold, label in _STATUS_BANDS},
        },
        "file_scores": file_scores,
        "albums": albums,
        "artists": artists,
    }
