# tests/test_resolve_duplicates.py
# -*- coding: utf-8 -*-
"""
Tests für scripts/resolve_duplicates.py (Duplicate Resolution Phase 1 CLI).

`scripts/` ist bewusst kein Python-Package - das Modul wird deshalb ueber
importlib direkt per Dateipfad geladen (identisches Muster wie
tests/test_reprocess_artist_metadata.py / tests/test_normalize_test_library_loudness.py).

Test-Strategie (CLAUDE.md Abschnitt 7/8): Path-Safety/Determinismus/
Read-Only-Garantie deterministisch getestet; ein kleiner Teil nutzt echte,
per ffmpeg erzeugte m4a-Dateien für den End-to-End-Scan-Pfad. Der reale
Badchieff-Fixture-Fall (Auftrag Abschnitt 23) wird - sofern die realen
Testdaten unter /tmp/musicbot_test/metadaten/Badchieff vorhanden sind -
zusätzlich als ECHTER End-to-End-Beweis kopiert (nicht nur synthetisch
nachgebildet wie in tests/test_duplicate_resolution.py) und danach wieder
entfernt.
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

_spec = importlib.util.spec_from_file_location("resolve_duplicates", MODULE_PATH)
rd = importlib.util.module_from_spec(_spec)
sys.modules["resolve_duplicates"] = rd
_spec.loader.exec_module(rd)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg nicht auf PATH verfügbar")

ALLOWED_ROOT = rd.ALLOWED_ROOT  # /tmp/musicbot_test/library
REAL_BADCHIEFF_DIR = Path("/tmp/musicbot_test/metadaten/Badchieff")


def _make_real_m4a(
    path: Path, artist: str, title: str, album: str = None, trkn=None,
    duration: float = 1, mb_recording_id: str = None,
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
    audio.save()


@pytest.fixture
def isolated_test_dir():
    d = ALLOWED_ROOT / f"_pytest_resolve_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestPathSafety:
    def test_path_outside_allowed_root_is_blocked(self, tmp_path):
        with pytest.raises(rd.PathSafetyError, match="außerhalb"):
            rd.validate_scan_root(tmp_path)

    def test_forbidden_production_root_is_blocked(self):
        with pytest.raises(rd.PathSafetyError, match="verbotenen"):
            rd.validate_scan_root(Path("/mnt/128ssd"))

    def test_missing_path_is_blocked(self):
        with pytest.raises(rd.PathSafetyError, match="existiert nicht"):
            rd.validate_scan_root(ALLOWED_ROOT / "_this_does_not_exist_xyz")

    def test_allowed_root_itself_is_accepted(self):
        assert rd.validate_scan_root(ALLOWED_ROOT) == ALLOWED_ROOT.resolve()

    def test_symlink_escaping_root_is_blocked_test19(self, isolated_test_dir, tmp_path):
        """Test 19 (Auftrag Abschnitt 22): Symlink außerhalb Root ->
        SAFETY BLOCK."""
        outside = tmp_path / "outside"
        outside.mkdir()
        link = isolated_test_dir / "escape_link"
        link.symlink_to(outside)
        with pytest.raises(rd.PathSafetyError):
            rd.validate_scan_root(link)

    def test_path_traversal_via_dotdot_is_blocked_test18(self):
        """Test 18 (Auftrag Abschnitt 22): Path traversal -> SAFETY BLOCK."""
        traversal = ALLOWED_ROOT / ".." / ".." / ".."
        with pytest.raises(rd.PathSafetyError):
            rd.validate_scan_root(traversal)

    def test_file_within_root_accepted_by_per_file_check(self, isolated_test_dir):
        f = isolated_test_dir / "x.m4a"
        f.write_bytes(b"x")
        assert rd.validate_file_within_root(f, ALLOWED_ROOT) is True

    def test_file_symlink_escaping_root_rejected_by_per_file_check(
        self, isolated_test_dir, tmp_path
    ):
        outside_file = tmp_path / "outside.m4a"
        outside_file.write_bytes(b"x")
        link = isolated_test_dir / "linked.m4a"
        link.symlink_to(outside_file)
        assert rd.validate_file_within_root(link, ALLOWED_ROOT) is False


class TestNoExecuteFlags:
    """Phase 1 (Auftrag Abschnitt 18): --execute/--apply/--delete durften
    NICHT existieren. Phase 3 (MusicBot — Duplicate Resolution Phase 3,
    Abschnitt 3) macht --execute bewusst real - --apply/--delete bleiben
    weiterhin verbotene Alias-Flags (Exit-Code != 0, klare Fehlermeldung,
    ohne etwas auszufuehren). Positive --execute-Tests siehe
    tests/test_resolve_duplicates_execute.py."""

    @pytest.mark.parametrize("flag", ["--apply", "--delete"])
    def test_mutation_flag_rejected(self, flag, capsys):
        exit_code = rd.main([flag])
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "mutation is not available" in captured.err

    def test_dry_run_flag_accepted_as_noop(self, isolated_test_dir):
        exit_code = rd.main(["--path", str(isolated_test_dir), "--dry-run"])
        assert exit_code == 0


class TestReadOnlyGuarantee:
    @requires_ffmpeg
    def test_scan_leaves_filesystem_completely_unchanged(self, isolated_test_dir):
        """Test 20 (Auftrag Abschnitt 22): Dry-Run - Vorher/Nachher-
        Dateisystemzustand identisch."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track")
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1)

        before = rd.snapshot_tree(isolated_test_dir)
        exit_code = rd.main(["--path", str(isolated_test_dir)])
        after = rd.snapshot_tree(isolated_test_dir)

        assert exit_code == 0
        assert before == after
        assert single.exists()
        assert album.exists()

    @requires_ffmpeg
    def test_no_unlink_rename_move_replace_called_within_library_during_run(
        self, isolated_test_dir
    ):
        """Technische Sicherheitspruefung (Auftrag Abschnitt 21): jeder
        Aufruf von unlink()/rename()/replace() auf einem Pfad INNERHALB
        der gescannten Library wuerde den Test fehlschlagen lassen. Der
        JSON-Report (ausserhalb der Library, in isolated_test_dir.parent)
        nutzt Path.replace() legitim fuer den atomaren Schreibvorgang -
        nur Aufrufe innerhalb des Scan-Roots sind hier sicherheitsrelevant."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track")

        original_unlink = Path.unlink
        original_rename = Path.rename
        original_replace = Path.replace

        def _guarded(name, original):
            def _wrapped(self_path, *args, **kwargs):
                if isolated_test_dir in self_path.resolve().parents or self_path.resolve() == isolated_test_dir:
                    raise AssertionError(f"{name}() called on library path: {self_path}")
                return original(self_path, *args, **kwargs)

            return _wrapped

        with patch.object(Path, "unlink", _guarded("unlink", original_unlink)), \
             patch.object(Path, "rename", _guarded("rename", original_rename)), \
             patch.object(Path, "replace", _guarded("replace", original_replace)):
            with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "report.json"):
                exit_code = rd.main(["--path", str(isolated_test_dir)])
        assert exit_code == 0


class TestDryRunEndToEnd:
    @requires_ffmpeg
    def test_album_vs_single_scan_produces_correct_report(self, isolated_test_dir):
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(single, "Artist", "Track")
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(album, "Artist", "Track", album="Album", trkn=1)

        with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "report.json"):
            exit_code = rd.main(["--path", str(isolated_test_dir)])
            report = json.loads((isolated_test_dir.parent / "report.json").read_text())

        assert exit_code == 0
        assert report["files_scanned"] == 2
        assert report["duplicate_groups"] == 1
        assert report["resolved_groups"] == 1
        assert report["read_only_intact"] is True
        decision = report["decisions"][0]
        assert decision["keep"] == str(album)
        assert decision["remove_proposal"] == [str(single)]
        assert decision["action"] == "RESOLVED"

    @requires_ffmpeg
    def test_single_file_no_duplicate_group(self, isolated_test_dir):
        f = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(f, "Artist", "Track")

        with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "report2.json"):
            rd.main(["--path", str(isolated_test_dir)])
            report = json.loads((isolated_test_dir.parent / "report2.json").read_text())

        assert report["duplicate_groups"] == 0
        assert report["single_candidate_groups"] == 1

    @requires_ffmpeg
    def test_artist_flag_scopes_to_artist_subfolder(self, isolated_test_dir):
        artist_name = isolated_test_dir.name
        f = ALLOWED_ROOT / artist_name / "Singles" / "2025 - Track.m4a"
        try:
            _make_real_m4a(f, "Artist", "Track")
            with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "report3.json"):
                exit_code = rd.main(["--artist", artist_name])
        finally:
            shutil.rmtree(ALLOWED_ROOT / artist_name, ignore_errors=True)
        assert exit_code == 0


class TestSafetyGateEndToEnd:
    """MusicBot — Duplicate Resolution Phase 2: End-to-End-Beweis, dass
    Duration-/MusicBrainz-/Album-Kontext-Auslesung tatsaechlich bis zum
    Safety Gate durchverdrahtet ist (nicht nur auf resolve_group()-Ebene
    isoliert getestet, siehe tests/test_duplicate_resolution.py)."""

    @requires_ffmpeg
    def test_real_duration_mismatch_in_remix_album_blocks_remove(self, isolated_test_dir):
        """Nachbildung des realen Nachts-wach-Funds mit echten, per
        ffmpeg erzeugten Dateien unterschiedlicher Laenge in einem
        Remix-Album-Ordner."""
        track_02 = isolated_test_dir / "makko" / "2022 - Nachts wach (Remix EP)" / "02 - Nachts wach.m4a"
        _make_real_m4a(
            track_02, "makko", "Nachts wach", album="Nachts wach (Remix EP)",
            trkn=2, duration=1,
        )
        track_04 = isolated_test_dir / "makko" / "2022 - Nachts wach (Remix EP)" / "04 - Nachts wach.m4a"
        _make_real_m4a(
            track_04, "makko", "Nachts wach", album="Nachts wach (Remix EP)",
            trkn=4, duration=3,
        )

        with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "gate_report.json"):
            exit_code = rd.main(["--path", str(isolated_test_dir)])
            report = json.loads((isolated_test_dir.parent / "gate_report.json").read_text())

        assert exit_code == 0
        decision = report["decisions"][0]
        assert decision["action"] == "MANUAL_REVIEW"
        assert decision["keep"] is None
        assert decision["remove_proposal"] == []
        ev = decision["evidence"][0]
        assert ev["safety_gate"] == "BLOCKED"
        assert ev["duration_consistent"] is False
        assert ev["album_context_risk"] is True

    @requires_ffmpeg
    def test_matching_musicbrainz_recording_id_overrides_duration_mismatch(
        self, isolated_test_dir
    ):
        """Auftrag Abschnitt 4: eine uebereinstimmende MusicBrainz
        Recording ID ist eine starke Identitaetsbestaetigung und
        ueberstimmt eine ansonsten blockierende Duration-Abweichung."""
        single = isolated_test_dir / "Artist" / "Singles" / "2025 - Track.m4a"
        _make_real_m4a(
            single, "Artist", "Track", duration=1,
            mb_recording_id="11111111-1111-1111-1111-111111111111",
        )
        album = isolated_test_dir / "Artist" / "2025 - Album" / "01 - Track.m4a"
        _make_real_m4a(
            album, "Artist", "Track", album="Album", trkn=1, duration=3,
            mb_recording_id="11111111-1111-1111-1111-111111111111",
        )

        with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "gate_report2.json"):
            exit_code = rd.main(["--path", str(isolated_test_dir)])
            report = json.loads((isolated_test_dir.parent / "gate_report2.json").read_text())

        assert exit_code == 0
        decision = report["decisions"][0]
        assert decision["action"] == "RESOLVED"
        assert decision["keep"] == str(album)
        assert decision["remove_proposal"] == [str(single)]
        ev = decision["evidence"][0]
        assert ev["safety_gate"] == "PASSED"
        assert ev["musicbrainz_match"] is True


@requires_ffmpeg
class TestBadchieffRealFixtureEndToEnd:
    """Auftrag Abschnitt 23: echter End-to-End-Beweis mit den REALEN
    Badchieff-Dateien (kopiert, nicht synthetisch) - sofern in dieser
    Umgebung vorhanden. Kein Hardcoding: derselbe main()/resolve_group()
    -Codepfad wie jeder andere Testfall."""

    @pytest.mark.skipif(
        not REAL_BADCHIEFF_DIR.exists(), reason="reale Badchieff-Testdaten nicht vorhanden"
    )
    def test_real_badchieff_files_album_wins(self, isolated_test_dir):
        target = isolated_test_dir / "Badchieff"
        shutil.copytree(REAL_BADCHIEFF_DIR, target)
        before = rd.snapshot_tree(isolated_test_dir)

        with patch.object(rd, "REPORT_JSON_PATH", isolated_test_dir.parent / "badchieff_report.json"):
            exit_code = rd.main(["--path", str(isolated_test_dir)])
            report = json.loads(
                (isolated_test_dir.parent / "badchieff_report.json").read_text()
            )

        after = rd.snapshot_tree(isolated_test_dir)
        assert before == after, "reale Badchieff-Testdaten dürfen nicht verändert werden"
        assert exit_code == 0

        gut_aus_decisions = [d for d in report["decisions"] if d["title"] == "GUT AUS"]
        assert len(gut_aus_decisions) == 1
        decision = gut_aus_decisions[0]
        assert decision["action"] == "RESOLVED"
        assert decision["keep"].endswith("HEUTE ODER GESTERN/12 - GUT AUS.m4a")
        assert len(decision["remove_proposal"]) == 2
        assert all("Singles" in p for p in decision["remove_proposal"])
