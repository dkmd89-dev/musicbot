# tests/test_control_center_artist_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Library L3a — Artist-Detail-Seitengerüst nach
docs/CONTROL_CENTER_UI_STANDARD.md (Nutzerentscheidung 2026-09-28):

- Kopf mit Breadcrumb, Kennzahl-Karten statt .tiles
- Alben/Tracks als Tabler-list-group statt row-list/select-row/row-count
  (U17: lange Namen werden gekürzt statt überzulaufen)
- Track-Detail als Tabler-Offcanvas statt eigenem Drawer (Standard §6),
  Fokus kehrt nach dem Schließen zur Track-Zeile zurück, nach einer
  Drawer-Aktion nicht
- Laden über ccApi, Zustände über ccState

Der Bereich "Metadaten bearbeiten" und die Library-Wartung folgen in L3b
(Dialoge) bzw. L4 (Editor-Ablauf) und werden hier bewusst nicht geprüft.

Die echte static/pages/library_artist.js läuft zusammen mit der echten
static/common.js in node.
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
ARTIST_JS = CC_DIR / "static" / "pages" / "library_artist.js"
ARTIST_HTML = CC_DIR / "templates" / "library_artist_detail.html"
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


def _l3a_js() -> str:
    """Die in L3a umgestellten JS-Bereiche (Master-Detail + Drawer)."""
    js = ARTIST_JS.read_text(encoding="utf-8")
    master = js[js.index("function _renderAlbumListHtml"):js.index("function _artistAlbumOptions")]
    drawer = js[js.index("let _trackDrawerIsAdmin = false;"):js.index("function initPage()")]
    loader = js[js.index("async function loadArtistDetail"):js.index("function _diffSummary")]
    return master + drawer + loader


def test_l3a_areas_have_no_emoji_or_legacy_list_classes():
    js = _l3a_js()
    assert not _EMOJI.search(js), _EMOJI.search(js)
    for legacy in ("row-list", "row-item", "row-count", "select-row", "tile-value", "empty-note", "hint"):
        assert legacy not in js, legacy
    head = ARTIST_HTML.read_text(encoding="utf-8").split("<!-- CC-UI L4: Metadaten-Editor")[0]
    assert not _EMOJI.search(head)
    assert "empty-note" not in head and "drawer-overlay" not in head


@pytest.mark.asyncio
async def test_header_breadcrumb_and_offcanvas_markup(client):
    html = (await client.get("/library/Bausa")).text
    assert '<ol class="breadcrumb mb-1"' in html and 'id="breadcrumb-artist"' in html
    assert '<use href="#i-microphone"/></svg><span id="artist-title">' in html
    assert '<use href="#i-arrow-left"/></svg>Zurück zu Artists' in html
    oc = html[html.index('id="track-drawer"'):]
    oc = oc[:oc.index("<!-- CC-UI L4: Metadaten-Editor")]
    for dom_id in ("track-drawer-title", "track-drawer-subtitle", "track-drawer-close",
                   "track-drawer-info", "track-drawer-health", "track-drawer-actions"):
        assert f'id="{dom_id}"' in oc, dom_id
    assert 'role="dialog" aria-modal="true" aria-labelledby="track-drawer-title"' in html


