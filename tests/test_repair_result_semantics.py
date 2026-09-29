# -*- coding: utf-8 -*-
"""Findings #4/#5/#6 — einheitliche Repair-Ergebnissemantik.

SUCCESS / UNRESOLVED / SKIPPED / FAILED müssen in Core
(repair_service._overall_status(), RepairRunResult/LevelRepairResult),
Job-Registry (control_center/routers/jobs.py::_run_level_repair_job()),
Telegram (_format_result()/_format_l23_result()) und UI (health.js,
library_artist_detail.html) aus denselben Rohdaten gleich interpretiert
werden. "geändert" = changed_files (tatsächlich geschrieben), NIE
affected_files (berührt, auch SKIPPED).

Fälle (Auftrag Phase 2):
  A  SUCCESS=5                               → SUCCESS, changed=5
  B  SUCCESS=5, UNRESOLVED=2, SKIPPED=3      → SUCCESS (Partial), Zähler sichtbar
  C  UNRESOLVED=5                            → UNRESOLVED (kein Erfolg, kein harter Fehler)
  D  SKIPPED=5                               → SKIPPED, nicht FAILED
  E  exit_code != 0 + Journal-Einträge       → kein SUCCESS
  F  Verifikation nach "SUCCESS" schlägt fehl → Eintrag UNRESOLVED (Executor,
     Library-Closure), Service übernimmt das, Finding bleibt OPEN

Bewusste Abweichung vom Auftragstext bei Fall B: "changed" zählt Dateien,
die tatsächlich geschrieben wurden - das schließt UNRESOLVED-Einträge ein
(Datei wurde geschrieben, nur die Verifikation schlug fehl; ARCH-033-F1
Fix (b), identisch zu scripts/library_repair.py::wrote_to_disk für den
Navidrome-Scan). Im Fall B mit je eigener Datei pro Eintrag ist changed
daher 7, nicht 5. Siehe docs/LIBRARY_REPAIR.md.
"""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import services.library_repair.repair_service as rs
from services.jobs.job_registry import JobRegistry
from services.library_health.findings import (
    STATUS_OPEN,
    FindingsRegistry,
    generate_finding_id,
)
from services.library_repair.doctor_runner import DoctorRepairResult, DoctorScanResult
from services.library_repair.repair_service import LevelRepairResult, RepairRunResult


def run(coro):
    return asyncio.run(coro)


def _counts(success=0, unresolved=0, skipped=0, failed=0):
    return {k: v for k, v in {
        "SUCCESS": success, "UNRESOLVED": unresolved, "SKIPPED": skipped, "FAILED": failed,
    }.items() if v}


def _entries(success=0, unresolved=0, skipped=0, failed=0):
    out = []
    for status, n in (("SUCCESS", success), ("UNRESOLVED", unresolved),
                      ("SKIPPED", skipped), ("FAILED", failed)):
        for i in range(n):
            out.append({"file": f"{status.lower()}_{i}.m4a", "status": status})
    return out


# ─────────────────────────────────────────────────────────────────────────
# Core: _overall_status() / _changed_files()
# ─────────────────────────────────────────────────────────────────────────


def _status(counts, exit_code=0, timed_out=False, error_message=None):
    return rs._overall_status(
        counts, exit_code=exit_code, timed_out=timed_out, error_message=error_message,
    )


