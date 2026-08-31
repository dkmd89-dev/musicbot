"""
AE-12 (docs/archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md): seit dem Fix ruft
enhanced_metadata_processor.py TagWriter.write_tags() ueber
asyncio.to_thread() auf. Bis zu Config.MAX_CONCURRENT_DOWNLOADS (=3, siehe
config.py) Tracks koennen gleichzeitig verarbeitet werden, alle ueber
dieselbe, gemeinsam genutzte (Singleton-)TagWriter-Instanz.

Anders als bei AE-10 (ChartRenderer haelt globalen mutierbaren
matplotlib.pyplot-Zustand, ein Lock war zwingend noetig) besitzt TagWriter
keinen gemeinsamen mutierbaren Zustand - dieser Test verankert den im
AE-12-Audit einmalig durchgefuehrten deterministischen Beweis dauerhaft
als Regressionstest: mehrere echte, gleichzeitig ueber asyncio.to_thread()
dispatchte write_tags()-Aufrufe auf unterschiedlichen Dateien duerfen sich
nicht gegenseitig kontaminieren.

Deterministisch durch threading.Barrier (alle Worker-Threads starten so
gleichzeitig wie moeglich) statt Timing - kein Sleep/Race als alleiniger
Beweis.
"""

import asyncio
import shutil
import subprocess
import threading

import pytest
from mutagen.id3 import ID3

from services.metadata.tag_writer import TagWriter

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _make_real_mp3(path, duration_seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "libmp3lame", "-b:a", "192k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfuegbar")
class TestConcurrentWriteTagsAcrossDifferentFiles:
    def test_barrier_synchronized_threads_do_not_cross_contaminate(self, tmp_path):
        writer = TagWriter()  # eine geteilte Instanz, wie im echten Singleton-Prozessor

        seed = tmp_path / "seed.mp3"
        _make_real_mp3(seed)

        n = 5
        targets = [tmp_path / f"concurrent_{i}.mp3" for i in range(n)]
        for t in targets:
            shutil.copy2(seed, t)

        barrier = threading.Barrier(n)
        errors = []

        def worker(idx, target):
            try:
                barrier.wait(timeout=5)
                writer.write_tags(
                    target_path=target,
                    artist=f"Artist-{idx}",
                    title=f"Title-{idx}",
                    album_info={"album": f"Album-{idx}", "year": "2026"},
                    track_number=idx,
                    genres_result=None,
                    cover_art=b"\xff\xd8\xff" + b"\x00" * 500,
                )
            except Exception as e:
                errors.append((idx, e))

        threads = [
            threading.Thread(target=worker, args=(i, t))
            for i, t in enumerate(targets)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Unerwartete Fehler bei gleichzeitigem Tagging: {errors}"
        for i, target in enumerate(targets):
            tags = ID3(target)
            assert tags["TIT2"].text == [f"Title-{i}"], (
                f"Datei {i}: Tags wurden mit einer anderen gleichzeitig "
                f"laufenden write_tags()-Ausfuehrung vertauscht"
            )
            leftover = list(tmp_path.glob(f".{target.name}.tmp_*"))
            assert not leftover, f"Verwaiste Tmp-Datei(en) fuer Datei {i}: {leftover}"

    def test_real_asyncio_to_thread_dispatch_does_not_cross_contaminate(
        self, tmp_path
    ):
        """
        Ergaenzend zum reinen threading.Barrier-Beweis oben: derselbe
        Nachweis ueber den tatsaechlichen Dispatch-Mechanismus
        (asyncio.to_thread(), Default-ThreadPoolExecutor), exakt wie er
        jetzt in enhanced_metadata_processor.py verwendet wird.
        """
        writer = TagWriter()

        seed = tmp_path / "seed.mp3"
        _make_real_mp3(seed)

        n = 5
        targets = [tmp_path / f"async_concurrent_{i}.mp3" for i in range(n)]
        for t in targets:
            shutil.copy2(seed, t)

        async def write_one(idx, target):
            await asyncio.to_thread(
                writer.write_tags,
                target_path=target,
                artist=f"Artist-{idx}",
                title=f"Title-{idx}",
                album_info={"album": f"Album-{idx}", "year": "2026"},
                track_number=idx,
                genres_result=None,
                cover_art=b"\xff\xd8\xff" + b"\x00" * 500,
            )

        async def run_all():
            await asyncio.gather(*(write_one(i, t) for i, t in enumerate(targets)))

        asyncio.run(run_all())

        for i, target in enumerate(targets):
            tags = ID3(target)
            assert tags["TIT2"].text == [f"Title-{i}"], (
                f"Datei {i}: Tags wurden ueber asyncio.to_thread() "
                f"vertauscht"
            )