_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const log = [];
const mkEl = (id) => {
  const el = { id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: "", dataset: {}, options: [], listeners: {}, open: false,
    classList: { add(c) { log.push(`${id}+${c}`); }, remove(c) { log.push(`${id}-${c}`); }, contains: () => false, toggle() {} },
    setAttribute() {}, getAttribute() { return null; },
    querySelector: () => mkEl("_sub"), querySelectorAll: () => [],
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    appendChild() {}, remove() {}, scrollIntoView() {}, focus() { log.push(`focus:${id}`); } };
  return el;
};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, contains: () => true, classList: { toggle() {}, remove() {}, contains: () => false } },
  activeElement: null,
};
const fire = (id, type) => (document.getElementById(id).listeners[type] || []).forEach((f) => f({}));
global.window = {
  location: { pathname: sc.path || "/library/Bausa" },
  tabler: sc.noTabler ? undefined : { Offcanvas: { getOrCreateInstance: (el) => ({
    show() { log.push("offcanvas:show"); },
    hide() { log.push("offcanvas:hide"); fire(el.id, "hidden.bs.offcanvas"); },
  }) } },
  confirm: () => true,
};
global.console = { ...console, error() {} };
const routes = sc.routes || {};
global.fetch = async (url) => {
  const key = url.split("?")[0];
  const r = key.endsWith("/auth/whoami") ? { status: 200, body: { user_id: 1, access_level: sc.access || "OWNER" } }
    : (routes[key] || { status: 404, body: { error: { message: "nicht gefunden" } } });
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => JSON.stringify(r.body), json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
const api = new Function(src + "\nreturn { renderArtistDetail, openTrackDrawer, closeTrackDrawer };")();
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  for (const op of sc.ops || []) {
    if (op.op === "open") {
      document.activeElement = document.getElementById("trigger-row");
      api.openTrackDrawer(op.track);
    } else if (op.op === "close") fire("track-drawer-close", "click");
    else if (op.op === "action") {
      (document.getElementById("track-drawer-actions").listeners.click || []).forEach((f) =>
        f({ target: { closest: () => ({ dataset: { trackAction: op.action } }) } }));
    }
    await tick();
  }
  const out = { log, els: {} };
  Object.keys(els).forEach((id) => { out.els[id] = { html: els[id].innerHTML, text: String(els[id].textContent) }; });
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})();
"""


def _run(tmp_path: Path, scenario: dict) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run([_NODE, str(harness), str(COMMON_JS), str(ARTIST_JS), json.dumps(scenario)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_LONG = "2021 - Ein wirklich sehr sehr langer Albumname der auf dem Handy nie in eine Zeile passt"


def _track(path, **kw):
    t = {"relative_path": path, "filename": path.rsplit("/", 1)[-1], "extension": ".m4a",
         "album_directory": None, "title": None, "artist": "Bausa", "album": None, "album_artist": None,
         "genre": None, "year": None, "track_number": None, "disc_number": None, "mb_recording_id": None,
         "mb_release_id": None, "isrc": None, "issue_codes": []}
    t.update(kw)
    return t


def _body():
    return {
        "artist": "Bausa", "file_count": 3, "album_count": 1, "health_score": 81, "stale": False,
        "generated_at": "2026-09-27T05:47:00",
        "albums": [{"artist": "Bausa", "album": _LONG, "file_count": 2, "health_score": 75, "issue_codes": []}],
        "tracks": [
            _track(f"Bausa/{_LONG}/01.m4a", album_directory=_LONG, title="<b>Powers</b>", track_number=1,
                   issue_codes=["GENRE_EMPTY", "ARTWORK_MISSING"]),
            _track(f"Bausa/{_LONG}/02.m4a", album_directory=_LONG, title="Was Du Liebe nennst", track_number=2),
            _track("Bausa/Singles/Auf gute Freunde.m4a", title="Auf gute Freunde"),
        ],
    }


_OVERVIEW = "/api/v1/library/artists-overview/Bausa"


@needs_node
def test_render_kpis_album_list_and_tracks(tmp_path):
    out = _run(tmp_path, {"routes": {_OVERVIEW: {"status": 200, "body": _body()}}})
    html = out["els"]["artist-content"]["html"]
    assert out["els"]["artist-title"]["text"] == "Bausa"
    assert out["els"]["breadcrumb-artist"]["text"] == "Bausa"
    # Kennzahlen: Health 81 -> gelb (Schwellen 90/70 wie Library-Liste)
    assert '<span class="text-yellow">81</span>' in html
    assert '<div class="h2 mb-0" data-kpi="findings">2</div>' in html
    # U17: Albumname gekürzt, Zahl als Badge daneben
    assert '<span class="flex-fill text-truncate">' + _LONG + "</span>" in html
    assert 'class="badge bg-secondary-lt flex-shrink-0"' in html
    # Tracks: Themen-Badge mit Klartext im Tooltip, Stift, Escaping
    assert 'title="Genre-Tag leer, Cover fehlt">' in html
    assert "&lt;b&gt;Powers&lt;/b&gt;" in html and "<b>Powers</b>" not in html
    assert html.count('<use href="#i-edit"/>') >= 3  # 2 Tracks + Metadaten-Sprung
    # CC-UI L4: ein Link "Metadaten bearbeiten" (Admin) statt Metadaten/Wartung
    assert 'class="segment-nav' in html and 'id="artist-detail-open-metadata"' in html
    assert 'id="artist-detail-open-wartung"' not in html


@needs_node
def test_unknown_artist_shows_empty_state_with_back_link(tmp_path):
    out = _run(tmp_path, {"routes": {_OVERVIEW: {"status": 404, "body": {
        "error": {"message": "Artist nicht im Report."}}}}})
    html = out["els"]["artist-content"]["html"]
    assert "Artist nicht gefunden" in html and "Artist nicht im Report." in html
    assert 'href="/library"' in html and "Zurück zu Artists" in html


@needs_node
def test_server_error_shows_error_with_retry(tmp_path):
    out = _run(tmp_path, {"routes": {_OVERVIEW: {"status": 500, "body": {"error": {"message": "kaputt"}}}}})
    html = out["els"]["artist-content"]["html"]
    assert "text-danger" in html and "kaputt" in html and "Erneut versuchen" in html


@needs_node
def test_drawer_opens_as_offcanvas_with_datagrid_badges_and_actions(tmp_path):
    t = _body()["tracks"][0]
    out = _run(tmp_path, {"routes": {_OVERVIEW: {"status": 200, "body": _body()}}, "ops": [{"op": "open", "track": t}]})
    assert "offcanvas:show" in out["log"]
    assert out["els"]["track-drawer-title"]["text"] == "<b>Powers</b>"  # textContent, kein HTML
    info = out["els"]["track-drawer-info"]["html"]
    assert 'class="datagrid"' in info and "MB Recording-ID" in info
    health = out["els"]["track-drawer-health"]["html"]
    assert "bg-yellow-lt" in health and "Genre-Tag leer" in health and "Cover fehlt" in health
    actions = out["els"]["track-drawer-actions"]["html"]
    for action, icon in (("title", "edit"), ("artist", "microphone"), ("album", "disc"),
                         ("albumartist", "users"), ("genre", "tag"), ("duplicates", "copy")):  # L4: statt Wartung
        assert f'data-track-action="{action}">' in actions and f'href="#i-{icon}"' in actions


@needs_node
def test_drawer_close_returns_focus_to_track_row(tmp_path):
    out = _run(tmp_path, {"ops": [{"op": "open", "track": _body()["tracks"][1]}, {"op": "close"}]})
    log = out["log"]
    assert log.index("offcanvas:hide") < log.index("focus:trigger-row")


@needs_node
def test_drawer_action_does_not_steal_focus_back_to_track_row(tmp_path):
    """Nach einer Drawer-Aktion (Sprung ins Formular) darf der animierte
    Offcanvas-Abschluss den Fokus nicht zurück zur Track-Zeile ziehen."""
    out = _run(tmp_path, {"routes": {_OVERVIEW: {"status": 200, "body": _body()}},
                          "ops": [{"op": "open", "track": _body()["tracks"][1]}, {"op": "action", "action": "duplicates"}]})
    assert "offcanvas:hide" in out["log"]
    assert "focus:trigger-row" not in out["log"]


@needs_node
def test_drawer_without_tabler_falls_back_to_show_class(tmp_path):
    out = _run(tmp_path, {"noTabler": True, "ops": [{"op": "open", "track": _body()["tracks"][1]}, {"op": "close"}]})
    assert "track-drawer+show" in out["log"] and "track-drawer-show" in out["log"]
    assert "focus:trigger-row" in out["log"]


@needs_node
def test_drawer_actions_hidden_for_non_admin(tmp_path):
    out = _run(tmp_path, {"access": "USER", "ops": [{"op": "open", "track": _body()["tracks"][1]}]})
    actions = out["els"]["track-drawer-actions"]["html"]
    assert "Aktionen benötigen Admin-Berechtigung" in actions and "data-track-action" not in actions


# ═════════════════════════════════════════════════════════════════════════
# CC-UI Library L3b — Dialoge, Pflichtfeld-Hinweise, Wartung nach Standard
# (Nutzerentscheidung 2026-09-28: Hinweis am Feld statt alert(), Modal statt
# confirm(); Ablauf von "Metadaten bearbeiten" bleibt bis L4 unverändert).
# ═════════════════════════════════════════════════════════════════════════


def test_whole_artist_page_has_no_emoji_browser_dialogs_or_legacy_markup():
    js = ARTIST_JS.read_text(encoding="utf-8")
    html = ARTIST_HTML.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "window.alert" not in js and "window.prompt" not in js
    # einziger confirm()-Aufruf: der Rückfall ohne Tabler-Modal
    assert js.count("window.confirm(") == 1 and "window.confirm(message)" in js
    for legacy in ('class="empty-note', 'class="hint', "dot dot-", 'class="row-item', 'class="row-list', 'class="row-count'):
        assert legacy not in js and legacy not in html, legacy
    assert 'style="cursor' not in html
    # CC-UI L4: keine aufklappbaren Karten mehr, alles im Editor-Seitenpanel
    assert 'class="card-header cc-summary"' not in html and 'id="md-editor"' in html


_HARNESS_L3B = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const log = [];
const mkEl = (id) => {
  const el = { id, hidden: false, textContent: "", innerHTML: "", className: "", style: {}, disabled: false,
    value: (sc.values || {})[id] || "", dataset: {}, options: [], listeners: {}, open: false,
    classList: { add(c) { log.push(`${id}+${c}`); }, remove(c) { log.push(`${id}-${c}`); }, contains: () => false, toggle() {} },
    setAttribute() {}, getAttribute() { return null; },
    querySelector: () => mkEl("_sub"), querySelectorAll: () => [],
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    insertAdjacentElement() {}, appendChild() {}, remove() {}, scrollIntoView() {}, focus() { log.push(`focus:${id}`); } };
  return el;
};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {}, removeEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, contains: () => true, classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = { location: { pathname: "/library/Bausa" }, tabler: sc.tabler ? { Modal: {} } : undefined,
  confirm: (t) => { log.push("window.confirm:" + t); return sc.confirmAnswer; } };
global.console = { ...console, error() {} };
const calls = [];
const routes = sc.routes || {};
global.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  calls.push(method + " " + url);
  const key = method + " " + url.split("?")[0];
  const byUrl = (sc.routesContains || []).find((rc) => url.includes(rc.match));
  const r = url.includes("/auth/whoami") ? { status: 200, body: { user_id: 1, access_level: sc.access || "OWNER" } }
    : (byUrl || routes[key] || { status: 404, body: { error: { message: "nicht gefunden" } } });
  if (r.delay) await new Promise((res) => setTimeout(res, r.delay));
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => JSON.stringify(r.body), json: async () => r.body };
};
global.setInterval = () => 1; global.clearInterval = () => {};
global.log = log; global.sc = sc;
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8")
  + "\n;ccConfirm = (o) => { log.push('ccConfirm:' + JSON.stringify(o)); return Promise.resolve(sc.confirmAnswer); };"
  + "\n;ccToast = (k, t, x) => { log.push('toast:' + [k, t, x].join('|')); };";
const api = new Function(src + "\nreturn { loadArtistEditPreview, executeArtistEdit, loadTitleEditPreview, "
  + "renderMetadataEditPreview, renderArtistDetail, openMetadataEditor, _selectAlbumForEdit, executeAlbumTab, "
  + "_selectTitleTrack, _albumState, "
  + "loadTrackNumberEditPreview, executeTrackNumberEdit, executeTitleTab, _titleState };")();
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  calls.length = 0;
  for (const op of sc.ops || []) {
    if (op.input) {
      const el = document.getElementById(op.input);
      el.value = op.value;
      for (const f of el.listeners.input || []) f({ target: el });
    } else if (op.wait) {
      await new Promise((res) => setTimeout(res, op.wait));
    } else {
      const args = (op.args || []).map((a) => (typeof a === "string" && a[0] === "@" ? document.getElementById(a.slice(1)) : a));
      await api[op.fn](...args);
    }
    await tick();
  }
  const out = { log, calls, els: {}, albumState: api._albumState };
  Object.keys(els).forEach((id) => { out.els[id] = { html: els[id].innerHTML, text: String(els[id].textContent), disabled: els[id].disabled, value: els[id].value, hidden: els[id].hidden }; });
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})();
"""


