"""
Download-Control-Center 2026-09-02: DownloadExecutor.download_single_track()
darf einen DownloadCancelledError (geworfen vom Cancel-Check-Hook, siehe
download_utils.py::_make_cancel_check_hook()) NICHT wie einen normalen
Download-Fehler behandeln - kein Retry, sofortiges Weiterreichen an den
Aufrufer (_process_playlist_download() bricht die gesamte Schleife ab,
statt zum naechsten Track weiterzugehen).

Mocking-Muster identisch zu tests/test_download_executor_playlist_track_cleanup.py
(DL-06) - yt_dlp.YoutubeDL wird durch eine Fake-Klasse ersetzt, die die
injizierten progress_hooks tatsaechlich aufruft (simuliert echtes
yt-dlp-Verhalten: eine im Hook geworfene Exception bricht den Download ab).
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import yt_dlp

from services.downloader.download.download_executor import DownloadExecutor
from services.downloader.errors import DownloadCancelledError


def run_async(coro):
    return asyncio.run(coro)


def make_track_info(video_id: str, url: str = "https://youtube.com/watch?v=x"):
    return {"webpage_url": url, "id": video_id, "title": f"Song {video_id}"}


class FakeYoutubeDL:
    """Siehe tests/test_download_executor_playlist_track_cleanup.py für die
    Begründung dieses Musters."""

    def __init__(self, ydl_opts):
        self.ydl_opts = ydl_opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        # Simuliert yt-dlps eigenes Verhalten: JEDER registrierte
        # progress_hooks-Callback wird aufgerufen - inkl. eines vom
        # Aufrufer injizierten Cancel-Check-Hooks. Wirft einer davon,
        # bricht der Download ab (die Exception propagiert unverändert).
        for hook in self.ydl_opts.get("progress_hooks", []):
            hook({"status": "downloading"})
        return {"requested_downloads": [{"filepath": "/tmp/should-not-be-used.m4a"}]}


@pytest.fixture
def executor():
    return DownloadExecutor()


class TestDownloadCancelledErrorIsNotRetried:
    def test_cancelled_error_propagates_without_retry(
        self, executor, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

        def cancel_hook(status):
            raise DownloadCancelledError()

        with pytest.raises(DownloadCancelledError):
            run_async(
                executor.download_single_track(
                    track_info=make_track_info("cancelme"),
                    ydl_opts={"progress_hooks": [cancel_hook]},
                    track_idx=1,
                    download_dir=tmp_path,
                    max_retries=3,
                    retry_backoff_seconds=0.0,
                )
            )

    def test_cancelled_error_does_not_trigger_a_second_attempt(
        self, executor, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
        calls = {"n": 0}

        def cancel_hook(status):
            calls["n"] += 1
            raise DownloadCancelledError()

        with pytest.raises(DownloadCancelledError):
            run_async(
                executor.download_single_track(
                    track_info=make_track_info("cancelme2"),
                    ydl_opts={"progress_hooks": [cancel_hook]},
                    track_idx=1,
                    download_dir=tmp_path,
                    max_retries=3,
                    retry_backoff_seconds=0.0,
                )
            )

        assert calls["n"] == 1, (
            "Ein Nutzer-Abbruch darf nicht wie ein normaler Fehler erneut "
            "versucht werden - der Hook haette nur beim ersten Aufruf "
            "feuern duerfen."
        )

    def test_raw_artifact_is_still_cleaned_up_on_cancel(
        self, executor, tmp_path, monkeypatch
    ):
        """Auch bei Abbruch soll ein bereits (teilweise) heruntergeladenes
        Rohartefakt entfernt werden - identisches Verhalten wie bei einem
        normalen Fehlschlag (DL-06)."""
        artifact = tmp_path / "Track_01_partial.webm"
        artifact.write_bytes(b"partial-bytes")

        class FakeYoutubeDLWithArtifact(FakeYoutubeDL):
            def extract_info(self, url, download=True):
                for hook in self.ydl_opts.get("progress_hooks", []):
                    hook({"status": "finished", "filename": str(artifact)})
                for hook in self.ydl_opts.get("progress_hooks", []):
                    hook({"status": "downloading"})
                return {}

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDLWithArtifact)

        def cancel_hook(status):
            if status.get("status") == "downloading":
                raise DownloadCancelledError()

        with pytest.raises(DownloadCancelledError):
            run_async(
                executor.download_single_track(
                    track_info=make_track_info("cancelme3"),
                    ydl_opts={"progress_hooks": [cancel_hook]},
                    track_idx=1,
                    download_dir=tmp_path,
                    max_retries=1,
                )
            )

        assert not artifact.exists()

    def test_cancel_during_downloading_status_cleans_up_part_file(
        self, executor, tmp_path, monkeypatch
    ):
        """
        P2-Fund (docs/FINDINGS_INDEX.md, "Hard-Cancel waehrend laufendem
        Download - .part-Datei bleibt liegen"): der realistische Fall ist
        NICHT wie im Test oben (ein "finished"-Event VOR dem Abbruch) -
        ein echter Nutzer-Abbruch trifft fast immer status=="downloading",
        das "finished"-Event fuer den aktuellen Track feuert dann nie. Zu
        diesem Zeitpunkt existiert bereits eine physische ".part"-Datei
        (status["tmpfilename"], siehe yt_dlp/downloader/http.py::
        temp_name()) - die finale Datei (status["filename"]) existiert noch
        nicht. Ohne Fix blieb raw_downloaded_path in diesem Fall auf None,
        cleanup_single_download_artifact() wurde nie mit einem echten Pfad
        aufgerufen - und der 24h-Start-Sweep beruehrt .part-Dateien bewusst
        nie.
        """
        final_name = tmp_path / "Track_01_cancelme4.webm"
        part_file = tmp_path / "Track_01_cancelme4.webm.part"
        part_file.write_bytes(b"partial-bytes-still-downloading")

        # yt-dlp ruft progress_hooks mehrfach pro Sekunde auf (siehe
        # download_utils.py::_make_cancel_check_hook()-Docstring). Realistisch
        # simuliert: EIN "downloading"-Event OHNE Abbruch (dabei erfasst der
        # intern angehaengte _capture_raw_downloaded_path-Hook bereits die
        # .part-Datei), DANACH ein zweites Event, bei dem der Cancel-Hook
        # tatsaechlich abbricht - genau wie im echten Betrieb, wo der
        # Capture-Hook (zweiter in der Hook-Liste) laengst schon vor dem
        # eigentlichen Abbruch mehrfach gefeuert hat.
        downloading_status = {
            "status": "downloading",
            "filename": str(final_name),
            "tmpfilename": str(part_file),
            "downloaded_bytes": 1234,
            "total_bytes": 999999,
        }

        class FakeYoutubeDLDownloadingStatus(FakeYoutubeDL):
            def extract_info(self, url, download=True):
                for hook in self.ydl_opts.get("progress_hooks", []):
                    hook(downloading_status)
                for hook in self.ydl_opts.get("progress_hooks", []):
                    hook(downloading_status)
                return {}

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDLDownloadingStatus)

        calls = {"n": 0}

        def cancel_hook(status):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise DownloadCancelledError()

        with pytest.raises(DownloadCancelledError):
            run_async(
                executor.download_single_track(
                    track_info=make_track_info("cancelme4"),
                    ydl_opts={"progress_hooks": [cancel_hook]},
                    track_idx=1,
                    download_dir=tmp_path,
                    max_retries=1,
                )
            )

        assert not part_file.exists()
        assert not final_name.exists()
