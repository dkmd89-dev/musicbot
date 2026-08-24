"""
Unit-Tests für LyricsProcessor
(services/metadata/lyrics_processor.py) — P0-Metadaten-
Sub-Prozessor, vorher 0 Tests. Gefunden über eine systematische
Ungetestet-Prüfung aller Quelldateien gegen tests/-Referenzen.

genius_client (externer Dienst, Genius-API) wird gemockt (Regel 7).
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from services.metadata.lyrics_processor import LyricsProcessor


def make_processor(genius_client=None):
    return LyricsProcessor(genius_client or Mock(), logger=Mock())


class TestFetchLyrics:
    def test_returns_lyrics_and_genius_source_on_success(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(
            return_value={"lyrics": "Some lyrics text"}
        )
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(processor.fetch_lyrics("Artist", "Title"))

        assert lyrics == "Some lyrics text"
        assert source == "genius"
        genius_client.fetch_metadata.assert_called_once_with("Title", "Artist")

    def test_returns_none_tuple_when_genius_data_has_no_lyrics_key(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value={"title": "Title"})
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(processor.fetch_lyrics("Artist", "Title"))

        assert lyrics is None
        assert source is None

    def test_returns_none_tuple_when_genius_data_is_none(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(processor.fetch_lyrics("Artist", "Title"))

        assert lyrics is None
        assert source is None

    def test_returns_none_tuple_when_lyrics_value_is_empty_string(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value={"lyrics": ""})
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(processor.fetch_lyrics("Artist", "Title"))

        assert lyrics is None
        assert source is None

    def test_exception_is_caught_and_returns_none_tuple(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(side_effect=RuntimeError("API down"))
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(processor.fetch_lyrics("Artist", "Title"))

        assert lyrics is None
        assert source is None
        processor.logger.warning.assert_called_once()


class TestFetchLyricsWithFallback:
    def test_main_artist_success_skips_fallback_entirely(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(
            return_value={"lyrics": "Main artist lyrics"}
        )
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=["Feature Artist"]
            )
        )

        assert lyrics == "Main artist lyrics"
        genius_client.fetch_metadata.assert_called_once_with("Title", "Main Artist")

    def test_falls_back_to_feature_artist_when_main_artist_has_no_lyrics(self):
        genius_client = Mock()

        async def fetch_metadata(title, artist):
            if artist == "Feature Artist":
                return {"lyrics": "Feature artist lyrics"}
            return None

        genius_client.fetch_metadata = AsyncMock(side_effect=fetch_metadata)
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=["Feature Artist"]
            )
        )

        assert lyrics == "Feature artist lyrics"
        assert source == "genius"

    def test_tries_multiple_fallback_artists_in_order(self):
        genius_client = Mock()

        async def fetch_metadata(title, artist):
            if artist == "Second Feature":
                return {"lyrics": "Second feature lyrics"}
            return None

        genius_client.fetch_metadata = AsyncMock(side_effect=fetch_metadata)
        processor = make_processor(genius_client)

        lyrics, _ = asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist",
                "Title",
                fallback_artists=["First Feature", "Second Feature"],
            )
        )

        assert lyrics == "Second feature lyrics"
        assert genius_client.fetch_metadata.call_count == 3  # main + 2 fallbacks

    def test_no_lyrics_anywhere_returns_none_tuple(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        lyrics, source = asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=["Feature Artist"]
            )
        )

        assert lyrics is None
        assert source is None

    def test_none_fallback_artists_only_tries_main(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=None
            )
        )

        genius_client.fetch_metadata.assert_called_once_with("Title", "Main Artist")

    def test_empty_fallback_list_only_tries_main(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=[]
            )
        )

        genius_client.fetch_metadata.assert_called_once_with("Title", "Main Artist")

    def test_fallback_artist_identical_to_main_artist_is_skipped(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=["main artist"]
            )
        )

        # Nur der Hauptartist-Versuch, der case-insensitiv identische
        # Fallback-Name wird uebersprungen (kein zweiter API-Aufruf).
        genius_client.fetch_metadata.assert_called_once_with("Title", "Main Artist")

    def test_falsy_fallback_artist_entries_are_skipped(self):
        genius_client = Mock()
        genius_client.fetch_metadata = AsyncMock(return_value=None)
        processor = make_processor(genius_client)

        asyncio.run(
            processor.fetch_lyrics_with_fallback(
                "Main Artist", "Title", fallback_artists=["", None, "  "]
            )
        )

        # "" und None sind falsy -> uebersprungen. "  " ist truthy als String,
        # aber nach .strip() leer -> == "main artist".strip() ist False, also
        # NICHT durch die Identitaets-Pruefung uebersprungen, sondern real
        # versucht (charakterisiert das tatsaechliche Verhalten).
        assert genius_client.fetch_metadata.call_count == 2
