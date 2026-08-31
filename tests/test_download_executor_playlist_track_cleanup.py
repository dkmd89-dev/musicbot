"""
DL-06 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md):
DownloadExecutor.download_single_track() (Playlist-Track-Download) liess
nach einem Fehler INNERHALB des yt-dlp-/FFmpeg-Aufrufs selbst (z.B. ein
scheiterndes FFmpeg-Postprocessing) die bereits heruntergeladene Rohdatei
unbereinigt in Config.DOWNLOAD_DIR zurueck - strukturell identisch zu DL-02
(bereits fuer _process_single_download() in download_utils.py behoben),
aber nie auf diesen zweiten, unabhaengigen yt-dlp-Aufrufpfad uebertragen.

Fix: identisches progress_hooks-Prinzip wie DL-02 - ein pro Versuch NEU
gebundener Callback (lokale Closure, kein globaler/geteilter Zustand)
erfasst den tatsaechlichen Rohdatei-Pfad, sobald yt-dlp ihn selbst gemeldet
hat (status='finished'). Anders als bei DL-02 existiert hier eine echte
Retry-Schleife (max_retries-Parameter) - der Hook-Zustand wird deshalb
INNERHALB der Schleife (pro Versuch) neu gebunden, damit ein Cleanup nie
faelschlich den Pfad eines fruaeheren Versuchs trifft.

Mocking-Muster: yt_dlp.YoutubeDL wird durch eine Fake-Klasse ersetzt (statt
nur extract_info_async() zu mocken wie in anderen Tests), da
download_single_track() yt_dlp.YoutubeDL(...) direkt intern konstruiert -
die Fake-Klasse ruft dabei echte, injizierte progress_hooks-Callbacks auf,
um yt-dlps reales Verhalten zu simulieren.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yt_dlp

from services.downloader.download.download_executor import DownloadExecutor


def run_async(coro):
    return asyncio.run(coro)


def make_track_info(video_id: str, url: str = "https://youtube.com/watch?v=x"):
    return {"webpage_url": url, "id": video_id, "title": f"Song {video_id}"}


class FakeYoutubeDL:
    """Ersetzt yt_dlp.YoutubeDL fuer die Dauer eines Tests. `behavior` ist
    eine Callable, die (ydl_opts) -> Dict (Erfolg) erhaelt und dabei selbst
    entscheidet, ob/wie die injizierten progress_hooks gefeuert werden,
    bevor sie zurueckgibt oder wirft - simuliert damit echtes yt-dlp-
    Verhalten (Hook VOR Postprocessing, unabhaengig vom Ausgang)."""

    def __init__(self, ydl_opts):
        self.ydl_opts = ydl_opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        return self.ydl_opts["_fake_behavior"](self.ydl_opts)


def fire_hooks(ydl_opts: Dict[str, Any], filename: Optional[str]) -> None:
    if filename is None:
        return
    for hook in ydl_opts.get("progress_hooks", []):
        hook({"status": "finished", "filename": filename})


def install_fake_ydl(monkeypatch, behavior):
    """behavior(ydl_opts) -> dict, wird in FakeYoutubeDL.extract_info()
    aufgerufen. Injiziert `behavior` ueber einen Extra-Key in ydl_opts,
    damit FakeYoutubeDL ohne globalen/Modul-Zustand auskommt."""

    class _InjectingExecutor(DownloadExecutor):
        pass

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    orig_download_single_track = DownloadExecutor.download_single_track

    async def wrapped(self, track_info, ydl_opts, *a, **kw):
        ydl_opts = {**ydl_opts, "_fake_behavior": behavior}
        return await orig_download_single_track(self, track_info, ydl_opts, *a, **kw)

    monkeypatch.setattr(DownloadExecutor, "download_single_track", wrapped)


@pytest.fixture
def executor():
    return DownloadExecutor()


class TestFailureAfterRawDownloadCleansUpArtifact:
    def test_hook_reported_artifact_is_deleted_and_none_is_returned(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 1: Hook meldet einen konkreten Rohdateipfad, danach
        schlaegt der (simulierte) Postprocessing-Schritt fehl - Cleanup
        laeuft, bestehende None-Rueckgabe-Semantik bleibt erhalten."""
        artifact = tmp_path / "Track_01_abc.webm"
        artifact.write_bytes(b"raw-audio-bytes")

        def behavior(ydl_opts):
            fire_hooks(ydl_opts, str(artifact))
            raise RuntimeError("SIMULATED FFmpeg postprocessing failure")

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("abc"),
                ydl_opts={},
                track_idx=1,
                download_dir=tmp_path,
            )
        )

        assert result is None
        assert not artifact.exists()


