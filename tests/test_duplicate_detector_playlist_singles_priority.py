"""
Playlist-Prioritaet (Nutzer-Wunsch 2026-09-02): DuplicateDetector.
resolve_playlist_single_conflict() - siehe ausfuehrlicher Docstring in
services/duplicate/detector.py.

Live beobachtet: "Zartmann/Singles/2024 - wie du manchmal fehlst.m4a"
existierte bereits, als dieselbe Aufnahme Teil der Playlist
"Zartmann - dafuer bin ich frei EP" war - der Track fehlte danach im
Album, weil entweder der Metadata-Cache-Kurzschluss (CacheManager) oder
der Playlist-Duplikat-Check den Track uebersprang, statt ihn in den
Album-Ordner einzusortieren. Diese Tests decken NUR die neue Methode
isoliert ab (services/duplicate/detector.py) - der Aufruf innerhalb von
_process_playlist_download() wird in
tests/test_playlist_singles_priority_pre_check.py getestet.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.duplicate.detector import DuplicateDetector
from services.downloader.models import DuplicateEntry


def make_detector(tmp_path, config_overrides=None):
    config = MagicMock()
    config.LIBRARY_DIR = str(tmp_path / "library")
    config.DUPLICATE_CACHE_DIR = str(tmp_path / "duplicate_cache")
    config.ARTIST_OVERRIDE_FILE = str(tmp_path / "artist_overrides.json")
    config.GENRE_MAPPING_DIR = None
    if config_overrides:
        for k, v in config_overrides.items():
            setattr(config, k, v)

    detector = DuplicateDetector(config=config, logger_factory=lambda name: MagicMock())
    # Normalisierung/Titel-Bereinigung soll den rohen Wert unveraendert
    # durchreichen, damit die Tests sich auf die Konflikt-Logik selbst
    # konzentrieren koennen statt auf ArtistProcessor/ArtistNormalizer-
    # Details (die haben eigene, dedizierte Tests).
    detector._normalize_artist_for_comparison = lambda a: a
    detector._clean_title_for_comparison = lambda t, a=None: t
    return detector


class TestResolvePlaylistSingleConflict:
    def test_deletes_singles_file_and_returns_path(self, tmp_path):
        detector = make_detector(tmp_path)
        singles_dir = tmp_path / "library" / "Zartmann" / "Singles"
        singles_dir.mkdir(parents=True)
        singles_file = singles_dir / "2024 - wie du manchmal fehlst.m4a"
        singles_file.write_bytes(b"x")

        result = detector.resolve_playlist_single_conflict(
            "Zartmann", "wie du manchmal fehlst"
        )

        assert result == singles_file
        assert not singles_file.exists()

    def test_invalidates_duplicate_cache_entry_after_deletion(self, tmp_path):
        detector = make_detector(tmp_path)
        singles_dir = tmp_path / "library" / "Zartmann" / "Singles"
        singles_dir.mkdir(parents=True)
        singles_file = singles_dir / "2024 - wie du manchmal fehlst.m4a"
        singles_file.write_bytes(b"x")

        entry = DuplicateEntry(
            artist="Zartmann",
            title="wie du manchmal fehlst",
            url="https://youtu.be/OLD_SINGLE",
            file_path=singles_file,
            download_date=datetime.now(),
        )
        detector.duplicate_cache.add_entry(entry)
        assert detector.duplicate_cache.check_content_duplicate(
            "Zartmann", "wie du manchmal fehlst"
        )

        detector.resolve_playlist_single_conflict(
            "Zartmann", "wie du manchmal fehlst"
        )

        assert (
            detector.duplicate_cache.check_content_duplicate(
                "Zartmann", "wie du manchmal fehlst"
            )
            is None
        )
        assert detector.duplicate_cache.check_url_duplicate(
            "https://youtu.be/OLD_SINGLE"
        ) is None

    def test_does_not_touch_files_outside_singles_folder(self, tmp_path):
        """Ein Treffer in einem ANDEREN Album darf nicht geloescht werden -
        nur ein exakter 'Singles'-Ordner-Treffer loest die Prioritaets-
        Logik aus (siehe Docstring: bewusst konservativ)."""
        detector = make_detector(tmp_path)
        album_dir = tmp_path / "library" / "Zartmann" / "2023 - Anderes Album"
        album_dir.mkdir(parents=True)
        album_file = album_dir / "wie du manchmal fehlst.m4a"
        album_file.write_bytes(b"x")

        result = detector.resolve_playlist_single_conflict(
            "Zartmann", "wie du manchmal fehlst"
        )

        assert result is None
        assert album_file.exists()

    def test_no_conflict_returns_none(self, tmp_path):
        detector = make_detector(tmp_path)

        result = detector.resolve_playlist_single_conflict("Unbekannt", "Nichts")

        assert result is None

    def test_falls_back_to_library_scan_when_cache_empty(self, tmp_path):
        """Nach einem Neustart ohne register_download() ist der Duplicate-
        Cache leer - resolve_playlist_single_conflict() muss trotzdem ueber
        den Library-Scan-Fallback (wie check_for_duplicates()) einen
        physisch vorhandenen Singles-Treffer finden."""
        detector = make_detector(tmp_path)
        singles_dir = tmp_path / "library" / "Aymen" / "Singles"
        singles_dir.mkdir(parents=True)
        singles_file = singles_dir / "2025 - Capri Sun.m4a"
        singles_file.write_bytes(b"x")

        result = detector.resolve_playlist_single_conflict("Aymen", "Capri Sun")

        assert result == singles_file
        assert not singles_file.exists()

    def test_unlink_failure_is_caught_and_returns_none(self, tmp_path, monkeypatch):
        detector = make_detector(tmp_path)
        singles_dir = tmp_path / "library" / "Zartmann" / "Singles"
        singles_dir.mkdir(parents=True)
        singles_file = singles_dir / "2024 - x.m4a"
        singles_file.write_bytes(b"x")

        def boom(self):
            raise OSError("locked")

        monkeypatch.setattr(Path, "unlink", boom)

        result = detector.resolve_playlist_single_conflict("Zartmann", "x")

        assert result is None
        assert singles_file.exists()  # unveraendert, da Loeschen fehlschlug
