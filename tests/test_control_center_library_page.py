# tests/test_control_center_library_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Library — Schritt L1 (Nutzerentscheidung 2026-09-28):

- U1: das Inline-JS von /library und /library/{artist} liegt byte-identisch
  in static/pages/library.js bzw. static/pages/library_artist.js. Das
  Verhalten sichern die bestehenden Tests ab, die das Skript jetzt aus
  diesen Dateien lesen (test_artist_*_ui.py, test_artist_detail_master_view.py,
  test_library_home_dashboard.py, test_control_center_ui.py).
- U16: /metadata (Stub-Seite, nirgends verlinkt) leitet auf /library um.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
CC_DIR = ROOT / "control_center"


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path, script", [
    ("/library", "library.js"),
    ("/library/Bausa", "library_artist.js"),
])
async def test_library_pages_load_their_script_from_static_pages(client, path, script):
    html = (await client.get(path)).text
    assert f'<script src="/static/pages/{script}"></script>' in html
    # kein Inline-Skript mehr im Seiteninhalt (nur noch die Shell-Skripte)
    content = html[html.index('id="dashboard-view"'):]
    assert "<script>" not in content.split(f'/static/pages/{script}')[0]
    served = (await client.get(f"/static/pages/{script}")).text
    assert served == (CC_DIR / "static" / "pages" / script).read_text(encoding="utf-8")


@pytest.mark.parametrize("template", ["library.html", "library_artist_detail.html"])
def test_templates_have_no_inline_script(template):
    assert "<script>" not in (CC_DIR / "templates" / template).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_library_script_uses_prefixed_src_behind_proxy(client):
    html = (await client.get("/library/Bausa", headers={"X-Forwarded-Prefix": "/cc"})).text
    assert '<script src="/cc/static/pages/library_artist.js"></script>' in html


