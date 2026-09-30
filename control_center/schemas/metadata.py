# control_center/schemas/metadata.py
# -*- coding: utf-8 -*-
"""
Response-Schemas für GET /api/v1/library/tracks, /artists, /albums.

Dünnes Mapping über den bereits vorhandenen Library-Health-Report hinweg
(services/library_health/report.py::build_report_dict(), identischer
Aufrufpfad wie routers/health.py/repair.py über
control_center/_library_scan.py::run_library_scan() — keine neue
Scan-Logik). `report["files"]` (FileHealth.to_dict()), `report["artists"]`/
`report["albums"]` (services/library_health/scoring.py::build_health_section())
liefern bereits alle benötigten Felder.

Bewusst NICHT durchgereicht: `states` (interner Analyse-Zustand pro
Dimension) und `path_classification` (interne Duplicate-Detection-
Klassifikation) — beides Implementierungsdetail ohne Nutzen für eine
Track-/Artist-/Album-Browser-Ansicht (Master-Prompt Regel 9, identisches
Prinzip wie das Weglassen von `library_root` in schemas/health.py).

Pagination von Anfang an (`limit`/`offset`/`total`) — Library-Größen im
dreistelligen bis vierstelligen Bereich haben sich bereits zweimal
(1114 Repair-Kandidaten, 1173 akzeptierte Findings) als real erwiesen,
hier von vornherein vermieden statt erst nach einem Live-Smoke-Test
nachgezogen.
"""

from __future__ import annotations

from pathlib import Path
from services.library_health.tag_reader import read_tags

from typing import Optional

from pydantic import BaseModel


class TrackSchema(BaseModel):
    relative_path: str
    filename: str
    extension: str
    file_size: int
    library_section: str
    artist_directory: Optional[str]
    album_directory: Optional[str]
    artist: Optional[str]
    album_artist: Optional[str]
    title: Optional[str]
    album: Optional[str]
    year: Optional[str]
    genre: Optional[str]
    track_number: Optional[int]
    disc_number: Optional[int]
    mb_recording_id: Optional[str]
    mb_release_id: Optional[str]
    isrc: Optional[str]
    integrated_lufs: Optional[float]
    issue_codes: list[str]
    # Datei-Health aus dem Report (services/library_health/scoring.py::
    # file_health_score); None bei Reports ohne den Wert.
    health_score: Optional[float] = None


class TracksResponse(BaseModel):
    total: int
    limit: int
    offset: int
    tracks: list[TrackSchema]


def _track_to_schema(entry: dict) -> TrackSchema:
    return TrackSchema(
        relative_path=entry["relative_path"],
        filename=entry["filename"],
        extension=entry["extension"],
        file_size=entry["file_size"],
        library_section=entry["library_section"],
        artist_directory=entry.get("artist_directory"),
        album_directory=entry.get("album_directory"),
        artist=entry.get("artist"),
        album_artist=entry.get("album_artist"),
        title=entry.get("title"),
        album=entry.get("album"),
        year=entry.get("year"),
        genre=entry.get("genre"),
        track_number=entry.get("track_number"),
        disc_number=entry.get("disc_number"),
        mb_recording_id=entry.get("mb_recording_id"),
        mb_release_id=entry.get("mb_release_id"),
        isrc=entry.get("isrc"),
        integrated_lufs=entry.get("integrated_lufs"),
        issue_codes=entry.get("issue_codes", []),
        health_score=entry.get("file_health_score"),
    )


def tracks_to_response(files: list[dict], *, limit: int, offset: int) -> TracksResponse:
    """Reines Mapping + Pagination, keine Scan-/Sortierlogik — die
    Reihenfolge kommt bereits deterministisch sortiert aus
    build_report_dict() (nach relative_path)."""
    total = len(files)
    page = files[offset:offset + limit]
    return TracksResponse(
        total=total, limit=limit, offset=offset,
        tracks=[_track_to_schema(f) for f in page],
    )


class ArtistSummarySchema(BaseModel):
    artist: str
    file_count: int
    album_count: int
    health_score: float
    issue_codes: list[str]


class ArtistsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    artists: list[ArtistSummarySchema]


