# tests/test_control_center_navidrome_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Navidrome N1 — Musik-Bereich nach docs/CONTROL_CENTER_UI_STANDARD.md §15.

Die echte static/pages/navidrome.js läuft zusammen mit der echten
static/common.js in node gegen einen Fake-DOM und Fake-fetch (gleiches Muster
wie tests/test_control_center_overview_page.py). N1 ändert nur die Darstellung:
Alle Endpunkte und die Modal-Detailansichten bleiben unverändert.
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

CC_DIR = Path(__file__).resolve().parent.parent / "control_center"
COMMON_JS = CC_DIR / "static" / "common.js"
NAVIDROME_JS = CC_DIR / "static" / "pages" / "navidrome.js"
NAVIDROME_HTML = CC_DIR / "templates" / "navidrome.html"
ICONS = CC_DIR / "templates" / "_icons.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
_BASE = "/api/v1/navidrome"


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
# Template / statische Eigenschaften
# ─────────────────────────────────────────────────────────────────────────


def test_navidrome_template_and_js_have_no_emoji():
    for path in (NAVIDROME_HTML, NAVIDROME_JS):
        assert not _EMOJI.search(path.read_text(encoding="utf-8")), f"Emoji in {path.name}"


@pytest.mark.asyncio
async def test_navidrome_page_layout_n1(client):
    html = (await client.get("/navidrome")).text

    assert '<div class="page-pretitle">Music</div>' in html
    assert '<use href="#i-headphones"/></svg>Navidrome</h2>' in html
    # Kopf: Suche, Status (bestehende IDs/Endpunkte), Scan
    for element_id in ("nav-search-form", "nav-search-input", "navidrome-status",
                       "navidrome-artist-count", "navidrome-scan-btn", "navidrome-scan-log-btn"):
        assert f'id="{element_id}"' in html, element_id
    assert 'data-status-endpoint="/api/v1/navidrome/status"' in html
    assert 'data-scan-endpoint="/api/v1/navidrome/scan"' in html
    # Pill-Reiter + Panes
    for tab in ("start", "artists", "albums", "genres", "playlists", "favorites"):
        assert f'data-navtab="{tab}"' in html
        assert f'id="nav-pane-{tab}"' in html
    assert 'id="nav-pane-search"' in html and 'nav nav-pills' in html
    # Regale der Startseite
    for shelf in ("newest", "random", "artists", "favorites"):
        assert f'id="nav-shelf-{shelf}"' in html
    assert 'id="nav-shuffle-btn"' in html
    # Scan-Ausgabe im Seitenpanel; N2: Detailseite statt Modal
    assert 'id="navidrome-scan-offcanvas"' in html and 'id="navidrome-scan-output"' in html
    for element_id in ("nav-pane-detail", "nav-detail-content", "nav-detail-back"):
        assert f'id="{element_id}"' in html, element_id
    assert "nav-detail-modal" not in html and "nav-detail-body" not in html
    # Alte Reiter/Blätter-Bedienung ist weg
    for gone in ("nav-artists-prev", "nav-albums-next", "tab-discover", "nav-discover-random"):
        assert gone not in html


@pytest.mark.asyncio
async def test_navidrome_page_icons_exist_in_sprite(client):
    html = (await client.get("/navidrome")).text
    used = set(re.findall(r'<use href="#i-([a-z0-9-]+)"', html))
    used |= set(re.findall(r'ccIcon\("([a-z0-9-]+)"', NAVIDROME_JS.read_text(encoding="utf-8")))
    sprite = ICONS.read_text(encoding="utf-8")
    missing = sorted(i for i in used if f'id="i-{i}"' not in sprite)
    assert not missing, f"Icons fehlen im Sprite: {missing}"


def test_navidrome_js_uses_real_hash_links_and_no_modal_stack():
    js = NAVIDROME_JS.read_text(encoding="utf-8")
    for kind in ("artist", "album", "song", "genre", "playlist", "top"):
        assert re.search(rf"\b{kind}:\s*_render\w+View", js), f"Detailseite {kind} fehlt"
    assert "#/${type}/" in js
    for gone in ("_navView", "bootstrap.Modal", "_wireDetailLinks", "nav-detail-modal"):
        assert gone not in js, gone
    # Keine Browser-Dialoge mehr
    assert "prompt(" not in js.replace("ccPrompt(", "")
    assert "alert(" not in js.replace('"alert"', "")
    assert "window.confirm" not in js and " confirm(" not in js


# ─────────────────────────────────────────────────────────────────────────
# navidrome.js real ausgeführt
# ─────────────────────────────────────────────────────────────────────────

