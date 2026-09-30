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
# Kern zuerst, danach die Modus-Dateien (Ladereihenfolge wie im Template).
EDITOR_FILES = [EDITOR_JS] + [CC_DIR / "static" / "pages" / f"mappings_editor_{name}.js" for name in ("lists", "yaml", "versions")]
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
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(pagePath, "utf-8") + "\n" + editorPath.split(",").map((f) => fs.readFileSync(f, "utf-8")).join("\n")
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
        "GET /api/v1/admin/mappings/status": {"status": 200, "body": {"snapshot_status": "available", "bot_running": True, "statuses": [
            {"mapping_id": "genre-aliases", "filename": "genre_aliases.yaml", "state": "applied", "message": "ok"}]}},
    }
    r.update(over)
    return r


def _run(tmp_path, responses=None, ops=None, confirms=True):
    scenario = {"responses": _base(**(responses or {})), "ops": ops or [], "confirms": confirms}
    script = tmp_path / "editor_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    out = subprocess.run([_NODE, str(script), str(COMMON_JS), str(PAGE_JS), ",".join(map(str, EDITOR_FILES)), json.dumps(scenario)],
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
    js = "\n".join(f.read_text(encoding="utf-8") for f in EDITOR_FILES)
    html = TEMPLATE.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "confirm(" not in js.replace("ccConfirm(", "") and "onclick" not in js and 'style="' not in js
    assert 'style="' not in html and not re.search(r"<script(?![^>]*\bsrc=)", html)
    for element_id in ("mappings-editor", "mappings-editor-body", "mappings-editor-save", "mappings-editor-title"):
        assert f'id="{element_id}"' in html
    for f in EDITOR_FILES:   # alle Dateien eingebunden, Kern zuerst
        assert f'src="{{{{ base_path }}}}/static/pages/{f.name}"' in html
    assert [html.index(f.name) for f in EDITOR_FILES] == sorted(html.index(f.name) for f in EDITOR_FILES)


def test_editor_sends_only_existing_endpoints():
    js = "\n".join(f.read_text(encoding="utf-8") for f in EDITOR_FILES)
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


# ── 5.3: Filter (Chip-Liste) ─────────────────────────────────────────────

_F = "genre-filters"
_S = "special-channels"


def _edit_list(type_):
    return _ev("mappings-root", "click", {"action": "edit-list", "type": type_})


def _filters_list(values):
    return {"status": 200, "body": {"mapping_id": _F, "count": len(values), "values": values, "etag": "EF0", "warnings": []}}


def _filters_preview(change="update", added=(), removed=(), values=(), warnings=(), etag="EF1", comment="Kommentarzeilen in genre_filters.yaml gehen beim Speichern verloren."):
    return {"status": 200, "body": {"mapping_id": _F, "change": change, "added": list(added), "removed": list(removed),
                                    "values": list(values), "warnings": list(warnings), "etag": etag, "comment_warning": comment}}


def _previews(out, path_suffix="/preview"):
    return [c for c in out["calls"] if c["call"].startswith("POST") and c["call"].endswith(path_suffix)]


@needs_node
def test_filter_editor_loads_list_renders_chips_and_previews_without_key(tmp_path):
    responses = {f"GET /api/v1/admin/mappings/{_F}": _filters_list(["rock", "indie", "seen live"]),
                 f"POST /api/v1/admin/mappings/{_F}/preview": _filters_preview("unchanged", comment=None)}
    out = _run(tmp_path, responses=responses, ops=[_edit_list(_F)])
    body = _el(out, "mappings-editor-body")["html"]

    assert "show" in _el(out, "mappings-editor")["cls"]
    assert _calls(out).count(f"GET /api/v1/admin/mappings/{_F}") == 2   # Seite + Editor
    assert body.count('data-action="flt-remove"') == 3 and "Filter suchen (3 Einträge)" in body
    assert _previews(out)[0]["call"] == f"POST /api/v1/admin/mappings/{_F}/preview"   # kein ?key=
    assert _previews(out)[0]["body"] == {"values": ["rock", "indie", "seen live"]}
    assert _el(out, "mappings-editor-save")["disabled"] is True                     # unverändert