def _artist_to_schema(entry: dict) -> ArtistSummarySchema:
    return ArtistSummarySchema(
        artist=entry["artist"],
        file_count=entry["file_count"],
        album_count=entry["album_count"],
        health_score=entry["health_score"],
        issue_codes=entry["issue_codes"],
    )


def artists_to_response(artists: list[dict], *, limit: int, offset: int) -> ArtistsResponse:
    total = len(artists)
    page = artists[offset:offset + limit]
    return ArtistsResponse(
        total=total, limit=limit, offset=offset,
        artists=[_artist_to_schema(a) for a in page],
    )


class AlbumSummarySchema(BaseModel):
    artist: str
    album: str
    file_count: int
    health_score: float
    issue_codes: list[str]


class AlbumsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    albums: list[AlbumSummarySchema]


def _album_to_schema(entry: dict) -> AlbumSummarySchema:
    return AlbumSummarySchema(
        artist=entry["artist"],
        album=entry["album"],
        file_count=entry["file_count"],
        health_score=entry["health_score"],
        issue_codes=entry["issue_codes"],
    )


def albums_to_response(albums: list[dict], *, limit: int, offset: int) -> AlbumsResponse:
    total = len(albums)
    page = albums[offset:offset + limit]
    return AlbumsResponse(
        total=total, limit=limit, offset=offset,
        albums=[_album_to_schema(a) for a in page],
    )


# ─────────────────────────────────────────────────────────────────────────
# GET /api/v1/library/artists-overview(/{artist}) — Library Artist-Centric
# UX (CC-AC-1). Liest denselben Report wie oben, aber aus dem PERSISTENTEN
# Report (control_center/_library_scan.py::load_cached_report(), Auftrag
# §7a) statt aus einem frischen Scan — kein neues Datenmodell, dieselben
# ArtistSummarySchema/AlbumSummarySchema/TrackSchema wie oben, nur ein
# zusaetzlicher `generated_at`/`stale`-Rahmen, damit das UI den
# Report-Stand anzeigen kann (Auftrag §7a Punkt 1: "Report lesen UND im
# UI sichtbar kennzeichnen, wenn aelter").
# ─────────────────────────────────────────────────────────────────────────


class ArtistsOverviewResponse(BaseModel):
    total: int
    artists: list[ArtistSummarySchema]
    generated_at: Optional[str]
    stale: bool
    # Nur gesetzt, wenn die Library seit dem Report gewachsen/geaendert wurde.
    stale_reason: Optional[str] = None


class ReportRefreshResponse(BaseModel):
    refreshed: bool
    generated_at: Optional[str]
    total_files: Optional[int]


def artists_overview_to_response(
    report: dict, *, stale: bool, stale_reason: Optional[str] = None,
) -> ArtistsOverviewResponse:
    artists = report.get("artists", [])
    return ArtistsOverviewResponse(
        total=len(artists),
        artists=[_artist_to_schema(a) for a in artists],
        generated_at=(report.get("scan") or {}).get("completed_at"),
        stale=stale,
        stale_reason=stale_reason,
    )


class ArtistDetailResponse(BaseModel):
    artist: str
    file_count: int
    album_count: int
    health_score: float
    issue_codes: list[str]
    albums: list[AlbumSummarySchema]
    tracks: list[TrackSchema]
    generated_at: Optional[str]
    stale: bool


