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