class TestFailureWithoutHookIsSafe:
    def test_failure_before_hook_fires_does_not_guess_a_path(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 2: Fehler VOR Fertigstellung des Rohdownloads - der Hook
        feuert nie. Kein Cleanup anhand eines geratenen Pfades; eine
        bereits vorhandene, unbeteiligte Datei bleibt unangetastet."""
        unrelated = tmp_path / "Unrelated.webm"
        unrelated.write_bytes(b"other-raw-audio-bytes")

        def behavior(ydl_opts):
            raise RuntimeError("SIMULATED network failure before raw download finished")

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("nohook"),
                ydl_opts={},
                track_idx=2,
                download_dir=tmp_path,
            )
        )

        assert result is None
        assert unrelated.exists()


class TestSuccessRegression:
    def test_successful_download_never_triggers_cleanup_and_returns_path(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 3: Hook meldet Datei, Download insgesamt erfolgreich -
        Cleanup darf NICHT laufen, bestehendes Rueckgabeverhalten
        (Dateipfad statt None) bleibt unveraendert."""
        artifact = tmp_path / "Track_03_ok.m4a"
        artifact.write_bytes(b"final-audio-bytes")

        def behavior(ydl_opts):
            fire_hooks(ydl_opts, str(artifact))
            return {"requested_downloads": [{"filepath": str(artifact)}]}

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("ok1"),
                ydl_opts={},
                track_idx=3,
                download_dir=tmp_path,
            )
        )

        assert result == str(artifact)
        assert artifact.exists()


class TestUnrelatedArtifactIsProtected:
    def test_only_hook_reported_artifact_is_deleted_unrelated_survives(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 4: zwei Dateien vorhanden (die vom Hook gemeldete UND eine
        zweite, unbeteiligte) - nur die gemeldete Datei wird geloescht."""
        artifact_current = tmp_path / "Track_04_cur.webm"
        artifact_current.write_bytes(b"current-bytes")
        artifact_unrelated = tmp_path / "Track_99_other.webm"
        artifact_unrelated.write_bytes(b"unrelated-bytes")

        def behavior(ydl_opts):
            fire_hooks(ydl_opts, str(artifact_current))
            raise RuntimeError("SIMULATED FFmpeg postprocessing failure")

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("cur"),
                ydl_opts={},
                track_idx=4,
                download_dir=tmp_path,
            )
        )

        assert result is None
        assert not artifact_current.exists()
        assert artifact_unrelated.exists()


class TestRetryIsolation:
    def test_first_attempt_artifact_is_cleaned_before_second_attempt_and_not_reused(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 5: max_retries=2. Versuch 1 meldet Datei A per Hook und
        schlaegt fehl - Cleanup muss Datei A SOFORT entfernen (nicht erst
        nach Versuch 2). Versuch 2 meldet eine ANDERE Datei B und ist
        erfolgreich - B darf NICHT durch das Cleanup von Versuch 1
        beeintraechtigt werden, und Versuch 1s (bereits entfernte) Datei A
        darf beim Erfolg von Versuch 2 nicht erneut angefasst werden."""
        artifact_a = tmp_path / "Track_05_attempt1.webm"
        artifact_a.write_bytes(b"attempt-1-bytes")
        artifact_b = tmp_path / "Track_05_attempt2.m4a"
        artifact_b.write_bytes(b"attempt-2-final-bytes")

        calls = {"n": 0}

        def behavior(ydl_opts):
            calls["n"] += 1
            if calls["n"] == 1:
                fire_hooks(ydl_opts, str(artifact_a))
                raise RuntimeError("SIMULATED failure on first attempt")
            fire_hooks(ydl_opts, str(artifact_b))
            return {"requested_downloads": [{"filepath": str(artifact_b)}]}

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("retry1"),
                ydl_opts={},
                track_idx=5,
                download_dir=tmp_path,
                max_retries=2,
                retry_backoff_seconds=0.0,
            )
        )

        assert calls["n"] == 2
        assert result == str(artifact_b)
        assert not artifact_a.exists(), (
            "Artefakt aus Versuch 1 haette bereits vor Versuch 2 entfernt "
            "werden muessen (Retry-Isolation)"
        )
        assert artifact_b.exists(), (
            "Erfolgreiches Artefakt aus Versuch 2 darf nicht durch das "
            "Cleanup von Versuch 1 beeintraechtigt worden sein"
        )

    def test_both_attempts_fail_each_cleans_up_only_its_own_artifact(
        self, executor, tmp_path, monkeypatch
    ):
        """Ergaenzung zu Test 5: schlagen BEIDE Versuche fehl, muss JEDER
        sein eigenes Artefakt entfernen - keines darf das des anderen
        Versuchs treffen oder unangetastet lassen."""
        artifact_a = tmp_path / "Track_06_attempt1.webm"
        artifact_a.write_bytes(b"attempt-1-bytes")
        artifact_b = tmp_path / "Track_06_attempt2.webm"
        artifact_b.write_bytes(b"attempt-2-bytes")

        calls = {"n": 0}

        def behavior(ydl_opts):
            calls["n"] += 1
            target = artifact_a if calls["n"] == 1 else artifact_b
            fire_hooks(ydl_opts, str(target))
            raise RuntimeError(f"SIMULATED failure on attempt {calls['n']}")

        install_fake_ydl(monkeypatch, behavior)

        result = run_async(
            executor.download_single_track(
                track_info=make_track_info("retry2"),
                ydl_opts={},
                track_idx=6,
                download_dir=tmp_path,
                max_retries=2,
                retry_backoff_seconds=0.0,
            )
        )

        assert result is None
        assert calls["n"] == 2
        assert not artifact_a.exists()
        assert not artifact_b.exists()


