"""
Unit-Tests für utils/file_ops.py — vorher 0 Tests, gefunden über die
systematische Ungetestet-Prüfung.

WICHTIG: file_ops.py hatte urspruenglich 3 Funktionen. Bei der Analyse
festgestellt, dass 2 davon tot waren:
- safe_rename() (eigene Implementierung) wurde NIE aufgerufen -
  utils/helpers.py hat eine eigene, unabhaengige safe_rename()-Funktion
  (die tatsaechlich von FilenameFixerTool importiert/genutzt wird), die
  IO_SEMAPHORE und atomic_rename() aus DIESER Datei importiert, aber
  ihre eigene Retry-Fallback-Logik hat.
- move_to_processed() hatte 0 Aufrufer im gesamten Repo.

Beide entfernt. atomic_rename() und IO_SEMAPHORE bleiben, da sie ueber
utils/helpers.py::safe_rename() indirekt live im FilenameFixerTool-Pfad
genutzt werden (P0 - Datei-Verschiebung in die Library).
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.file_ops import atomic_rename, IO_SEMAPHORE


class TestAtomicRename:
    def test_moves_file_to_destination(self, tmp_path):
        src = tmp_path / "source.mp3"
        src.write_bytes(b"audio-data")
        dest = tmp_path / "subdir" / "dest.mp3"

        result = asyncio.run(atomic_rename(src, dest))

        assert result is True
        assert not src.exists()
        assert dest.exists()
        assert dest.read_bytes() == b"audio-data"

    def test_creates_missing_destination_directory(self, tmp_path):
        src = tmp_path / "source.mp3"
        src.write_bytes(b"x")
        dest = tmp_path / "a" / "b" / "c" / "dest.mp3"

        asyncio.run(atomic_rename(src, dest))

        assert dest.exists()

    def test_missing_source_returns_false_without_raising(self, tmp_path):
        src = tmp_path / "does_not_exist.mp3"
        dest = tmp_path / "dest.mp3"

        result = asyncio.run(atomic_rename(src, dest))

        assert result is False

    def test_accepts_string_paths(self, tmp_path):
        src = tmp_path / "source.mp3"
        src.write_bytes(b"x")
        dest = tmp_path / "dest.mp3"

        result = asyncio.run(atomic_rename(str(src), str(dest)))

        assert result is True
        assert dest.exists()

    def test_uses_os_rename_on_posix(self, tmp_path):
        # os.name == "nt" laesst sich auf diesem Linux-System nicht sinnvoll
        # simulieren (pathlib.Path()s Klassen-Dispatch haengt selbst am
        # echten os.name und wuerde bei einem Patch abstuerzen - siehe
        # NotImplementedError: "cannot instantiate 'WindowsPath'").
        # Stattdessen nur den tatsaechlich auf diesem System genutzten
        # POSIX-Zweig explizit verifizieren.
        src = tmp_path / "source.mp3"
        src.write_bytes(b"x")
        dest = tmp_path / "dest.mp3"

        with patch("utils.file_ops.os.rename") as mock_rename:
            result = asyncio.run(atomic_rename(src, dest))

        assert result is True
        mock_rename.assert_called_once_with(str(src), str(dest))


class TestIoSemaphore:
    def test_is_an_asyncio_semaphore_with_expected_limit(self):
        assert isinstance(IO_SEMAPHORE, asyncio.Semaphore)
        # Interner Zaehlerstand ist nicht offiziell oeffentlich, aber
        # praktisch stabil genug fuer eine Charakterisierung des Limits.
        assert IO_SEMAPHORE._value == 5
