"""
DL-02 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2C_DL02_AUDIT.md):
services/downloader/download_utils.py::_process_single_download() liess
nach einem Fehler INNERHALB des yt-dlp-/FFmpeg-Aufrufs selbst (z.B. ein
scheiterndes FFmpeg-Postprocessing) die bereits heruntergeladene Rohdatei
unbereinigt in Config.DOWNLOAD_DIR zurueck - kein Cleanup-Aufruf existierte
in dieser Funktion, und die vorhandene find_downloaded_file()-Logik ist in
diesem Fehlerfall grundsaetzlich nicht anwendbar (kein download_info-Dict
verfuegbar, siehe Audit Abschnitt 2).

Fix: ein yt-dlp progress_hooks-Callback (lokale Closure, kein globaler
Zustand) erfasst den tatsaechlichen Rohdatei-Pfad, sobald yt-dlp ihn selbst
gemeldet hat (status='finished') - unabhaengig vom Ausgang des nachfolgenden
Postprocessing-Schritts. Im Fehlerfall wird NUR dieser eine, fuer den
aktuellen Aufruf spezifische Pfad ueber die bereits bestehende
cleanup_single_download_artifact() bereinigt; die Exception propagiert
danach unveraendert weiter.

Mocking-Muster uebernommen von
tests/test_download_utils_metadata_translation.py
(make_enhanced_processor_for_single) - hier jedoch mit einer echten
extract_info_async()-Ersatzfunktion (statt eines reinen AsyncMock), da der
Test den vom Fix injizierten progress_hooks-Callback selbst aufrufen muss,
um yt-dlps reales Verhalten zu simulieren.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from services.downloader.download_utils import _process_single_download
from services.downloader.errors import DownloadError
from services.metadata.models import MetadataResult


def run_async(coro):
    return asyncio.run(coro)


def make_processor(tmp_path):
    processor = Mock()
    processor.session_stats = {
        "total_processed": 0,
        "cache_hits": 0,
        "failed_downloads": 0,
    }
    processor.config = Mock()
    processor.config.DOWNLOAD_DIR = tmp_path
    processor.cache_manager = Mock()
    processor.cache_manager.lookup_single_track = Mock(return_value=None)
    processor.download_executor = Mock()
    return processor


def make_video_info():
    return {"title": "Song", "artist": "Artist", "uploader": "Artist", "id": "abc123"}


class TestFfmpegFailureCleansUpKnownArtifact:
    def test_hook_reported_artifact_is_deleted_and_exception_propagates(
        self, tmp_path, monkeypatch
    ):
        """Test 1: yt-dlp meldet ueber den Hook einen konkreten Rohdateipfad,
        schlaegt danach fehl (simuliertes FFmpeg-Postprocessing) - Cleanup
        wird ausgefuehrt, Exception bleibt erhalten."""
        processor = make_processor(tmp_path)
        artifact = tmp_path / "Song.webm"
        artifact.write_bytes(b"raw-audio-bytes")

        cleanup_calls = []
        monkeypatch.setattr(
            "services.downloader.download_utils.cleanup_single_download_artifact",
            lambda *a, **kw: cleanup_calls.append(a),
        )

        async def failing_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact)})
            raise RuntimeError("SIMULATED FFmpeg postprocessing failure")

        processor.download_executor.extract_info_async = failing_extract_info_async

        with pytest.raises(DownloadError, match="Single-Download fehlgeschlagen"):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][0] == artifact
        assert processor.session_stats["failed_downloads"] == 1

    def test_hook_reported_artifact_actually_removed_from_disk(self, tmp_path):
        """Test 1 (Dateizustand statt nur Mock-Aufruf): dieselbe Simulation
        wie oben, aber ohne cleanup_single_download_artifact() zu mocken -
        prueft den TATSAECHLICHEN Dateisystemzustand nach dem Fix."""
        processor = make_processor(tmp_path)
        artifact = tmp_path / "Song.webm"
        artifact.write_bytes(b"raw-audio-bytes")

        async def failing_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact)})
            raise RuntimeError("SIMULATED FFmpeg postprocessing failure")

        processor.download_executor.extract_info_async = failing_extract_info_async

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert not artifact.exists()


class TestFailureBeforeHookIsSafe:
    def test_failure_before_hook_fires_does_not_delete_unrelated_file(self, tmp_path):
        """Test 2 (Sicherheitsfall): Fehler VOR Fertigstellung des
        Rohdownloads - der Hook feuert nie. Es darf kein unsicheres Cleanup
        stattfinden; eine bereits vorhandene, unbeteiligte Datei bleibt
        unangetastet."""
        processor = make_processor(tmp_path)
        unrelated = tmp_path / "Unrelated.webm"
        unrelated.write_bytes(b"other-raw-audio-bytes")

        async def failing_extract_info_async(url, ydl_opts, download=True):
            raise RuntimeError("SIMULATED network failure before raw download finished")

        processor.download_executor.extract_info_async = failing_extract_info_async

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert unrelated.exists()


class TestDownloadingStatusPartFileCleanup:
    """
    P2-Fund (docs/FINDINGS_INDEX.md, "Hard-Cancel waehrend laufendem
    Download - .part-Datei bleibt liegen"): der Hook wurde bisher nur bei
    status=="finished" ausgewertet. Ein Abbruch (Hard-Cancel via
    DownloadCancelledError) oder jeder andere Fehler WAEHREND des
    eigentlichen Downloads (status=="downloading", der weitaus groesste
    Teil der gesamten Downloaddauer) feuert "finished" nie - der Hook
    liefert in diesem Zustand aber bereits status["tmpfilename"], die
    ECHTE physische ".part"-Datei, die yt-dlp zu diesem Zeitpunkt auf der
    Platte hat (siehe yt_dlp/downloader/http.py::temp_name()). Ohne Fix
    blieb raw_downloaded_path auf None, cleanup_single_download_artifact()
    wurde nie mit einem echten Pfad aufgerufen - und der 24h-Start-Sweep
    (download_artifact_cleanup.py::cleanup_download_artifacts()) beruehrt
    .part-Dateien bewusst NIE (siehe dortiger Docstring). Diese Klasse von
    Abbruchartefakten hatte damit KEINEN Cleanup-Pfad ueberhaupt.
    """

    def test_cancel_during_downloading_status_cleans_up_part_file(
        self, tmp_path, monkeypatch
    ):
        processor = make_processor(tmp_path)
        final_name = tmp_path / "Song.webm"
        part_file = tmp_path / "Song.webm.part"
        part_file.write_bytes(b"partial-bytes-still-downloading")

        cleanup_calls = []
        monkeypatch.setattr(
            "services.downloader.download_utils.cleanup_single_download_artifact",
            lambda *a, **kw: cleanup_calls.append(a),
        )

        async def cancelled_mid_download_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook(
                    {
                        "status": "downloading",
                        "filename": str(final_name),
                        "tmpfilename": str(part_file),
                        "downloaded_bytes": 1234,
                        "total_bytes": 999999,
                    }
                )
            raise RuntimeError("SIMULATED Hard-Cancel waehrend des Downloads")

        processor.download_executor.extract_info_async = (
            cancelled_mid_download_extract_info_async
        )

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][0] == part_file, (
            "Cleanup muss die tatsaechlich physisch vorhandene .part-Datei "
            "treffen (status['tmpfilename']), nicht die noch nicht "
            "existierende finale Datei (status['filename'])."
        )

    def test_cancel_during_downloading_status_actually_removes_part_file_from_disk(
        self, tmp_path
    ):
        """Wie oben, aber ohne Mock - prueft den tatsaechlichen
        Dateisystemzustand nach dem Fix."""
        processor = make_processor(tmp_path)
        final_name = tmp_path / "Song2.webm"
        part_file = tmp_path / "Song2.webm.part"
        part_file.write_bytes(b"partial-bytes-still-downloading")

        async def cancelled_mid_download_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook(
                    {
                        "status": "downloading",
                        "filename": str(final_name),
                        "tmpfilename": str(part_file),
                        "downloaded_bytes": 1234,
                        "total_bytes": 999999,
                    }
                )
            raise RuntimeError("SIMULATED Hard-Cancel waehrend des Downloads")

        processor.download_executor.extract_info_async = (
            cancelled_mid_download_extract_info_async
        )

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert not part_file.exists()
        assert not final_name.exists()


class TestSuccessRegression:
    def test_successful_download_never_triggers_cleanup(self, tmp_path, monkeypatch):
        """Test 3: Hook meldet Datei, Download insgesamt erfolgreich -
        Cleanup darf NICHT ausgefuehrt werden, bestehendes Erfolgsverhalten
        bleibt unveraendert."""
        processor = make_processor(tmp_path)
        artifact = tmp_path / "Song.webm"
        artifact.write_bytes(b"raw-audio-bytes")

        cleanup_calls = []
        monkeypatch.setattr(
            "services.downloader.download_utils.cleanup_single_download_artifact",
            lambda *a, **kw: cleanup_calls.append(a),
        )

        async def succeeding_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact)})
            return {"id": "abc123"}

        processor.download_executor.extract_info_async = succeeding_extract_info_async
        processor.download_executor.find_downloaded_file = Mock(
            return_value=str(artifact)
        )
        processor.enhanced_metadata_processor = Mock()
        processor.enhanced_metadata_processor.process_single_track = AsyncMock(
            return_value=MetadataResult(success=True, title="Song", artist="Artist")
        )

        result = run_async(
            _process_single_download(
                url="https://youtube.com/watch?v=x",
                video_info=make_video_info(),
                ydl_opts={},
                enhanced_processor=processor,
                filename_fixer=Mock(),
            )
        )

        assert result["success"] is True
        assert cleanup_calls == []
        assert artifact.exists()


class TestUnrelatedArtifactIsProtected:
    def test_only_hook_reported_artifact_is_deleted_unrelated_artifact_survives(
        self, tmp_path
    ):
        """Test 4: zwei Dateien vorhanden (die vom Hook gemeldete UND eine
        zweite, unbeteiligte) - nur die gemeldete Datei wird geloescht, kein
        directory-/glob-weites Cleanup."""
        processor = make_processor(tmp_path)
        artifact_current = tmp_path / "Song.webm"
        artifact_current.write_bytes(b"raw-audio-bytes")
        artifact_other = tmp_path / "OtherSong.webm"
        artifact_other.write_bytes(b"other-raw-audio-bytes")

        async def failing_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact_current)})
            raise RuntimeError("SIMULATED FFmpeg postprocessing failure")

        processor.download_executor.extract_info_async = failing_extract_info_async

        with pytest.raises(DownloadError):
            run_async(
                _process_single_download(
                    url="https://youtube.com/watch?v=x",
                    video_info=make_video_info(),
                    ydl_opts={},
                    enhanced_processor=processor,
                    filename_fixer=Mock(),
                )
            )

        assert not artifact_current.exists()
        assert artifact_other.exists()


class TestClosureIsolationAcrossConcurrentDownloads:
    def test_two_concurrent_downloads_do_not_share_hook_state(self, tmp_path):
        """Test 5: zwei unabhaengige _process_single_download()-Aufrufe
        laufen ECHT GLEICHZEITIG (asyncio.gather) mit jeweils eigenem
        Hook-Closure. Download A schlaegt fehl, Download B ist erfolgreich -
        beweist, dass kein globaler/gemeinsamer Hook-Zustand verwendet wird."""
        processor_a = make_processor(tmp_path)
        artifact_a = tmp_path / "SongA.webm"
        artifact_a.write_bytes(b"a-raw-audio-bytes")

        async def failing_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact_a)})
            raise RuntimeError("SIMULATED failure for download A")

        processor_a.download_executor.extract_info_async = failing_extract_info_async

        processor_b = make_processor(tmp_path)
        artifact_b = tmp_path / "SongB.webm"
        artifact_b.write_bytes(b"b-raw-audio-bytes")

        async def succeeding_extract_info_async(url, ydl_opts, download=True):
            for hook in ydl_opts.get("progress_hooks", []):
                hook({"status": "finished", "filename": str(artifact_b)})
            return {"id": "b123"}

        processor_b.download_executor.extract_info_async = succeeding_extract_info_async
        processor_b.download_executor.find_downloaded_file = Mock(
            return_value=str(artifact_b)
        )
        processor_b.enhanced_metadata_processor = Mock()
        processor_b.enhanced_metadata_processor.process_single_track = AsyncMock(
            return_value=MetadataResult(success=True, title="Song B", artist="Artist B")
        )

        async def run_both():
            return await asyncio.gather(
                _process_single_download(
                    url="https://youtube.com/watch?v=a",
                    video_info={"title": "Song A", "artist": "Artist A"},
                    ydl_opts={},
                    enhanced_processor=processor_a,
                    filename_fixer=Mock(),
                ),
                _process_single_download(
                    url="https://youtube.com/watch?v=b",
                    video_info={"title": "Song B", "artist": "Artist B"},
                    ydl_opts={},
                    enhanced_processor=processor_b,
                    filename_fixer=Mock(),
                ),
                return_exceptions=True,
            )

        results = run_async(run_both())

        assert isinstance(results[0], DownloadError)
        assert isinstance(results[1], dict) and results[1]["success"] is True

        assert not artifact_a.exists()
        assert artifact_b.exists()
