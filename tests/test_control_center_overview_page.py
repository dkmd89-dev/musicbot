# tests/test_control_center_overview_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Overview — Darstellung nach docs/CONTROL_CENTER_UI_STANDARD.md.

Die echte static/pages/overview.js läuft zusammen mit der echten
static/common.js in node gegen einen Fake-DOM und Fake-fetch (gleiches
Muster wie tests/test_control_center_ui_shell.py). Geprüft werden die
unveränderten Schwellen/Endpunkte und die neuen Zustände (Fehler statt
dauerhaftem "Lädt…", Status-Badges, escapte Verlaufseinträge).
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
OVERVIEW_JS = CC_DIR / "static" / "pages" / "overview.js"
OVERVIEW_HTML = CC_DIR / "templates" / "overview.html"
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


# ─────────────────────────────────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────────────────────────────────


def test_overview_template_and_js_have_no_emoji():
    for path in (OVERVIEW_HTML, OVERVIEW_JS):
        assert not _EMOJI.search(path.read_text(encoding="utf-8")), f"Emoji in {path.name}"


@pytest.mark.asyncio
async def test_overview_uses_standard_page_header_and_icons(client):
    html = (await client.get("/")).text

    assert '<div class="page-pretitle">System</div>' in html
    assert '<use href="#i-home"/></svg>Overview</h2>' in html
    for icon in ("cpu", "memory", "disk", "robot", "books", "history", "server", "headphones"):
        assert f'<use href="#i-{icon}"/>' in html
        assert f'id="i-{icon}"' in html, f"Symbol i-{icon} wird nicht gerendert"
    assert 'id="attention-status"' in html


@pytest.mark.asyncio
async def test_header_is_single_row_on_mobile(client):
    html = (await client.get("/")).text
    header = html[html.index('<header class="navbar'):html.index("</header>")]

    assert 'class="container-xl flex-nowrap"' in header
    title = header[: header.index("MusicBot Control Center")]
    assert title.rstrip().endswith('<span class="navbar-text">')
    assert 'class="navbar-nav d-none d-md-flex"' in header
    assert 'id="current-user" class="nav-item d-none d-sm-block' in header


# ─────────────────────────────────────────────────────────────────────────
# overview.js real ausgeführt
# ─────────────────────────────────────────────────────────────────────────

_HARNESS = r"""
const fs = require("fs");
const [commonPath, overviewPath, scenarioJson] = process.argv.slice(2);
const scenario = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const cls = new Set();
  const attrs = {};
  return {
    id, hidden: false, textContent: "", innerHTML: "", className: "", style: {},
    classList: { add: (c) => cls.add(c), remove: (...cs) => cs.forEach((c) => cls.delete(c)),
                 contains: (c) => cls.has(c), toggle: () => {} },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    querySelector: () => null, addEventListener: () => {},
    _cls: cls, _attrs: attrs,
  };
};
global.document = {
  querySelector: () => null,
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = {};
global.localStorage = { getItem: () => null, setItem: () => {} };
global.console = { ...console, error: () => {} };
const calls = [];
global.fetch = async (url) => {
  calls.push(url);
  const path = url.split("?")[0];
  const r = scenario[path] || scenario[url] || { status: 500, body: { error: { message: "x" } } };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
           json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(overviewPath, "utf-8");
new Function(src)();
setTimeout(() => {
  const out = {};
  for (const [id, e] of Object.entries(els)) {
    out[id] = { text: e.textContent, html: e.innerHTML, className: e.className, hidden: e.hidden,
                width: e.style.width, cls: [...e._cls] };
  }
  console.log(JSON.stringify({ els: out, calls }));
}, 50);
"""

_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "OWNER"}}
_SYSTEM = {"status": 200, "body": {
    "cpu_percent": 12.34, "cpu_count": 4,
    "memory_percent": 75.0, "memory_used_mb": 2048, "memory_total_mb": 4096,
    "disk_percent": 95.5, "disk_used_gb": 90.0, "disk_total_gb": 100.0,
    "bot_service_active": True, "bot_uptime_formatted": "2 Tage",
    "bot_started_at": "2026-09-26T10:00:00",
    "platform_os": "Linux", "platform_release": "6.1", "platform_python": "3.11.2", "platform_arch": "x86_64",
    "load_avg_1": 0.5, "load_avg_5": 0.25, "load_avg_15": 0.125,
    "swap_total_gb": 0, "swap_used_gb": 0,
}}
_HEALTH = {"status": 200, "body": {
    "library": {"files": 1234, "artists": 56, "albums": 78},
    "health": {"status": "GOOD", "score": 85}, "stale": True,
}}


