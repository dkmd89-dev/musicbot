# services/clients/lastfm_client.py

import asyncio
import pylast
from typing import Optional, Dict, List, Any, Tuple

from config import Config
import async_timeout
from logger import get_module_logger


# Baseline v5/v6 Technical Debt (P3, latentes Secret-Leak-Risiko):
# pylast.LastFMNetwork.__repr__() baut den API-Key/API-Secret/Session-Key/
# Password-Hash direkt in den Repr-String ein (pylast/__init__.py, Klasse
# LastFMNetwork). Da praktisch jedes von einem Network-Objekt erzeugte
# pylast-Domainobjekt (Artist, Track, Album, Tag, ...) sein eigenes
# __repr__() wiederum ueber repr(self.network) aufbaut, wuerde JEDES
# versehentliche repr()/f"{obj!r}"-Logging eines beliebigen pylast-Objekts
# (nicht nur des Network-Objekts selbst) alle vier Secrets im Klartext
# offenlegen - aktuell nirgends im Code aufgerufen (kein aktives Leck),
# aber ein latentes Risiko bei kuenftigen Aenderungen. Instanz-Attribute
# koennen __repr__ nicht ueberschreiben (Python loest Dunder-Methoden fuer
# eingebaute Funktionen wie repr() immer auf der Klasse auf, nie auf der
# Instanz) - der Fix patcht daher die Klassenmethode selbst, einmalig beim
# Modul-Import. Das macht automatisch auch Artist.__repr__()/
# Track.__repr__() etc. sicher, da diese lediglich repr(self.network)
# delegieren. __str__() ("{name} Network") ist bereits sicher und bleibt
# unveraendert.
def _safe_lastfm_network_repr(self: "pylast.LastFMNetwork") -> str:
    return "pylast.LastFMNetwork(<redacted>)"


pylast.LastFMNetwork.__repr__ = _safe_lastfm_network_repr


class LastFMClient:
    """
    Client zur Abfrage von Last.fm-Metadaten.
    """

    def __init__(self, logger: Optional[Any] = None):
        """
        Initialisiert den LastFMClient.

        Args:
            logger: Optionale Logger-Instanz. Wird keine übergeben, wird eine
                    neue Instanz über `get_module_logger` erstellt.
        """
        self.logger = logger or get_module_logger("LastfmClient")

        config = Config()
        self.api_key = config.LASTFM_API_KEY
        self.api_secret = config.LASTFM_API_SECRET

        # Network initialisieren (genau wie im Test)
        self.network = pylast.LastFMNetwork(
            api_key=self.api_key,
            api_secret=self.api_secret,
            username=None,
            password_hash=None,
        )
        self.logger.info("✨ LastFMClient initialisiert.")

    def _get_lastfm_data(
        self, title: str, artist: str, mbid: str = None
    ) -> Tuple[Optional[Dict], List]:
        """
        Holt Last.fm-Daten für einen Track.
        """
        context_str = f"{artist} - {title}"
        
        try:
            # Artist-Objekt holen (wie im Test)
            artist_obj = self.network.get_artist(artist)
            if not artist_obj:
                self.logger.debug(f"[{context_str}] Artist nicht gefunden")
                return None, []

            self.logger.debug(f"[{context_str}] Artist gefunden: {artist_obj}")

            # Artist-Tags holen (funktioniert wie im Test)
            artist_tags = []
            try:
                tags = artist_obj.get_top_tags(limit=10)
                artist_tags = [tag.item.get_name().lower() for tag in tags]
                if artist_tags:
                    self.logger.info(f"[{context_str}] 🎤 Artist-Tags: {artist_tags[:5]}")
            except Exception as e:
                self.logger.debug(f"[{context_str}] Artist-Tags Fehler: {e}")

            # Versuche Track-Tags (wenn möglich)
            track_tags = []
            try:
                # Track via get_track versuchen
                track = self.network.get_track(artist, title)
                if track:
                    track_tags_raw = track.get_top_tags(limit=10) or []
                    track_tags = [tag.item.get_name().lower() for tag in track_tags_raw]
                    if track_tags:
                        self.logger.info(f"[{context_str}] 🏷️ Track-Tags: {track_tags[:5]}")
            except Exception as e:
                self.logger.debug(f"[{context_str}] Track-Tags Fehler: {e}")

            # Kombiniere Tags (Artist-Tags haben Vorrang)
            all_tags = []
            for t in artist_tags + track_tags:
                if t not in all_tags:
                    all_tags.append(t)

            # Simuliere track_info für minimalen Fallback
            track_info = {
                "title": title,
                "artist": artist,
                "album": None,
                "listeners": None,
                "playcount": None,
                "wiki": None,
            }

            self.logger.info(f"[{context_str}] ✅ {len(all_tags)} Tags: {all_tags[:5]}")
            return track_info, all_tags

        except Exception as e:
            self.logger.error(f"[{context_str}] Fehler: {e}", exc_info=True)
            return None, []

    async def fetch_metadata(
        self, title: str, artist: str, include_genre: bool = True, mbid: str = None
    ) -> Dict[str, Any]:
        """
        Holt Last.fm-Metadaten.
        """
        context_str = f"{artist} - {title}"
        self.logger.debug(f"[LastFM] 📥 Hole Metadaten für: {context_str}")

        try:
            async with async_timeout.timeout(Config.LASTFM_TIMEOUT):
                track_info, tag_names = await asyncio.to_thread(
                    self._get_lastfm_data, title, artist, mbid
                )

                if not track_info:
                    self.logger.info(f"[LastFM] Keine Daten für {context_str}")
                    return {}

                self.logger.info(f"[LastFM] 🏷️ {len(tag_names)} Tags: {tag_names[:5] if tag_names else 'keine'}")

                # ARCH-012 Phase 2: das frueher hier per GenreMapper.determine_genre()
                # berechnete Genre wurde vom einzigen Aufrufer
                # (genre_processor._fetch_genre_from_lastfm()) praktisch nie
                # verwendet - die eigentliche Entscheidung faellt dort ueber
                # prioritize_genres() auf den rohen "tags". "genre" bleibt als
                # Schluessel erhalten (unveraenderte Rueckgabestruktur), liefert
                # aber nur noch den Platzhalter, der zuvor bereits der Fallback-
                # Wert war. include_genre bleibt Teil der Signatur, wird aber
                # nicht mehr ausgewertet.
                return {
                    "tags": tag_names,
                    "listeners": track_info.get("listeners"),
                    "playcount": track_info.get("playcount"),
                    "album": track_info.get("album"),
                    "wiki": track_info.get("wiki"),
                    "genre": "unknown",
                }
                
        except asyncio.TimeoutError:
            self.logger.warning(f"[LastFM] ⏱️ Timeout für {context_str}")
            return {}
        except Exception as e:
            self.logger.error(f"[LastFM] ❌ Fehler: {e}")
            return {}
