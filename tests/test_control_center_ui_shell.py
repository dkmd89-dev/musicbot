# tests/test_control_center_ui_shell.py
# -*- coding: utf-8 -*-
"""
CC-UI-1 — Shell, Theme und gemeinsame UI-Helfer nach
docs/CONTROL_CENTER_UI_STANDARD.md.

Geprüft wird der echte Produktionscode: gerenderte Seiten über die echte
App (httpx.ASGITransport), die ausgelieferten Dateien common.css /
common.js und - falls node verfügbar ist - die Helfer real ausgeführt
(gleiches Harness-Muster wie tests/test_control_center_subpath_ui.py).
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
TEMPLATES = sorted((CC_DIR / "templates").glob("*.html"))
COMMON_CSS = CC_DIR / "static" / "common.css"
COMMON_JS = CC_DIR / "static" / "common.js"
ICONS = CC_DIR / "templates" / "_icons.html"

ALL_PAGES = ["/", "/downloads", "/library", "/statistics", "/health", "/mappings", "/navidrome", "/logs", "/logger", "/admin"]
# CC-UI Logs/Logger: "adjustments" (Logger) ist kein Sidebar-Eintrag mehr,
# /logger hängt als Reiter unter "Logs".
NAV_ICONS = ["home", "download", "books", "chart", "headphones", "health", "logs", "settings"]


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


def _sidebar(html: str) -> str:
    start = html.index('id="sidebar"')
    return html[start:html.index("</aside>", start)]


# ─────────────────────────────────────────────────────────────────────────
# Shell (_base.html)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_defaults_to_dark_theme_with_prerender_script(client, path):
    html = (await client.get(path)).text

    assert '<html lang="de" data-bs-theme="dark">' in html
    head = html[: html.index("</head>")]
    # Gespeicherte Wahl wird VOR dem Stylesheet gelesen (kein Aufblitzen).
    assert head.index('localStorage.getItem("cc-theme")') < head.index("tabler.min.css")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_page_has_theme_toggle_and_icon_sprite(client, path):
    html = (await client.get(path)).text

    assert 'id="theme-toggle"' in html
    assert 'aria-label="Hell/Dunkel umschalten"' in html
    for icon in NAV_ICONS + ["music", "sun", "moon", "logout"]:
        assert re.search(rf'<symbol fill="none" stroke="currentColor"[^>]*id="i-{icon}"', html), f"Icon i-{icon} fehlt/gefuellt im Sprite"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_sidebar_is_dark_uses_sprite_icons_and_has_no_emoji(client, path):
    html = (await client.get(path)).text
    sidebar = _sidebar(html)

    assert 'data-bs-theme="dark"' in html[html.index("<aside"):html.index('id="sidebar"') + 60]
    for icon in NAV_ICONS:
        assert f'<use href="#i-{icon}"/>' in sidebar
    assert not re.search(r"[\U0001F300-\U0001FAFF]", sidebar), "Emoji in der Sidebar"


@pytest.mark.asyncio
async def test_logout_button_keeps_id_and_text_with_icon(client):
    html = (await client.get("/")).text

    btn = html[html.index('id="logout-btn"'):]
    btn = btn[: btn.index("</button>")]
    assert "hidden" in btn
    assert '<use href="#i-logout"/>' in btn
    assert btn.rstrip().endswith("Abmelden")


def test_every_used_icon_exists_in_sprite():
    # Jinja-Kommentare {# ... #} werden nicht gerendert - Symbole darin
    # zählen nicht (Regression: Symbole landeten versehentlich im Kommentar).
    sprite = re.sub(r"\{#.*?#\}", "", ICONS.read_text(encoding="utf-8"), flags=re.S)
    defined = set(re.findall(r'<symbol [^>]*id="i-([a-z-]+)"', sprite))
    used = set()
    for path in TEMPLATES + [COMMON_JS]:
        used |= set(re.findall(r'href="#i-([a-z-]+)"', path.read_text(encoding="utf-8")))
    js = COMMON_JS.read_text(encoding="utf-8")
    used |= set(re.findall(r'icon: "([a-z-]+)"', js))
    used |= set(re.findall(r'ccIcon\("([a-z-]+)"', js))
    missing = used - defined
    assert not missing, f"Icons ohne Symbol im Sprite: {sorted(missing)}"


# ─────────────────────────────────────────────────────────────────────────
# common.css
# ─────────────────────────────────────────────────────────────────────────


def test_common_css_has_no_broken_comment_openers():
    """Regression: '//* ...' (Zeile 52) und '}* ...' (Zeile 118) seit der
    Tabler-Migration a82e998 - der Browser verwarf dadurch die Regeln
    #current-user und #navidrome-status komplett."""
    css = COMMON_CSS.read_text(encoding="utf-8")

    assert not re.search(r"^//\*", css, re.M)
    assert not re.search(r"^\}\*", css, re.M)
    assert css.count("/*") == css.count("*/")