def _run_l3b(tmp_path: Path, scenario: dict) -> dict:
    harness = tmp_path / "harness_l3b.js"
    harness.write_text(_HARNESS_L3B, encoding="utf-8")
    proc = subprocess.run([_NODE, str(harness), str(COMMON_JS), str(ARTIST_JS), json.dumps(scenario)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_EXEC = "POST /api/v1/admin/maintenance/artist-rename/execute"


@needs_node
def test_empty_required_field_gets_hint_at_field_not_alert(tmp_path):
    out = _run_l3b(tmp_path, {"ops": [{"fn": "loadArtistEditPreview"}]})
    assert "artist-edit-new-artist+is-invalid" in out["log"]
    assert out["els"]["artist-edit-new-artist-feedback"]["text"] == "Bitte neuen Artist-Namen eingeben."
    assert "focus:artist-edit-new-artist" in out["log"]
    assert not out["calls"]  # kein Preview-Request


@needs_node
def test_title_hint_marks_the_actually_missing_field(tmp_path):
    out = _run_l3b(tmp_path, {"values": {"title-edit-track-select": "Bausa/x.m4a"}, "ops": [{"fn": "loadTitleEditPreview"}]})
    assert "title-edit-new-title+is-invalid" in out["log"]
    assert "title-edit-track-select+is-invalid" not in out["log"]
    assert out["els"]["title-edit-new-title-feedback"]["text"] == "Bitte neuen Titel eingeben."


@needs_node
def test_execute_asks_via_modal_with_unchanged_text_and_declined_sends_nothing(tmp_path):
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": False, "values": {"artist-edit-new-artist": "Bausa Neu"},
                              "ops": [{"fn": "executeArtistEdit"}]})
    opts = json.loads(next(e for e in out["log"] if e.startswith("ccConfirm:"))[len("ccConfirm:"):])
    assert opts["title"] == 'Artist "Bausa" wirklich zu "Bausa Neu" umbenennen?'
    assert opts["text"].startswith("Mit Backup abgesichert") and opts["danger"] is True
    assert not any(c.startswith("POST") for c in out["calls"])


