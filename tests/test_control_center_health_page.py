# tests/test_control_center_health_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Health — Ergänzung zu tests/test_health_page_layout_a.py (dort ist
die Tab-/Findings-/Kennzahlen-Struktur festgeschrieben).

Hier: Browser-Dialoge durch ccConfirm/ccPrompt ersetzt (Nutzerentscheidung
2026-09-28: ein Dialog mit Eingabefeld statt prompt()+confirm(); Abbrechen
der SAFE_AUTOMATIC-Reparatur mit Nachfrage), Toasts statt alert(),
einheitliche Job-Anzeige, Log-Auszug im Terminal-Stil, keine Emojis.

Die echte static/pages/health.js läuft zusammen mit der echten
static/common.js in node. Ohne Tabler-JS fallen ccConfirm/ccPrompt auf
window.confirm/window.prompt zurück - darüber werden die Antworten gesteuert.
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

ROOT = Path(__file__).resolve().parent.parent
CC_DIR = ROOT / "control_center"
COMMON_JS = CC_DIR / "static" / "common.js"
HEALTH_JS = CC_DIR / "static" / "pages" / "health.js"
HEALTH_HTML = CC_DIR / "templates" / "health.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def test_health_has_no_browser_dialogs_emoji_or_inline_pre_style():
    js = HEALTH_JS.read_text(encoding="utf-8")
    html = HEALTH_HTML.read_text(encoding="utf-8")
    for call in ("window.alert", "window.confirm", "window.prompt"):
        assert call not in js, call
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert 'style="white-space' not in js
    assert "empty-note" not in js and "Lädt…" not in html


@pytest.mark.asyncio
async def test_health_header_follows_standard(client):
    html = (await client.get("/health")).text
    assert '<div class="page-pretitle">Wartung</div>' in html
    assert '<use href="#i-health"/></svg>Health</h2>' in html
    for icon in ("tool", "tag", "chart", "history"):
        assert f'<use href="#i-{icon}"/>' in html


_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const listeners = {};
  return { id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: "", dataset: {}, children: [],
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    setAttribute() {}, getAttribute() { return null; }, querySelector: () => null,
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    appendChild() {}, remove() {} };
};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
const confirms = []; const prompts = [];
const confirmAnswers = sc.confirm || []; const promptAnswers = sc.prompt || [];
global.window = {
  confirm: (t) => { confirms.push(t); return confirmAnswers.length ? confirmAnswers.shift() : true; },
  prompt: (t) => { prompts.push(t); return promptAnswers.length ? promptAnswers.shift() : null; },
};
global.console = { ...console, error() {} };
const intervals = [];
global.setInterval = (fn, ms) => { intervals.push(ms); return intervals.length; };
global.clearInterval = () => {};
const toasts = [];
const calls = [];
const responses = sc.responses || {};
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push({ call: method + " " + url, body: (opts && opts.body) || null });
  const r = responses[method + " " + url.split("?")[0]] || { status: 200, body: {} };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8")
  + "\n;ccToast = (k, t, x) => { toasts.push([k, t, x || ''].join('|')); };";
