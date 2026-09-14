# tests/test_library_repair_library_artists.py
# -*- coding: utf-8 -*-
"""services/library_repair/library_artists.py (ARCH-032 Phase 3C)."""

from services.library_repair.library_artists import (
    list_library_artist_dirs,
    resolve_artist_by_index,
)


def test_lists_artist_directories_sorted(tmp_path):
    (tmp_path / "Zeeba").mkdir()
    (tmp_path / "Aymen").mkdir()
    (tmp_path / "makko").mkdir()

    assert list_library_artist_dirs(tmp_path) == ["Aymen", "Zeeba", "makko"]


def test_empty_library_returns_empty_list(tmp_path):
    assert list_library_artist_dirs(tmp_path) == []


def test_missing_library_root_returns_empty_list(tmp_path):
    assert list_library_artist_dirs(tmp_path / "does_not_exist") == []


def test_ignores_non_directory_entries(tmp_path):
    (tmp_path / "Aymen").mkdir()
    (tmp_path / "stray_file.m4a").write_text("x", encoding="utf-8")

    assert list_library_artist_dirs(tmp_path) == ["Aymen"]


def test_ignores_hidden_directories(tmp_path):
    (tmp_path / "Aymen").mkdir()
    (tmp_path / ".library_repair_backups").mkdir()

    assert list_library_artist_dirs(tmp_path) == ["Aymen"]


def test_ignores_symlinked_directories(tmp_path):
    real = tmp_path.parent / "outside_artist_dir"
    real.mkdir(exist_ok=True)
    (tmp_path / "Aymen").mkdir()
    (tmp_path / "Linked").symlink_to(real)

    assert list_library_artist_dirs(tmp_path) == ["Aymen"]


def test_resolve_by_index_returns_matching_artist(tmp_path):
    (tmp_path / "Aymen").mkdir()
    (tmp_path / "Zeeba").mkdir()

    assert resolve_artist_by_index(0, library_root=tmp_path) == "Aymen"
    assert resolve_artist_by_index(1, library_root=tmp_path) == "Zeeba"


def test_resolve_by_index_out_of_range_returns_none(tmp_path):
    (tmp_path / "Aymen").mkdir()

    assert resolve_artist_by_index(5, library_root=tmp_path) is None
    assert resolve_artist_by_index(-1, library_root=tmp_path) is None


def test_resolve_by_index_never_accepts_raw_path_injection(tmp_path):
    """Der Index ist die EINZIGE Eingabe - es gibt keinen Codepfad, der
    einen vom Aufrufer uebergebenen String direkt als Pfad verwendet
    (ARCH-031 B.8 Anti-Injection-Anforderung)."""
    (tmp_path / "Aymen").mkdir()
    (tmp_path / "..").mkdir(exist_ok=True)  # no-op, existiert immer
    result = resolve_artist_by_index(0, library_root=tmp_path)
    assert result == "Aymen"
    assert "/" not in result and ".." not in result
