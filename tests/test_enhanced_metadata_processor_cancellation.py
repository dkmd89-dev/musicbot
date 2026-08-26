"""
DL-01 (docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2D_DL01_AUDIT.md):
asyncio.CancelledError erbt seit Python 3.8 von BaseException, wurde von
keinem der bestehenden `except Exception`-Bloecke in
EnhancedMetadataProcessor.process_single_track() abgefangen. Eine
Cancellation, die eintrifft, NACHDEM move_to_library() (Schritt 16) bereits
gelaufen ist, hinterliess dadurch eine Datei dauerhaft in der Library, ohne
dass sie je im MetadataCache/DuplicateCache registriert wurde - je nach
exaktem Zeitpunkt entweder noch ungetaggt (Cancellation waehrend
write_tags()) oder sogar vollstaendig korrekt getaggt, aber dennoch
unregistriert (Cancellation nach Cache-Store, waehrend Auto-Learning).

Fix: ein dedizierter `except asyncio.CancelledError:`-Zweig in
process_single_track() (spiegelt exakt das bereits bestehende, geprüfte
tag_err-Loesch-Idiom, siehe die inline try/except OSError-Bloecke), der
`library_path` (falls bereits gesetzt) entfernt und danach zwingend `raise`
(bare) ausfuehrt - CancelledError wird niemals verschluckt.

Testmethodik: Wiederverwendet die etablierten Fixtures aus
tests/test_metadata_processor_happy_path.py bzw.
tests/test_enhanced_metadata_processor_event_loop_blocking.py (echte
Produktionsklassen EnhancedMetadataProcessor/FilenameFixerTool, nur externe
Dienste gefaked). Cancellation wird deterministisch ueber echtes
asyncio.Task.cancel() ausgeloest, synchronisiert per threading.Event
(fuer via asyncio.to_thread laufende Schritte: Loudness-Normalisierung,
Tag-Write) bzw. asyncio.Event (fuer native Koroutinen-Awaits:
Auto-Learning) - kein Sleep-Racing.
"""

import asyncio
import threading
from pathlib import Path

import pytest

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor
from utils.audio_enhancer import AudioEnhancer
from utils.filenamefixer import FilenameFixerTool


class HappyPathConfig:
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


class FakeExternalClient:
    async def fetch_metadata(self, *args, **kwargs):
        return {}


@pytest.fixture
def happy_path_config(tmp_path, mapping_dir_copy):
    return HappyPathConfig(tmp_path, mapping_dir_copy)


@pytest.fixture
def processor(happy_path_config, monkeypatch):
    monkeypatch.setattr(
        AudioEnhancer, "normalize_loudness", staticmethod(lambda *a, **kw: True)
    )

    proc = EnhancedMetadataProcessor(happy_path_config)
    proc._mb_client = FakeExternalClient()
    proc._lfm_client = FakeExternalClient()

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
    # Regel 7 (CLAUDE.md): externe Dienste in Unit-Tests mocken/faken -
    # get_cover_art() fragt laut FINDING-1-Kommentar (enhanced_metadata_
    # processor.py) im Worst Case bis zu 6 Quellen mit je 8s Timeout ab
    # (~48s) und macht dabei echte Netzwerkaufrufe. Ungemockt macht das die
    # in dieser Datei verwendeten kurzen, deterministischen
    # _wait_until()-Timeouts unzuverlaessig (haengt vom Sandbox-Netzwerk-
    # verhalten ab, nicht vom hier zu testenden Cancellation-Verhalten).
    monkeypatch.setattr(
        proc.cover_processor, "get_cover_art", lambda *a, **kw: (None, None)
    )
    return proc


@pytest.fixture
def filename_fixer(happy_path_config):
    return FilenameFixerTool(happy_path_config)


def _make_track_metadata(source: Path, video_id: str, artist: str = "DL01 Artist"):
    return {
        "title": f"{artist} - DL01 Song (Official Video)",
        "artist": artist,
        "uploader": artist,
        "channel": artist,
        "id": video_id,
        "filepath": str(source),
        "genre": "Hip Hop",
    }


async def _wait_until(predicate, timeout=5.0, interval=0.01):
    """Pollt predicate() aus dem Event-Loop, ohne diesen zu blockieren -
    kein Sleep-Race, sondern eine harte Obergrenze fuer den Fall, dass die
    erwartete Codepassage nie erreicht wird (Testsetup-Fehler statt Hang)."""
    elapsed = 0.0
    while not predicate():
        if elapsed >= timeout:
            raise AssertionError(
                "Erwartete Codepassage wurde nicht innerhalb des Timeouts "
                "erreicht - Testannahme ueber den Pipeline-Ablauf verletzt."
            )
        await asyncio.sleep(interval)
        elapsed += interval


