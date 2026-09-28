# tests/test_control_center_logs_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Logs/Logger — gemeinsamer Kopf mit Reitern "Logdateien" (/logs) und
"Logger-Einstellungen" (/logger), ein Sidebar-Eintrag "Logs" für beide
Seiten (Nutzerentscheidung 2026-09-28), Log-Zeilen im Terminal-Stil
(docs/CONTROL_CENTER_UI_STANDARD.md §10), ccConfirm statt window.confirm()
vor "Konfiguration anwenden", keine Emojis.

Regression (eigener Fehler aus PR #356): beim Entfernen der
badge-status-*-Klassen blieb der zusammengesetzte Klassenname
`badge-${…}` im /logs-Inline-Script übrig - ERROR/CRITICAL-Zeilen waren
danach farblos. Die Level-Farbe hängt jetzt an den cc-t-*-Klassen des
Terminals, ERROR/WARNING-Zähler als ccStatusBadge.

Die echte static/pages/logs.js läuft zusammen mit der echten
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
LOGS_JS = CC_DIR / "static" / "pages" / "logs.js"
LOGGER_JS = CC_DIR / "static" / "pages" / "logger.js"
LOGS_HTML = CC_DIR / "templates" / "logs.html"
LOGGER_HTML = CC_DIR / "templates" / "logger.html"
HEADER_HTML = CC_DIR / "templates" / "_logs_header.html"
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


def _sidebar(html: str) -> str:
    return html[html.index("<aside"):html.index("</aside>")]


# ---------------------------------------------------------------------------
# Templates: Kopf, Reiter, Sidebar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("path, active, inactive", [
    ("/logs", "/logs", "/logger"),
    ("/logger", "/logger", "/logs"),
])
async def test_shared_header_with_active_tab(client, path, active, inactive):
    html = (await client.get(path)).text
    assert '<div class="page-pretitle">System</div>' in html
    assert '<use href="#i-logs"/></svg>Logs</h2>' in html
    subnav = html[html.index('id="logs-subnav"'):]
    subnav = subnav[:subnav.index("</ul>")]
    assert re.search(rf'href="{active}"\s+class="nav-link active" aria-current="page"', subnav)
    assert re.search(rf'href="{inactive}"\s+class="nav-link">', subnav)
    assert "Logdateien" in subnav and "Logger-Einstellungen" in subnav


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/logs", "/logger"])
async def test_sidebar_has_single_logs_entry_active_on_both_pages(client, path):
    sidebar = _sidebar((await client.get(path)).text)
    assert 'href="/logger"' not in sidebar
    assert "Logger</span>" not in sidebar
    idx = sidebar.index('href="/logs"')
    assert "nav-link active" in sidebar[idx:idx + 120]


@pytest.mark.asyncio
async def test_logs_entry_not_active_on_other_pages(client):
    sidebar = _sidebar((await client.get("/admin")).text)
    idx = sidebar.index('href="/logs"')
    assert "nav-link active" not in sidebar[idx:idx + 120]


def test_logs_and_logger_have_no_emoji_browser_dialogs_or_old_placeholders():
    for path in (LOGS_JS, LOGGER_JS, LOGS_HTML, LOGGER_HTML, HEADER_HTML):
        text = path.read_text(encoding="utf-8")
        assert not _EMOJI.search(text), f"Emoji in {path.name}: {_EMOJI.search(text).group()!r}"
        assert "window.confirm" not in text, path.name
        assert "empty-note" not in text, path.name
        assert "Lädt…" not in text, path.name
    # Logs-Logik liegt nicht mehr inline im Template (U1).
    assert "<script>" not in LOGS_HTML.read_text(encoding="utf-8")


def test_logs_js_has_no_composed_badge_class():
    """Regression #356: kein zusammengesetzter badge-${…}-Klassenname mehr."""
    js = LOGS_JS.read_text(encoding="utf-8")
    assert "badge-${" not in js
    assert "status-failed" not in js


