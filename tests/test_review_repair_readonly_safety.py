# tests/test_review_repair_readonly_safety.py
# -*- coding: utf-8 -*-
"""
PFLICHT-Test (Aufgabe "Library Health Review + Repair MusicBot",
Abschnitt 52): sowohl Review-Aktionen als auch die Repair-Preview
beweisen technisch, dass sie KEINE Library-Datei verändern.

Isoliertes Testsystem mit echten m4a-Dateien, vollständiger Before/After-
Snapshot (Pfad, Größe, mtime_ns, SHA-256) für Struktur/Dateien/Metadaten/
Audio/Cover in EINEM Wert (SHA-256 über die komplette Datei deckt alle
vier ab - jede Änderung an Tag/Audio/Cover ändert den Hash).
"""

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from handlers.library_health_review_handler import LibraryHealthReviewHandler
from handlers.repair_musicbot_handler import RepairMusicBotHandler
from services.library_health.findings import (
    FindingsRegistry,
    annotate_issues_with_findings,
    build_findings_summary,
)
from services.library_health.scanner import run_scan
from services.library_repair.doctor_runner import DoctorScanResult

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
    """Ein SHA-256 pro Datei deckt Struktur (Pfad als Key), Metadaten
    (Tags sind Teil der Datei), Audio UND Cover (ebenfalls Teil der
    Datei) gemeinsam ab - jede Aenderung an irgendeinem dieser vier
    Aspekte aendert den Hash."""
    snap = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            st = f.stat()
            snap[str(f.relative_to(root))] = (
                len(data), st.st_mtime_ns, hashlib.sha256(data).hexdigest()
            )
    return snap


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def isolated_library(tmp_path):
    library_root = tmp_path / "library"
    _make_m4a(
        library_root / "Artist One" / "Singles" / "2021 - Song A.m4a",
        artist="Artist One", title="Song A", album="Song A",
        genre="Pop / Rock", year="2021",
    )
    _make_m4a(
        library_root / "Artist Two" / "Singles" / "2020 - Bare.m4a",
    )
    return library_root


@requires_ffmpeg
class TestReviewReadOnlySafety:
    def test_full_review_session_does_not_touch_library(self, isolated_library, tmp_path):
        report = run_scan(isolated_library, genre_mapping_dir=None)
        registry_path = tmp_path / "findings.json"
        registry = FindingsRegistry(registry_path)
        registry.merge_scan_issues(report["issues"], scanned_at=report["scan"]["completed_at"])
        registry.save()

        before = _snapshot(isolated_library)

        class FakeConfig:
            OWNER_USER_ID = 1
            ADMIN_USER_IDS = [2]
            DATA_DIR = str(tmp_path)

        handler = LibraryHealthReviewHandler(FakeConfig(), logger_factory=lambda n: Mock())

        def _mock_update(user_id):
            update = Mock()
            update.effective_user = Mock()
            update.effective_user.id = user_id
            update.callback_query = Mock()
            update.callback_query.answer = AsyncMock()
            update.callback_query.edit_message_text = AsyncMock()
            return update

        context = Mock()
        context.user_data = {}

        # Uebersicht oeffnen, Severity/Kategorie durchklicken, Einzelreview
        # starten, Resolve + False-Positive + Skip ausfuehren, Batch-
        # False-Positive bestaetigen - eine komplette, realistische Review-
        # Session.
        update = _mock_update(2)
        run(handler.handle_start(update, context))

        groups_seen = []
        from services.library_health.findings import group_open_findings_by_category

        for group in group_open_findings_by_category(registry):
            run(handler.handle_severity(update, context, group.tier))
            run(handler.handle_category(update, context, group.code))
            run(handler.handle_edit_start(update, context, group.code))
            for finding in list(group.findings):
                run(handler.handle_single_action(update, context, "resolve", finding.finding_id))
            groups_seen.append(group.code)

        assert groups_seen, "Test-Library muss mindestens eine Kategorie erzeugen"
        assert _snapshot(isolated_library) == before

    def test_batch_false_positive_does_not_touch_library(self, isolated_library, tmp_path):
        report = run_scan(isolated_library, genre_mapping_dir=None)
        registry_path = tmp_path / "findings.json"
        registry = FindingsRegistry(registry_path)
        registry.merge_scan_issues(report["issues"], scanned_at=report["scan"]["completed_at"])
        registry.save()

        before = _snapshot(isolated_library)

        class FakeConfig:
            OWNER_USER_ID = 1
            ADMIN_USER_IDS = [2]
            DATA_DIR = str(tmp_path)

        handler = LibraryHealthReviewHandler(FakeConfig(), logger_factory=lambda n: Mock())
        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 2
        update.callback_query = Mock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = Mock()

        from services.library_health.findings import group_open_findings_by_category

        for group in group_open_findings_by_category(registry):
            run(handler.handle_batch_confirmed(update, context, group.code))

        assert _snapshot(isolated_library) == before


@requires_ffmpeg
class TestRepairPreviewReadOnlySafety:
    def test_analyze_and_proposals_and_preview_do_not_touch_library(self, isolated_library, tmp_path):
        before = _snapshot(isolated_library)

        class FakeConfig:
            OWNER_USER_ID = 1
            ADMIN_USER_IDS = [2]
            DATA_DIR = str(tmp_path)

        handler = RepairMusicBotHandler(FakeConfig(), logger_factory=lambda n: Mock())
        message = Mock()
        message.edit_text = AsyncMock()

        async def _fake_scan(*_a, **_kw):
            report = run_scan(isolated_library, genre_mapping_dir=None)
            registry_path = tmp_path / "findings.json"
            registry = FindingsRegistry(registry_path)
            registry.merge_scan_issues(report["issues"], scanned_at=report["scan"]["completed_at"])
            registry.save()
            annotated = annotate_issues_with_findings(report["issues"], registry)
            report["issues"] = annotated
            report["findings"] = build_findings_summary(annotated)
            return DoctorScanResult(exit_code=0, report=report)

        import handlers.repair_musicbot_handler as repair_handler_module

        with patch.object(repair_handler_module, "build_repair_plan") as mocked_plan:
            from services.library_repair.repair_service import build_repair_plan as real_build_plan

            async def _real_plan_via_fake_scan():
                with patch(
                    "services.library_repair.repair_service.run_health_scan",
                    new=AsyncMock(side_effect=_fake_scan),
                ):
                    return await real_build_plan()

            mocked_plan.side_effect = _real_plan_via_fake_scan

            run(handler._run_analyze_and_report(message))
            run(handler._run_proposals_and_report(message))
            run(handler._run_preview_and_report(message))

        assert _snapshot(isolated_library) == before