@needs_node
def test_without_tabler_modal_falls_back_to_confirm_with_full_text(tmp_path):
    out = _run_l3b(tmp_path, {"confirmAnswer": False, "values": {"artist-edit-new-artist": "X"},
                              "ops": [{"fn": "executeArtistEdit"}]})
    msg = next(e for e in out["log"] if e.startswith("window.confirm:"))
    assert 'wirklich zu "X" umbenennen?' in msg and "Mit Backup abgesichert" in msg


@needs_node
def test_execute_success_and_error_render_as_alerts(tmp_path):
    ok = {"success_count": 3, "failed_count": 0, "skipped_count": 1}
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": True, "values": {"artist-edit-new-artist": "X"},
                              "routes": {_EXEC: {"status": 200, "body": ok}}, "ops": [{"fn": "executeArtistEdit"}]})
    res = out["els"]["artist-edit-result-content"]["html"]
    # Regression (vorbestehend, am alten Stand reproduziert): die Erfolgsmeldung
    # wurde vom anschließenden Vorschau-Neuladen sofort wieder geleert.
    assert 'class="alert alert-success mb-0"' in res and "3 erfolgreich, 0 fehlgeschlagen, 1 übersprungen." in res
    assert "toast:success|Änderungen geschrieben|3 erfolgreich, 0 fehlgeschlagen, 1 übersprungen." in out["log"]
    assert out["calls"][-1].startswith("GET /api/v1/admin/maintenance/artist-rename/preview")  # Vorschau neu geladen
    assert "Ordner „Bausa“" in res or "Ordner „Bausa\"" in res
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": True, "values": {"artist-edit-new-artist": "X"},
                              "routes": {_EXEC: {"status": 409, "body": {"error": {"message": "<b>läuft</b>"}}}},
                              "ops": [{"fn": "executeArtistEdit"}]})
    res = out["els"]["artist-edit-result-content"]["html"]
    assert 'class="alert alert-danger mb-0"' in res and "&lt;b&gt;läuft&lt;/b&gt;" in res


