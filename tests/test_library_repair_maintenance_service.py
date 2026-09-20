# tests/test_library_repair_maintenance_service.py
# -*- coding: utf-8 -*-
"""services/library_repair/maintenance_service.py (ARCH-032 Phase 3B).

Command-getriebener Maintenance-Flow gegen echte, isolierte m4a-Test-
dateien (nie die Produktions-Library, ARCH-032 Auftrag §21)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from mutagen.mp4 import MP4, MP4FreeForm

import services.library_repair.run_tracking as rt
from services.library_repair import maintenance_service as ms

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _m4a(path: Path, *, genre=None, artist=None, artists_ff=None, album=None, album_artist=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )
    a = MP4(path)
    a["©nam"] = ["T"]
    if genre:
        a["©gen"] = [genre]
    if artist:
        a["©ART"] = artist if isinstance(artist, list) else [artist]
    if artists_ff:
        a["----:com.apple.iTunes:ARTISTS"] = [MP4FreeForm(x.encode()) for x in artists_ff]
    if album:
        a["©alb"] = [album]
    if album_artist:
        a["aART"] = [album_artist]
    a.save()


def _set_legacy_genre(path: Path, value: str) -> None:
    a = MP4(path)
    a["----:com.apple.iTunes:GENRE"] = [MP4FreeForm(value.encode("utf-8"))]
    a.save()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(rt.Config, "DATA_DIR", data_dir)
    yield data_dir


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


@pytest.fixture
def mapping_dir(tmp_path):
    d = tmp_path / "mapping"
    d.mkdir()
    return d


# ── artist_targets() ─────────────────────────────────────────────────────


def test_artist_targets_lists_m4a_files_under_artist_dir(lib):
    (lib / "Bausa" / "Singles").mkdir(parents=True)
    (lib / "Bausa" / "Singles" / "a.m4a").touch()
    (lib / "Bausa" / "Singles" / "b.m4a").touch()
    (lib / "Bausa" / "notes.txt").touch()

    targets = ms.artist_targets("Bausa", library_root=lib)
    assert targets == ["Bausa/Singles/a.m4a", "Bausa/Singles/b.m4a"]


def test_artist_targets_unknown_artist_returns_empty(lib):
    lib.mkdir()
    assert ms.artist_targets("Unknown", library_root=lib) == []


# ── resolve_target_genre() ───────────────────────────────────────────────


def test_resolve_target_genre_manual_value():
    assert ms.resolve_target_genre("Filow", genre="Pop / Rock") == "Pop; Rock"


def test_resolve_target_genre_from_mapping(mapping_dir):
    (mapping_dir / "artist_genre.yaml").write_text(
        yaml.safe_dump({"ARTIST_GENRE_MAP": {"filow": {"primary": "Deutschrap"}}}),
        encoding="utf-8",
    )
    assert ms.resolve_target_genre(
        "Filow", from_mapping=True, mapping_dir=mapping_dir
    ) == "Deutschrap"


def test_resolve_target_genre_from_mapping_unknown_artist_raises(mapping_dir):
    (mapping_dir / "artist_genre.yaml").write_text(
        yaml.safe_dump({"ARTIST_GENRE_MAP": {}}), encoding="utf-8"
    )
    with pytest.raises(ms.MaintenanceServiceError):
        ms.resolve_target_genre("Unknown", from_mapping=True, mapping_dir=mapping_dir)


def test_resolve_target_genre_no_genre_and_no_mapping_raises():
    with pytest.raises(ms.MaintenanceServiceError):
        ms.resolve_target_genre("Filow")


# ── Artist Casing: Preview + Execute ────────────────────────────────────


@requires_ffmpeg
class TestArtistCasingFlow:
    def test_preview_is_read_only(self, lib, mapping_dir):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (mapping_dir / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        preview = ms.preview_artist_casing("Bausa", library_root=lib, mapping_dir=mapping_dir)
        assert preview.read_only is True
        assert preview.target_count == 1
        assert preview.changed_count == 1
        # Datei tatsaechlich unveraendert:
        assert MP4(p).tags["©ART"] == ["bausa"]
        # Journal wurde nicht auf die Platte geschrieben:
        assert not rt.journal_path().exists()

    def test_execute_writes_and_records_run(self, lib, mapping_dir):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (mapping_dir / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        result = ms.execute_artist_casing_fix(
            "Bausa", triggered_by="test", library_root=lib, mapping_dir=mapping_dir,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert result.success_count == 1
        assert MP4(p).tags["©ART"] == ["Bausa"]

        history = rt.load_repair_history()
        assert len(history) == 1
        assert history[0]["kind"] == rt.KIND_MAINTENANCE
        assert history[0]["level"] == "ARTIST_CASING"
        assert rt.is_repair_running() is False  # Lock wieder freigegeben

    def test_execute_shares_lock_with_repair_flow(self, lib, mapping_dir):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p, artist=["bausa"])
        (mapping_dir / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                ms.execute_artist_casing_fix(
                    "Bausa", triggered_by="test", library_root=lib, mapping_dir=mapping_dir,
                )
        finally:
            rt.release_repair_lock()


# ── Legacy Genre Cleanup: Preview + Execute ─────────────────────────────


@requires_ffmpeg
class TestLegacyGenreCleanupFlow:
    def test_preview_is_read_only(self, lib):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p, genre="Pop")
        _set_legacy_genre(p, "Pop")

        preview = ms.preview_legacy_genre_cleanup("Filow", library_root=lib)
        assert preview.changed_count == 1
        assert MP4(p).tags.get("----:com.apple.iTunes:GENRE") is not None

    def test_execute_removes_legacy_atom(self, lib):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p, genre="Pop")
        _set_legacy_genre(p, "Pop")

        result = ms.execute_legacy_genre_cleanup("Filow", triggered_by="test", library_root=lib)
        assert result.status == rt.STATUS_SUCCESS
        assert MP4(p).tags.get("----:com.apple.iTunes:GENRE") is None


# ── Set Genre: Preview + Execute ────────────────────────────────────────


@requires_ffmpeg
class TestSetGenreFlow:
    def test_execute_with_manual_genre(self, lib):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)

        result = ms.execute_set_genre(
            "Filow", triggered_by="test", genre="Deutschrap; Hip Hop", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert MP4(p).tags["©gen"] == ["Deutschrap; Hip Hop"]

    def test_execute_with_mapping(self, lib, mapping_dir):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p)
        (mapping_dir / "artist_genre.yaml").write_text(
            yaml.safe_dump({"ARTIST_GENRE_MAP": {"filow": {"primary": "Deutschrap"}}}),
            encoding="utf-8",
        )

        result = ms.execute_set_genre(
            "Filow", triggered_by="test", from_mapping=True,
            library_root=lib, mapping_dir=mapping_dir,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert MP4(p).tags["©gen"] == ["Deutschrap"]

    def test_only_if_missing_skips_existing_genre(self, lib):
        p = lib / "Filow" / "Singles" / "a.m4a"
        _m4a(p, genre="Existing")

        result = ms.execute_set_genre(
            "Filow", triggered_by="test", genre="Pop",
            only_if_missing=True, library_root=lib,
        )
        assert result.status == rt.STATUS_SKIPPED
        assert MP4(p).tags["©gen"] == ["Existing"]


# ── Partial Success (Auftrag §8.5) ──────────────────────────────────────


@requires_ffmpeg
class TestPartialSuccess:
    def test_mixed_success_and_failed_reports_both_counts(self, lib, mapping_dir, monkeypatch):
        p1 = lib / "Bausa" / "Singles" / "a.m4a"
        p2 = lib / "Bausa" / "Singles" / "b.m4a"
        _m4a(p1, artist=["bausa"])
        _m4a(p2, artist=["bausa"])
        (mapping_dir / "artist_overrides.json").write_text(
            json.dumps({"bausa": "Bausa"}), encoding="utf-8"
        )

        import services.library_repair.executor as _exec

        real_md5 = _exec._audio_essence_md5
        calls = {"n": 0}

        def _flaky(path):
            calls["n"] += 1
            # Pro Datei 2 Aufrufe (audio_before, audio_tmp); nur der
            # 4. Aufruf (audio_tmp der zweiten Datei) schlaegt fehl ->
            # Datei 1 SUCCESS, Datei 2 FAILED.
            if calls["n"] == 4:
                return "DIFFERENT"
            return real_md5(path)

        monkeypatch.setattr(_exec, "_audio_essence_md5", _flaky)

        result = ms.execute_artist_casing_fix(
            "Bausa", triggered_by="test", library_root=lib, mapping_dir=mapping_dir,
        )
        assert result.success_count == 1
        assert result.failed_count == 1
        # Gesamtstatus bleibt SUCCESS (mind. eine Datei erfolgreich,
        # identische Semantik zu repair_service.py::RepairRunResult) -
        # success_count/failed_count tragen die Partial-Info fuer die
        # Praesentationsschicht.
        assert result.status == rt.STATUS_SUCCESS


# ── resolve_track_by_index() / current_title() (Manual Title Editing) ────


@requires_ffmpeg
class TestResolveTrackByIndex:
    def test_resolves_valid_index(self, lib):
        p1 = lib / "Bausa" / "Singles" / "a.m4a"
        p2 = lib / "Bausa" / "Singles" / "b.m4a"
        _m4a(p1)
        _m4a(p2)
        assert ms.resolve_track_by_index("Bausa", 0, library_root=lib) == "Bausa/Singles/a.m4a"
        assert ms.resolve_track_by_index("Bausa", 1, library_root=lib) == "Bausa/Singles/b.m4a"

    def test_out_of_range_returns_none(self, lib):
        p1 = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p1)
        assert ms.resolve_track_by_index("Bausa", 5, library_root=lib) is None
        assert ms.resolve_track_by_index("Bausa", -1, library_root=lib) is None

    def test_unknown_artist_returns_none(self, lib):
        lib.mkdir()
        assert ms.resolve_track_by_index("Unknown", 0, library_root=lib) is None


@requires_ffmpeg
class TestCurrentTitle:
    def test_reads_title_tag(self, lib):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)
        assert ms.current_title("Bausa/Singles/a.m4a", library_root=lib) == "T"


# ── _validate_manual_value() ─────────────────────────────────────────────


class TestValidateManualValue:
    def test_trims_whitespace(self):
        assert ms._validate_manual_value("  Neu  ", label="X") == "Neu"

    def test_none_raises(self):
        with pytest.raises(ms.MaintenanceServiceError):
            ms._validate_manual_value(None, label="X")

    def test_empty_raises(self):
        with pytest.raises(ms.MaintenanceServiceError):
            ms._validate_manual_value("   ", label="X")

    def test_newline_raises(self):
        with pytest.raises(ms.MaintenanceServiceError):
            ms._validate_manual_value("a\nb", label="X")

    def test_too_long_raises(self):
        with pytest.raises(ms.MaintenanceServiceError):
            ms._validate_manual_value("x" * 201, label="X")

    def test_max_length_accepted(self):
        assert ms._validate_manual_value("x" * 200, label="X") == "x" * 200


# ── Manual Artist Editing: Preview + Execute (Auftrag Abschnitt 5-7) ─────


@requires_ffmpeg
class TestArtistRenameFlow:
    def test_preview_is_read_only(self, lib):
        p = lib / "Macloud" / "Singles" / "a.m4a"
        _m4a(p, artist=["Macloud"])

        preview = ms.preview_artist_rename("Macloud", "Miksu & Macloud", library_root=lib)
        assert preview.read_only is True
        assert preview.target_count == 1
        assert preview.changed_count == 1
        assert MP4(p).tags["©ART"] == ["Macloud"]
        assert not rt.journal_path().exists()

    def test_identical_value_yields_zero_changed(self, lib):
        p = lib / "Macloud" / "Singles" / "a.m4a"
        _m4a(p, artist=["Macloud"])

        preview = ms.preview_artist_rename("Macloud", "Macloud", library_root=lib)
        assert preview.target_count == 1
        assert preview.changed_count == 0

    def test_execute_writes_and_records_run(self, lib):
        p = lib / "Macloud" / "Singles" / "a.m4a"
        _m4a(p, artist=["Macloud"])

        result = ms.execute_artist_rename(
            "Macloud", "Miksu & Macloud", triggered_by="test", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert result.success_count == 1
        assert MP4(p).tags["©ART"] == ["Miksu & Macloud"]

        history = rt.load_repair_history()
        assert len(history) == 1
        assert history[0]["kind"] == rt.KIND_MAINTENANCE
        assert history[0]["level"] == "ARTIST_RENAME"
        assert rt.is_repair_running() is False

    def test_execute_with_empty_new_value_raises_without_writing(self, lib):
        p = lib / "Macloud" / "Singles" / "a.m4a"
        _m4a(p, artist=["Macloud"])

        with pytest.raises(ms.MaintenanceServiceError):
            ms.execute_artist_rename("Macloud", "   ", triggered_by="test", library_root=lib)
        assert MP4(p).tags["©ART"] == ["Macloud"]
        assert rt.is_repair_running() is False  # Lock nicht haengen geblieben

    def test_execute_shares_lock_with_repair_flow(self, lib):
        p = lib / "Macloud" / "Singles" / "a.m4a"
        _m4a(p, artist=["Macloud"])

        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                ms.execute_artist_rename(
                    "Macloud", "Miksu & Macloud", triggered_by="test", library_root=lib,
                )
        finally:
            rt.release_repair_lock()


# ── Manual Title Editing: Preview + Execute (Auftrag Abschnitt 8/9) ──────


@requires_ffmpeg
class TestTitleEditFlow:
    def test_preview_is_read_only(self, lib):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)

        preview = ms.preview_title_edit(
            "Bausa", "Bausa/Singles/a.m4a", "Neuer Titel", library_root=lib,
        )
        assert preview.read_only is True
        assert preview.target_count == 1
        assert preview.changed_count == 1
        assert MP4(p).tags["©nam"] == ["T"]
        assert not rt.journal_path().exists()

    def test_identical_value_yields_zero_changed(self, lib):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)

        preview = ms.preview_title_edit("Bausa", "Bausa/Singles/a.m4a", "T", library_root=lib)
        assert preview.changed_count == 0

    def test_execute_writes_and_records_run(self, lib):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)

        result = ms.execute_title_edit(
            "Bausa", "Bausa/Singles/a.m4a", "Neuer Titel", triggered_by="test", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert result.success_count == 1
        assert MP4(p).tags["©nam"] == ["Neuer Titel"]

        history = rt.load_repair_history()
        assert len(history) == 1
        assert history[0]["kind"] == rt.KIND_MAINTENANCE
        assert history[0]["level"] == "TITLE_EDIT"

    def test_no_automatic_title_cleanup(self, lib):
        """Auftrag Abschnitt 8/9: kein TitleCleaner auf den manuellen
        Zielwert - Marketing-Suffix bleibt exakt wie eingegeben."""
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)

        result = ms.execute_title_edit(
            "Bausa", "Bausa/Singles/a.m4a", '"Titel" prod. XY',
            triggered_by="test", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert MP4(p).tags["©nam"] == ['"Titel" prod. XY']

    def test_execute_shares_lock_with_repair_flow(self, lib):
        p = lib / "Bausa" / "Singles" / "a.m4a"
        _m4a(p)

        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                ms.execute_title_edit(
                    "Bausa", "Bausa/Singles/a.m4a", "Neuer Titel",
                    triggered_by="test", library_root=lib,
                )
        finally:
            rt.release_repair_lock()


# ── _resolve_within_library() (Defense-in-Depth) ─────────────────────────


class TestResolveWithinLibrary:
    def test_in_bounds_path_resolves(self, tmp_path):
        (tmp_path / "a.m4a").touch()
        result = ms._resolve_within_library("a.m4a", tmp_path)
        assert result == (tmp_path / "a.m4a").resolve()

    def test_traversal_outside_library_raises(self, tmp_path):
        outside = tmp_path.parent / "outside_lib_test"
        outside.mkdir(exist_ok=True)
        with pytest.raises(ms.MaintenanceServiceError):
            ms._resolve_within_library("../outside_lib_test", tmp_path)


# ── album_targets() / current_album() / current_album_artist() ──────────


@requires_ffmpeg
class TestAlbumTargets:
    def test_lists_m4a_files_under_album_dir(self, lib):
        (lib / "Bausa" / "2020 - Album X" / "01.m4a").parent.mkdir(parents=True)
        (lib / "Bausa" / "2020 - Album X" / "01.m4a").touch()
        (lib / "Bausa" / "2020 - Album X" / "02.m4a").touch()
        (lib / "Bausa" / "2020 - Album X" / "notes.txt").touch()

        targets = ms.album_targets("Bausa", "2020 - Album X", library_root=lib)
        assert targets == [
            "Bausa/2020 - Album X/01.m4a", "Bausa/2020 - Album X/02.m4a",
        ]

    def test_unknown_album_returns_empty(self, lib):
        (lib / "Bausa").mkdir(parents=True)
        assert ms.album_targets("Bausa", "Unknown Album", library_root=lib) == []

    def test_different_album_dirs_stay_independent(self, lib):
        """Auftrag §7: zwei Ordner mit identischem sichtbaren Albumnamen
        bleiben unabhaengige Scopes."""
        (lib / "Bausa" / "2024 - Album X" / "a.m4a").parent.mkdir(parents=True)
        (lib / "Bausa" / "2024 - Album X" / "a.m4a").touch()
        (lib / "Bausa" / "2025 - Album X" / "a.m4a").parent.mkdir(parents=True)
        (lib / "Bausa" / "2025 - Album X" / "a.m4a").touch()

        targets_2024 = ms.album_targets("Bausa", "2024 - Album X", library_root=lib)
        targets_2025 = ms.album_targets("Bausa", "2025 - Album X", library_root=lib)
        assert targets_2024 == ["Bausa/2024 - Album X/a.m4a"]
        assert targets_2025 == ["Bausa/2025 - Album X/a.m4a"]
        assert set(targets_2024).isdisjoint(targets_2025)


@requires_ffmpeg
class TestCurrentAlbumAndAlbumArtist:
    def test_reads_representative_album_value(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "01.m4a"
        _m4a(p, album="Album X")
        assert ms.current_album("Bausa", "2020 - Album X", library_root=lib) == "Album X"

    def test_empty_when_no_targets(self, lib):
        (lib / "Bausa").mkdir(parents=True)
        assert ms.current_album("Bausa", "Unknown", library_root=lib) == ""

    def test_reads_representative_album_artist_value(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "01.m4a"
        _m4a(p, album_artist="Bausa")
        assert ms.current_album_artist("Bausa", "2020 - Album X", library_root=lib) == "Bausa"


# ── Manual Album Editing: Preview + Execute (Auftrag Abschnitt 6-9) ──────


@requires_ffmpeg
class TestAlbumEditFlow:
    def test_preview_is_read_only(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album="Album X")

        preview = ms.preview_album_edit("Bausa", "2020 - Album X", "Album X (Deluxe)", library_root=lib)
        assert preview.read_only is True
        assert preview.target_count == 1
        assert preview.changed_count == 1
        assert MP4(p).tags["©alb"] == ["Album X"]
        assert not rt.journal_path().exists()

    def test_identical_value_yields_zero_changed(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album="Album X")

        preview = ms.preview_album_edit("Bausa", "2020 - Album X", "Album X", library_root=lib)
        assert preview.changed_count == 0

    def test_execute_writes_and_records_run(self, lib):
        p1 = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        p2 = lib / "Bausa" / "2020 - Album X" / "b.m4a"
        _m4a(p1, album="Album X")
        _m4a(p2, album="Album X")

        result = ms.execute_album_edit(
            "Bausa", "2020 - Album X", "Album X (Deluxe)", triggered_by="test", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        assert result.success_count == 2
        assert MP4(p1).tags["©alb"] == ["Album X (Deluxe)"]
        assert MP4(p2).tags["©alb"] == ["Album X (Deluxe)"]

        history = rt.load_repair_history()
        assert len(history) == 1
        assert history[0]["kind"] == rt.KIND_MAINTENANCE
        assert history[0]["level"] == "ALBUM_EDIT"
        assert rt.is_repair_running() is False

    def test_execute_with_empty_value_raises_without_writing(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album="Album X")

        with pytest.raises(ms.MaintenanceServiceError):
            ms.execute_album_edit("Bausa", "2020 - Album X", "   ", triggered_by="test", library_root=lib)
        assert MP4(p).tags["©alb"] == ["Album X"]
        assert rt.is_repair_running() is False

    def test_execute_shares_lock_with_repair_flow(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album="Album X")

        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                ms.execute_album_edit(
                    "Bausa", "2020 - Album X", "Neu", triggered_by="test", library_root=lib,
                )
        finally:
            rt.release_repair_lock()


# ── Manual Album Artist Editing: Preview + Execute (Auftrag §10-13) ─────


@requires_ffmpeg
class TestAlbumArtistEditFlow:
    def test_preview_is_read_only(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album_artist="Bausa")

        preview = ms.preview_album_artist_edit(
            "Bausa", "2020 - Album X", "Bausa & Friends", library_root=lib,
        )
        assert preview.read_only is True
        assert preview.target_count == 1
        assert preview.changed_count == 1
        assert MP4(p).tags["aART"] == ["Bausa"]

    def test_identical_value_yields_zero_changed(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album_artist="Bausa")

        preview = ms.preview_album_artist_edit("Bausa", "2020 - Album X", "Bausa", library_root=lib)
        assert preview.changed_count == 0

    def test_execute_writes_only_album_artist(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album_artist="Bausa", artist=["Bausa"], album="Album X")

        result = ms.execute_album_artist_edit(
            "Bausa", "2020 - Album X", "Bausa & Friends", triggered_by="test", library_root=lib,
        )
        assert result.status == rt.STATUS_SUCCESS
        tags = MP4(p).tags
        assert tags["aART"] == ["Bausa & Friends"]
        assert tags["©ART"] == ["Bausa"]
        assert tags["©alb"] == ["Album X"]

        history = rt.load_repair_history()
        assert history[0]["level"] == "ALBUM_ARTIST_EDIT"

    def test_execute_shares_lock_with_repair_flow(self, lib):
        p = lib / "Bausa" / "2020 - Album X" / "a.m4a"
        _m4a(p, album_artist="Bausa")

        rt.acquire_repair_lock()
        try:
            with pytest.raises(rt.RepairAlreadyRunningError):
                ms.execute_album_artist_edit(
                    "Bausa", "2020 - Album X", "Neu", triggered_by="test", library_root=lib,
                )
        finally:
            rt.release_repair_lock()
