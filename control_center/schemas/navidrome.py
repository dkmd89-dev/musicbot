# control_center/schemas/navidrome.py
# -*- coding: utf-8 -*-
"""
Response-Schemas für die Navidrome-API des Control Centers.

Format bewusst identisch zu den bestehenden Schemas gehalten
(Pydantic-BaseModel, flache Felder, snake_case). Subsonic-Rohfelder
(camelCase wie songCount, coverArt) werden ausschliesslich im Router
gemappt, nicht hier.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ===== Bestehende Schemas (unverändert) =====

class NavidromeStatusResponse(BaseModel):
    connected: bool
    artist_count: Optional[int] = None


class ScanTriggerResponse(BaseModel):
    success: bool
    returncode: int
    stdout: str
    stderr: str


# ===== Gemeinsame Listen-Bausteine =====

class ArtistItem(BaseModel):
    id: str
    name: str
    album_count: Optional[int] = None


class AlbumItem(BaseModel):
    id: str
    name: str
    artist: Optional[str] = None
    artist_id: Optional[str] = None
    cover_art: Optional[str] = None
    song_count: Optional[int] = None
    year: Optional[int] = None


class SongItem(BaseModel):
    id: str
    title: str
    artist: Optional[str] = None
    artist_id: Optional[str] = None
    album: Optional[str] = None
    album_id: Optional[str] = None
    duration: Optional[int] = None
    track: Optional[int] = None
    year: Optional[int] = None


# ===== Artists =====

class ArtistListResponse(BaseModel):
    items: List[ArtistItem]
    page: int
    page_size: int
    total: int
    has_next: bool


class ArtistDetailResponse(BaseModel):
    id: str
    name: str
    album_count: Optional[int] = None
    albums: List[AlbumItem] = Field(default_factory=list)


# ===== Albums =====

class AlbumListResponse(BaseModel):
    items: List[AlbumItem]
    page: int
    page_size: int
    total: Optional[int] = None
    has_next: bool


class AlbumDetailResponse(BaseModel):
    id: str
    name: str
    artist: Optional[str] = None
    artist_id: Optional[str] = None
    cover_art: Optional[str] = None
    year: Optional[int] = None
    song_count: Optional[int] = None
    duration: Optional[int] = None
    songs: List[SongItem] = Field(default_factory=list)


# ===== Songs =====

class SongDetailResponse(SongItem):
    genre: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    play_count: Optional[int] = None
    cover_art: Optional[str] = None


# ===== Genres =====

class GenreItem(BaseModel):
    name: str
    song_count: Optional[int] = None


class GenreListResponse(BaseModel):
    items: List[GenreItem]


class GenreDetailResponse(BaseModel):
    name: str
    songs: List[SongItem] = Field(default_factory=list)


# ===== Suche =====

class SearchResponse(BaseModel):
    artists: List[ArtistItem] = Field(default_factory=list)
    albums: List[AlbumItem] = Field(default_factory=list)
    songs: List[SongItem] = Field(default_factory=list)


# ===== Playlists =====

class PlaylistItem(BaseModel):
    id: str
    name: str
    song_count: int = 0
    owner: Optional[str] = None
    duration: Optional[int] = None
    public: Optional[bool] = None


class PlaylistListResponse(BaseModel):
    items: List[PlaylistItem]
    page: int
    page_size: int
    total: int
    has_next: bool


class PlaylistDetailResponse(BaseModel):
    id: str
    name: str
    owner: Optional[str] = None
    song_count: int = 0
    duration: Optional[int] = None
    songs: List[SongItem] = Field(default_factory=list)


class PlaylistCreateRequest(BaseModel):
    name: str


class PlaylistRenameRequest(BaseModel):
    name: str


class PlaylistMutationResponse(BaseModel):
    success: bool
    playlist_id: Optional[str] = None
    name: Optional[str] = None


# ===== Favoriten =====

class FavoritesResponse(BaseModel):
    artists: List[ArtistItem] = Field(default_factory=list)
    albums: List[AlbumItem] = Field(default_factory=list)
    songs: List[SongItem] = Field(default_factory=list)


# ===== Entdecken =====

class RandomSongsResponse(BaseModel):
    songs: List[SongItem] = Field(default_factory=list)


class NewestAlbumsResponse(BaseModel):
    items: List[AlbumItem]
    page: int
    page_size: int
    has_next: bool


class TopSongsResponse(BaseModel):
    artist_id: str
    artist_name: str
    songs: List[SongItem] = Field(default_factory=list)
