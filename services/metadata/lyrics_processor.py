# services/metadata/lyrics_processor.py
# -*- coding: utf-8 -*-

from typing import List, Optional, Tuple

from logger import get_module_logger


class LyricsProcessor:
    """
    Verantwortlich für das Abrufen von Lyrics über den Genius-Client.
    Unterstützt Fallback auf Feature-Artists wenn der Hauptartist kein Ergebnis liefert.
    """

    def __init__(self, genius_client, logger=None):
        self.genius_client = genius_client
        self.logger = logger or get_module_logger("LyricsProcessor")

    # ─────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_lyrics(
        self,
        artist: str,
        title: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Ruft Lyrics für einen Track ab.
        Gibt (lyrics, source) zurück — source ist "genius" oder None.
        """
        try:
            self.logger.debug(f"📜 Lade Lyrics für: {artist} - {title}")
            genius_data = await self.genius_client.fetch_metadata(title, artist)
            if genius_data and genius_data.get("lyrics"):
                lyrics = genius_data["lyrics"]
                self.logger.info(f"📜✅ Lyrics gefunden für: {title}")
                return lyrics, "genius"
        except Exception as e:
            self.logger.warning(f"📜❌ Fehler beim Laden der Lyrics: {e}")
        return None, None

    async def fetch_lyrics_with_fallback(
        self,
        artist: str,
        title: str,
        fallback_artists: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Versucht Lyrics mit dem Hauptartist abzurufen.
        Falls kein Ergebnis, werden fallback_artists (z.B. feat. Artists) probiert.
        Gibt (lyrics, source) zurück — source ist "genius" oder None.
        """
        # Erster Versuch: Hauptartist
        lyrics, source = await self.fetch_lyrics(artist, title)
        if lyrics:
            return lyrics, source

        # Fallback: Feature-Artists
        if fallback_artists:
            for fallback_artist in fallback_artists:
                if not fallback_artist or fallback_artist.strip().lower() == artist.strip().lower():
                    continue
                self.logger.debug(
                    f"📜 Lyrics-Fallback: versuche feat. Artist '{fallback_artist}'"
                )
                lyrics, source = await self.fetch_lyrics(fallback_artist, title)
                if lyrics:
                    self.logger.info(
                        f"📜✅ Lyrics via Fallback-Artist '{fallback_artist}' gefunden für: {title}"
                    )
                    return lyrics, source

        self.logger.debug(f"📜❌ Keine Lyrics gefunden für: {artist} - {title}")
        return None, None
