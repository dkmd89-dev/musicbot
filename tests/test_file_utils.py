"""
Unit-Tests für FileUtils (services/downloader/utils/file_utils.py)
— vorher 0 Tests, live via SingletonMixin verdrahtet und durch die gesamte
Download-Pipeline als Parameter durchgereicht (downloader.py, download_utils.py,
klassen/download_handler.py, enhanced_metadata_processor.py), gefunden über
die systematische Ungetestet-Prüfung.

WICHTIGER BEFUND (dokumentiert, nicht behoben - siehe Baseline):
Trotz der breiten Verdrahtung wird KEINE der 5 öffentlichen Methoden
(verify_file, safe_rename, clean_temp_files, create_dir, sanitize_filename)
und auch nicht `.library_dir` irgendwo in der Produktions-Codebasis
tatsächlich aufgerufen/gelesen - per Repo-weitem Grep verifiziert. Reale
Datei-Sanitisierung/-Umbenennung läuft stattdessen über die eigenständigen
Funktionen in utils/helpers.py (verify_file/safe_rename/sanitize_filename),
die von utils/filenamefixer.py::FilenameFixerTool importiert und genutzt
werden. FileUtils wird nur konstruiert und durchgereicht, seine Methoden
laufen nie. Trotzdem hier vollständig charakterisiert (echte Fachlogik,
könnte jederzeit reaktiviert/verdrahtet werden) statt entfernt (Regel 20:
Legacy-Code nicht ohne Beweis/Nutzerentscheidung löschen).

Nutzt object.__new__ + manuelle _do_init()-Injektion NICHT - stattdessen den
echten SingletonMixin-Konstruktionspfad (FileUtils(library_dir=..., ...)),
da reset_singletons (conftest.py, autouse) den Instanz-Cache vor/nach jedem
Test leert und _do_init() hier keine teuren externen Aufrufe macht (nur
Pfad-Zuweisung + Logging).
"""

import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.downloader.utils.error_handler import FileProcessingError
from services.downloader.utils.file_utils import FileUtils


def make_file_utils(tmp_path):
    return FileUtils(
        library_dir=tmp_path / "library", logger_factory=lambda name: Mock()
    )


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────
# verify_file
# ─────────────────────────────────────────────────────────────────────────


class TestVerifyFile:
    def test_missing_file_is_invalid(self, tmp_path):
        fu = make_file_utils(tmp_path)
        is_valid, reason = run_async(fu.verify_file(tmp_path / "does_not_exist.mp3"))
        assert is_valid is False
        assert reason == "Datei existiert nicht"

    def test_nonempty_file_is_valid(self, tmp_path):
        fu = make_file_utils(tmp_path)
        f = tmp_path / "song.mp3"
        f.write_bytes(b"x" * 100)

        is_valid, reason = run_async(fu.verify_file(f))

        assert is_valid is True
        assert reason == "OK"
        assert f.exists()

    def test_empty_file_is_invalid_and_deleted(self, tmp_path):
        fu = make_file_utils(tmp_path)
        f = tmp_path / "empty.mp3"
        f.write_bytes(b"")

        is_valid, reason = run_async(fu.verify_file(f))

        assert is_valid is False
        assert reason == "Dateigröße 0"
        assert not f.exists()


# ─────────────────────────────────────────────────────────────────────────
# safe_rename
# ─────────────────────────────────────────────────────────────────────────


class TestSafeRename:
    def test_missing_source_raises(self, tmp_path):
        fu = make_file_utils(tmp_path)
        with pytest.raises(FileNotFoundError):
            run_async(
                fu.safe_rename(tmp_path / "nope.mp3", tmp_path / "dest.mp3")
            )

    def test_moves_file_and_creates_dest_dir(self, tmp_path):
        fu = make_file_utils(tmp_path)
        src = tmp_path / "src.mp3"
        src.write_bytes(b"data")
        dest = tmp_path / "nested" / "dir" / "dest.mp3"

        run_async(fu.safe_rename(src, dest))

        assert not src.exists()
        assert dest.exists()
        assert dest.read_bytes() == b"data"

    def test_overwrites_existing_dest(self, tmp_path):
        fu = make_file_utils(tmp_path)
        src = tmp_path / "src.mp3"
        src.write_bytes(b"new-data")
        dest = tmp_path / "dest.mp3"
        dest.write_bytes(b"old-data")

        run_async(fu.safe_rename(src, dest))

        assert dest.read_bytes() == b"new-data"


# ─────────────────────────────────────────────────────────────────────────
# clean_temp_files
# ─────────────────────────────────────────────────────────────────────────