@needs_node
def test_preview_diff_is_below_filename_not_beside_it(tmp_path):
    """U17 (FINDINGS_INDEX, Tag-Vorschau): Diff unter dem Dateinamen, umbrechbar."""
    body = {"target_count": 1, "changed_count": 1, "outcomes": [
        {"file": "Bausa/Ein sehr langer Pfad/01 - Titel.m4a", "status": "DRY_RUN",
         "before": {"artist": "Bausa"}, "after": {"artist": "Bausa feat. Jemand"}}]}
    out = _run_l3b(tmp_path, {"ops": [{"fn": "renderMetadataEditPreview",
                                       "args": ["@artist-edit-content", body, "artist-edit-execute-btn"]}]})
    html = out["els"]["artist-edit-content"]["html"]
    assert '<div class="list-group">' in html and "row-count" not in html
    assert 'class="text-secondary small text-break">artist: Bausa → Bausa feat. Jemand</div>' in html
    assert out["els"]["artist-edit-execute-btn"]["disabled"] is False


def test_l3_repair_is_no_longer_on_the_artist_page():
    """CC-UI L4 (Nutzerentscheidung 2026-09-28): L3-Reparatur nur noch auf der
    Health-Seite (gleicher Endpunkt, dort nur bei offenen L3-Befunden)."""
    js = ARTIST_JS.read_text(encoding="utf-8")
    html = ARTIST_HTML.read_text(encoding="utf-8")
    assert '"/api/v1/jobs/repair-level3"' not in js and "repair-l3-btn" not in html
    assert "startArtistRepairJob" not in js
    assert '"/api/v1/jobs/repair-level3"' in (CC_DIR / "static" / "pages" / "health.js").read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════