@needs_node
def test_filter_add_remove_search_and_duplicates(tmp_path):
    responses = {f"GET /api/v1/admin/mappings/{_F}": _filters_list(["rock", "indie"]),
                 f"POST /api/v1/admin/mappings/{_F}/preview": _filters_preview("update", added=["favorites"], removed=["indie"])}
    add = lambda v: _ev("mappings-editor", "keydown", {"field": "flt-input"}, v, "Enter")
    out = _run(tmp_path, responses=responses, ops=[
        _edit_list(_F), add("favorites"), add("ROCK"), add("   "), _ev("mappings-editor", "click", {"action": "flt-remove", "value": "indie"})])

    assert _previews(out)[-1]["body"] == {"values": ["rock", "favorites"]}   # Duplikat (case-insensitiv) und Leeres übersprungen
    preview = _el(out, "mappings-editor-preview")["html"]
    assert "favorites" in preview and "cc-mapping-diff-add" in preview and "cc-mapping-diff-del" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is False

    out = _run(tmp_path, responses=responses, ops=[_edit_list(_F), _ev("mappings-editor", "input", {"field": "flt-search"}, "ind")])
    chips = _el(out, "mappings-f-chips")["html"]
    assert "indie" in chips and "rock" not in chips
    assert len(_previews(out)) == 1                                           # Suche ist nur Anzeige, keine neue Vorschau


@needs_node
def test_filter_cleanup_is_writable_and_put_has_no_key(tmp_path):
    responses = {f"GET /api/v1/admin/mappings/{_F}": _filters_list(["rock", "indie"]),
                 f"POST /api/v1/admin/mappings/{_F}/preview": _filters_preview("cleanup", warnings=["Die Datei enthaelt unsaubere Eintraege (15 Duplikate)."]),
                 f"PUT /api/v1/admin/mappings/{_F}": {"status": 200, "body": {"written": True, "message": "Mapping gespeichert. Wirkt nach Neustart."}}}
    out = _run(tmp_path, responses=responses, ops=[_edit_list(_F), _save()])
    put = [c for c in out["calls"] if c["call"].startswith("PUT ")]

    assert "Bereinigung" in _el(out, "mappings-editor-preview")["html"]
    assert "unsaubere Eintraege" in _el(out, "mappings-editor-message")["html"]
    assert put[0]["call"] == f"PUT /api/v1/admin/mappings/{_F}" and put[0]["body"] == {"values": ["rock", "indie"], "etag": "EF1"}
    assert out["toasts"] == ["ok|Mapping gespeichert|Mapping gespeichert. Wirkt nach Neustart."]
    assert len(out["confirms"]) == 1 and "ersetzt die Datei" in out["confirms"][0]


# ── 5.3: Spezialkanäle (Kategorien, Priorität) ───────────────────────────


def _cats(*pairs):
    return [{"name": n, "channels": list(c)} for n, c in pairs]


def _special_list(cats):
    return {"status": 200, "body": {"mapping_id": _S, "count": len(cats), "categories": cats, "etag": "ES0", "warnings": []}}


def _special_preview(change="update", added=(), removed=(), order=None, warnings=(), etag="ES1"):
    return {"status": 200, "body": {"mapping_id": _S, "change": change, "categories": [], "added": list(added), "removed": list(removed),
                                    "warnings": list(warnings), "etag": etag, "order_change": order,
                                    "comment_warning": "Kommentarzeilen in special_channel.yaml gehen beim Speichern verloren."}}


_TWO = _cats(("Podcast", ["A", "B"]), ("Playlist", ["C"]))


def _special_responses(cats=_TWO, preview=None):
    return {f"GET /api/v1/admin/mappings/{_S}": _special_list(cats),
            f"POST /api/v1/admin/mappings/{_S}/preview": preview or _special_preview("update", order="Reihenfolge: Podcast, Playlist → Playlist, Podcast"),
            f"PUT /api/v1/admin/mappings/{_S}": {"status": 200, "body": {"written": True, "message": "Gespeichert."}}}