class TestCleanTempFiles:
    def test_old_file_is_deleted(self, tmp_path):
        fu = make_file_utils(tmp_path)
        old_file = tmp_path / "old.tmp"
        old_file.write_bytes(b"x")
        old_time = time.time() - 7200  # 2 Stunden alt
        import os

        os.utime(old_file, (old_time, old_time))

        run_async(fu.clean_temp_files(tmp_path))

        assert not old_file.exists()

    def test_recent_file_is_kept(self, tmp_path):
        fu = make_file_utils(tmp_path)
        recent_file = tmp_path / "recent.tmp"
        recent_file.write_bytes(b"x")

        run_async(fu.clean_temp_files(tmp_path))

        assert recent_file.exists()

    def test_directories_are_not_deleted(self, tmp_path):
        fu = make_file_utils(tmp_path)
        old_dir = tmp_path / "old_subdir"
        old_dir.mkdir()
        old_time = time.time() - 7200
        import os

        os.utime(old_dir, (old_time, old_time))

        # Darf nicht crashen und das Verzeichnis nicht loeschen (nur is_file()
        # wird angefasst).
        run_async(fu.clean_temp_files(tmp_path))

        assert old_dir.exists()

    def test_missing_directory_does_not_raise(self, tmp_path):
        fu = make_file_utils(tmp_path)
        run_async(fu.clean_temp_files(tmp_path / "does_not_exist"))
        # Kein Crash - Fehler wird intern geloggt und geschluckt.


# ─────────────────────────────────────────────────────────────────────────
# create_dir
# ─────────────────────────────────────────────────────────────────────────


class TestCreateDir:
    def test_creates_missing_directory(self, tmp_path):
        fu = make_file_utils(tmp_path)
        target = tmp_path / "new_dir"

        result = fu.create_dir(target)

        assert result == target
        assert target.is_dir()

    def test_noop_when_already_exists(self, tmp_path):
        fu = make_file_utils(tmp_path)
        target = tmp_path / "existing_dir"
        target.mkdir()

        result = fu.create_dir(target)

        assert result == target
        assert target.is_dir()

    def test_appends_to_base_path(self, tmp_path):
        fu = make_file_utils(tmp_path)
        result = fu.create_dir("sub", base_path=tmp_path)
        assert result == tmp_path / "sub"
        assert result.is_dir()

    def test_raises_file_processing_error_on_failure(self, tmp_path, monkeypatch):
        fu = make_file_utils(tmp_path)

        def raise_on_mkdir(*args, **kwargs):
            raise OSError("Simulated failure")

        monkeypatch.setattr(Path, "mkdir", raise_on_mkdir)

        with pytest.raises(FileProcessingError):
            fu.create_dir(tmp_path / "will_fail")


# ─────────────────────────────────────────────────────────────────────────
# sanitize_filename
# ─────────────────────────────────────────────────────────────────────────


class TestSanitizeFilename:
    def test_none_returns_empty_string(self, tmp_path):
        fu = make_file_utils(tmp_path)
        assert fu.sanitize_filename(None) == ""

    def test_normal_filename_unchanged(self, tmp_path):
        fu = make_file_utils(tmp_path)
        assert fu.sanitize_filename("Normal Song Title") == "Normal Song Title"

    def test_illegal_chars_replaced_with_space(self, tmp_path):
        fu = make_file_utils(tmp_path)
        result = fu.sanitize_filename('Song: Part <1> / "Two"')
        for char in '<>:"/\\|?*':
            assert char not in result

    def test_too_long_filename_is_truncated(self, tmp_path):
        fu = make_file_utils(tmp_path)
        long_name = "A" * 300
        result = fu.sanitize_filename(long_name)
        assert len(result) <= 150

    def test_ft_notation_normalized_to_feat(self, tmp_path):
        fu = make_file_utils(tmp_path)
        result = fu.sanitize_filename("Artist ft. Other Artist")
        assert "feat." in result
        assert " ft. " not in result

    def test_ft_substring_inside_word_not_mangled(self, tmp_path):
        """
        Regressionsschutz analog ARTISTNORM-001/002: FEAT_NOTATION_PATTERN
        verlangt zwingendes \\s+ vor UND nach "ft" - "trifft"/"Kraftklub"
        duerfen nicht als Feature-Notation fehlinterpretiert werden.
        """
        fu = make_file_utils(tmp_path)
        assert fu.sanitize_filename("Hardenacke trifft Freunde") == "Hardenacke trifft Freunde"
        assert fu.sanitize_filename("Kraftklub Live") == "Kraftklub Live"

    def test_extra_whitespace_collapsed(self, tmp_path):
        fu = make_file_utils(tmp_path)
        assert fu.sanitize_filename("Song   Title  Here") == "Song Title Here"

    def test_non_string_input_is_stringified(self, tmp_path):
        fu = make_file_utils(tmp_path)
        assert fu.sanitize_filename(12345) == "12345"

    def test_exception_returns_fallback(self, tmp_path, monkeypatch):
        """
        Nutzt bewusst EXTRA_SPACES_PATTERN (modul-eigenes, kompiliertes Regex-
        Objekt) statt unicodedata.normalize als Mock-Ziel: unicodedata ist ein
        geteiltes Stdlib-Modul, das auch pytest selbst intern nutzt (z.B.
        wcswidth fuer Terminal-Ausgabe) - ein globaler Patch darauf riss
        vorher die gesamte Testsitzung mit einem pytest-INTERNALERROR ab.
        """
        import services.downloader.utils.file_utils as file_utils_module

        fu = make_file_utils(tmp_path)
        fake_pattern = Mock()
        fake_pattern.sub = Mock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(file_utils_module, "EXTRA_SPACES_PATTERN", fake_pattern)

        assert fu.sanitize_filename("Some Title") == "ungueltiger_dateiname"