class TestOverallStatus:
    def test_case_a_all_success(self):
        assert _status(_counts(success=5)) == "SUCCESS"

    def test_case_b_partial_success_stays_success(self):
        assert _status(_counts(success=5, unresolved=2, skipped=3)) == "SUCCESS"

    def test_case_c_unresolved_only_is_unresolved_not_failed_not_skipped(self):
        assert _status(_counts(unresolved=5)) == "UNRESOLVED"

    def test_case_d_skipped_only_is_skipped_not_failed(self):
        assert _status(_counts(skipped=5)) == "SKIPPED"

    def test_case_e_nonzero_exit_with_success_entries_is_not_success(self):
        assert _status(_counts(success=5), exit_code=1) == "UNRESOLVED"

    def test_case_e_nonzero_exit_without_writes_is_failed(self):
        assert _status(_counts(skipped=3), exit_code=1) == "FAILED"
        assert _status(_counts(failed=2), exit_code=1) == "FAILED"
        assert _status({}, exit_code=3) == "FAILED"

    def test_failed_only_is_failed(self):
        assert _status(_counts(failed=2)) == "FAILED"
        assert _status(_counts(failed=2, unresolved=1)) == "FAILED"

    def test_failed_with_success_stays_success_partial(self):
        assert _status(_counts(success=1, failed=2)) == "SUCCESS"

    def test_timeout_or_error_message_is_failed(self):
        assert _status(_counts(success=5), timed_out=True) == "FAILED"
        assert _status(_counts(success=5), error_message="x") == "FAILED"

    def test_empty_run_is_skipped(self):
        assert _status({}) == "SKIPPED"
        assert _status({}, exit_code=None) == "SKIPPED"


class TestChangedFiles:
    def test_success_and_unresolved_count_skipped_and_failed_do_not(self):
        entries = _entries(success=2, unresolved=1, skipped=3, failed=1)
        assert rs._changed_files(entries) == [
            "success_0.m4a", "success_1.m4a", "unresolved_0.m4a",
        ]

    def test_skipped_with_sha_diff_counts(self):
        entries = [{"file": "a.m4a", "status": "SKIPPED",
                    "sha256_before": "x", "sha256_after": "y"}]
        assert rs._changed_files(entries) == ["a.m4a"]

    def test_same_file_multiple_entries_counted_once(self):
        entries = [{"file": "a.m4a", "status": "SUCCESS"},
                   {"file": "a.m4a", "status": "UNRESOLVED"}]
        assert rs._changed_files(entries) == ["a.m4a"]


# ─────────────────────────────────────────────────────────────────────────
# Core: echte Orchestrierung (SAFE_AUTOMATIC + L3), Subprozess gemockt
# ─────────────────────────────────────────────────────────────────────────


def _issue(code, path, artist="Bausa"):
    return {
        "issue_code": code, "severity": "WARNING", "scope": "file", "path": path,
        "artist": artist, "album": None, "title": None, "message": f"msg {code}",
        "details": {}, "confidence": None, "related_files": [],
    }


def _report(issues):
    return {
        "schema_version": "1.0",
        "scan": {"started_at": "t0", "completed_at": "t1", "duration_seconds": 1.0},
        "library": {"root": "/lib", "files": len(issues), "artists": 1, "albums": 1},
        "health": {"score": 95.0, "status": "EXCELLENT"},
        "statistics": {},
        "issues": issues,
    }


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.Config, "DATA_DIR", tmp_path)
    yield tmp_path


SAFE = ("safe", "META_ALBUM_ARTIST_MISSING", "run_safe_automatic_repair")
L3 = ("l3", "META_MB_RECORDING_MISSING", "run_level3_repair")


def _run_service(kind, *, exit_code, entries, issues_open_after=None):
    """Führt execute_safe_automatic_repair()/execute_level3_repair() mit
    gemocktem Scan/Subprozess aus; der Fake-Subprozess schreibt `entries`
    ins echte Journal (dasselbe Muster wie tests/test_repair_service.py)."""
    level, code, run_attr = kind
    issue = _issue(code, "Bausa/Singles/a.m4a")
    registry = FindingsRegistry(rs._findings_registry_path())
    registry.merge_scan_issues([issue], scanned_at="2026-01-01T00:00:00Z")
    registry.save()
    fid = generate_finding_id(issue)

    pre_scan = DoctorScanResult(exit_code=0, report=_report([issue]))
    post_issues = []
    if issues_open_after:
        post_issues = [{**issue, "finding_id": fid, "finding_status": STATUS_OPEN}]
    post_scan = DoctorScanResult(exit_code=0, report=_report(post_issues))

    jpath = rs.journal_path()
    jpath.parent.mkdir(parents=True, exist_ok=True)

    def _fake_apply(*_a, **_kw):
        with open(jpath, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps({"timestamp": "t", "issue_code": code,
                                    "action": "X", **e}) + "\n")
        return DoctorRepairResult(exit_code=exit_code, stderr_tail="boom")

    with patch.object(rs, "run_health_scan", new=AsyncMock(side_effect=[pre_scan, post_scan])), \
         patch.object(rs, run_attr, new=AsyncMock(side_effect=_fake_apply)):
        if level == "safe":
            result = run(rs.execute_safe_automatic_repair(triggered_by="test"))
        else:
            result = run(rs.execute_level3_repair("Bausa", triggered_by="test"))
    return result, fid


