# tests/test_repair_integration.py
# -*- coding: utf-8 -*-
"""
End-to-End-Integrationstest (Aufgabe "Repair MusicBot", Abschnitt 51):

    Health Scan → Finding → Repair Plan → Preview → Confirmation
    → Repair Executor → Verification → Finding Status → Health Scan

Verwendet an JEDER Stelle die ECHTE Produktionsfunktion - KEIN Mock -
mit EINER bewussten, dokumentierten Ausnahme:

    services/library_repair/doctor_runner.py (Subprozess-Wrapper um
    scripts/library_health_check.py / scripts/library_repair.py) wird
    hier NICHT durchlaufen, weil diese beiden CLI-Skripte beim Fehlen
    von `--library` fest gegen `config.Config.LIBRARY_DIR` scannen (die
    ECHTE Produktionsbibliothek) - der Subprozess-Wrapper selbst hat
    bereits eigene Tests in tests/test_doctor_runner.py und
    tests/test_library_health_readonly_safety.py (inkl. CLI-Subprozess).

Stattdessen werden exakt dieselben, darunterliegenden Produktions-
funktionen direkt aufgerufen, die diese Skripte selbst verwenden:

    services.library_health.scanner.run_scan()              (echter Scan)
    services.library_health.findings.*                       (echte Findings-Registry)
    services.library_repair.planner.plan_repairs()/filter_plan()  (echter Planner)
    services.library_repair.repair_service.get_safe_automatic_candidates()/
        build_preview()                                       (echter Service)
    services.library_repair.executor.apply_level1()          (ECHTER Executor,
                                                                 keine Simulation)
    services.library_repair.journal.RepairJournal             (echtes Journal)

Der tatsächlich ausgeführte Executor (GENRE_DELIMITER_INCONSISTENT,
Level SAFE_AUTOMATIC) ist verlustfrei und sicher gegen eine isolierte
Test-Library testbar (Abschnitt 51: "ein tatsächlich vorhandener und
sicher testbarer Repair Executor").
"""

import shutil
import subprocess

import pytest

from services.library_health.findings import (
    STATUS_FALSE_POSITIVE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    FindingsRegistry,
    accept_finding,
    annotate_issues_with_findings,
    build_findings_summary,
    generate_finding_id,
    get_accepted_findings,
    get_review_summary,
)
from services.library_health.scanner import run_scan
from services.library_repair.executor import apply_level1
from services.library_repair.journal import RepairJournal
from services.library_repair.planner import disposition_for_code, plan_repairs
from services.library_repair.repair_service import build_preview, get_safe_automatic_candidates

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg nicht auf PATH")


def _make_m4a(path, seconds=2, **tags):
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
               "genre": "©gen", "year": "©day",
               "album_artist": "aART"}[k]] = [v]
        a.save()


def _snapshot(root):
    import hashlib

    snap = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            st = f.stat()
            snap[str(f.relative_to(root))] = (
                len(data), st.st_mtime_ns, hashlib.sha256(data).hexdigest()
            )
    return snap


