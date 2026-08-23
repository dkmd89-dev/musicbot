"""
Regressionstest fuer zwei in Phase 3 gefundene Bugs in der Lyrics-Fallback-
Kette von GeniusClient (services/clients/genius_client.py), siehe
docs/MusicBot_ENGINEERING_BASELINE.md:

1. Tier 2 (Genius-REST-API) und die gesamten Tiers 3+4 (HTML-Scraping,
   lyricsgenius-Bibliothek) liefen frueher in EINEM gemeinsamen try-Block.
   Scheiterte Tier 2 aus irgendeinem Grund (kein GENIUS_ACCESS_TOKEN
   konfiguriert -> self.genius_api ist None -> AttributeError bei
   `None.search_song`; ein Netzwerkfehler; kein Suchtreffer - dort gab es
   sogar ein fruehes `return {}`), brach die GESAMTE Methode sofort ab.
   Tier 3 und Tier 4 sind aber bewusst als UNABHAENGIGE Fallbacks gedacht
   (Tier 4 braucht nicht einmal einen erfolgreichen Tier-2-Treffer) - sie
   wurden trotzdem nie versucht.

2. Tier 4 (_fallback_with_lyricsgenius) las Config.GENIUS_CONFIG["access_token"],
   ein Key, der in GENIUS_CONFIG (config.py) gar nicht existiert (nur
   timeout/max_retries/...) - jeder Aufruf loeste einen KeyError aus, der
   lokal verschluckt wurde. Tier 4 war dadurch IMMER tot, unabhaengig davon,
   ob ein gueltiger GENIUS_ACCESS_TOKEN anderswo konfiguriert war.

Fix: Tier 2 in eine eigene Methode (_fetch_via_genius_api) mit eigenem
try/except extrahiert, die bei jedem Fehlschlag ("", "", {}) zurueckgibt statt
zu propagieren oder fruehzeitig zurueckzukehren. Tier 4 nutzt jetzt
self.genius_access_token (= Config.GENIUS_ACCESS_TOKEN, denselben Token wie
Tier 2) statt des nicht existierenden Config-Keys.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.clients.genius_client import GeniusClient
from utils.lyrics_cache import LyricsCache


def make_client(tmp_path, genius_api=None, genius_access_token=""):
    """Konstruiert einen GeniusClient ohne den echten __init__ zu durchlaufen
    (der wuerde ueber get_config() reale, konfigurierte Verzeichnisse
    anfassen) - nur die fuer die Fallback-Kette relevanten Attribute werden
    gesetzt."""
    client = object.__new__(GeniusClient)
    client.logger = MagicMock()
    client.genius_api = genius_api
    client.genius_access_token = genius_access_token
    client.lyrics_cache = LyricsCache(cache_dir=tmp_path)
    client.processed_files = 0
    client.failed_files = 0
    return client


class TestFetchViaGeniusApiIsolation:
    """Bug 1: Tier 2 darf Tier 3/4 nicht durch einen Fehlschlag verhindern."""

    def test_returns_empty_tuple_when_no_genius_api_configured(self, tmp_path):
        client = make_client(tmp_path, genius_api=None)

        result = asyncio.run(
            client._fetch_via_genius_api("Some Song", "Some Artist", "query")
        )

        assert result == ("", "", {})

    def test_returns_empty_tuple_when_fetch_with_retry_raises(self, tmp_path):
        client = make_client(tmp_path, genius_api=MagicMock())
        client._fetch_with_retry = AsyncMock(side_effect=RuntimeError("boom"))

        result = asyncio.run(
            client._fetch_via_genius_api("Some Song", "Some Artist", "query")
        )

        assert result == ("", "", {})

    def test_returns_empty_tuple_when_no_search_match_found(self, tmp_path):
        client = make_client(tmp_path, genius_api=MagicMock())

        async def fake_fetch_with_retry(func, *args, **kwargs):
            # search_song() -> kein Treffer, search_songs() -> keine hits
            if "search_songs" in str(func):
                return {"hits": []}
            return None

        client._fetch_with_retry = fake_fetch_with_retry

        result = asyncio.run(
            client._fetch_via_genius_api("Some Song", "Some Artist", "query")
        )

        assert result == ("", "", {})


class TestFetchLyricsFallsThroughToTier4:
    """
    End-to-End-Beweis: process_single_track()-relevanter Pfad
    (fetch_metadata -> _fetch_lyrics) erreicht jetzt tatsaechlich Tier 4,
    wenn Tier 2 nicht verfuegbar ist - vorher haette dieser Fall sofort
    ein leeres Dict zurueckgegeben, ohne Tier 3/4 ueberhaupt zu versuchen.
    """

    def test_no_genius_api_still_reaches_lyricsgenius_fallback(self, tmp_path):
        client = make_client(tmp_path, genius_api=None, genius_access_token="fake-token")

        # _is_valid_lyrics() verlangt mindestens 40 Zeichen.
        fake_lyrics = "La la la, this is a sufficiently long lyrics fallback text."
        client._fallback_with_lyricsgenius = MagicMock(return_value=fake_lyrics)

        result = asyncio.run(client.fetch_metadata("Some Song", "Some Artist"))

        client._fallback_with_lyricsgenius.assert_called_once()
        assert result.get("lyrics") == fake_lyrics


class TestFallbackWithLyricsgeniusUsesCorrectToken:
    """Bug 2: Tier 4 las einen nicht existierenden Config-Key."""

    def test_skips_gracefully_without_access_token(self, tmp_path):
        client = make_client(tmp_path, genius_access_token="")

        result = client._fallback_with_lyricsgenius("Some Song", "Some Artist")

        assert result == ""

    def test_uses_genius_access_token_not_missing_config_key(self, tmp_path, monkeypatch):
        client = make_client(tmp_path, genius_access_token="real-token-value")

        captured_token = {}

        class FakeLyricsGenius:
            def __init__(self, token, **kwargs):
                captured_token["token"] = token

            def search_song(self, title, artist):
                fake_song = MagicMock()
                fake_song.lyrics = "Fake lyrics content"
                return fake_song

        monkeypatch.setattr(
            "services.clients.genius_client.LyricsGenius", FakeLyricsGenius
        )

        result = client._fallback_with_lyricsgenius("Some Song", "Some Artist")

        assert captured_token["token"] == "real-token-value"
        assert result == "Fake lyrics content"