def _refresh_editable_fields_from_tags(entry: dict, library_root: Path) -> dict:
    """Liest die editierbaren Track-Felder live aus den Datei-Tags.

    Zweck (Bugfix 2026-09-27): Nach einem erfolgreichen Metadaten-Edit
    (Title/Artist/Album/Albumartist/Genre/Jahr/Track-Nr/Disc-Nr) zeigte
    der Artist-Detail-Endpunkt weiterhin die alten Werte, weil er
    ausschliesslich aus dem persistenten Report las, und der Report
    nach einem Edit nicht invalidiert wird. Der Live-Read ueberspringt
    diesen Cache-Staleness fuer die editierbaren Felder; aggregierte
    Felder (file_size, issue_codes, mb_recording_id, isrc,
    integrated_lufs) bleiben weiterhin aus dem Report.

    Fallback: bei jedem Lesefehler (Datei fehlt, korrupt, kein
    mutagen-Support) wird der unveraenderte `entry` zurueckgegeben -
    kein 500er durch eine einzelne kaputte Datei.
    """
    rel_path = entry.get("relative_path")
    if not rel_path:
        return entry
    full_path = Path(library_root) / rel_path
    try:
        tag_data = read_tags(full_path)
    except Exception:
        return entry

    if getattr(tag_data, "error", None):
        return entry

    enriched = dict(entry)

    if tag_data.title:
        enriched["title"] = tag_data.title

    # Multi-Artist: TagData hat zwei Felder (artists_primary_tag als Liste
    # + artist als einzelner String). Prioritaet: join der Liste, damit
    # "Apache 207; Nina Chuba" nicht auf den ersten Wert reduziert wird.
    if tag_data.artists_primary_tag:
        enriched["artist"] = ", ".join(tag_data.artists_primary_tag)
    elif tag_data.artist:
        enriched["artist"] = tag_data.artist

    if tag_data.album:
        enriched["album"] = tag_data.album
    if tag_data.album_artist:
        enriched["album_artist"] = tag_data.album_artist
    if tag_data.genre:
        enriched["genre"] = tag_data.genre
    if tag_data.year:
        enriched["year"] = tag_data.year
    if tag_data.track_number is not None:
        enriched["track_number"] = tag_data.track_number
    if tag_data.disc_number is not None:
        enriched["disc_number"] = tag_data.disc_number

    return enriched


def artist_detail_to_response(
    report: dict, *, artist: str, stale: bool,
    library_root: Optional[Path] = None,
) -> Optional[ArtistDetailResponse]:
    """Liefert None, wenn `artist` im Report nicht (mehr) vorkommt -
    Aufrufer meldet dafuer HTTPException(404, code="ARTIST_NOT_FOUND").
    Album-/Track-Zugehoerigkeit ist verzeichnisbasiert (`entry["artist"]`
    fuer Alben, `file["artist_directory"]` fuer Tracks - identische
    Konvention wie services/library_repair/library_artists.py/
    maintenance_service.py::artist_targets(), "Artist = stabiler Kontext",
    Auftrag §10), NICHT der rohe ©ART-Tag-Wert, der abweichen kann."""
    summary = next((a for a in report.get("artists", []) if a["artist"] == artist), None)
    if summary is None:
        return None
    albums = [a for a in report.get("albums", []) if a["artist"] == artist]
    tracks = [f for f in report.get("files", []) if f.get("artist_directory") == artist]
    if library_root is not None:
        tracks = [_refresh_editable_fields_from_tags(f, library_root) for f in tracks]
    return ArtistDetailResponse(
        artist=summary["artist"],
        file_count=summary["file_count"],
        album_count=summary["album_count"],
        health_score=summary["health_score"],
        issue_codes=summary["issue_codes"],
        albums=[_album_to_schema(a) for a in albums],
        tracks=[_track_to_schema(f) for f in tracks],
        generated_at=(report.get("scan") or {}).get("completed_at"),
        stale=stale,
    )


class MappingSummaryResponse(BaseModel):
    """Übersicht über die Genre-/Artist-Mapping-Dateien (mapping/*.yaml/
    *.json) — Master-Prompt Abschnitt 7 "Mapping anzeigen". Reines Mapping
    über utils.genre_map.GenreMapper.get_statistics()["mappings"] hinweg
    (bereits produktiv) — keine
    eigene YAML-/JSON-Parsing-Logik. Nur die reinen Mapping-Zählungen,
    NICHT die Laufzeit-Cache-/Query-Statistiken (queries/cache_hits/
    fuzzy_matches/rule_matches/cache_hit_rate) — die sind für eine frische
    Control-Center-Anfrage nicht aussagekräftig (Prozess-Lebenszeit-
    Artefakt, kein Mapping-Inhalt)."""

    artists: int
    channels: int
    hierarchy: int
    rules: int
    aliases: int
    overrides: int
    unique_primary_genres: int


def mapping_statistics_to_response(stats: dict) -> MappingSummaryResponse:
    m = stats["mappings"]
    return MappingSummaryResponse(
        artists=m["artists"],
        channels=m["channels"],
        hierarchy=m["hierarchy"],
        rules=m["rules"],
        aliases=m["aliases"],
        overrides=m["overrides"],
        unique_primary_genres=stats["unique_primary_genres"],
    )