@needs_node
def test_special_editor_shows_priority_cards_and_disables_edge_arrows(tmp_path):
    out = _run(tmp_path, responses=_special_responses(), ops=[_edit_list(_S)])
    body = _el(out, "mappings-editor-body")["html"]

    assert body.index("Podcast") < body.index("Playlist")
    assert 'cc-mapping-prio d-inline-flex align-items-center justify-content-center">1<' in body and '>2<' in body
    assert 'data-action="cat-up" data-index="0"' in body and 'aria-label="Podcast nach oben" disabled' in body
    assert 'aria-label="Playlist nach unten" disabled' in body
    assert "Reihenfolge der Kategorien ist die Priorität" in body and "Config.SPECIAL_CHANNELS" in body
    assert _previews(out)[0]["body"] == {"categories": _TWO}


@needs_node
def test_special_reorder_sends_new_order_and_shows_order_change(tmp_path):
    out = _run(tmp_path, responses=_special_responses(), ops=[_edit_list(_S), _ev("mappings-editor", "click", {"action": "cat-down", "index": "0"})])

    assert [c["name"] for c in _previews(out)[-1]["body"]["categories"]] == ["Playlist", "Podcast"]
    preview = _el(out, "mappings-editor-preview")["html"]
    assert "Reihenfolge: Podcast, Playlist" in preview and "cc-mapping-diff-mod" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is False

    out = _run(tmp_path, responses=_special_responses(), ops=[_edit_list(_S), _ev("mappings-editor", "click", {"action": "cat-up", "index": "1"})])
    assert [c["name"] for c in _previews(out)[-1]["body"]["categories"]] == ["Playlist", "Podcast"]


@needs_node
def test_special_add_remove_channels_and_categories(tmp_path):
    ops = [_edit_list(_S),
           _ev("mappings-editor", "keydown", {"field": "ch-input", "index": "0"}, "Neu", "Enter"),
           _ev("mappings-editor", "keydown", {"field": "ch-input", "index": "0"}, "a", "Enter"),           # Duplikat (case-insensitiv)
           _ev("mappings-editor", "click", {"action": "ch-remove", "index": "1", "channel": "C"}),
           {"op": "field", "field": "cat-name", "value": "Compilations"}, _ev("mappings-editor", "click", {"action": "cat-add"})]
    out = _run(tmp_path, responses=_special_responses(), ops=ops)

    assert _previews(out)[-1]["body"]["categories"] == _cats(("Podcast", ["A", "B", "Neu"]), ("Playlist", []), ("Compilations", []))

    out = _run(tmp_path, responses=_special_responses(), ops=[_edit_list(_S), _ev("mappings-editor", "click", {"action": "cat-remove", "index": "0"})])
    assert _previews(out)[-1]["body"]["categories"] == _cats(("Playlist", ["C"]))


@needs_node
def test_special_save_puts_categories_with_etag_and_confirms(tmp_path):
    out = _run(tmp_path, responses=_special_responses(), ops=[_edit_list(_S), _ev("mappings-editor", "click", {"action": "cat-down", "index": "0"}), _save()])
    put = [c for c in out["calls"] if c["call"].startswith("PUT ")]

    assert put[0]["call"] == f"PUT /api/v1/admin/mappings/{_S}"
    assert put[0]["body"] == {"categories": _cats(("Playlist", ["C"]), ("Podcast", ["A", "B"])), "etag": "ES1"}
    assert out["toasts"] == ["ok|Mapping gespeichert|Gespeichert."]
    assert _calls(out).count(f"GET /api/v1/admin/mappings/{_S}") == 3     # Seite, Editor, Neuladen nach Speichern


@needs_node
def test_special_preview_422_and_conflict_409(tmp_path):
    bad = {"status": 422, "body": {"error": {"message": "Kategorie 'Neu' darf nicht leer sein."}}}
    out = _run(tmp_path, responses=_special_responses(preview=bad), ops=[_edit_list(_S)])
    assert "darf nicht leer sein" in _el(out, "mappings-editor-preview")["html"]
    assert _el(out, "mappings-editor-save")["disabled"] is True

    responses = _special_responses()
    responses[f"PUT /api/v1/admin/mappings/{_S}"] = {"status": 409, "body": {"error": {"message": "Der Mapping-Stand wurde seit der Vorschau geaendert."}}}
    out = _run(tmp_path, responses=responses, confirms=[True, True], ops=[_edit_list(_S), _save()])
    assert len(out["confirms"]) == 2 and not out["toasts"]
    assert _calls(out).count(f"GET /api/v1/admin/mappings/{_S}") == 4      # Seite, Editor, Neuladen, Editor neu geöffnet


