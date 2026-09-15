# control_center/schemas/downloads.py
# -*- coding: utf-8 -*-
"""
Response-Schema für GET /api/v1/downloads/history.

Dünnes Mapping über services/downloader/download_history.py::
DownloadHistoryEntry hinweg (kein 1:1-Durchreichen der Dataclass, wie
schemas/health.py/findings.py) — "chat_id" wird pro Eintrag ergänzt
(DownloadHistoryStore.get_all_recent() liefert (chat_id, Entry)-Paare).
"""

from __future__ import annotations

from pydantic import BaseModel

from services.downloader.download_history import DownloadHistoryEntry


class DownloadHistoryEntrySchema(BaseModel):
    chat_id: int
    url: str
    title: str
    artist: str
    status: str
    timestamp: str
    genre_ok: bool | None
    lyrics_ok: bool | None
    cover_ok: bool | None
    mb_ok: bool | None
    loudness_ok: bool | None


class DownloadHistoryResponse(BaseModel):
    entries: list[DownloadHistoryEntrySchema]


def _entry_to_schema(chat_id: int, entry: DownloadHistoryEntry) -> DownloadHistoryEntrySchema:
    return DownloadHistoryEntrySchema(
        chat_id=chat_id,
        url=entry.url,
        title=entry.title,
        artist=entry.artist,
        status=entry.status,
        timestamp=entry.timestamp,
        genre_ok=entry.genre_ok,
        lyrics_ok=entry.lyrics_ok,
        cover_ok=entry.cover_ok,
        mb_ok=entry.mb_ok,
        loudness_ok=entry.loudness_ok,
    )


def history_to_response(entries: list[tuple[int, DownloadHistoryEntry]]) -> DownloadHistoryResponse:
    """Reines Mapping, keine Fachlogik — identisches Prinzip wie
    schemas/health.py::report_to_health_response()."""
    return DownloadHistoryResponse(
        entries=[_entry_to_schema(chat_id, entry) for chat_id, entry in entries]
    )
