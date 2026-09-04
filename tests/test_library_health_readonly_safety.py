# tests/test_library_health_readonly_safety.py
# -*- coding: utf-8 -*-
"""
PFLICHT-Test (Prompt Abschnitt 32/33): der Library Health Scanner beweist
technisch, dass er KEINE Library-Datei veraendert.

  1. Isolierte Test-Library mit echten m4a/mp3 (inkl. defekter Datei).
  2. SHA256 + mtime_ns + size + relative Pfade VOR dem Scan.
  3. run_scan()  UND  der CLI-Subprozess.
  4. Erneute Erfassung — muss byteidentisch sein.
  5. Import-Graph: keiner der bekannten Schreib-Pfade
     (TagWriter/FilenameFixer/AudioEnhancer/Duplicate-Execution/
     EnhancedMetadataProcessor) landet im Import-Graph des Scanners.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _make_m4a(path: Path, seconds=2, **tags):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", "-b:a", "192k", str(path), "-y", "-loglevel", "error"],
        check=True,
    )
    if tags:
        from mutagen.mp4 import MP4

        a = MP4(path)
        for k, v in tags.items():
            a[{"artist": "©ART", "title": "©nam", "album": "©alb",
               "genre": "©gen", "year": "©day"}[k]] = [v]
        a.save()


def _snapshot(root: Path) -> dict:
    snap = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            st = f.stat()
            snap[str(f.relative_to(root))] = (
                len(data), st.st_mtime_ns, hashlib.sha256(data).hexdigest()
            )
    return snap


@pytest.fixture
def test_library(tmp_path):
    lib = tmp_path / "library"
    _make_m4a(lib / "Artist One" / "Singles" / "2021 - Song A.m4a",
              artist="Artist One", title="Song A", album="Song A", genre="Pop", year="2021")
    _make_m4a(lib / "Artist One" / "2019 - Album X" / "01 - Track.m4a",
              artist="Artist One", title="Track", album="Album X", year="2019")
    _make_m4a(lib / "Artist Two" / "Singles" / "2020 - Bare.m4a")
    # bewusst defekte Datei — darf den Scan nicht abbrechen und nicht
    # "repariert" werden.
    broken = lib / "Artist Two" / "Singles" / "2020 - Broken.m4a"
    broken.write_bytes(b"NOT A REAL MP4 FILE \x00\x01\x02" * 40)
    return lib


@requires_ffmpeg
def test_run_scan_does_not_mutate_library(test_library):
    from services.library_health.scanner import run_scan

    before = _snapshot(test_library)
    report = run_scan(test_library, genre_mapping_dir=None)
    after = _snapshot(test_library)

    assert before == after, "Scanner hat Library-Dateien veraendert!"
    assert set(before) == set(after), "Pfade haben sich geaendert"
    # der Scan lief trotz defekter Datei vollstaendig durch
    assert report["statistics"]["total_files"] == 4


@requires_ffmpeg
def test_run_scan_with_loudness_measurement_does_not_mutate_library(test_library):
    """--measure-loudness dekodiert jede Datei per ffmpeg-loudnorm, schreibt
    aber nach `null` — die Library muss byte-identisch bleiben, keine
    temp-Datei zuruecklassen."""
    from services.library_health.scanner import run_scan

    before = _snapshot(test_library)
    run_scan(test_library, genre_mapping_dir=None, measure_loudness=True)
    after = _snapshot(test_library)

    assert before == after, "LUFS-Messung hat Library-Dateien veraendert!"
    assert set(before) == set(after), "Pfade/temp-Dateien haben sich geaendert"


@requires_ffmpeg
def test_cli_subprocess_does_not_mutate_library(test_library, tmp_path):
    before = _snapshot(test_library)
    out_json = tmp_path / "out" / "report.json"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "library_health_check.py"),
         "--library", str(test_library), "--json", str(out_json)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    after = _snapshot(test_library)
    assert before == after
    assert out_json.exists()
    report = json.loads(out_json.read_text())
    assert report["schema_version"]
    assert not str(out_json).startswith(str(test_library))  # Report ausserhalb


@requires_ffmpeg
def test_fail_on_error_exit_code(test_library, tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "library_health_check.py"),
         "--library", str(test_library), "--json", str(tmp_path / "r.json"),
         "--fail-on-error"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    # die defekte + die tag-lose Datei erzeugen ERROR/CRITICAL
    assert result.returncode == 1


def test_forbidden_mutation_flags_are_rejected(tmp_path):
    for flag in ("--fix", "--repair", "--delete", "--execute", "--apply"):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "library_health_check.py"), flag],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert "diagnostisch" in result.stderr


def test_scanner_import_graph_has_no_writer_modules():
    """In einem frischen Interpreter: der Import von
    services.library_health.scanner darf keinen der bekannten Schreib-Pfade
    mitziehen (Prompt Abschnitt 33 — 'nicht einmal in den Import-Graph')."""
    forbidden = [
        "services.metadata",
        "services.metadata.tag_writer",
        "services.metadata.enhanced_metadata_processor",
        "services.metadata.cover_processor",
        "services.duplicate.execution",
        "services.duplicate.resolution",
        "utils.filenamefixer",
        "utils.audio_enhancer",
    ]
    code = (
        "import sys; import services.library_health.scanner; "
        f"bad=[m for m in {forbidden!r} if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Schreib-Module im Import-Graph: {result.stdout.strip()}"
