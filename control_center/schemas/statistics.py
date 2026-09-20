# control_center/schemas/statistics.py
# -*- coding: utf-8 -*-
"""
Response-Schema für GET /api/v1/statistics/me.

Dünnes Mapping über services/statistik/statistics_calculator.py::
StatisticsCalculator.generate_stats() hinweg — reduziert bewusst auf
total_plays/top_artists/top_songs für die erste Dashboard-Ansicht (die
detaillierteren Varianten top_songs_detailed/top_artists_split dienen
anderen, hier nicht benötigten Darstellungszwecken, siehe dortiger
Docstring). `period_start`/`period_end` sind im Quell-Dict echte
datetime-Objekte — hier explizit auf ISO-Strings gemappt statt sich auf
Pydantics automatische datetime-Serialisierung zu verlassen (konsistent
zum expliziten Mapping-Stil in schemas/health.py).

`has_data=False` bildet generate_stats() == None ab (Quell-Funktion:
"kein Verlauf für diesen Navidrome-Nutzer existiert überhaupt" — ein
legitimer Empty-State, kein Fehler, siehe Master-Prompt Regel 45).

GenreStatsResponse/MusicDnaResponse (Nachtrag) mappen analog über
generate_genre_stats()/generate_music_dna() — beide All-Time (kein
Kalenderzeitraum, anders als generate_stats()), daher kein `period`-Feld.
`has_data=False` bildet dort ebenfalls "keinerlei Verlaufsdaten" ab; ein
bereits vorhandener Verlauf ohne (auswertbare) Genre-Angaben liefert
stattdessen `has_data=True` mit leeren Listen (identische Quell-Semantik,
siehe StatisticsCalculator.generate_genre_stats()-Docstring).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TopEntry(BaseModel):
    label: str
    count: int


class StatisticsResponse(BaseModel):
    has_data: bool
    navidrome_username: str
    period: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    total_plays: Optional[int] = None
    top_artists: list[TopEntry] = []
    top_songs: list[TopEntry] = []


def stats_to_response(navidrome_username: str, stats: Optional[dict]) -> StatisticsResponse:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    schemas/health.py::report_to_health_response()."""
    if stats is None:
        return StatisticsResponse(has_data=False, navidrome_username=navidrome_username)

    period_start = stats.get("period_start")
    period_end = stats.get("period_end")
    return StatisticsResponse(
        has_data=True,
        navidrome_username=navidrome_username,
        period=stats.get("period"),
        period_start=period_start.isoformat() if period_start else None,
        period_end=period_end.isoformat() if period_end else None,
        total_plays=stats.get("total_plays"),
        top_artists=[
            TopEntry(label=label, count=count)
            for label, count in stats.get("top_artists", [])
        ],
        top_songs=[
            TopEntry(label=label, count=count)
            for label, count in stats.get("top_songs", [])
        ],
    )


class GenreStatsResponse(BaseModel):
    has_data: bool
    navidrome_username: str
    total_plays_with_genre: Optional[int] = None
    top_genres: list[TopEntry] = []


def genre_stats_to_response(navidrome_username: str, stats: Optional[dict]) -> GenreStatsResponse:
    """Reines Mapping über StatistikService.generate_genre_stats() hinweg."""
    if stats is None:
        return GenreStatsResponse(has_data=False, navidrome_username=navidrome_username)

    return GenreStatsResponse(
        has_data=True,
        navidrome_username=navidrome_username,
        total_plays_with_genre=stats.get("total_plays_with_genre"),
        top_genres=[
            TopEntry(label=genre, count=count)
            for genre, count in stats.get("top_genres", [])
        ],
    )


class PctEntry(BaseModel):
    label: str
    pct: float


class TimeOfDayPct(BaseModel):
    morgens: float
    nachmittags: float
    abends: float
    nachts: float


class MusicDnaResponse(BaseModel):
    has_data: bool
    navidrome_username: str
    total_plays: Optional[int] = None
    unique_songs: Optional[int] = None
    top_genres_pct: list[PctEntry] = []
    top_artists_pct: list[PctEntry] = []
    time_of_day_pct: Optional[TimeOfDayPct] = None
    repeat_rate_pct: Optional[float] = None


def music_dna_to_response(navidrome_username: str, stats: Optional[dict]) -> MusicDnaResponse:
    """Reines Mapping über StatistikService.generate_music_dna() hinweg."""
    if stats is None:
        return MusicDnaResponse(has_data=False, navidrome_username=navidrome_username)

    time_of_day = stats.get("time_of_day_pct") or {}
    return MusicDnaResponse(
        has_data=True,
        navidrome_username=navidrome_username,
        total_plays=stats.get("total_plays"),
        unique_songs=stats.get("unique_songs"),
        top_genres_pct=[
            PctEntry(label=genre, pct=pct)
            for genre, pct in stats.get("top_genres_pct", [])
        ],
        top_artists_pct=[
            PctEntry(label=artist, pct=pct)
            for artist, pct in stats.get("top_artists_pct", [])
        ],
        time_of_day_pct=TimeOfDayPct(
            morgens=time_of_day.get("morgens", 0.0),
            nachmittags=time_of_day.get("nachmittags", 0.0),
            abends=time_of_day.get("abends", 0.0),
            nachts=time_of_day.get("nachts", 0.0),
        ),
        repeat_rate_pct=stats.get("repeat_rate_pct"),
    )