_HARNESS = r"""
const fs = require("fs");
const [commonPath, pagePath, scenarioJson] = process.argv.slice(2);
const scenario = JSON.parse(scenarioJson);
const steps = scenario.__steps || [];
const els = {};
const mkEl = (id) => {
  const cls = new Set();
  const attrs = {};
  const handlers = {};
  let inner = "";
  const btn = { handlers: {}, addEventListener: (ev, fn) => { (btn.handlers[ev] = btn.handlers[ev] || []).push(fn); } };
  const el = {
    id, hidden: false, textContent: "", className: "", style: {}, dataset: {}, value: "",
    disabled: false, title: "",
    get innerHTML() { return inner; }, set innerHTML(v) { inner = v; },
    classList: {
      add: (...c) => c.forEach((x) => cls.add(x)),
      remove: (...c) => c.forEach((x) => cls.delete(x)),
      contains: (c) => cls.has(c),
      toggle: (c, f) => { const on = f === undefined ? !cls.has(c) : !!f; if (on) cls.add(c); else cls.delete(c); return on; },
    },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k], removeAttribute: (k) => { delete attrs[k]; },
    querySelector: () => (/<button/.test(inner) ? btn : null),
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn); },
    appendChild: (c) => { (el._children = el._children || []).push(c); },
    remove: () => {},
    _cls: cls, _attrs: attrs, _h: handlers, _btn: btn,
  };
  return el;
};
const tabNames = ["start", "artists", "albums", "genres", "playlists", "favorites"];
const tabs = tabNames.map((t) => { const e = mkEl("tab-" + t); e.dataset.navtab = t; els["tab-" + t] = e; return e; });
global.document = {
  querySelector: () => null,
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  querySelectorAll: (sel) => (sel === "[data-navtab]" ? tabs : []),
  createElement: () => mkEl("created"),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { classList: { toggle() {}, remove() {}, contains: () => false }, appendChild() {}, style: { removeProperty() {} } },
};
const hashHandlers = [];
const pushes = [];
global.window = {
  prompt: () => (scenario.__prompt === undefined ? null : scenario.__prompt),
  confirm: () => !!scenario.__confirm,
  location: { hash: scenario.__hash || "", pathname: "/navidrome", search: "" },
  history: { pushState: (_s, _t, url) => { pushes.push(url); global.window.location.hash = ""; } },
  addEventListener: (ev, fn) => { if (ev === "hashchange") hashHandlers.push(fn); },
  scrollTo: () => {},
};
global.localStorage = { getItem: () => null, setItem: () => {} };
global.console = { ...console, error: () => {} };
const calls = [];
global.fetch = async (url, options) => {
  const opts = options || {};
  calls.push({ url, method: opts.method || "GET", body: opts.body || null,
               xhr: (opts.headers || {})["X-Requested-With"] || null });
  const path = url.split("?")[0];
  const r = scenario[url] || scenario[path] || { status: 500, body: { error: { message: "boom" } } };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const names = ["_navShowTab", "runSearch", "createPlaylist", "renamePlaylistPrompt", "deletePlaylistConfirm",
               "_navOnPlaylistClick", "loadShelfRandom", "_navState", "triggerNavidromeScan",
               "_navParseHash", "_navHref"];
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(pagePath, "utf-8")
  + "\nglobalThis.__t = { " + names.join(", ") + " };";
new Function(src)();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  await sleep(60);
  for (const s of steps) {
    if (s.fn) await globalThis.__t[s.fn](...(s.args || []));
    else if (s.set) els[s.set.id].value = s.set.value;
    else if (s.click) { for (const fn of (els[s.click]._h.click || [])) await fn({ preventDefault() {}, target: els[s.click] }); }
    else if (s.hash !== undefined) { global.window.location.hash = s.hash; for (const fn of hashHandlers) await fn(); }
    else if (s.submit) { for (const fn of (els[s.submit]._h.submit || [])) await fn({ preventDefault() {} }); }
    else if (s.clickBtn) { for (const fn of (els[s.clickBtn]._btn.handlers.click || [])) await fn(); }
    else if (s.playlistClick) {
      const p = s.playlistClick;
      await globalThis.__t._navOnPlaylistClick({ preventDefault() {},
        target: { closest: (sel) => (sel === "." + p.cls ? { dataset: { id: p.id, name: p.name } } : null) } });
    }
    await sleep(30);
  }
  const out = {};
  for (const [id, e] of Object.entries(els)) {
    out[id] = { text: e.textContent, html: e.innerHTML, className: e.className, hidden: e.hidden,
                cls: [...e._cls], attrs: e._attrs, value: e.value, disabled: e.disabled };
  }
  const toasts = ((els["cc-toast-container"] || {})._children || []).map((t) => t.innerHTML);
  // Erst vollständig schreiben, dann beenden (process.exit direkt nach console.log
  // schneidet die Ausgabe an der Pipe ab; offene Toast-Timer halten node sonst am Leben).
  const parsed = (scenario.__parse || []).map((h) => globalThis.__t._navParseHash(h));
  const payload = JSON.stringify({ els: out, calls, toasts, pushes, parsed,
    state: { tab: globalThis.__t._navState.tab, prev: globalThis.__t._navState.prevTab } });
  process.stdout.write(payload + "\n", () => process.exit(0));
})();
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}


def _album(i: int, **kw) -> dict:
    d = {"id": f"a{i}", "name": f"Album {i}", "artist": f"Artist {i}", "artist_id": f"ar{i}",
         "cover_art": f"al-{i}", "song_count": 10, "year": 2020 + i}
    d.update(kw)
    return d


def _ok(body) -> dict:
    return {"status": 200, "body": body}


def _base(**overrides) -> dict:
    scenario = {
        "/api/v1/auth/whoami": _WHOAMI,
        f"{_BASE}/status": _ok({"connected": True, "artist_count": 47}),
        f"{_BASE}/newest?page=0&page_size=12": _ok({"items": [_album(1), _album(2)], "page": 0, "page_size": 12, "has_next": False}),
        f"{_BASE}/random?size=40": _ok({"songs": [
            {"id": "s1", "title": "T1", "album_id": "a1"}, {"id": "s2", "title": "T2", "album_id": "a1"},
            {"id": "s3", "title": "T3", "album_id": "a2"},
        ]}),
        f"{_BASE}/albums/a1": _ok({"id": "a1", "name": "Album 1", "artist": "Artist 1", "cover_art": "al-1", "songs": []}),
        f"{_BASE}/albums/a2": _ok({"id": "a2", "name": "Album 2", "artist": "Artist 2", "cover_art": "al-2", "songs": []}),
        f"{_BASE}/artists?page=0&page_size=12": _ok({"items": [{"id": "ar1", "name": "Chapo", "album_count": 1}],
                                                     "page": 0, "page_size": 12, "total": 1, "has_next": False}),
        f"{_BASE}/favorites": _ok({"artists": [], "albums": [], "songs": []}),
    }
    scenario.update(overrides)
    return scenario


def _run(tmp_path, scenario, steps=None, **extra) -> dict:
    scenario = dict(scenario)
    scenario["__steps"] = steps or []
    scenario.update(extra)
    script = tmp_path / "navidrome_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(NAVIDROME_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _urls(out) -> list[str]:
    return [c["url"] for c in out["calls"]]


@needs_node
def test_start_loads_only_the_start_shelves(tmp_path):
    out = _run(tmp_path, _base())

    assert sorted(_urls(out)) == sorted([
        "/api/v1/auth/whoami",
        f"{_BASE}/status",
        f"{_BASE}/newest?page=0&page_size=12",
        f"{_BASE}/random?size=40",
        f"{_BASE}/albums/a1",
        f"{_BASE}/albums/a2",
        f"{_BASE}/artists?page=0&page_size=12",
        f"{_BASE}/favorites",
    ])
    # Raster/Genres/Playlists werden erst beim Öffnen des Reiters geladen
    assert not any("/genres" in u or "/playlists" in u for u in _urls(out))


@needs_node
def test_start_shelves_render_tiles_with_cover_proxy(tmp_path):
    els = _run(tmp_path, _base())["els"]

    newest = els["nav-shelf-newest"]["html"]
    assert newest.count('class="nav-tile nav-album-link"') == 2
    assert f'src="{_BASE}/cover/al-1?size=300"' in newest
    assert 'href="#/album/a1"' in newest and "Artist 1 · 2021" in newest
    artists = els["nav-shelf-artists"]["html"]
    assert "artist-card nav-artist-link" in artists and "1 Album<" in artists
    assert 'href="#/artist/ar1"' in artists
    assert els["nav-shelf-favorites-section"]["hidden"] is True   # keine favorisierten Alben


@needs_node
def test_random_shelf_uses_unique_albums_capped_at_eight_and_skips_failures(tmp_path):
    songs = [{"id": f"s{i}", "title": f"T{i}", "album_id": f"a{i % 12}"} for i in range(30)]
    scenario = _base(**{f"{_BASE}/random?size=40": _ok({"songs": songs})})
    for i in range(12):
        scenario[f"{_BASE}/albums/a{i}"] = _ok({"id": f"a{i}", "name": f"Album {i}", "cover_art": f"al-{i}"})
    scenario[f"{_BASE}/albums/a3"] = {"status": 404, "body": {"error": {"message": "weg"}}}
    out = _run(tmp_path, scenario)

    album_calls = [u for u in _urls(out) if re.search(r"/albums/a\d+$", u)]
    assert len(album_calls) == 8 and len(set(album_calls)) == 8
    html = out["els"]["nav-shelf-random"]["html"]
    assert html.count('class="nav-tile nav-album-link"') == 7      # a3 fehlgeschlagen -> übersprungen


@needs_node
def test_shuffle_button_reloads_only_the_random_shelf(tmp_path):
    out = _run(tmp_path, _base(), steps=[{"click": "nav-shuffle-btn"}])

    assert _urls(out).count(f"{_BASE}/random?size=40") == 2
    assert _urls(out).count(f"{_BASE}/newest?page=0&page_size=12") == 1


@needs_node
def test_shelf_error_is_local_with_retry_and_favorites_shelf_appears(tmp_path):
    scenario = _base(**{
        f"{_BASE}/newest?page=0&page_size=12": {"status": 500, "body": {"error": {"message": "kaputt"}}},
        f"{_BASE}/favorites": _ok({"artists": [], "songs": [], "albums": [_album(5)]}),
    })
    els = _run(tmp_path, scenario)["els"]

    assert "kaputt" in els["nav-shelf-newest"]["html"] and "Erneut versuchen" in els["nav-shelf-newest"]["html"]
    assert "nav-tile" in els["nav-shelf-random"]["html"]            # andere Regale unberührt
    assert els["nav-shelf-favorites-section"]["hidden"] is False
    assert "Album 5" in els["nav-shelf-favorites"]["html"]


@needs_node
def test_tile_text_is_escaped(tmp_path):
    evil = _album(1, name='<img src=x onerror=alert(1)>', artist="<b>x</b>")
    scenario = _base(**{f"{_BASE}/newest?page=0&page_size=12": _ok({"items": [evil], "page": 0, "page_size": 12, "has_next": False})})
    html = _run(tmp_path, scenario)["els"]["nav-shelf-newest"]["html"]

    assert "<img src=x" not in html and "<b>x</b>" not in html
    assert "&lt;img" in html


@needs_node
def test_status_badge_online_and_offline(tmp_path):
    els = _run(tmp_path, _base())["els"]
    assert els["navidrome-status"]["className"] == "badge bg-green-lt"
    assert "Online" in els["navidrome-status"]["html"]
    assert els["navidrome-artist-count"]["text"] == "47 Artists"

    offline = _run(tmp_path, _base(**{f"{_BASE}/status": {"status": 500, "body": {"error": {"message": "x"}}}}))["els"]
    assert offline["navidrome-status"]["className"] == "badge bg-red-lt"
    assert "Offline" in offline["navidrome-status"]["html"]


@needs_node
def test_tabs_switch_lazily_and_mark_active(tmp_path):
    scenario = _base(**{
        f"{_BASE}/albums?page=0&page_size=30": _ok({"items": [_album(1)], "page": 0, "page_size": 30, "total": None, "has_next": False}),
    })
    out = _run(tmp_path, scenario, steps=[{"fn": "_navShowTab", "args": ["albums"]}, {"fn": "_navShowTab", "args": ["albums"]}])

    assert _urls(out).count(f"{_BASE}/albums?page=0&page_size=30") == 1      # zweites Öffnen lädt nicht neu
    els = out["els"]
    assert els["tab-albums"]["attrs"]["aria-selected"] == "true" and "active" in els["tab-albums"]["cls"]
    assert els["tab-start"]["attrs"]["aria-selected"] == "false" and "active" not in els["tab-start"]["cls"]
    assert "active" in els["nav-pane-albums"]["cls"] and "active" not in els["nav-pane-start"]["cls"]
    assert els["nav-albums-list"]["html"].startswith('<div class="nav-grid">')
    assert els["nav-albums-footer"]["html"] == ""                             # has_next false -> kein Button


@needs_node
def test_artist_grid_loads_more_and_appends(tmp_path):
    page = lambda n, nxt: _ok({"items": [{"id": f"ar{n}", "name": f"Artist{n}", "album_count": 2}],
                               "page": n, "page_size": 30, "total": 2, "has_next": nxt})
    scenario = _base(**{f"{_BASE}/artists?page=0&page_size=30": page(0, True),
                        f"{_BASE}/artists?page=1&page_size=30": page(1, False)})
    out = _run(tmp_path, scenario, steps=[{"fn": "_navShowTab", "args": ["artists"]}, {"clickBtn": "nav-artists-footer"}])

    els = out["els"]
    assert f"{_BASE}/artists?page=1&page_size=30" in _urls(out)
    assert "Artist0" in els["nav-artists-list"]["html"] and "Artist1" in els["nav-artists-list"]["html"]
    assert "nav-grid-artists" in els["nav-artists-list"]["html"]
    assert els["nav-artists-footer"]["html"] == ""                            # letzte Seite -> Button weg


@needs_node
def test_empty_and_error_states_use_ccstate(tmp_path):
    scenario = _base(**{
        f"{_BASE}/genres": _ok({"items": []}),
        f"{_BASE}/favorites": _ok({"artists": [], "albums": [], "songs": []}),
        f"{_BASE}/playlists?page=0&page_size=20": {"status": 500, "body": {"error": {"message": "nope"}}},
    })
    out = _run(tmp_path, scenario, steps=[{"fn": "_navShowTab", "args": ["genres"]}, {"fn": "_navShowTab", "args": ["favorites"]},
                                          {"fn": "_navShowTab", "args": ["playlists"]}])
    els = out["els"]

    assert "Keine Genres gefunden." in els["nav-genres-list"]["html"]
    assert "Noch keine Favoriten" in els["nav-favorites-list"]["html"]
    assert "nope" in els["nav-playlists-list"]["html"] and "Erneut versuchen" in els["nav-playlists-list"]["html"]


@needs_node
def test_genres_render_as_chips(tmp_path):
    scenario = _base(**{f"{_BASE}/genres": _ok({"items": [{"name": "Deutschrap", "song_count": 12}, {"name": "Pop", "song_count": None}]})})
    html = _run(tmp_path, scenario, steps=[{"fn": "_navShowTab", "args": ["genres"]}])["els"]["nav-genres-list"]["html"]

    assert html.count("nav-genre-link") == 2 and 'href="#/genre/Deutschrap"' in html and ">12<" in html


@needs_node
def test_search_shows_grouped_results_and_leaving_returns_to_previous_tab(tmp_path):
    scenario = _base(**{f"{_BASE}/search?q=Ali&type=all": _ok({
        "artists": [{"id": "ar9", "name": "Ali"}],
        "albums": [_album(9)],
        "songs": [{"id": "s9", "title": "Lied", "artist": "Ali", "album": "Album 9", "duration": 185}],
    })})
    out = _run(tmp_path, scenario, steps=[
        {"fn": "_navShowTab", "args": ["albums"]},
        {"set": {"id": "nav-search-input", "value": "Ali"}}, {"submit": "nav-search-form"},
    ])
    els = out["els"]

    assert f"{_BASE}/search?q=Ali&type=all" in _urls(out)
    assert out["state"] == {"tab": "search", "prev": "albums"}
    assert "active" in els["nav-pane-search"]["cls"] and "active" not in els["nav-pane-albums"]["cls"]
    html = els["nav-search-results"]["html"]
    assert "Artists" in html and "Alben" in html and "Songs" in html
    assert "nav-song-link" in html and "3:05" in html and "Ali" in html

    back = _run(tmp_path, scenario, steps=[
        {"fn": "_navShowTab", "args": ["albums"]},
        {"set": {"id": "nav-search-input", "value": "Ali"}}, {"submit": "nav-search-form"},
        {"set": {"id": "nav-search-input", "value": "  "}}, {"submit": "nav-search-form"},
    ])
    assert back["state"]["tab"] == "albums"
    assert "active" in back["els"]["nav-pane-albums"]["cls"]


@needs_node
def test_search_without_results_and_error(tmp_path):
    empty = _run(tmp_path, _base(**{f"{_BASE}/search?q=zzz&type=all": _ok({"artists": [], "albums": [], "songs": []})}),
                 steps=[{"set": {"id": "nav-search-input", "value": "zzz"}}, {"submit": "nav-search-form"}])
    assert "Keine Ergebnisse" in empty["els"]["nav-search-results"]["html"]

    err = _run(tmp_path, _base(), steps=[{"set": {"id": "nav-search-input", "value": "zzz"}}, {"submit": "nav-search-form"}])
    assert "boom" in err["els"]["nav-search-results"]["html"] and "Erneut versuchen" in err["els"]["nav-search-results"]["html"]


@needs_node
def test_playlists_list_and_create_with_dialog_and_toast(tmp_path):
    pl = _ok({"items": [{"id": "p1", "name": "Mix", "song_count": 3, "owner": "admin", "duration": 600}],
              "page": 0, "page_size": 20, "total": 1, "has_next": False})
    scenario = _base(**{f"{_BASE}/playlists?page=0&page_size=20": pl,
                        f"{_BASE}/playlists": _ok({"success": True, "playlist_id": "p2", "name": "Neue Liste"})})
    out = _run(tmp_path, scenario, steps=[{"fn": "_navShowTab", "args": ["playlists"]}, {"fn": "createPlaylist"}],
               __prompt="  Neue\nListe ")

    html = out["els"]["nav-playlists-list"]["html"]
    assert "nav-playlist-rename" in html and "nav-playlist-delete" in html and "admin · 3 Songs · 10:00" in html
    post = [c for c in out["calls"] if c["method"] == "POST" and c["url"] == f"{_BASE}/playlists"]
    assert len(post) == 1 and json.loads(post[0]["body"]) == {"name": "Neue Liste"} and post[0]["xhr"] == "XMLHttpRequest"
    assert any("Playlist angelegt" in t for t in out["toasts"])
    assert _urls(out).count(f"{_BASE}/playlists?page=0&page_size=20") == 2       # danach neu geladen


@needs_node
def test_playlist_create_cancelled_or_blank_sends_nothing(tmp_path):
    for prompt in (None, "   "):
        out = _run(tmp_path, _base(), steps=[{"fn": "createPlaylist"}], __prompt=prompt)
        assert not [c for c in out["calls"] if c["method"] != "GET"]


@needs_node
def test_playlist_rename_and_delete_are_confirmed_and_toasted(tmp_path):
    scenario = _base(**{
        f"{_BASE}/playlists/p1": _ok({"success": True}),
        f"{_BASE}/playlists?page=0&page_size=20": _ok({"items": [], "page": 0, "page_size": 20, "total": 0, "has_next": False}),
    })
    ren = _run(tmp_path, scenario, steps=[{"playlistClick": {"cls": "nav-playlist-rename", "id": "p1", "name": "Mix"}}],
               __prompt="Neu")
    put = [c for c in ren["calls"] if c["method"] == "PUT"]
    assert len(put) == 1 and put[0]["url"] == f"{_BASE}/playlists/p1" and json.loads(put[0]["body"]) == {"name": "Neu"}
    assert any("Playlist umbenannt" in t for t in ren["toasts"])

    same = _run(tmp_path, scenario, steps=[{"playlistClick": {"cls": "nav-playlist-rename", "id": "p1", "name": "Mix"}}],
                __prompt="Mix")
    assert not [c for c in same["calls"] if c["method"] != "GET"]                 # unveränderter Name -> kein Request

    declined = _run(tmp_path, scenario, steps=[{"playlistClick": {"cls": "nav-playlist-delete", "id": "p1", "name": "Mix"}}],
                    __confirm=False)
    assert not [c for c in declined["calls"] if c["method"] == "DELETE"]

    deleted = _run(tmp_path, scenario, steps=[{"playlistClick": {"cls": "nav-playlist-delete", "id": "p1", "name": "Mix"}}],
                   __confirm=True)
    assert [c["url"] for c in deleted["calls"] if c["method"] == "DELETE"] == [f"{_BASE}/playlists/p1"]
    assert any("Playlist gelöscht" in t for t in deleted["toasts"])


@needs_node
def test_playlist_write_error_is_shown_as_toast(tmp_path):
    scenario = _base(**{f"{_BASE}/playlists": {"status": 403, "body": {"error": {"message": "Keine Berechtigung"}}}})
    out = _run(tmp_path, scenario, steps=[{"fn": "createPlaylist"}], __prompt="Neu")

    assert any("Playlist nicht angelegt" in t and "Keine Berechtigung" in t for t in out["toasts"])


@needs_node
def test_scan_result_goes_to_offcanvas_output_and_toast(tmp_path):
    scenario = _base(**{f"{_BASE}/scan": _ok({"success": True, "returncode": 0, "stdout": "fertig", "stderr": ""})})
    out = _run(tmp_path, scenario, steps=[{"click": "navidrome-scan-btn"}])

    els = out["els"]
    assert [c["method"] for c in out["calls"] if c["url"] == f"{_BASE}/scan"] == ["POST"]
    assert "Scan erfolgreich (rc=0)" in els["navidrome-scan-output"]["text"] and "fertig" in els["navidrome-scan-output"]["text"]
    assert "d-none" not in els["navidrome-scan-log-btn"]["cls"]
    assert els["navidrome-scan-btn"]["disabled"] is False
    assert any("Scan abgeschlossen" in t for t in out["toasts"])


@needs_node
def test_scan_failure_and_forbidden(tmp_path):
    failed = _run(tmp_path, _base(**{f"{_BASE}/scan": _ok({"success": False, "returncode": 2, "stdout": "", "stderr": "kaputt"})}),
                  steps=[{"click": "navidrome-scan-btn"}])
    assert "Scan fehlgeschlagen (rc=2)" in failed["els"]["navidrome-scan-output"]["text"]
    assert any("Scan fehlgeschlagen" in t for t in failed["toasts"])

    denied = _run(tmp_path, _base(**{f"{_BASE}/scan": {"status": 403, "body": {"error": {"message": "Nur Admin"}}}}),
                  steps=[{"click": "navidrome-scan-btn"}])
    assert "Nur Admin" in denied["els"]["navidrome-scan-output"]["text"]
    assert any("Scan nicht möglich" in t and "Nur Admin" in t for t in denied["toasts"])
    assert denied["els"]["navidrome-scan-btn"]["disabled"] is False


# ─────────────────────────────────────────────────────────────────────────
# N2: Detailseiten per Hash-Routing (kein Modal mehr)
# ─────────────────────────────────────────────────────────────────────────

_SONGS = [
    {"id": "s1", "title": "Erster", "artist": "Artist 1", "artist_id": "ar1", "album": "Album 1", "album_id": "a1",
     "duration": 185, "track": 1},
    {"id": "s2", "title": "Zweiter", "artist": "Artist 1", "artist_id": "ar1", "album": "Album 1", "album_id": "a1",
     "duration": 60, "track": 2},
]


def _detail_scenario(**overrides) -> dict:
    scenario = _base(**{
        f"{_BASE}/albums/a1": _ok({"id": "a1", "name": "Album 1", "artist": "Artist 1", "artist_id": "ar1",
                                   "cover_art": "al-1", "year": 2021, "song_count": 2, "duration": 245, "songs": _SONGS}),
        f"{_BASE}/artists/ar1": _ok({"id": "ar1", "name": "Chapo", "album_count": 2, "albums": [_album(1), _album(2)]}),
        f"{_BASE}/artists/ar1/top": _ok({"artist_id": "ar1", "artist_name": "Chapo", "songs": _SONGS}),
        f"{_BASE}/songs/s1": _ok({**_SONGS[0], "genre": "Rap", "genres": ["Rap", "Deutschrap"], "play_count": 7, "cover_art": "al-1", "year": 2021}),
        f"{_BASE}/genres/Deutsch%20Rap": _ok({"name": "Deutsch Rap", "songs": _SONGS}),
        f"{_BASE}/playlists/p1": _ok({"id": "p1", "name": "Mix", "owner": "admin", "song_count": 2, "duration": 245, "songs": _SONGS}),
    })
    scenario.update(overrides)
    return scenario


@needs_node
def test_deep_link_renders_album_page_without_loading_start_shelves(tmp_path):
    out = _run(tmp_path, _detail_scenario(), __hash="#/album/a1")

    assert f"{_BASE}/albums/a1" in _urls(out)
    assert f"{_BASE}/newest?page=0&page_size=12" not in _urls(out)       # Deep-Link lädt keine Startseite
    assert out["state"]["tab"] == "detail"
    assert "active" in out["els"]["nav-pane-detail"]["cls"] and "active" not in out["els"]["nav-pane-start"]["cls"]
    html = out["els"]["nav-detail-content"]["html"]
    assert "Album 1" in html and f'{_BASE}/cover/al-1?size=500' in html
    assert 'href="#/artist/ar1"' in html and "2021 · 2 Songs · 4:05" in html
    assert html.count('href="#/song/') == 2 and "Erster" in html and "3:05" in html


@needs_node
def test_artist_page_links_albums_and_top_songs(tmp_path):
    html = _run(tmp_path, _detail_scenario(), __hash="#/artist/ar1")["els"]["nav-detail-content"]["html"]

    assert "Chapo" in html and "2 Alben" in html
    assert html.count('class="nav-tile nav-album-link"') == 2 and 'href="#/album/a1"' in html
    assert 'href="#/top/ar1"' in html
    assert 'class="artist-avatar"' in html and f'{_BASE}/cover/ar1?size=300' in html


@needs_node
def test_song_genre_top_and_playlist_pages(tmp_path):
    song = _run(tmp_path, _detail_scenario(), __hash="#/song/s1")["els"]["nav-detail-content"]["html"]
    assert "Erster" in song and 'href="#/artist/ar1"' in song and 'href="#/album/a1"' in song
    assert "Rap, Deutschrap" in song and ">7<" in song and "3:05" in song

    genre_out = _run(tmp_path, _detail_scenario(), __hash="#/genre/Deutsch%20Rap")
    assert f"{_BASE}/genres/Deutsch%20Rap" in _urls(genre_out)             # Hash-Kodierung bleibt erhalten
    assert "Deutsch Rap" in genre_out["els"]["nav-detail-content"]["html"]
    assert genre_out["els"]["nav-detail-content"]["html"].count('href="#/song/') == 2

    top = _run(tmp_path, _detail_scenario(), __hash="#/top/ar1")["els"]["nav-detail-content"]["html"]
    assert 'href="#/artist/ar1"' in top and "Chapo" in top and top.count('href="#/song/') == 2

    playlist = _run(tmp_path, _detail_scenario(), __hash="#/playlist/p1")["els"]["nav-detail-content"]["html"]
    assert "Mix" in playlist and "admin · 2 Songs · 4:05" in playlist
    assert 'class="btn nav-playlist-rename" data-id="p1" data-name="Mix"' in playlist
    assert "nav-playlist-delete" in playlist and playlist.count('href="#/song/') == 2


@needs_node
def test_detail_states_not_found_and_error(tmp_path):
    missing = _run(tmp_path, _detail_scenario(**{f"{_BASE}/albums/a1": {"status": 404, "body": {"error": {"message": "weg"}}}}),
                   __hash="#/album/a1")["els"]["nav-detail-content"]["html"]
    assert "Nicht gefunden" in missing and "Erneut versuchen" not in missing

    broken = _run(tmp_path, _detail_scenario(**{f"{_BASE}/albums/a1": {"status": 500, "body": {"error": {"message": "kaputt"}}}}),
                  __hash="#/album/a1")["els"]["nav-detail-content"]["html"]
    assert "kaputt" in broken and "Erneut versuchen" in broken


@needs_node
def test_detail_text_is_escaped(tmp_path):
    evil = _detail_scenario(**{f"{_BASE}/albums/a1": _ok({
        "id": "a1", "name": "<script>alert(1)</script>", "artist": "<b>x</b>", "artist_id": "ar1", "songs": []})})
    html = _run(tmp_path, evil, __hash="#/album/a1")["els"]["nav-detail-content"]["html"]

    assert "<script>" not in html and "<b>x</b>" not in html and "&lt;script&gt;" in html


@needs_node
def test_hashchange_opens_detail_and_clearing_hash_returns_to_previous_tab(tmp_path):
    out = _run(tmp_path, _detail_scenario(), steps=[
        {"fn": "_navShowTab", "args": ["albums"]},
        {"hash": "#/album/a1"},
    ])
    assert out["state"] == {"tab": "detail", "prev": "albums"}
    assert "Album 1" in out["els"]["nav-detail-content"]["html"]

    back = _run(tmp_path, _detail_scenario(), steps=[
        {"fn": "_navShowTab", "args": ["albums"]},
        {"hash": "#/album/a1"},
        {"hash": ""},                                                   # Browser-Zurück
    ])
    assert back["state"]["tab"] == "albums"
    assert "active" in back["els"]["nav-pane-albums"]["cls"] and "active" not in back["els"]["nav-pane-detail"]["cls"]


@needs_node
def test_back_button_and_tabs_clear_the_hash(tmp_path):
    out = _run(tmp_path, _detail_scenario(), steps=[
        {"fn": "_navShowTab", "args": ["genres"]},
        {"hash": "#/album/a1"},
        {"click": "nav-detail-back"},
    ])
    assert out["state"]["tab"] == "genres" and out["pushes"] == ["/navidrome"]

    via_tab = _run(tmp_path, _detail_scenario(), __hash="#/album/a1", steps=[{"click": "tab-artists"}])
    assert via_tab["state"]["tab"] == "artists" and via_tab["pushes"] == ["/navidrome"]

    # Deep-Link: "Zurück" führt zur Startseite (kein vorheriger Reiter bekannt)
    deep = _run(tmp_path, _detail_scenario(), __hash="#/album/a1", steps=[{"click": "nav-detail-back"}])
    assert deep["state"]["tab"] == "start" and f"{_BASE}/newest?page=0&page_size=12" in _urls(deep)


@needs_node
def test_search_result_links_are_hash_links_and_search_clears_detail_hash(tmp_path):
    scenario = _detail_scenario(**{f"{_BASE}/search?q=Ali&type=all": _ok({
        "artists": [{"id": "ar9", "name": "Ali"}], "albums": [_album(9)], "songs": [_SONGS[0]]})})
    out = _run(tmp_path, scenario, __hash="#/album/a1", steps=[
        {"set": {"id": "nav-search-input", "value": "Ali"}}, {"submit": "nav-search-form"}])

    html = out["els"]["nav-search-results"]["html"]
    assert 'href="#/artist/ar9"' in html and 'href="#/album/a9"' in html and 'href="#/song/s1"' in html
    assert out["state"]["tab"] == "search" and out["pushes"] == ["/navidrome"]


@needs_node
def test_playlist_delete_on_detail_page_returns_to_playlist_list(tmp_path):
    scenario = _detail_scenario(**{
        f"{_BASE}/playlists?page=0&page_size=20": _ok({"items": [], "page": 0, "page_size": 20, "total": 0, "has_next": False}),
    })
    out = _run(tmp_path, scenario, __hash="#/playlist/p1", __confirm=True,
               steps=[{"playlistClick": {"cls": "nav-playlist-delete", "id": "p1", "name": "Mix"}}])

    assert [c["url"] for c in out["calls"] if c["method"] == "DELETE"] == [f"{_BASE}/playlists/p1"]
    assert out["state"]["tab"] == "playlists"
    assert _urls(out).count(f"{_BASE}/playlists?page=0&page_size=20") == 1     # genau einmal geladen
    assert any("Playlist gelöscht" in t for t in out["toasts"])


@needs_node
def test_playlist_rename_on_detail_page_reloads_the_page(tmp_path):
    scenario = _detail_scenario(**{f"{_BASE}/playlists/p1": _ok({"id": "p1", "name": "Mix", "owner": "a", "song_count": 0, "songs": []})})
    out = _run(tmp_path, scenario, __hash="#/playlist/p1", __prompt="Neu",
               steps=[{"playlistClick": {"cls": "nav-playlist-rename", "id": "p1", "name": "Mix"}}])

    assert [c["url"] for c in out["calls"] if c["method"] == "PUT"] == [f"{_BASE}/playlists/p1"]
    assert [c["url"] for c in out["calls"] if c["method"] == "GET"].count(f"{_BASE}/playlists/p1") == 2
    assert out["state"]["tab"] == "detail"


@needs_node
def test_parse_hash_accepts_only_known_routes(tmp_path):
    hashes = ["#/album/a1", "#/genre/Deutsch%20Rap", "#/nope/x", "#/album/", "", "#/song/%E0%A4%A"]
    out = _run(tmp_path, _base(), __parse=hashes)

    assert out["parsed"] == [{"type": "album", "id": "a1"}, {"type": "genre", "id": "Deutsch Rap"},
                             None, None, None, None]