def _unresolved(result):
    return result.unresolved


def _success(result):
    if isinstance(result, RepairRunResult):
        return result.status_counts.get("SUCCESS", 0)
    return result.success


@pytest.mark.parametrize("kind", [SAFE, L3], ids=["safe_automatic", "l3"])
class TestServiceCases:
    def test_case_a(self, kind):
        result, _ = _run_service(kind, exit_code=0, entries=_entries(success=5))
        assert result.status == "SUCCESS"
        assert len(result.changed_files) == 5
        assert result.exit_code == 0

    def test_case_b(self, kind):
        result, _ = _run_service(
            kind, exit_code=0, entries=_entries(success=5, unresolved=2, skipped=3),
        )
        assert result.status == "SUCCESS"
        assert _success(result) == 5
        assert _unresolved(result) == 2
        assert len(result.affected_files) == 10
        # geschrieben: 5 SUCCESS + 2 UNRESOLVED (siehe Modul-Docstring)
        assert len(result.changed_files) == 7

    def test_case_c(self, kind):
        result, _ = _run_service(kind, exit_code=0, entries=_entries(unresolved=5))
        assert result.status == "UNRESOLVED"
        assert result.error_message is None

    def test_case_d(self, kind):
        result, _ = _run_service(kind, exit_code=0, entries=_entries(skipped=5))
        assert result.status == "SKIPPED"
        assert result.changed_files == []
        assert len(result.affected_files) == 5

    def test_case_e_exit_code_not_hidden_by_journal(self, kind):
        result, _ = _run_service(kind, exit_code=1, entries=_entries(success=5))
        assert result.status != "SUCCESS"
        assert result.status == "UNRESOLVED"
        assert result.exit_code == 1
        runs = rs.load_repair_history(limit=1)
        assert runs[0]["status"] == "UNRESOLVED"
        assert runs[0]["exit_code"] == 1
        assert len(runs[0]["changed_files"]) == 5

    def test_case_e_crash_without_journal_is_failed(self, kind):
        result, _ = _run_service(kind, exit_code=3, entries=[])
        assert result.status == "FAILED"
        assert "Exit-Code 3" in result.error_message

    def test_case_f_verification_failure_keeps_finding_open(self, kind):
        # Executor (_verify_issue_resolved(), Library-Closure) hat den
        # vermeintlichen SUCCESS bereits zu UNRESOLVED herabgestuft.
        entry = {"file": "Bausa/Singles/a.m4a", "status": "UNRESOLVED",
                 "reason": "Befund nach Reparatur weiterhin erkannt"}
        result, fid = _run_service(
            kind, exit_code=0, entries=[entry], issues_open_after=True,
        )
        assert result.status == "UNRESOLVED"
        assert result.resolved_count == 0
        assert result.changed_files == ["Bausa/Singles/a.m4a"]
        registry = FindingsRegistry(rs._findings_registry_path())
        assert registry.get(fid).status == STATUS_OPEN