class TestCancellationBeforeMoveToLibrary:
    """Test 1 (Fall A, Audit Abschnitt 4): Cancellation VOR move_to_library().
    Bewusst NICHT vom DL-01-Fix behandelt (identisch zur PHASE-1-Scope-
    Entscheidung) - nicht-diskriminierend, dient als Regressionsschutz
    dafuer, dass dieser Fall unangetastet bleibt."""

    def test_cancellation_during_loudness_normalization_propagates_without_library_file(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = threading.Event()
        proceed = threading.Event()

        def controlled_normalize_loudness(*a, **kw):
            started.set()
            assert proceed.wait(timeout=5), "Test haengt: proceed nie gesetzt"
            return True

        monkeypatch.setattr(
            AudioEnhancer,
            "normalize_loudness",
            staticmethod(controlled_normalize_loudness),
        )

        track_metadata = _make_track_metadata(source, "CANCELA1")

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            await _wait_until(started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())

        # Fall A: bewusst kein Cleanup - Quelldatei bleibt in DOWNLOAD_DIR
        # liegen (wird vom 24h-Start-Sweep erfasst), da move_to_library()
        # nie erreicht wurde.
        assert source.exists()
        assert list(happy_path_config.LIBRARY_DIR.rglob("*.mp3")) == []


class TestCancellationDuringWriteTags:
    """Test 2 (Fall B, Audit Abschnitt 4): Cancellation WAEHREND
    await asyncio.to_thread(self.tag_writer.write_tags, ...). Das ist der
    DL-01-Kernfall - vor dem Fix bleibt die Datei liegen (diskriminierend)."""

    def test_cancellation_during_write_tags_removes_library_artifact_and_propagates(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = threading.Event()
        proceed = threading.Event()

        def controlled_write_tags(self, target_path, **kwargs):
            started.set()
            assert proceed.wait(timeout=5), "Test haengt: proceed nie gesetzt"
            # Absichtlich KEIN echtes Taggen - simuliert einen Thread, der
            # nach der Cancellation im Hintergrund haengen bleibt (Fall B1,
            # Audit Abschnitt 4).

        monkeypatch.setattr(
            processor.tag_writer.__class__, "write_tags", controlled_write_tags
        )

        track_metadata = _make_track_metadata(source, "CANCELB1")

        library_files_before_cancel = {}

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            await _wait_until(started.is_set)
            # move_to_library() (rein synchron) ist zu diesem Zeitpunkt
            # bereits gelaufen - die Datei muss jetzt real existieren.
            library_files_before_cancel["files"] = list(
                happy_path_config.LIBRARY_DIR.rglob("*.mp3")
            )
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())

        assert len(library_files_before_cancel["files"]) == 1, (
            "move_to_library() haette vor der Cancellation bereits eine "
            "Datei erzeugt haben muessen - Testannahme verletzt"
        )
        assert list(happy_path_config.LIBRARY_DIR.rglob("*.mp3")) == [], (
            "Library-Datei wurde nach Cancellation waehrend write_tags() "
            "nicht entfernt - DL-01 nicht behoben"
        )


class TestCancellationImmediatelyAfterSuccessfulTagging:
    """Test 3 (Fall C, Audit Abschnitt 4): Cancellation NACH Cache-Store,
    waehrend Auto-Learning - Tagging ist zu diesem Zeitpunkt bereits
    vollstaendig erfolgreich abgeschlossen. Per Audit-Semantik (Abschnitt 4,
    7) entfernt der EINE, generische CancelledError-Zweig die Datei auch
    hier - bewusst keine Unterscheidung "war schon fertig getaggt", um den
    Fix minimal zu halten (siehe Audit Abschnitt 1/7)."""

    def test_cancellation_after_successful_tagging_still_removes_untracked_file(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = asyncio.Event()
        proceed = asyncio.Event()
        hit = {"which": None}

        async def controlled_learn_genre(*a, **kw):
            hit["which"] = "genre"
            started.set()
            await proceed.wait()

        async def controlled_learn_artist(*a, **kw):
            hit["which"] = "artist"
            started.set()
            await proceed.wait()

        monkeypatch.setattr(
            processor.auto_learn_manager, "learn_genre", controlled_learn_genre
        )
        monkeypatch.setattr(
            processor.auto_learn_manager, "learn_artist", controlled_learn_artist
        )

        track_metadata = _make_track_metadata(source, "CANCELC1", artist="Faller C Artist")

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
            except asyncio.TimeoutError:
                pytest.fail(
                    "Weder learn_genre() noch learn_artist() wurden erreicht - "
                    "Testannahme ueber den Pipeline-Ablauf verletzt (Auto-Learn-"
                    "Bedingungen fuer diesen Testinput nicht erfuellt)."
                )
            # Tagging ist an dieser Stelle bereits real & vollstaendig
            # abgeschlossen (write_tags() lief unpatched/echt durch, Cache-
            # Store lief bereits synchron VOR den Auto-Learn-Awaits).
            library_files = list(happy_path_config.LIBRARY_DIR.rglob("*.mp3"))
            assert len(library_files) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())

        assert list(happy_path_config.LIBRARY_DIR.rglob("*.mp3")) == [], (
            "Vollstaendig getaggte, aber nie registrierte Datei wurde nach "
            "Cancellation waehrend Auto-Learning nicht entfernt (Fall C, "
            "Audit Abschnitt 4/7)"
        )


class TestCleanupFailureDoesNotSwallowCancellation:
    """Test 4: schlaegt das Loeschen selbst fehl (OSError), darf
    CancelledError trotzdem NICHT verschluckt/ersetzt werden. Nicht
    diskriminierend fuer die reine "propagiert"-Aussage (vor dem Fix
    existiert der neue except-Zweig gar nicht, CancelledError propagiert
    dort bereits "zufaellig" ungehindert) - beweist aber gezielt die
    Sicherheitseigenschaft des NEUEN Zweigs: ein Cleanup-Fehler darf die
    Cancellation nicht maskieren."""

    def test_unlink_oserror_during_cancellation_cleanup_does_not_mask_cancelled_error(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = threading.Event()
        proceed = threading.Event()

        def controlled_write_tags(self, target_path, **kwargs):
            started.set()
            assert proceed.wait(timeout=5), "Test haengt: proceed nie gesetzt"

        monkeypatch.setattr(
            processor.tag_writer.__class__, "write_tags", controlled_write_tags
        )

        def _boom_unlink(self, *a, **kw):
            raise OSError("simulierter Loeschfehler")

        monkeypatch.setattr(Path, "unlink", _boom_unlink)

        track_metadata = _make_track_metadata(source, "CANCELD1")

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            await _wait_until(started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())
        # Kein weiterer Assert noetig - pytest.raises(asyncio.CancelledError)
        # ist der eigentliche Beweis: eine OSError beim Cleanup wurde NICHT
        # zur nach aussen sichtbaren Exception (kein "OSError" statt
        # "CancelledError").


class TestSuccessfulDownloadRegression:
    """Test 5: normaler, erfolgreicher Durchlauf ohne jede Cancellation -
    bestehendes Verhalten bleibt unveraendert. Nicht diskriminierend (reiner
    Nicht-Regressions-Nachweis)."""

    def test_normal_success_path_unaffected_by_new_cancellation_branch(
        self, processor, filename_fixer, happy_path_config, tmp_path
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")
        track_metadata = _make_track_metadata(source, "CANCELE1")

        result = asyncio.run(
            processor.process_single_track(
                track_metadata=track_metadata, filename_fixer=filename_fixer
            )
        )

        assert result.success is True
        assert result.library_path is not None
        assert Path(result.library_path).exists()


class TestUnrelatedArtifactIsProtected:
    """Test 6: ein zweites, unbeteiligtes Library-Artefakt darf durch den
    Cancellation-Cleanup niemals angetastet werden. Fuer sich genommen nicht
    diskriminierend (vor dem Fix wird ueberhaupt nichts geloescht, die
    unbeteiligte Datei bliebe also auch ohne Fix zufaellig unangetastet) -
    kombiniert mit derselben Zielpfad-Loeschbestaetigung wie
    TestCancellationDuringWriteTags aber, welche das eigentlich
    diskriminierende Verhalten liefert."""

    def test_second_unrelated_library_file_survives_cancellation_cleanup(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        happy_path_config.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        unrelated = happy_path_config.LIBRARY_DIR / "Unrelated Artist" / "unrelated.mp3"
        unrelated.parent.mkdir(parents=True, exist_ok=True)
        unrelated.write_bytes(b"unrelated-pre-existing-library-file")

        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = threading.Event()
        proceed = threading.Event()

        def controlled_write_tags(self, target_path, **kwargs):
            started.set()
            assert proceed.wait(timeout=5), "Test haengt: proceed nie gesetzt"

        monkeypatch.setattr(
            processor.tag_writer.__class__, "write_tags", controlled_write_tags
        )

        track_metadata = _make_track_metadata(source, "CANCELF1")

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            await _wait_until(started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())

        assert unrelated.exists()
        # Das eigene, gecancelte Artefakt wurde trotzdem entfernt (sonst
        # waere der Test kein echter Beweis fuer gezieltes statt zufaellig
        # unterbliebenes Cleanup).
        remaining = [
            p for p in happy_path_config.LIBRARY_DIR.rglob("*.mp3") if p != unrelated
        ]
        assert remaining == []


class TestParallelDownloadsIsolation:
    """Test 7: zwei echte, gleichzeitig laufende
    process_single_track()-Aufrufe auf DERSELBEN (Singleton-)Processor-
    Instanz - einer wird gecancelt, der andere laeuft normal durch. Nur das
    Artefakt des gecancelten Aufrufs darf entfernt werden."""

    def test_only_cancelled_downloads_artifact_is_removed(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source_cancel = tmp_path / "cancel_me.mp3"
        source_cancel.write_bytes(b"fake-audio-bytes-cancel")
        source_ok = tmp_path / "let_me_finish.mp3"
        source_ok.write_bytes(b"fake-audio-bytes-ok")

        started = threading.Event()
        proceed = threading.Event()
        real_write_tags = processor.tag_writer.__class__.write_tags

        def controlled_write_tags(self, target_path, artist, **kwargs):
            if artist == "Cancel Artist":
                started.set()
                assert proceed.wait(timeout=5), "Test haengt: proceed nie gesetzt"
                return
            return real_write_tags(self, target_path, artist, **kwargs)

        monkeypatch.setattr(
            processor.tag_writer.__class__, "write_tags", controlled_write_tags
        )

        track_metadata_cancel = _make_track_metadata(
            source_cancel, "CANCELG1", artist="Cancel Artist"
        )
        track_metadata_ok = _make_track_metadata(
            source_ok, "CANCELG2", artist="Ok Artist"
        )

        async def run():
            task_cancel = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata_cancel, filename_fixer=filename_fixer
                )
            )
            await _wait_until(started.is_set)
            task_cancel.cancel()

            task_ok = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata_ok, filename_fixer=filename_fixer
                )
            )

            results = await asyncio.gather(task_cancel, task_ok, return_exceptions=True)
            proceed.set()
            return results

        results = asyncio.run(run())

        assert isinstance(results[0], asyncio.CancelledError)
        assert results[1].success is True
        assert Path(results[1].library_path).exists()

        remaining_mp3 = list(happy_path_config.LIBRARY_DIR.rglob("*.mp3"))
        assert len(remaining_mp3) == 1
        assert remaining_mp3[0] == Path(results[1].library_path)


class TestCancellationOutsideTaggingPath:
    """Test 8: Cancellation an einer anderen, bereits VOR dieser Phase
    korrekten Stelle (waehrend des Lyrics-Fetch, deutlich vor
    move_to_library()) - beweist, dass der neue except-Zweig die bereits
    bestehende, korrekte Cancellation-Propagation ausserhalb des
    Tagging-Pfads nicht veraendert (library_path ist hier None, der neue
    Zweig no-opt korrekt). Nicht diskriminierend (war schon vorher korrekt),
    ergaenzt TestCancellationBeforeMoveToLibrary um einen zweiten,
    fruehen Await-Punkt."""

    def test_cancellation_during_lyrics_fetch_propagates_unaffected(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        started = asyncio.Event()
        proceed = asyncio.Event()

        async def controlled_fetch_lyrics(*a, **kw):
            started.set()
            await proceed.wait()
            return None, None

        monkeypatch.setattr(
            processor.lyrics_processor,
            "fetch_lyrics_with_fallback",
            controlled_fetch_lyrics,
        )

        track_metadata = _make_track_metadata(source, "CANCELH1")

        async def run():
            task = asyncio.create_task(
                processor.process_single_track(
                    track_metadata=track_metadata, filename_fixer=filename_fixer
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()

        asyncio.run(run())

        assert source.exists()
        assert list(happy_path_config.LIBRARY_DIR.rglob("*.mp3")) == []


class TestRegularExceptionPathUnaffected:
    """Test 9: bestehender tag_err-Pfad (reguläre Exception, KEINE
    Cancellation) bleibt durch die neue, separate except-Klausel
    unveraendert - Gegenstueck zu allen obigen CancelledError-Tests. Nicht
    diskriminierend (reiner Nicht-Regressions-Nachweis fuer den bereits
    vorhandenen except Exception-Zweig)."""

    def test_regular_tag_write_exception_still_cleans_up_via_existing_except_exception(
        self, processor, filename_fixer, happy_path_config, tmp_path, monkeypatch
    ):
        source = tmp_path / "downloaded.mp3"
        source.write_bytes(b"fake-audio-bytes-not-real-mp3-data")

        def _boom(self, *args, **kwargs):
            raise RuntimeError("simulierter write_tags-Fehler (keine Cancellation)")

        monkeypatch.setattr(processor.tag_writer.__class__, "write_tags", _boom)

        track_metadata = _make_track_metadata(source, "CANCELI1")

        result = asyncio.run(
            processor.process_single_track(
                track_metadata=track_metadata, filename_fixer=filename_fixer
            )
        )

        assert result.success is False
        assert list(happy_path_config.LIBRARY_DIR.rglob("*.mp3")) == []
