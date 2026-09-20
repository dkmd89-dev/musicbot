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


class MappingSummaryResponse(BaseModel):
    """Übersicht über die Genre-/Artist-Mapping-Dateien (mapping/*.yaml/
    *.json) — Master-Prompt Abschnitt 7 "Mapping anzeigen". Reines Mapping
    über utils.genre_map.GenreMapper.get_statistics()["mappings"] hinweg
    (bereits produktiv, u. a. von der Reprocessing-CLI genutzt) — keine
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
