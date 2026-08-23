# services/downloader/spotify_downloader.py
# -*- coding: utf-8 -*-
"""
🎵 SpotifyDownloader – Spezialversion OHNE Premium & OHNE API-Keys.
Nutzt die Spotify-Embed-API für Metadaten und yt-dlp für den Download.

Unterstützte Typen:
- Track (Musik)
- Episode (Podcast)
- Show (Podcast-Serie)
- Album (kommt später)
- Playlist (kommt später)

CHANGELOG v2.2:
    ✅ Embed-API als PRIMÄRE Quelle (subtitle = Show-Name)
    ✅ oEmbed nur noch als Fallback
    ✅ Vollständig transparentes Logging mit Schritt-für-Schritt-Status
    ✅ Cover-Art von Spotify wird geladen und an Pipeline übergeben
    ✅ Verbesserte Fehlerbehandlung mit detaillierten Logs
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from utils.podcast_rss_manager import PodcastRSSManager

from logger import get_module_logger

# ─────────────────────────────────────────────────────────────────────────────
# HILFSFUNKTIONEN
# ─────────────────────────────────────────────────────────────────────────────


def _is_spotify_url(url: str) -> bool:
    """Prüft ob eine URL eine Spotify-URL ist."""
    return bool(
        re.search(
            r"(open\.spotify\.com|spotify\.link|spoti\.fi)", url.strip(), re.IGNORECASE
        )
    )


def _spotify_url_type(url: str) -> str:
    """Gibt den Typ der Spotify-URL zurück."""
    url = url.strip().lower()
    if "/track/" in url:
        return "track"
    if "/album/" in url:
        return "album"
    if "/playlist/" in url:
        return "playlist"
    if "/episode/" in url:
        return "episode"
    if "/show/" in url:
        return "show"
    return "unknown"


def _extract_spotify_id(url: str) -> Optional[str]:
    """Extrahiert die Spotify-ID (robust gegen /intl-de/ und andere Einschübe)."""
    match = re.search(r"(?:track|album|playlist|episode|show)/([A-Za-z0-9]+)", url)
    if match:
        return match.group(1)

    clean_url = url.split("?")[0].strip("/")
    parts = clean_url.split("/")
    if parts:
        possible_id = parts[-1]
        if possible_id.isalnum() and len(possible_id) >= 15:
            return possible_id
    return None


def _sanitize_spotify_url(url: str) -> str:
    """Entfernt Tracking-Parameter wie ?si=..."""
    return url.strip().split("?")[0].rstrip("/")


# ─────────────────────────────────────────────────────────────────────────────
# HAUPTKLASSE
# ─────────────────────────────────────────────────────────────────────────────


class SpotifyDownloader:
    """
    Spotify-Downloader ohne API-Key.

    Verwendet die öffentliche Embed-API von Spotify für Metadaten
    und yt-dlp für den eigentlichen Audio-Download von YouTube.
    """

    def __init__(
        self,
        config,
        logger_factory: Optional[Callable] = None,
        artist_map=None,
        rss_manager=None,
    ):
        self.config = config
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("SpotifyDownloader")
        self.artist_map = artist_map

        # Verzeichnisse aus Config laden
        self.download_dir = Path(getattr(config, "DOWNLOAD_DIR", "/tmp/spotify_dl"))
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.audio_format = getattr(config, "AUDIO_FORMAT", "m4a")
        self.audio_quality = str(getattr(config, "AUDIO_QUALITY", "192"))

        self.logger.info("=" * 60)
        self.logger.info("🎵 SpotifyDownloader (No-API Mode) initialisiert")
        self.logger.info(f"   📁 Download-Verzeichnis: {self.download_dir}")
        self.logger.info(
            f"   🎵 Audio-Format: {self.audio_format} @ {self.audio_quality}kbps"
        )
        self.logger.info(
            f"   👤 Artist-Map: {'Verfügbar' if self.artist_map else 'Nicht verfügbar'}"
        )
        self.logger.info("   📋 Unterstützte Typen: Track, Episode, Show")
        self.logger.info("=" * 60)
        # 🆕 Podcast RSS Manager initialisieren (ARCH-003, P-8: optional
        # injizierbar - ohne Angabe unverändertes Default-Verhalten)
        if rss_manager is not None:
            self.rss_manager = rss_manager
        else:
            mapping_dir = getattr(config, "GENRE_MAPPING_DIR", "mapping")
            self.rss_manager = PodcastRSSManager(mapping_dir, self.logger_factory)

        self.logger.info(
            f"📻 Podcast RSS Manager: {len(self.rss_manager.feeds)} Feeds geladen"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # METADATEN-EXTRAKTION
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_metadata_no_api(
        self, spotify_id: str, content_type: str = "track"
    ) -> Optional[Dict[str, Any]]:
        """
        Extrahiert Metadaten über die Embed-API (PRIMÄR) und oEmbed (FALLBACK).

        Für Podcasts (content_type="episode"):
            - Embed-API liefert Show-Name im 'subtitle'-Feld
            - oEmbed liefert KEINEN Show-Namen (nur "Spotify" als provider_name)
        """
        loop = asyncio.get_event_loop()

        self.logger.debug(
            f"🔍 [METADATEN] Starte Extraktion: ID={spotify_id}, Typ={content_type}"
        )

        # ===== METHODE 1: Embed-API (PRIMÄR - hat Show-Name im 'subtitle') =====
        embed_url = f"https://open.spotify.com/embed/{content_type}/{spotify_id}"
        embed_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            self.logger.debug(f"   🌐 Embed-API: {embed_url}")

            def _fetch_embed():
                req = Request(embed_url, headers=embed_headers)
                with urlopen(req, timeout=10) as resp:
                    return resp.read().decode("utf-8")

            html = await loop.run_in_executor(None, _fetch_embed)
            self.logger.debug(f"   📄 HTML empfangen: {len(html)} Zeichen")

            json_match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html,
                re.DOTALL,
            )

            if json_match:
                self.logger.debug(
                    f"   ✅ __NEXT_DATA__ JSON gefunden ({len(json_match.group(1))} chars)"
                )
                data = json.loads(json_match.group(1))
                entity = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("state", {})
                    .get("data", {})
                    .get("entity", {})
                )

                if entity:
                    self.logger.debug(
                        f"   ✅ Entity gefunden mit Keys: {list(entity.keys())[:5]}..."
                    )

                    # 🖼️ Cover-Art URL extrahieren
                    cover_url = None
                    visual_identity = entity.get("visualIdentity", {})
                    images = visual_identity.get("image", [])
                    if images:
                        cover_url = images[0].get("url")
                        self.logger.debug(
                            f"   🖼️ Cover-URL: {cover_url[:80]}..."
                            if cover_url
                            else "   🖼️ Kein Cover"
                        )

                    if content_type == "episode":
                        episode_name = entity.get("name", "Unknown Episode")

                        # 1. PRIORITÄT: 'subtitle' ist der Show-Name
                        show_name = entity.get("subtitle")

                        # 2. FALLBACK: 'show'-Objekt
                        if not show_name:
                            show_name = entity.get("show", {}).get("name")
                            if show_name:
                                self.logger.debug(
                                    f"   📻 Show aus 'show.name': {show_name}"
                                )

                        # 3. LETZTER FALLBACK: 'publisher'
                        if not show_name:
                            show_name = entity.get("publisher")
                            if show_name:
                                self.logger.debug(
                                    f"   📻 Show aus 'publisher': {show_name}"
                                )

                        # 🆕 Fallback: <title>-Tag der Embed-Seite
                        if not show_name:
                            title_match = re.search(
                                r"<title>(.*?)</title>", html, re.DOTALL
                            )
                            if title_match:
                                page_title = title_match.group(1).strip()
                                if " | " in page_title:
                                    show_name = page_title.split(" | ")[-1].strip()
                                    self.logger.debug(
                                        f"   📻 Show aus HTML <title>: {show_name}"
                                    )

                        if show_name:
                            # Bereinigung: "Show-Name - Zusatz" → "Show-Name"
                            if " - " in show_name:
                                original = show_name
                                show_name = show_name.split(" - ")[0].strip()
                                self.logger.debug(
                                    f"   🧹 Bereinigt: '{original}' → '{show_name}'"
                                )

                            self.logger.info(f"   📻 Podcast: {show_name}")
                            self.logger.info(f"   🎙️ Episode: {episode_name}")

                            # Artist-Map Normalisierung
                            if self.artist_map:
                                try:
                                    normalized = self.artist_map.normalize(show_name)
                                    if normalized and normalized != show_name:
                                        self.logger.info(
                                            f"   🔄 Normalisiert: '{show_name}' → '{normalized}'"
                                        )
                                        show_name = normalized
                                except Exception as e:
                                    self.logger.debug(
                                        f"   ⚠️ Normalisierung fehlgeschlagen: {e}"
                                    )

                            # Release-Datum
                            release_date = entity.get("releaseDate", {})
                            year = ""
                            if release_date:
                                iso_string = release_date.get("isoString", "")
                                if iso_string:
                                    year = str(iso_string)[:4]
                                    self.logger.debug(f"   📅 Jahr: {year}")

                            return {
                                "title": episode_name,
                                "artist": show_name,
                                "album": show_name,
                                "year": year,
                                "type": "episode",
                                "show_name": show_name,
                                "episode_name": episode_name,
                                "cover_url": cover_url,
                            }
                        else:
                            self.logger.warning(
                                "   ⚠️ Kein Show-Name in Embed-API gefunden"
                            )
                    else:
                        # Musik-Track
                        title = entity.get("name", "Unknown Title")
                        artists = entity.get("artists", [])
                        artist_names = [
                            a.get("name", "Unknown Artist") for a in artists
                        ]
                        artist_str = (
                            ", ".join(artist_names)
                            if artist_names
                            else "Unknown Artist"
                        )
                        album_name = entity.get("album", {}).get(
                            "name", "Spotify Single"
                        )

                        release_date = entity.get("releaseDate", {})
                        year = ""
                        if release_date:
                            iso_string = release_date.get("isoString", "")
                            if iso_string:
                                year = str(iso_string)[:4]

                        self.logger.info(f"   🎵 Titel: {title}")
                        self.logger.info(f"   👤 Artist: {artist_str}")
                        self.logger.info(f"   💿 Album: {album_name}")

                        return {
                            "title": title,
                            "artist": artist_str,
                            "album": album_name,
                            "year": year,
                            "type": "track",
                            "cover_url": cover_url,
                        }
                else:
                    self.logger.warning("   ⚠️ Kein Entity in __NEXT_DATA__ gefunden")
            else:
                self.logger.warning("   ⚠️ __NEXT_DATA__ JSON nicht gefunden")

        except Exception as e:
            self.logger.warning(
                f"   ⚠️ Embed-API fehlgeschlagen: {type(e).__name__}: {e}"
            )

        # ===== METHODE 2: oEmbed-API (FALLBACK - nur für Titel) =====
        oembed_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/{content_type}/{spotify_id}"
        oembed_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        try:
            self.logger.debug(f"   🔄 Fallback: oEmbed-API: {oembed_url}")

            def _fetch_oembed():
                req = Request(oembed_url, headers=oembed_headers)
                with urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            oembed_data = await loop.run_in_executor(None, _fetch_oembed)
            title = oembed_data.get("title", "Unknown")
            thumbnail_url = oembed_data.get("thumbnail_url")

            self.logger.debug(f"   ✅ oEmbed-Daten: title='{title}'")

            if content_type == "episode":
                # oEmbed liefert KEINEN Show-Namen
                self.logger.warning("   ⚠️ oEmbed liefert keinen Show-Namen")
                return {
                    "title": title,
                    "artist": "Unknown Podcast",
                    "album": "Unknown Podcast",
                    "year": "",
                    "type": "episode",
                    "show_name": "Unknown Podcast",
                    "episode_name": title,
                    "cover_url": thumbnail_url,
                }
            else:
                if " - " in title:
                    artist_str, track_title = title.split(" - ", 1)
                else:
                    artist_str = "Unknown Artist"
                    track_title = title

                return {
                    "title": track_title.strip(),
                    "artist": artist_str.strip(),
                    "album": "Spotify Single",
                    "year": "",
                    "type": "track",
                    "cover_url": thumbnail_url,
                }

        except Exception as e:
            self.logger.error(
                f"   ❌ oEmbed-Fallback fehlgeschlagen: {type(e).__name__}: {e}"
            )

        self.logger.error("   ❌ Alle Metadaten-Quellen erschöpft")
        return None

    async def _download_from_rss_feed(
        self, spotify_show_id: str, episode_name: str
    ) -> Optional[Path]:
        """Lädt Episode direkt vom RSS-Feed (KEIN Premium nötig!)"""
        import feedparser
        from urllib.request import urlretrieve

        feed_info = self.rss_manager.get_feed(spotify_show_id)
        if not feed_info:
            return None

        self.logger.info(f"📡 RSS-Feed gefunden: {feed_info.name}")

        try:
            loop = asyncio.get_event_loop()

            def _parse_and_download():
                feed = feedparser.parse(feed_info.rss_feed)
                episode_name_lower = episode_name.lower().strip()

                for entry in feed.entries:
                    title = entry.get("title", "")
                    if episode_name_lower in title.lower():
                        self.logger.info(f"✅ Episode im RSS-Feed gefunden: {title}")

                        # Audio-URL finden
                        audio_url = None
                        for link in entry.get("links", []):
                            if link.get("type", "").startswith("audio/"):
                                audio_url = link.get("href")
                                break

                        if not audio_url:
                            enclosures = entry.get("enclosures", [])
                            if enclosures:
                                audio_url = enclosures[0].get("href")

                        # Cover-URL aus Feed extrahieren
                        cover_url = None
                        if hasattr(feed.feed, "image"):
                            cover_url = feed.feed.image.get(
                                "href"
                            ) or feed.feed.image.get("url")
                        if not cover_url and hasattr(entry, "itunes_image"):
                            cover_url = entry.itunes_image.get("href")

                        if audio_url:
                            safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)
                            output_file = self.download_dir / f"{safe_title}.mp3"
                            urlretrieve(audio_url, output_file)

                            # Cover downloaden wenn vorhanden
                            cover_data = None
                            if cover_url:
                                try:
                                    req = Request(
                                        cover_url, headers={"User-Agent": "Mozilla/5.0"}
                                    )
                                    with urlopen(req, timeout=10) as resp:
                                        cover_data = resp.read()
                                except:
                                    pass

                            return output_file, cover_data, title

                return None, None, None

            result = await loop.run_in_executor(None, _parse_and_download)

            if result and result[0]:
                self._cached_cover = result[1]  # Cover für später speichern
                self._cached_rss_title = result[2]
                return result[0]

        except Exception as e:
            self.logger.warning(f"⚠️ RSS-Feed Download fehlgeschlagen: {e}")

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # DOWNLOAD
    # ─────────────────────────────────────────────────────────────────────────

    async def _download_via_ytdlp_safe(
        self, meta: Dict[str, Any], original_url: str
    ) -> Dict[str, Any]:
        """Nutzt yt-dlp mit Anti-Block-Parametern für den Audio-Download."""
        import yt_dlp

        self.logger.debug("🎬 [DOWNLOAD] Starte yt-dlp Download...")

        # 🖼️ Cover-Art von Spotify downloaden
        cover_art_data = None
        cover_url = meta.get("cover_url")
        if cover_url:
            try:
                self.logger.info(f"   🖼️ Lade Cover-Art von Spotify...")
                loop = asyncio.get_event_loop()

                def _download_cover():
                    req = Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urlopen(req, timeout=10) as resp:
                        return resp.read()

                cover_art_data = await loop.run_in_executor(None, _download_cover)
                self.logger.info(
                    f"   ✅ Cover-Art geladen ({len(cover_art_data)} bytes)"
                )
            except Exception as e:
                self.logger.warning(f"   ⚠️ Cover-Art Download fehlgeschlagen: {e}")

        # Suchquery je nach Content-Type
        if meta.get("type") == "episode":
            show_name = meta.get("show_name", "")
            episode_name = meta.get("episode_name", "")

            search_queries = [
                f"ytsearch1:{show_name} {episode_name} podcast",
                f"ytsearch1:{episode_name} podcast",
                f"ytsearch1:{show_name} podcast episode",
                f"ytsearch1:{episode_name}",
            ]

            self.logger.info(f"   🔍 Podcast-Suche: '{show_name}' / '{episode_name}'")

            info = None
            loop = asyncio.get_event_loop()

            for i, search_query in enumerate(search_queries, 1):
                self.logger.debug(f"      Strategie {i}: {search_query}")

                try:

                    def _do_search():
                        with yt_dlp.YoutubeDL(
                            self._get_ydl_opts(download=False)
                        ) as ydl:
                            return ydl.extract_info(search_query, download=False)

                    info = await loop.run_in_executor(None, _do_search)

                    if info and "entries" in info and len(info["entries"]) > 0:
                        entry = info["entries"][0]
                        video_title = entry.get("title", "")
                        video_duration = entry.get("duration", 0)
                        video_uploader = entry.get("uploader", "")

                        self.logger.debug(f"      📺 Video: {video_title[:50]}...")
                        self.logger.debug(f"      ⏱️ Dauer: {video_duration//60}min")
                        self.logger.debug(f"      📤 Uploader: {video_uploader}")

                        is_likely_podcast = False

                        if video_duration and video_duration > 600:
                            is_likely_podcast = True
                        if show_name and show_name.lower() in video_uploader.lower():
                            is_likely_podcast = True
                        if show_name and any(
                            word.lower() in video_title.lower()
                            for word in show_name.lower().split()
                            if len(word) > 3
                        ):
                            is_likely_podcast = True

                        if is_likely_podcast:
                            self.logger.info(f"      ✅ Passendes Video gefunden!")
                            break
                        else:
                            self.logger.debug(f"      ⏭️ Video scheint kein Podcast")
                            info = None

                except Exception as e:
                    self.logger.debug(
                        f"      ⚠️ Strategie {i} fehlgeschlagen: {type(e).__name__}"
                    )
                    continue

            if not info:
                self.logger.error(
                    "   ❌ Keine passende Podcast-Episode auf YouTube gefunden"
                )
                return {
                    "success": False,
                    "error": "Keine passende Podcast-Episode auf YouTube gefunden.",
                }

            self.logger.info(f"   🎬 Starte YouTube-Download...")

            def _do_download():
                with yt_dlp.YoutubeDL(self._get_ydl_opts(download=True)) as ydl:
                    return ydl.extract_info(
                        info["entries"][0]["webpage_url"], download=True
                    )

            download_info = await loop.run_in_executor(None, _do_download)

        else:
            search_query = f"ytsearch1:{meta['artist']} - {meta['title']} audio"
            self.logger.info(f"   🔍 Musik-Suche: {search_query}")

            loop = asyncio.get_event_loop()

            def _do_dl():
                with yt_dlp.YoutubeDL(self._get_ydl_opts(download=True)) as ydl:
                    return ydl.extract_info(search_query, download=True)

            download_info = await loop.run_in_executor(None, _do_dl)

        # Erfolg prüfen und Datei finden
        if download_info:
            # BUG-004-Fix: die heruntergeladene Datei wurde vorher über
            # "neueste Datei im gesamten download_dir" ermittelt - dieses
            # Verzeichnis ist identisch mit Config.DOWNLOAD_DIR, das AUCH
            # von der regulären YouTube-Download-Pipeline genutzt wird
            # (Config.SPOTIFY_DOWNLOAD_DIR existiert zwar, wurde aber nie
            # angebunden). Bei mehreren gleichzeitigen Downloads
            # (MAX_CONCURRENT_DOWNLOADS erlaubt das explizit) konnte so die
            # Datei eines PARALLEL laufenden, fremden Downloads
            # fälschlicherweise als "die eigene" erkannt werden - falscher
            # Audio-Inhalt unter falschen Metadaten. yt-dlp liefert den
            # tatsächlichen, nach Postprocessing (FFmpegExtractAudio)
            # korrigierten Pfad zuverlässig über download_info["filepath"].
            downloaded_path = download_info.get("filepath") or download_info.get(
                "_filename"
            )
            downloaded_file = Path(downloaded_path) if downloaded_path else None
            if not (downloaded_file and downloaded_file.exists()):
                # Defensiver Fallback, falls yt-dlp ausnahmsweise keinen
                # Pfad liefert - alte, unsichere Methode bleibt als
                # letzter Ausweg erhalten statt komplett zu entfallen.
                files = sorted(
                    [f for f in self.download_dir.glob("*") if f.is_file()],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                downloaded_file = files[0] if files else None

            if downloaded_file:
                self.logger.info(
                    f"   📁 Heruntergeladene Datei: {downloaded_file.name}"
                )

                is_podcast = meta.get("type") == "episode"
                podcast_name = meta.get("show_name", "")

                if is_podcast and podcast_name and podcast_name != "Unknown Podcast":
                    self.logger.info(f"   📻 Podcast-Modus: '{podcast_name}'")
                    artist_name = podcast_name
                    album_name = podcast_name
                    channel_name = podcast_name
                    uploader = podcast_name
                else:
                    artist_name = meta["artist"]
                    album_name = meta.get("album", "")
                    channel_name = ""
                    uploader = ""

                    if is_podcast:
                        self.logger.warning("   ⚠️ Podcast-Name ist 'Unknown Podcast'")

                track_info = {
                    "success": True,
                    "filepath": str(downloaded_file),
                    "title": meta["title"],
                    "artist": artist_name,
                    "album": album_name,
                    "year": meta.get("year", ""),
                    "source": "spotify_no_api_embed",
                    "original_url": original_url,
                    "content_type": meta.get("type", "track"),
                    "is_podcast": is_podcast,
                    "podcast_name": podcast_name,
                    "channel_name": channel_name,
                    "uploader": uploader,
                    "spotify_content_type": meta.get("type", "track"),
                    "cover_art": cover_art_data,
                }

                self.logger.info("   ✅ Download erfolgreich!")
                self.logger.info(f"      🎤 Artist:  {artist_name}")
                self.logger.info(f"      🎵 Titel:   {meta['title']}")
                self.logger.info(
                    f"      🖼️ Cover:   {'Ja' if cover_art_data else 'Nein'}"
                )

                return {
                    "success": True,
                    "type": "single",
                    "track_info": track_info,
                    "processor_instance": None,
                }

        self.logger.error("   ❌ YouTube konnte keinen passenden Audio-Stream finden")
        return {
            "success": False,
            "error": "YouTube konnte keinen passenden Audio-Stream finden.",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # HAUPTMETHODE
    # ─────────────────────────────────────────────────────────────────────────

    async def download(self, url: str) -> Dict[str, Any]:
        """
        Hauptmethode für den Download.

        Unterstützt:
        - Track URLs (Musik)
        - Episode URLs (Podcast)
        - Show URLs (wird auf erste Episode gemappt)
        """
        self.logger.info("=" * 70)
        self.logger.info("🎵 [SPOTIFY] 📥 DOWNLOAD GESTARTET")
        self.logger.info(f"   🔗 URL: {url}")
        self.logger.info("=" * 70)

        original_url = url
        url = _sanitize_spotify_url(url)
        self.logger.debug(f"🧹 URL bereinigt: {url}")

        # Schritt 1: Kurzlinks auflösen
        needs_resolution = any(
            domain in url for domain in ["spotify.link", "spoti.fi"]
        ) or not re.search(r"/(track|album|playlist|episode|show)/", url)

        if needs_resolution:
            self.logger.info("🔗 [1/6] Prüfe Weiterleitungen...")
            try:
                loop = asyncio.get_event_loop()

                def _resolve():
                    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urlopen(req, timeout=10) as resp:
                        return resp.geturl()

                resolved_url = await loop.run_in_executor(None, _resolve)
                if resolved_url != url:
                    self.logger.info(f"   ✅ Aufgelöst: {resolved_url}")
                    url = _sanitize_spotify_url(resolved_url)
                else:
                    self.logger.debug("   ℹ️ Keine Weiterleitung")
            except Exception as e:
                self.logger.warning(f"   ⚠️ Auflösung fehlgeschlagen: {e}")

        # Schritt 2: URL-Typ erkennen
        self.logger.info("🏷️ [2/6] URL-Typ analysieren...")
        url_type = _spotify_url_type(url)
        self.logger.info(f"   ✅ Typ: {url_type}")

        # Schritt 3: ID extrahieren
        self.logger.info("🔑 [3/6] Spotify-ID extrahieren...")
        spotify_id = _extract_spotify_id(url)
        if not spotify_id:
            self.logger.error("   ❌ Keine gültige Spotify-ID gefunden")
            return {
                "success": False,
                "error": f"Keine gültige Spotify-ID gefunden in: {url}",
            }
        self.logger.info(f"   ✅ ID: {spotify_id}")

        # Schritt 4: Content-Type bestimmen
        self.logger.info("📋 [4/6] Content-Type bestimmen...")
        if url_type in ["episode", "show"]:
            content_type = "episode"
            self.logger.info("   ✅ Podcast-Episode")
        else:
            content_type = "track"
            self.logger.info("   ✅ Musik-Track")

        # 🆕 PRIORITÄT 1: RSS-Feed Download (wenn verfügbar)
        if url_type == "episode":
            # Metadaten holen (brauchen wir für Show-Name)
            meta = await self._fetch_metadata_no_api(spotify_id, content_type)

            if meta:
                show_name = meta.get("show_name")

                # Versuche Feed über Show-Namen zu finden
                feed = self.rss_manager.get_feed_by_name(show_name)
                if feed:
                    show_id = feed.spotify_show_id
                    self.logger.info(
                        f"📻 [5/6] RSS-Feed über Namen gefunden: '{show_name}' → {show_id}"
                    )

                    self.logger.info(f"   🎯 Versuche direkten RSS-Download...")
                    rss_file = await self._download_from_rss_feed(
                        show_id, meta.get("episode_name")
                    )

                    if rss_file:
                        self.logger.info("=" * 70)
                        self.logger.info("✅ [SPOTIFY] RSS-DOWNLOAD ERFOLGREICH")
                        self.logger.info(f"   📁 Datei:   {rss_file.name}")
                        self.logger.info(f"   🎤 Artist:  {meta.get('show_name')}")
                        self.logger.info(f"   🎵 Titel:   {meta.get('title')}")
                        self.logger.info("=" * 70)

                        # 🆕 Processing Stats für RSS-Download
                        rss_response = await self._build_success_response_rss(
                            rss_file, meta, original_url
                        )

                        # 🆕 Stats hinzufügen
                        rss_response["track_info"]["processing_stats"] = {
                            "successful_normalizations": 1,
                            "successful_genre_mappings": 1,
                            "lyrics_found": 0,
                            "youtube_parser_used": 0,
                            "artist_map_parsing_fallback": 0,
                            "cache_hits": 0,
                            "cache_misses": 1,
                            "total_processed": 1,
                            "source": "rss_feed",
                        }

                        # 🆕 Cover aus RSS hinzufügen
                        if hasattr(self, "_cached_cover") and self._cached_cover:
                            rss_response["track_info"]["cover_art"] = self._cached_cover
                            rss_response["track_info"]["cover_embedded"] = False

                        return rss_response
                    else:
                        self.logger.info(
                            "   📡 Kein RSS-Treffer, fallback zu YouTube..."
                        )

                # Speichere Meta für später (falls YouTube-Fallback)
                self._cached_meta = meta
            else:
                self.logger.warning("   ⚠️ Konnte Metadaten nicht laden")

        # Schritt 5: Metadaten laden (für YouTube-Fallback, falls nicht schon geschehen)
        meta = getattr(self, "_cached_meta", None)
        if not meta:
            self.logger.info("📝 [5/6] Metadaten von Spotify laden...")
            meta = await self._fetch_metadata_no_api(spotify_id, content_type)

        if not meta:
            self.logger.error("   ❌ Metadaten konnten nicht geladen werden")
            return {
                "success": False,
                "error": "Konnte Metadaten nicht über die Embed-API laden.",
            }

        self.logger.info("   ✅ Metadaten geladen:")
        if content_type == "episode":
            self.logger.info(f"      📻 Show:  {meta.get('show_name', 'N/A')}")
        else:
            self.logger.info(f"      👤 Artist: {meta.get('artist', 'N/A')}")
        self.logger.info(f"      🎵 Titel:  {meta.get('title', 'N/A')}")
        self.logger.info(f"      📅 Jahr:   {meta.get('year', 'N/A') or 'N/A'}")
        self.logger.info(
            f"      🖼️ Cover:  {'Ja' if meta.get('cover_url') else 'Nein'}"
        )

        # Schritt 6: YouTube-Download
        self.logger.info("🎬 [6/6] YouTube-Download starten...")

        if url_type == "show":
            self.logger.info("   ℹ️ Show-URL: Lade neueste Episode")

        result = await self._download_via_ytdlp_safe(meta, original_url)

        if result.get("success"):
            track_info = result.get("track_info", {})
            self.logger.info("=" * 70)
            self.logger.info("✅ [SPOTIFY] DOWNLOAD ERFOLGREICH ABGESCHLOSSEN")
            self.logger.info(
                f"   📁 Datei:   {Path(track_info.get('filepath', '')).name}"
            )
            self.logger.info(f"   🎤 Artist:  {track_info.get('artist')}")
            self.logger.info(f"   💿 Album:   {track_info.get('album')}")
            self.logger.info(f"   🎵 Titel:   {track_info.get('title')}")
            self.logger.info(
                f"   🖼️ Cover:   {'Ja' if track_info.get('cover_art') else 'Nein'}"
            )
            self.logger.info(
                f"   🎙️ Podcast: {'Ja' if track_info.get('is_podcast') else 'Nein'}"
            )
            self.logger.info("=" * 70)
        else:
            self.logger.error("=" * 70)
            self.logger.error(f"❌ [SPOTIFY] DOWNLOAD FEHLGESCHLAGEN")
            self.logger.error(f"   Fehler: {result.get('error', 'Unbekannter Fehler')}")
            self.logger.error("=" * 70)

        return result

    async def _build_success_response_rss(
        self, file_path: Path, meta: Dict, original_url: str
    ) -> Dict[str, Any]:
        """Baut Erfolgs-Response für RSS-Download"""
        return {
            "success": True,
            "type": "single",
            "track_info": {
                "success": True,
                "filepath": str(file_path),
                "title": meta.get("title", "Unknown"),
                "artist": meta.get("show_name", meta.get("artist", "Unknown")),
                "album": meta.get("show_name", ""),
                "year": meta.get("year", ""),
                "source": "rss_feed",
                "original_url": original_url,
                "is_podcast": True,
                "podcast_name": meta.get("show_name", ""),
                "channel_name": meta.get("show_name", ""),
                "uploader": meta.get("show_name", ""),
                "spotify_content_type": "episode",
            },
            "processor_instance": None,
        }

    def _get_ydl_opts(self, download: bool = True) -> Dict[str, Any]:
        """Erstellt yt-dlp Optionen."""
        out_template = str(self.download_dir / "%(title)s.%(ext)s")

        opts = {
            "format": f"bestaudio[ext={self.audio_format}]/bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "source_address": "0.0.0.0",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "noplaylist": True,
        }

        if download:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.audio_format,
                    "preferredquality": self.audio_quality,
                }
            ]
            opts["postprocessor_args"] = ["-threads", "4"]

        return opts
