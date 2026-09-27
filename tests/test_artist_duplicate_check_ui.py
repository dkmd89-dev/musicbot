# -*- coding: utf-8 -*-
"""Artist-Detailseite: Duplikat-Check (Job-Anbindung).

Backlog-Punkt "Duplikat-Check im CC" (docs/audits/
WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md §2.3 A / §5 Nr. 4a).

Markup/Verdrahtung ueber die echte create_app(); die Render-/Zustandsfunktionen
des Inline-Skripts werden aus dem Template extrahiert und real mit node
ausgefuehrt - identisches Testmuster wie
tests/test_artist_genre_revalidation_ui.py.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

TEMPLATE = Path(__file__).resolve().parent.parent / "control_center" / "templates" / "library_artist_detail.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_panel_explains_that_it_is_read_only(client):
    html = (await client.get("/library/Bausa")).text
    panel = html.split('id="duplicate-check-panel"', 1)[1].split('id="duplicate-check-content"', 1)[0]
    assert "wird nichts gelöscht" in panel
    assert "library_repair.py --allow-delete" in panel


@pytest.mark.asyncio
async def test_script_uses_api_url_and_polls_every_second(client):
    html = (await client.get("/library/Bausa")).text
    block = html.split("// -- Duplikat-Check", 1)[1].split('document.getElementById("genre-manage-preview-btn")', 1)[0]
    assert re.findall(r"fetch\((?!apiUrl)", block) == []
    assert "setInterval(() => _pollDuplicateCheckJob(_dupCheckJobId), 1000)" in block
    assert 'body: JSON.stringify({ artist })' in block


_FUNCS = ["_shortPath", "duplicateCheckResultHtml", "_dupCheckSetBusy", "_stopDupCheckPolling",
          "_renderDuplicateCheckJob"]

_HARNESS = r"""
const els = {};
const mk = (id) => (els[id] = els[id] || { id, innerHTML: "", disabled: false });
global.document = { getElementById: (id) => mk(id) };
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"));
global.clearInterval = () => {};
global.currentArtistFromPath = () => "Bausa";
let _dupCheckTimer = null;
%FUNCS%
const scenario = JSON.parse(process.argv[2]);
const out = {};
if (scenario.result) out.html = duplicateCheckResultHtml(scenario.result);
for (const job of scenario.jobs || []) _renderDuplicateCheckJob(job);
out.els = Object.fromEntries(Object.entries(els).map(([k, v]) => [k, { html: v.innerHTML, disabled: v.disabled }]));
console.log(JSON.stringify(out));
"""


def _extract(src: str, name: str) -> str:
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


def _run(tmp_path: Path, scenario: dict) -> dict:
    src = TEMPLATE.read_text(encoding="utf-8")
    script = tmp_path / "h.js"
    script.write_text(_HARNESS.replace("%FUNCS%", "\n".join(_extract(src, n) for n in _FUNCS)), encoding="utf-8")
    r = subprocess.run([_NODE, str(script), json.dumps(scenario)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _report(**over):
    base = {
        "duplicate_groups": 1, "resolved_groups": 1, "manual_review_groups": 0,
        "files_scanned": 4, "read_only_intact": True,
        "decisions": [{
            "title": "Song A", "action": "RESOLVED",
            "keep": "/library/Artist/Song A (320).m4a",
            "remove_proposal": ["/library/Artist/Song A (128).m4a"],
            "candidates": [
                {"path": "/library/Artist/Song A (320).m4a", "bitrate": 320},
                {"path": "/library/Artist/Song A (128).m4a", "bitrate": 128},
            ],
        }],
    }
    base.update(over)
    return base


def _job(status="SUCCEEDED", result=None, **kw):
    j = {"status": status, "progress": 100.0, "message": "", "result": result, "error": None}
    j.update(kw)
    return j


@needs_node
def test_no_duplicates_shows_a_success_message(tmp_path):
    html = _run(tmp_path, {"result": _report(duplicate_groups=0, resolved_groups=0, files_scanned=12)})["html"]
    assert "alert-success" in html and "Keine Duplikat-Gruppen gefunden" in html and "12 Dateien geprüft" in html


@needs_node
def test_resolved_group_shows_keep_and_remove_proposal_with_bitrates(tmp_path):
    html = _run(tmp_path, {"result": _report()})["html"]
    assert "Song A" in html
    assert "Behalten: Song A (320).m4a (320 kbps)" in html
    assert "Vorschlag entfernen: Song A (128).m4a (128 kbps)" in html
    assert "library_repair.py --allow-delete --artist Bausa --apply" in html


@needs_node
def test_manual_review_group_shows_the_reason_instead_of_a_proposal(tmp_path):
    html = _run(tmp_path, {"result": _report(decisions=[{
        "title": "Song B", "action": "MANUAL_REVIEW", "reason": "Uneindeutige Kandidaten",
    }])})["html"]
    assert "Song B" in html and "MANUAL_REVIEW" in html and "Uneindeutige Kandidaten" in html
    assert "Behalten:" not in html


@needs_node
def test_safety_violation_shows_a_warning_instead_of_decisions(tmp_path):
    html = _run(tmp_path, {"result": _report(read_only_intact=False)})["html"]
    assert "Sicherheitswarnung" in html and "verändert" in html
    assert "Song A" not in html


@needs_node
def test_result_escapes_all_server_values(tmp_path):
    html = _run(tmp_path, {"result": _report(decisions=[{
        "title": "<b>x</b>", "action": "MANUAL_REVIEW", "reason": "<script>s</script>",
    }])})["html"]
    assert "<b>" not in html and "<script>" not in html


@needs_node
def test_running_job_shows_progress(tmp_path):
    # Busy-Zustand des Buttons wird von startDuplicateCheck() gesetzt, nicht
    # vom Renderer (identisches Prinzip wie bei der Genre-Revalidierung) -
    # hier wird nur die Fortschrittsanzeige selbst geprueft.
    out = _run(tmp_path, {"jobs": [_job("RUNNING", None, progress=10.0, message="Duplikat-Scan läuft für Bausa…")]})
    assert "RUNNING (10%)" in out["els"]["duplicate-check-content"]["html"]


@needs_node
def test_failed_job_shows_the_error_and_reenables_the_button(tmp_path):
    out = _run(tmp_path, {"jobs": [_job("FAILED", None, error="Es läuft bereits eine Reparatur <b>")]})
    html = out["els"]["duplicate-check-content"]["html"]
    assert "Fehlgeschlagen: Es läuft bereits eine Reparatur" in html and "<b>" not in html
    assert out["els"]["duplicate-check-btn"]["disabled"] is False


@needs_node
def test_succeeded_job_renders_the_report(tmp_path):
    out = _run(tmp_path, {"jobs": [_job("SUCCEEDED", _report(duplicate_groups=0, resolved_groups=0))]})
    assert "Keine Duplikat-Gruppen gefunden" in out["els"]["duplicate-check-content"]["html"]
