# tests/test_control_center_mappings_editor.py
# -*- coding: utf-8 -*-
"""
Mapping-Administration 5.2 — die echte static/pages/mappings_editor.js läuft
zusammen mit mappings.js und common.js in node gegen Fake-DOM und Fake-API
(Muster wie tests/test_control_center_mappings_page.py). Geprüft werden der
Ablauf Öffnen → automatische Vorschau → Bestätigung → PUT mit Etag, Konflikt
(409), Validierungsfehler (422), das Verwerfen veralteter Vorschauen, Escaping
sowie Versionen und Restore. Fachlogik bleibt im Backend; hier zählt, dass die
UI nur anzeigt und nie ohne Antwort des Servers Erfolg meldet.
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
PAGE_JS = CC_DIR / "static" / "pages" / "mappings.js"
EDITOR_JS = CC_DIR / "static" / "pages" / "mappings_editor.js"
TEMPLATE = CC_DIR / "templates" / "mappings.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

_HARNESS = r"""
const fs = require("fs");
const [commonPath, pagePath, editorPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const fields = {};
const mkEl = (id) => {
  const cls = new Set(); const attrs = {}; const listeners = {};
  return {
    id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false, value: "", dataset: {},
    classList: { add: (c) => cls.add(c), remove: (...cs) => cs.forEach((c) => cls.delete(c)), contains: (c) => cls.has(c), toggle: () => {} },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    querySelector: () => null, addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    appendChild: () => {}, remove: () => {}, _listeners: listeners, _cls: cls,
  };
};
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.document = {
  querySelector: (sel) => { const m = /data-field="([^"]+)"/.exec(sel); return m && fields[m[1]] !== undefined ? { value: fields[m[1]], dataset: {} } : null; },
  querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { appendChild: () => {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
const confirms = [];
global.window = { confirm: (t) => { confirms.push(t); const c = sc.confirms; return Array.isArray(c) ? (c.length > 1 ? c.shift() : c[0]) : c !== false; } };
global.console = { ...console, error: () => {} };
const realSetTimeout = setTimeout;
global.setTimeout = (fn, ms) => realSetTimeout(fn, 1);
const calls = [];
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push({ call: method + " " + url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  const key = method + " " + url.split("?")[0];
  let r = sc.responses[key];
  if (Array.isArray(r)) r = r.length > 1 ? r.shift() : r[0];
  if (!r) r = { status: 500, body: { error: { message: "unerwartet: " + key } } };
  if (r.delay) await new Promise((res) => realSetTimeout(res, r.delay));
  return { status: r.status, ok: r.status >= 200 && r.status < 300, text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)), json: async () => r.body };
};
const toasts = [];
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(pagePath, "utf-8") + "\n" + fs.readFileSync(editorPath, "utf-8")
  + "\n;ccToast = (kind, title, text) => { toasts.push([kind, title, text || ''].join('|')); };";
new Function("toasts", src)(toasts);
const tick = () => new Promise((r) => realSetTimeout(r, 12));
(async () => {
  for (let i = 0; i < 4; i++) await tick();
  for (const op of sc.ops || []) {
    if (op.op === "field") fields[op.field] = op.value;
    if (op.op === "respond") Object.assign(sc.responses, op.responses);
    if (op.op === "wait") await new Promise((r) => realSetTimeout(r, op.ms));
    if (op.op === "event") {
      const t = { dataset: op.dataset || {}, value: op.value === undefined ? "" : op.value, key: op.key, closest: () => t, preventDefault: () => {} };
      for (const f of (document.getElementById(op.id)._listeners[op.type] || [])) await f({ target: t, key: op.key, preventDefault: () => {} });
    }
    if (!op.nowait) for (let i = 0; i < 4; i++) await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, text: e.textContent, hidden: e.hidden, disabled: e.disabled, cls: [...e._cls] };
  console.log(JSON.stringify({ els: out, calls, confirms, toasts }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}
_ALIAS_LIST = {"status": 200, "body": {"mapping_id": "genre-aliases", "count": 1, "entries": [{"key": "neo soulish", "canonical": "Soul"}]}}


def _alias_preview(change="update", **kw):
    body = {"mapping_id": "genre-aliases", "key": "neo soulish", "change": change,
            "existing": {"key": "neo soulish", "canonical": "Soul"} if change != "create" else None,
            "canonical": "Neo Soul", "canonical_changed": True, "warnings": [], "etag": "ETAG1",
            "comment_warning": "Kommentarzeilen in genre_aliases.yaml gehen beim Speichern verloren."}
    body.update(kw)
    return {"status": 200, "body": body}


def _base(**over):
    r = {
        "GET /api/v1/auth/whoami": _WHOAMI,
        "GET /api/v1/admin/mappings/channel-genre": {"status": 200, "body": {"mapping_id": "channel-genre", "count": 0, "entries": []}},
        "GET /api/v1/admin/mappings/genre-aliases": _ALIAS_LIST,
        "GET /api/v1/admin/mappings/genre-overrides": {"status": 200, "body": {"mapping_id": "genre-overrides", "count": 0, "entries": []}},
        "GET /api/v1/admin/mappings/genre-filters": {"status": 200, "body": {"mapping_id": "genre-filters", "count": 0, "values": [], "etag": "e", "warnings": []}},
        "GET /api/v1/admin/mappings/special-channels": {"status": 200, "body": {"mapping_id": "special-channels", "count": 0, "categories": [], "etag": "e", "warnings": []}},
        "GET /api/v1/admin/mappings/genre-aliases/entry": {"status": 200, "body": {
            "mapping_id": "genre-aliases", "key": "neo soulish", "exists": True, "etag": "ETAG1",
            "entry": {"key": "neo soulish", "canonical": "Soul"}}},
        "POST /api/v1/admin/mappings/genre-aliases/preview": _alias_preview(),
        "PUT /api/v1/admin/mappings/genre-aliases": {"status": 200, "body": {
            "written": True, "unchanged": False, "new_etag": "ETAG2", "bot_reload_required": True,
            "message": "Mapping gespeichert. Die Änderung wirkt nach Bot-Neustart."}},
    }
    r.update(over)
    return r


def _run(tmp_path, responses=None, ops=None, confirms=True):
    scenario = {"responses": _base(**(responses or {})), "ops": ops or [], "confirms": confirms}
    script = tmp_path / "editor_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run([_NODE, str(script), str(COMMON_JS), str(PAGE_JS), str(EDITOR_JS), json.dumps(scenario)],
                         capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _el(out, element_id):
    return out["els"][element_id]


def _calls(out):
    return [c["call"] for c in out["calls"]]


def _ev(id_, type_, dataset=None, value=None, key=None, nowait=False):
    return {"op": "event", "id": id_, "type": type_, "dataset": dataset or {}, "value": value, "key": key, "nowait": nowait}


def _edit(type_="genre-aliases", key="neo soulish"):
    return _ev("mappings-root", "click", {"action": "edit", "type": type_, "key": key})


def _new(type_="genre-aliases"):
    return _ev("mappings-root", "click", {"action": "new", "type": type_})


def _save():
    return _ev("mappings-editor", "click", {"action": "save"})


def _type_field(field, value):
    return [{"op": "field", "field": field, "value": value}, _ev("mappings-editor", "input", {"field": field}, value)]


# ── Statik ───────────────────────────────────────────────────────────────


def test_editor_js_and_template_follow_standard():
    js = EDITOR_JS.read_text(encoding="utf-8")
    html = TEMPLATE.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "confirm(" not in js.replace("ccConfirm(", "") and "onclick" not in js and 'style="' not in js
    assert 'style="' not in html and not re.search(r"<script(?![^>]*\bsrc=)", html)
    for element_id in ("mappings-editor", "mappings-editor-body", "mappings-editor-save", "mappings-editor-title"):
        assert f'id="{element_id}"' in html
    assert 'src="{{ base_path }}/static/pages/mappings_editor.js"' in html


def test_editor_sends_only_existing_endpoints():
    js = EDITOR_JS.read_text(encoding="utf-8")
    assert "/api/v1/admin/mappings" in js
    assert not re.search(r'ccApi\(\s*"DELETE"', js)  # kein Löschen: es gibt keinen Endpunkt


# ── Öffnen und automatische Vorschau ────────────────────────────────────


@needs_node
def test_edit_opens_panel_loads_entry_and_runs_preview(tmp_path):
    out = _run(tmp_path, ops=[_edit()])

    assert "show" in _el(out, "mappings-editor")["cls"]
    assert "GET /api/v1/admin/mappings/genre-aliases/entry?key=neo%20soulish" in _calls(out)
    assert "POST /api/v1/admin/mappings/genre-aliases/preview?key=neo%20soulish" in _calls(out)
    assert _el(out, "mappings-editor-title")["text"] == "neo soulish"
    body = _el(out, "mappings-editor-body")["html"]
    assert 'value="neo soulish"' in body and "readonly" in body and 'value="Soul"' in body
    preview = _el(out, "mappings-editor-preview")["html"]
    assert "Änderung" in preview and "Soul" in preview and "Neo Soul" in preview
    assert "Kommentarzeilen" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is False


@needs_node
def test_opening_editor_only_reads_and_previews_never_writes(tmp_path):
    out = _run(tmp_path, ops=[_edit()])

    assert not any(c.startswith(("PUT ", "DELETE ")) for c in _calls(out))
    assert not out["toasts"]


@needs_node
def test_unchanged_preview_keeps_save_disabled(tmp_path):
    out = _run(tmp_path, responses={"POST /api/v1/admin/mappings/genre-aliases/preview": _alias_preview("unchanged")}, ops=[_edit()])

    assert "Keine Änderung" in _el(out, "mappings-editor-preview")["html"]
    assert _el(out, "mappings-editor-save")["disabled"] is True


@needs_node
def test_preview_warnings_are_shown_and_do_not_block_saving(tmp_path):
    warn = "Der Key 'Trip Hop' greift zur Laufzeit nicht: die Genre-Pipeline sucht Overrides kleingeschrieben."
    prev = {"status": 200, "body": {"mapping_id": "genre-overrides", "key": "Trip Hop", "change": "create", "existing": None,
                                    "override": "Downtempo", "override_changed": True, "warnings": [warn], "etag": "E9", "comment_warning": None}}
    out = _run(tmp_path, responses={"POST /api/v1/admin/mappings/genre-overrides/preview": prev},
               ops=[_new("genre-overrides"), *_type_field("key", "Trip Hop"), *_type_field("override", "Downtempo")])

    assert warn.replace("'", "&#39;") in _el(out, "mappings-editor-message")["html"]
    assert "Neu" in _el(out, "mappings-editor-preview")["html"]
    assert _el(out, "mappings-editor-save")["disabled"] is False


@needs_node
def test_typing_is_debounced_to_one_preview_with_latest_value(tmp_path):
    fast = lambda field, value: [{"op": "field", "field": field, "value": value, "nowait": True},
                                 _ev("mappings-editor", "input", {"field": field}, nowait=True)]
    out = _run(tmp_path, ops=[_new(), *fast("key", "a"), *fast("canonical", "A"), *fast("canonical", "AB"),
                              {"op": "field", "field": "canonical", "value": "AB"}])
    previews = [c for c in out["calls"] if c["call"].startswith("POST") and "/preview" in c["call"]]

    assert len(previews) == 1 and previews[0]["body"] == {"canonical": "AB"}


@needs_node
def test_outdated_preview_response_is_discarded(tmp_path):
    # Die erste Antwort kommt erst NACH der zweiten an (langsames Netz) und darf sie nicht überschreiben.
    slow_old = {**_alias_preview(canonical="OLD", etag="ETAG_OLD"), "delay": 250}
    fast_new = _alias_preview(canonical="NEU", etag="ETAG_NEU")
    out = _run(tmp_path, responses={"POST /api/v1/admin/mappings/genre-aliases/preview": [slow_old, fast_new]},
               ops=[_new(), {"op": "field", "field": "key", "value": "k"}, _ev("mappings-editor", "input", {"field": "key"}),
                    {"op": "field", "field": "canonical", "value": "NEU"}, _ev("mappings-editor", "input", {"field": "canonical"}),
                    {"op": "wait", "ms": 400}, _save()])
    put = [c for c in out["calls"] if c["call"].startswith("PUT ")]

    assert "NEU" in _el(out, "mappings-editor-preview")["html"] and "OLD" not in _el(out, "mappings-editor-preview")["html"]
    assert put and put[0]["body"]["etag"] == "ETAG_NEU"


@needs_node
def test_new_entry_without_key_shows_hint_and_no_request(tmp_path):
    out = _run(tmp_path, ops=[_new()])

    assert "Schlüssel eingeben" in _el(out, "mappings-editor-preview")["html"]
    assert not any("/preview" in c for c in _calls(out))
    assert _el(out, "mappings-editor-save")["disabled"] is True


@needs_node
def test_preview_422_is_shown_and_save_stays_disabled(tmp_path):
    bad = {"status": 422, "body": {"error": {"code": "MAPPING_INVALID_INPUT", "message": "Alias zu lang (max. 200 Zeichen)."}}}
    out = _run(tmp_path, responses={"POST /api/v1/admin/mappings/genre-aliases/preview": bad}, ops=[_edit()])

    assert "Alias zu lang" in _el(out, "mappings-editor-preview")["html"]
    assert _el(out, "mappings-editor-save")["disabled"] is True


@needs_node
def test_api_texts_are_escaped_in_form_and_preview(tmp_path):
    evil = "<img src=x onerror=alert(1)>"
    entry = {"status": 200, "body": {"mapping_id": "genre-aliases", "key": evil, "exists": True, "etag": "E",
                                     "entry": {"key": evil, "canonical": evil}}}
    prev = _alias_preview(key=evil, canonical=evil, existing={"key": evil, "canonical": evil}, warnings=[evil])
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/entry": entry,
                                    "POST /api/v1/admin/mappings/genre-aliases/preview": prev}, ops=[_edit(key=evil)])

    for element_id in ("mappings-editor-body", "mappings-editor-preview", "mappings-editor-message"):
        assert "<img" not in _el(out, element_id)["html"]
    assert "&lt;img" in _el(out, "mappings-editor-preview")["html"]


# ── Speichern ────────────────────────────────────────────────────────────


@needs_node
def test_save_confirms_then_puts_with_preview_etag_and_reloads_list(tmp_path):
    out = _run(tmp_path, ops=[_edit(), _save()])

    assert len(out["confirms"]) == 1
    put = [c for c in out["calls"] if c["call"].startswith("PUT ")]
    assert len(put) == 1
    assert put[0]["call"] == "PUT /api/v1/admin/mappings/genre-aliases?key=neo%20soulish"
    assert put[0]["body"] == {"canonical": "Soul", "etag": "ETAG1"}
    assert out["toasts"] == ["ok|Mapping gespeichert|Mapping gespeichert. Die Änderung wirkt nach Bot-Neustart."]
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 2  # Liste neu geladen
    assert "show" not in _el(out, "mappings-editor")["cls"]  # Panel geschlossen


@needs_node
def test_declined_confirmation_sends_nothing(tmp_path):
    out = _run(tmp_path, ops=[_edit(), _save()], confirms=False)

    assert not any(c.startswith("PUT ") for c in _calls(out))
    assert not out["toasts"]


@needs_node
def test_no_success_toast_without_server_success(tmp_path):
    fail = {"status": 503, "body": {"error": {"code": "MAPPING_BACKUP_FAILED", "message": "Backup konnte nicht angelegt werden — es wurde nichts geschrieben."}}}
    out = _run(tmp_path, responses={"PUT /api/v1/admin/mappings/genre-aliases": fail}, ops=[_edit(), _save()])

    assert not out["toasts"]
    assert "Backup konnte nicht angelegt werden" in _el(out, "mappings-editor-message")["html"]
    assert "show" in _el(out, "mappings-editor")["cls"]  # Draft bleibt offen


@needs_node
def test_put_422_keeps_draft_and_shows_message(tmp_path):
    bad = {"status": 422, "body": {"error": {"message": "Genre enthaelt Steuerzeichen."}}}
    out = _run(tmp_path, responses={"PUT /api/v1/admin/mappings/genre-aliases": bad}, ops=[_edit(), _save()])

    assert "Genre enthaelt Steuerzeichen." in _el(out, "mappings-editor-message")["html"]
    assert not out["toasts"]


@needs_node
def test_conflict_409_asks_and_reloads_only_when_confirmed(tmp_path):
    conflict = {"status": 409, "body": {"error": {"code": "MAPPING_CHANGED", "message": "Der Mapping-Stand wurde seit der Vorschau geaendert."}}}
    # 1. Bestätigung = Speichern ok, 2. Bestätigung = "Neu laden und verwerfen"
    out = _run(tmp_path, responses={"PUT /api/v1/admin/mappings/genre-aliases": conflict}, ops=[_edit(), _save()], confirms=[True, True])

    assert len(out["confirms"]) == 2 and "Neu laden verwirft" in out["confirms"][1]
    assert not out["toasts"]
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 2
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases/entry?key=neo%20soulish") == 2

    out = _run(tmp_path, responses={"PUT /api/v1/admin/mappings/genre-aliases": conflict}, ops=[_edit(), _save()], confirms=[True, False])
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 1  # nichts neu geladen
    assert not out["toasts"]


# ── Channel-Genre: Sekundärgenres ────────────────────────────────────────


_CHANNEL_ENTRY = {"status": 200, "body": {"mapping_id": "channel-genre", "key": "trap nation", "exists": True, "etag": "E",
                                          "entry": {"key": "trap nation", "primary": "Hip Hop", "secondary": ["Trap"], "description": "Trap channel"}}}
_CHANNEL_PREVIEW = {"status": 200, "body": {"mapping_id": "channel-genre", "channel": "trap nation", "key": "trap nation", "change": "update",
                                            "existing": {"key": "trap nation", "primary": "Hip Hop", "secondary": ["Trap"], "description": "Trap channel"},
                                            "primary": "Hip Hop", "secondary": ["Trap", "Deutschrap"], "description": "Trap channel",
                                            "primary_changed": False, "added": ["Deutschrap"], "removed": [], "warnings": [], "etag": "EC"}}


@needs_node
def test_channel_genre_chips_add_remove_and_payload(tmp_path):
    responses = {"GET /api/v1/admin/mappings/channel-genre/entry": _CHANNEL_ENTRY,
                 "POST /api/v1/admin/mappings/channel-genre/preview": _CHANNEL_PREVIEW,
                 "PUT /api/v1/admin/mappings/channel-genre": {"status": 200, "body": {"written": True, "message": "ok"}}}
    out = _run(tmp_path, responses=responses, ops=[
        _edit("channel-genre", "trap nation"),
        {"op": "field", "field": "primary", "value": "Hip Hop"}, {"op": "field", "field": "description", "value": "Trap channel"},
        _ev("mappings-editor", "keydown", {"field": "sec-input"}, "Deutschrap", "Enter"),
        _save()])
    puts = [c for c in out["calls"] if c["call"].startswith("PUT ")]

    assert puts[0]["body"] == {"primary": "Hip Hop", "secondary": ["Trap", "Deutschrap"], "description": "Trap channel", "etag": "EC"}
    preview = [c for c in out["calls"] if "/preview" in c["call"]][-1]
    assert preview["body"]["secondary"] == ["Trap", "Deutschrap"]

    out = _run(tmp_path, responses=responses, ops=[_edit("channel-genre", "trap nation"),
                                                     _ev("mappings-editor", "click", {"action": "sec-remove", "genre": "Trap"})])
    assert [c for c in out["calls"] if "/preview" in c["call"]][-1]["body"]["secondary"] == []


# ── Versionen ────────────────────────────────────────────────────────────

_VERSIONS = {"status": 200, "body": {"mapping_id": "genre-aliases", "count": 2, "max_versions": 20, "versions": [
    {"version_id": "20260930T101500_000001Z", "created_at": "2026-09-30T10:15:00.000001+00:00", "size": 2048, "sha256": "a" * 64},
    {"version_id": "20260929T081500_000001Z", "created_at": "2026-09-29T08:15:00.000001+00:00", "size": 512, "sha256": "b" * 64}]}}
_RESTORE_PREVIEW = {"status": 200, "body": {"mapping_id": "genre-aliases", "version_id": "20260930T101500_000001Z",
                                            "created_at": "2026-09-30T10:15:00.000001+00:00", "change": "update",
                                            "added": ["alt: Zurueck"], "removed": ["neo soulish: Neo Soul"], "changed": ["rnb: R&B → Rhythm and Blues"],
                                            "etag": "ER", "warnings": ["Die Version wird unveraendert zurueckgeschrieben."]}}
_RESTORE = {"status": 200, "body": {**_RESTORE_PREVIEW["body"], "written": True, "unchanged": False, "new_etag": "ER2",
                                    "bot_reload_required": True, "message": "Version wiederhergestellt. Wirkung nach Neustart."}}


def _versions(type_="genre-aliases"):
    return _ev("mappings-root", "click", {"action": "versions", "type": type_})


@needs_node
def test_versions_list_shows_dates_sizes_and_no_save_button(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/backups": _VERSIONS}, ops=[_versions()])
    body = _el(out, "mappings-editor-body")["html"]

    assert "GET /api/v1/admin/mappings/genre-aliases/backups" in _calls(out)
    assert body.count('data-action="ver-preview"') == 2 and "2,0 KB" in body and "512 B" in body
    assert "letzten 20 Versionen" in body
    assert _el(out, "mappings-editor-save")["hidden"] is True
    assert _el(out, "mappings-editor-title")["text"] == "Versionen"


@needs_node
def test_versions_empty_state(tmp_path):
    empty = {"status": 200, "body": {"mapping_id": "genre-aliases", "count": 0, "max_versions": 20, "versions": []}}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/backups": empty}, ops=[_versions()])

    assert "Noch keine Versionen" in _el(out, "mappings-editor-body")["html"]


@needs_node
def test_version_preview_shows_diff_and_restore_flow(tmp_path):
    vid = "20260930T101500_000001Z"
    responses = {"GET /api/v1/admin/mappings/genre-aliases/backups": _VERSIONS,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/preview": _RESTORE_PREVIEW,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/restore": _RESTORE}
    out = _run(tmp_path, responses=responses, ops=[
        _versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid})])
    preview = _el(out, "mappings-editor-preview")["html"]

    assert "alt: Zurueck" in preview and "neo soulish: Neo Soul" in preview and "R&amp;B → Rhythm and Blues" in preview
    assert "cc-mapping-diff-add" in preview and "cc-mapping-diff-del" in preview and "cc-mapping-diff-mod" in preview
    assert 'data-action="ver-restore"' in preview and "unveraendert zurueckgeschrieben" in preview

    out = _run(tmp_path, responses=responses, ops=[
        _versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid}),
        _ev("mappings-editor", "click", {"action": "ver-restore"})])
    post = [c for c in out["calls"] if c["call"].endswith("/restore")]
    assert len(out["confirms"]) == 1 and len(post) == 1 and post[0]["body"] == {"etag": "ER"}
    assert out["toasts"] == ["ok|Version wiederhergestellt|Version wiederhergestellt. Wirkung nach Neustart."]
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 2          # Bestand neu geladen
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases/backups") == 2  # Liste neu geladen


