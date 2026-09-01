"""
Tests fuer scripts/normalize_test_library_loudness.py (isoliertes
LUFS-Reprocessing der Test-Bibliothek).

`scripts/` ist bewusst kein Python-Package - das Modul wird deshalb ueber
importlib direkt per Dateipfad geladen (identisches Muster wie
tests/test_reprocess_artist_metadata.py).

Test-Strategie (CLAUDE.md Abschnitt 7/8): reine, netzwerkfreie Logik
(Path-Safety, Report-Struktur, Exit-Codes) wird deterministisch getestet.
Ein kleiner Teil nutzt echte, per ffmpeg erzeugte m4a-Dateien (winzige
1-Sekunden-Clips) fuer den tatsaechlichen Lautheits-Mess-/Normalisierungs-
Pfad - AudioEnhancer.normalize_loudness() selbst wird dabei NICHT gemockt,
wo es um den eigentlichen Normalisierungs-Regressionsschutz geht (Test 5/9),
aber gezielt gemockt, wo nur die Delegation/Fehlerbehandlung/der Backup-
Sicherheitsnetz-Pfad bewiesen werden soll (Tests 6/7/13) - passend zur im
Auftrag ausdruecklich erlaubten Mocking-Policy ("Mocks verwenden, wo reale
FFmpeg-Ausfuehrung fuer Unit-Tests nicht erforderlich ist").

WICHTIGER FUND waehrend der Implementierung (siehe Modul-Docstring von
normalize_test_library_loudness.py): AudioEnhancer.normalize_loudness()
hinterlaesst eine leere 0-Byte-Datei (meldet aber True/Erfolg), wenn die
Eingabedatei ein eingebettetes Cover hat, da der FFmpeg-apply-Aufruf ohne
"-map 0:a"/"-vn" auch das Cover als Videostream re-encodieren will, was im
ipod/mp4-Container fehlschlaegt. Test 13 (test_backup_restores_file_when_
audio_enhancer_leaves_it_corrupted) verankert das als dauerhaften
Regressionstest fuer das in diesem Script eingebaute Backup/Restore-
Sicherheitsnetz - NICHT fuer utils/audio_enhancer.py selbst, das laut
Auftrag unveraendert bleibt.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from mutagen.mp4 import MP4, MP4Cover

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "normalize_test_library_loudness.py"

_spec = importlib.util.spec_from_file_location(
    "normalize_test_library_loudness", MODULE_PATH
)
nll = importlib.util.module_from_spec(_spec)
sys.modules["normalize_test_library_loudness"] = nll
_spec.loader.exec_module(nll)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG_AVAILABLE and FFPROBE_AVAILABLE),
    reason="ffmpeg/ffprobe nicht auf PATH verfuegbar",
)

ALLOWED_ROOT = nll.ALLOWED_ROOT  # /tmp/musicbot_test/library


def _make_quiet_m4a(path: Path, duration_seconds: float = 1.0):
    """Erzeugt eine leise (weit unter -16 LUFS) echte m4a-Testdatei."""
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-af", "volume=-30dB", "-c:a", "aac", "-b:a", "128k",
            str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )


def _make_loud_normalized_m4a(path: Path, duration_seconds: float = 1.0):
    """Erzeugt eine echte m4a-Testdatei, per AudioEnhancer bereits auf
    -16 LUFS vorbereitet, fuer den SKIP-Pfad."""
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
            "-c:a", "aac", "-b:a", "128k", str(path), "-y", "-loglevel", "error",
        ],
        check=True,
    )
    nll.AudioEnhancer.normalize_loudness(str(path), target_lufs=nll.TARGET_LUFS)


def _add_cover(path: Path, jpeg_bytes: bytes):
    audio = MP4(path)
    audio["©nam"] = ["Test Title"]
    audio["©ART"] = ["Test Artist"]
    audio["covr"] = [MP4Cover(jpeg_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


@pytest.fixture
def real_cover_jpeg(tmp_path):
    """Ein echtes, gueltiges kleines JPEG (kein Fake-Blob) - erforderlich,
    um den echten AudioEnhancer-Cover-Stream-Defekt reproduzierbar zu
    testen (ein ungueltiger Fake-Blob waere kein fairer Beweis)."""
    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg nicht verfuegbar")
    jpeg_path = tmp_path / "cover.jpg"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1",
         str(jpeg_path), "-y", "-loglevel", "error"],
        check=True,
    )
    return jpeg_path.read_bytes()


@pytest.fixture
def isolated_test_dir():
    """Ein echtes, temporaeres Verzeichnis UNTER der real erlaubten
    Testbibliothek (/tmp/musicbot_test/library) - ALLOWED_ROOT ist eine
    Modul-Konstante und an diese Konvention gebunden."""
    import uuid

    d = ALLOWED_ROOT / f"_pytest_lufs_{uuid.uuid4().hex[:8]}" / "Singles"
    d.mkdir(parents=True)
    yield d.parent
    shutil.rmtree(d.parent, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
# 1+2: Path-Safety
# ─────────────────────────────────────────────────────────────────────────


class TestPathSafety:
    def test_path_outside_test_library_is_blocked(self, tmp_path):
        with pytest.raises(nll.PathSafetyError, match="ausserhalb der erlaubten"):
            nll.validate_scan_root(tmp_path)

    def test_forbidden_production_root_is_blocked(self):
        with pytest.raises(nll.PathSafetyError, match="verbotenen Bereich"):
            nll.validate_scan_root(Path("/mnt/4tb/library"))

    def test_missing_path_is_blocked(self):
        with pytest.raises(nll.PathSafetyError, match="existiert nicht"):
            nll.validate_scan_root(ALLOWED_ROOT / "_does_not_exist_xyz")

    def test_symlink_escaping_test_library_is_blocked(self, isolated_test_dir, tmp_path):
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        symlink_path = isolated_test_dir / "escape_link"
        symlink_path.symlink_to(outside_dir, target_is_directory=True)

        with pytest.raises(nll.PathSafetyError, match="ausserhalb der erlaubten"):
            nll.validate_scan_root(symlink_path)

    def test_file_symlink_escaping_root_is_rejected_by_validate_file_within_root(
        self, isolated_test_dir, tmp_path
    ):
        outside_file = tmp_path / "outside.m4a"
        outside_file.write_bytes(b"not real audio")
        symlink_file = isolated_test_dir / "Singles" / "escape.m4a"
        symlink_file.symlink_to(outside_file)

        assert nll.validate_file_within_root(symlink_file, isolated_test_dir) is False

    def test_file_within_root_is_accepted(self, isolated_test_dir):
        real_file = isolated_test_dir / "Singles" / "track.m4a"
        real_file.write_bytes(b"data")
        assert nll.validate_file_within_root(real_file, isolated_test_dir) is True

    def test_allowed_root_itself_is_accepted(self):
        """Anders als beim Reprocessing-Tool (Artist-Unterordner
        erforderlich) ist die Testbibliotheks-Wurzel selbst hier ein
        gueltiges Standard-Ziel (Standardwert von --path)."""
        assert nll.validate_scan_root(ALLOWED_ROOT) == ALLOWED_ROOT.resolve()


# ─────────────────────────────────────────────────────────────────────────
# 3: Dry-Run veraendert nichts
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestDryRun:
    def test_dry_run_does_not_modify_file(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)
        before_bytes = path.read_bytes()

        result = nll.process_file(path, isolated_test_dir, dry_run=True)

        assert result["action"] == "NORMALIZE"
        assert result["status"] == "NORMALIZE"
        assert path.read_bytes() == before_bytes, "Dry-Run darf die Datei nicht veraendern"

    def test_dry_run_does_not_create_backup_files(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)

        nll.process_file(path, isolated_test_dir, dry_run=True)

        assert not list(isolated_test_dir.rglob("*.lufs_backup"))


# ─────────────────────────────────────────────────────────────────────────
# 4+5: Skip- vs. Normalize-Entscheidung
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestSkipVsNormalizeDecision:
    def test_already_normalized_file_is_skipped_not_reencoded(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "normalized.m4a"
        _make_loud_normalized_m4a(path)
        before_bytes = path.read_bytes()

        result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["action"] == "SKIP"
        assert result["status"] == "SKIPPED_ALREADY_NORMALIZED"
        assert path.read_bytes() == before_bytes, (
            "Eine bereits normalisierte Datei darf nicht erneut encodiert werden"
        )

    def test_file_outside_tolerance_is_normalized(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)

        result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["action"] == "NORMALIZE"
        assert result["status"] == "NORMALIZED"
        assert abs(result["after_lufs"] - nll.TARGET_LUFS) <= nll.LUFS_TOLERANCE

    def test_tolerance_boundary_values_from_ticket_example(self):
        """Abschnitt 'Intelligentes Skip-Verhalten' im Auftrag, exakt
        nachgerechnet: -16.0/-15.8/-16.4 -> SKIP, -14.0/-18.5 -> NORMALIZE."""
        for lufs in (-16.0, -15.8, -16.4):
            assert abs(lufs - nll.TARGET_LUFS) <= nll.LUFS_TOLERANCE, lufs
        for lufs in (-14.0, -18.5):
            assert abs(lufs - nll.TARGET_LUFS) > nll.LUFS_TOLERANCE, lufs


# ─────────────────────────────────────────────────────────────────────────
# 6: Delegation an AudioEnhancer
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestDelegationToAudioEnhancer:
    def test_normalization_is_delegated_to_audio_enhancer_with_correct_target(
        self, isolated_test_dir
    ):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)

        with patch.object(
            nll.AudioEnhancer, "normalize_loudness",
            wraps=nll.AudioEnhancer.normalize_loudness,
        ) as spy:
            nll.process_file(path, isolated_test_dir, dry_run=False)

        spy.assert_called_once_with(str(path), target_lufs=nll.TARGET_LUFS)

    def test_measure_loudness_is_pure_analysis_no_parallel_apply_logic(self):
        """
        Das Script darf KEINE eigene 'Anwenden'-FFmpeg-loudnorm-
        Implementierung parallel zu AudioEnhancer besitzen (Auftrag: 'Keine
        eigene FFmpeg-Loudnorm-Implementierung parallel zu AudioEnhancer
        bauen'). measure_loudness() ist die einzige eigene FFmpeg-loudnorm-
        Aufrufstelle in diesem Script und muss eine reine Analyse ohne
        Schreibzugriff/Encoder-Zieldatei sein (-f null statt einer echten
        Ausgabedatei, kein '-c:a'-Encoder-Flag).
        """
        import inspect

        measure_src = inspect.getsource(nll.measure_loudness)
        assert '"null"' in measure_src, "measure_loudness() muss reine Analyse sein (-f null)"
        assert "-c:a" not in measure_src, (
            "measure_loudness() darf keinen Encoder verwenden - das waere eine "
            "eigene Anwenden-Implementierung parallel zu AudioEnhancer"
        )
        assert "temp_path" not in measure_src


# ─────────────────────────────────────────────────────────────────────────
# 7: Fehlerbehandlung - ein Fehler stoppt nicht den gesamten Lauf
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestErrorHandling:
    def test_measurement_failure_does_not_raise(self, isolated_test_dir):
        broken = isolated_test_dir / "Singles" / "broken.m4a"
        broken.write_bytes(b"not a real audio file")

        result = nll.process_file(broken, isolated_test_dir, dry_run=False)

        assert result["status"] == "MEASUREMENT_FAILED"
        assert result["error"] is not None

    def test_normalize_loudness_exception_is_caught_and_original_restored(
        self, isolated_test_dir
    ):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)
        original_bytes = path.read_bytes()

        with patch.object(
            nll.AudioEnhancer, "normalize_loudness",
            side_effect=RuntimeError("simulierter ffmpeg-Absturz"),
        ):
            result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["status"] == "FAILED"
        assert "simulierter ffmpeg-Absturz" in result["error"]
        assert path.read_bytes() == original_bytes, "Original muss trotz Exception erhalten bleiben"
        assert not list(isolated_test_dir.rglob("*.lufs_backup"))

    def test_one_failing_file_does_not_stop_processing_of_others(self, isolated_test_dir):
        broken = isolated_test_dir / "Singles" / "broken.m4a"
        broken.write_bytes(b"not real audio")
        good = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(good)

        results = [
            nll.process_file(p, isolated_test_dir, dry_run=False)
            for p in sorted(isolated_test_dir.rglob("*.m4a"))
        ]

        statuses = {r["file"]: r["status"] for r in results}
        assert statuses["Singles/broken.m4a"] == "MEASUREMENT_FAILED"
        assert statuses["Singles/quiet.m4a"] == "NORMALIZED"


# ─────────────────────────────────────────────────────────────────────────
# 8: Verzeichnisstruktur bleibt unveraendert
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestStructureIntegrity:
    def test_directory_structure_unchanged_after_run(self, isolated_test_dir):
        (isolated_test_dir / "Album").mkdir()
        path1 = isolated_test_dir / "Singles" / "quiet.m4a"
        path2 = isolated_test_dir / "Album" / "track.m4a"
        _make_quiet_m4a(path1)
        _make_quiet_m4a(path2)

        before = nll.snapshot_directory_tree(isolated_test_dir)
        for p in (path1, path2):
            nll.process_file(p, isolated_test_dir, dry_run=False)
        after = nll.snapshot_directory_tree(isolated_test_dir)

        assert before == after

    def test_main_reports_structure_integrity_pass(self, isolated_test_dir, capsys):
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)

        exit_code = nll.main(["--path", str(isolated_test_dir)])

        assert exit_code == 0
        assert "Structure integrity: PASS" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────
# 9+10: Cover/Metadaten-Erhalt bzw. -Erkennung
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestMetadataAndCoverIntegrity:
    def test_metadata_diff_detects_change(self):
        before = {"artist": ["A"], "title": ["T"], "error": None}
        after = {"artist": ["B"], "title": ["T"], "error": None}
        diff = nll.diff_metadata(before, after)
        assert diff == {"artist": {"before": ["A"], "after": ["B"]}}

    def test_metadata_diff_empty_when_unchanged(self):
        snap = {"artist": ["A"], "error": None}
        assert nll.diff_metadata(snap, dict(snap)) == {}

    def test_cover_survives_normalization_when_no_video_stream_bug_triggers(
        self, isolated_test_dir
    ):
        """Regressionsschutz fuer den Normalfall (kein Cover -> kein
        AudioEnhancer-Cover-Stream-Defekt, siehe Modul-Docstring)."""
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)
        audio = MP4(path)
        audio["©lyr"] = ["Test Lyrics"]
        audio.save()

        result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["status"] == "NORMALIZED"
        assert result["metadata_diff"] == {}


# ─────────────────────────────────────────────────────────────────────────
# 13 (zusaetzlich, aus dem live gefundenen Defekt): Backup/Restore-
# Sicherheitsnetz
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestBackupRestoreSafetyNet:
    def test_backup_restores_file_when_audio_enhancer_leaves_it_corrupted(
        self, isolated_test_dir
    ):
        """
        Deterministischer Nachbau des live reproduzierten AudioEnhancer-
        Defekts (siehe Modul-Docstring): normalize_loudness() liefert True,
        hinterlaesst die Datei aber leer. Das Script MUSS die Original-Datei
        aus dem Backup wiederherstellen statt den Datenverlust stehen zu
        lassen.
        """
        path = isolated_test_dir / "Singles" / "quiet.m4a"
        _make_quiet_m4a(path)
        original_bytes = path.read_bytes()

        def _corrupt_but_claim_success(filepath, target_lufs=-16.0):
            Path(filepath).write_bytes(b"")  # simuliert den realen Defekt
            return True

        with patch.object(
            nll.AudioEnhancer, "normalize_loudness",
            side_effect=_corrupt_but_claim_success,
        ):
            result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["status"] == "FAILED"
        assert "beschaedigt" in result["error"]
        assert path.read_bytes() == original_bytes, (
            "Original-Datei muss trotz vorgetaeuschtem Erfolg wiederhergestellt werden"
        )
        assert not list(isolated_test_dir.rglob("*.lufs_backup")), (
            "Kein Backup-Rest nach erfolgreicher Wiederherstellung"
        )

    def test_real_audio_enhancer_bug_with_embedded_cover_is_caught_and_restored(
        self, isolated_test_dir, real_cover_jpeg
    ):
        """
        Nicht gemockter End-to-End-Beweis mit ECHTEM AudioEnhancer und
        einem echten, gueltigen JPEG-Cover - reproduziert den in diesem
        Auftrag live entdeckten Defekt ohne Mock und beweist, dass das
        Backup/Restore-Sicherheitsnetz auch gegen den echten FFmpeg-Fehler
        greift (kein Datenverlust trotz bestehendem AudioEnhancer-Defekt).
        """
        path = isolated_test_dir / "Singles" / "quiet_with_cover.m4a"
        _make_quiet_m4a(path)
        _add_cover(path, real_cover_jpeg)
        original_bytes = path.read_bytes()

        result = nll.process_file(path, isolated_test_dir, dry_run=False)

        assert result["status"] == "FAILED"
        assert path.exists() and path.read_bytes() == original_bytes, (
            "Bekannter AudioEnhancer-Cover-Stream-Defekt darf die Testdatei "
            "nicht dauerhaft beschaedigen"
        )
        assert not list(isolated_test_dir.rglob("*.lufs_backup"))


# ─────────────────────────────────────────────────────────────────────────
# 11: Exit-Codes
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestExitCodes:
    def test_exit_code_0_on_full_success(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "normalized.m4a"
        _make_loud_normalized_m4a(path)

        assert nll.main(["--path", str(isolated_test_dir)]) == 0

    def test_exit_code_1_on_measurement_failure(self, isolated_test_dir):
        broken = isolated_test_dir / "Singles" / "broken.m4a"
        broken.write_bytes(b"not real audio")

        assert nll.main(["--path", str(isolated_test_dir)]) == 1

    def test_exit_code_2_on_path_safety_violation(self, tmp_path):
        assert nll.main(["--path", str(tmp_path)]) == 2


# ─────────────────────────────────────────────────────────────────────────
# 12: Report-Erzeugung
# ─────────────────────────────────────────────────────────────────────────


@requires_ffmpeg
class TestReportGeneration:
    def test_report_json_written_with_expected_structure(self, isolated_test_dir):
        path = isolated_test_dir / "Singles" / "normalized.m4a"
        _make_loud_normalized_m4a(path)

        nll.main(["--path", str(isolated_test_dir)])

        assert nll.REPORT_JSON_PATH.exists()
        with open(nll.REPORT_JSON_PATH) as f:
            report = json.load(f)

        for key in (
            "timestamp", "target_lufs", "tolerance", "files_scanned",
            "normalized", "skipped", "failed", "safety_blocked",
            "measurement_failed", "metadata_integrity", "structure_integrity",
            "results",
        ):
            assert key in report, f"Report fehlt Feld '{key}'"
        assert report["target_lufs"] == nll.TARGET_LUFS
        assert report["tolerance"] == nll.LUFS_TOLERANCE
        assert report["files_scanned"] == 1
        assert len(report["results"]) == 1