# CC-UI L4 — Metadaten-Editor (Entwurf docs/designs/control-center-ui/
# l4-metadaten-editor.html, Nutzerfreigabe 2026-09-28): Seitenpanel,
# vorbelegte Felder, automatische Vorschau, Album mit EINEM Übernehmen,
# Titel direkt in der Liste. Vorschau-Endpunkte sind read-only (dry_run).
# ═════════════════════════════════════════════════════════════════════════

_RENAME_PREVIEW = "GET /api/v1/admin/maintenance/artist-rename/preview"


def _preview_body(n):
    return {"target_count": n, "changed_count": n, "outcomes": [
        {"file": f"Bausa/A/{i}.m4a", "status": "DRY_RUN", "before": {"artist": "Bausa"}, "after": {"artist": "X"}}
        for i in range(n)]}


def test_editor_markup_has_five_tabs_and_no_legacy_cards():
    html = ARTIST_HTML.read_text(encoding="utf-8")
    for tab in ("artist", "title", "album", "genre", "dupes"):
        assert f'data-md-tab="{tab}"' in html and f'data-md-pane="{tab}"' in html
    assert 'id="artist-metadata-edit-panel"' not in html and 'id="artist-maintenance-panel"' not in html
    assert 'data-count-label="Übernehmen"' in html


@needs_node
def test_editor_opens_with_artist_prefilled_and_no_request_for_unchanged_value(tmp_path):
    out = _run_l3b(tmp_path, {"ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
        {"fn": "openMetadataEditor", "args": ["artist"]},
        {"wait": 700},
    ]})
    assert "md-editor+show" in out["log"]  # ohne Tabler: Rückfall über .show
    assert out["els"]["artist-edit-new-artist"]["value"] == "Bausa"
    assert "Entspricht dem aktuellen Namen" in out["els"]["artist-edit-content"]["html"]
    assert not [c for c in out["calls"] if "preview" in c]


@needs_node
def test_auto_preview_is_debounced_and_labels_the_execute_button(tmp_path):
    out = _run_l3b(tmp_path, {"routes": {_RENAME_PREVIEW: {"status": 200, "body": _preview_body(2)}}, "ops": [
        {"input": "artist-edit-new-artist", "value": "Bausa f"},
        {"input": "artist-edit-new-artist", "value": "Bausa feat"},
        {"input": "artist-edit-new-artist", "value": "Bausa feat. X"},
        {"wait": 800},
    ]})
    previews = [c for c in out["calls"] if "artist-rename/preview" in c]
    assert len(previews) == 1 and "new_artist=Bausa+feat.+X" in previews[0]
    btn = out["els"]["artist-edit-execute-btn"]
    assert btn["disabled"] is False
    assert "2 von 2 Datei(en) werden geändert" in out["els"]["artist-edit-content"]["html"]


