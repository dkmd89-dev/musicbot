"""
ARCH-022 — Charakterisierung: einmal LEARNED/CONFIRMED gelernte Genre-
Eintraege werden nie wieder mit frischen Last.fm-Daten abgeglichen.

Live-Fund 2026-09-02/03 (Nutzer-Report): Last.fm liefert fuer Artist
"Toobrokeforfiji" heute 8 Tags (rap, hip-hop, hiphop, hip hop, berlin
rap, deutschrap, chill rap, boloboys). Der heutige prioritize_genres()-
Code wuerde daraus primary=Deutschrap, secondary=[Hip Hop] ableiten -
aber der gespeicherte Bestandseintrag in mapping/auto_learned_genre.yaml
hat secondary=[] und wird nie aktualisiert.

Root Cause, im Code verifiziert: Sobald ein Genre-Eintrag LEARNED wird
(>= 2 Beobachtungen, services/metadata/auto_learn.py::_confidence_tier()),
landet er ueber utils/genre_map.py::GenreMapper (Zeile 255-269) in
GenreMapper.artist_map - derselben Struktur wie manuell gepflegte
Eintraege aus artist_genre.yaml. GenreProcessor.determine_genre_with_
fallbacks() findet ihn dann in Schritt 1 als "Manuelles Genre"
(services/metadata/genre_processor.py:99-110), setzt
auto_learn_disabled=True.

Praezisierung waehrend der Testentwicklung (Pre-Fix-Diskriminierung
deckte eine zu pauschale Erst-Annahme auf): MusicBrainz WIRD bei jedem
Aufruf erreicht, auch bei bereits bekanntem Genre - siehe
genre_processor.py:141 "MusicBrainz - IMMER fuer IDs". Das
MusicBrainz-GENRE-Ergebnis wird dabei aber verworfen, nur die mb_ids
werden dem bekannten Ergebnis angehaengt (genre_processor.py:157-164).
Last.fm (genre_processor.py:174-187, die eigentliche Quelle frischerer
Tags im Toobrokeforfiji-Fall) wird dagegen NIE erreicht, sobald
known_result (aus Schritt 1 Manuell oder Schritt 2 Lokal) bereits
gesetzt ist - der fruehe `return known_result` (Zeile 164) ist die
tatsaechliche Ursache dafuer, dass frischere Last.fm-Tags nie
uebernommen werden. enhanced_metadata_processor.py:1009-1014 prueft
zusaetzlich auto_learn_disabled und ruft learn_genre() dann gar nicht
mehr auf - auch ohne den Last.fm-Aufruf wuerde also keine neue
Beobachtung gespeichert.

Dieser Test dokumentiert das AKTUELLE (als unerwuenscht erkannte)
Verhalten bewusst - kein Fix in dieser Phase. Nutzer-Entscheidung
(ARCH-022): Revalidierung bleibt bewusst nur manuell ueber
scripts/reprocess_artist_metadata.py, kein automatisches Zeit-/
Zaehler-Verhalten im kritischen Download-Pfad.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.metadata.auto_learn import AutoLearnManager
from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from services.metadata.genre_processor import GenreProcessor
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.audio_enhancer import AudioEnhancer
from utils.genre_map import GenreMapper
from utils.singleton import SingletonMixin


def _genre_info(primary, secondary=None, source="lastfm"):
    return SimpleNamespace(
        primary=primary, secondary=list(secondary or []), source=source, raw_tags=[]
    )


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


def _make_manager(mapping_dir: Path) -> AutoLearnManager:
    """Identisches Setup-Muster wie
    tests/test_auto_learn_genre_confidence_audit.py::_make_manager()."""
    config = _Config(mapping_dir)
    artist_config = ArtistConfig(
        library_dir=mapping_dir.parent / "library",
        override_file=mapping_dir / "artist_overrides.json",
        mapping_dir=mapping_dir,
    )
    artist_normalizer = ArtistNormalizer(artist_config)
    genre_mapper = GenreMapper(mapping_dir=mapping_dir)
    return AutoLearnManager(
        config=config, artist_normalizer=artist_normalizer, genre_mapper=genre_mapper
    )


def _run(coro):
    return asyncio.run(coro)


class CountingClient:
    """Zaehlt fetch_metadata()-Aufrufe - Beweis, dass ein externer
    Client bei bereits bekanntem Genre NIE erreicht wird."""

    def __init__(self, response=None):
        self._response = response or {}
        self.call_count = 0

    async def fetch_metadata(self, *args, **kwargs):
        self.call_count += 1
        return self._response


class TestLearnedAndConfirmedShortCircuitAllFallbacks:
    """Kern-Charakterisierung: bereits ab LEARNED (nicht erst CONFIRMED)
    wird determine_genre_with_fallbacks() nie mehr bis zu MusicBrainz/
    Last.fm vordringen - unabhaengig davon, wie viele frische Tags dort
    verfuegbar waeren."""

    ARTIST = "TEST_REVALIDATION_ARTIST"

    def _learn_n_times(self, mapping_dir: Path, n: int) -> None:
        manager = _make_manager(mapping_dir)
        for _ in range(n):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Stable Genre")))

    def _reload_genre_processor(self, mapping_dir: Path) -> GenreProcessor:
        """Simuliert einen Neustart/Neu-Laden - Singleton-Reset wie im
        etablierten Muster von test_auto_learn_genre_confidence_audit.py."""
        SingletonMixin._instances.clear()
        fresh_mapper = GenreMapper(mapping_dir=mapping_dir)
        return GenreProcessor(_Config(mapping_dir), fresh_mapper)

    def test_learned_tier_short_circuits_all_fallbacks(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        self._learn_n_times(mapping_dir, 2)  # _LEARNED_THRESHOLD

        genre_processor = self._reload_genre_processor(mapping_dir)
        mb_client = CountingClient()
        lfm_client = CountingClient()

        result = _run(
            genre_processor.determine_genre_with_fallbacks(
                track_metadata={"title": "Irgendein neuer Song"},
                artist_name=self.ARTIST,
                channel_name=self.ARTIST,
                mb_client=mb_client,
                lfm_client=lfm_client,
            )
        )

        assert result is not None
        assert result.primary == "Stable Genre"
        assert result.source == "artist_exact_manual"
        assert result.auto_learn_disabled is True
        assert mb_client.call_count == 1, (
            "MusicBrainz wird bestehend IMMER fuer IDs aufgerufen "
            "(genre_processor.py:141) - das ist bestehendes, korrektes "
            "Verhalten und NICHT Teil des charakterisierten Bugs."
        )
        assert lfm_client.call_count == 0, (
            "Last.fm wurde trotz nur LEARNED-Status (2 Beobachtungen) "
            "nicht mehr live abgefragt - genau das verhindert, dass "
            "frischere Last.fm-Tags (z.B. mehr secondary-Genres) je "
            "uebernommen werden. Das ist der charakterisierte Bug."
        )

    def test_confirmed_tier_short_circuits_all_fallbacks(self, tmp_path):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()
        self._learn_n_times(mapping_dir, 4)  # _CONFIRMED_THRESHOLD

        genre_processor = self._reload_genre_processor(mapping_dir)
        mb_client = CountingClient()
        lfm_client = CountingClient()

        result = _run(
            genre_processor.determine_genre_with_fallbacks(
                track_metadata={"title": "Irgendein neuer Song"},
                artist_name=self.ARTIST,
                channel_name=self.ARTIST,
                mb_client=mb_client,
                lfm_client=lfm_client,
            )
        )

        assert result is not None
        assert result.source == "artist_exact_manual"
        assert result.auto_learn_disabled is True
        assert mb_client.call_count == 1
        assert lfm_client.call_count == 0


class HappyPathConfig:
    """Identisches Muster wie
    tests/test_enhanced_metadata_processor_search_title_uses_cleaned_title.py::HappyPathConfig."""

    def __init__(self, tmp_path: Path, mapping_dir: Path):
        self.LIBRARY_DIR = tmp_path / "library"
        self.DOWNLOAD_DIR = tmp_path / "downloads"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.TEMP_DIR = tmp_path / "temp"
        self.LOG_DIR = tmp_path / "logs"
        self.GENRE_MAPPING_DIR = mapping_dir
        self.ARTIST_OVERRIDE_FILE = tmp_path / "artist_overrides.json"
        self.METADATA_CACHE_DIR = tmp_path / "metadata_cache"
        self.DUPLICATE_CACHE_DIR = tmp_path / "duplicate_cache"
        self.FANART_API_KEY = None


class TestEnhancedMetadataProcessorNeverCallsLearnGenreAgain:
    """End-zu-End-Beleg: sobald ein Artist LEARNED ist, ruft die volle
    Produktions-Pipeline (EnhancedMetadataProcessor.process_single_track())
    learn_genre() fuer diesen Artist nie wieder auf - die observations-
    Zahl in der YAML-Datei bleibt eingefroren, obwohl ein neuer Download
    stattfindet."""

    ARTIST = "TEST_E2E_REVALIDATION_ARTIST"

    def _read_observations(self, mapping_dir: Path) -> int:
        import json

        # ARCH-022: auto_learned_genre.yaml -> auto_learned_genre.json.
        path = mapping_dir / "auto_learned_genre.json"
        data = json.loads(path.read_text()) or {}
        entry = data.get("ARTIST_GENRE_MAP", {}).get(self.ARTIST)
        assert entry is not None, "Erwarteter Bestandseintrag fehlt"
        return entry["observations"]

    def test_second_download_does_not_add_a_new_observation(
        self, tmp_path, monkeypatch
    ):
        mapping_dir = tmp_path / "mapping"
        mapping_dir.mkdir()

        # Schritt 1: Artist per echtem AutoLearnManager auf LEARNED bringen.
        manager = _make_manager(mapping_dir)
        for _ in range(2):
            _run(manager.learn_genre(self.ARTIST, _genre_info("Stable Genre")))
        assert self._read_observations(mapping_dir) == 2

        # Schritt 2: frischer Prozess-Start (Singleton-Reset), dann die
        # volle Produktions-Pipeline fuer einen NEUEN Track desselben
        # Artists durchlaufen lassen.
        SingletonMixin._instances.clear()
        monkeypatch.setattr(
            AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
        )
        happy_path_config = HappyPathConfig(tmp_path, mapping_dir)
        proc = EnhancedMetadataProcessor(happy_path_config)

        mb_recorder = CountingClient()
        proc._mb_client = mb_recorder
        proc._lfm_client = CountingClient()

        async def fake_fetch_lyrics(*args, **kwargs):
            return None, None

        async def fake_fetch_album_from_musicbrainz(*args, **kwargs):
            return None

        monkeypatch.setattr(
            proc.lyrics_processor, "fetch_lyrics_with_fallback", fake_fetch_lyrics
        )
        monkeypatch.setattr(
            proc.album_processor,
            "fetch_album_from_musicbrainz",
            fake_fetch_album_from_musicbrainz,
        )

        source = tmp_path / "second_track.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
        from utils.filenamefixer import FilenameFixerTool

        filename_fixer = FilenameFixerTool(happy_path_config)

        track_metadata = {
            "title": f"{self.ARTIST} - Ein komplett neuer Song",
            "artist": self.ARTIST,
            "uploader": self.ARTIST,
            "channel": self.ARTIST,
            "id": "SECOND_TRACK_ID",
            "filepath": str(source),
            "genre": None,
        }

        _run(
            proc.process_single_track(
                track_metadata=track_metadata, filename_fixer=filename_fixer
            )
        )

        # Hinweis: MusicBrainz wird bestehend IMMER fuer IDs aufgerufen
        # (genre_processor.py:141), auch bei bekanntem Genre - kein
        # sinnvoller Assert auf call_count==0 hier, siehe Docstring
        # oben. Der eigentliche Beweis ist die unveraenderte
        # observations-Zahl unten (kein neuer learn_genre()-Aufruf).
        assert self._read_observations(mapping_dir) == 2, (
            "observations ist gestiegen - learn_genre() wurde entgegen "
            "der charakterisierten Erwartung erneut aufgerufen. Wenn "
            "dieser Test fehlschlaegt, hat sich das Verhalten geaendert "
            "und dieser Testfall (nicht der Fix) muss ueberprueft werden."
        )
