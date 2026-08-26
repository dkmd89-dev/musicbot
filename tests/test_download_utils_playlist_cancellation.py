"""
DL-08 (docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md,
Abschnitt 6 "DL-07 und DL-08 bewusst nicht bearbeitet"):

services/downloader/download_utils.py::_process_playlist_download() sammelt
Track-Ergebnisse in einer rein lokalen `results`-Liste und gibt sie erst am
regulaeren Funktionsende zurueck (`return results`). Die Track-Schleife faengt
nur `except Exception`, nicht `asyncio.CancelledError` (erbt seit Python 3.8
von BaseException, nicht von Exception). Tritt eine CancelledError waehrend
eines await-Punkts innerhalb der Schleife auf (z.B. yt-dlp-Executor-Await oder
Metadaten-Verarbeitung), verlaesst sie die Funktion sofort - bereits fuer
erfolgreich abgeschlossene Tracks gesammelte Ergebnisse gehen komplett
verloren, inklusive der Konsequenz, dass
klassen/download_handler.py::_register_playlist_track_duplicates() fuer
KEINEN Track der Playlist mehr aufgerufen wird (auch nicht fuer die vor dem
Abbruch bereits erfolgreichen).

Fachliche Entscheidung (explizit freigegeben): bereits erfolgreich
abgeschlossene Tracks MUESSEN trotz Playlist-Abbruch registriert werden (sonst
Library-Datei vorhanden, aber kein DuplicateCache-Eintrag - Inkonsistenz).
Der aktuell abgebrochene bzw. ein fehlgeschlagener Track wird NICHT
registriert. CancelledError wird in jedem Fall weiterhin vollstaendig
propagiert (nie verschluckt).

Fix (kleinster moeglicher Wirkungsradius, keine Signaturaenderungen):
  1. _process_playlist_download() (download_utils.py): neuer
     `except asyncio.CancelledError:`-Zweig in der Track-Schleife haengt die
     bis dahin gesammelte `results`-Liste als Attribut
     `partial_playlist_results` an das Exception-Objekt und wirft sie per
     `raise` erneut (keine Unterdrueckung der Cancellation-Semantik).
  2. handle_youtube_links() (klassen/download_handler.py): neuer
     `except asyncio.CancelledError as ce:` Zweig liest dieses Attribut
     (`getattr(ce, "partial_playlist_results", None)`) und ruft bei
     vorhandenen Teilergebnissen das bereits bestehende, UNVERAENDERTE
     `self._register_playlist_track_duplicates(partial_results)` synchron
     auf, danach erneut `raise` (Propagation bleibt erhalten).

enhanced_download_with_retry() und downloader.py::download_audio() muessen
NICHT geaendert werden - beide fangen CancelledError bereits jetzt nicht ab
(`except Exception`/`except DownloadError`), die Exception samt angehaengtem
Attribut durchlaeuft sie unveraendert.

Teil 1 (TestPlaylistDownloadCancellationPreservesPartialResults) testet die
tatsaechliche Produktionsfunktion _process_playlist_download() direkt, mit
echter asyncio.Task.cancel()-Semantik (kein simuliertes Exception-Werfen).
enhanced_processor wird als Mock injiziert (Regel 7: EnhancedDownloadProcessor
ist ein echter SingletonMixin, ein Klassen-Mock verhindert versehentliche
Beruehrung einer aus einem frueheren Testlauf gecachten Instanz - identisches
Muster wie tests/test_download_utils_retry.py). _process_track_metadata()
wird gezielt gefaked, um praezise zu steuern, welcher Track wann als
erfolgreich/fehlgeschlagen/dauerhaft-blockiert-bis-zur-Cancellation gilt.

Teil 2 (TestHandleYoutubeLinksRegistersPartialResultsOnCancellation) testet
handle_youtube_links() mit einer REALEN DuplicateDetector-Instanz (wie
tests/test_download_handler_playlist_duplicate_registration.py), um echten
Cache-Zustand statt nur Funktionsaufrufe zu pruefen. self.downloader.download_audio
wird gefaked, um eine CancelledError mit vorbereitetem
partial_playlist_results-Attribut auszuloesen - dieselbe Form, die
_process_playlist_download() nach dem Fix tatsaechlich erzeugt.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from services.downloader import download_utils
from services.downloader.download_utils import _process_playlist_download
from klassen.download_handler import DownloadHandler
from services.downloader.download_result_reporter import DownloadResultReporter
from services.duplicate.detector import DuplicateDetector


def run_async(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# Teil 1: _process_playlist_download() direkt (echtes task.cancel())
# ═══════════════════════════════════════════════════════════════════════════


def make_processor():
    processor = Mock()
    processor.playlist_processor = Mock()
    processor.channel_router = Mock()
    processor.channel_router.resolve_dominant_artist = Mock(
        return_value=(None, "Dom Artist")
    )
    processor.year_resolver = Mock()
    processor.year_resolver.resolve_playlist_year = Mock(return_value=2024)
    processor.session_stats = {
        "total_processed": 0,
        "successful_downloads": 0,
        "failed_downloads": 0,
        "cache_hits": 0,
        "lyrics_found": 0,
        "dominant_artists_detected": 0,
        "artist_map_fallbacks": 0,
        "title_cleanups": 0,
    }
    processor.cache_manager = Mock()
    processor.cache_manager.lookup_playlist_track = Mock(return_value=None)
    processor.download_executor = Mock()
    processor.download_executor.download_single_track = AsyncMock(
        side_effect=lambda **kw: f"/fake/dl/{kw['track_info']['title']}.m4a"
    )
    processor.config = Mock()
    processor.config.DOWNLOAD_DIR = "/fake/downloads"
    processor.config.MAX_PLAYLIST_ITEMS = None
    processor.enhanced_metadata_processor = Mock()
    processor.enhanced_metadata_processor.get_processing_statistics = Mock(
        return_value={}
    )
    return processor


def make_track_info(title, artist="Some Artist", url=None):
    return {
        "title": title,
        "artist": artist,
        "url": url or f"https://www.youtube.com/watch?v={title}",
    }


def make_fake_process_track_metadata(behaviors):
    """behaviors: dict Titel -> "success" | "fail" | "block".

    "block" simuliert den Moment, in dem ein echter task.cancel() eintrifft:
    die Coroutine haengt an einem await, der nie von selbst zurueckkehrt -
    genau wie der reale run_in_executor()-/Metadaten-Await in Produktion.
    """

    async def fake(
        *,
        track_info,
        downloaded_file,
        enhanced_processor,
        filename_fixer,
        album_name,
        dominant_artist,
        playlist_year,
        track_idx,
        playlist_channel,
        logger,
    ):
        title = track_info["title"]
        behavior = behaviors[title]
        if behavior == "success":
            return {
                "success": True,
                "title": title,
                "artist": track_info["artist"],
                "url": track_info["url"],
                "library_path": f"/fake/lib/{title}.mp3",
                "renamed_due_to_conflict": False,
            }
        if behavior == "fail":
            return {"success": False, "title": title, "error": "boom"}
        if behavior == "block":
            await asyncio.Event().wait()  # blockiert bis zur echten Cancellation
        raise AssertionError(f"unbekanntes Testverhalten: {behavior}")

    return fake


def run_playlist_download(processor, entries_count):
    return _process_playlist_download(
        playlist_info={"title": "PL", "uploader": "U", "entries": [0] * entries_count},
        ydl_opts={},
        enhanced_processor=processor,
        filename_fixer=Mock(),
    )


async def start_and_cancel_after(coro, started_marker_fn):
    """Startet coro als echten Task, wartet bis started_marker_fn() True liefert,
    ruft dann task.cancel() auf und gibt die CancelledError-Instanz zurueck."""
    task = asyncio.create_task(coro)
    for _ in range(1000):
        if started_marker_fn():
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("Marker wurde nie gesetzt - Test-Setup fehlerhaft")
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    return exc_info.value


class TestPlaylistDownloadCancellationPreservesPartialResults:
    def test_A_cancellation_during_third_track_preserves_first_two_results(self, monkeypatch):
        """Test A: Track 1+2 erfolgreich, Cancellation waehrend Track 3.
        Track 1+2 muessen in den an die CancelledError angehaengten
        Teilergebnissen erhalten bleiben, Track 3 darf NICHT enthalten sein."""
        tracks_info = [make_track_info("T1"), make_track_info("T2"), make_track_info("T3")]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        reached_t3 = {"flag": False}

        fake = make_fake_process_track_metadata({"T1": "success", "T2": "success", "T3": "block"})

        async def fake_with_marker(**kwargs):
            if kwargs["track_info"]["title"] == "T3":
                reached_t3["flag"] = True
            return await fake(**kwargs)

        monkeypatch.setattr(download_utils, "_process_track_metadata", fake_with_marker)

        exc = run_async(
            start_and_cancel_after(
                run_playlist_download(processor, 3), lambda: reached_t3["flag"]
            )
        )

        partial = getattr(exc, "partial_playlist_results", None)
        assert partial is not None, (
            "CancelledError traegt kein partial_playlist_results-Attribut - "
            "Fix noch nicht implementiert oder Vor-Fix-Stand"
        )
        assert [r["title"] for r in partial] == ["T1", "T2"]
        assert all(r["success"] for r in partial)

    def test_B_cancellation_during_first_track_yields_empty_partial_results(self, monkeypatch):
        """Test B: Cancellation waehrend Track 1 (kein Track zuvor erfolgreich)
        -> partial_playlist_results ist leer, aber vorhanden (kein Absturz),
        CancelledError propagiert weiterhin."""
        tracks_info = [make_track_info("T1"), make_track_info("T2")]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        reached_t1 = {"flag": False}
        fake = make_fake_process_track_metadata({"T1": "block", "T2": "success"})

        async def fake_with_marker(**kwargs):
            if kwargs["track_info"]["title"] == "T1":
                reached_t1["flag"] = True
            return await fake(**kwargs)

        monkeypatch.setattr(download_utils, "_process_track_metadata", fake_with_marker)

        exc = run_async(
            start_and_cancel_after(
                run_playlist_download(processor, 2), lambda: reached_t1["flag"]
            )
        )

        partial = getattr(exc, "partial_playlist_results", None)
        assert partial == []

    def test_C_normal_successful_run_is_unaffected_by_new_cancellation_handling(self, monkeypatch):
        """Test C (Regressionsschutz): ohne Cancellation aendert der Fix am
        regulaeren Rueckgabewert nichts - alle 3 Tracks im Ergebnis, in
        Reihenfolge, kein CancelledError."""
        tracks_info = [make_track_info("T1"), make_track_info("T2"), make_track_info("T3")]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        fake = make_fake_process_track_metadata(
            {"T1": "success", "T2": "success", "T3": "success"}
        )
        monkeypatch.setattr(download_utils, "_process_track_metadata", fake)

        results = run_async(run_playlist_download(processor, 3))

        assert [r["title"] for r in results] == ["T1", "T2", "T3"]
        assert all(r["success"] for r in results)

    def test_D_actively_cancelled_track_never_appears_in_partial_results(self, monkeypatch):
        """Test D: der GERADE laufende (abgebrochene) Track darf unter keinen
        Umstaenden Teil der Teilergebnisse sein - auch nicht mit success=False
        o.ae. Platzhalter. Explizite, eigenstaendige Pruefung ergaenzend zu
        Test A."""
        tracks_info = [make_track_info("T1"), make_track_info("T2")]
        processor = make_processor()
        processor.playlist_processor.process_playlist_metadata = Mock(
            return_value={"tracks": tracks_info, "dominant_artist": "Dom", "album": "PL"}
        )
        reached_t2 = {"flag": False}
        fake = make_fake_process_track_metadata({"T1": "success", "T2": "block"})

        async def fake_with_marker(**kwargs):
            if kwargs["track_info"]["title"] == "T2":
                reached_t2["flag"] = True
            return await fake(**kwargs)

        monkeypatch.setattr(download_utils, "_process_track_metadata", fake_with_marker)

        exc = run_async(
            start_and_cancel_after(
                run_playlist_download(processor, 2), lambda: reached_t2["flag"]
            )
        )

        partial = getattr(exc, "partial_playlist_results", None)
        assert partial is not None
        titles = [r.get("title") for r in partial]
        assert "T2" not in titles
        assert titles == ["T1"]


# ═══════════════════════════════════════════════════════════════════════════
# Teil 2: handle_youtube_links() mit realer DuplicateDetector-Instanz
# ═══════════════════════════════════════════════════════════════════════════


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
        self.LIBRARY_DIR = str(tmp_path / "library")


def make_handler_with_update(tmp_path):
    handler = object.__new__(DownloadHandler)
    handler.logger = Mock()
    handler.duplicate_detector = DuplicateDetector(FakeConfig(tmp_path))
    handler.result_reporter = DownloadResultReporter(logger=Mock())
    handler.downloader = Mock()
    handler._check_duplicates_before_download = AsyncMock(return_value=(False, None, None))
    handler._update_status = AsyncMock()

    status_msg = Mock()
    status_msg.edit_text = AsyncMock()
    handler.status_msg = status_msg
    handler.update = Mock()

    update = Mock()
    update.message = Mock()
    update.message.text = "https://www.youtube.com/playlist?list=PLXYZ"
    update.message.reply_text = AsyncMock(return_value=status_msg)
    update.effective_chat = Mock(id=123)
    update.update_id = 1
    context = Mock()

    return handler, update, context


def make_partial_track(tmp_path, title, artist, url, filename, create_file=True):
    library_path = tmp_path / "library" / filename
    if create_file:
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.write_bytes(b"fake-audio-bytes")
    return {
        "success": True,
        "title": title,
        "artist": artist,
        "url": url,
        "library_path": str(library_path),
        "renamed_due_to_conflict": False,
    }


class TestHandleYoutubeLinksRegistersPartialResultsOnCancellation:
    def test_partial_results_are_registered_in_duplicate_cache_on_cancellation(self, tmp_path):
        """Kernfall: download_audio() wirft eine CancelledError mit bereits
        angehaengten Teilergebnissen (so wie sie _process_playlist_download()
        nach dem Fix tatsaechlich erzeugt) - beide Tracks muessen im echten
        DuplicateCache landen, CancelledError muss weiterhin propagieren."""
        handler, update, context = make_handler_with_update(tmp_path)

        track1 = make_partial_track(
            tmp_path, "T1", "Artist1", "https://www.youtube.com/watch?v=T1", "T1.mp3"
        )
        track2 = make_partial_track(
            tmp_path, "T2", "Artist2", "https://www.youtube.com/watch?v=T2", "T2.mp3"
        )
        ce = asyncio.CancelledError()
        ce.partial_playlist_results = [track1, track2]
        handler.downloader.download_audio = AsyncMock(side_effect=ce)

        async def run():
            with pytest.raises(asyncio.CancelledError):
                await handler.handle_youtube_links(update, context)

        run_async(run())

        is_dup1, entry1, reason1 = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REUP1", raw_artist="Artist1", raw_title="T1"
        )
        is_dup2, entry2, reason2 = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REUP2", raw_artist="Artist2", raw_title="T2"
        )
        assert is_dup1 is True
        assert is_dup2 is True

    def test_track_not_in_partial_results_is_not_registered(self, tmp_path):
        """Gegenprobe zum Kernfall: nur T1 ist Teil der Teilergebnisse (T2 war
        der gerade abgebrochene Track) - T2 darf NICHT im Cache landen."""
        handler, update, context = make_handler_with_update(tmp_path)

        track1 = make_partial_track(
            tmp_path, "T1", "Artist1", "https://www.youtube.com/watch?v=T1", "T1.mp3"
        )
        ce = asyncio.CancelledError()
        ce.partial_playlist_results = [track1]
        handler.downloader.download_audio = AsyncMock(side_effect=ce)

        async def run():
            with pytest.raises(asyncio.CancelledError):
                await handler.handle_youtube_links(update, context)

        run_async(run())

        is_dup1, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REUP1", raw_artist="Artist1", raw_title="T1"
        )
        is_dup2, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=REUP2", raw_artist="Artist2", raw_title="T2"
        )
        assert is_dup1 is True
        assert is_dup2 is False

    def test_cancellation_without_partial_results_attribute_does_not_crash(self, tmp_path):
        """Eine 'nackte' CancelledError ohne partial_playlist_results-Attribut
        (z.B. Cancellation an anderer Stelle der Pipeline) darf keinen
        AttributeError ausloesen und muss weiterhin sauber propagieren -
        ohne jeden Registrierungsversuch."""
        handler, update, context = make_handler_with_update(tmp_path)
        handler.downloader.download_audio = AsyncMock(side_effect=asyncio.CancelledError())

        async def run():
            with pytest.raises(asyncio.CancelledError):
                await handler.handle_youtube_links(update, context)

        run_async(run())  # darf keine AttributeError werfen

        is_dup, _, _ = handler.duplicate_detector.check_for_duplicates(
            "https://www.youtube.com/watch?v=ANY"
        )
        assert is_dup is False

    def test_cancellation_is_never_swallowed(self, tmp_path):
        """Explizite, eigenstaendige Absicherung: handle_youtube_links() muss
        die CancelledError in jedem Fall (mit UND ohne Teilergebnisse) erneut
        werfen - niemals als normale Rueckkehr behandeln."""
        handler, update, context = make_handler_with_update(tmp_path)
        track1 = make_partial_track(
            tmp_path, "T1", "Artist1", "https://www.youtube.com/watch?v=T1", "T1.mp3"
        )
        ce = asyncio.CancelledError()
        ce.partial_playlist_results = [track1]
        handler.downloader.download_audio = AsyncMock(side_effect=ce)

        async def run():
            await handler.handle_youtube_links(update, context)

        with pytest.raises(asyncio.CancelledError):
            run_async(run())