@needs_node
def test_restore_declined_or_unchanged_sends_nothing(tmp_path):
    vid = "20260930T101500_000001Z"
    responses = {"GET /api/v1/admin/mappings/genre-aliases/backups": _VERSIONS,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/preview": _RESTORE_PREVIEW}
    out = _run(tmp_path, responses=responses, confirms=False, ops=[
        _versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid}), _ev("mappings-editor", "click", {"action": "ver-restore"})])
    assert not any(c.endswith("/restore") for c in _calls(out)) and not out["toasts"]

    same = {"status": 200, "body": {**_RESTORE_PREVIEW["body"], "change": "unchanged", "added": [], "removed": [], "changed": [], "warnings": []}}
    responses[f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/preview"] = same
    out = _run(tmp_path, responses=responses, ops=[_versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid})])
    assert 'data-action="ver-restore"' not in _el(out, "mappings-editor-preview")["html"]
    assert "entspricht dem aktuellen Stand" in _el(out, "mappings-editor-preview")["html"]


@needs_node
def test_restore_conflict_409_offers_reload(tmp_path):
    vid = "20260930T101500_000001Z"
    conflict = {"status": 409, "body": {"error": {"message": "Der Mapping-Stand wurde seit der Vorschau geaendert."}}}
    responses = {"GET /api/v1/admin/mappings/genre-aliases/backups": _VERSIONS,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/preview": _RESTORE_PREVIEW,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/restore": conflict}
    out = _run(tmp_path, responses=responses, confirms=[True, True], ops=[
        _versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid}), _ev("mappings-editor", "click", {"action": "ver-restore"})])

    assert len(out["confirms"]) == 2 and "Neu laden verwirft" in out["confirms"][1]
    assert not out["toasts"]
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases/backups") == 2


@needs_node
def test_versions_403_and_503(tmp_path):
    denied = {"status": 403, "body": {"error": {"message": "nein"}}}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/backups": denied}, ops=[_versions()])
    assert "Keine Berechtigung" in _el(out, "mappings-editor-body")["html"]

    down = {"status": 503, "body": {"error": {"message": "Datei nicht lesbar"}}}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/backups": down}, ops=[_versions()])
    assert "Datei nicht lesbar" in _el(out, "mappings-editor-body")["html"]
