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
    if (op.op === "event") {
      const t = { dataset: op.dataset || {}, value: op.value || "", closest: (sel) => (sel.includes("[data-action=\"search\"]") ? (op.dataset && op.dataset.action === "search" ? t : null) : t) };
      for (const f of (document.getElementById("mappings-root")._listeners[op.type] || [])) await f({ target: t });
    }
    if (op.op === "respond") Object.assign(sc.responses, op.responses);
    await tick(); await tick();
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, hidden: e.hidden };
  console.log(JSON.stringify({ els: out, calls }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}


_CHANNELS = [
    {"key": "16bars", "primary": "Hip Hop", "secondary": ["Deutschrap"], "description": "German rap channel"},
    {"key": "trap nation", "primary": "Hip Hop", "secondary": ["Trap", "Deutschrap"], "description": "Trap channel"},
    {"key": "cercle", "primary": "Electronic", "secondary": [], "description": None},
]
_ALIASES = [{"key": f"alias {n:03d}", "canonical": f"Genre {n:03d}"} for n in range(120)]


def _lists(**overrides):
    r = {
        "GET /api/v1/auth/whoami": _WHOAMI,
        "GET /api/v1/admin/mappings/channel-genre": {"status": 200, "body": {
            "mapping_id": "channel-genre", "count": len(_CHANNELS), "entries": _CHANNELS}},
        "GET /api/v1/admin/mappings/genre-aliases": {"status": 200, "body": {
            "mapping_id": "genre-aliases", "count": len(_ALIASES), "entries": _ALIASES}},
        "GET /api/v1/admin/mappings/genre-overrides": {"status": 200, "body": {
            "mapping_id": "genre-overrides", "count": 3, "entries": [
                {"key": "Hip-Hop", "override": "Hip Hop"}, {"key": "hip-hop", "override": "Hip Hop"},
                {"key": "acid techno", "override": "Techno"}]}},
        "GET /api/v1/admin/mappings/genre-filters": {"status": 200, "body": {
            "mapping_id": "genre-filters", "count": 1234, "values": ["rock"] * 1200 + ["seen live"] * 34,
            "etag": "e", "warnings": ["15 casefold-Duplikate zusammengefuehrt."]}},
        "GET /api/v1/admin/mappings/special-channels": {"status": 200, "body": {
            "mapping_id": "special-channels", "count": 2, "etag": "e", "warnings": [],
            "categories": [{"name": "Podcast", "channels": ["A", "B", "C"]},
                           {"name": "Playlist", "channels": ["D"]}]}},
        "GET /api/v1/admin/mappings/status": _status(),
    }
    r.update(overrides)
    return r


def _status(states=None, running=True, started="2026-09-30T08:00:00+00:00", notes=None):
    states = states or {}
    entries = []
    for mapping_id in _TYPES:
        state = states.get(mapping_id, "applied")
        entries.append({"mapping_id": mapping_id, "filename": mapping_id + ".yaml", "state": state,
                        "message": {"applied": "Die Runtime nutzt den gespeicherten Stand.",
                                    "pending_restart": "Gespeichert, aber noch nicht angewendet: der Bot lädt die Datei beim Start (Neustart nötig).",
                                    "unknown": "Kein lesbarer Bot-Snapshot — der Runtime-Stand ist unbekannt.",
                                    "unavailable": "Die Datei fehlt."}[state],
                        "saved_sha256": "aaaaaaaaaaaa", "loaded_sha256": "bbbbbbbbbbbb", "note": (notes or {}).get(mapping_id)})
    return {"status": 200, "body": {"snapshot_status": "available" if running else "stale", "bot_running": running,
                                    "bot_started_at": started, "age_seconds": 5.0, "statuses": entries}}


def _run(tmp_path, responses=None, ops=None) -> dict:
    scenario = {"responses": _lists(**(responses or {})), "ops": ops or []}
    script = tmp_path / "mappings_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(MAPPINGS_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _el(out, element_id: str) -> str:
    return out["els"][element_id]["html"]


def _tab(mapping_id: str) -> dict:
    return {"op": "event", "type": "click", "dataset": {"action": "tab", "type": mapping_id}}


def _search(text: str) -> dict:
    return {"op": "event", "type": "input", "dataset": {"action": "search"}, "value": text}


def _page(n: int) -> dict:
    return {"op": "event", "type": "click", "dataset": {"action": "page", "page": str(n)}}


def _calls(out):
    return [c["call"] for c in out["calls"]]


# ── Statik ───────────────────────────────────────────────────────────────


def test_mappings_js_follows_standard():
    js = MAPPINGS_JS.read_text(encoding="utf-8")
    assert not _EMOJI.search(js)
    assert "confirm(" not in js.replace("ccConfirm(", "")
    assert "onclick" not in js and 'style="' not in js
    # Nur lesend: kein PUT/POST in dieser Ausbaustufe.
    assert not re.search(r'ccApi\(\s*"(PUT|POST|DELETE|PATCH)"', js)


def test_mapping_classes_are_defined_in_common_css():
    css = COMMON_JS.with_name("common.css").read_text(encoding="utf-8")
    for cls in (".cc-mapping-tile", ".cc-mapping-scroll", ".cc-mapping-prio"):
        assert cls in css


# ── Kacheln ──────────────────────────────────────────────────────────────


@needs_node
def test_five_tiles_show_live_counts_and_first_tab_is_active(tmp_path):
    out = _run(tmp_path)
    tiles = _el(out, "mappings-tiles")

    assert tiles.count('data-action="tab"') == 5
    assert "1.234" in tiles and "120" in tiles
    for label in ("Channel-Genre", "Genre-Aliase", "Genre-Overrides", "Genre-Filter", "Spezialkanäle"):
        assert label in tiles
    assert 'data-type="channel-genre"' in tiles.split("cc-mapping-tile active")[1][:200]
    assert tiles.count("cc-mapping-tile active") == 1
    assert "1 Hinweis" in tiles  # Filter-warnings sichtbar


@needs_node
def test_page_only_reads_no_write_requests(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-aliases"), _search("alias 01"), _page(2)])

    assert all(c.startswith("GET ") for c in _calls(out))
    for mapping_id in _TYPES:
        assert f"GET /api/v1/admin/mappings/{mapping_id}" in _calls(out)


# ── Tabellen ─────────────────────────────────────────────────────────────


@needs_node
def test_channel_genre_table_shows_all_columns_with_chips(tmp_path):
    out = _run(tmp_path)
    body = _el(out, "mappings-pane-body")

    for header in ("Kanal", "Primär", "Sekundär", "Beschreibung"):
        assert header in body
    assert "trap nation" in body and "German rap channel" in body
    assert '<span class="badge bg-secondary-lt me-1">Trap</span>' in body
    assert "3 Kanäle" in _el(out, "mappings-pane-head")


@needs_node
def test_switching_tab_shows_that_type(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-overrides")])
    body = _el(out, "mappings-pane-body")

    assert "Override" in body and "case-sensitiv" in body
    assert "Hip-Hop" in body and "hip-hop" in body  # Case-Varianten getrennt
    assert "Genre-Overrides" in _el(out, "mappings-pane-head")
    assert _el(out, "mappings-tiles").count("cc-mapping-tile active") == 1


@needs_node
def test_paging_50_per_page_and_navigation(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-aliases")])
    body, foot = _el(out, "mappings-pane-body"), _el(out, "mappings-pane-foot")

    assert body.count("<tr><td") == 50 and "alias 049" in body and "alias 050" not in body
    assert "1–50 von 120" in foot and "Seite 1 / 3" in foot

    out = _run(tmp_path, ops=[_tab("genre-aliases"), _page(3)])
    body, foot = _el(out, "mappings-pane-body"), _el(out, "mappings-pane-foot")
    assert body.count("<tr><td") == 20 and "alias 119" in body and "alias 100" in body
    assert "101–120 von 120" in foot


@needs_node
def test_search_filters_client_side_resets_page_and_makes_no_new_request(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-aliases"), _page(2), _search("genre 07")])
    body = _el(out, "mappings-pane-body")

    assert body.count("<tr><td") == 10 and "alias 070" in body and "alias 079" in body
    assert "1–10 von 10" in _el(out, "mappings-pane-foot")
    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 1


@needs_node
def test_search_without_hit_shows_no_results(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-aliases"), _search("gibtesnicht")])

    assert "Keine Treffer" in _el(out, "mappings-pane-body")


@needs_node
def test_search_matches_secondary_genres_of_channels(tmp_path):
    out = _run(tmp_path, ops=[_search("trap")])
    body = _el(out, "mappings-pane-body")

    assert "trap nation" in body and "16bars" not in body


# ── Filter (Chips) und Spezialkanäle (Kategorien) ────────────────────────


@needs_node
def test_filters_show_warnings_and_chips_with_search(tmp_path):
    out = _run(tmp_path, ops=[_tab("genre-filters")])
    body = _el(out, "mappings-pane-body")

    assert "15 casefold-Duplikate zusammengefuehrt." in body and "alert-warning" in body
    assert body.count('class="badge bg-secondary-lt">') == 1234

    out = _run(tmp_path, ops=[_tab("genre-filters"), _search("seen")])
    assert _el(out, "mappings-pane-body").count('class="badge bg-secondary-lt">') == 34
    assert "34 von 1.234 Filtern" in _el(out, "mappings-pane-foot")


@needs_node
def test_special_channels_show_priority_order_and_all_channels(tmp_path):
    out = _run(tmp_path, ops=[_tab("special-channels")])
    body = _el(out, "mappings-pane-body")

    assert body.index("Podcast") < body.index("Playlist")
    assert 'cc-mapping-prio d-inline-flex align-items-center justify-content-center">1<' in body
    assert 'cc-mapping-prio d-inline-flex align-items-center justify-content-center">2<' in body
    for ch in ("A", "B", "C", "D"):
        assert f'<span class="badge bg-secondary-lt">{ch}</span>' in body
    assert "Config.SPECIAL_CHANNELS" in body
    assert "4 Kanäle" in _el(out, "mappings-pane-head")


@needs_node
def test_special_channels_search_hides_non_matching_categories(tmp_path):
    out = _run(tmp_path, ops=[_tab("special-channels"), _search("playl")])
    body = _el(out, "mappings-pane-body")

    assert "Playlist" in body and "Podcast" not in body
    assert '<span class="badge bg-secondary-lt">D</span>' in body  # Kategorie passt -> alle Kanäle sichtbar


# ── Escaping ─────────────────────────────────────────────────────────────


@needs_node
def test_api_texts_are_escaped_everywhere(tmp_path):
    evil = "<img src=x onerror=alert(1)>"
    responses = {
        "GET /api/v1/admin/mappings/channel-genre": {"status": 200, "body": {
            "mapping_id": "channel-genre", "count": 1,
            "entries": [{"key": evil, "primary": evil, "secondary": [evil], "description": evil}]}},
        "GET /api/v1/admin/mappings/genre-filters": {"status": 200, "body": {
            "mapping_id": "genre-filters", "count": 1, "values": [evil], "etag": "e", "warnings": [evil]}},
    }
    out = _run(tmp_path, responses=responses, ops=[_search("img")])
    assert "<img" not in _el(out, "mappings-pane-body")
    out = _run(tmp_path, responses=responses, ops=[_tab("genre-filters")])
    assert "<img" not in _el(out, "mappings-pane-body")
    assert "&lt;img src=x onerror=alert(1)&gt;" in _el(out, "mappings-pane-body")


# ── Zustände ─────────────────────────────────────────────────────────────


@needs_node
def test_empty_mapping_shows_empty_state(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-overrides": {"status": 200, "body": {
        "mapping_id": "genre-overrides", "count": 0, "entries": []}}}
    out = _run(tmp_path, responses=responses, ops=[_tab("genre-overrides")])

    assert "Noch keine Einträge" in _el(out, "mappings-pane-body")


@needs_node
def test_unavailable_mapping_shows_error_only_for_that_tab_and_tile(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-aliases": {"status": 503, "body": {
        "error": {"code": "MAPPING_UNAVAILABLE", "message": "genre_aliases.yaml existiert nicht."}}}}
    out = _run(tmp_path, responses=responses, ops=[_tab("genre-aliases")])

    body = _el(out, "mappings-pane-body")
    assert "Genre-Aliase nicht erreichbar: genre_aliases.yaml existiert nicht." in body
    assert "Erneut versuchen" in body
    tiles = _el(out, "mappings-tiles")
    assert "nicht erreichbar" in tiles and "1.234" in tiles  # andere Kacheln unberührt


@needs_node
def test_reload_button_reloads_all_and_recovers_failed_type(tmp_path):
    responses = {"GET /api/v1/admin/mappings/genre-aliases": [
        {"status": 503, "body": {"error": {"message": "kurz weg"}}},
        {"status": 200, "body": {"mapping_id": "genre-aliases", "count": 1, "entries": [{"key": "a", "canonical": "B"}]}},
    ]}
    out = _run(tmp_path, responses=responses, ops=[_tab("genre-aliases"), {"op": "click", "id": "mappings-reload-btn"}])

    assert _calls(out).count("GET /api/v1/admin/mappings/genre-aliases") == 2
    assert "Erneut versuchen" not in _el(out, "mappings-pane-body")
    assert "<td class=\"text-break\">a</td>" in _el(out, "mappings-pane-body")


@needs_node
def test_forbidden_shows_no_permission_without_retry(tmp_path):
    responses = {f"GET /api/v1/admin/mappings/{m}": {"status": 403, "body": {"error": {"message": "nein"}}}
                 for m in _TYPES}
    out = _run(tmp_path, responses=responses)

    body = _el(out, "mappings-pane-body")
    assert "Keine Berechtigung" in body and "Erneut versuchen" not in body


@needs_node
def test_network_failure_is_retryable(tmp_path):
    responses = {"GET /api/v1/admin/mappings/channel-genre": {"network": True}}
    body = _el(_run(tmp_path, responses=responses), "mappings-pane-body")

    assert "Channel-Genre nicht erreichbar" in body and "Erneut versuchen" in body


@needs_node
def test_not_logged_in_loads_nothing(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/auth/whoami": {"status": 401, "body": {}}})

    assert not any("/admin/mappings/" in c for c in _calls(out))


@needs_node
def test_new_search_returns_to_first_page_even_with_many_hits(tmp_path):
    # 100 Treffer -> zwei Seiten; von Seite 2 aus zu suchen muss auf Seite 1 springen.
    out = _run(tmp_path, ops=[_tab("genre-aliases"), _page(2), _search("alias 0")])

    assert "alias 000" in _el(out, "mappings-pane-body")
    assert "1–50 von 100" in _el(out, "mappings-pane-foot")


# ── Aktionsknöpfe (5.2) ──────────────────────────────────────────────────


@needs_node
def test_action_buttons_only_where_backend_supports_them(tmp_path):
    for mapping_id in ("channel-genre", "genre-aliases", "genre-overrides"):
        head = _el(_run(tmp_path, ops=[_tab(mapping_id)]), "mappings-pane-head")
        assert 'data-action="new"' in head and 'data-action="versions"' in head
    for mapping_id in ("genre-filters", "special-channels"):
        head = _el(_run(tmp_path, ops=[_tab(mapping_id)]), "mappings-pane-head")
        assert 'data-action="versions"' in head and 'data-action="edit-list"' in head and 'data-action="new"' not in head


@needs_node
def test_rows_have_edit_button_but_no_delete(tmp_path):
    body = _el(_run(tmp_path, ops=[_tab("genre-aliases")]), "mappings-pane-body")

    assert body.count('data-action="edit"') == 50
    assert 'data-key="alias 000"' in body and 'aria-label="alias 000 bearbeiten"' in body
    assert "delete" not in body.lower() and "löschen" not in body.lower()  # kein Löschen: es gibt keinen Endpunkt


# ── Runtime-Status: gespeichert vs. angewendet ───────────────────────────


@needs_node
def test_tiles_show_runtime_state_with_icon_and_text(tmp_path):
    states = {"channel-genre": "applied", "genre-aliases": "pending_restart", "genre-overrides": "unknown", "genre-filters": "unavailable"}
    tiles = _el(_run(tmp_path, responses={"GET /api/v1/admin/mappings/status": _status(states)}), "mappings-tiles")

    for label in ("Angewendet", "Neustart nötig", "Runtime unbekannt", "Datei fehlt"):
        assert label in tiles
    assert tiles.count("badge bg-yellow-lt") >= 1 and "bg-green-lt" in tiles


@needs_node
def test_pending_restart_shows_message_and_restart_link_in_pane(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": _status({"channel-genre": "pending_restart"})})
    pane = _el(out, "mappings-pane-status")

    assert out["els"]["mappings-pane-status"]["hidden"] is False
    assert "Neustart nötig" in pane and "noch nicht angewendet" in pane
    assert 'href="/admin"' in pane and "Bot neu starten" in pane
    assert "Bot gestartet" in pane


@needs_node
def test_applied_shows_no_restart_link(tmp_path):
    pane = _el(_run(tmp_path), "mappings-pane-status")

    assert "Angewendet" in pane and "Bot neu starten" not in pane


@needs_node
def test_status_follows_the_selected_tab_and_shows_special_channel_note(tmp_path):
    notes = {"special-channels": "Teile der Prüfung lesen special_channel.yaml je Aufruf neu und wirken ohne Neustart."}
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": _status({"special-channels": "pending_restart", "channel-genre": "applied"}, notes=notes)},
               ops=[_tab("special-channels")])
    pane = _el(out, "mappings-pane-status")

    assert "Neustart nötig" in pane and "je Aufruf neu" in pane

    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": _status({"special-channels": "pending_restart"}, notes=notes)})
    assert "je Aufruf" not in _el(out, "mappings-pane-status")   # erster Tab: Channel-Genre


@needs_node
def test_stopped_bot_is_named_in_the_message_not_hidden(tmp_path):
    status = _status({"channel-genre": "pending_restart"}, running=False)
    status["body"]["statuses"][0]["message"] += " Der Bot läuft nicht oder schreibt keinen Snapshot mehr — Stand vom letzten Lauf."
    pane = _el(_run(tmp_path, responses={"GET /api/v1/admin/mappings/status": status}), "mappings-pane-status")

    assert "läuft nicht" in pane


@needs_node
def test_stopped_bot_never_shows_a_green_applied_badge(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": _status({"genre-aliases": "pending_restart"}, running=False)})
    tiles = _el(out, "mappings-tiles")

    assert "Bot läuft nicht" in tiles
    assert "Angewendet" not in tiles and "bg-green-lt" not in tiles
    assert "Bot läuft nicht" in _el(out, "mappings-pane-status")


@needs_node
def test_unavailable_status_endpoint_does_not_break_the_page(tmp_path):
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": {"status": 503, "body": {"error": {"message": "weg"}}}})

    assert "nicht abrufbar" in _el(out, "mappings-pane-status")
    assert "1.234" in _el(out, "mappings-tiles")           # Bestand ist trotzdem da
    assert "Angewendet" not in _el(out, "mappings-tiles")   # und es wird nichts erfunden


@needs_node
def test_status_texts_are_escaped(tmp_path):
    status = _status({"channel-genre": "pending_restart"})
    status["body"]["statuses"][0]["message"] = "<img src=x onerror=alert(1)>"
    out = _run(tmp_path, responses={"GET /api/v1/admin/mappings/status": status})

    assert "<img" not in _el(out, "mappings-pane-status") and "<img" not in _el(out, "mappings-tiles")
    assert "&lt;img" in _el(out, "mappings-pane-status")


@needs_node
def test_every_type_has_a_yaml_button_with_advanced_hint(tmp_path):
    for mapping_id in _TYPES:
        head = _el(_run(tmp_path, ops=[_tab(mapping_id)]), "mappings-pane-head")
        assert 'data-action="yaml"' in head and f'data-type="{mapping_id}"' in head and "Fortgeschrittene" in head
