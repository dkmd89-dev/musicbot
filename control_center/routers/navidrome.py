# control_center/routers/navidrome.py
# -*- coding: utf-8 -*-
"""
Navidrome-Router des Control Centers.

Stellt die vollständige Navidrome-Funktionalität des Telegram-Bots
(handlers/navidrome_menu_handler.py) als REST-API bereit.

  Status / Scan
    GET    /api/v1/navidrome/status
    POST   /api/v1/navidrome/scan                     (ADMIN)

  Browse
    GET    /api/v1/navidrome/artists                  ?page&page_size
    GET    /api/v1/navidrome/artists/{artist_id}
    GET    /api/v1/navidrome/artists/{artist_id}/top  ?count
    GET    /api/v1/navidrome/albums                   ?page&page_size&artist_id
    GET    /api/v1/navidrome/albums/{album_id}
    GET    /api/v1/navidrome/genres
    GET    /api/v1/navidrome/genres/{genre_name}      ?size
    GET    /api/v1/navidrome/songs/{song_id}

  Suche & Entdecken
    GET    /api/v1/navidrome/search                   ?q&type
    GET    /api/v1/navidrome/random                   ?size
    GET    /api/v1/navidrome/newest                   ?page&page_size
    GET    /api/v1/navidrome/favorites

  Playlists (CRUD)
    GET    /api/v1/navidrome/playlists                ?page&page_size
    GET    /api/v1/navidrome/playlists/{playlist_id}
    POST   /api/v1/navidrome/playlists                (USER)  {name}
    PUT    /api/v1/navidrome/playlists/{playlist_id}  (USER)  {name}
    DELETE /api/v1/navidrome/playlists/{playlist_id}  (USER)

Reine Orchestrierung: ruft ausschliesslich
services/clients/navidrome_api.py::NavidromeAPI auf — keine eigene
Fachlogik.

Hinweis: NavidromeAPI.make_request() ist SYNCHRON (nutzt intern
requests.get()); die höherstufigen Methoden check_connection(),
get_artists(), search(), get_now_playing() sind dagegen async und
wrappen intern bereits asyncio.to_thread. Für direkte
make_request()-Aufrufe nutzen wir daher den lokalen Helper _req(), der
das Wrapping übernimmt — identisches Muster zu
handlers/navidrome_menu_handler.py.

Schreibende Endpunkte (POST/PUT/DELETE) sind zusätzlich mit
verify_same_origin (CSRF) geschützt; der Scan bleibt ADMIN-only,
Playlist-CRUD genügt AccessLevel.USER (identisch zur Telegram-Seite).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from handlers.menu.models import AccessLevel
from logger import get_module_logger
from services.clients.navidrome_api import NavidromeAPI
from utils.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError

from ..dependencies import get_current_user_id, require_min_access_level, verify_same_origin
from ..schemas.errors import ErrorDetail
from ..schemas.navidrome import (
    AlbumDetailResponse,
    AlbumItem,
    AlbumListResponse,
    ArtistDetailResponse,
    ArtistItem,
    ArtistListResponse,
    FavoritesResponse,
    GenreDetailResponse,
    GenreItem,
    GenreListResponse,
    NavidromeStatusResponse,
    NewestAlbumsResponse,
    PlaylistCreateRequest,
    PlaylistDetailResponse,
    PlaylistItem,
    PlaylistListResponse,
    PlaylistMutationResponse,
    PlaylistRenameRequest,
    RandomSongsResponse,
    ScanTriggerResponse,
    SearchResponse,
    SongDetailResponse,
    SongItem,
    TopSongsResponse,
)

router = APIRouter(
    prefix="/api/v1/navidrome",
    tags=["navidrome"],
    dependencies=[Depends(require_min_access_level(AccessLevel.USER))],
)
_logger = get_module_logger("control_center.navidrome")


# ===== Helper =====

async def _req(
    api: NavidromeAPI,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Async-Wrapper für die synchrone NavidromeAPI.make_request().

    Identisches Muster zu handlers/navidrome_menu_handler.py:
        await asyncio.to_thread(api.make_request, endpoint, params or {})
    """
    return await asyncio.to_thread(api.make_request, endpoint, params or {})