@needs_node
def test_special_names_are_escaped(tmp_path):
    evil = "<img src=x onerror=alert(1)>"
    out = _run(tmp_path, responses=_special_responses(_cats((evil, [evil]))), ops=[_edit_list(_S)])

    assert "<img" not in _el(out, "mappings-editor-body")["html"]
    assert "&lt;img" in _el(out, "mappings-editor-body")["html"]


@needs_node
def test_list_editors_never_write_before_confirmation_and_versions_work_for_lists(tmp_path):
    out = _run(tmp_path, responses=_special_responses(), confirms=False, ops=[_edit_list(_S), _ev("mappings-editor", "click", {"action": "cat-down", "index": "0"}), _save()])
    assert not any(c.startswith("PUT ") for c in _calls(out))

    versions = {"status": 200, "body": {"mapping_id": _F, "count": 0, "max_versions": 20, "versions": []}}
    out = _run(tmp_path, responses={f"GET /api/v1/admin/mappings/{_F}/backups": versions}, ops=[_ev("mappings-root", "click", {"action": "versions", "type": _F})])
    assert f"GET /api/v1/admin/mappings/{_F}/backups" in _calls(out)
    assert "Noch keine Versionen" in _el(out, "mappings-editor-body")["html"]


@needs_node
def test_runtime_status_is_reloaded_after_save_and_after_restore(tmp_path):
    out = _run(tmp_path, ops=[_edit(), _save()])
    assert _calls(out).count("GET /api/v1/admin/mappings/status") == 2      # Seite + nach Speichern

    vid = "20260930T101500_000001Z"
    responses = {"GET /api/v1/admin/mappings/genre-aliases/backups": _VERSIONS,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/preview": _RESTORE_PREVIEW,
                 f"POST /api/v1/admin/mappings/genre-aliases/backups/{vid}/restore": _RESTORE}
    out = _run(tmp_path, responses=responses, ops=[_versions(), _ev("mappings-editor", "click", {"action": "ver-preview", "version": vid}),
                                                    _ev("mappings-editor", "click", {"action": "ver-restore"})])
    assert _calls(out).count("GET /api/v1/admin/mappings/status") == 2      # Seite + nach Restore


# ── B4: YAML-Editor (Rohtext) ────────────────────────────────────────────

_YAML_TEXT = "# Aliase\nGENRE_ALIASES:\n  rnb: R&B  # klassisch\n"
_YAML_GET = {"status": 200, "body": {"mapping_id": "genre-aliases", "filename": "genre_aliases.yaml", "text": _YAML_TEXT,
                                     "etag": "EY0", "size": len(_YAML_TEXT), "max_bytes": 524288}}


def _yaml_preview(change="update", added=(), removed=(), changed=(), diff=(), warnings=(), etag="EY1"):
    return {"status": 200, "body": {"mapping_id": "genre-aliases", "change": change, "added": list(added), "removed": list(removed),
                                    "changed": list(changed), "warnings": list(warnings), "text_diff": list(diff), "etag": etag}}


def _yaml_responses(preview=None):
    return {"GET /api/v1/admin/mappings/genre-aliases/yaml": _YAML_GET,
            "POST /api/v1/admin/mappings/genre-aliases/yaml/preview": preview or _yaml_preview(
                added=["neo: Neo Soul"], diff=["--- aktuell", "+++ neu", "@@ -1,3 +1,4 @@", " GENRE_ALIASES:", "+  neo: Neo Soul"]),
            "PUT /api/v1/admin/mappings/genre-aliases/yaml": {"status": 200, "body": {"written": True, "message": "YAML gespeichert. Wirkt nach Neustart."}}}


def _open_yaml(type_="genre-aliases"):
    return _ev("mappings-root", "click", {"action": "yaml", "type": type_})


def _yaml_typing(text):
    return [{"op": "field", "field": "yaml-text", "value": text}, _ev("mappings-editor", "input", {"field": "yaml-text"}, text)]


