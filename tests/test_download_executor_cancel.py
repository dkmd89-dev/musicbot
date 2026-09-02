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
