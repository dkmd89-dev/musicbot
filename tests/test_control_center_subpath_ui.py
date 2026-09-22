# tests/test_control_center_subpath_ui.py
# -*- coding: utf-8 -*-
"""
Subpath-Betrieb der UI (Phase 2): Templates/JS tragen den vom Reverse
Proxy gemeldeten Prefix (X-Forwarded-Prefix -> scope["root_path"] ->
`base_path` im Template -> <meta name="cc-base"> -> apiUrl() in JS).

Drei Ebenen:
  1. Statische Guards ueber templates/*.html + static/common.js — verhindern,
     dass kuenftig wieder ein root-absoluter fetch()/href/src eingefuehrt wird.
  2. Gerendertes HTML aller 12 Seiten (echte create_app()) mit und ohne Prefix.
  3. common.js real ausgefuehrt (node, falls vorhanden): apiUrl()/_loadInto()/
     checkAuth() rufen fetch() mit dem Prefix auf.
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
COMMON_JS = CC_DIR / "static" / "common.js"
HEALTH_JS = CC_DIR / "static" / "pages" / "health.js"

ALL_PAGES = [
    "/", "/downloads", "/library", "/metadata", "/statistics",
    "/health", "/navidrome", "/logs", "/admin",
]
PREFIX = "/controlcenter"
PREFIX_HEADER = {"X-Forwarded-Prefix": PREFIX}

# href/src/action, die mit "/" beginnen, aber nicht "//" (protokollrelativ)
_ROOT_ABS_ATTR = re.compile(r'\b(?:href|src|action)="/(?!/)')


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
# 1. Statische Guards
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_unprefixed_root_absolute_attribute(path):
    text = path.read_text(encoding="utf-8")
    assert not _ROOT_ABS_ATTR.search(text), (
        f'{path.name}: href/src/action="/..." ohne {{{{ base_path }}}} gefunden'
    )


@pytest.mark.parametrize("path", TEMPLATES + [COMMON_JS, HEALTH_JS], ids=lambda p: p.name)
def test_every_fetch_goes_through_api_url(path):
    text = path.read_text(encoding="utf-8")
    # Kommentarzeilen ausschliessen: ein Kommentar wie
    # "// direkt an fetch() uebergeben" ist kein Aufruf und
    # wuerde sonst als false positive matchen. Als Kommentarzeile
    # gilt eine Zeile, die (nach optionalem Whitespace) mit "//"
    # beginnt.
    code_lines = [
        line for line in text.splitlines()
        if not line.lstrip().startswith("//")
    ]
    code = "\n".join(code_lines)
    # Erlaubt auch mehrzeilige fetch(...)-Aufrufe: zwischen "fetch(" und
    # "apiUrl(" darf Whitespace (inkl. Newline) stehen.
    bad = [m.group(0) for m in re.finditer(r"\bfetch\s*\((?!\s*apiUrl\()", code)]
    assert not bad, f"{path.name}: fetch() ohne apiUrl(): {bad}"


def test_load_into_applies_api_url_internally():
    text = COMMON_JS.read_text(encoding="utf-8")
    assert "fetch(apiUrl(url)" in text


def test_base_template_declares_cc_base_meta():
    text = (CC_DIR / "templates" / "_base.html").read_text(encoding="utf-8")
    assert '<meta name="cc-base" content="{{ base_path }}">' in text


# ─────────────────────────────────────────────────────────────────────────
# 2. Gerendertes HTML
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ALL_PAGES)
async def test_direct_access_renders_unprefixed(client, page):
    html = (await client.get(page)).text
    assert '<meta name="cc-base" content="">' in html
    assert 'href="/static/common.css"' in html
    assert 'src="/static/common.js"' in html
    assert PREFIX not in html


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ALL_PAGES)
async def test_prefixed_access_prefixes_all_links_and_assets(client, page):
    html = (await client.get(page, headers=PREFIX_HEADER)).text
    assert f'<meta name="cc-base" content="{PREFIX}">' in html
    assert f'href="{PREFIX}/static/common.css"' in html
    assert f'src="{PREFIX}/static/common.js"' in html
    # Keine root-absolute Referenz ohne Prefix mehr im gerenderten Dokument
    leftovers = [m.group(0) for m in re.finditer(r'\b(?:href|src|action)="/(?!/)[^"]*"', html)
                 if not m.group(0).split('"')[1].startswith(PREFIX + "/")
                 and m.group(0).split('"')[1] != PREFIX]
    assert leftovers == []


@pytest.mark.asyncio
async def test_prefixed_sidebar_contains_all_nav_targets(client):
    html = (await client.get("/downloads", headers=PREFIX_HEADER)).text
    for nav in ALL_PAGES:
        assert f'href="{PREFIX}{nav}"' in html, nav


@pytest.mark.asyncio
async def test_prefixed_active_marker_and_inline_links(client):
    html = (await client.get("/health", headers=PREFIX_HEADER)).text
    # _base.html rendert href/class als eigene Attribut-Zeilen — deshalb
    # hier tolerant gegenueber Whitespace zwischen beiden Attributen statt
    # eines starren Ein-Zeilen-Substrings (unabhaengige, vorbestehende
    # Drift derselben Art wie bei der panel-link-Assertion unten, hier
    # nachgezogen, weil dieser Test ohnehin auf /health umgestellt wird).
    assert re.search(rf'href="{re.escape(PREFIX)}/health"\s*\n\s*class="nav-link active"', html)
    overview = (await client.get("/", headers=PREFIX_HEADER)).text
    # PR adc1051 ("migrate overview to Tabler", nach PR #285) hat den
    # Inline-Link auf Tabler-Button-Klassen umgestellt (class="panel-link"
    # existiert seitdem nicht mehr, siehe control_center/templates/
    # overview.html) — diese Assertion war seitdem unbemerkt gegen die
    # alte Klasse gerichtet (unabhaengige, vorbestehende Drift, hier
    # nachgezogen, weil dieser Test ohnehin auf /health statt /findings
    # umgestellt wird, api_health.md).
    assert f'href="{PREFIX}/health#findings-content" class="btn btn-link p-0"' in overview


@pytest.mark.asyncio
async def test_hostile_prefix_header_never_reaches_html(client):
    html = (await client.get("/", headers={"X-Forwarded-Prefix": '//evil.example"><script>'})).text
    assert "evil.example" not in html
    assert '<meta name="cc-base" content="">' in html


# ─────────────────────────────────────────────────────────────────────────
# 3. common.js real ausgefuehrt
# ─────────────────────────────────────────────────────────────────────────

_NODE = shutil.which("node")

_HARNESS = r"""
const fs = require("fs");
const base = process.argv[2];
const calls = [];
const els = {};
global.document = {
  querySelector: (sel) => (sel === 'meta[name="cc-base"]' ? { content: base } : null),
  getElementById: (id) => (els[id] = els[id] || { hidden: false, textContent: "", innerHTML: "" }),
  addEventListener: () => {},
  body: { classList: { toggle() {}, remove() {} } },
};
global.window = {};
global.fetch = async (url, opts) => {
  calls.push({ url, method: (opts && opts.method) || "GET" });
  return { status: 200, ok: true, json: async () => ({ user_id: 1, access_level: "OWNER" }) };
};
const src = fs.readFileSync(process.argv[3], "utf-8");
(async () => {
  const api = new Function(src + "\nreturn { apiUrl, _loadInto, checkAuth, onTelegramAuth };")();
  const out = { apiUrl: api.apiUrl("/api/v1/x?y=1") };
  await api._loadInto("some-el", "/api/v1/jobs?limit=5", () => {});
  await api.checkAuth();
  api.onTelegramAuth({ id: 1 });
  await new Promise((r) => setTimeout(r, 10));
  out.calls = calls;
  console.log(JSON.stringify(out));
})();
"""


def _run_harness(tmp_path, base: str) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), base, str(COMMON_JS)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")
def test_common_js_with_prefix_calls_prefixed_api_urls(tmp_path):
    out = _run_harness(tmp_path, PREFIX)
    assert out["apiUrl"] == f"{PREFIX}/api/v1/x?y=1"
    assert [c["url"] for c in out["calls"]] == [
        f"{PREFIX}/api/v1/jobs?limit=5",
        f"{PREFIX}/api/v1/auth/whoami",
        f"{PREFIX}/api/v1/auth/telegram-callback",
    ]


@pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")
def test_common_js_without_prefix_keeps_root_urls(tmp_path):
    out = _run_harness(tmp_path, "")
    assert out["apiUrl"] == "/api/v1/x?y=1"
    assert [c["url"] for c in out["calls"]] == [
        "/api/v1/jobs?limit=5",
        "/api/v1/auth/whoami",
        "/api/v1/auth/telegram-callback",
    ]