# ─────────────────────────────────────────────────────────────────────────
# Telegram: _format_result() (SAFE_AUTOMATIC) + _format_l23_result()
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def handler():
    from handlers.repair_musicbot_handler import RepairMusicBotHandler
    return RepairMusicBotHandler(config=Mock(), logger_factory=lambda name: Mock())


def _safe_result(status, counts, *, exit_code=0, changed=None, affected=None):
    entries = _entries(**{k.lower(): v for k, v in counts.items()})
    return RepairRunResult(
        repair_id="r", status=status, started_at="t0", finished_at="t1",
        candidates_total=sum(counts.values()), resolved_count=0,
        status_counts=counts,
        affected_files=affected if affected is not None else [e["file"] for e in entries],
        changed_files=changed if changed is not None else rs._changed_files(entries),
        exit_code=exit_code,
    )


def _l23_result(status, counts, *, exit_code=0):
    entries = _entries(**{k.lower(): v for k, v in counts.items()})
    return LevelRepairResult(
        repair_id="r", artist="Bausa", level="l3", status=status,
        started_at="t0", finished_at="t1", total=sum(counts.values()),
        success=counts.get("SUCCESS", 0), failed=counts.get("FAILED", 0),
        skipped=counts.get("SKIPPED", 0), unresolved=counts.get("UNRESOLVED", 0),
        affected_files=[e["file"] for e in entries],
        changed_files=rs._changed_files(entries), exit_code=exit_code,
    )


class TestTelegramFormatResult:
    def test_case_a(self, handler):
        text = handler._format_result(_safe_result("SUCCESS", _counts(success=5)))
        assert text.startswith("✅")
        assert "Geänderte Dateien: 5" in text

    def test_case_b_shows_unresolved_and_changed_not_affected(self, handler):
        text = handler._format_result(
            _safe_result("SUCCESS", _counts(success=5, unresolved=2, skipped=3)),
        )
        assert text.startswith("🟠")
        assert "Erfolgreich: 5" in text
        assert "Überprüfen: 2" in text
        assert "Übersprungen: 3" in text
        assert "Geänderte Dateien: 7" in text  # nicht 10 (affected)

    def test_case_c_unresolved_only_is_orange_not_red(self, handler):
        text = handler._format_result(_safe_result("UNRESOLVED", _counts(unresolved=5)))
        assert text.startswith("🟠")
        assert "❌" not in text
        assert "Überprüfung nötig" in text

    def test_case_d_skipped_only_is_not_red(self, handler):
        text = handler._format_result(_safe_result("SKIPPED", _counts(skipped=5)))
        assert text.startswith("🟡")
        assert "❌" not in text
        assert "Geänderte Dateien: 0" in text

    def test_case_e_exit_code_warning(self, handler):
        text = handler._format_result(
            _safe_result("UNRESOLVED", _counts(success=5), exit_code=1),
        )
        assert text.startswith("🟠")
        assert "Exit-Code 1" in text

    def test_all_failed_header_is_not_partial(self, handler):
        text = handler._format_result(_safe_result("FAILED", _counts(failed=3)))
        assert text.startswith("❌")
        assert "teilweise" not in text
        assert "fehlgeschlagen" in text

    def test_failed_with_success_is_partial(self, handler):
        text = handler._format_result(_safe_result("SUCCESS", _counts(success=1, failed=1)))
        assert text.startswith("❌")
        assert "teilweise abgeschlossen" in text

    def test_zero_exit_has_no_warning(self, handler):
        text = handler._format_result(_safe_result("SUCCESS", _counts(success=1)))
        assert "Exit-Code" not in text