def test_previously_dropped_rules_are_standalone_rules():
    css = COMMON_CSS.read_text(encoding="utf-8")
    no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    for selector in ("#current-user", "#navidrome-status"):
        match = re.search(r"(^|[}\s])" + re.escape(selector) + r"\s*\{", no_comments)
        assert match, f"{selector} ist keine eigenständige Regel"
        before = no_comments[: match.start() + 1].rstrip()
        assert before == "" or before.endswith("}"), f"{selector}: Müll vor dem Selektor"


def test_common_css_follows_theme_toggle_not_os_setting():
    css = COMMON_CSS.read_text(encoding="utf-8")
    no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "prefers-color-scheme" not in no_comments
    assert '[data-bs-theme="dark"]' in no_comments
    assert "--bg: var(--tblr-body-bg)" in no_comments
    assert "--card-bg: var(--tblr-bg-surface)" in no_comments


def test_common_css_sets_teal_accent_and_terminal_style():
    css = COMMON_CSS.read_text(encoding="utf-8")

    assert "--tblr-primary: #0ca678;" in css
    assert ".cc-terminal {" in css
    # Tabler färbt .btn-link fest blau - muss auf den Akzent gezogen sein.
    assert ".btn-link { color: var(--tblr-primary); }" in css


# ─────────────────────────────────────────────────────────────────────────
# common.js - Helfer real ausgeführt
# ─────────────────────────────────────────────────────────────────────────

_NODE = shutil.which("node")