def _base(**overrides):
    scenario = {
        "/api/v1/auth/whoami": _WHOAMI,
        "/api/v1/admin/system/status": _SYSTEM,
        "/api/v1/library/health/cached": _HEALTH,
        "/api/v1/navidrome/status": {"status": 200, "body": {"connected": True, "artist_count": 1500}},
        "/api/v1/library/findings/summary": {"status": 200, "body": {"open": 0}},
        "/api/v1/downloads/history": {"status": 200, "body": {"entries": []}},
    }
    scenario.update(overrides)
    return scenario


def _run(tmp_path, scenario) -> dict:
    script = tmp_path / "overview_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(OVERVIEW_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_loads_only_the_known_cheap_endpoints(tmp_path):
    out = _run(tmp_path, _base())

    assert sorted(out["calls"]) == sorted([
        "/api/v1/auth/whoami",
        "/api/v1/admin/system/status",
        "/api/v1/library/health/cached",
        "/api/v1/navidrome/status",
        "/api/v1/library/findings/summary",
        "/api/v1/downloads/history?limit=5",
    ])
    assert not any("repair-plan" in c or c.endswith("/library/health") for c in out["calls"])


@needs_node
def test_metric_thresholds_unchanged_and_now_visible(tmp_path):
    els = _run(tmp_path, _base())["els"]

    assert els["metric-cpu-value"]["text"] == "12.3 %"
    assert els["metric-cpu-value"]["className"] == "h2 mb-0"
    assert els["metric-ram-value"]["className"] == "h2 mb-0 text-warning"   # 75 % >= 70
    assert els["metric-disk-value"]["className"] == "h2 mb-0 text-danger"   # 95.5 % >= 90
    assert els["metric-cpu-sub"]["text"] == "4 Kerne"
    assert els["metric-ram-sub"]["text"] == "2.0 GB / 4.0 GB"
    assert els["metric-disk-sub"]["text"] == "90.0 GB / 100.0 GB"


@needs_node
def test_bot_status_is_badge_without_emoji(tmp_path):
    online = _run(tmp_path, _base())["els"]["metric-bot-value"]["html"]
    assert online.startswith('<span class="badge bg-green-lt">') and "Online" in online

    offline_sys = json.loads(json.dumps(_SYSTEM))
    offline_sys["body"]["bot_service_active"] = False
    offline = _run(tmp_path, _base(**{"/api/v1/admin/system/status": offline_sys}))["els"]["metric-bot-value"]["html"]
    assert offline.startswith('<span class="badge bg-red-lt">') and "Offline" in offline


@needs_node
def test_system_card_values_without_emoji(tmp_path):
    els = _run(tmp_path, _base())["els"]

    assert els["system-platform-os"]["text"] == "Linux 6.1"
    assert els["system-platform-python"]["text"] == "Python 3.11.2 · x86_64"
    assert els["system-load-value"]["text"] == "0.50 · 0.25 · 0.13"
    assert els["system-swap-value"]["text"] == "kein Swap"
    assert els["system-uptime-value"]["text"] == "2 Tage"


@needs_node
def test_system_status_error_resets_values(tmp_path):
    els = _run(tmp_path, _base(**{"/api/v1/admin/system/status": {"status": 503}}))["els"]

    assert els["metric-cpu-value"]["text"] == "–"
    assert els["metric-cpu-sub"]["text"] == "Nicht abrufbar"
    assert els["system-load-value"]["text"] == "–"


@needs_node
def test_library_health_bar_color_follows_status_and_marks_stale(tmp_path):
    els = _run(tmp_path, _base())["els"]

    assert els["status-library-value"]["text"] == "1.234 Dateien"
    # GOOD mit Score 85: vorher gelb (Score-Schwelle 90), jetzt grün (Status)
    assert els["status-library-health-fill"]["className"] == "progress-bar bg-green"
    assert els["status-library-health-fill"]["width"] == "85%"
    assert els["status-library-health-label"]["text"] == "GOOD · 85/100 · Bericht veraltet"
    assert els["status-library-health-bar"]["hidden"] is False
    hint = els["status-library-hint"]["html"]
    assert "56 Artists · 78 Alben" in hint and "bg-yellow-lt" in hint and "veraltet" in hint


@needs_node
@pytest.mark.parametrize("status,color", [("EXCELLENT", "green"), ("FAIR", "yellow"), ("POOR", "red"), ("CRITICAL", "red")])
def test_library_health_bar_color_per_status(tmp_path, status, color):
    health = {"status": 200, "body": {"library": {"files": 1}, "health": {"status": status, "score": 50}, "stale": False}}
    els = _run(tmp_path, _base(**{"/api/v1/library/health/cached": health}))["els"]

    assert els["status-library-health-fill"]["className"] == f"progress-bar bg-{color}"