class TestTelegramL23SharesSemantics:
    @pytest.mark.parametrize("status,counts,emoji", [
        ("SUCCESS", _counts(success=5), "✅"),
        ("SUCCESS", _counts(success=5, unresolved=2, skipped=3), "🟠"),
        ("UNRESOLVED", _counts(unresolved=5), "🟠"),
        ("SKIPPED", _counts(skipped=5), "🟡"),
        ("UNRESOLVED", _counts(success=5), "🟠"),  # Fall E (exit 1)
        ("FAILED", _counts(failed=5), "❌"),
    ])
    def test_same_emoji_as_safe_automatic(self, handler, status, counts, emoji):
        exit_code = 1 if (status == "UNRESOLVED" and "SUCCESS" in counts) else 0
        safe = handler._format_result(_safe_result(status, counts, exit_code=exit_code))
        l23 = handler._format_l23_result("l3", "Bausa", _l23_result(status, counts, exit_code=exit_code))
        assert safe.startswith(emoji)
        assert l23.startswith(emoji)

    def test_l23_exit_code_warning(self, handler):
        text = handler._format_l23_result(
            "l3", "Bausa", _l23_result("UNRESOLVED", _counts(success=5), exit_code=1),
        )
        assert "Exit-Code 1" in text


# ─────────────────────────────────────────────────────────────────────────
# Control Center: Job-Ergebnis (_run_level_repair_job)
# ─────────────────────────────────────────────────────────────────────────


def _run_job(result):
    import control_center.routers.jobs as jobs_router

    registry = JobRegistry()
    job = registry.create(kind="repair_level3", initiator="1")

    async def _fake_execute(artist, *, triggered_by):
        return result

    with patch.object(jobs_router, "execute_level3_repair", _fake_execute):
        run(jobs_router._run_level_repair_job(
            registry, job.job_id, level="l3", artist="Bausa", user_id="1",
        ))
    return registry.get(job.job_id)


class TestControlCenterJobResult:
    def test_case_b_result_carries_changed_and_unresolved(self):
        job = _run_job(_l23_result("SUCCESS", _counts(success=5, unresolved=2, skipped=3)))
        assert job.status.value == "SUCCEEDED"
        r = job.result
        assert r["success"] == 5
        assert r["unresolved"] == 2
        assert r["skipped"] == 3
        assert len(r["changed_files"]) == 7
        assert len(r["affected_files"]) == 10  # kompatibel erhalten, aber != geändert

    def test_case_c_unresolved_job_is_not_failed(self):
        job = _run_job(_l23_result("UNRESOLVED", _counts(unresolved=5)))
        assert job.status.value == "SUCCEEDED"
        assert job.result["status"] == "UNRESOLVED"

    def test_case_e_exit_code_in_result(self):
        job = _run_job(_l23_result("UNRESOLVED", _counts(success=5), exit_code=1))
        assert job.result["exit_code"] == 1
        assert job.result["status"] == "UNRESOLVED"

    def test_failed_is_failed_job(self):
        result = _l23_result("FAILED", _counts(failed=5))
        job = _run_job(result)
        assert job.status.value == "FAILED"


# ─────────────────────────────────────────────────────────────────────────
# UI: health.js + library_artist_detail.html real ausgeführt (node)
# ─────────────────────────────────────────────────────────────────────────

_NODE = shutil.which("node")
_CC = Path(__file__).resolve().parent.parent / "control_center"
_HEALTH_JS = _CC / "static" / "pages" / "health.js"
# _renderLevel23JobStatus ruft zusaetzlich _jobResultHtml auf (seit #358,
# Health nach UI-Standard). Die drei Helper werden mit extrahiert.
_HEALTH_HELPERS = ("_repairOutcomeText", "_repairCountsText", "_jobResultHtml")


