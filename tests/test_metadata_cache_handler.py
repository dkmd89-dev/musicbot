"""
Characterization-Tests fuer MetadataCacheHandler
(services/downloader/utils/metadata/cache.py), Phase 1 Engineering Baseline.

WICHTIGER FUND waehrend der Exploration (siehe docs/MusicBot_ENGINEERING_BASELINE.md,
Risiko CACHE-001): check() und _normalize_cache_title() sind seit dem allerersten
Commit reine Stubs (Methodenrumpf nur "..."), geben also immer None zurueck.
enhanced_metadata_processor.py ruft cache_handler.check() als Cache-Hit-Pruefung
auf (Zeile 223 und 1058) - der Cache-Hit-Pfad der Metadata-Pipeline ist damit
in Produktion vollstaendig wirkungslos, jeder Track durchlaeuft immer die volle
Pipeline inkl. externer API-Calls.

Der Nutzer hat entschieden, dieses Verhalten in Phase 1 nur zu charakterisieren
(einzufrieren), NICHT zu fixen - eine echte Implementierung aendert das
Laufzeitverhalten des Bots spuerbar (weniger externe API-Calls) und braucht
mehr Testabdeckung als hier vorgesehen. Der Fix ist ein offener Punkt fuer eine
spaetere, bewusste Entscheidung.

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


class TestCheckIsCurrentlyAStub:
    """
    Dokumentiert das aktuelle (kaputte) Verhalten: check() gibt IMMER None
    zurueck, unabhaengig davon, ob vorher ein passender Eintrag gespeichert
    wurde. Das ist bewusst KEIN Test fuer "korrektes" Cache-Hit-Verhalten -
    er faengt eine Regression ab, falls sich check() unbemerkt aendert,
    bevor eine bewusste Fix-Entscheidung getroffen wird.
    """

    def test_check_returns_none_on_empty_cache(self, cache_handler):
        result = cache_handler.check(
            track_metadata={"title": "Some Song"}, dominant_artist="Some Artist"
        )
        assert result is None

    def test_check_returns_none_even_after_matching_store(
        self, cache_handler, base_cache
    ):
        stored = MetadataResult(
            success=True, title="Some Song", artist="Some Artist"
        )
        cache_handler.store(stored, dominant_artist="Some Artist")

        # Der zugrunde liegende Cache hat den Eintrag tatsaechlich gespeichert...
        assert base_cache.get("some artist", "some song") is not None

        # ...aber check() ist ein Stub und liefert trotzdem immer None.
        result = cache_handler.check(
            track_metadata={"title": "Some Song", "artist": "Some Artist"},
            dominant_artist="Some Artist",
        )
        assert result is None

    def test_normalize_cache_title_always_returns_none(self, cache_handler):
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
