# tests/test_control_center_downloads_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Downloads — Darstellung nach docs/CONTROL_CENTER_UI_STANDARD.md.

Die echte static/pages/downloads.js läuft zusammen mit der echten
static/common.js in node gegen einen Fake-DOM und eine Fake-API (Muster wie
tests/test_control_center_overview_page.py). Unverändert bleiben müssen:
Endpunkte, Polling (Job 1 s, Verlauf 30 s), Rehydrate über localStorage,
Berechnungen der Kennzahlen/Metadaten-Quoten. Neu: Job-Karte mit Phasen,
Job-Verlauf im Seitenpanel, Abbrechen nur nach Bestätigung, Verlauf als
Tabelle.
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
DOWNLOADS_JS = CC_DIR / "static" / "pages" / "downloads.js"
DOWNLOADS_HTML = CC_DIR / "templates" / "downloads.html"
JOBS_ROUTER = CC_DIR / "routers" / "jobs.py"
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


# ─────────────────────────────────────────────────────────────────────────
# Template / statisch
# ─────────────────────────────────────────────────────────────────────────


def test_downloads_template_and_js_have_no_emoji_and_no_inline_icon_set():
    js = DOWNLOADS_JS.read_text(encoding="utf-8")
    html = DOWNLOADS_HTML.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "_DL_ICON_PATHS" not in js and "_dlIcon" not in js   # Sprite statt eigener Icon-Sammlung
    assert "window.alert" not in js and "confirm(" not in js.replace("ccConfirm(", "")
    assert "<svg xmlns" not in html                              # nur Sprite-<use>


def test_phase_messages_in_jobs_router_are_the_ones_the_ui_maps():
    """Die Phasen-Schrittfolge leitet sich aus den Job-Meldungen ab - ändert
    sich ein Text in routers/jobs.py, muss downloads.js mitgezogen werden."""
    router = JOBS_ROUTER.read_text(encoding="utf-8")
    js = DOWNLOADS_JS.read_text(encoding="utf-8")
    for msg, prefix in (
        ('"Duplikat-Prüfung…"', '"Duplikat-Prüfung"'),
        ('"Download läuft…"', '"Download läuft"'),
        ('f"Metadaten: {step}"', '"Metadaten"'),
        ('"Metadaten werden verarbeitet…"', '"Metadaten"'),
        ('"Zusammenfassung wird erstellt…"', '"Zusammenfassung"'),
    ):
        assert msg in router, f"Job-Meldung {msg} fehlt in routers/jobs.py"
        assert f"m.startsWith({prefix})" in js


@pytest.mark.asyncio
async def test_downloads_page_uses_standard_header_and_offcanvas(client):
    html = (await client.get("/downloads")).text

    assert '<div class="page-pretitle">Musik</div>' in html
    assert '<use href="#i-download"/></svg>Downloads</h2>' in html
    assert 'id="download-events-offcanvas"' in html
    for icon in ("link", "refresh", "chart", "history", "search", "alert", "music", "minus", "copy"):
        assert f'id="i-{icon}"' in html, f"Symbol i-{icon} fehlt im gerenderten Sprite"


# ─────────────────────────────────────────────────────────────────────────
# downloads.js real ausgeführt
# ─────────────────────────────────────────────────────────────────────────