def _extract_function(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


_HARNESS = r"""
const src = require("fs").readFileSync(process.argv[2], "utf-8");
const job = JSON.parse(process.argv[3]);
const el = { innerHTML: "" };
global.document = { getElementById: () => el, querySelectorAll: () => [] };
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"));
const noop = () => {};
const render = new Function(
  "_stopLevel23JobPolling", "_setLevel23ButtonsDisabled", "loadRepairHistory",
  "loadRepairStatistics", "loadJobs", "_stopArtistRepairJobPolling",
  "_setArtistRepairButtonsDisabled", "_LEVEL23_LABELS", "_ARTIST_REPAIR_LEVEL_LABELS",
  "ccStatusBadge", "ccToast",
  src + "\nreturn RENDER;",
)(noop, noop, noop, noop, noop, noop, noop, {}, {},
   // Stub aus common.js: reproduziert das von _jobResultHtml erwartete
   // Klassenschema "dot-<kind>" (der Test prueft "dot-warn").
   (kind, label) => `<span class="badge dot-${kind}">${_escapeHtml(label)}</span>`,
   noop);
render(job);
process.stdout.write(el.innerHTML);
"""


def _render(path: Path, render_fn: str, result: dict, tmp_path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    code = "\n".join(
        _extract_function(src, n) for n in (*_HEALTH_HELPERS, render_fn)
    )
    snippet = tmp_path / "snippet.js"
    snippet.write_text(code, encoding="utf-8")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS.replace("RENDER", render_fn), encoding="utf-8")
    job = {"status": "SUCCEEDED", "progress": 100, "result": result}
    out = subprocess.run(
        [_NODE, str(harness), str(snippet), json.dumps(job)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return out.stdout


def _job_result(status, counts, exit_code=0):
    entries = _entries(**{k.lower(): v for k, v in counts.items()})
    return {
        "artist": "Bausa", "level": "l3", "status": status, "total": len(entries),
        "success": counts.get("SUCCESS", 0), "failed": counts.get("FAILED", 0),
        "skipped": counts.get("SKIPPED", 0), "unresolved": counts.get("UNRESOLVED", 0),
        "resolved_count": 0, "affected_files": [e["file"] for e in entries],
        "changed_files": rs._changed_files(entries), "exit_code": exit_code,
    }


_UI_TARGETS = [
    (_HEALTH_JS, "_renderLevel23JobStatus"),
    # library_artist_detail.html / _renderArtistRepairJobStatus entfaellt:
    # L3-Repair laeuft seit CC-UI L4 ausschliesslich auf der Health-Seite
    # (FINDINGS_INDEX-Zeile "Library L4"), die Artist-Detail-Seite rendert
    # keine Repair-Jobs mehr. Die Ergebnissemantik wird ueber [health_js]
    # abgedeckt.
]


@pytest.mark.skipif(_NODE is None, reason="node nicht verfügbar")
@pytest.mark.parametrize("path,render_fn", _UI_TARGETS, ids=["health_js"])
class TestUiRendering:
    def test_case_b_uses_changed_files_and_shows_unresolved(self, path, render_fn, tmp_path):
        html = _render(path, render_fn,
                       _job_result("SUCCESS", _counts(success=5, unresolved=2, skipped=3)), tmp_path)
        assert "7 Datei(en) geändert" in html
        assert "10 Datei(en) geändert" not in html
        assert "2 zu überprüfen" in html
        assert "Überprüfung nötig" in html

    def test_case_c_warn_not_ok(self, path, render_fn, tmp_path):
        html = _render(path, render_fn, _job_result("UNRESOLVED", _counts(unresolved=5)), tmp_path)
        assert "dot-warn" in html
        assert "dot-ok" not in html

    def test_case_d_skipped_is_not_reported_as_no_findings(self, path, render_fn, tmp_path):
        html = _render(path, render_fn, _job_result("SKIPPED", _counts(skipped=5)), tmp_path)
        assert "nichts zu tun" in html
        assert "0 Datei(en) geändert" in html
        assert "dot-error" not in html

    def test_case_e_exit_code_note(self, path, render_fn, tmp_path):
        html = _render(path, render_fn,
                       _job_result("UNRESOLVED", _counts(success=5), exit_code=1), tmp_path)
        assert "Exit-Code 1" in html
        assert "dot-warn" in html

    def test_case_a_success(self, path, render_fn, tmp_path):
        html = _render(path, render_fn, _job_result("SUCCESS", _counts(success=5)), tmp_path)
        assert "dot-ok" in html
        assert "5 Datei(en) geändert" in html
        assert "Exit-Code" not in html
