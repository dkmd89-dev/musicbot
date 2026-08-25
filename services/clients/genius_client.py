# genius_client.py (KORRIGIERTE VERSION)
# -*- coding: utf-8 -*-
"""
GeniusClient – Asynchroner Client für Genius-API und Lyrics-Scraping.
"""

import asyncio
import aiohttp
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Callable, Any
from pathlib import Path
from bs4 import BeautifulSoup
from tenacity import AsyncRetrying, wait_exponential, stop_after_attempt, RetryError
from lyricsgenius import Genius as LyricsGenius

from utils.lyrics_cache import LyricsCache
from config import Config
from logger import get_module_logger


class GeniusClient:
    """
    Asynchroner Client zur Interaktion mit der Genius-API und zum Scrapen von
    Songtexten.

    Strategie:
    1. Cache-Prüfung (LyricsCache)
    2. Genius-REST-API
    3. HTML-Scraping von genius.com (CAPTCHA-Fallback)
    4. lyricsgenius-Bibliothek als letzter Fallback

    Session-Management:
    ───────────────────
    Jede HTTP-Anfrage erhält eine eigene, kurzlebige aiohttp.ClientSession,
    die nach der Anfrage sofort mit `async with` geschlossen wird.
    Damit werden die asyncio-Warnungen „Unclosed client session" und
    „Unclosed connector" vollständig vermieden.
    """

    def __init__(self, logger: Optional[Any] = None):
        """
        Initialisiert den GeniusClient.

        Args:
            logger: Optionale Logger-Instanz. Wird keine übergeben, wird eine
                    neue Instanz über `get_module_logger` erstellt.
        """
        self.logger = logger or get_module_logger("GeniusClient")

        # RICHTIG: Config importieren und Instanz holen
        from config import get_config
        from pathlib import Path  # ← WICHTIG: Path importieren

        config = get_config()

        # Genius API aus der Config-Instanz holen (nicht aus der Klasse)
        self.genius_api = config.genius if hasattr(config, "genius") else None
        # Fuer _fallback_with_lyricsgenius() (Tier 4) - siehe dort, warum
        # nicht Config.GENIUS_CONFIG["access_token"] verwendet wird.
        self.genius_access_token = config.GENIUS_ACCESS_TOKEN

        # LyricsCache mit Config initialisieren (NUR EIN AUFRUF!)
        self.lyrics_cache = LyricsCache(
            cache_dir=config.LYRICS_CACHE_DIR_RESOLVED, config=config
        )

        # Zähler für Verarbeitungsstatistik
        self.processed_files: int = 0
        self.failed_files: int = 0

        self.logger.info("✨ GeniusClient initialisiert.")
        self.logger.debug(f"   Lyrics-Cache Pfad: {self.lyrics_cache.cache_path}")

    # ──────────────────────────────────────────────────────────────────────────
    # Öffentliche API
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_metadata(self, title: str, artist: str) -> Dict[str, Optional[str]]:
        """
        Hauptmethode zum Abrufen von Metadaten und Songtexten.

        Args:
            title:  Liedtitel
            artist: Künstlername

        Returns:
            Dictionary mit Keys: title, artist, lyrics, genius_url,
            cover_url, year, album – oder leeres Dict bei Fehlschlag.
        """
        return await self._fetch_lyrics(title, artist)

    async def async_close(self) -> None:
        """
        Asynchrone Aufräum-Methode.

        Wird von bot.py's `_async_cleanup_components()` aufgerufen.
        Da wir keine persistente Session mehr halten, gibt es hier
        nichts zu schließen – die Methode existiert für API-Kompatibilität.
        """
        self.logger.debug(
            "ℹ️ GeniusClient.async_close() aufgerufen (keine persistente Session)."
        )

    def close(self) -> None:
        """
        Synchrone Aufräum-Methode (Legacy-Kompatibilität).

        Keine persistente Session zu schließen, aber räumt den
        Lyrics-Cache auf (leere/korrupte/TTL-abgelaufene Einträge).
        """
        self.lyrics_cache.cleanup()

    # ──────────────────────────────────────────────────────────────────────────
    # Interne Logik
    # ──────────────────────────────────────────────────────────────────────────

    async def _fetch_lyrics(self, title: str, artist: str) -> Dict[str, Optional[str]]:
        """Lyrics abrufen – UnboundLocalError-sicher."""
        clean_artist = artist.strip()
        clean_title = title.strip()

        # 1. Cache
        cached = self.lyrics_cache.get(clean_artist, clean_title)
        if cached and self._is_valid_lyrics(cached.get("lyrics", "")):
            self.logger.debug(f"✅ Cache-Hit für '{clean_artist} - {clean_title}'")
            return cached

        query = f"{clean_title} {clean_artist}"
        lyrics = ""
        genius_url = ""
        song = {}

        try:
            lyrics, genius_url, song = await self._fetch_via_genius_api(
                clean_title, clean_artist, query
            )

            # 3. HTML-Scraping Fallback
            if not self._is_valid_lyrics(lyrics) and genius_url:
                self.logger.warning("⚠️ API-Lyrics unvollständig → HTML-Scraping...")
                lyrics = await self._scrape_genius_lyrics_html(genius_url)

            # 4. lyricsgenius Fallback
            if not self._is_valid_lyrics(lyrics):
                self.logger.warning("⚠️ HTML-Scraping erfolglos → lyricsgenius...")
                lyrics = await asyncio.to_thread(
                    self._fallback_with_lyricsgenius, clean_title, clean_artist
                )

            # 5. Ergebnis
            if self._is_valid_lyrics(lyrics):
                metadata = {
                    "title": song.get("title", clean_title),
                    "artist": song.get("primary_artist", {}).get("name", clean_artist),
                    "lyrics": lyrics,
                    "genius_url": genius_url,
                    "cover_url": song.get("song_art_image_url"),
                    "year": (
                        str(song.get("release_date_components", {}).get("year") or "")[
                            :4
                        ]
                        or None
                    ),
                    "album": (
                        song.get("album", {}).get("name") if song.get("album") else None
                    ),
                }
                self.logger.info(
                    f"📜✔️ Lyrics für '{clean_artist} - {clean_title}' gefunden."
                )
                self.lyrics_cache.store(clean_artist, clean_title, metadata)
                self.processed_files += 1
                return metadata

        except Exception as e:
            self.logger.error(
                f"🐛 Unerwarteter Fehler bei '{query}': {e}", exc_info=True
            )

        self.failed_files += 1
        self.logger.error(
            f"❌ Keine Lyrics für '{clean_artist} - {clean_title}' gefunden."
        )
        return {}

    async def _fetch_via_genius_api(self, clean_title: str, clean_artist: str, query: str):
        """
        Tier 2 (Genius-REST-API) als eigener, isolierter Schritt.

        Gibt bei JEDEM Fehlschlag (kein genius_api konfiguriert, Netzwerkfehler,
        kein Suchtreffer, keine extrahierbare Song-ID) ("", "", {}) zurueck,
        statt die Ausnahme/einen fruehen Return nach aussen durchzureichen.
        Vorher fuehrte ein Fehlschlag hier (z.B. self.genius_api is None, weil
        kein GENIUS_ACCESS_TOKEN konfiguriert ist) dazu, dass die komplette
        Methode sofort abbrach und Tier 3 (HTML-Scraping) sowie Tier 4
        (lyricsgenius-Bibliothek) NIE versucht wurden - obwohl beide
        unabhaengig von einem erfolgreichen API-Suchtreffer funktionieren
        koennen (Tier 4 braucht nur einen eigenen Token, keinen API-Client).
        """
        lyrics = ""
        genius_url = ""
        song: Dict[str, Any] = {}

        if self.genius_api is None:
            self.logger.debug(
                "ℹ️ Kein Genius-API-Client konfiguriert (GENIUS_ACCESS_TOKEN fehlt) "
                "→ überspringe REST-API-Suche."
            )
            return lyrics, genius_url, song

        try:
            # 2. Direkte Suche via search_song()
            search_result = await self._fetch_with_retry(
                self.genius_api.search_song, clean_title, clean_artist
            )

            if search_result:
                # ✅ FIX: search_result ist ein Song-Objekt – extrahiere die ID korrekt
                song_id = None

                # Versuche verschiedene Wege, an die Song-ID zu kommen
                if hasattr(search_result, "id"):
                    song_id = search_result.id
                elif hasattr(search_result, "song_id"):
                    song_id = search_result.song_id
                elif isinstance(search_result, dict) and "id" in search_result:
                    song_id = search_result["id"]
                elif hasattr(search_result, "url"):
                    # Fallback: ID aus URL extrahieren
                    import re

                    url = search_result.url
                    match = re.search(r"/(\d+)/", url)
                    if match:
                        song_id = int(match.group(1))

                if song_id:
                    song_details = await self._fetch_with_retry(
                        self.genius_api.song, song_id
                    )
                    song = song_details.get("song", {}) if song_details else {}
                    genius_url = song.get("url", "")
                    lyrics = song.get("lyrics", {}).get("plain", "") or ""
                else:
                    # Wenn search_result schon die vollständigen Daten hat
                    if hasattr(search_result, "lyrics"):
                        lyrics = search_result.lyrics or ""
                    if hasattr(search_result, "url"):
                        genius_url = search_result.url
                    # Versuche, ein Dict zu erstellen
                    song = {
                        "title": getattr(search_result, "title", clean_title),
                        "primary_artist": {
                            "name": getattr(search_result, "artist", clean_artist)
                        },
                        "url": genius_url,
                    }
            else:
                # Fallback: search_songs() für breitere Suche
                self.logger.debug(
                    "search_song() ohne Ergebnis → versuche search_songs()..."
                )
                # ✅ FIX A: Immer initialisieren
                best_match = None

                search_songs_result = await self._fetch_with_retry(
                    self.genius_api.search_songs,
                    query,
                    per_page=Config.GENIUS_CONFIG.get("max_results", 5),
                )
                hits = (
                    search_songs_result.get("hits", []) if search_songs_result else []
                )

                if hits:
                    best_match = self._find_best_match_dynamic(
                        clean_title, clean_artist, [h["result"] for h in hits]
                    )

                # Kein Match gefunden - kein fruehes return {} mehr (siehe
                # Docstring): Tier 3/4 sollen trotzdem versucht werden.
                if best_match is None:
                    self.logger.warning(
                        f"⚠️ Kein Genius-Match für: '{clean_title}' / '{clean_artist}'"
                    )
                    return lyrics, genius_url, song

                # Song-ID sicher extrahieren (best_match ist ein Dict im Fallback-Pfad)
                song_id = best_match.get("id")
                if not song_id:
                    song_url = best_match.get("url", "")
                    if song_url:
                        import re

                        m = re.search(r"/(\d+)/", song_url)
                        song_id = m.group(1) if m else None

                if not song_id:
                    self.logger.warning("⚠️ Keine Song-ID aus Match extrahierbar")
                    return lyrics, genius_url, song

                song_details = await self._fetch_with_retry(
                    self.genius_api.song, song_id
                )
                song = song_details.get("song", {}) if song_details else {}
                genius_url = song.get("url", "")
                lyrics = song.get("lyrics", {}).get("plain", "") or ""

            return lyrics, genius_url, song

        except Exception as e:
            self.logger.warning(
                f"⚠️ Genius-REST-API-Suche fehlgeschlagen fuer '{query}': {e} "
                f"→ Tier 3/4 werden trotzdem versucht."
            )
            return "", "", {}

    async def _scrape_genius_lyrics_html(self, url: str) -> str:
        """
        Scrapt Songtexte direkt von der Genius-Webseite als Fallback.

        WICHTIG – Session-Management:
        ─────────────────────────────
        Wir erstellen hier eine **eigene, kurzlebige** aiohttp.ClientSession
        und schließen sie sofort nach der Anfrage mit `async with`.
        Das verhindert die asyncio-Warnungen „Unclosed client session" /
        „Unclosed connector", die entstehen, wenn Sessions nicht explizit
        geschlossen werden.

        Args:
            url: Vollständige Genius-URL des Songs

        Returns:
            Gefundener Songtext als String oder leerer String bei Fehler.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0.0.0 Safari/537.36"
            )
        }

        try:
            # ✅ Session als Kontext-Manager → wird garantiert geschlossen
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.warning(
                            f"🕸️ Genius HTML-Status {response.status} für URL: {url}"
                        )
                        return ""

                    html = await response.text()

            # HTML-Parsing außerhalb der Session (Session ist bereits zu)
            if "captcha" in html.lower() or "are you human" in html.lower():
                self.logger.warning(
                    "👮 CAPTCHA erkannt – Zugriff auf Genius-HTML geblockt."
                )
                return ""

            soup = BeautifulSoup(html, "html.parser")

            # Moderner Lyrics-Container
            containers = soup.select('div[data-lyrics-container="true"]')
            if containers:
                lyrics = "\n\n".join(
                    div.get_text("\n", strip=True) for div in containers
                )
                return lyrics.replace("\u200b", "").replace("\ufeff", "").strip()

            # Legacy-Fallback
            self.logger.warning(
                "🕸️ Moderner Lyrics-Container nicht gefunden, versuche Legacy-Struktur."
            )
            legacy = soup.select_one("div.lyrics")
            if legacy:
                return (
                    legacy.get_text("\n", strip=True)
                    .replace("\u200b", "")
                    .replace("\ufeff", "")
                    .strip()
                )

            self.logger.error(
                "❌ HTML-Scraping: Konnte keinen Lyrics-Container finden."
            )
            return ""

        except aiohttp.ClientError as e:
            self.logger.error(
                f"🌐 Netzwerkfehler beim HTML-Scraping: {e}", exc_info=True
            )
            return ""
        except Exception as e:
            self.logger.error(
                f"🐛 Unerwarteter Fehler beim HTML-Scraping: {e}", exc_info=True
            )
            return ""

    def _fallback_with_lyricsgenius(self, title: str, artist: str) -> str:
        """
        Verwendet die `lyricsgenius`-Bibliothek als letzten Lyrics-Fallback.

        Wird über `asyncio.to_thread()` aus dem async-Kontext aufgerufen,
        da lyricsgenius synchron ist.

        Args:
            title:  Liedtitel
            artist: Künstlername

        Returns:
            Lyrics-String oder leerer String bei Fehler.
        """
        if not self.genius_access_token:
            self.logger.debug(
                "ℹ️ Kein GENIUS_ACCESS_TOKEN konfiguriert → lyricsgenius-Fallback "
                "übersprungen."
            )
            return ""

        try:
            # GENIUS_CONFIG (config.py) hat keinen "access_token"-Key (nur
            # timeout/max_retries/...) - das fuehrte bisher IMMER zu einem
            # KeyError hier, unabhaengig davon, ob anderswo ein gueltiger
            # Token konfiguriert war. self.genius_access_token (siehe
            # __init__) liest den echten Token aus Config.GENIUS_ACCESS_TOKEN,
            # denselben, den auch die Tier-2-REST-API verwendet.
            client = LyricsGenius(
                self.genius_access_token,
                skip_non_songs=True,
                remove_section_headers=True,
                timeout=10,
            )
            song = client.search_song(title=title, artist=artist)
            if song and song.lyrics:
                self.logger.info("✅ lyricsgenius-Fallback erfolgreich.")
                return song.lyrics.strip()
            self.logger.warning("⚠️ lyricsgenius konnte keine gültigen Lyrics finden.")
            return ""
        except Exception as e:
            self.logger.error(f"🐛 lyricsgenius-Fallback-Fehler: {e}", exc_info=True)
            return ""

    # ──────────────────────────────────────────────────────────────────────────
    # Hilfsmethoden
    # ──────────────────────────────────────────────────────────────────────────

    def _is_valid_lyrics(self, lyrics: str) -> bool:
        """
        Prüft, ob ein Songtext-String gültig ist (nicht leer oder Platzhalter).

        Args:
            lyrics: Zu prüfender Lyrics-String

        Returns:
            True wenn der Text als gültig gilt, sonst False.
        """
        if not lyrics or not lyrics.strip():
            return False
        content = lyrics.lower().strip()
        invalid_markers = [
            "lyrics not available",
            "lyrics for this song have yet to be released",
            "we're sorry",
            "genius isn't available in your country",
        ]
        return len(content) >= 40 and not any(m in content for m in invalid_markers)

    def _find_best_match_dynamic(
        self, title: str, artist: str, candidates: List[Dict]
    ) -> Optional[Dict]:
        """
        Findet den besten Treffer aus den API-Ergebnissen durch dynamische
        Gewichtung von Titel- und Künstler-Ähnlichkeit.

        Logik:
        - Hohe Artist-Übereinstimmung (≥ 0.9): gleichgewichtete Mittelung
        - Sonst: Titel gewichtet stärker (0.65 vs 0.35)

        Args:
            title:      Gesuchter Titel
            artist:     Gesuchter Künstler
            candidates: Liste von Genius-Treffern (Dicts)

        Returns:
            Bester Treffer als Dict oder None wenn kein Treffer den
            Schwellenwert überschreitet.
        """
        best_match: Optional[Dict] = None
        best_score: float = 0.0

        for cand in candidates:
            c_title = cand.get("title", "")
            c_artist = cand.get("primary_artist", {}).get("name", "")

            title_score = SequenceMatcher(None, title.lower(), c_title.lower()).ratio()
            artist_score = SequenceMatcher(
                None, artist.lower(), c_artist.lower()
            ).ratio()

            if artist_score >= 0.9:
                # Sehr hohe Artist-Übereinstimmung → gleichgewichtet
                score = (title_score + artist_score) / 2
                threshold = 0.5
            else:
                # Standard: Titel-Ähnlichkeit stärker gewichten
                score = (title_score * 0.65) + (artist_score * 0.35)
                threshold = Config.GENIUS_CONFIG.get("match_threshold", 0.75)

            if score > best_score and score >= threshold:
                best_score = score
                best_match = cand

        return best_match

    async def _fetch_with_retry(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        Führt eine synchrone Funktion (Genius-API-Call) mit exponentiellem
        Backoff und konfigurierbaren Wiederholungsversuchen aus.

        Nutzt `asyncio.to_thread()` damit der Event-Loop nicht blockiert.

        Args:
            func:   Aufzurufende synchrone Funktion
            *args:  Positionsargumente für func
            **kwargs: Schlüsselwortargumente für func

        Returns:
            Rückgabewert von func oder None bei endgültigem Fehlschlag.
        """
        try:
            async for attempt in AsyncRetrying(
                wait=wait_exponential(min=2, max=10),
                stop=stop_after_attempt(Config.GENIUS_CONFIG["max_retries"]),
                reraise=True,
            ):
                with attempt:
                    self.logger.debug(
                        f"🔁 Versuch {attempt.retry_state.attempt_number} "
                        f"für '{func.__name__}'..."
                    )
                    return await asyncio.to_thread(func, *args, **kwargs)
        except RetryError as e:
            self.logger.error(
                f"❌ Maximale Wiederholungsversuche für '{func.__name__}' "
                f"erreicht. Fehler: {e}"
            )
            return None
