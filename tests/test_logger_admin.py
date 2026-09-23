# -*- coding: utf-8 -*-
"""
CC-LOGGER-L2 — Tests für services/logger_admin.py (Application Layer).

Reine Unit-Tests gegen temporäre Log-Verzeichnisse (tmp_path), keine
echte Config/Logs berührt. Kein FastAPI-Import.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from services.logger_admin import (
    InvalidLogFilenameError,
    get_log_file,
    get_log_file_stats,
    human_size_str,
    list_log_files,
)


def _write_log(path: Path, content: str = "x\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


class TestListLogFiles:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert list_log_files(tmp_path) == []

    def test_missing_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert list_log_files(tmp_path / "does_not_exist") == []

    def test_lists_log_files_sorted_by_mtime_desc(self, tmp_path: Path) -> None:
        a = _write_log(tmp_path / "bot.log")
        time.sleep(0.01)
        b = _write_log(tmp_path / "modul.log")
        time.sleep(0.01)
        c = _write_log(tmp_path / "bot.log.1")
        # Neueste zuerst
        names = [m.name for m in list_log_files(tmp_path)]
        assert names == [c.name, b.name, a.name]

    def test_ignores_non_log_files(self, tmp_path: Path) -> None:
        _write_log(tmp_path / "bot.log")
        _write_log(tmp_path / "not_a_log.txt")
        _write_log(tmp_path / "random.dat")
        names = [m.name for m in list_log_files(tmp_path)]
        assert names == ["bot.log"]

    def test_size_and_mtime_are_populated(self, tmp_path: Path) -> None:
        _write_log(tmp_path / "bot.log", "hello\n")
        metas = list_log_files(tmp_path)
        assert len(metas) == 1
        assert metas[0].size_bytes == 6  # len("hello\n")
        assert metas[0].modified_at.year >= 2024


class TestGetLogFileStats:
    def test_empty_dir(self, tmp_path: Path) -> None:
        stats = get_log_file_stats(tmp_path)
        assert stats.total_files == 0
        assert stats.total_size_bytes == 0
        assert stats.largest_file is None
        assert stats.oldest_file is None

    def test_aggregate_counts_and_sizes(self, tmp_path: Path) -> None:
        _write_log(tmp_path / "big.log", "a" * 1000)
        time.sleep(0.01)
        _write_log(tmp_path / "small.log", "b" * 10)
        stats = get_log_file_stats(tmp_path)
        assert stats.total_files == 2
        assert stats.total_size_bytes == 1010
        assert stats.largest_file == "big.log"
        assert stats.largest_size_bytes == 1000
        # "big.log" ist zuerst geschrieben → älter → oldest
        assert stats.oldest_file == "big.log"
        assert stats.oldest_age_days == 0


class TestGetLogFile:
    def test_reads_known_file(self, tmp_path: Path) -> None:
        _write_log(
            tmp_path / "bot.log",
            "10:00:00 ℹ️ [COMP] hello\n10:00:01 ⚠️ [COMP] warn\n",
        )
        result = get_log_file(tmp_path, name="bot.log")
        assert result["source"] == "bot.log"
        assert result["total_matched"] == 2
        assert len(result["entries"]) == 2
        # Neueste zuerst
        assert result["entries"][0].message == "warn"

    def test_limit_truncates_entries(self, tmp_path: Path) -> None:
        lines = "\n".join(f"10:00:{i:02d} ℹ️ [COMP] line-{i}" for i in range(50))
        _write_log(tmp_path / "bot.log", lines + "\n")
        result = get_log_file(tmp_path, name="bot.log", limit=5)
        assert result["total_matched"] == 50
        assert len(result["entries"]) == 5

    def test_level_filter(self, tmp_path: Path) -> None:
        _write_log(
            tmp_path / "bot.log",
            "10:00:00 ℹ️ [COMP] info-line\n10:00:01 ❌ [COMP] error-line\n",
        )
        result = get_log_file(tmp_path, name="bot.log", level="ERROR")
        assert result["total_matched"] == 1
        assert result["entries"][0].message == "error-line"

    def test_unknown_name_raises(self, tmp_path: Path) -> None:
        _write_log(tmp_path / "bot.log")
        with pytest.raises(InvalidLogFilenameError):
            get_log_file(tmp_path, name="does-not-exist.log")


class TestSecurityPathTraversal:
    """Traversal-Versuche MÜSSEN bereits in der Whitelist scheitern,
    unabhängig vom Containment-Zweitcheck."""

    @pytest.mark.parametrize(
        "attack",
        [
            "../etc/passwd",
            "../../../etc/passwd",
            "/etc/passwd",
            "bot.log/../../etc/passwd",
            ".",
            "..",
            "",
        ],
    )
    def test_traversal_raises_invalid_filename(self, tmp_path: Path, attack: str) -> None:
        _write_log(tmp_path / "bot.log")
        with pytest.raises(InvalidLogFilenameError):
            get_log_file(tmp_path, name=attack)

    def test_symlink_outside_log_dir_not_exposed(self, tmp_path: Path) -> None:
        # Symlink auf /etc/passwd innerhalb des Log-Verzeichnisses.
        # Die Whitelist (list_log_sources → glob `*.log*`) erfasst den
        # Symlink nur, wenn er auf *.log* endet — der Standardfall ist
        # also bereits durch die Whitelist abgedeckt.
        outside = tmp_path.parent / "outside.log"
        outside.write_text("not a real log\n", encoding="utf-8")
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        link = log_dir / "sneaky.log"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("Symlinks in dieser Umgebung nicht verfügbar")
        # Whitelist erlaubt "sneaky.log", aber der Inhalts-Pfad zeigt nach außen.
        # Erwartung: Whitelist greift; wenn nicht, Containment-Check.
        # Beide Wege führen zu InvalidLogFilenameError.
        with pytest.raises(InvalidLogFilenameError):
            get_log_file(log_dir, name="sneaky.log")


class TestHumanSizeWrapper:
    def test_formats_bytes(self) -> None:
        assert human_size_str(0).endswith("B")
        assert human_size_str(1024).endswith("KB")
        assert human_size_str(1024 * 1024).endswith("MB")


class TestLimitValidation:
    """Server-seitige Limit-Validierung im App-Layer. Die HTTP-Schicht
    (FastAPI) prüft dasselbe über Query(ge=1, le=2000) — diese Tests
    sichern die zusätzliche, defensive App-Layer-Prüfung ab, damit
    direkte Aufrufer nicht stillschweigend übergroße Limits
    durchreichen."""

    @pytest.fixture
    def small_log(self, tmp_path: Path) -> Path:
        _write_log(tmp_path / "bot.log", "10:00:00 ℹ️ [C] a\n")
        return tmp_path

    def test_default_limit_is_200(self, small_log: Path) -> None:
        # Aufruf ohne limit-Argument nutzt DEFAULT_LIMIT (200).
        from services.logger_admin import DEFAULT_LIMIT
        assert DEFAULT_LIMIT == 200
        result = get_log_file(small_log, name="bot.log")
        assert result["limit"] == 200

    def test_limit_1_is_accepted(self, small_log: Path) -> None:
        result = get_log_file(small_log, name="bot.log", limit=1)
        assert result["limit"] == 1

    def test_limit_2000_is_accepted(self, small_log: Path) -> None:
        result = get_log_file(small_log, name="bot.log", limit=2000)
        assert result["limit"] == 2000

    @pytest.mark.parametrize("bad_limit", [0, -1, -100, 2001, 5000, 99999])
    def test_limit_out_of_range_raises(self, small_log: Path, bad_limit: int) -> None:
        from services.logger_admin import InvalidLimitError
        with pytest.raises(InvalidLimitError):
            get_log_file(small_log, name="bot.log", limit=bad_limit)

    def test_limit_2001_is_not_silently_clamped(self, small_log: Path) -> None:
        """Expliziter Nicht-Clamp-Test (Nutzeranforderung): ein Wert
        >2000 darf NICHT stillschweigend auf 2000 reduziert werden,
        sondern muss einen Fehler werfen."""
        from services.logger_admin import InvalidLimitError
        with pytest.raises(InvalidLimitError):
            get_log_file(small_log, name="bot.log", limit=2001)
