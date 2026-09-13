# services/navidrome/browser_service.py
# -*- coding: utf-8 -*-
"""
Reine API-Aufruf-/Datenextraktions-Funktion für die Navidrome-Album-
Browse-Ansicht.

Architecture Refactoring Audit, Migrationsstufe 4 (siehe
docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md,
Abschnitt 5/Nachtrag): 1:1 aus
handlers/navidrome_menu_handler.py::handle_browse_albums() extrahiert -
die einzige der drei Browse-Methoden mit echter Verzweigungslogik (zwei
Subsonic-Endpunkte je nach `artist_id`). Bewusst NICHT für
handle_browse_artists()/handle_browse_genres() (nach der Rendering-
Extraktion in Stufe 1/3 dort nur noch 1-2 Zeilen reiner API-Call - eine
Service-Extraktion wäre dort reine Zeremonie ohne Kopplungsgewinn,
siehe CLAUDE.md Abschnitt 18/Anti-Overengineering-Regel des Plans).

Verantwortlichkeit (Single Responsibility):
  - Ausschließlich Subsonic-API-Aufruf + Response-Unwrapping für die
    Album-Liste (Artist-spezifisch via `getArtist`, sonst
    `getAlbumList2`).
  - KEIN Rendering, KEIN Telegram-Bezug, KEIN Error-Handling - das
    bleibt in `NavidromeMenuHandler.handle_browse_albums()`
    (Connection-Check + `try/except`).

`navidrome_api` wird injiziert (kein eigener Import/keine eigene
Konstruktion - konsistent mit der ARCH-009/`services/clients`-
Konvention: reiner Integrationsadapter-Aufruf, keine eigene
NavidromeAPI-Instanziierung in dieser Schicht).
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple


async def get_albums_page(
    navidrome_api,
    page: int,
    artist_id: Optional[str],
    page_size: int = 15,
) -> Tuple[List[Dict[str, Any]], str]:
    """Lädt eine Seite Alben - Artist-spezifisch via `getArtist` (liefert
    die komplette Albumliste des Künstlers, hier lokal paginiert), sonst
    alphabetisch via `getAlbumList2` (Offset/Size direkt an die API).

    Gibt `(albums, title_prefix)` zurück. 1:1 aus
    `NavidromeMenuHandler.handle_browse_albums()` verschoben, keine
    Verhaltensänderung."""
    if artist_id:
        # getArtist liefert Albumliste des Künstlers
        data = await asyncio.to_thread(
            navidrome_api.make_request, "getArtist", {"id": artist_id}
        )
        artist = data.get("subsonic-response", {}).get("artist", {})
        albums = artist.get("album", [])
        title_prefix = "🎤 Alben des Künstlers"
        # Lokal paginieren
        start = page * page_size
        end = start + page_size
        albums = albums[start:end]
    else:
        # Alphabetisch nach Künstler mit Offset/Size
        params = {
            "type": "alphabeticalByArtist",
            "size": page_size,
            "offset": page * page_size,
        }
        data = await asyncio.to_thread(
            navidrome_api.make_request, "getAlbumList2", params
        )
        albums = (
            data.get("subsonic-response", {})
            .get("albumList2", {})
            .get("album", [])
        )
        title_prefix = "💿 Alle Alben"

    return albums, title_prefix