@needs_node
def test_yaml_editor_loads_raw_text_verbatim_into_textarea_and_warns_about_raw_mode(tmp_path):
    out = _run(tmp_path, responses=_yaml_responses(_yaml_preview("unchanged")), ops=[_open_yaml()])
    body = _el(out, "mappings-editor-body")["html"]

    assert "GET /api/v1/admin/mappings/genre-aliases/yaml" in _calls(out)
    assert "<textarea" in body and 'data-field="yaml-text"' in body and 'spellcheck="false"' in body and 'wrap="off"' in body
    assert "# Aliase\nGENRE_ALIASES:\n  rnb: R&amp;B  # klassisch\n" in body      # unverändert, nur HTML-escaped
    assert "Fortgeschritten" in body and "Kommentare bleiben erhalten" in body and "512 KB" in body
    assert "Keine Änderung" in _el(out, "mappings-editor-preview")["html"]
    assert _el(out, "mappings-editor-save")["disabled"] is True
    assert _el(out, "mappings-editor-title")["text"] == "YAML"


@needs_node
def test_yaml_typing_previews_with_semantic_and_colored_text_diff(tmp_path):
    new = _YAML_TEXT + "  neo: Neo Soul\n"
    out = _run(tmp_path, responses=_yaml_responses(), ops=[_open_yaml(), *_yaml_typing(new)])
    preview = _el(out, "mappings-editor-preview")["html"]
    sent = [c for c in out["calls"] if c["call"].endswith("/yaml/preview")]

    assert sent[-1]["body"] == {"text": new}
    assert "Änderung" in preview and "neo: Neo Soul" in preview and "cc-mapping-diff-add" in preview
    assert "cc-terminal" in preview and "cc-t-ok" in preview and "cc-t-time" in preview     # +/@@ eingefärbt
    assert _el(out, "mappings-editor-save")["disabled"] is False


@needs_node
def test_yaml_format_only_change_is_savable_with_explanation(tmp_path):
    fmt = _yaml_preview("format", diff=["--- aktuell", "+++ neu", "-# Aliase", "+# Neuer Kommentar"])
    out = _run(tmp_path, responses=_yaml_responses(fmt), ops=[_open_yaml(), *_yaml_typing("# Neuer Kommentar\n")])
    preview = _el(out, "mappings-editor-preview")["html"]

    assert "Formatierung" in preview and "Kommentare" in preview and "cc-t-err" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is False


@needs_node
def test_yaml_422_lists_every_error_line_and_blocks_saving(tmp_path):
    bad = {"status": 422, "body": {"error": {"code": "MAPPING_INVALID_INPUT",
                                             "message": "x: Alias zu lang (max. 200 Zeichen).\nok: Zielgenre darf nicht leer sein.\nDer Text enthält <b>Tags</b>."}}}
    out = _run(tmp_path, responses=_yaml_responses(bad), ops=[_open_yaml(), *_yaml_typing("kaputt")])
    preview = _el(out, "mappings-editor-preview")["html"]

    assert preview.count("<li") >= 3 and "Alias zu lang" in preview and "darf nicht leer sein" in preview
    assert "&lt;b&gt;Tags&lt;/b&gt;" in preview and "<b>" not in preview
    assert _el(out, "mappings-editor-save")["disabled"] is True


@needs_node
def test_yaml_save_confirms_then_puts_text_verbatim_with_preview_etag(tmp_path):
    new = _YAML_TEXT + "  neo: Neo Soul\n"
    out = _run(tmp_path, responses=_yaml_responses(), ops=[_open_yaml(), *_yaml_typing(new), _save()])
    put = [c for c in out["calls"] if c["call"].startswith("PUT ")]

    assert len(out["confirms"]) == 1 and "unverändert" in out["confirms"][0] and "Version" in out["confirms"][0]
    assert put[0]["call"] == "PUT /api/v1/admin/mappings/genre-aliases/yaml"
    assert put[0]["body"] == {"text": new, "etag": "EY1"}                       # Text unverändert, Etag aus der Vorschau
    assert out["toasts"] == ["ok|YAML gespeichert|YAML gespeichert. Wirkt nach Neustart."]
    assert _calls(out).count("GET /api/v1/admin/mappings/status") == 2         # Status neu geladen
    assert "show" not in _el(out, "mappings-editor")["cls"]