@needs_node
def test_slower_older_preview_never_overwrites_newer_one(tmp_path):
    out = _run_l3b(tmp_path, {"routesContains": [
        {"match": "new_artist=Alt", "status": 200, "body": _preview_body(5), "delay": 300},
        {"match": "new_artist=Neu", "status": 200, "body": _preview_body(1)},
    ], "ops": [
        {"input": "artist-edit-new-artist", "value": "Alt"}, {"wait": 650},   # Alt läuft (300 ms)
        {"input": "artist-edit-new-artist", "value": "Neu"}, {"wait": 1000},  # Neu kommt nach Alt an
    ]})
    html = out["els"]["artist-edit-content"]["html"]
    assert "1 von 1 Datei(en) werden geändert" in html and "5 von 5" not in html


@needs_node
def test_album_tab_prefills_current_tags_and_runs_both_edits_with_one_confirm(tmp_path):
    body = _body()
    key = _LONG
    for t in body["tracks"][:2]:
        t.update(album="Powers", album_artist="Bausa")
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": True, "routesContains": [
        {"match": "album-edit/preview", "status": 200, "body": _preview_body(2)},
        {"match": "albumartist-edit/preview", "status": 200, "body": _preview_body(2)},
        {"match": "albumartist-edit/execute", "status": 200, "body": {"success_count": 2, "failed_count": 0, "skipped_count": 0}},
        {"match": "album-edit/execute", "status": 200, "body": {"success_count": 2, "failed_count": 0, "skipped_count": 0}},
    ], "ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"fn": "_selectAlbumForEdit", "args": [key]},
        {"input": "album-edit-new-album", "value": "Powers (Deluxe)"},
        {"input": "albumartist-edit-new-albumartist", "value": "Bausa & Friends"},
        {"wait": 800},
        {"fn": "executeAlbumTab"},
    ]})
    assert out["els"]["albumartist-edit-album-select"]["value"] == key  # versteckte Auswahl synchron
    confirms = [e for e in out["log"] if e.startswith("ccConfirm:")]
    assert len(confirms) == 1
    opts = json.loads(confirms[0][len("ccConfirm:"):])
    assert 'Albumname: "Powers" → "Powers (Deluxe)" (2 Dateien)' in opts["text"]
    assert 'Albuminterpret: "Bausa" → "Bausa & Friends" (2 Dateien)' in opts["text"]
    posts = [c for c in out["calls"] if c.startswith("POST")]
    assert [p.split("/maintenance/")[1] for p in posts] == ["album-edit/execute", "albumartist-edit/execute"]


@needs_node


def test_album_tab_unchanged_values_send_no_preview(tmp_path):
    body = _body()
    for t in body["tracks"][:2]:
        t.update(album="Powers", album_artist="Bausa")
    out = _run_l3b(tmp_path, {"ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"fn": "_selectAlbumForEdit", "args": [_LONG]},
        {"wait": 700},
    ]})
    assert out["els"]["album-edit-new-album"]["value"] == "Powers"
    assert out["els"]["albumartist-edit-new-albumartist"]["value"] == "Bausa"
    assert "keine Änderung" in out["els"]["album-edit-content"]["html"]
    assert not [c for c in out["calls"] if "preview" in c]
    assert out["els"]["album-edit-execute-btn"]["disabled"] is True


@needs_node
def test_title_list_renders_tracks_and_selecting_prefills_title(tmp_path):
    body = _body()
    path = body["tracks"][1]["relative_path"]
    out = _run_l3b(tmp_path, {"ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"fn": "_selectTitleTrack", "args": [path]},
    ]})
    html = out["els"]["title-edit-list"]["html"]
    assert html.count("data-title-path=") == 3 and "<select" not in html
    assert out["els"]["title-edit-track-select"]["value"] == path
    assert out["els"]["title-edit-new-title"]["value"] == "Was Du Liebe nennst"
    assert out["els"]["title-edit-box"]["hidden"] is False
    assert "Entspricht dem aktuellen Titel" in out["els"]["title-edit-content"]["html"]


