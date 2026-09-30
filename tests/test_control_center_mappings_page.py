# tests/test_control_center_mappings_page.py
# -*- coding: utf-8 -*-
"""
Mapping-Administration 5.1 — die echte static/pages/mappings.js läuft zusammen
mit der echten static/common.js in node gegen einen Fake-DOM und eine
Fake-API (Muster wie tests/test_control_center_admin_page.py). Geprüft werden
Darstellung des Live-Bestands, Zustände (Laden/Leer/Fehler/403), Escaping,
Warnungen und dass die Seite ausschließlich lesend auf die bestehenden
Endpunkte zugreift.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CC_DIR = ROOT / "control_center"
COMMON_JS = CC_DIR / "static" / "common.js"
MAPPINGS_JS = CC_DIR / "static" / "pages" / "mappings.js"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
_TYPES = ["channel-genre", "genre-aliases", "genre-overrides", "genre-filters", "special-channels"]

_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const cls = new Set(); const attrs = {}; const listeners = {};
  return {
    id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: "", dataset: {},
    classList: { add: (c) => cls.add(c), remove: (...cs) => cs.forEach((c) => cls.delete(c)),
                 contains: (c) => cls.has(c), toggle: () => {} },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    querySelector: () => null, addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    appendChild: () => {}, remove: () => {},
    _listeners: listeners,
  };
};
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { appendChild: () => {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = {};
global.console = { ...console, error: () => {} };
const calls = [];
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push({ call: method + " " + url, xrw: !!(opts && opts.headers && opts.headers["X-Requested-With"]) });
  const key = method + " " + url.split("?")[0];
  let r = sc.responses[key];
  if (Array.isArray(r)) r = r.length > 1 ? r.shift() : r[0];
  if (!r) r = { status: 500, body: { error: { message: "unerwartet: " + key } } };
  if (r.network) throw new Error("Netzwerk weg");
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
new Function(src)();
const realSetTimeout = setTimeout;
const tick = () => new Promise((r) => realSetTimeout(r, 15));
(async () => {
  await tick(); await tick(); await tick();
  for (const op of sc.ops || []) {
    if (op.op === "click") for (const f of (document.getElementById(op.id)._listeners.click || [])) await f({ target: null });
    if (op.op === "respond") Object.assign(sc.responses, op.responses);
    await tick(); await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, hidden: e.hidden };
  console.log(JSON.stringify({ els: out, calls }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}


def _lists(**overrides):
    r = {
        "GET /api/v1/auth/whoami": _WHOAMI,
        "GET /api/v1/admin/mappings/channel-genre": {"status": 200, "body": {
            "mapping_id": "channel-genre", "count": 2,
            "entries": [{"key": "16bars"}, {"key": "trap nation"}]}},
        "GET /api/v1/admin/mappings/genre-aliases": {"status": 200, "body": {
            "mapping_id": "genre-aliases", "count": 3,
            "entries": [{"key": "a"}, {"key": "b"}, {"key": "c"}]}},
        "GET /api/v1/admin/mappings/genre-overrides": {"status": 200, "body": {
            "mapping_id": "genre-overrides", "count": 1, "entries": [{"key": "acid techno"}]}},
        "GET /api/v1/admin/mappings/genre-filters": {"status": 200, "body": {
            "mapping_id": "genre-filters", "count": 1234, "values": ["rock"] * 1234,
            "etag": "e", "warnings": ["15 casefold-Duplikate zusammengefuehrt."]}},
        "GET /api/v1/admin/mappings/special-channels": {"status": 200, "body": {
            "mapping_id": "special-channels", "count": 2, "etag": "e", "warnings": [],
            "categories": [{"name": "Podcast", "channels": ["A", "B", "C"]},
                           {"name": "Playlist", "channels": ["D"]}]}},
    }
    r.update(overrides)
    return r


def _run(tmp_path, responses=None, ops=None) -> dict:
    scenario = {"responses": _lists(**(responses or {})), "ops": ops or []}
    script = tmp_path / "mappings_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(MAPPINGS_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _body(out, mapping_id: str) -> str:
    return out["els"][f"mappings-card-{mapping_id}-body"]["html"]


def _calls(out):
    return [c["call"] for c in out["calls"]]


# ── Statik ───────────────────────────────────────────────────────────────


def test_mappings_js_follows_standard():
    js = MAPPINGS_JS.read_text(encoding="utf-8")
    assert not _EMOJI.search(js)
    assert "confirm(" not in js.replace("ccConfirm(", "")
    assert "onclick" not in js and 'style="' not in js
    # Nur lesend: kein PUT/POST in 5.1.
    assert not re.search(r'ccApi\(\s*"(PUT|POST|DELETE|PATCH)"', js)


# ── Darstellung ──────────────────────────────────────────────────────────


@needs_node
def test_five_cards_show_live_counts_from_existing_endpoints(tmp_path):
    out = _run(tmp_path)

    assert "2" in _body(out, "channel-genre") and "Kanäle" in _body(out, "channel-genre")
    assert ">3<" in _body(out, "genre-aliases") and "Aliase" in _body(out, "genre-aliases")
    assert ">1<" in _body(out, "genre-overrides") and "Overrides" in _body(out, "genre-overrides")
    assert "1.234" in _body(out, "genre-filters")
    special = _body(out, "special-channels")
    assert ">2<" in special and "Kategorien" in special
    assert "4 Kanäle in 2 Kategorien" in special
    for mapping_id in _TYPES:
        assert f"GET /api/v1/admin/mappings/{mapping_id}" in _calls(out)


@needs_node
def test_page_only_reads_no_write_requests(tmp_path):
    out = _run(tmp_path)

    assert all(c.startswith("GET ") for c in _calls(out))


@needs_node
def test_list_warnings_are_shown_and_escaped(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-filters": {"status": 200, "body": {
        "mapping_id": "genre-filters", "count": 1, "values": ["rock"], "etag": "e",
        "warnings": ["<img src=x onerror=alert(1)> Duplikat"]}}}
    html = _body(_run(tmp_path, responses=responses), "genre-filters")

    assert "&lt;img src=x onerror=alert(1)&gt; Duplikat" in html
    assert "<img" not in html


# ── Zustände ─────────────────────────────────────────────────────────────


@needs_node
def test_empty_mapping_shows_empty_state(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-overrides": {"status": 200, "body": {
        "mapping_id": "genre-overrides", "count": 0, "entries": []}}}
    html = _body(_run(tmp_path, responses=responses), "genre-overrides")

    assert "Noch keine Einträge" in html


@needs_node
def test_unavailable_mapping_shows_error_with_retry_only_for_that_card(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-aliases": {"status": 503, "body": {
        "error": {"code": "MAPPING_UNAVAILABLE", "message": "genre_aliases.yaml existiert nicht."}}}}
    out = _run(tmp_path, responses=responses)

    failed = _body(out, "genre-aliases")
    assert "Genre-Aliase nicht erreichbar: genre_aliases.yaml existiert nicht." in failed
    assert "Erneut versuchen" in failed
    assert "Erneut versuchen" not in _body(out, "channel-genre")
    assert ">2<" in _body(out, "channel-genre")


@needs_node
def test_retry_button_reloads_card(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-aliases": [
        {"status": 503, "body": {"error": {"message": "kurz weg"}}},
        {"status": 200, "body": {"mapping_id": "genre-aliases", "count": 1, "entries": [{"key": "a"}]}},
    ]}
    out = _run(tmp_path, responses=responses, ops=[{"op": "click", "id": "mappings-reload-btn"}])

    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 2
    assert ">1<" in _body(out, "genre-aliases")
    assert "Erneut versuchen" not in _body(out, "genre-aliases")


@needs_node
def test_forbidden_shows_no_permission_without_retry(tmp_path):
    responses = {f"GET /api/v1/admin/mappings/{m}": {"status": 403, "body": {"error": {"message": "nein"}}}
                 for m in _TYPES}
    out = _run(tmp_path, responses=responses)

    for mapping_id in _TYPES:
        html = _body(out, mapping_id)
        assert "Keine Berechtigung" in html and "Erneut versuchen" not in html


@needs_node
def test_network_failure_is_retryable(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-filters": {"network": True}}
    html = _body(_run(tmp_path, responses=responses), "genre-filters")

    assert "Genre-Filter nicht erreichbar" in html and "Erneut versuchen" in html


@needs_node
def test_not_logged_in_shows_login_view_and_loads_nothing(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/auth/whoami": {"status": 401, "body": {}}})

    assert not any("/admin/mappings/" in c for c in _calls(out))