_HARNESS = r"""
const fs = require("fs");
const base = process.argv[2];
const calls = [];
const els = {};
const attrs = { "data-bs-theme": "dark" };
const storage = {};
let storageThrows = false;
global.document = {
  querySelector: (sel) => (sel === 'meta[name="cc-base"]' ? { content: base } : null),
  getElementById: (id) => (els[id] = els[id] || { hidden: false, textContent: "", innerHTML: "" }),
  addEventListener: () => {},
  documentElement: { getAttribute: (k) => attrs[k], setAttribute: (k, v) => { attrs[k] = v; } },
  body: { classList: { toggle() {}, remove() {} } },
};
global.localStorage = {
  setItem: (k, v) => { if (storageThrows) throw new Error("blocked"); storage[k] = v; },
  getItem: (k) => storage[k],
};
let confirmAsked = null;
global.window = { confirm: (t) => { confirmAsked = t; return true; } };
let nextResponse = null;
global.fetch = async (url, opts) => {
  calls.push({ url, method: (opts && opts.method) || "GET", body: opts && opts.body,
               ctype: opts && opts.headers && opts.headers["Content-Type"],
               credentials: opts && opts.credentials });
  return nextResponse;
};
const resp = (status, body) => ({ status, ok: status >= 200 && status < 300,
  text: async () => (body === undefined ? "" : JSON.stringify(body)) });
const src = fs.readFileSync(process.argv[3], "utf-8");
(async () => {
  const api = new Function(src + "\nreturn { ccIcon, ccStatusBadge, ccStatusKind, ccState, ccApi, ccConfirm, ccSetTheme, CcApiError };")();
  const out = {};
  out.icon = api.ccIcon("download", "me-1");
  out.badge = api.ccStatusBadge("error", "<b>x</b>");
  out.badgeUnknown = api.ccStatusBadge("nope", "y");
  out.kinds = ["SUCCEEDED", "RUNNING", "FAILED", "CANCELLED", "success", "WARNING", "FAIR", "UNRESOLVED", "whatever"]
    .map(api.ccStatusKind);

  const el = { innerHTML: "" };
  api.ccState.empty(el, "Noch <nichts>", "sub & mehr");
  out.empty = el.innerHTML;
  api.ccState.loading(el);
  out.loading = el.innerHTML;

  nextResponse = resp(200, { ok: 1 });
  out.get = await api.ccApi("GET", "/api/v1/x");
  nextResponse = resp(201, { id: 7 });
  out.post = await api.ccApi("POST", "/api/v1/y", { a: 1 });
  nextResponse = resp(204);
  out.empty204 = await api.ccApi("DELETE", "/api/v1/z");
  nextResponse = resp(409, { error: { code: "X", message: "Schon vorhanden" } });
  try { await api.ccApi("POST", "/api/v1/y", {}); } catch (e) { out.err = { name: e.name, msg: e.message, status: e.status }; }
  nextResponse = resp(500);
  try { await api.ccApi("GET", "/api/v1/q"); } catch (e) { out.err500 = e.message; }
  nextResponse = resp(401, { error: { message: "no" } });
  try { await api.ccApi("GET", "/api/v1/w"); } catch (e) { out.err401 = e.status; }
  out.loginVisible = els["login-view"] && els["login-view"].hidden === false;
  out.dashHidden = els["dashboard-view"] && els["dashboard-view"].hidden === true;
  out.calls = calls;

  out.confirm = await api.ccConfirm({ title: "T", text: "Wirklich?" });
  out.confirmAsked = confirmAsked;

  api.ccSetTheme("light");
  out.themeAfterLight = attrs["data-bs-theme"];
  out.stored = storage["cc-theme"];
  storageThrows = true;
  api.ccSetTheme("dark");
  out.themeAfterDarkBlockedStorage = attrs["data-bs-theme"];
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _run(tmp_path, base: str) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), base, str(COMMON_JS)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")


@needs_node
def test_icon_and_status_badge_markup_is_escaped(tmp_path):
    out = _run(tmp_path, "")

    assert out["icon"] == '<svg class="icon me-1" aria-hidden="true"><use href="#i-download"/></svg>'
    assert out["badge"].startswith('<span class="badge bg-red-lt">')
    assert '<use href="#i-alert"/>' in out["badge"]
    assert "&lt;b&gt;x&lt;/b&gt;" in out["badge"] and "<b>" not in out["badge"]
    assert out["badgeUnknown"].startswith('<span class="badge bg-secondary-lt">')


@needs_node
def test_status_kind_mapping_matches_standard(tmp_path):
    out = _run(tmp_path, "")

    assert out["kinds"] == ["ok", "running", "error", "neutral", "ok", "warn", "warn", "warn", "neutral"]


@needs_node
def test_state_helpers_escape_text(tmp_path):
    out = _run(tmp_path, "")

    assert "Noch &lt;nichts&gt;" in out["empty"] and "sub &amp; mehr" in out["empty"]
    assert 'class="empty' in out["empty"]
    assert "placeholder-glow" in out["loading"]


@needs_node
@pytest.mark.parametrize("base", ["", "/controlcenter"])
def test_cc_api_goes_through_api_url_and_sends_json(tmp_path, base):
    out = _run(tmp_path, base)

    assert [c["url"] for c in out["calls"]] == [
        f"{base}/api/v1/x", f"{base}/api/v1/y", f"{base}/api/v1/z",
        f"{base}/api/v1/y", f"{base}/api/v1/q", f"{base}/api/v1/w",
    ]
    assert all(c["credentials"] == "same-origin" for c in out["calls"])
    get, post = out["calls"][0], out["calls"][1]
    assert get["method"] == "GET" and get.get("body") is None and get.get("ctype") is None
    assert post["method"] == "POST" and post["body"] == '{"a":1}' and post["ctype"] == "application/json"
    assert out["get"] == {"ok": 1} and out["post"] == {"id": 7} and out["empty204"] is None


@needs_node
def test_cc_api_errors_use_error_message_and_401_shows_login(tmp_path):
    out = _run(tmp_path, "")

    assert out["err"] == {"name": "CcApiError", "msg": "Schon vorhanden", "status": 409}
    assert out["err500"] == "HTTP 500"
    assert out["err401"] == 401
    assert out["loginVisible"] is True and out["dashHidden"] is True


@needs_node
def test_confirm_falls_back_to_browser_confirm_without_tabler(tmp_path):
    out = _run(tmp_path, "")

    assert out["confirm"] is True
    assert out["confirmAsked"] == "Wirklich?"


@needs_node
def test_theme_switch_persists_and_tolerates_blocked_storage(tmp_path):
    out = _run(tmp_path, "")

    assert out["themeAfterLight"] == "light"
    assert out["stored"] == "light"
    assert out["themeAfterDarkBlockedStorage"] == "dark"


# ─────────────────────────────────────────────────────────────────────────
# Mobile Navigation (FINDINGS_INDEX: Menü-Schalter außerhalb des
# Bildschirms) - der Schalter darf nicht in <aside id="sidebar"> liegen,
# weil common.css die Sidebar auf dem Handy per translateX(-100%) aus dem
# Bild schiebt.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL_PAGES)
async def test_mobile_menu_toggle_lives_in_header_not_in_sidebar(client, path):
    html = (await client.get(path)).text

    assert 'id="sidebar-toggle"' not in _sidebar(html)
    header = html[html.index('<header class="navbar'):]
    header = header[: header.index("</header>")]
    assert 'id="sidebar-toggle"' in header
    toggle = header[header.index('id="sidebar-toggle"'):]
    toggle = toggle[: toggle.index(">")]
    assert 'aria-controls="sidebar"' in toggle
    assert 'aria-expanded="false"' in toggle
    assert 'id="sidebar-backdrop"' in html


def test_mobile_backdrop_is_a_real_element_not_body_pseudo():
    css = COMMON_CSS.read_text(encoding="utf-8")
    no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "body.sidebar-open::after" not in no_comments
    assert "#sidebar-backdrop" in no_comments


_NAV_HARNESS = r"""
const fs = require("fs");
const docListeners = {};
const mk = (id) => {
  const l = {}; const a = {};
  return { id, listeners: l, attrs: a,
    addEventListener: (t, f) => { (l[t] = l[t] || []).push(f); },
    setAttribute: (k, v) => { a[k] = String(v); },
    getAttribute: (k) => a[k],
    fire: (t, ev) => (l[t] || []).forEach((f) => f(ev || {})) };
};
const els = { "sidebar-toggle": mk("sidebar-toggle"), "sidebar": mk("sidebar"), "sidebar-backdrop": mk("sidebar-backdrop") };
els["sidebar-toggle"].attrs["aria-expanded"] = "false";
const cls = new Set();
global.document = {
  querySelector: () => null,
  getElementById: (id) => els[id] || null,
  addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { classList: {
    toggle: (c, force) => { const on = force === undefined ? !cls.has(c) : !!force; on ? cls.add(c) : cls.delete(c); return on; },
    remove: (c) => cls.delete(c), add: (c) => cls.add(c), contains: (c) => cls.has(c) } },
};
global.window = {};
global.localStorage = { getItem: () => null, setItem: () => {} };
new Function(fs.readFileSync(process.argv[2], "utf-8"))();
(docListeners["DOMContentLoaded"] || []).forEach((f) => f());
const snap = () => ({ open: cls.has("sidebar-open"), expanded: els["sidebar-toggle"].attrs["aria-expanded"] });
const keydown = (key) => (docListeners["keydown"] || []).forEach((f) => f({ key }));
const out = {};
out.start = snap();
els["sidebar-toggle"].fire("click"); out.afterToggle = snap();
els["sidebar-backdrop"].fire("click"); out.afterBackdrop = snap();
els["sidebar-toggle"].fire("click");
keydown("a"); out.afterOtherKey = snap();
keydown("Escape"); out.afterEscape = snap();
els["sidebar-toggle"].fire("click");
els["sidebar"].fire("click", { target: { closest: () => null } }); out.afterNonLinkClick = snap();
els["sidebar"].fire("click", { target: { closest: (s) => (s === "a" ? {} : null) } }); out.afterLinkClick = snap();
els["sidebar-toggle"].fire("click"); els["sidebar-toggle"].fire("click"); out.afterDoubleToggle = snap();
console.log(JSON.stringify(out));
"""


@needs_node
def test_mobile_menu_opens_and_closes_with_aria_state(tmp_path):
    script = tmp_path / "nav.js"
    script.write_text(_NAV_HARNESS, encoding="utf-8")
    result = subprocess.run([_NODE, str(script), str(COMMON_JS)],
                            capture_output=True, text=True, timeout=30, check=True)
    out = json.loads(result.stdout.strip().splitlines()[-1])

    closed = {"open": False, "expanded": "false"}
    opened = {"open": True, "expanded": "true"}
    assert out["start"] == closed
    assert out["afterToggle"] == opened
    assert out["afterBackdrop"] == closed
    assert out["afterOtherKey"] == opened
    assert out["afterEscape"] == closed
    assert out["afterNonLinkClick"] == opened
    assert out["afterLinkClick"] == closed
    assert out["afterDoubleToggle"] == closed