# ---------------------------------------------------------------------------
# logs.js im node-Harness
# ---------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => ({ id, hidden: false, textContent: "", innerHTML: "", className: "", style: {},
  disabled: false, value: "", dataset: {}, options: [],
  classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
  setAttribute() {}, getAttribute() { return null; }, querySelector: () => null,
  addEventListener() {}, appendChild() {}, remove() {} });
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = { confirm: () => true };
global.console = { ...console, error() {} };
const calls = [];
global.fetch = async (url) => {
  calls.push(url);
  const body = url.includes("/api/v1/logs") ? sc.logs : { user_id: 1, access_level: "OWNER" };
  return { status: 200, ok: true, json: async () => body, text: async () => JSON.stringify(body) };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
new Function(src)();
setTimeout(() => {
  const g = (id) => document.getElementById(id);
  process.stdout.write(JSON.stringify({
    content: g("logs-content").innerHTML, count: g("logs-count").textContent,
    sources: g("logs-source-select").innerHTML, calls,
  }) + "\n", () => process.exit(0));
}, 30);
"""


def _run(tmp_path: Path, logs: dict) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(harness), str(COMMON_JS), str(LOGS_JS), json.dumps({"logs": logs})],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _body(entries, total=None):
    return {"source": "bot.log", "available_sources": ["bot.log", "err<or>.log"],
            "entries": entries, "total_matched": len(entries) if total is None else total}


_ENTRIES = [
    {"time": "12:00:01", "level": "INFO", "component": "TELEGRAM_BOT", "message": "gestartet"},
    {"time": "12:00:02", "level": "WARNING", "component": "META", "message": "langsam"},
    {"time": "12:00:03", "level": "ERROR", "component": "DL", "message": "<b>kaputt</b>"},
    {"time": "12:00:04", "level": "CRITICAL", "component": "DL", "message": "weg"},
]


@needs_node
def test_render_logs_terminal_style_with_colored_levels(tmp_path):
    out = _run(tmp_path, _body(_ENTRIES))
    html = out["content"]
    assert any("/api/v1/logs?" in c and "limit=200" in c for c in out["calls"])
    assert 'class="cc-terminal' in html
    assert '<span class="cc-t-time">12:00:01</span>' in html
    # Regression #356: ERROR/CRITICAL farbig (cc-t-err), WARNING gelb.
    assert '<span class="cc-t-err">ERROR   </span>' in html
    assert '<span class="cc-t-err">CRITICAL</span>' in html
    assert '<span class="cc-t-warn">WARNING </span>' in html
    assert '<span class="cc-t-info">INFO    </span>' in html
    assert "[TELEGRAM_BOT]" in html
    # Zähler als Status-Badges nach Standard-Mapping.
    assert "bg-red-lt" in html and "2 ERROR/CRITICAL" in html
    assert "bg-yellow-lt" in html and "1 WARNING" in html
    assert out["count"] == "4 Zeilen"


@needs_node
def test_render_logs_escapes_message_and_sources(tmp_path):
    out = _run(tmp_path, _body(_ENTRIES))
    assert "<b>kaputt</b>" not in out["content"]
    assert "&lt;b&gt;kaputt&lt;/b&gt;" in out["content"]
    assert "err&lt;or&gt;.log" in out["sources"]


@needs_node
def test_render_logs_empty_state(tmp_path):
    out = _run(tmp_path, _body([]))
    assert "Keine passenden Log-Zeilen." in out["content"]
    assert "cc-terminal" not in out["content"]
    assert out["count"] == ""


@needs_node
def test_render_logs_truncation_hint(tmp_path):
    out = _run(tmp_path, _body(_ENTRIES[:1], total=500))
    assert "Zeige 1 von 500" in out["content"]
    assert out["count"] == "1 von 500"
    # Nur INFO-Zeilen -> keine Zähler-Badges.
    assert "ERROR/CRITICAL" not in out["content"]