def _as_list(value: Any) -> List[Any]:
    """Subsonic liefert bei nur einem Eintrag ein Objekt statt einer Liste."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _subsonic(payload: Dict[str, Any]) -> Dict[str, Any]:
    return payload.get("subsonic-response", {}) or {}


# ===== Mapper Subsonic -> Control-Center-Schemas =====

def _map_artist(raw: Dict[str, Any]) -> ArtistItem:
    return ArtistItem(
        id=str(raw.get("id", "")),
        name=raw.get("name") or raw.get("title") or "",
        album_count=raw.get("albumCount"),
    )


def _map_album(raw: Dict[str, Any]) -> AlbumItem:
    return AlbumItem(
        id=str(raw.get("id", "")),
        name=raw.get("name") or raw.get("title") or "",
        artist=raw.get("artist"),
        artist_id=raw.get("artistId"),
        cover_art=raw.get("coverArt"),
        song_count=raw.get("songCount"),
        year=raw.get("year"),
    )


def _map_song(raw: Dict[str, Any]) -> SongItem:
    return SongItem(
        id=str(raw.get("id", "")),
        title=raw.get("title") or raw.get("name") or "",
        artist=raw.get("artist"),
        artist_id=raw.get("artistId"),
        album=raw.get("album"),
        album_id=raw.get("albumId"),
        duration=raw.get("duration"),
        track=raw.get("track"),
        year=raw.get("year"),
    )


def _paginate(items: List[Any], page: int, page_size: int) -> List[Any]:
    start = page * page_size
    return items[start : start + page_size]


# ===== Status =====

@router.get("/status", response_model=NavidromeStatusResponse)
async def get_navidrome_status() -> NavidromeStatusResponse:
    api = NavidromeAPI()
    connected = await api.check_connection()

    artist_count = None
    if connected:
        try:
            artists = await api.get_artists()
            artist_count = len(artists)
        except Exception as e:  # noqa: BLE001
            _logger.error(f"Navidrome erreichbar, aber get_artists() fehlgeschlagen: {e!r}")

    return NavidromeStatusResponse(connected=connected, artist_count=artist_count)


# ===== Scan =====

@router.post(
    "/scan",
    response_model=ScanTriggerResponse,
    dependencies=[
        Depends(require_min_access_level(AccessLevel.ADMIN)),
        Depends(verify_same_origin),
    ],
)
async def post_navidrome_scan(user_id: int = Depends(get_current_user_id)) -> ScanTriggerResponse:
    _logger.info(f"🔄 [control_center] Navidrome-Scan angefordert von User {user_id}")
    try:
        result = await NavidromeScanTrigger.run_scan()
    except (AttributeError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(code="NAVIDROME_SCAN_CONFIG_ERROR", message=str(e)).model_dump(),
        ) from e
    except ScanTimeoutError as e:
        raise HTTPException(
            status_code=504, detail=ErrorDetail(code="NAVIDROME_SCAN_TIMEOUT", message=str(e)).model_dump(),
        ) from e

    return ScanTriggerResponse(
        success=result.success, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
    )




# ===== Cover-Art-Proxy =====
# Navidrome liefert Cover nur mit Auth - der Browser kann <img src> daher
# nicht direkt auf Navidrome zeigen lassen. Wir proxyen die Bytes durch das CC.

@router.get("/cover/{cover_id}")
async def get_cover(
    cover_id: str,
    size: int = Query(300, ge=1, le=1200),
) -> Response:
    api = NavidromeAPI()
    try:
        data, content_type = await asyncio.to_thread(
            api.fetch_cover_art, cover_id, size
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Cover nicht gefunden")
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )

# ===== Artists =====

@router.get("/artists", response_model=ArtistListResponse)
async def list_artists(
    page: int = Query(0, ge=0),
    page_size: int = Query(30, ge=1, le=200),
) -> ArtistListResponse:
    api = NavidromeAPI()
    raw = await api.get_artists()
    mapped = [_map_artist(a) for a in raw]
    total = len(mapped)
    window = _paginate(mapped, page, page_size)
    return ArtistListResponse(
        items=window,
        page=page,
        page_size=page_size,
        total=total,
        has_next=(page + 1) * page_size < total,
    )


@router.get("/artists/{artist_id}", response_model=ArtistDetailResponse)
async def get_artist(artist_id: str) -> ArtistDetailResponse:
    api = NavidromeAPI()
    data = await _req(api, "getArtist", {"id": artist_id})
    artist = _subsonic(data).get("artist") or {}
    if not artist:
        raise HTTPException(status_code=404, detail="Artist nicht gefunden")
    albums = [_map_album(a) for a in _as_list(artist.get("album"))]
    return ArtistDetailResponse(
        id=str(artist.get("id", artist_id)),
        name=artist.get("name") or "",
        album_count=artist.get("albumCount"),
        albums=albums,
    )


@router.get("/artists/{artist_id}/top", response_model=TopSongsResponse)
async def get_top_songs(
    artist_id: str,
    count: int = Query(25, ge=1, le=100),
) -> TopSongsResponse:
    api = NavidromeAPI()
    artist_data = await _req(api, "getArtist", {"id": artist_id})
    artist = _subsonic(artist_data).get("artist") or {}
    artist_name = artist.get("name")
    if not artist_name:
        raise HTTPException(status_code=404, detail="Artist nicht gefunden")

    data = await _req(api, "getTopSongs", {"artist": artist_name, "count": count})
    songs_raw = _subsonic(data).get("topSongs", {}).get("song", [])
    return TopSongsResponse(
        artist_id=artist_id,
        artist_name=artist_name,
        songs=[_map_song(s) for s in _as_list(songs_raw)],
    )


# ===== Albums =====

@router.get("/albums", response_model=AlbumListResponse)
async def list_albums(
    page: int = Query(0, ge=0),
    page_size: int = Query(15, ge=1, le=200),
    artist_id: Optional[str] = Query(None),
) -> AlbumListResponse:
    api = NavidromeAPI()
    if artist_id:
        data = await _req(api, "getArtist", {"id": artist_id})
        albums_raw = _as_list((_subsonic(data).get("artist") or {}).get("album"))
        mapped = [_map_album(a) for a in albums_raw]
        total: Optional[int] = len(mapped)
        window = _paginate(mapped, page, page_size)
        return AlbumListResponse(
            items=window,
            page=page,
            page_size=page_size,
            total=total,
            has_next=(page + 1) * page_size < total,
        )

    data = await _req(
        api,
        "getAlbumList2",
        {"type": "alphabeticalByArtist", "size": page_size, "offset": page * page_size},
    )
    albums_raw = _as_list(_subsonic(data).get("albumList2", {}).get("album"))
    mapped = [_map_album(a) for a in albums_raw]
    return AlbumListResponse(
        items=mapped,
        page=page,
        page_size=page_size,
        total=None,
        has_next=len(mapped) == page_size,
    )


@router.get("/albums/{album_id}", response_model=AlbumDetailResponse)
async def get_album(album_id: str) -> AlbumDetailResponse:
    api = NavidromeAPI()
    data = await _req(api, "getAlbum", {"id": album_id})
    album = _subsonic(data).get("album") or {}
    if not album:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    songs = [_map_song(s) for s in _as_list(album.get("song"))]
    return AlbumDetailResponse(
        id=str(album.get("id", album_id)),
        name=album.get("name") or "",
        artist=album.get("artist"),
        artist_id=album.get("artistId"),
        cover_art=album.get("coverArt"),
        year=album.get("year"),
        song_count=album.get("songCount"),
        duration=album.get("duration"),
        songs=songs,
    )


# ===== Genres =====

@router.get("/genres", response_model=GenreListResponse)
async def list_genres() -> GenreListResponse:
    api = NavidromeAPI()
    data = await _req(api, "getGenres", {})
    genres_raw = _as_list(_subsonic(data).get("genres", {}).get("genre"))
    items = [
        GenreItem(
            name=g.get("value") or g.get("name") or "",
            song_count=g.get("songCount"),
        )
        for g in genres_raw
    ]
    return GenreListResponse(items=items)


@router.get("/genres/{genre_name}", response_model=GenreDetailResponse)
async def get_genre_songs(
    genre_name: str,
    size: int = Query(50, ge=1, le=500),
) -> GenreDetailResponse:
    api = NavidromeAPI()
    data = await _req(
        api,
        "getSongsByGenre",
        {"genre": genre_name, "size": size, "offset": 0},
    )
    songs_raw = _as_list(_subsonic(data).get("songsByGenre", {}).get("song"))
    return GenreDetailResponse(
        name=genre_name,
        songs=[_map_song(s) for s in songs_raw],
    )


# ===== Songs =====

@router.get("/songs/{song_id}", response_model=SongDetailResponse)
async def get_song(song_id: str) -> SongDetailResponse:
    api = NavidromeAPI()
    data = await _req(api, "getSong", {"id": song_id})
    song = _subsonic(data).get("song") or {}
    if not song:
        raise HTTPException(status_code=404, detail="Song nicht gefunden")
    base = _map_song(song)
    genres_raw = song.get("genres") or []
    genre_names = [g.get("name", "") for g in genres_raw if isinstance(g, dict)]
    return SongDetailResponse(
        **base.model_dump(),
        genre=song.get("genre") or None,
        genres=genre_names,
        play_count=song.get("playCount"),
        cover_art=song.get("coverArt"),
    )


# ===== Suche & Entdecken =====

@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    type: str = Query("all"),
) -> SearchResponse:
    api = NavidromeAPI()
    result = await api.search(q)
    artists = [_map_artist(a) for a in _as_list(result.get("artist"))] if type in ("all", "artists") else []
    albums = [_map_album(a) for a in _as_list(result.get("album"))] if type in ("all", "albums") else []
    songs = [_map_song(s) for s in _as_list(result.get("song"))] if type in ("all", "songs") else []
    return SearchResponse(artists=artists, albums=albums, songs=songs)


@router.get("/random", response_model=RandomSongsResponse)
async def random_songs(size: int = Query(25, ge=1, le=100)) -> RandomSongsResponse:
    api = NavidromeAPI()
    data = await _req(api, "getRandomSongs", {"size": size})
    songs_raw = _as_list(_subsonic(data).get("randomSongs", {}).get("song"))
    return RandomSongsResponse(songs=[_map_song(s) for s in songs_raw])


@router.get("/newest", response_model=NewestAlbumsResponse)
async def newest_albums(
    page: int = Query(0, ge=0),
    page_size: int = Query(15, ge=1, le=100),
) -> NewestAlbumsResponse:
    api = NavidromeAPI()
    data = await _req(
        api,
        "getAlbumList2",
        {"type": "newest", "size": page_size, "offset": page * page_size},
    )
    albums_raw = _as_list(_subsonic(data).get("albumList2", {}).get("album"))
    mapped = [_map_album(a) for a in albums_raw]
    return NewestAlbumsResponse(
        items=mapped,
        page=page,
        page_size=page_size,
        has_next=len(mapped) == page_size,
    )


@router.get("/favorites", response_model=FavoritesResponse)
async def favorites() -> FavoritesResponse:
    api = NavidromeAPI()
    data = await _req(api, "getStarred2", {})
    starred = _subsonic(data).get("starred2", {}) or {}
    return FavoritesResponse(
        artists=[_map_artist(a) for a in _as_list(starred.get("artist"))],
        albums=[_map_album(a) for a in _as_list(starred.get("album"))],
        songs=[_map_song(s) for s in _as_list(starred.get("song"))],
    )


# ===== Playlists =====

@router.get("/playlists", response_model=PlaylistListResponse)
async def list_playlists(
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
) -> PlaylistListResponse:
    api = NavidromeAPI()
    data = await _req(api, "getPlaylists", {})
    playlists_raw = _as_list(_subsonic(data).get("playlists", {}).get("playlist"))
    mapped = [
        PlaylistItem(
            id=str(p.get("id", "")),
            name=p.get("name") or "",
            song_count=p.get("songCount") or 0,
            owner=p.get("owner"),
            duration=p.get("duration"),
            public=p.get("public"),
        )
        for p in playlists_raw
    ]
    total = len(mapped)
    window = _paginate(mapped, page, page_size)
    return PlaylistListResponse(
        items=window,
        page=page,
        page_size=page_size,
        total=total,
        has_next=(page + 1) * page_size < total,
    )


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetailResponse)
async def get_playlist(playlist_id: str) -> PlaylistDetailResponse:
    api = NavidromeAPI()
    data = await _req(api, "getPlaylist", {"id": playlist_id})
    pl = _subsonic(data).get("playlist") or {}
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist nicht gefunden")
    songs = [_map_song(s) for s in _as_list(pl.get("entry"))]
    return PlaylistDetailResponse(
        id=str(pl.get("id", playlist_id)),
        name=pl.get("name") or "",
        owner=pl.get("owner"),
        song_count=pl.get("songCount") or len(songs),
        duration=pl.get("duration"),
        songs=songs,
    )


@router.post(
    "/playlists",
    response_model=PlaylistMutationResponse,
    dependencies=[Depends(verify_same_origin)],
)
async def create_playlist(
    body: PlaylistCreateRequest,
    user_id: int = Depends(get_current_user_id),
) -> PlaylistMutationResponse:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    _logger.info(f"📋 [control_center] Playlist erstellen von User {user_id}: {name!r}")
    api = NavidromeAPI()
    data = await _req(api, "createPlaylist", {"name": name})
    pl = _subsonic(data).get("playlist") or {}
    return PlaylistMutationResponse(
        success=True,
        playlist_id=str(pl.get("id")) if pl.get("id") else None,
        name=pl.get("name") or name,
    )


@router.put(
    "/playlists/{playlist_id}",
    response_model=PlaylistMutationResponse,
    dependencies=[Depends(verify_same_origin)],
)
async def rename_playlist(
    playlist_id: str,
    body: PlaylistRenameRequest,
    user_id: int = Depends(get_current_user_id),
) -> PlaylistMutationResponse:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    _logger.info(f"✏️ [control_center] Playlist {playlist_id} umbenennen von User {user_id}: {name!r}")
    api = NavidromeAPI()
    await _req(api, "updatePlaylist", {"playlistId": playlist_id, "name": name})
    return PlaylistMutationResponse(success=True, playlist_id=playlist_id, name=name)


@router.delete(
    "/playlists/{playlist_id}",
    response_model=PlaylistMutationResponse,
    dependencies=[Depends(verify_same_origin)],
)
async def delete_playlist(
    playlist_id: str,
    user_id: int = Depends(get_current_user_id),
) -> PlaylistMutationResponse:
    _logger.info(f"🗑️ [control_center] Playlist {playlist_id} löschen von User {user_id}")
    api = NavidromeAPI()
    await _req(api, "deletePlaylist", {"id": playlist_id})
    return PlaylistMutationResponse(success=True, playlist_id=playlist_id)