@pytest.mark.asyncio
async def test_metadata_redirects_to_library(client):
    r = await client.get("/metadata", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/library"
    assert not (CC_DIR / "templates" / "metadata.html").exists()


@pytest.mark.asyncio
async def test_metadata_redirect_keeps_proxy_prefix(client):
    r = await client.get("/metadata", headers={"X-Forwarded-Prefix": "/cc"}, follow_redirects=False)
    assert r.headers["location"] == "/cc/library"


@pytest.mark.asyncio
async def test_metadata_redirect_ignores_hostile_prefix(client):
    """Kein offener Redirect: ungültige Prefixe verwirft normalize_prefix()."""
    r = await client.get("/metadata", headers={"X-Forwarded-Prefix": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/library"


# ═════════════════════════════════════════════════════════════════════════
# CC-UI Library L2 — Library-Übersicht als Metadaten-Werkstatt
# (Nutzerentscheidung 2026-09-28). Die echte static/pages/library.js läuft
# zusammen mit der echten static/common.js in node.
# ═════════════════════════════════════════════════════════════════════════

import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

LIBRARY_JS = CC_DIR / "static" / "pages" / "library.js"
LIBRARY_HTML = CC_DIR / "templates" / "library.html"
COMMON_JS = CC_DIR / "static" / "common.js"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def test_library_has_no_emoji_inline_svg_or_old_states():
    js = LIBRARY_JS.read_text(encoding="utf-8")
    html = LIBRARY_HTML.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "<path" not in html and "<path" not in js, "Inline-SVG statt Sprite"
    assert "empty-note" not in js and "empty-note" not in html
    assert "row-list" not in js and "counts-grid" not in js
    assert 'style="cursor' not in html
    # F3: kein wiederholtes Einfügen des Stale-Hinweises mehr
    assert "insertBefore" not in js


@pytest.mark.asyncio
async def test_library_header_and_workshop_controls(client):
    html = (await client.get("/library")).text
    assert '<div class="page-pretitle">Music</div>' in html
    assert '<use href="#i-books"/></svg>Library</h2>' in html
    assert "Metadaten prüfen, bearbeiten und aktualisieren." in html
    assert 'id="artist-issue-filter"' in html and 'id="artists-overview-stale"' in html
    assert "Library-Metadata" in html and 'class="card-header cc-summary"' in html
    for icon in ("music", "microphone", "disc", "tool", "health", "alert", "search", "filter", "scan"):
        assert f'<use href="#i-{icon}"/>' in html, icon


_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const el = { id, hidden: id === "library-kpi-tiles", textContent: "", innerHTML: "", className: "", style: {},
    disabled: false, value: "", dataset: {}, listeners: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    setAttribute() {}, getAttribute() { return null; },
    querySelector: () => null, querySelectorAll: () => [],
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    appendChild() {}, remove() {},
    insertAdjacentHTML(pos, html) { this.innerHTML = pos === "afterbegin" ? html + this.innerHTML : this.innerHTML + html; } };
  if (id === "artist-issue-filter") {
    // value nur setzbar, wenn eine passende <option> existiert (wie im Browser)
    let v = "";
    Object.defineProperty(el, "value", {
      get: () => v,
      set: (nv) => { v = (nv === "" || el.innerHTML.includes(`value="${nv}"`)) ? nv : ""; },
    });
  }
  return el;
};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = { location: { href: "" } };
global.console = { ...console, error() {} };
const calls = [];
const routes = sc.routes || {};
global.fetch = async (url) => {
  calls.push(url);
  const key = url.split("?")[0];
  const r = key.endsWith("/auth/whoami") ? { status: 200, body: { user_id: 1, access_level: "OWNER" } }
    : (routes[key] || { status: 200, body: { entries: [] } });
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => JSON.stringify(r.body), json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
const api = new Function(src + "\nreturn { renderArtistsOverview, _renderLibraryAttention, loadMetadataList, loadMappingSummary };")();
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  for (const op of sc.ops || []) {
    if (op.op === "call") await api[op.fn](...(op.args || []).map((a) => (typeof a === "string" && a[0] === "@" ? document.getElementById(a.slice(1)) : a)));
    else if (op.op === "set") { document.getElementById(op.id).value = op.value; for (const f of document.getElementById(op.id).listeners.change || []) f(); }
    else if (op.op === "clickIssue") document.getElementById("library-attention-content").onclick({ target: { closest: () => ({ dataset: { issue: op.code } }) } });
    await tick();
  }
  const out = { calls, els: {} };
  Object.keys(els).forEach((id) => { out.els[id] = { html: els[id].innerHTML, text: String(els[id].textContent), hidden: els[id].hidden, value: els[id].value }; });
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})();
"""


def _run(tmp_path: Path, scenario: dict) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run([_NODE, str(harness), str(COMMON_JS), str(LIBRARY_JS), json.dumps(scenario)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_API = "/api/v1/library"
_ARTISTS = [
    {"artist": "Cro", "file_count": 20, "album_count": 3, "health_score": 95, "issue_codes": []},
    {"artist": "<Apache>", "file_count": 8, "album_count": 1, "health_score": 60,
     "issue_codes": ["GENRE_EMPTY", "ARTWORK_MISSING"]},
    {"artist": "Bausa", "file_count": 5, "album_count": 1, "health_score": 80, "issue_codes": ["GENRE_EMPTY"]},
]
_OVERVIEW = {"total": 3, "artists": _ARTISTS, "generated_at": "2026-09-27T05:47:00", "stale": False}
_CACHED = {"library": {"artists": 3, "files": 33, "albums": 5}, "scan": {"completed_at": "2026-09-27T05:47:00"},
           "health": {"score": 88.5, "status": "GOOD"},
           "statistics": {"total_files": 33, "total_artists": 3, "total_albums": 5,
                          "issues_by_severity": {"WARNING": 3}, "issues_by_code": {"GENRE_EMPTY": 2, "ARTWORK_MISSING": 1}}}
_OK = {f"{_API}/artists-overview": {"status": 200, "body": _OVERVIEW},
       f"{_API}/health/cached": {"status": 200, "body": _CACHED}}


@needs_node
def test_artist_rows_have_edit_link_topics_badge_and_escaping(tmp_path):
    out = _run(tmp_path, {"routes": _OK})
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 3
    assert "&lt;Apache&gt;" in html and "<Apache>" not in html
    assert 'href="/library/%3CApache%3E" class="btn btn-sm btn-ghost-teal"' in html
    assert '<use href="#i-edit"/>' in html and "Bearbeiten" in html
    assert 'title="Genre-Tag leer, Cover fehlt">2 offen</span>' in html
    assert out["els"]["artists-overview-count"]["text"] == "3 Artists"


@needs_node
def test_issue_filter_offers_present_topics_with_counts_and_filters(tmp_path):
    out = _run(tmp_path, {"routes": _OK, "ops": [{"op": "set", "id": "artist-issue-filter", "value": "GENRE_EMPTY"}]})
    sel = out["els"]["artist-issue-filter"]["html"]
    assert "Alle Artists (3)" in sel and "Mit offenen Themen (2)" in sel
    assert sel.index("Genre-Tag leer (2)") < sel.index("Cover fehlt (1)")
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 2 and ">Cro<" not in html
    assert out["els"]["artists-overview-count"]["text"] == "2 von 3 Artists"


@needs_node
def test_issue_filter_any_and_empty_result(tmp_path):
    out = _run(tmp_path, {"routes": _OK, "ops": [{"op": "set", "id": "artist-issue-filter", "value": "__any"}]})
    assert out["els"]["artists-overview-content"]["html"].count('class="artist-row"') == 2
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/artists-overview": {"status": 200, "body": {
        **_OVERVIEW, "artists": [_ARTISTS[0]]}}}, "ops": [{"op": "set", "id": "artist-issue-filter", "value": "__any"}]})
    assert "Keine Artists für diese Auswahl" in out["els"]["artists-overview-content"]["html"]


@needs_node
def test_attention_click_filters_artists_by_topic(tmp_path):
    out = _run(tmp_path, {"routes": _OK, "ops": [{"op": "clickIssue", "code": "ARTWORK_MISSING"}]})
    assert out["els"]["artist-issue-filter"]["value"] == "ARTWORK_MISSING"
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 1 and "&lt;Apache&gt;" in html
    att = out["els"]["library-attention-content"]["html"]
    assert 'data-issue="GENRE_EMPTY"' in att and "Betroffene Artists anzeigen" in att


@needs_node
def test_attention_findings_link_points_to_health_not_missing_page(tmp_path):
    """F1: /findings gibt es nicht (404) - Link auf die Findings der Health-Seite."""
    out = _run(tmp_path, {"routes": _OK})
    att = out["els"]["library-attention-content"]["html"]
    assert 'href="/health#findings-content"' in att
    assert 'href="/findings"' not in att
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/health/cached": {"status": 200, "body": {
        **_CACHED, "statistics": {"issues_by_severity": {}, "issues_by_code": {}}}}}})
    att = out["els"]["library-attention-content"]["html"]
    assert "Keine kritischen Probleme" in att and 'href="/health#findings-content"' in att


@needs_node
def test_missing_health_report_shows_empty_state_not_endless_loading(tmp_path):
    """F2: /health/cached 404 -> vorher blieben beide Karten auf 'wird geladen'."""
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/health/cached": {"status": 404, "body": {
        "error": {"code": "LIBRARY_REPORT_MISSING", "message": "x"}}}}})
    assert "Noch kein Health-Scan" in out["els"]["library-health-content"]["html"]
    assert "Noch keine Auswertung" in out["els"]["library-attention-content"]["html"]
    # Kennzahlen bleiben ausgeblendet (niemals geschätzte Werte)
    assert out["els"].get("library-kpi-tiles", {"hidden": True})["hidden"] is True


@needs_node
def test_health_server_error_shows_error_with_retry(tmp_path):
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/health/cached": {"status": 500, "body": {}}}})
    for key in ("library-health-content", "library-attention-content"):
        assert "text-danger" in out["els"][key]["html"] and "Erneut versuchen" in out["els"][key]["html"]


@needs_node
def test_stale_hint_is_set_once_in_fixed_place(tmp_path):
    """F3: vorher wurde der Hinweis bei jedem Neuladen zusätzlich eingefügt."""
    stale = {**_OVERVIEW, "stale": True}
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/artists-overview": {"status": 200, "body": stale}}, "ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content", stale]}]})
    el = out["els"]["artists-overview-stale"]
    assert el["hidden"] is False
    assert el["text"] == "Stand: 2026-09-27T05:47:00 (nicht mehr aktuell)"


@needs_node
def test_live_scan_tracks_table_with_edit_link_and_truncation(tmp_path):
    tracks = {"total": 120, "limit": 50, "offset": 0, "tracks": [
        {"relative_path": "Cro/A/1.m4a", "filename": "1.m4a", "artist": "Cro", "title": "<b>Easy</b>",
         "album": "Tru.", "artist_directory": "Cro"},
        {"relative_path": "x/2.m4a", "filename": "2.m4a", "artist": None, "title": None, "album": None,
         "artist_directory": None}]}
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/tracks": {"status": 200, "body": tracks}}, "ops": [
        {"op": "set", "id": "metadata-missing-filter", "value": "META_GENRE_MISSING"},
        {"op": "call", "fn": "loadMetadataList", "args": ["tracks"]}]})
    html = out["els"]["metadata-content"]["html"]
    assert any(c == f"{_API}/tracks?limit=50&offset=0&issue_code=META_GENRE_MISSING" for c in out["calls"])
    assert "<table" in html and "row-list" not in html
    assert "Zeige 2 von 120" in html and "kein Auto-Rendern großer Listen" in html
    assert "&lt;b&gt;Easy&lt;/b&gt;" in html and ">2.m4a<" in html
    assert html.count('href="/library/Cro"') == 1  # nur Tracks mit artist_directory


@needs_node
def test_live_scan_mapping_summary_as_datagrid(tmp_path):
    summary = {"artists": 10, "channels": 2, "hierarchy": 5, "rules": 7, "aliases": 3, "overrides": 1,
               "unique_primary_genres": 12}
    out = _run(tmp_path, {"routes": {**_OK, f"{_API}/mapping-summary": {"status": 200, "body": summary}},
                          "ops": [{"op": "call", "fn": "loadMappingSummary"}]})
    html = out["els"]["metadata-content"]["html"]
    assert 'class="datagrid"' in html and "Primäre Genres" in html and ">12<" in html
