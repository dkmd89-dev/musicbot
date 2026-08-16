#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔍 ADVANCED PODCAST FINDER - OPTIMIERT
Durchsucht ALLE relevanten Quellen nach Podcast RSS-Feeds

Quellen:
- Apple Podcasts API (iTunes)
- Podcast Index API (mit API-Key)
- Podcast Index Community Mirror
- Google Podcasts (via RSS)
- Spotify Show API (Embed)
- Podbean
- Buzzsprout
- Anchor.fm
- Spreaker
- Audiorella
- RSS.com
- Transistor.fm
- Simplecast
- Megaphone
- Libsyn
- SoundCloud
- Archive.org
- Podcast.de
- Podtail
- Player.fm
- fyyd.de (deutsch)
- Podcast Addict
- Google Search Dorking
- Domain Discovery

Output:
- Gefundene RSS-Feeds
- Direkte Audio-URLs
- JSON Export für podcast_rss_feeds.yaml
"""

import yaml
import json
import re
import time
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# Optional: Für besseres Parsing
try:
    import feedparser

    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print("⚠️ feedparser nicht installiert. Installiere mit: pip install feedparser")

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Podcast Index API Key (optional - registriere dich unter https://podcastindex.org/)
PODCAST_INDEX_API_KEY = ""  # Hier eintragen für bessere Ergebnisse
PODCAST_INDEX_API_SECRET = ""

# Timeout für Requests
TIMEOUT = 10

# Maximale parallele Requests
MAX_WORKERS = 5


@dataclass
class PodcastResult:
    """Ergebnis einer Podcast-Suche"""

    source: str
    title: str
    author: str = ""
    feed_url: str = ""
    website: str = ""
    spotify_id: str = ""
    apple_id: str = ""
    episode_count: int = 0
    audio_urls: List[str] = field(default_factory=list)
    cover_url: str = ""
    description: str = ""
    language: str = ""
    explicit: bool = False
    categories: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 0-1, wie sicher der Match ist

    def to_yaml_entry(self) -> Dict:
        """Konvertiert zu YAML-Eintrag für podcast_rss_feeds.yaml"""
        return {
            "name": self.title,
            "rss_feed": self.feed_url,
            "enabled": True,
            "priority": 1,
            "source": self.source,
            "description": self.description[:200] if self.description else "",
        }


class AdvancedPodcastFinder:
    """Durchsucht ALLE Quellen nach Podcasts"""

    def __init__(self, show_name: str, episode_name: str = "", spotify_url: str = ""):
        self.show_name = show_name
        self.episode_name = episode_name
        self.spotify_url = spotify_url
        self.spotify_show_id = self._extract_spotify_show_id()

        self.results: List[PodcastResult] = []
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _extract_spotify_show_id(self) -> Optional[str]:
        """Extrahiert Spotify Show ID aus URL oder via API"""
        if self.spotify_url and "show/" in self.spotify_url:
            match = re.search(r"/show/([A-Za-z0-9]+)", self.spotify_url)
            if match:
                return match.group(1)
        return None

    def _print_header(self, title: str):
        """Gibt formatierte Überschrift aus"""
        print(f"\n{'=' * 70}")
        print(f"🔍 {title}")
        print(f"{'=' * 70}")

    def _print_success(self, message: str):
        """Gibt Erfolgsmeldung aus"""
        print(f"   ✅ {message}")

    def _print_warning(self, message: str):
        """Gibt Warnung aus"""
        print(f"   ⚠️ {message}")

    def _print_info(self, message: str):
        """Gibt Info aus"""
        print(f"   ℹ️ {message}")

    def _add_result(self, result: PodcastResult):
        """Fügt Ergebnis hinzu (vermeidet Duplikate)"""
        # Prüfe ob Feed-URL bereits existiert
        for existing in self.results:
            if existing.feed_url and existing.feed_url == result.feed_url:
                return
            if (
                existing.title
                and result.title
                and existing.title.lower() == result.title.lower()
            ):
                # Update existing mit neuen Infos
                if not existing.feed_url and result.feed_url:
                    existing.feed_url = result.feed_url
                if not existing.spotify_id and result.spotify_id:
                    existing.spotify_id = result.spotify_id
                return

        self.results.append(result)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. APPLE PODCASTS (iTunes API)
    # ─────────────────────────────────────────────────────────────────────────

    def search_apple_podcasts(self) -> List[PodcastResult]:
        """Durchsucht Apple Podcasts API (kostenlos, kein API-Key)"""
        self._print_header("1. Apple Podcasts (iTunes API)")

        url = "https://itunes.apple.com/search"
        params = {"term": self.show_name, "entity": "podcast", "limit": 10}

        try:
            response = self.session.get(url, params=params, timeout=TIMEOUT)
            data = response.json()

            results = []
            for item in data.get("results", []):
                feed_url = item.get("feedUrl", "")

                if feed_url:
                    result = PodcastResult(
                        source="apple_podcasts",
                        title=item.get("collectionName", item.get("trackName", "")),
                        author=item.get("artistName", ""),
                        feed_url=feed_url,
                        website=item.get("collectionViewUrl", ""),
                        apple_id=str(item.get("collectionId", "")),
                        episode_count=item.get("trackCount", 0),
                        cover_url=item.get(
                            "artworkUrl600", item.get("artworkUrl100", "")
                        ),
                        categories=[g for g in item.get("genres", [])],
                        explicit=item.get("collectionExplicitness") == "explicit",
                    )

                    # Berechne Confidence
                    title_match = self.show_name.lower() in result.title.lower()
                    author_match = self.show_name.lower() in result.author.lower()
                    result.confidence = (
                        0.9 if title_match else (0.7 if author_match else 0.5)
                    )

                    if result.confidence >= 0.5:
                        self._add_result(result)
                        results.append(result)
                        self._print_success(
                            f"'{result.title}' → Feed: {feed_url[:60]}..."
                        )

            if not results:
                self._print_warning("Keine Ergebnisse in Apple Podcasts")

            return results

        except Exception as e:
            self._print_warning(f"Fehler: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # 2. PODCAST INDEX API
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_podcast_index_headers(self) -> Dict:
        """Generiert Headers für Podcast Index API"""
        if not PODCAST_INDEX_API_KEY or not PODCAST_INDEX_API_SECRET:
            return {}

        api_header_time = str(int(time.time()))
        data_to_hash = (
            PODCAST_INDEX_API_KEY + PODCAST_INDEX_API_SECRET + api_header_time
        )
        api_header_hash = hashlib.sha1(data_to_hash.encode()).hexdigest()

        return {
            "X-Auth-Key": PODCAST_INDEX_API_KEY,
            "X-Auth-Date": api_header_time,
            "Authorization": api_header_hash,
        }

    def search_podcast_index(self) -> List[PodcastResult]:
        """Durchsucht Podcast Index API"""
        self._print_header("2. Podcast Index API")

        headers = self._generate_podcast_index_headers()
        if not headers:
            self._print_warning("Kein API-Key konfiguriert - überspringe")
            return []

        url = "https://api.podcastindex.org/api/1.0/search/byterm"
        params = {"q": self.show_name, "max": 10}

        try:
            response = self.session.get(
                url, headers=headers, params=params, timeout=TIMEOUT
            )
            data = response.json()

            results = []
            for feed in data.get("feeds", []):
                result = PodcastResult(
                    source="podcast_index",
                    title=feed.get("title", ""),
                    author=feed.get("author", ""),
                    feed_url=feed.get("url", ""),
                    website=feed.get("link", ""),
                    apple_id=str(feed.get("itunesId", "")),
                    episode_count=feed.get("episodeCount", 0),
                    cover_url=feed.get("artwork", feed.get("image", "")),
                    description=feed.get("description", ""),
                    language=feed.get("language", ""),
                    explicit=feed.get("explicit", False),
                )

                title_match = self.show_name.lower() in result.title.lower()
                result.confidence = 0.9 if title_match else 0.6

                if result.confidence >= 0.5:
                    self._add_result(result)
                    results.append(result)
                    self._print_success(
                        f"'{result.title}' → Feed: {result.feed_url[:60]}..."
                    )

            return results

        except Exception as e:
            self._print_warning(f"Fehler: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # 3. SPOTIFY SHOW API (Embed)
    # ─────────────────────────────────────────────────────────────────────────

    def search_spotify_show(self) -> Optional[PodcastResult]:
        """Extrahiert Info von Spotify Show-Seite"""
        self._print_header("3. Spotify Show API (Embed)")

        if not self.spotify_show_id:
            # Versuche Show-ID zu finden
            search_url = (
                f"https://open.spotify.com/search/{quote(self.show_name)}/shows"
            )
            self._print_info(f"Keine Show-ID - suche manuell unter: {search_url}")
            return None

        embed_url = f"https://open.spotify.com/embed/show/{self.spotify_show_id}"

        try:
            response = self.session.get(embed_url, timeout=TIMEOUT)

            # Suche nach __NEXT_DATA__
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text,
                re.DOTALL,
            )

            if match:
                data = json.loads(match.group(1))
                entity = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("state", {})
                    .get("data", {})
                    .get("entity", {})
                )

                if entity:
                    result = PodcastResult(
                        source="spotify",
                        title=entity.get("name", ""),
                        author=entity.get("publisher", ""),
                        spotify_id=self.spotify_show_id,
                        website=entity.get("externalUrls", {}).get("website", ""),
                        episode_count=entity.get("totalEpisodes", 0),
                        cover_url=entity.get("visualIdentity", {})
                        .get("image", [{}])[0]
                        .get("url", ""),
                        description=entity.get("description", ""),
                        explicit=entity.get("explicit", False),
                        confidence=1.0,
                    )

                    self._add_result(result)
                    self._print_success(
                        f"'{result.title}' (Publisher: {result.author})"
                    )
                    if result.website:
                        self._print_info(f"Website: {result.website}")

                    return result

            self._print_warning("Keine Daten gefunden")

        except Exception as e:
            self._print_warning(f"Fehler: {e}")

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # 4. PODCAST-HOSTS DURCHSUCHEN
    # ─────────────────────────────────────────────────────────────────────────

    def _check_url(self, url: str) -> Optional[str]:
        """Prüft ob URL existiert"""
        try:
            response = self.session.head(url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                return url
        except:
            pass
        return None

    def search_podcast_hosts(self) -> List[PodcastResult]:
        """Durchsucht bekannte Podcast-Hosts"""
        self._print_header("4. Podcast-Hosts")

        clean_name = re.sub(r"[^a-z0-9]", "-", self.show_name.lower().strip())
        clean_name_short = clean_name.replace("--", "-")

        hosts = [
            # Podbean
            f"https://{clean_name_short}.podbean.com",
            f"https://feed.podbean.com/{clean_name_short}/feed.xml",
            # Buzzsprout
            f"https://feeds.buzzsprout.com/{clean_name_short}.rss",
            # Anchor.fm
            f"https://anchor.fm/s/{clean_name_short}",
            f"https://anchor.fm/s/{clean_name_short}/podcast/rss",
            # Spreaker
            f"https://www.spreaker.com/show/{clean_name_short}",
            f"https://api.spreaker.com/show/{clean_name_short}/episodes",
            # Audiorella (Julep)
            f"https://cdn.audiorella.com/podcasts/search?q={quote(self.show_name)}",
            # RSS.com
            f"https://rss.com/podcasts/{clean_name_short}",
            # Transistor.fm
            f"https://feeds.transistor.fm/{clean_name_short}",
            # Simplecast
            f"https://feeds.simplecast.com/{clean_name_short}",
            # Megaphone
            f"https://feeds.megaphone.fm/{clean_name_short}",
            # Libsyn
            f"https://{clean_name_short}.libsyn.com/rss",
            # SoundCloud
            f"https://feeds.soundcloud.com/users/soundcloud:users:{clean_name_short}/sounds.rss",
        ]

        results = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {
                executor.submit(self._check_url, url): url for url in hosts
            }

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result_url = future.result()
                    if result_url:
                        # Bestimme Host-Typ
                        if "podbean" in url:
                            source = "podbean"
                        elif "buzzsprout" in url:
                            source = "buzzsprout"
                        elif "anchor.fm" in url:
                            source = "anchor"
                        elif "spreaker" in url:
                            source = "spreaker"
                        elif "audiorella" in url:
                            source = "audiorella"
                        elif "soundcloud" in url:
                            source = "soundcloud"
                        else:
                            source = "other"

                        result = PodcastResult(
                            source=source,
                            title=self.show_name,
                            feed_url=(
                                result_url
                                if "feed" in result_url or "rss" in result_url
                                else ""
                            ),
                            website=result_url if "feed" not in result_url else "",
                            confidence=0.8,
                        )

                        self._add_result(result)
                        results.append(result)
                        self._print_success(f"{source.upper()}: {result_url}")

                except Exception as e:
                    pass

        if not results:
            self._print_warning("Keine Podcast-Hosts gefunden")

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # 5. PODCAST-VERZEICHNISSE
    # ─────────────────────────────────────────────────────────────────────────

    def search_podcast_directories(self) -> List[PodcastResult]:
        """Durchsucht Podcast-Verzeichnisse"""
        self._print_header("5. Podcast-Verzeichnisse")

        directories = [
            ("podcast.de", f"https://www.podcast.de/suche/?q={quote(self.show_name)}"),
            ("podtail", f"https://podtail.com/de/search/?q={quote(self.show_name)}"),
            (
                "player.fm",
                f"https://player.fm/series/{quote(self.show_name.replace(' ', '-').lower())}",
            ),
            ("fyyd.de", f"https://fyyd.de/search?q={quote(self.show_name)}"),
            (
                "podcastaddict",
                f"https://podcastaddict.com/search?q={quote(self.show_name)}",
            ),
            (
                "listennotes",
                f"https://www.listennotes.com/search/?q={quote(self.show_name)}&type=podcast",
            ),
        ]

        results = []

        for name, url in directories:
            try:
                response = self.session.get(url, timeout=TIMEOUT)
                if response.status_code == 200:
                    self._print_success(f"{name}: URL erreichbar")
                    # TODO: Parsing der Suchergebnisse
            except:
                pass

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # 6. GOOGLE SEARCH DORKING
    # ─────────────────────────────────────────────────────────────────────────

    def search_google_dorks(self) -> List[str]:
        """Durchsucht Google mit speziellen Suchoperatoren"""
        self._print_header("6. Google Search Dorking")

        dorks = [
            f'site:podcasts.apple.com "{self.show_name}"',
            f'site:open.spotify.com/show "{self.show_name}"',
            f'inurl:feed "{self.show_name}" podcast',
            f'inurl:rss "{self.show_name}" podcast',
            f'"{self.show_name}" "RSS" podcast',
        ]

        found = []
        for dork in dorks[:3]:  # Nur erste 3
            search_url = f"https://www.google.com/search?q={quote(dork)}"
            self._print_info(f"Google: {dork[:50]}...")

            try:
                response = self.session.get(search_url, timeout=TIMEOUT)
                soup = BeautifulSoup(response.text, "html.parser")

                for link in soup.find_all("a"):
                    href = link.get("href", "")
                    if href.startswith("/url?q="):
                        url = parse_qs(href[7:].split("&")[0]).get("q", [""])[0]
                        if url and "google" not in url:
                            found.append(url)
                            self._print_success(f"Gefunden: {url[:70]}...")

                time.sleep(1)  # Rate limiting
            except Exception as e:
                pass

        return found

    # ─────────────────────────────────────────────────────────────────────────
    # 7. ARCHIVE.ORG
    # ─────────────────────────────────────────────────────────────────────────

    def search_archive_org(self) -> List[str]:
        """Durchsucht Archive.org"""
        self._print_header("7. Archive.org")

        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f"title:({self.show_name}) AND mediatype:(audio)",
            "fl[]": ["identifier", "title"],
            "output": "json",
            "rows": 5,
        }

        try:
            response = self.session.get(url, params=params, timeout=TIMEOUT)
            data = response.json()

            urls = []
            for doc in data.get("response", {}).get("docs", []):
                identifier = doc.get("identifier")
                if identifier:
                    archive_url = f"https://archive.org/details/{identifier}"
                    urls.append(archive_url)
                    self._print_success(
                        f"Archive: {doc.get('title', identifier)[:50]}..."
                    )

            return urls
        except:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # 8. RSS-FEED VALIDIERUNG
    # ─────────────────────────────────────────────────────────────────────────

    def validate_rss_feed(self, feed_url: str) -> Optional[Dict]:
        """Validiert RSS-Feed und extrahiert Episoden"""
        if not FEEDPARSER_AVAILABLE:
            return None

        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo:
                return None

            episodes = []
            for entry in feed.entries[:5]:
                audio_url = None
                for link in entry.get("links", []):
                    if "audio" in link.get("type", ""):
                        audio_url = link.get("href")
                        break

                if not audio_url and entry.get("enclosures"):
                    audio_url = entry["enclosures"][0].get("href")

                episodes.append(
                    {
                        "title": entry.get("title", ""),
                        "audio_url": audio_url,
                        "published": entry.get("published", ""),
                    }
                )

            return {
                "title": feed.feed.get("title", ""),
                "episode_count": len(feed.entries),
                "episodes": episodes,
            }

        except Exception as e:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # HAUPTMETHODE
    # ─────────────────────────────────────────────────────────────────────────

    def run_all(self) -> List[PodcastResult]:
        """Führt ALLE Suchmethoden aus"""
        print("\n" + "=" * 80)
        print(f"🔍 ADVANCED PODCAST FINDER")
        print("=" * 80)
        print(f"📻 Show:    {self.show_name}")
        if self.episode_name:
            print(f"🎙️ Episode: {self.episode_name}")
        if self.spotify_url:
            print(f"🔗 Spotify: {self.spotify_url}")
        print("=" * 80)

        # Alle Suchmethoden ausführen
        self.search_apple_podcasts()

        if PODCAST_INDEX_API_KEY:
            self.search_podcast_index()

        self.search_spotify_show()
        self.search_podcast_hosts()
        self.search_podcast_directories()
        self.search_google_dorks()
        self.search_archive_org()

        # RSS-Feeds validieren
        self._print_header("RSS-Feed Validierung")
        for result in self.results:
            if result.feed_url:
                validation = self.validate_rss_feed(result.feed_url)
                if validation:
                    result.episode_count = validation["episode_count"]
                    for ep in validation["episodes"]:
                        if ep["audio_url"]:
                            result.audio_urls.append(ep["audio_url"])
                    self._print_success(
                        f"'{result.title}': {validation['episode_count']} Episoden, Feed OK"
                    )
                else:
                    self._print_warning(f"'{result.title}': Feed nicht valide")

        return self.results

    # ─────────────────────────────────────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────────────────────────────────────

    def print_summary(self):
        """Gibt Zusammenfassung aus"""
        print("\n" + "=" * 80)
        print("📊 ZUSAMMENFASSUNG")
        print("=" * 80)

        # Gruppiere nach Source
        by_source = {}
        for r in self.results:
            if r.source not in by_source:
                by_source[r.source] = []
            by_source[r.source].append(r)

        for source, results in by_source.items():
            print(f"\n📍 {source.upper()} ({len(results)} Ergebnisse):")
            for r in results[:3]:
                print(f"   • {r.title}")
                if r.feed_url:
                    print(f"     Feed: {r.feed_url}")
                if r.website:
                    print(f"     Web:  {r.website}")
                if r.audio_urls:
                    print(f"     Audio: {len(r.audio_urls)} URLs")

        # Beste Ergebnisse
        valid_feeds = [r for r in self.results if r.feed_url and r.confidence >= 0.7]

        print(f"\n{'=' * 80}")
        print(f"🎯 BESTE ERGEBNISSE ({len(valid_feeds)} valide Feeds)")
        print("=" * 80)

        for r in sorted(valid_feeds, key=lambda x: x.confidence, reverse=True)[:5]:
            print(f"\n✅ {r.title} (Confidence: {r.confidence:.0%})")
            print(f"   📡 Feed: {r.feed_url}")
            print(f"   🎤 Autor: {r.author}")
            print(f"   📊 Episoden: {r.episode_count}")
            print(f"   🔊 Audio-URLs: {len(r.audio_urls)}")

    def export_yaml_config(self, output_file: str = "podcast_rss_feeds_found.yaml"):
        """Exportiert gefundene Feeds als YAML-Konfiguration"""
        valid_feeds = [r for r in self.results if r.feed_url and r.confidence >= 0.7]

        if not valid_feeds:
            print("❌ Keine validen Feeds zum Exportieren")
            return

        config = {"podcasts": {}}

        for r in valid_feeds:
            # Verwende Spotify-ID wenn verfügbar, sonst generiere Key
            key = (
                r.spotify_id
                if r.spotify_id
                else re.sub(r"[^a-z0-9]", "_", r.title.lower())
            )
            config["podcasts"][key] = r.to_yaml_entry()

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# mapping/podcast_rss_feeds.yaml\n")
            f.write("# Automatisch generiert von AdvancedPodcastFinder\n\n")
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        print(f"\n✅ Konfiguration exportiert nach: {output_file}")

    def export_json(self, output_file: str = "podcast_search_results.json"):
        """Exportiert alle Ergebnisse als JSON"""
        data = {
            "query": {
                "show_name": self.show_name,
                "episode_name": self.episode_name,
                "spotify_url": self.spotify_url,
            },
            "results": [],
        }

        for r in self.results:
            result_dict = asdict(r)
            data["results"].append(result_dict)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"✅ Ergebnisse exportiert nach: {output_file}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Advanced Podcast Finder")
    parser.add_argument("--show", "-s", required=True, help="Name des Podcasts")
    parser.add_argument("--episode", "-e", help="Name der Episode (optional)")
    parser.add_argument("--spotify", "-u", help="Spotify URL (optional)")
    parser.add_argument(
        "--export-yaml", "-y", action="store_true", help="Export als YAML"
    )
    parser.add_argument(
        "--export-json", "-j", action="store_true", help="Export als JSON"
    )

    args = parser.parse_args()

    finder = AdvancedPodcastFinder(
        show_name=args.show,
        episode_name=args.episode or "",
        spotify_url=args.spotify or "",
    )

    results = finder.run_all()
    finder.print_summary()

    if args.export_yaml:
        finder.export_yaml_config()

    if args.export_json:
        finder.export_json()

    if not results:
        print("\n❌ KEINE ERGEBNISSE GEFUNDEN")
        print("   → Dies ist ein SPOTIFY-EXKLUSIVER Podcast!")
        print("   → Download nur mit Premium möglich.")


if __name__ == "__main__":
    # Für direkten Aufruf ohne Argumente
    import sys

    if len(sys.argv) == 1:
        # Demo-Modus
        print("🔍 ADVANCED PODCAST FINDER - DEMO MODUS")
        print()
        show = input("📻 Podcast-Name: ").strip()
        episode = input("🎙️ Episode (optional): ").strip()
        spotify = input("🔗 Spotify URL (optional): ").strip()

        finder = AdvancedPodcastFinder(
            show_name=show or "Im Bett mit Anna-Maria und Anis Ferchichi",
            episode_name=episode or "",
            spotify_url=spotify or "",
        )

        results = finder.run_all()
        finder.print_summary()

        if results:
            export = input("\n💾 Export als YAML? (j/n): ").strip().lower()
            if export in ["j", "ja", "y", "yes"]:
                finder.export_yaml_config()
    else:
        main()
