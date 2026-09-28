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
    head = ARTIST_HTML.read_text(encoding="utf-8").split("<!-- Manual Metadata Editing -->")[0]
    assert not _EMOJI.search(head)
    assert "empty-note" not in head and "drawer-overlay" not in head


@pytest.mark.asyncio
async def test_header_breadcrumb_and_offcanvas_markup(client):
    html = (await client.get("/library/Bausa")).text
    assert '<ol class="breadcrumb mb-1"' in html and 'id="breadcrumb-artist"' in html
    assert '<use href="#i-microphone"/></svg><span id="artist-title">' in html
    assert '<use href="#i-arrow-left"/></svg>Zurück zu Artists' in html
    oc = html[html.index('id="track-drawer"'):]
    oc = oc[:oc.index("<!-- Manual Metadata Editing -->")]
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
    assert 'class="segment-nav' in html and 'id="artist-detail-open-wartung"' in html


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
                         ("albumartist", "users"), ("genre", "tag"), ("maintenance", "tool")):
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
                          "ops": [{"op": "open", "track": _body()["tracks"][1]}, {"op": "action", "action": "maintenance"}]})
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