@needs_node
def test_editor_stays_closed_for_non_admin(tmp_path):
    out = _run_l3b(tmp_path, {"access": "USER", "ops": [{"fn": "openMetadataEditor", "args": ["artist"]}]})
    assert "md-editor+show" not in out["log"]
    assert out["els"]["artist-edit-open-btn"]["hidden"] is True


@needs_node
@needs_node
def test_track_number_edit_preview_and_execute_via_ui(tmp_path):
    """Tracknummer-Feld im Titel-Reiter: Vorbelegung aus Trackdaten,
    Vorschau nach Input, ein "Übernehmen" ruft track-number-edit/execute."""
    body = _body()
    key = _LONG
    # Track hat track_number=1 (siehe _track).
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": True, "routesContains": [
        {"match": "track-number-edit/preview", "status": 200, "body": _preview_body(1)},
        {"match": "track-number-edit/execute", "status": 200,
         "body": {"success_count": 1, "failed_count": 0, "skipped_count": 0}},
    ], "ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"fn": "_selectTitleTrack", "args": [body["tracks"][0]["relative_path"]]},
        {"input": "track-number-edit-new-number", "value": "7"},
        {"wait": 800},
        {"fn": "executeTitleTab"},
    ]})

    # Feld traegt nach Input den Nutzer-Wert
    assert out["els"]["track-number-edit-new-number"]["value"] == "7"

    # Bestaetigung nennt den Tracknummer-Wechsel. _artistConfirm splittet
    # in title (erste Zeile) + text (Rest) - die Aktion steht im Titel.
    confirms = [e for e in out["log"] if e.startswith("ccConfirm:")]
    assert len(confirms) == 1, out["log"]
    opts = json.loads(confirms[0][len("ccConfirm:"):])
    assert "Tracknummer" in opts["title"], opts
    assert '"7"' in opts["title"], opts["title"]

    # Nur track-number-edit/execute wird geschickt
    posts = [c for c in out["calls"] if c.startswith("POST")]
    assert any("track-number-edit/execute" in p for p in posts), out["calls"]
    assert not any("title-edit/execute" in p for p in posts), out["calls"]


def test_album_tab_prefills_year_field_and_runs_with_one_confirm(tmp_path):
    """D.12b.2-Folge: drittes Feld im Album-Reiter (Jahr, ©day) wird
    vorbelegt, ein "Übernehmen" ruft nur die geaenderten Endpunkte auf."""
    body = _body()
    key = _LONG
    for t in body["tracks"][:2]:
        t.update(album="Powers", album_artist="Bausa", year="2020")
    out = _run_l3b(tmp_path, {"tabler": True, "confirmAnswer": True, "routesContains": [
        {"match": "year-edit/preview", "status": 200, "body": _preview_body(2)},
        {"match": "year-edit/execute", "status": 200,
         "body": {"success_count": 2, "failed_count": 0, "skipped_count": 0}},
    ], "ops": [
        {"fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"fn": "_selectAlbumForEdit", "args": [key]},
        {"input": "year-edit-new-year", "value": "2024"},
        {"wait": 800},
        {"fn": "executeAlbumTab"},
    ]})

    # Feld traegt nach dem Input den Nutzer-Wert
    assert out["els"]["year-edit-new-year"]["value"] == "2024"

    # Genau eine Bestaetigung - die Bestaetigung nennt den Alt-Wert (2020)
    # und den neuen Wert (2024), das ist der eigentliche Beleg fuer die
    # Vorbelegung aus den Track-Daten.
    confirms = [e for e in out["log"] if e.startswith("ccConfirm:")]
    assert len(confirms) == 1, out["log"]
    opts = json.loads(confirms[0][len("ccConfirm:"):])
    assert 'Jahr: "2020" → "2024"' in opts["text"], opts["text"]

    # Nur year-edit/execute wird geschickt (Album/Albumartist unveraendert)
    posts = [c for c in out["calls"] if c.startswith("POST")]
    assert [p.split("/maintenance/")[1] for p in posts] == ["year-edit/execute"]