@needs_node
def test_library_without_report_shows_not_checked(tmp_path):
    els = _run(tmp_path, _base(**{"/api/v1/library/health/cached": {"status": 404, "body": {"error": {"message": "x"}}}}))["els"]

    assert els["status-library-value"]["text"] == "Nicht geprüft"
    assert els["status-library-hint"]["text"] == "Noch kein Health-Report vorhanden."


@needs_node
@pytest.mark.parametrize("open_findings,color,text", [
    (0, "green", "Alles sauber"),
    (1, "yellow", "1 Finding erfordert"),
    (24, "yellow", "Findings erfordern"),
    (25, "red", "Findings erfordern"),
])
def test_attention_thresholds_unchanged(tmp_path, open_findings, color, text):
    summary = {"status": 200, "body": {"open": open_findings}}
    els = _run(tmp_path, _base(**{"/api/v1/library/findings/summary": summary}))["els"]

    assert els["attention-status"]["className"] == f"card-status-start bg-{color}"
    html = els["attention-content"]["html"]
    if open_findings:
        assert f">{open_findings}</span>" in html
    assert text.split(" ", 1)[-1] in html


@needs_node
def test_attention_error_is_visible_instead_of_endless_loading(tmp_path):
    """Vorher: stiller Rückfall, die Karte blieb dauerhaft auf 'Lädt…'."""
    els = _run(tmp_path, _base(**{"/api/v1/library/findings/summary": {"status": 500}}))["els"]

    html = els["attention-content"]["html"]
    assert "Findings nicht abrufbar." in html
    assert "Erneut versuchen" in html
    assert "placeholder-glow" not in els["attention-content"]["cls"]


@needs_node
def test_recent_activity_empty_state(tmp_path):
    els = _run(tmp_path, _base())["els"]

    assert 'class="empty' in els["recent-activity-content"]["html"]
    assert "Noch keine Downloads" in els["recent-activity-content"]["html"]


@needs_node
def test_recent_activity_rows_are_escaped_with_german_status(tmp_path):
    history = {"status": 200, "body": {"entries": [
        {"status": "success", "title": "<b>Titel</b>", "artist": "A & B", "timestamp": "2026-09-28T12:00:00"},
        {"status": "failed", "title": "X", "artist": "Y", "timestamp": "2026-09-28T11:00:00"},
        {"status": "cancelled", "title": "Z", "artist": "W", "timestamp": "kaputt"},
    ]}}
    html = _run(tmp_path, _base(**{"/api/v1/downloads/history": history}))["els"]["recent-activity-content"]["html"]

    assert "&lt;b&gt;Titel&lt;/b&gt;" in html and "<b>Titel</b>" not in html
    assert "A &amp; B" in html
    assert "bg-green-lt" in html and "Fertig" in html
    assert "bg-red-lt" in html and "Fehler" in html
    assert "bg-secondary-lt" in html and "Abgebrochen" in html
    assert "table card-table" in html


@needs_node
def test_recent_activity_error_state_with_retry(tmp_path):
    els = _run(tmp_path, _base(**{"/api/v1/downloads/history": {"status": 502}}))["els"]

    assert "Verlauf nicht abrufbar." in els["recent-activity-content"]["html"]
    assert "Erneut versuchen" in els["recent-activity-content"]["html"]
    assert "card-body" in els["recent-activity-content"]["cls"]


@needs_node
@pytest.mark.parametrize("response,badge,label,hint", [
    ({"status": 200, "body": {"connected": True, "artist_count": 1500}}, "bg-green-lt", "Online", "1.500 Artists"),
    ({"status": 200, "body": {"connected": False}}, "bg-red-lt", "Offline", "Nicht erreichbar"),
    ({"status": 500}, "bg-yellow-lt", "Unbekannt", "Status nicht abrufbar."),
])
def test_navidrome_status_badges(tmp_path, response, badge, label, hint):
    els = _run(tmp_path, _base(**{"/api/v1/navidrome/status": response}))["els"]

    assert badge in els["status-navidrome-value"]["html"] and label in els["status-navidrome-value"]["html"]
    assert els["status-navidrome-hint"]["text"] == hint


@needs_node
def test_unauthenticated_shows_login_and_loads_nothing_else(tmp_path):
    out = _run(tmp_path, _base(**{"/api/v1/auth/whoami": {"status": 401}}))

    assert out["calls"] == ["/api/v1/auth/whoami"]
    assert out["els"]["login-view"]["hidden"] is False
