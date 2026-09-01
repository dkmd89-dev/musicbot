# tests/test_filenamefixer_move_to_library_toctou.py
# -*- coding: utf-8 -*-
"""
Baseline v5/v6 Technical Debt: move_to_library() pruefte den Zielnamen nur
per final_target.exists() BEVOR geschrieben wurde - das Fenster zwischen
dieser Pruefung und dem spaeteren tmp_target.replace(final_target) blieb
offen. Berechnen zwei Aufrufer (z.B. der laufende Bot + ein gleichzeitig
manuell gestarteter scripts/reprocess_artist_metadata.py-Lauf, der bewusst
dieselbe move_to_library()-Implementierung wiederverwendet) zufaellig
denselben Zielnamen, konnten beide die Pruefung passieren, bevor einer
geschrieben hatte - der Verlierer wurde durch das anschliessende
Path.replace() dann STILLSCHWEIGEND ueberschrieben (Datenverlust, keine
Korruption - das Copy+Rename-Muster aus FINDING-6 schuetzt bereits davor).

Fix: final_target wird jetzt per os.O_CREAT | os.O_EXCL atomar auf
Betriebssystemebene beansprucht (funktioniert damit auch
prozessuebergreifend) - bei Kollision wird der naechste "(N)"-Kandidat
probiert, exakt dieselbe Namenskonvention wie bisher.

Testmethodik: zwei echte Threads rufen move_to_library() mit IDENTISCHEN
Artist/Album/Titel/Jahr/Tracknummer auf (identischer target_path), aber
unterschiedlichem Quellinhalt. Ein threading.Barrier synchronisiert den
Start beider Threads; shutil.copy2() wird um eine kleine, deterministische
Pause verlaengert (steht stellvertretend fuer reale I/O-Latenz und
vergroessert das Race-Fenster zuverlaessig, ohne auf zufaelliges
Thread-Timing angewiesen zu sein). Am ungefixten Code (.exists()-Pruefung)
fuehrt das reproduzierbar dazu, dass beide Threads denselben target_path
(ohne "(N)"-Suffix) waehlen und der zweite den ersten stillschweigend
ueberschreibt - der Test schlaegt dort fehl (siehe Pre-Fix-Diskriminierung
unten im Kommentar der Testklasse).
"""

import shutil
import threading
import time
from pathlib import Path

import pytest

from utils.filenamefixer import FilenameFixerTool


class FakeConfig:
    def __init__(self, tmp_path: Path, mapping_dir: Path = None):
        self.LIBRARY_DIR = tmp_path / "library"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.TEMP_DIR = tmp_path / "temp"
        self.GENRE_MAPPING_DIR = mapping_dir or (tmp_path / "empty_mapping")


@pytest.fixture
def tool(tmp_path):
    return FilenameFixerTool(FakeConfig(tmp_path))


class TestMoveToLibraryConcurrentSameTargetIsRaceFree:
    def test_two_concurrent_callers_with_identical_target_both_survive(
        self, tool, tmp_path, monkeypatch
    ):
        # Zwei unterschiedliche Quelldateien, die auf denselben target_path
        # abbilden (identische Artist/Album/Titel/Jahr/Tracknummer).
        source_a = tmp_path / "source_a.m4a"
        source_b = tmp_path / "source_b.m4a"
        source_a.write_bytes(b"CONTENT-FROM-CALLER-A")
        source_b.write_bytes(b"CONTENT-FROM-CALLER-B")

        # shutil.copy2() um eine kleine, deterministische Pause verlaengert -
        # vergroessert das Fenster zwischen Namenswahl und tatsaechlichem
        # Schreiben zuverlaessig (steht stellvertretend fuer reale
        # I/O-Latenz), ohne auf zufaelliges Thread-Timing angewiesen zu sein.
        real_copy2 = shutil.copy2

        def slow_copy2(src, dst, *a, **kw):
            time.sleep(0.05)
            return real_copy2(src, dst, *a, **kw)

        monkeypatch.setattr(shutil, "copy2", slow_copy2)

        barrier = threading.Barrier(2)
        results = {}
        errors = []

        def call(name, source):
            try:
                barrier.wait(timeout=5)
                target, renamed = tool.move_to_library(
                    source_path=source,
                    artist="Race Artist",
                    album="Race Album",
                    title="Race Title",
                    year="2024",
                    track_number=1,
                )
                results[name] = (target, renamed)
            except Exception as e:  # pragma: no cover - Diagnose bei Fehlschlag
                errors.append((name, e))

        t_a = threading.Thread(target=call, args=("a", source_a))
        t_b = threading.Thread(target=call, args=("b", source_b))
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        assert not errors, f"Unerwartete Fehler in den Threads: {errors}"
        assert set(results.keys()) == {"a", "b"}

        target_a, _ = results["a"]
        target_b, _ = results["b"]

        # Kernaussage 1: beide Aufrufer muessen unterschiedliche Zieldateien
        # bekommen haben - kein stillschweigendes gegenseitiges Ueberschreiben.
        assert target_a != target_b, (
            "Beide Aufrufer haben denselben final_target erhalten - die "
            "Namenskollision wurde nicht erkannt, einer haette den anderen "
            "beim anschliessenden Path.replace() stillschweigend "
            "ueberschrieben."
        )

        # Kernaussage 2: beide Inhalte muessen tatsaechlich auf der Platte
        # erhalten geblieben sein (kein Datenverlust).
        contents_on_disk = {target_a.read_bytes(), target_b.read_bytes()}
        assert contents_on_disk == {
            b"CONTENT-FROM-CALLER-A",
            b"CONTENT-FROM-CALLER-B",
        }, (
            "Mindestens einer der beiden Inhalte ist verloren gegangen - "
            "eine Datei wurde von der anderen ueberschrieben."
        )

        assert target_a.exists() and target_b.exists()
