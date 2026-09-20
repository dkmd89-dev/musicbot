# tests/test_library_repair_library_artists.py
# -*- coding: utf-8 -*-
"""services/library_repair/library_artists.py (ARCH-032 Phase 3C)."""

from services.library_repair.library_artists import (
    list_artist_albums,
    list_library_artist_dirs,
    resolve_album_by_index,
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


# ── list_artist_albums() / resolve_album_by_index() (Manual Metadata
# Editing v2) ─────────────────────────────────────────────────────────────


def test_lists_album_directories_sorted(tmp_path):
    (tmp_path / "Bausa" / "2020 - Album B").mkdir(parents=True)
    (tmp_path / "Bausa" / "2019 - Album A").mkdir(parents=True)

    assert list_artist_albums("Bausa", library_root=tmp_path) == [
        "2019 - Album A", "2020 - Album B",
    ]


def test_excludes_singles_case_insensitive(tmp_path):
    (tmp_path / "Bausa" / "2020 - Album X").mkdir(parents=True)
    (tmp_path / "Bausa" / "Singles").mkdir(parents=True)

    assert list_artist_albums("Bausa", library_root=tmp_path) == ["2020 - Album X"]


def test_excludes_singles_uppercase_variant(tmp_path):
    (tmp_path / "Bausa" / "2020 - Album X").mkdir(parents=True)
    (tmp_path / "Bausa" / "SINGLES").mkdir(parents=True)

    assert list_artist_albums("Bausa", library_root=tmp_path) == ["2020 - Album X"]


def test_same_album_title_in_different_directories_stays_distinct(tmp_path):
    """Auftrag §7: zwei Ordner mit demselben sichtbaren Albumnamen
    bleiben unabhaengige Kontexte."""
    (tmp_path / "Bausa" / "2024 - Album X").mkdir(parents=True)
    (tmp_path / "Bausa" / "2025 - Album X").mkdir(parents=True)

    albums = list_artist_albums("Bausa", library_root=tmp_path)
    assert albums == ["2024 - Album X", "2025 - Album X"]
    assert len(set(albums)) == 2  # keine Vermischung


def test_unknown_artist_returns_empty_list(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    assert list_artist_albums("Unknown", library_root=tmp_path) == []


def test_no_albums_only_singles_returns_empty_list(tmp_path):
    (tmp_path / "Bausa" / "Singles").mkdir(parents=True)
    assert list_artist_albums("Bausa", library_root=tmp_path) == []


def test_ignores_hidden_and_symlinked_album_directories(tmp_path):
    (tmp_path / "Bausa" / "2020 - Album X").mkdir(parents=True)
    (tmp_path / "Bausa" / ".hidden").mkdir(parents=True)
    real = tmp_path.parent / "outside_album_dir"
    real.mkdir(exist_ok=True)
    (tmp_path / "Bausa" / "Linked").symlink_to(real)

    assert list_artist_albums("Bausa", library_root=tmp_path) == ["2020 - Album X"]


def test_resolve_album_by_index_returns_matching_album(tmp_path):
    (tmp_path / "Bausa" / "2019 - Album A").mkdir(parents=True)
    (tmp_path / "Bausa" / "2020 - Album B").mkdir(parents=True)

    assert resolve_album_by_index("Bausa", 0, library_root=tmp_path) == "2019 - Album A"
    assert resolve_album_by_index("Bausa", 1, library_root=tmp_path) == "2020 - Album B"


def test_resolve_album_by_index_out_of_range_returns_none(tmp_path):
    (tmp_path / "Bausa" / "2019 - Album A").mkdir(parents=True)
    assert resolve_album_by_index("Bausa", 5, library_root=tmp_path) is None
    assert resolve_album_by_index("Bausa", -1, library_root=tmp_path) is None


def test_resolve_album_by_index_never_returns_singles(tmp_path):
    (tmp_path / "Bausa" / "Singles").mkdir(parents=True)
    (tmp_path / "Bausa" / "2020 - Album X").mkdir(parents=True)

    result = resolve_album_by_index("Bausa", 0, library_root=tmp_path)
    assert result == "2020 - Album X"
    assert result.lower() != "singles"
