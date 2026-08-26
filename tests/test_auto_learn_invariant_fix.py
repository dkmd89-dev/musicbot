"""
P0-A (docs/MusicBot_ARCHITECTURE_EVOLUTION.md, Abschnitt 27):
services/metadata/auto_learn.py verletzte sowohl INV-01 (Event-Loop-Blockierung -
alle drei Schreibpfade liefen synchron im Event-Loop-Thread) als auch INV-02
(keine atomare Persistenz - direktes open(mode="w"), kein tmp+replace).

Zusaetzlich deckte der Architecture-Evolution-Audit ein Cross-Invariant-Risiko
auf: die Read-Modify-Write-Sequenz enthielt keinen await-Punkt, wodurch asyncios
kooperatives Scheduling zufaellig eine Serialisierung zwischen gleichzeitig
laufenden Tracks herstellte. Ein naiver asyncio.to_thread()-Fix OHNE Lock haette
diese zufaellige Sicherheit aufgehoben und eine echte Lost-Update-Race zwischen
parallelen Worker-Threads eingefuehrt (MAX_CONCURRENT_DOWNLOADS=3 erlaubt echte
Parallelitaet ueber den ThreadPoolExecutor von asyncio.to_thread()).

Der Fix kombiniert:
  - asyncio.to_thread() fuer INV-01 (Event-Loop bleibt frei)
  - threading.Lock (self._write_lock, Vorbild utils/artist_map.py) fuer die
    Serialisierung ueber echte OS-Threads hinweg
  - atomares Schreiben (tmp-Datei + Path.replace) fuer INV-02

Vier Tests, die alle vier Aspekte einzeln beweisen:

1. test_write_is_routed_through_asyncio_to_thread: deterministischer Beweis
   (kein Timing), dass learn_genre() ueber asyncio.to_thread() laeuft - exakt
   das etablierte Muster aus FINDING-1/FINDING-7.
2. test_interrupted_write_leaves_previous_valid_yaml_untouched: INV-02 -
   Schreibunterbrechung darf die vorherige gueltige Datei nicht beschaedigen
   (Muster aus FINDING-5).
3. test_concurrent_writes_without_lock_can_lose_an_update: beweist die
   allgemeine Schwachstellen-Klasse mit ERZWUNGENER Interleaving (threading.Barrier,
   kein Timing) - zwei "rohe" (ungeschuetzte) Schreiber verlieren nachweisbar
   einen Eintrag.
4. test_concurrent_writes_through_manager_preserve_all_entries: beweist, dass
   der eigentliche Fix (echtes Lock, echte parallele Worker-Threads via
   asyncio.to_thread) diese Race NICHT aufweist - alle Eintraege ueberleben.
"""

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from services.metadata.auto_learn import AutoLearnManager
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.genre_map import GenreMapper


class _Config:
    def __init__(self, mapping_dir: Path):
        self.GENRE_MAPPING_DIR = mapping_dir


@pytest.fixture
def mapping_dir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    return d


@pytest.fixture
def auto_learn(mapping_dir, tmp_path):
    config = _Config(mapping_dir)
    artist_config = ArtistConfig(
        library_dir=tmp_path / "library",
        override_file=tmp_path / "artist_overrides.json",
    )
    artist_normalizer = ArtistNormalizer(artist_config)
    genre_mapper = GenreMapper(mapping_dir=mapping_dir)
    return AutoLearnManager(
        config=config,
        artist_normalizer=artist_normalizer,
        genre_mapper=genre_mapper,
    )


class _GenreInfo:
    primary = "Electronic"
    secondary = ["House"]
    source = "lastfm"
    raw_tags = ["electronic", "house"]


