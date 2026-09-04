# tests/test_resolve_duplicates_execute.py
# -*- coding: utf-8 -*-
"""
Tests für scripts/resolve_duplicates.py --execute (MusicBot — Duplicate
Resolution Phase 3: SAFE EXECUTE IMPLEMENTATION).

SICHERHEITSREGEL DIESER TESTDATEI (nicht verhandelbar, siehe der reale
Vorfall in docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md Abschnitt
23): JEDER Aufruf von `rd.main([..., "--execute", ...])` in dieser Datei
MUSS explizit mit `--path str(isolated_test_dir)` oder `--artist
<eindeutiger-uuid-name>` auf ein isoliertes, für genau diesen Test
erzeugtes Unterverzeichnis von ALLOWED_ROOT gescoped sein. NIEMALS
`rd.main(["--execute"])` ohne Pfad-Scoping aufrufen - das würde gegen
den GESAMTEN ALLOWED_ROOT (die geteilte, reale Testbibliothek) laufen.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from mutagen.mp4 import MP4

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "resolve_duplicates.py"

_spec = importlib.util.spec_from_file_location("resolve_duplicates_execute", MODULE_PATH)
rd = importlib.util.module_from_spec(_spec)
sys.modules["resolve_duplicates_execute"] = rd
_spec.loader.exec_module(rd)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfügbar")

ALLOWED_ROOT = rd.ALLOWED_ROOT  # /tmp/musicbot_test/library


def _make_real_m4a(
    path: Path, artist: str, title: str, album: str = None, trkn=None,
    duration: float = 1, mb_recording_id: str = None, isrc: str = None,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )
    audio = MP4(path)
    audio["©nam"] = [title]
    audio["©ART"] = [artist]
    if album:
        audio["©alb"] = [album]
    if trkn:
        audio["trkn"] = [(trkn, 0)]
    if mb_recording_id:
        audio["----:com.apple.iTunes:MusicBrainz Recording Id"] = [
            mb_recording_id.encode("utf-8")
        ]
    if isrc:
        audio["----:com.apple.iTunes:ISRC"] = [isrc.encode("utf-8")]
    audio.save()


@pytest.fixture
def isolated_test_dir():
    d = ALLOWED_ROOT / f"_pytest_execute_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _run_execute(isolated_test_dir, tmp_path, extra_args=None):
    """Zentraler, sicherer Wrapper: erzwingt IMMER --path-Scoping des
    GESCANNTEN Verzeichnisses auf das isolierte Testverzeichnis (siehe
    Sicherheitsregel im Modul-Docstring). Die JSON-/JSONL-Ausgabedateien
    (Report/Plan/Audit-Log) werden bewusst NICHT unter ALLOWED_ROOT
    geschrieben, sondern in `tmp_path` (pytest-eigenes, garantiert
    isoliertes Scratch-Verzeichnis außerhalb der Library) - vermeidet
    liegengebliebene Artefakte im geteilten Library-Root."""
    args = ["--path", str(isolated_test_dir), "--execute"] + (extra_args or [])
    with patch.object(rd, "REPORT_JSON_PATH", tmp_path / "dry_run_report.json"), \
         patch.object(rd, "EXECUTION_PLAN_JSON_PATH", tmp_path / "execution_plan.json"), \
         patch.object(rd, "EXECUTION_REPORT_JSON_PATH", tmp_path / "execution_report.json"), \
         patch.object(rd, "AUDIT_LOG_JSONL_PATH", tmp_path / "audit_log.jsonl"):
        exit_code = rd.main(args)
        exec_report = json.loads(rd.EXECUTION_REPORT_JSON_PATH.read_text())
    return exit_code, exec_report


@requires_ffmpeg
class TestExecuteEndToEnd:
    def test_execute_deletes_validated_remove_file(self, isolated_test_dir, tmp_path):
        """Test 1: --execute löscht ein validiertes REMOVE-File."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1)
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1)

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)

        assert exit_code == 0
        assert exec_report["execution_result"] == "SUCCESS"
        assert exec_report["files_deleted"] == 1
        assert not single.exists()
        assert album.exists()

    def test_dry_run_without_execute_deletes_nothing(self, isolated_test_dir, tmp_path):
        """Test 2."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1)
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1)

        with patch.object(rd, "REPORT_JSON_PATH", tmp_path / "dryrun_report.json"):
            exit_code = rd.main(["--path", str(isolated_test_dir)])

        assert exit_code == 0
        assert single.exists()
        assert album.exists()

    def test_manual_review_group_never_deleted_even_with_execute(self, isolated_test_dir, tmp_path):
        """Test 3: MANUAL_REVIEW (hier: Duration-Mismatch, kein MB-ID) -
        --execute löscht trotzdem nichts."""
        track_a = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(track_a, "Artist", "Track", album="Album", trkn=1, duration=1)
        track_b = isolated_test_dir / "Artist" / "2025 - Album" / "02 - Track.m4a"
        _make_real_m4a(track_b, "Artist", "Track", album="Album", trkn=2, duration=3)

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)

        assert exit_code == 0
        assert exec_report["files_deleted"] == 0
        assert exec_report["groups_eligible"] == 0
        assert track_a.exists()
        assert track_b.exists()

    def test_isrc_mismatch_group_never_deleted(self, isolated_test_dir, tmp_path):
        """Zusätzliche Sicherheitsprobe (Phase 2.3-Fix): ISRC-Mismatch
        blockiert weiterhin, auch im Execute-Pfad."""
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1, isrc="ISRC0000001")
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1, isrc="ISRC0000002")

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)

        assert exec_report["files_deleted"] == 0
        assert album.exists()
        assert single.exists()

    def test_forbidden_root_blocks_execute(self):
        """Test 12."""
        exit_code = rd.main(["--path", "/mnt/128ssd", "--execute"])
        assert exit_code == 2

    def test_symlink_escaping_root_blocks_execute(self, isolated_test_dir, tmp_path):
        """Test 13: Symlink-Eskalation nach der Plan-Erstellung - der
        REMOVE-Kandidat wird nach dem Scan durch einen Symlink außerhalb
        des Roots ersetzt, revalidate_group() muss dies erkennen."""
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_target = outside_dir / "escaped.m4a"

        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1)
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1)
        # Kopiere den Inhalt des Singles nach außerhalb, damit Fingerprint
        # (Größe/SHA-256) zunächst noch passen würde, wenn der
        # Symlink-Check NICHT greifen würde.
        shutil.copyfile(single, outside_target)

        original_build_execution_plan = rd.build_execution_plan

        def _plan_then_swap_to_symlink(decisions):
            plan = original_build_execution_plan(decisions)
            single.unlink()
            single.symlink_to(outside_target)
            return plan

        with patch.object(rd, "build_execution_plan", side_effect=_plan_then_swap_to_symlink):
            exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)

        assert exec_report["files_deleted"] == 0
        assert exec_report["path_safety"] == "FAIL"
        # Das eigentliche Ziel außerhalb des Roots darf nicht angetastet sein.
        assert outside_target.exists()

    def test_dry_run_execute_dry_run_shows_expected_new_state(self, isolated_test_dir, tmp_path):
        """Test 18."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1)
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1)

        with patch.object(rd, "REPORT_JSON_PATH", tmp_path / "before_report.json"):
            rd.main(["--path", str(isolated_test_dir)])
            before = json.loads((tmp_path / "before_report.json").read_text())
        assert before["duplicate_groups"] == 1
        assert before["resolved_groups"] == 1

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exit_code == 0
        assert exec_report["files_deleted"] == 1

        with patch.object(rd, "REPORT_JSON_PATH", tmp_path / "after_report.json"):
            rd.main(["--path", str(isolated_test_dir)])
            after = json.loads((tmp_path / "after_report.json").read_text())
        assert after["duplicate_groups"] == 0
        assert after["files_scanned"] == 1
        assert album.exists()
        assert not single.exists()

    def test_manifest_and_audit_log_written_with_expected_fields(self, isolated_test_dir, tmp_path):
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1, mb_recording_id="MB123")
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1, mb_recording_id="MB123")

        plan_path = tmp_path / "plan.json"
        audit_path = tmp_path / "audit.jsonl"
        with patch.object(rd, "REPORT_JSON_PATH", tmp_path / "report.json"), \
             patch.object(rd, "EXECUTION_PLAN_JSON_PATH", plan_path), \
             patch.object(rd, "EXECUTION_REPORT_JSON_PATH", tmp_path / "exec_report.json"), \
             patch.object(rd, "AUDIT_LOG_JSONL_PATH", audit_path):
            rd.main(["--path", str(isolated_test_dir), "--execute"])

        plan = json.loads(plan_path.read_text())
        assert len(plan["entries"]) == 1
        entry = plan["entries"][0]
        assert entry["keep"]["sha256"]
        assert entry["remove"][0]["sha256"]
        assert entry["mb_recording_id"] == "MB123"

        audit_lines = audit_path.read_text().strip().splitlines()
        assert len(audit_lines) == 1
        audit_entry = json.loads(audit_lines[0])
        assert audit_entry["deleted_path"] == str(single)
        assert audit_entry["keep_path"] == str(album)
        assert audit_entry["mb_recording_id"] == "MB123"
        assert "original_sha256" in audit_entry


