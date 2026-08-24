"""
Tests fuer services/downloader/download_artifact_cleanup.py.

Deckt beide Strategien ab (siehe Modul-Docstring dort und
docs/MusicBot_ARCH-003_Services_Phase1_Analyse.md, Temp-Cleanup-Abschnitt):
  - cleanup_single_download_artifact() (Strategie C, primaer)
  - cleanup_download_artifacts() (Strategie A, Fallback)

Regel 7: keine echten externen Abhaengigkeiten - reine Dateisystem-Logik,
Logger wird gemockt.
"""

import time
from pathlib import Path
from unittest.mock import Mock

from services.downloader.download_artifact_cleanup import (
    cleanup_download_artifacts,
    cleanup_single_download_artifact,
)


def make_logger():
    return Mock()


# ─────────────────────────────────────────────────────────────────────────
# cleanup_single_download_artifact (Strategie C)
# ─────────────────────────────────────────────────────────────────────────


class TestCleanupSingleDownloadArtifact:
    def test_none_path_is_a_noop(self, tmp_path):
        logger = make_logger()
        cleanup_single_download_artifact(None, tmp_path, logger)
        logger.info.assert_not_called()

    def test_none_download_dir_is_a_noop(self, tmp_path):
        """
        Deckt Config-Fakes ohne DOWNLOAD_DIR-Attribut ab (siehe
        test_metadata_processor_happy_path.py::HappyPathConfig).
        """
        target = tmp_path / "orphan.m4a"
        target.write_bytes(b"data")
        logger = make_logger()

        cleanup_single_download_artifact(target, None, logger)

        assert target.exists()
        logger.info.assert_not_called()

    def test_existing_file_is_deleted(self, tmp_path):
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        target = download_dir / "Track_01_abc.m4a"
        target.write_bytes(b"data")

        cleanup_single_download_artifact(target, download_dir, make_logger())

        assert not target.exists()

    def test_already_moved_file_is_left_alone_no_error(self, tmp_path):
        """
        Deckt den Fall ab, dass move_to_library() vor dem Fehler bereits
        gelaufen ist - original_path existiert am alten Ort nicht mehr.
        Muss ein stiller No-op sein, kein Fehler.
        """
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        already_moved = download_dir / "already_moved.m4a"  # existiert nicht

        cleanup_single_download_artifact(already_moved, download_dir, make_logger())
        # kein Raise = Erfolg

    def test_path_outside_download_dir_is_never_deleted(self, tmp_path):
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        outside_dir = tmp_path / "library"
        outside_dir.mkdir()
        outside_file = outside_dir / "already_in_library.m4a"
        outside_file.write_bytes(b"data")

        cleanup_single_download_artifact(outside_file, download_dir, make_logger())

        assert outside_file.exists()

    def test_matching_info_json_is_deleted_alongside(self, tmp_path):
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        target = download_dir / "Track_01_abc.m4a"
        target.write_bytes(b"data")
        info_json = download_dir / "Track_01_abc.info.json"
        info_json.write_text("{}")

        cleanup_single_download_artifact(target, download_dir, make_logger())

        assert not target.exists()
        assert not info_json.exists()

    def test_missing_info_json_does_not_raise(self, tmp_path):
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        target = download_dir / "Track_01_abc.m4a"
        target.write_bytes(b"data")

        cleanup_single_download_artifact(target, download_dir, make_logger())

        assert not target.exists()  # kein Fehler trotz fehlender .info.json

    def test_unlink_error_is_logged_not_raised(self, tmp_path, monkeypatch):
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        target = download_dir / "Track_01_abc.m4a"
        target.write_bytes(b"data")

        def _boom(self):
            raise OSError("disk error")

        monkeypatch.setattr(Path, "unlink", _boom)

        logger = make_logger()
        cleanup_single_download_artifact(target, download_dir, logger)  # kein Raise

        logger.warning.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# cleanup_download_artifacts (Strategie A)
# ─────────────────────────────────────────────────────────────────────────


def _make_old_file(path: Path, hours_old: float):
    path.write_bytes(b"data")
    old_time = time.time() - hours_old * 3600
    import os

    os.utime(path, (old_time, old_time))


class TestCleanupDownloadArtifacts:
    def test_missing_directory_returns_zero(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        result = cleanup_download_artifacts(missing, make_logger())
        assert result == 0

    def test_old_known_extension_is_deleted(self, tmp_path):
        old_file = tmp_path / "orphaned.m4a"
        _make_old_file(old_file, hours_old=48)

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 1
        assert not old_file.exists()

    def test_recent_file_is_kept(self, tmp_path):
        recent_file = tmp_path / "fresh.m4a"
        recent_file.write_bytes(b"data")  # mtime = jetzt

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 0
        assert recent_file.exists()

    def test_old_but_unknown_extension_is_kept(self, tmp_path):
        old_unknown = tmp_path / "mystery.dat"
        _make_old_file(old_unknown, hours_old=48)

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 0
        assert old_unknown.exists()

    def test_old_part_file_is_never_deleted(self, tmp_path):
        """
        Explizite Sicherheitsanforderung: .part-Dateien laufender Downloads
        duerfen niemals geloescht werden - auch nicht bei hohem Alter.
        """
        old_part = tmp_path / "downloading_track.m4a.part"
        _make_old_file(old_part, hours_old=999)

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 0
        assert old_part.exists()

    def test_old_ytdl_file_is_never_deleted(self, tmp_path):
        old_ytdl = tmp_path / "downloading_track.ytdl"
        _make_old_file(old_ytdl, hours_old=999)

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 0
        assert old_ytdl.exists()

    def test_old_info_json_is_deleted(self, tmp_path):
        old_info = tmp_path / "Track_01_abc.info.json"
        _make_old_file(old_info, hours_old=48)

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 1
        assert not old_info.exists()

    def test_subdirectories_are_never_touched(self, tmp_path):
        subdir = tmp_path / "some_subdir.m4a"  # Name endet zufaellig auf .m4a
        subdir.mkdir()

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 0
        assert subdir.exists()

    def test_multiple_old_files_all_deleted_mixed_with_kept_ones(self, tmp_path):
        old_audio = tmp_path / "old.m4a"
        _make_old_file(old_audio, hours_old=48)
        old_part = tmp_path / "active.m4a.part"
        _make_old_file(old_part, hours_old=48)
        recent_audio = tmp_path / "new.mp3"
        recent_audio.write_bytes(b"data")

        deleted = cleanup_download_artifacts(tmp_path, make_logger(), max_age_hours=24)

        assert deleted == 1
        assert not old_audio.exists()
        assert old_part.exists()
        assert recent_audio.exists()

    def test_default_max_age_is_24_hours(self, tmp_path):
        just_under_24h = tmp_path / "just_under.m4a"
        _make_old_file(just_under_24h, hours_old=23.9)
        just_over_24h = tmp_path / "just_over.m4a"
        _make_old_file(just_over_24h, hours_old=24.1)

        deleted = cleanup_download_artifacts(tmp_path, make_logger())  # kein max_age_hours

        assert deleted == 1
        assert just_under_24h.exists()
        assert not just_over_24h.exists()