const api = new Function("toasts", src + "\nreturn { acceptFinding, resolveFinding, unacceptFinding, startRepairJob, cancelRepairJob, startLevel23Job, startHealthScanJob, _renderRepairJobStatus, _renderLevel23JobStatus };")(toasts);
const tick = () => new Promise((r) => setTimeout(r, 10));
(async () => {
  await tick();
  calls.length = 0;
  for (const op of sc.ops || []) {
    const args = (op.args || []).map((a) => (a === "@btn" ? mkEl("btn") : a));
    await api[op.fn](...args);
    await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, disabled: e.disabled, hidden: e.hidden };
  console.log(JSON.stringify({ els: out, calls, confirms, prompts, toasts, intervals }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _run(tmp_path, ops, confirm=None, prompt=None, responses=None) -> dict:
    scenario = {"ops": ops, "confirm": confirm or [], "prompt": prompt or [], "responses": responses or {}}
    script = tmp_path / "health_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(HEALTH_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _posts(out):
    return [c for c in out["calls"] if c["call"].startswith("POST")]


# ── Findings ─────────────────────────────────────────────────────────────

_ACCEPT = "POST /api/v1/library/findings/f1/accept"
_REVIEW = "POST /api/v1/library/findings/f1/review"


@needs_node
@pytest.mark.parametrize("answer", [None, "", "   "])
def test_accept_needs_reason_and_is_cancellable(tmp_path, answer):
    out = _run(tmp_path, [{"fn": "acceptFinding", "args": ["f1", "@btn"]}], prompt=[answer])
    assert len(out["prompts"]) == 1 and out["confirms"] == []     # ein Dialog statt zwei
    assert _posts(out) == []


@needs_node
def test_accept_posts_trimmed_reason_and_toasts(tmp_path):
    out = _run(tmp_path, [{"fn": "acceptFinding", "args": ["f1", "@btn"]}], prompt=["  bewusst so  "],
               responses={_ACCEPT: {"status": 200, "body": {}}})
    post = _posts(out)[0]
    assert post["call"] == _ACCEPT and json.loads(post["body"]) == {"reason": "bewusst so"}
    assert "ok|Finding akzeptiert|" in out["toasts"]


@needs_node
def test_accept_error_is_toast(tmp_path):
    out = _run(tmp_path, [{"fn": "acceptFinding", "args": ["f1", "@btn"]}], prompt=["x"],
               responses={_ACCEPT: {"status": 409, "body": {"error": {"message": "schon akzeptiert"}}}})
    assert "error|Finding nicht akzeptiert|schon akzeptiert" in out["toasts"]


@needs_node
@pytest.mark.parametrize("answer,note", [("", None), ("  repariert per Hand ", "repariert per Hand")])
def test_resolve_note_is_optional(tmp_path, answer, note):
    out = _run(tmp_path, [{"fn": "resolveFinding", "args": ["f1", "@btn"]}], prompt=[answer],
               responses={_REVIEW: {"status": 200, "body": {}}})
    assert out["confirms"] == [] and len(out["prompts"]) == 1
    assert json.loads(_posts(out)[0]["body"]) == {"status": "RESOLVED", "note": note}
    assert "ok|Als repariert markiert|" in out["toasts"]


@needs_node
def test_resolve_cancel_sends_nothing(tmp_path):
    out = _run(tmp_path, [{"fn": "resolveFinding", "args": ["f1", "@btn"]}], prompt=[None])
    assert _posts(out) == []


@needs_node
@pytest.mark.parametrize("answer,posted", [(False, False), (True, True)])
def test_unaccept_only_after_confirmation(tmp_path, answer, posted):
    out = _run(tmp_path, [{"fn": "unacceptFinding", "args": ["f1", "@btn"]}], confirm=[answer])
    assert out["confirms"] == ["Das Finding wird wieder als offen geführt."]
    assert bool(_posts(out)) is posted


# ── SAFE_AUTOMATIC / Abbrechen / L3 ──────────────────────────────────────

_JOB = {"job_id": "r1", "status": "RUNNING", "progress": 40, "message": "SAFE_AUTOMATIC-Reparatur läuft…"}


@needs_node
@pytest.mark.parametrize("answer,posted", [(False, False), (True, True)])
def test_repair_start_only_after_confirmation(tmp_path, answer, posted):
    out = _run(tmp_path, [{"fn": "startRepairJob"}], confirm=[answer],
               responses={"POST /api/v1/jobs/repair-safe-automatic": {"status": 202, "body": _JOB}})
    assert "es werden tatsächlich Dateien in der Library verändert" in out["confirms"][0]
    assert bool(_posts(out)) is posted
    if posted:
        html = out["els"]["repair-job-content"]["html"]
        assert "bg-teal-lt" in html and "Läuft" in html and "40 %" in html
        assert 1000 in out["intervals"]


@needs_node
@pytest.mark.parametrize("answer,cancelled", [(False, False), (True, True)])
def test_repair_cancel_needs_confirmation(tmp_path, answer, cancelled):
    responses = {"POST /api/v1/jobs/repair-safe-automatic": {"status": 202, "body": _JOB},
                 "POST /api/v1/jobs/r1/cancel": {"status": 200, "body": _JOB}}
    out = _run(tmp_path, [{"fn": "startRepairJob"}, {"fn": "cancelRepairJob"}], confirm=[True, answer], responses=responses)
    assert out["confirms"][1].startswith("Bereits reparierte Dateien bleiben unverändert")
    assert ("POST /api/v1/jobs/r1/cancel" in [c["call"] for c in out["calls"]]) is cancelled


@needs_node
def test_repair_result_states_and_escaped_terminal_tail(tmp_path):
    ok = {"status": "SUCCEEDED", "result": {"stdout_tail": "<script>x</script> fertig"}, "progress": 100}
    out = _run(tmp_path, [{"fn": "_renderRepairJobStatus", "args": [ok]}])
    html = out["els"]["repair-job-content"]["html"]
    assert "bg-green-lt" in html and "Reparatur abgeschlossen." in html
    assert '<pre class="cc-terminal' in html and "&lt;script&gt;" in html and "<script>" not in html
    assert "ok|SAFE_AUTOMATIC-Reparatur abgeschlossen|" in out["toasts"]

    failed = {"status": "FAILED", "error": "<b>kaputt</b>", "result": {"stderr_tail": "trace"}, "progress": 0}
    html = _run(tmp_path, [{"fn": "_renderRepairJobStatus", "args": [failed]}])["els"]["repair-job-content"]["html"]
    assert "bg-red-lt" in html and "&lt;b&gt;kaputt&lt;/b&gt;" in html and "cc-terminal" in html

    cancelled = {"status": "CANCELLED", "progress": 10}
    html = _run(tmp_path, [{"fn": "_renderRepairJobStatus", "args": [cancelled]}])["els"]["repair-job-content"]["html"]
    assert "bg-secondary-lt" in html and "Abgebrochen" in html


@needs_node
@pytest.mark.parametrize("answer,posted", [(False, False), (True, True)])
def test_level3_start_only_after_confirmation(tmp_path, answer, posted):
    out = _run(tmp_path, [{"fn": "startLevel23Job", "args": ["l3", "Kygo", "2"]}], confirm=[answer],
               responses={"POST /api/v1/jobs/repair-level3": {"status": 202, "body": {"job_id": "l1", "status": "PENDING", "progress": 0}}})
    assert "Kygo" in out["confirms"][0] and "MusicBrainz" in out["confirms"][0]
    assert bool(_posts(out)) is posted
    if posted:
        assert json.loads(_posts(out)[0]["body"]) == {"artist": "Kygo"}


@needs_node
@pytest.mark.parametrize("result,badge", [
    ({"status": "SUCCESS", "artist": "A", "level": "l3", "total": 3, "success": 3, "skipped": 0, "failed": 0,
      "resolved_count": 3, "changed_files": ["x"]}, "bg-green-lt"),
    ({"status": "UNRESOLVED", "artist": "A", "level": "l3", "total": 3, "success": 1, "skipped": 0, "failed": 0,
      "unresolved": 2, "resolved_count": 1, "changed_files": []}, "bg-yellow-lt"),
    ({"status": "FAILED", "artist": "A", "level": "l3", "total": 3, "success": 0, "skipped": 0, "failed": 3,
      "resolved_count": 0, "changed_files": []}, "bg-red-lt"),
])
def test_level3_result_badges(tmp_path, result, badge):
    out = _run(tmp_path, [{"fn": "_renderLevel23JobStatus", "args": [{"status": "SUCCEEDED", "result": result}]}])
    assert badge in out["els"]["level23-job-content"]["html"]


@needs_node
def test_health_scan_start_error_is_toast_not_alert(tmp_path):
    out = _run(tmp_path, [{"fn": "startHealthScanJob"}],
               responses={"POST /api/v1/jobs/health-scan": {"status": 409, "body": {"error": {"message": "läuft bereits"}}}})
    assert "error|Health-Scan nicht gestartet|läuft bereits" in out["toasts"]
    assert out["els"]["health-scan-btn"]["disabled"] is False