@needs_node
def test_yaml_never_writes_without_confirmation_or_success(tmp_path):
    out = _run(tmp_path, responses=_yaml_responses(), confirms=False, ops=[_open_yaml(), *_yaml_typing(_YAML_TEXT + "x: y\n"), _save()])
    assert not any(c.startswith("PUT ") for c in _calls(out)) and not out["toasts"]

    responses = _yaml_responses()
    responses["PUT /api/v1/admin/mappings/genre-aliases/yaml"] = {"status": 503, "body": {"error": {"message": "Backup konnte nicht angelegt werden — es wurde nichts geschrieben."}}}
    out = _run(tmp_path, responses=responses, ops=[_open_yaml(), *_yaml_typing(_YAML_TEXT + "x: y\n"), _save()])
    assert not out["toasts"] and "Backup konnte nicht angelegt werden" in _el(out, "mappings-editor-message")["html"]
    assert "show" in _el(out, "mappings-editor")["cls"]


@needs_node
def test_yaml_conflict_409_reopens_with_fresh_text_only_when_confirmed(tmp_path):
    responses = _yaml_responses()
    responses["PUT /api/v1/admin/mappings/genre-aliases/yaml"] = {"status": 409, "body": {"error": {"message": "Die Mapping-Datei wurde seit dem Laden geändert."}}}
    out = _run(tmp_path, responses=responses, confirms=[True, True], ops=[_open_yaml(), *_yaml_typing(_YAML_TEXT + "x: y\n"), _save()])

    assert len(out["confirms"]) == 2 and "Neu laden verwirft" in out["confirms"][1] and not out["toasts"]
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases/yaml") == 2

    out = _run(tmp_path, responses=responses, confirms=[True, False], ops=[_open_yaml(), *_yaml_typing(_YAML_TEXT + "x: y\n"), _save()])
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases/yaml") == 1


@needs_node
def test_yaml_texts_are_escaped_in_textarea_and_diff(tmp_path):
    evil = "</textarea><img src=x onerror=alert(1)>"
    get = {"status": 200, "body": {**_YAML_GET["body"], "text": evil}}
    prev = _yaml_preview(added=[evil], diff=["+" + evil], warnings=[evil])
    responses = {**_yaml_responses(prev), "GET /api/v1/admin/mappings/genre-aliases/yaml": get}
    out = _run(tmp_path, responses=responses, ops=[_open_yaml(), *_yaml_typing(evil)])

    for element_id in ("mappings-editor-body", "mappings-editor-preview", "mappings-editor-message"):
        assert "<img" not in _el(out, element_id)["html"] and "</textarea><img" not in _el(out, element_id)["html"]


@needs_node
def test_yaml_403_and_503_on_open(tmp_path):
    denied = {"status": 403, "body": {"error": {"message": "nein"}}}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/yaml": denied}, ops=[_open_yaml()])
    assert "Keine Berechtigung" in _el(out, "mappings-editor-body")["html"]

    down = {"status": 503, "body": {"error": {"message": "genre_aliases.yaml konnte nicht gelesen werden."}}}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/genre-aliases/yaml": down}, ops=[_open_yaml()])
    assert "konnte nicht gelesen werden" in _el(out, "mappings-editor-body")["html"]


def test_no_editor_file_exceeds_the_size_guideline():
    # Richtwert der Projektstandards: vor ~700 Zeilen aufteilen.
    for f in EDITOR_FILES:
        assert len(f.read_text(encoding="utf-8").splitlines()) < 700, f.name


def test_all_mapping_scripts_build_urls_only_through_apiurl_for_subpath_operation():
    # UI-Standard §1 Regel 6 / §14: jede URL über apiUrl()/ccApi (Betrieb hinter /controlcenter).
    for f in EDITOR_FILES + [PAGE_JS]:
        js = f.read_text(encoding="utf-8")
        assert "fetch(" not in js, f.name
        assert 'href="/' not in js and "window.location" not in js, f.name
        for literal in re.findall(r'"(/[a-z][^"]*)"', js):
            assert literal.startswith("/api/v1/admin/mappings") or literal == "/admin", (f.name, literal)
    assert 'apiUrl("/admin")' in PAGE_JS.read_text(encoding="utf-8")