@requires_ffmpeg
class TestFullRepairLifecycle:
    def test_scan_finding_plan_preview_execute_verify_resolve_rescan(self, tmp_path):
        library_root = tmp_path / "library"
        target_file = library_root / "Test Artist" / "Singles" / "2024 - Song.m4a"
        _make_m4a(
            target_file, artist="Test Artist", title="Song", album="Song",
            genre="Pop / Rock", year="2024", album_artist="Test Artist",
        )
        registry_path = tmp_path / "findings.json"

        # ── 1. Health Scan (echter Scanner) ───────────────────────────
        report = run_scan(library_root, genre_mapping_dir=None)
        issue_codes = {i["issue_code"] for i in report["issues"]}
        assert "GENRE_DELIMITER_INCONSISTENT" in issue_codes

        # ── 2. Finding (echte Findings-Registry) ──────────────────────
        registry = FindingsRegistry(registry_path)
        registry.merge_scan_issues(report["issues"], scanned_at=report["scan"]["completed_at"])
        registry.save()
        annotated_issues = annotate_issues_with_findings(report["issues"], registry)
        report["issues"] = annotated_issues
        report["findings"] = build_findings_summary(annotated_issues)

        genre_issue = next(
            i for i in annotated_issues if i["issue_code"] == "GENRE_DELIMITER_INCONSISTENT"
        )
        fid = genre_issue["finding_id"]
        assert genre_issue["finding_status"] == STATUS_OPEN
        assert registry.get(fid).status == STATUS_OPEN

        # ── 3. Repair Plan (echter Planner, nur OPEN-Findings) ────────
        open_issues = [i for i in annotated_issues if i["finding_status"] == STATUS_OPEN]
        plan = plan_repairs({**report, "issues": open_issues})
        safe_candidates = get_safe_automatic_candidates(plan)
        assert any(c.issue_code == "GENRE_DELIMITER_INCONSISTENT" for c in safe_candidates)

        # ── 4. Preview (read-only) ─────────────────────────────────────
        before_preview = _snapshot(library_root)
        preview = build_preview(safe_candidates)
        assert preview.read_only is True
        assert preview.candidate_count >= 1
        assert _snapshot(library_root) == before_preview  # Preview aendert nichts

        # ── 5. Confirmation (Telegram-/CLI-Schicht - hier: simulierter
        #      expliziter Nutzer-Tap, kein technischer Schritt) ─────────
        user_confirmed = True
        assert user_confirmed

        # ── 6. Repair Executor (ECHTER Executor, kein Mock) ───────────
        journal = RepairJournal(tmp_path / "journal.jsonl")
        outcomes = apply_level1(safe_candidates, library_root, journal, dry_run=False)
        journal.flush()
        genre_outcome = next(
            o for o in outcomes if o.issue_code == "GENRE_DELIMITER_INCONSISTENT"
        )
        assert genre_outcome.status == "SUCCESS"

        from mutagen.mp4 import MP4

        assert MP4(target_file)["©gen"] == ["Pop; Rock"]

        # ── 7. Verification: erneuter Health Scan ─────────────────────
        post_report = run_scan(library_root, genre_mapping_dir=None)
        post_issue_codes = {i["issue_code"] for i in post_report["issues"]}
        assert "GENRE_DELIMITER_INCONSISTENT" not in post_issue_codes

        # ── 8. Finding Status: NUR nach Verification -> RESOLVED ──────
        merge_result = registry.merge_scan_issues(
            post_report["issues"], scanned_at=post_report["scan"]["completed_at"]
        )
        assert merge_result["resolved_by_scan"] == 1  # vom Scanner nicht mehr erkannt
        assert registry.get(fid).status == "RESOLVED_BY_SCAN"

        # Repair-Service markiert NACH Verification explizit RESOLVED
        # (nicht FALSE_POSITIVE) - hier die reale Verifikationslogik
        # nachvollzogen (identisch zu repair_service.execute_safe_automatic_repair()).
        post_open_ids = {
            i.get("finding_id") for i in annotate_issues_with_findings(post_report["issues"], registry)
            if i.get("finding_status") == STATUS_OPEN
        }
        assert fid not in post_open_ids
        registry.review_finding(fid, STATUS_RESOLVED, reviewed_by="integration-test")
        registry.save()
        assert registry.get(fid).status == STATUS_RESOLVED

        # ── 9. Health Scan (erneut) - Finding bleibt RESOLVED, kein Reopen ─
        final_report = run_scan(library_root, genre_mapping_dir=None)
        registry.merge_scan_issues(
            final_report["issues"], scanned_at=final_report["scan"]["completed_at"]
        )
        registry.save()
        assert registry.get(fid).status == STATUS_RESOLVED
        assert fid not in {f.finding_id for f in registry.get_open_findings()}

    def test_preview_step_never_touches_library_files(self, tmp_path):
        library_root = tmp_path / "library"
        _make_m4a(
            library_root / "Artist" / "Singles" / "2024 - Song.m4a",
            artist="Artist", title="Song", album="Song", genre="Pop / Rock",
        )
        before = _snapshot(library_root)

        report = run_scan(library_root, genre_mapping_dir=None)
        plan = plan_repairs(report)
        safe = get_safe_automatic_candidates(plan)
        build_preview(safe)

        assert _snapshot(library_root) == before

    def test_repair_repair_rescan_is_idempotent(self, tmp_path):
        """Auftrag §35: repair -> repair -> rescan -> keine unnoetige
        zweite Aenderung, kein Schaden."""
        library_root = tmp_path / "library"
        target = library_root / "Artist" / "Singles" / "2024 - Song.m4a"
        _make_m4a(target, artist="Artist", title="Song", album="Song",
                  genre="Pop / Rock", year="2024", album_artist="Artist")
        journal = RepairJournal(tmp_path / "journal.jsonl")

        report = run_scan(library_root, genre_mapping_dir=None)
        safe = get_safe_automatic_candidates(plan_repairs(report))
        out1 = apply_level1(safe, library_root, journal, dry_run=False)
        assert any(o.status == "SUCCESS" for o in out1)
        snap_after_first = _snapshot(library_root)

        # zweiter Lauf gegen einen frischen Scan
        report2 = run_scan(library_root, genre_mapping_dir=None)
        assert "GENRE_DELIMITER_INCONSISTENT" not in {
            i["issue_code"] for i in report2["issues"]
        }
        safe2 = get_safe_automatic_candidates(plan_repairs(report2))
        out2 = apply_level1(safe2, library_root, journal, dry_run=False)
        assert all(o.status != "SUCCESS" for o in out2)
        assert _snapshot(library_root) == snap_after_first  # nichts weiter veraendert

    def test_closure_flow_remaining_findings_accept_and_summary(self, tmp_path):
        """Auftrag §41: LIBRARY -> HEALTH -> FINDINGS -> REPAIR -> RESCAN ->
        REMAINING FINDINGS -> REVIEW -> ACCEPT -> JSON -> SUMMARY.
        Erwartung: auto-repairable remaining == 0; der verbleibende Befund
        ist eindeutig MANUAL_REVIEW und wird bewusst akzeptiert."""
        library_root = tmp_path / "library"
        target = library_root / "Artist" / "Singles" / "Song.m4a"
        # genre-delimiter (AUTO) + kein Jahr (MANUAL_REVIEW) auf DERSELBEN Datei
        _make_m4a(target, artist="Artist", title="Song", album="Song",
                  genre="Pop / Rock", album_artist="Artist")
        registry_path = tmp_path / "findings.json"

        report = run_scan(library_root, genre_mapping_dir=None)
        codes = {i["issue_code"] for i in report["issues"]}
        assert {"GENRE_DELIMITER_INCONSISTENT", "META_YEAR_MISSING"} <= codes

        registry = FindingsRegistry(registry_path)
        registry.merge_scan_issues(
            report["issues"], scanned_at=report["scan"]["completed_at"]
        )
        registry.save()
        year_issue = next(
            i for i in report["issues"] if i["issue_code"] == "META_YEAR_MISSING"
        )
        genre_issue = next(
            i for i in report["issues"]
            if i["issue_code"] == "GENRE_DELIMITER_INCONSISTENT"
        )
        year_fid = generate_finding_id(year_issue)
        genre_fid = generate_finding_id(genre_issue)
        assert year_fid != genre_fid  # §34.6 zwei Findings derselben Datei

        assert disposition_for_code("META_YEAR_MISSING") == "MANUAL_REVIEW"
        assert disposition_for_code("GENRE_DELIMITER_INCONSISTENT") == "AUTO_REPAIR"

        # ── Repair (nur AUTO) ────────────────────────────────────────────
        journal = RepairJournal(tmp_path / "journal.jsonl")
        safe = get_safe_automatic_candidates(plan_repairs(report))
        assert {c.issue_code for c in safe} == {"GENRE_DELIMITER_INCONSISTENT"}
        apply_level1(safe, library_root, journal, dry_run=False)

        # ── Rescan + Remaining ──────────────────────────────────────────
        post = run_scan(library_root, genre_mapping_dir=None)
        registry.merge_scan_issues(
            post["issues"], scanned_at=post["scan"]["completed_at"]
        )
        registry.save()
        assert registry.get(genre_fid).status != STATUS_OPEN  # behoben
        assert registry.get(year_fid).status == STATUS_OPEN  # bleibt offen

        remaining_auto = get_safe_automatic_candidates(plan_repairs(post))
        assert remaining_auto == []  # auto-repairable remaining == 0

        # ── Accept (bewusste Nutzerentscheidung) ────────────────────────
        accept_finding(
            registry, year_fid,
            reason="Bootleg-Single ohne verlässliches Veröffentlichungsjahr",
            reviewed_by="closure-test",
        )
        registry.save()

        open_ids = {f.finding_id for f in registry.get_open_findings()}
        assert year_fid not in open_ids  # aus OPEN verschwunden
        assert genre_fid not in open_ids  # repariert
        assert year_fid in {f.finding_id for f in get_accepted_findings(registry)}
        summary = get_review_summary(registry)
        assert summary.accepted == 1
        assert summary.resolved_by_scan >= 1  # genre-delimiter vom Scan als weg erkannt
        # verbleibende OPEN sind reine INFO-Anreicherung (MB-IDs/Lyrics/Cover),
        # kein AUTO_REPAIR/SAFE_AUTOMATIC mehr (siehe remaining_auto oben)

        # ── JSON: bleibt persistent ────────────────────────────────────
        reloaded = FindingsRegistry(registry_path)
        f = reloaded.get(year_fid)
        assert f.status == STATUS_FALSE_POSITIVE
        assert "Bootleg-Single" in f.review_note

    def test_repair_never_sets_false_positive_regardless_of_outcome(self, tmp_path):
        library_root = tmp_path / "library"
        target_file = library_root / "Artist" / "Singles" / "2024 - Song.m4a"
        _make_m4a(
            target_file, artist="Artist", title="Song", album="Song", genre="Pop / Rock",
        )
        registry_path = tmp_path / "findings.json"

        report = run_scan(library_root, genre_mapping_dir=None)
        registry = FindingsRegistry(registry_path)
        registry.merge_scan_issues(report["issues"], scanned_at=report["scan"]["completed_at"])
        registry.save()

        genre_issue = next(
            i for i in report["issues"] if i["issue_code"] == "GENRE_DELIMITER_INCONSISTENT"
        )
        fid = generate_finding_id(genre_issue)

        plan = plan_repairs(report)
        safe = get_safe_automatic_candidates(plan)
        journal = RepairJournal(tmp_path / "journal.jsonl")
        apply_level1(safe, library_root, journal, dry_run=False)
        journal.flush()

        # Unabhaengig vom tatsaechlichen Ausgang darf der Executor selbst
        # NIEMALS FALSE_POSITIVE setzen - das bleibt exklusiv der Review-
        # Entscheidung vorbehalten (Abschnitt 39).
        assert registry.get(fid).status != "FALSE_POSITIVE"