class TestExecuteBackup:
    """--backup-dir: Per-Datei-Backup VOR jedem --execute-Delete (analog
    zum library_repair-Sicherheitsmodell)."""

    def test_deleted_file_is_backed_up_before_removal(self, isolated_test_dir, tmp_path):
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1, mb_recording_id="MB123")
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1, mb_recording_id="MB123")
        original_bytes = single.read_bytes()

        backup_dir = tmp_path / "backups"
        exit_code, exec_report = _run_execute(
            isolated_test_dir, tmp_path, extra_args=["--backup-dir", str(backup_dir)],
        )

        assert exit_code == 0
        assert not single.exists()
        assert album.exists()
        backups = list(backup_dir.rglob("*.bak"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original_bytes

        audit_path = tmp_path / "audit_log.jsonl"
        audit_entry = json.loads(audit_path.read_text().strip().splitlines()[0])
        assert audit_entry["backup_path"] == str(backups[0])

    def test_default_backup_dir_is_outside_scanned_root(self, isolated_test_dir, tmp_path):
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track", duration=1, mb_recording_id="MB123")
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1, duration=1, mb_recording_id="MB123")
        original_bytes = single.read_bytes()

        default_backup_dir = ALLOWED_ROOT.parent / rd.DEFAULT_BACKUP_DIR_NAME
        # eindeutiger Marker im Pfad (isolated_test_dir-Name) - robust
        # gegen andere/parallele Nutzung derselben Default-Backup-Wurzel.
        marker = isolated_test_dir.name
        try:
            exit_code, _ = _run_execute(isolated_test_dir, tmp_path)
            assert exit_code == 0
            assert not single.exists()
            matches = [
                p for p in default_backup_dir.rglob("*.bak")
                if marker in str(p) and p.name.startswith(single.name)
                and p.read_bytes() == original_bytes
            ]
            assert len(matches) == 1
        finally:
            for p in default_backup_dir.rglob("*.bak"):
                if marker in str(p):
                    p.unlink(missing_ok=True)


@requires_ffmpeg
class TestExecuteRegressionKnownCases:
    """Auftrag Phase 3 Abschnitt 19: alle bekannten Fälle müssen unter
    --execute weiterhin exakt funktionieren - hier mit den real
    gemessenen Tag-Werten nachgebildet (kein Zugriff auf die geteilte
    Bibliothek, siehe Modul-Docstring)."""

    def test_dein_luegner_pattern_album_kept_single_removed(self, isolated_test_dir, tmp_path):
        single = isolated_test_dir / "makko" / "Singles" / "2023 - Dein Lügner.m4a"
        _make_real_m4a(single, "makko", "Dein Lügner", duration=1, mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96")
        album = isolated_test_dir / "makko" / "2023 - Lieb mich oder lass es, Pt.1+2" / "15 - Dein Lügner.m4a"
        _make_real_m4a(album, "makko", "Dein Lügner", album="Lieb mich oder lass es, Pt.1+2", trkn=15, duration=1, mb_recording_id="13958616-333e-44d0-9c2d-06c31e517a96")

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exec_report["files_deleted"] == 1
        assert album.exists()
        assert not single.exists()

    def test_pueblo_pattern_no_mb_id_still_removed(self, isolated_test_dir, tmp_path):
        single = isolated_test_dir / "makko" / "Singles" / "2023 - Pueblo.m4a"
        _make_real_m4a(single, "makko", "Pueblo", duration=1)
        album = isolated_test_dir / "makko" / "2023 - Lieb mich oder lass es, Pt.1+2" / "14 - Pueblo.m4a"
        _make_real_m4a(album, "makko", "Pueblo", album="Lieb mich oder lass es, Pt.1+2", trkn=14, duration=1)

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exec_report["files_deleted"] == 1
        assert album.exists()
        assert not single.exists()

    def test_nachts_wach_pattern_manual_review_nothing_deleted(self, isolated_test_dir, tmp_path):
        track_02 = isolated_test_dir / "makko" / "2022 - Nachts wach (Remix EP)" / "02 - Nachts wach.m4a"
        _make_real_m4a(track_02, "makko", "Nachts wach", album="Nachts wach (Remix EP)", trkn=2, duration=1)
        track_04 = isolated_test_dir / "makko" / "2022 - Nachts wach (Remix EP)" / "04 - Nachts wach.m4a"
        _make_real_m4a(track_04, "makko", "Nachts wach", album="Nachts wach (Remix EP)", trkn=4, duration=3)

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exec_report["files_deleted"] == 0
        assert exec_report["groups_eligible"] == 0
        assert track_02.exists()
        assert track_04.exists()

    def test_badchieff_pattern_album_kept_both_singles_removed(self, isolated_test_dir, tmp_path):
        single_1 = isolated_test_dir / "Badchieff" / "Singles" / "2025 - GUT AUS (1).m4a"
        _make_real_m4a(single_1, "Badchieff", "GUT AUS", duration=1, isrc="DEQ322500136")
        single_2 = isolated_test_dir / "Badchieff" / "Singles" / "2025 - GUT AUS.m4a"
        _make_real_m4a(single_2, "Badchieff", "GUT AUS", duration=1, isrc="DEQ322500136")
        album = isolated_test_dir / "Badchieff" / "2025 - HEUTE ODER GESTERN" / "12 - GUT AUS.m4a"
        _make_real_m4a(album, "Badchieff", "GUT AUS", album="HEUTE ODER GESTERN", trkn=12, duration=1, isrc="DEQ322500136")

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exec_report["files_deleted"] == 2
        assert album.exists()
        assert not single_1.exists()
        assert not single_2.exists()

    def test_quote_normalized_pattern_bequem_style_removed(self, isolated_test_dir, tmp_path):
        """Bequem/Grad-mal-ein-Jahr-Muster (Phase 2.2-Fix): Single-Tag
        mit umschließenden Anführungszeichen, Album-Tag ohne."""
        single = isolated_test_dir / "makko" / "Singles" / "2021 - Bequem.m4a"
        _make_real_m4a(single, "makko", '"Bequem"', duration=1, mb_recording_id="5b72dd3a-49b0-46af-84cf-632137d31fa4")
        album = isolated_test_dir / "makko" / "2021 - Leb es oder lass es 2" / "11 - Bequem.m4a"
        _make_real_m4a(album, "makko", "Bequem", album="Leb es oder lass es 2", trkn=11, duration=1, mb_recording_id="5b72dd3a-49b0-46af-84cf-632137d31fa4")

        exit_code, exec_report = _run_execute(isolated_test_dir, tmp_path)
        assert exec_report["files_deleted"] == 1
        assert album.exists()
        assert not single.exists()