class TestConcurrentDownloadsIsolation:
    def test_two_concurrent_downloads_do_not_share_hook_state(
        self, executor, tmp_path, monkeypatch
    ):
        """Test 6: zwei ECHTE gleichzeitig laufende
        download_single_track()-Aufrufe (asyncio.gather). Download A
        schlaegt fehl, Download B ist erfolgreich - beweist, dass kein
        globaler/gemeinsamer Hook-Zustand existiert.

        WICHTIG (Testdesign-Korrektur): eine erste Fassung dieses Tests
        vertauschte yt_dlp.YoutubeDL waehrend der Laufzeit zwischen zwei
        parallelen Tasks (je ein eigenes Fake pro Download) - das ist
        selbst eine Race Condition (run_in_executor() startet den
        Hintergrund-Thread zu einem vom Event-Loop nicht kontrollierten
        Zeitpunkt; ein Vertauschen des Modul-Attributs haette das falsche
        Fake in den falschen Thread liefern koennen). Stattdessen wird
        yt_dlp.YoutubeDL genau EINMAL (stabil, ohne erneutes Patchen waehrend
        der Testlaufzeit) durch FakeYoutubeDL ersetzt; das Verhalten pro
        Aufruf wird stattdessen ueber einen Extra-Key direkt im jeweils
        eigenen ydl_opts-Dict injiziert (siehe fire_hooks()/FakeYoutubeDL) -
        dadurch ist kein gemeinsamer mutierbarer Zustand zwischen A und B
        mehr moeglich, unabhaengig davon, wann welcher Executor-Thread
        tatsaechlich laeuft."""
        artifact_a = tmp_path / "Track_07_a.webm"
        artifact_a.write_bytes(b"a-raw-bytes")
        artifact_b = tmp_path / "Track_08_b.m4a"
        artifact_b.write_bytes(b"b-final-bytes")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

        def behavior_a(ydl_opts):
            fire_hooks(ydl_opts, str(artifact_a))
            raise RuntimeError("SIMULATED failure for download A")

        def behavior_b(ydl_opts):
            fire_hooks(ydl_opts, str(artifact_b))
            return {"requested_downloads": [{"filepath": str(artifact_b)}]}

        async def run_both():
            return await asyncio.gather(
                executor.download_single_track(
                    track_info=make_track_info("concA"),
                    ydl_opts={"_fake_behavior": behavior_a},
                    track_idx=7,
                    download_dir=tmp_path,
                ),
                executor.download_single_track(
                    track_info=make_track_info("concB"),
                    ydl_opts={"_fake_behavior": behavior_b},
                    track_idx=8,
                    download_dir=tmp_path,
                ),
                return_exceptions=True,
            )

        results = run_async(run_both())

        assert results[0] is None
        assert results[1] == str(artifact_b)
        assert not artifact_a.exists()
        assert artifact_b.exists()