class TestLearnGenreRoutedThroughToThread:
    def test_write_is_routed_through_asyncio_to_thread(self, auto_learn):
        real_to_thread = asyncio.to_thread
        calls = []

        async def recording_to_thread(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch.object(auto_learn, "_is_genre_already_learned", return_value=False):
            with patch(
                "services.metadata.auto_learn.asyncio.to_thread",
                side_effect=recording_to_thread,
            ):
                result = asyncio.run(
                    auto_learn.learn_genre(
                        canonical_name="Thread Artist",
                        genre_result=_GenreInfo(),
                        raw_name="thread artist",
                    )
                )

        assert result is True
        assert auto_learn._write_genre_entry_sync in calls, (
            "learn_genre() schreibt nicht ueber asyncio.to_thread() - der "
            "Schreibvorgang wuerde damit wieder direkt im Event-Loop-Thread "
            "laufen und diesen fuer alle Telegram-Nutzer blockieren."
        )


class TestAtomicWrite:
    def test_interrupted_write_leaves_previous_valid_yaml_untouched(
        self, auto_learn, mapping_dir, monkeypatch
    ):
        auto_genre_path = mapping_dir / "auto_learned_genre.yaml"

        # Erster, erfolgreicher Schreibvorgang - reale Datei auf Platte.
        ok = asyncio.run(
            auto_learn.learn_genre(
                canonical_name="Stable Artist",
                genre_result=_GenreInfo(),
                raw_name="stable artist",
            )
        )
        assert ok is True
        original_content = auto_genre_path.read_text(encoding="utf-8")

        # Zweiter Schreibvorgang wird simuliert unterbrochen (Absturz waehrend
        # yaml.dump()).
        monkeypatch.setattr(
            "services.metadata.auto_learn.yaml.dump",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        result = asyncio.run(
            auto_learn.learn_genre(
                canonical_name="New Artist During Crash",
                genre_result=_GenreInfo(),
                raw_name="new artist during crash",
            )
        )
        assert result is False  # Fehler wird abgefangen, kein Crash

        # Die Datei muss weiterhin ihren letzten GUELTIGEN Zustand haben.
        assert auto_genre_path.read_text(encoding="utf-8") == original_content

        leftover_tmp_files = list(mapping_dir.glob("*.tmp_*"))
        assert leftover_tmp_files == []


class TestConcurrentWriteRace:
    def test_concurrent_writes_without_lock_can_lose_an_update(self, mapping_dir):
        """
        Beweist die allgemeine Schwachstellen-Klasse, die den Lock motiviert:
        zwei ungeschuetzte Schreiber, die per threading.Barrier gezwungen
        werden, beide VOR dem jeweils anderen Schreibvorgang zu lesen, verlieren
        nachweisbar einen Eintrag. Erzwungene Synchronisation, kein Timing.
        """
        path = mapping_dir / "unprotected.yaml"
        path.write_text(
            yaml.dump({"ARTIST_GENRE_MAP": {}}), encoding="utf-8"
        )
        barrier = threading.Barrier(2)

        def racy_write(key: str, value: dict):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            genre_map = data.get("ARTIST_GENRE_MAP", {})
            # Erzwingt, dass BEIDE Threads lesen, bevor irgendeiner schreibt.
            barrier.wait()
            genre_map[key] = value
            data["ARTIST_GENRE_MAP"] = genre_map
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f)

        t1 = threading.Thread(target=racy_write, args=("Artist A", {"primary": "Pop"}))
        t2 = threading.Thread(target=racy_write, args=("Artist B", {"primary": "Rock"}))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        final = yaml.safe_load(path.read_text(encoding="utf-8"))
        genre_map = final.get("ARTIST_GENRE_MAP", {})
        assert not ("Artist A" in genre_map and "Artist B" in genre_map), (
            "Erwartete Race (Lost Update) trat nicht auf - dieser Test soll "
            "genau die Schwachstelle demonstrieren, die self._write_lock im "
            "echten Fix verhindert."
        )

    def test_concurrent_writes_through_manager_preserve_all_entries(
        self, auto_learn
    ):
        """
        Beweist, dass der tatsaechliche Fix (asyncio.to_thread + self._write_lock)
        die oben demonstrierte Race NICHT aufweist - alle Eintraege ueberleben
        unter echter, paralleler Worker-Thread-Ausfuehrung.
        """

        async def learn_many():
            with patch.object(
                auto_learn, "_is_genre_already_learned", return_value=False
            ):
                tasks = [
                    auto_learn.learn_genre(
                        canonical_name=f"Concurrent Artist {i}",
                        genre_result=_GenreInfo(),
                        raw_name=f"concurrent artist {i}",
                    )
                    for i in range(8)
                ]
                return await asyncio.gather(*tasks)

        results = asyncio.run(learn_many())
        assert all(results), "Nicht alle parallelen learn_genre()-Aufrufe waren erfolgreich"

        auto_genre_path = auto_learn.config.GENRE_MAPPING_DIR / "auto_learned_genre.yaml"
        data = yaml.safe_load(auto_genre_path.read_text(encoding="utf-8"))
        genre_map = data.get("ARTIST_GENRE_MAP", {})

        for i in range(8):
            assert f"Concurrent Artist {i}" in genre_map, (
                f"Eintrag 'Concurrent Artist {i}' fehlt - Lost-Update-Race trotz "
                f"self._write_lock aufgetreten."
            )
