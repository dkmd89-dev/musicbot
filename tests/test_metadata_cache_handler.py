"""
Tests fuer MetadataCacheHandler (services/downloader/utils/metadata/cache.py).

TEST-003 (siehe docs/MusicBot_ENGINEERING_BASELINE.md): check() und
_normalize_cache_title() waren seit dem allerersten Commit reine Stubs
(Methodenrumpf nur "..."), gaben also immer None zurueck. Der Cache-Hit-Pfad
der Metadata-Pipeline war dadurch in Produktion vollstaendig wirkungslos -
jeder Track durchlief immer die volle Pipeline inkl. externer API-Calls.
In Phase 1 wurde das bewusst nur charakterisiert; check() ist jetzt (Phase 2,
Fortsetzung) implementiert.

Design: check() wird VOR der Artist-/Titel-Bereinigung aufgerufen (nur rohe
track_metadata), store() speichert NACH der Bereinigung unter dem finalen
Artist/Titel - ein direkter Artist::Titel-Lookup aus rohen Daten wuerde
praktisch nie treffen. check()/store() nutzen daher zusaetzlich einen
video_id-Index (track_metadata["id"], stabil ueber Roh- und Bereinigungs-
Phase hinweg) als Zwischenschluessel. _normalize_cache_title() bleibt
bewusst ein Stub (store()s bestehender .lower().strip()-Fallback reicht).

store() und invalidate() sind NICHT gestubbt und werden hier gegen die echte
zugrunde liegende utils.metadata_cache.MetadataCache getestet.
"""

from pathlib import Path

import pytest

from services.downloader.utils.metadata.cache import MetadataCacheHandler
from services.downloader.utils.metadata.models import MetadataResult
from utils.metadata_cache import MetadataCache


@pytest.fixture
def base_cache(tmp_path):
    return MetadataCache(cache_dir=tmp_path)


@pytest.fixture
def cache_handler(base_cache):
    return MetadataCacheHandler(base_cache)


class TestCheckCacheHitBehavior:
    def test_check_returns_none_on_empty_cache(self, cache_handler):
        result = cache_handler.check(
            track_metadata={"title": "Some Song", "id": "VID123"},
            dominant_artist="Some Artist",
        )
        assert result is None

    def test_check_returns_none_without_video_id(self, cache_handler, base_cache):
        stored = MetadataResult(
            success=True,
            title="Some Song",
            artist="Some Artist",
            original_metadata={"id": "VID123"},
        )
        cache_handler.store(stored, dominant_artist="Some Artist")

        # track_metadata ohne "id" -> kein verlaesslicher Zwischenschluessel
        # moeglich, auch wenn inhaltlich derselbe Track gemeint ist.
        result = cache_handler.check(
            track_metadata={"title": "Some Song", "artist": "Some Artist"},
            dominant_artist="Some Artist",
        )
        assert result is None

    def test_check_returns_none_for_unknown_video_id(self, cache_handler, base_cache):
        stored = MetadataResult(
            success=True,
            title="Some Song",
            artist="Some Artist",
            original_metadata={"id": "VID123"},
        )
        cache_handler.store(stored, dominant_artist="Some Artist")

        result = cache_handler.check(
            track_metadata={"id": "SOME_OTHER_VIDEO_ID"},
            dominant_artist="Some Artist",
        )
        assert result is None

    def test_check_finds_entry_via_video_id_after_store(
        self, cache_handler, base_cache
    ):
        stored = MetadataResult(
            success=True,
            title="Clean Song Title",
            artist="Clean Artist",
            album="Some Album",
            year=2021,
            original_metadata={"id": "VID123"},
        )
        cache_handler.store(stored, dominant_artist="Clean Artist")

        # check() bekommt nur die ROHEN track_metadata, wie sie vor der
        # Artist-/Titel-Bereinigung vorliegen wuerden - Titel/Artist weichen
        # bewusst von den gespeicherten (bereinigten) Werten ab.
        result = cache_handler.check(
            track_metadata={
                "id": "VID123",
                "title": "Clean Artist - Clean Song Title (Official Video)",
                "artist": "Clean Artist - Topic",
            },
            dominant_artist=None,
        )

        assert result is not None
        assert result.from_cache is True
        assert result.title == "Clean Song Title"
        assert result.artist == "Clean Artist"
        assert result.album == "Some Album"
        assert result.year == 2021

    def test_check_returns_none_when_library_file_no_longer_exists(
        self, cache_handler, tmp_path
    ):
        missing_file = tmp_path / "library" / "Clean Artist" / "Song.m4a"
        stored = MetadataResult(
            success=True,
            title="Some Song",
            artist="Some Artist",
            library_path=missing_file,
            original_metadata={"id": "VID123"},
        )
        cache_handler.store(stored, dominant_artist="Some Artist")

        result = cache_handler.check(
            track_metadata={"id": "VID123"}, dominant_artist=None
        )
        assert result is None

    def test_check_hit_when_library_file_exists(self, cache_handler, tmp_path):
        real_file = tmp_path / "Song.m4a"
        real_file.write_bytes(b"fake audio")
        stored = MetadataResult(
            success=True,
            title="Some Song",
            artist="Some Artist",
            library_path=real_file,
            original_metadata={"id": "VID123"},
        )
        cache_handler.store(stored, dominant_artist="Some Artist")

        result = cache_handler.check(
            track_metadata={"id": "VID123"}, dominant_artist=None
        )
        assert result is not None
        assert result.library_path == real_file

    def test_normalize_cache_title_is_still_a_stub(self, cache_handler):
        # Bewusst unangetastet - siehe Modul-Docstring.
        assert cache_handler._normalize_cache_title("Some Song") is None


class TestStore:
    def test_store_persists_entry_in_underlying_cache(self, cache_handler, base_cache):
        result = MetadataResult(
            success=True,
            title="Some Song",
            artist="Some Artist",
            album="Some Album",
            year=2020,
        )

        cache_handler.store(result, dominant_artist="Some Artist")

        # store() nutzt wegen des _normalize_cache_title-Stubs den
        # .lower().strip()-Fallback als tatsaechlichen Cache-Key.
        cached = base_cache.get("some artist", "some song")
        assert cached is not None
        assert cached["title"] == "Some Song"
        assert cached["album"] == "Some Album"
        assert cached["year"] == 2020

    def test_store_skips_unsuccessful_result(self, cache_handler, base_cache):
        result = MetadataResult(success=False, title="Failed Song", artist="Artist")

        cache_handler.store(result, dominant_artist="Artist")

        assert base_cache.get("artist", "failed song") is None

    def test_store_falls_back_to_unknown_artist_when_missing(
        self, cache_handler, base_cache
    ):
        result = MetadataResult(success=True, title="No Artist Song", artist="")

        cache_handler.store(result, dominant_artist=None)

        assert base_cache.get("unknown", "no artist song") is not None


class TestInvalidate:
    def test_invalidate_removes_previously_stored_entry(
        self, cache_handler, base_cache
    ):
        base_cache.store("some artist", "some song", {"title": "Some Song"})
        assert base_cache.get("some artist", "some song") is not None

        cache_handler.invalidate("some artist", "some song")

        assert base_cache.get("some artist", "some song") is None