_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const cls = new Set(); const attrs = {}; const listeners = {};
  const el = {
    id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: "", dataset: {},
    classList: { add: (c) => cls.add(c), remove: (...cs) => cs.forEach((c) => cls.delete(c)),
                 contains: (c) => cls.has(c), toggle: (c, f) => { (f === undefined ? !cls.has(c) : f) ? cls.add(c) : cls.delete(c); } },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    querySelector: () => null, addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    appendChild: () => {}, scrollIntoView: () => {}, remove: () => {},
    get firstElementChild() { return el._child || (el._child = mkEl(id + ":child")); },
    _cls: cls, _attrs: attrs, _listeners: listeners,
  };
  return el;
};
const storage = { ...(sc.storage || {}) };
global.localStorage = {
  getItem: (k) => (k in storage ? storage[k] : null),
  setItem: (k, v) => { storage[k] = String(v); }, removeItem: (k) => { delete storage[k]; },
};
global.document = {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { appendChild: () => {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
let confirmAnswer = sc.confirm !== undefined ? sc.confirm : true;
const confirms = [];
global.window = { confirm: (t) => { confirms.push(t); return confirmAnswer; } };
global.console = { ...console, error: () => {} };
const intervals = [];
global.setInterval = (fn, ms) => { intervals.push(ms); return intervals.length; };
global.clearInterval = () => {};
const calls = [];
const responses = sc.responses;
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push(method + " " + url);
  const key = method + " " + url.split("?")[0];
  let r = responses[key];
  if (Array.isArray(r)) r = r.length > 1 ? r.shift() : r[0];
  if (!r) r = { status: 500, body: { error: { message: "unerwartet" } } };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
const api = new Function(src + "\nreturn { _pollDownloadJob, cancelDownload, _setDownloadStatusFilter, _rerenderDownloads, _downloadPhaseIndex };")();
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  const snapshots = {};
  for (const op of sc.ops || []) {
    if (op.op === "click") { for (const f of (els[op.id] && els[op.id]._listeners.click) || []) await f({ target: { closest: () => null } }); }
    if (op.op === "submit") { for (const f of (els[op.id] && els[op.id]._listeners.submit) || []) await f({ preventDefault: () => {} }); }
    if (op.op === "call") { await api[op.fn](...(op.args || [])); }
    if (op.op === "set") { els[op.id] = els[op.id] || mkEl(op.id); els[op.id][op.key] = op.value; }
    if (op.op === "snap") { snapshots[op.name] = els[op.id] ? els[op.id].innerHTML : null; }
    await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, hidden: e.hidden, disabled: e.disabled };
  console.log(JSON.stringify({ els: out, calls, intervals, confirms, storage, snapshots,
    phases: ["Duplikat-Prüfung…", "Download läuft… 3/10", "Metadaten: Genre bestimmen…",
             "Metadaten werden verarbeitet…", "Zusammenfassung wird erstellt…", "irgendwas"].map(api._downloadPhaseIndex) }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}
_HISTORY_KEY = "GET /api/v1/downloads/history"


def _entry(title, artist, status="success", **tiers):
    e = {"title": title, "artist": artist, "status": status, "url": f"https://youtu.be/{title}",
         "timestamp": "2026-09-28T10:00:00"}
    e.update({k: tiers.get(k) for k in ("genre_ok", "lyrics_ok", "cover_ok", "mb_ok", "loudness_ok")})
    return e


def _run(tmp_path, responses=None, ops=None, storage=None, confirm=True) -> dict:
    base = {"GET /api/v1/auth/whoami": _WHOAMI, _HISTORY_KEY: {"status": 200, "body": {"entries": []}}}
    base.update(responses or {})
    scenario = {"responses": base, "ops": ops or [], "storage": storage or {}, "confirm": confirm}
    script = tmp_path / "downloads_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(DOWNLOADS_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


_JOB_KEY = "GET /api/v1/jobs/download/abc12345"
_STORED = {"musicbot_cc_active_download_job_id": "abc12345"}


def _job(status="RUNNING", message="Metadaten: Genre bestimmen…", progress=20.0, **extra):
    job = {"job_id": "abc12345", "status": status, "message": message, "progress": progress,
           "started_at": None, "context": {"download_type": "single"},
           "events": [{"at": "2026-09-28T10:00:00", "message": "Download läuft…"},
                      {"at": "2026-09-28T10:00:05", "message": "<b>Metadaten</b>"}]}
    job.update(extra)
    return job


@needs_node
def test_phase_index_mapping(tmp_path):
    assert _run(tmp_path)["phases"] == [0, 1, 2, 2, 3, -1]


@needs_node
def test_polling_intervals_and_endpoints_unchanged(tmp_path):
    out = _run(tmp_path, responses={_JOB_KEY: {"status": 200, "body": _job()}}, storage=_STORED)

    assert 1000 in out["intervals"] and 30000 in out["intervals"]
    assert "GET /api/v1/downloads/history?limit=200" in out["calls"]
    assert "GET /api/v1/jobs/download/abc12345" in out["calls"]


@needs_node
def test_idle_state_is_empty_component(tmp_path):
    out = _run(tmp_path, ops=[{"op": "call", "fn": "_pollDownloadJob", "args": ["gone"]}],
               responses={"GET /api/v1/jobs/download/gone": {"status": 404, "body": {"error": {"message": "x"}}}})
    html = out["els"]["download-status-content"]["html"]

    assert 'class="empty' in html and "Kein aktiver Download" in html


@needs_node
def test_running_job_card_with_badges_phase_progress_and_escaped_events(tmp_path):
    out = _run(tmp_path, responses={_JOB_KEY: {"status": 200, "body": _job()}}, storage=_STORED)
    card = out["els"]["download-status-content"]["html"]
    events = out["els"]["download-events-content"]["html"]

    assert "Metadaten: Genre bestimmen…" in card
    assert 'class="badge bg-teal-lt"' in card and "Läuft" in card
    assert "Einzeltitel" in card and "Job abc12345" in card
    assert 'class="step-item active">Metadaten</li>' in card
    assert "Phase 3 von 4 · Metadaten" in card
    assert 'style="width: 20%"' in card and "20 %" in card
    assert 'data-bs-target="#download-events-offcanvas"' in card and "Verlauf (2)" in card
    assert 'id="download-cancel-btn"' in card
    assert "timeline-event" in events
    assert "&lt;b&gt;Metadaten&lt;/b&gt;" in events and "<b>Metadaten</b>" not in events
    assert out["els"]["download-start-btn"]["disabled"] is True


@needs_node
def test_pending_job_shows_no_phase(tmp_path):
    out = _run(tmp_path, responses={_JOB_KEY: {"status": 200, "body": _job(status="PENDING", message="Wartet…", progress=0)}},
               storage=_STORED)
    card = out["els"]["download-status-content"]["html"]

    assert "Wartet" in card and "bg-secondary-lt" in card
    assert "step-item" not in card


@needs_node
@pytest.mark.parametrize("job,alert,text", [
    ({"status": "SUCCEEDED", "result": {"outcome": "success", "message": "Fertig: `a.mp3`"}}, "alert-success", "<code>a.mp3</code>"),
    ({"status": "SUCCEEDED", "result": {"outcome": "duplicate", "message": "Schon da", "artist": "Cro"}}, "alert-info", "Zum Artist „Cro"),
    ({"status": "FAILED", "error": "<x>kaputt"}, "alert-danger", "&lt;x&gt;kaputt"),
    ({"status": "CANCELLED"}, "alert-secondary", "Download abgebrochen."),
])
def test_job_results(tmp_path, job, alert, text):
    body = _job(**job)
    out = _run(tmp_path, responses={_JOB_KEY: {"status": 200, "body": body}}, storage=_STORED)
    card = out["els"]["download-status-content"]["html"]

    assert f"alert {alert}" in card and text in card
    assert 'style="white-space' not in card
    assert "Verlauf (2)" in card
    assert "musicbot_cc_active_download_job_id" not in out["storage"]
    assert out["els"]["download-start-btn"]["disabled"] is False


@needs_node
def test_cancel_only_after_confirmation(tmp_path):
    ops = [{"op": "click", "id": "download-cancel-btn"}]
    responses = {_JOB_KEY: {"status": 200, "body": _job()},
                 "POST /api/v1/jobs/download/abc12345/cancel": {"status": 200, "body": _job()}}

    declined = _run(tmp_path, responses=responses, storage=_STORED, ops=ops, confirm=False)
    assert declined["confirms"] == ["Bereits fertige Titel bleiben erhalten."]
    assert not any(c.startswith("POST") for c in declined["calls"])

    confirmed = _run(tmp_path, responses=responses, storage=_STORED, ops=ops, confirm=True)
    assert "POST /api/v1/jobs/download/abc12345/cancel" in confirmed["calls"]


@needs_node
def test_start_download_posts_trimmed_url_and_polls(tmp_path):
    responses = {"POST /api/v1/jobs/download": {"status": 202, "body": _job(status="PENDING", message="Wartet…", progress=0)}}
    ops = [{"op": "set", "id": "download-url-input", "key": "value", "value": " https://youtu.be/x "},
           {"op": "submit", "id": "download-start-form"}]
    out = _run(tmp_path, responses=responses, ops=ops)

    assert "POST /api/v1/jobs/download" in out["calls"]
    assert out["storage"]["musicbot_cc_active_download_job_id"] == "abc12345"
    assert 1000 in out["intervals"]
    assert "Wartet" in out["els"]["download-status-content"]["html"]
    assert out["els"]["download-start-btn"]["disabled"] is True


@needs_node
def test_start_error_is_shown_in_card_and_form_unlocked(tmp_path):
    responses = {"POST /api/v1/jobs/download": {"status": 400, "body": {"error": {"message": "URL <nicht> unterstützt"}}}}
    ops = [{"op": "set", "id": "download-url-input", "key": "value", "value": "https://example.com"},
           {"op": "submit", "id": "download-start-form"}]
    out = _run(tmp_path, responses=responses, ops=ops)
    card = out["els"]["download-status-content"]["html"]

    assert "alert alert-danger" in card and "URL &lt;nicht&gt; unterstützt" in card
    assert out["els"]["download-start-btn"]["disabled"] is False
    assert "musicbot_cc_active_download_job_id" not in out["storage"]


@needs_node
def test_history_table_escaped_with_german_status_and_tiers(tmp_path):
    entries = [
        _entry("<i>Eins</i>", "A & B", "success", genre_ok=True, lyrics_ok=False),
        _entry("Zwei", "C", "failed"),
        _entry("Drei", "D", "cancelled"),
    ]
    out = _run(tmp_path, responses={_HISTORY_KEY: {"status": 200, "body": {"entries": entries}}})
    html = out["els"]["downloads-content"]["html"]

    assert "table card-table" in html and "<th>Status</th>" in html
    assert "&lt;i&gt;Eins&lt;/i&gt;" in html and "<i>Eins</i>" not in html and "A &amp; B" in html
    assert "Fertig" in html and "Fehler" in html and "Abgebrochen" in html
    assert 'class="badge bg-green-lt" title="Genre: ok">Ge' in html
    assert 'class="badge bg-red-lt" title="Lyrics: fehlt">Ly' in html
    assert 'class="badge bg-secondary-lt" title="Cover: keine Aussage">Co' in html
    assert html.count("download-retry-btn") == 3 and 'data-url="https://youtu.be/Zwei"' in html


@needs_node
def test_history_filter_and_empty_states(tmp_path):
    entries = [_entry("Eins", "A", "success"), _entry("Zwei", "B", "failed")]
    out = _run(tmp_path, responses={_HISTORY_KEY: {"status": 200, "body": {"entries": entries}}},
               ops=[{"op": "call", "fn": "_setDownloadStatusFilter", "args": ["failed"]},
                    {"op": "snap", "name": "failed", "id": "downloads-content"},
                    {"op": "set", "id": "downloads-search", "key": "value", "value": "nichtda"},
                    {"op": "call", "fn": "_rerenderDownloads"}])
    assert "Zwei" in out["snapshots"]["failed"] and "Eins" not in out["snapshots"]["failed"]
    assert "Keine Treffer" in out["els"]["downloads-content"]["html"]

    empty = _run(tmp_path)["els"]["downloads-content"]["html"]
    assert 'class="empty' in empty and "Noch keine Downloads" in empty


@needs_node
def test_history_preview_limit_and_more_button(tmp_path):
    entries = [_entry(f"T{i}", "A") for i in range(13)]
    html = _run(tmp_path, responses={_HISTORY_KEY: {"status": 200, "body": {"entries": entries}}})["els"]["downloads-content"]["html"]

    assert html.count("<tr><td") == 10
    assert "3 weitere anzeigen" in html


@needs_node
def test_kpis_pipeline_attention_and_last_download(tmp_path):
    entries = [
        _entry("Neu", "X", "success", genre_ok=True, lyrics_ok=True, cover_ok=False),
        _entry("Alt", "Y", "failed", genre_ok=True),
        _entry("Mitte", "Z", "success"),
    ]
    els = _run(tmp_path, responses={_HISTORY_KEY: {"status": 200, "body": {"entries": entries}}})["els"]

    kpi = els["downloads-kpi"]
    assert kpi["hidden"] is False
    assert ">3</div>" in kpi["html"] and ">67 %</div>" in kpi["html"] and ">1</div>" in kpi["html"]
    assert ">75 %</div>" in kpi["html"]           # 3 von 4 bekannten Metadaten-Werten
    pipeline = els["downloads-pipeline-content"]["html"]
    assert "bg-green" in pipeline and "bg-red" in pipeline   # Genre 100 %, Cover 0 %
    attention = els["downloads-attention-content"]["html"]
    assert "1 fehlgeschlagen" in attention and "Alt" in attention
    assert "ohne Cover" in attention and "list-group-item" in attention
    assert 'id="downloads-attention-open-btn"' in attention
    last = els["downloads-last-content"]["html"]
    assert "X – Neu" in last and last.count("<svg") == 6


@needs_node
def test_attention_ok_state(tmp_path):
    entries = [_entry("Gut", "A", "success", genre_ok=True)]
    html = _run(tmp_path, responses={_HISTORY_KEY: {"status": 200, "body": {"entries": entries}}})["els"]["downloads-attention-content"]["html"]

    assert "Keine auffälligen Downloads" in html and "bg-green-lt" in html


@needs_node
def test_rehydrate_404_resets_to_idle_and_clears_storage(tmp_path):
    out = _run(tmp_path, responses={_JOB_KEY: {"status": 404, "body": {"error": {"message": "weg"}}}}, storage=_STORED)

    assert "Kein aktiver Download" in out["els"]["download-status-content"]["html"]
    assert "musicbot_cc_active_download_job_id" not in out["storage"]
    assert out["els"]["download-start-btn"]["disabled"] is False
