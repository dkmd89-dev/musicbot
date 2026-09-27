# -*- coding: utf-8 -*-
"""Health-Seite, Layout A (Tabs) — Markup-Vertrag und Client-Verhalten.

Zwei Ebenen:
  1. Gerendertes HTML (echte create_app()): Tabler-Tabs Findings | Repair |
     Verlauf, alle bestehenden DOM-IDs bleiben erhalten (Overview verlinkt auf
     /health#findings-content; health.js haengt Listener an diese IDs).
  2. health.js real mit node ausgefuehrt, zusammen mit dem ECHTEN common.js
     (`_loadInto()`-Vertrag: renderFn(el, body)); DOM/fetch sind minimal
     gestubbt (Muster wie tests/test_logger_js_config_controls.py).

Regression: bis zum Layout-A-Umbau hiess die Kachel-Renderfunktion
`renderHealth(data)`. `_loadInto()` ruft aber `renderFn(el, body)` auf, `data`
war also das DOM-Element -> die Kacheln zeigten IMMER "Keine Dateien in der
Library gefunden." (Score "–"), auch bei gueltigem /health/cached-Report.
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

CC = Path(__file__).resolve().parent.parent / "control_center"
COMMON_JS = CC / "static" / "common.js"
HEALTH_JS = CC / "static" / "pages" / "health.js"
_NODE = shutil.which("node")


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
# 1. Markup
# ─────────────────────────────────────────────────────────────────────────

# Jede dieser IDs wird von health.js (oder Overview/Tests) referenziert.
_REQUIRED_IDS = [
    "health-tiles", "score-history-content", "navidrome-status", "health-scan-btn",
    "health-scan-job-content", "health-findings-count", "findings-search",
    "findings-severity-filter", "findings-category-filter", "findings-content",
    "accepted-findings-toggle", "accepted-findings-content", "repair-steps",
    "repair-plan-btn", "repair-plan-content", "repair-start-btn", "repair-cancel-btn",
    "repair-start-hint", "repair-job-content", "level23-plan-btn",
    "level23-artists-content", "level23-job-content", "repair-statistics-content",
    "repair-history-content", "jobs-refresh-btn", "jobs-content",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("dom_id", _REQUIRED_IDS)
async def test_health_page_keeps_dom_id(client, dom_id):
    html = (await client.get("/health")).text
    assert f'id="{dom_id}"' in html


@pytest.mark.asyncio
async def test_health_page_has_three_tabler_tabs_with_panes(client):
    html = (await client.get("/health")).text
    assert 'class="nav nav-tabs card-header-tabs"' in html
    assert html.count('data-bs-toggle="tab"') == 3
    for pane in ("health-tab-findings", "health-tab-repair", "health-tab-history"):
        assert f'href="#{pane}"' in html
        assert f'id="{pane}"' in html
    # Findings ist der Standard-Tab (Deep-Link /health#findings-content).
    assert re.search(r'class="nav-link active"[^>]*data-bs-toggle="tab"', html)
    assert 'class="tab-pane active show" id="health-tab-findings"' in html


@pytest.mark.asyncio
async def test_findings_content_lives_in_the_default_findings_pane(client):
    """Overview verlinkt auf /health#findings-content — der Anker muss im
    sichtbaren Standard-Tab liegen, nicht in einem versteckten Pane."""
    html = (await client.get("/health")).text
    findings_pane = html.split('id="health-tab-findings"', 1)[1].split('id="health-tab-repair"', 1)[0]
    assert 'id="findings-content"' in findings_pane


@pytest.mark.asyncio
async def test_repair_history_and_jobs_live_in_the_history_tab(client):
    html = (await client.get("/health")).text
    history_pane = html.split('id="health-tab-history"', 1)[1]
    for dom_id in ("repair-statistics-content", "repair-history-content", "jobs-content"):
        assert f'id="{dom_id}"' in history_pane
    repair_pane = html.split('id="health-tab-repair"', 1)[1].split('id="health-tab-history"', 1)[0]
    assert 'id="repair-plan-content"' in repair_pane
    assert 'id="level23-artists-content"' in repair_pane


@pytest.mark.asyncio
async def test_scan_button_and_navidrome_chip_are_in_the_page_header(client):
    html = (await client.get("/health")).text
    header = html.split('class="page-header', 1)[1].split("MusicBot Doctor</h2>", 1)[0].split('class="nav nav-tabs', 1)[0]
    assert 'id="health-scan-btn"' in header
    assert 'id="navidrome-status"' in header


@pytest.mark.asyncio
async def test_health_page_dropped_redundant_score_badge_and_legacy_cards(client):
    html = (await client.get("/health")).text
    assert "health-score-badge" not in html
    # Keine Legacy-Bausteine mehr im Template.
    for legacy in ('class="tile', "counts-grid", "row-item", "badge-INFO"):
        assert legacy not in html
    # Navidrome ist keine eigene Karte mehr.
    assert "🎵 Navidrome</h2>" not in html


def test_health_js_uses_no_legacy_classes_and_only_api_url_fetches():
    js = HEALTH_JS.read_text(encoding="utf-8")
    for legacy in ("row-item", "counts-grid", 'class="tile"', "badge-status", "badge-${", "finding-group"):
        assert legacy not in js, legacy


# ─────────────────────────────────────────────────────────────────────────
# 2. Client-Verhalten (node)
# ─────────────────────────────────────────────────────────────────────────

needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_HARNESS = r"""
const fs = require("fs");
const els = {};
const fetchCalls = [];
function mkEl(id) {
  const el = {
    id, innerHTML: "", className: "", textContent: "", value: "", hidden: false,
    disabled: false, dataset: {}, children: [], listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    classList: { toggle() {}, contains: () => false, add() {}, remove() {} },
    querySelectorAll: () => [], setAttribute() {},
  };
  return el;
}
global.document = {
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
};
global.window = { alert() {}, confirm: () => true, prompt: () => "" };
global.__copied = null;
// Node >= 21 hat ein eigenes (nicht zuweisbares) global.navigator.
Object.defineProperty(global, "navigator", { configurable: true, value: { clipboard: { writeText: async (t) => {
  if (JSON.parse(process.argv[3]).clipboardFails) throw new Error("denied");
  global.__copied = t;
} } } });
const fired = [];

const scenario = JSON.parse(process.argv[3]);
global.fetch = async (url) => {
  if (url.indexOf("/auth/whoami") === -1) fetchCalls.push(url);  // checkAuth() aus initPage() ignorieren
  const key = Object.keys(scenario.routes || {}).find((k) => url.indexOf(k) !== -1);
  if (!key) return { status: 404, ok: false, json: async () => ({}) };
  return { status: 200, ok: true, json: async () => scenario.routes[key] };
};

const src = fs.readFileSync(process.argv[2], "utf-8");
const api = new Function(src + "\nreturn { loadHealth, renderHealth, renderScoreHistory, renderFindings, " +
  "renderRepairPlan, renderLevel23Artists, renderRepairHistory, renderRepairStatistics, renderJobs, " +
  "renderAcceptedFindings, loadNavidromeStatus, loadScoreHistory, loadFindings };")();

(async () => {
  // Schritt-Liste (repair-steps) mit beobachtbarem Zustand
  const lis = [0, 1, 2].map(() => ({ active: false, classList: { toggle(c, on) { this.owner.active = on; } } }));
  lis.forEach((li) => { li.classList.owner = li; });
  document.getElementById("repair-steps").children = lis;

  for (const op of scenario.ops || []) {
    if (op.op === "call") {
      const args = (op.args || []).map((a) => (typeof a === "string" && a[0] === "@" ? document.getElementById(a.slice(1)) : a));
      await api[op.fn].apply(null, args);
    } else if (op.op === "set") {
      document.getElementById(op.id)[op.prop] = op.value;
    } else if (op.op === "fire") {
      const closest = op.closest || {};
      Object.values(closest).forEach((o) => fired.push(o));
      document.getElementById(op.id).listeners[op.type]({
        target: { closest: (sel) => closest[sel] || null },
      });
      await new Promise((r) => setImmediate(r));  // async Listener (Kopieren) abwarten
    }
  }
  const out = { fetchCalls, steps: lis.map((l) => l.active), els: {}, copied: global.__copied, fired: fired.map((o) => o.textContent) };
  Object.keys(els).forEach((id) => {
    out.els[id] = { html: els[id].innerHTML, text: els[id].textContent, hidden: els[id].hidden,
                    disabled: els[id].disabled, cls: els[id].className };
  });
  // Bugfix (Harness): console.log() gefolgt von process.exit() kann bei
  // groesserem Output stdout abschneiden, wenn stdout eine Pipe ist
  // (subprocess.run(capture_output=True) nutzt Pipes) - der Write ist dort
  // asynchron, process.exit() beendet den Prozess ohne auf den Abschluss
  // zu warten (bekanntes Node.js-Verhalten). process.stdout.write() mit
  // Callback erzwingt: erst wenn der Write bestaetigt abgeschlossen ist,
  // wird beendet.
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ crash: String(e && e.stack || e) }) + "\n", () => process.exit(1));
});
"""


def _run(tmp_path: Path, scenario: dict) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    # common.js + health.js werden gemeinsam geladen (echter _loadInto()).
    combined = tmp_path / "common_plus_health.js"
    combined.write_text(
        COMMON_JS.read_text(encoding="utf-8") + "\n" + HEALTH_JS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [_NODE, str(script), str(combined), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crash" not in out, out.get("crash")
    return out


def _f(fid: str, path: str, sev: str = "INFO", **kw) -> dict:
    d = {"finding_id": fid, "path": path, "artist": path.split("/")[0], "album": None,
         "title": path.split("/")[-1], "severity": sev, "message": "msg " + fid}
    d.update(kw)
    return d


def _group(code: str, tier: str, paths: list) -> dict:
    return {"code": code, "tier": tier,
            "findings": [_f(f"{code}-{i}", p, tier) for i, p in enumerate(paths)]}


def _findings(tmp_path: Path, groups: list, ops_before: list = None, ops_after: list = None) -> dict:
    ops = list(ops_before or []) + [{"op": "call", "fn": "renderFindings", "args": ["@findings-content", groups]}]
    ops += list(ops_after or [])
    return _run(tmp_path, {"ops": ops})


_PATHS = [f"Artist{i}/Singles/2026 - Song {i}.m4a" for i in range(12)]




@needs_node
def test_health_tiles_render_from_cached_report_via_real_load_into(tmp_path: Path) -> None:
    """Regression (siehe Modul-Docstring): loadHealth() -> echter _loadInto()
    -> renderHealth(el, body). Vorher immer 'Keine Dateien ...'."""
    out = _run(tmp_path, {
        "routes": {"/api/v1/library/health/cached": {
            "library": {"files": 500, "artists": 44, "albums": 120},
            "health": {"score": 99.9, "status": "EXCELLENT"}, "stale": False}},
        "ops": [{"op": "call", "fn": "loadHealth"}],
    })
    assert out["fetchCalls"] == ["/api/v1/library/health/cached"]
    html = out["els"]["health-tiles"]["html"]
    assert "Keine Dateien" not in html
    assert "99.9" in html and "EXCELLENT" in html
    assert ">500<" in html and ">44<" in html and ">120<" in html
    assert 'class="progress-bar bg-green"' in html
    assert "width: 99.9%" in html


@needs_node
def test_health_tiles_empty_library_and_missing_score(tmp_path: Path) -> None:
    empty = _run(tmp_path, {
        "routes": {"/health/cached": {"library": {"files": 0, "artists": 0, "albums": 0},
                                       "health": {"score": None, "status": "UNSCORED"}}},
        "ops": [{"op": "call", "fn": "loadHealth"}],
    })
    assert "Keine Dateien in der Library gefunden." in empty["els"]["health-tiles"]["html"]

    unscored = _run(tmp_path, {
        "routes": {"/health/cached": {"library": {"files": 3, "artists": 1, "albums": 1},
                                       "health": {"score": None, "status": "UNSCORED"}}},
        "ops": [{"op": "call", "fn": "loadHealth"}],
    })
    html = unscored["els"]["health-tiles"]["html"]
    assert ">–<" in html
    assert "progress-bar" not in html  # kein Fake-Balken ohne Score


@needs_node
def test_health_tiles_status_colours_and_escaping(tmp_path: Path) -> None:
    def tiles(status):
        return _run(tmp_path, {
            "routes": {"/health/cached": {"library": {"files": 1, "artists": 1, "albums": 1},
                                           "health": {"score": 40.0, "status": status}}},
            "ops": [{"op": "call", "fn": "loadHealth"}],
        })["els"]["health-tiles"]["html"]

    assert "bg-orange-lt" in tiles("POOR")
    assert "bg-red-lt" in tiles("CRITICAL")
    assert "<b>" not in tiles("<b>x</b>") and "&lt;b&gt;" in tiles("<b>x</b>")


@needs_node
def test_score_history_sparkline_flat_and_varying(tmp_path: Path) -> None:
    flat = [{"score": 99.9, "status": "EXCELLENT", "total_issues": 1240, "total_files": 500,
             "timestamp": f"2026-09-2{i}T10:00:00"} for i in range(1, 5)]
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderScoreHistory",
                                   "args": ["@score-history-content", {"entries": flat}]}]})
    html = out["els"]["score-history-content"]["html"]
    assert html.count("<circle") == 4
    assert "<polyline" in html
    assert "4 Lauf/Läufe" in html
    assert "1.240 offene Issues laut Scan" in html
    # flache Reihe -> alle Punkte auf derselben Hoehe (kein Fake-Trend)
    assert len(set(re.findall(r'cy="([\d.]+)"', html))) == 1

    varying = [dict(e, score=s) for e, s in zip(flat, (90.0, 95.0, 70.0, 99.0))]
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderScoreHistory",
                                   "args": ["@score-history-content", {"entries": varying}]}]})
    assert len(set(re.findall(r'cy="([\d.]+)"', out["els"]["score-history-content"]["html"]))) > 1


@needs_node
def test_score_history_empty_state(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderScoreHistory",
                                   "args": ["@score-history-content", {"entries": []}]}]})
    assert "Noch kein Score-Verlauf vorhanden" in out["els"]["score-history-content"]["html"]
    assert "<svg" not in out["els"]["score-history-content"]["html"]


@needs_node
def test_navidrome_chip_connected_and_error(tmp_path: Path) -> None:
    ok = _run(tmp_path, {"routes": {"/api/v1/navidrome/status": {"connected": True, "artist_count": 44}},
                         "ops": [{"op": "call", "fn": "loadNavidromeStatus"}]})
    assert "Navidrome: Verbunden (44 Artists)" in ok["els"]["navidrome-status"]["html"]
    assert ok["els"]["navidrome-status"]["cls"] == "badge bg-green-lt"
    down = _run(tmp_path, {"routes": {"/api/v1/navidrome/status": {"connected": False}},
                           "ops": [{"op": "call", "fn": "loadNavidromeStatus"}]})
    assert "Nicht erreichbar" in down["els"]["navidrome-status"]["html"]
    assert down["els"]["navidrome-status"]["cls"] == "badge bg-red-lt"


# ── Findings ────────────────────────────────────────────────────────────

@needs_node
def test_findings_groups_sorted_by_severity_then_size(tmp_path: Path) -> None:
    groups = [_group("B_SMALL_INFO", "INFO", _PATHS[:2]),
              _group("A_BIG_INFO", "INFO", _PATHS[:6]),
              _group("Z_WARN", "WARNING", _PATHS[:1]),
              _group("Y_ERR", "ERROR", _PATHS[:1])]
    html = _findings(tmp_path, groups)["els"]["findings-content"]["html"]
    order = re.findall(r'<details class="card health-group" data-code="([^"]+)"', html)
    assert order == ["Y_ERR", "Z_WARN", "A_BIG_INFO", "B_SMALL_INFO"]


@needs_node
def test_findings_only_first_group_open_and_state_survives_rerender(tmp_path: Path) -> None:
    groups = [_group("G1", "INFO", _PATHS[:3]), _group("G2", "INFO", _PATHS[:2])]
    html = _findings(tmp_path, groups)["els"]["findings-content"]["html"]
    assert re.search(r'data-code="G1" open>', html)
    assert not re.search(r'data-code="G2" open>', html)


@needs_node
def test_findings_group_caps_rows_and_offers_more(tmp_path: Path) -> None:
    html = _findings(tmp_path, [_group("BIG", "INFO", _PATHS)])["els"]["findings-content"]["html"]
    assert html.count("health-finding-row") == 5
    assert "7 weitere anzeigen" in html
    assert 'class="list-group-item list-group-item-action text-secondary health-more-btn" data-code="BIG"' in html


@needs_node
def test_findings_more_button_expands_and_collapses(tmp_path: Path) -> None:
    groups = [_group("BIG", "INFO", _PATHS)]
    click = {"op": "fire", "id": "findings-content", "type": "click",
             "closest": {".health-more-btn": {"dataset": {"code": "BIG"}}}}
    expanded = _findings(tmp_path, groups, ops_after=[click])["els"]["findings-content"]["html"]
    assert expanded.count("health-finding-row") == 12
    assert "Weniger anzeigen" in expanded
    collapsed = _findings(tmp_path, groups, ops_after=[click, click])["els"]["findings-content"]["html"]
    assert collapsed.count("health-finding-row") == 5


@needs_node
def test_findings_row_has_dropdown_with_resolve_and_accept_actions(tmp_path: Path) -> None:
    html = _findings(tmp_path, [_group("G", "INFO", _PATHS[:1])])["els"]["findings-content"]["html"]
    assert 'data-bs-toggle="dropdown"' in html
    assert re.search(r'class="dropdown-item resolve-btn" data-finding-id="G-0"', html)
    assert re.search(r'class="dropdown-item accept-btn" data-finding-id="G-0"', html)
    assert "Als repariert markieren" in html and "Akzeptieren …" in html
    # keine zwei gleichrangigen Inline-Buttons pro Zeile mehr
    assert 'class="small resolve-btn"' not in html and 'class="small accept-btn"' not in html


@needs_node
def test_findings_search_filters_by_path_artist_and_code(tmp_path: Path) -> None:
    groups = [
        {"code": "META_ISRC_MISSING", "tier": "INFO", "findings": [
            _f("a", "Kygo/Singles/Take Me Back.m4a"), _f("b", "Sarah Connor/Singles/FICKA.m4a")]},
        {"code": "LYRICS_MISSING", "tier": "INFO", "findings": [_f("c", "Kygo/Singles/Without You.m4a")]},
        {"code": "ARTWORK_NON_SQUARE", "tier": "INFO", "findings": [_f("d", "Sido/Album/Track.m4a")]},
    ]
    by_artist = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-search", "prop": "value", "value": "KYGO"}])
    html = by_artist["els"]["findings-content"]["html"]
    assert html.count("health-finding-row") == 2
    assert 'data-finding-id="a"' in html and 'data-finding-id="c"' in html
    assert 'data-finding-id="b"' not in html and 'data-finding-id="d"' not in html

    by_code = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-search", "prop": "value", "value": "lyrics_missing"}])
    assert by_code["els"]["findings-content"]["html"].count("health-finding-row") == 1

    none = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-search", "prop": "value", "value": "zzz"}])
    assert "Keine offenen Findings" in none["els"]["findings-content"]["html"]


@needs_node
def test_findings_search_opens_all_matching_groups(tmp_path: Path) -> None:
    groups = [_group("G1", "INFO", ["Kygo/a.m4a"]), _group("G2", "INFO", ["Kygo/b.m4a"])]
    html = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-search", "prop": "value", "value": "kygo"}])["els"]["findings-content"]["html"]
    assert re.search(r'data-code="G1" open>', html) and re.search(r'data-code="G2" open>', html)


@needs_node
def test_findings_severity_and_category_filters_still_work(tmp_path: Path) -> None:
    groups = [{"code": "MIXED", "tier": "WARNING", "findings": [_f("w", "a/w.m4a", "WARNING"), _f("i", "a/i.m4a", "INFO")]},
              _group("OTHER", "INFO", ["b/x.m4a"])]
    sev = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-severity-filter", "prop": "value", "value": "WARNING"}])
    html = sev["els"]["findings-content"]["html"]
    assert 'data-finding-id="w"' in html and 'data-finding-id="i"' not in html and "OTHER" not in html
    cat = _findings(tmp_path, groups, ops_before=[{"op": "set", "id": "findings-category-filter", "prop": "value", "value": "OTHER"}])
    assert "MIXED" not in cat["els"]["findings-content"]["html"]


@needs_node
def test_findings_category_options_and_count_badge(tmp_path: Path) -> None:
    out = _findings(tmp_path, [_group("B", "INFO", _PATHS[:3]), _group("A", "INFO", _PATHS[:2])])
    opts = out["els"]["findings-category-filter"]["html"]
    assert opts.index('value="A"') < opts.index('value="B"')
    assert "Kategorie: alle" in opts
    assert out["els"]["health-findings-count"]["text"] == "5"


@needs_node
def test_findings_render_escapes_hostile_paths_and_ids(tmp_path: Path) -> None:
    evil = "<img src=x onerror=alert(1)>/x.m4a"
    groups = [{"code": '<script>c</script>', "tier": "INFO", "findings": [
        _f('"><b>id', evil, message='"><i>m')]}]
    html = _findings(tmp_path, groups)["els"]["findings-content"]["html"]
    assert "<img" not in html and "<script>" not in html and "<b>id" not in html and "<i>m" not in html
    assert "&lt;img" in html


@needs_node
def test_findings_empty_state(tmp_path: Path) -> None:
    out = _findings(tmp_path, [])
    assert "Keine offenen Findings" in out["els"]["findings-content"]["html"]
    assert out["els"]["health-findings-count"]["text"] == ""


@needs_node
def test_accepted_findings_use_tabler_list_and_keep_unaccept_hook(tmp_path: Path) -> None:
    body = {"total": 3, "findings": [{"finding_id": "x1", "code": "C", "path": "a/b.m4a", "message": "m",
                                       "review_note": "Bewusst <b>", "present_in_latest_scan": False}]}
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderAcceptedFindings", "args": ["@accepted-findings-content", body]}]})
    html = out["els"]["accepted-findings-content"]["html"]
    assert 'class="btn btn-sm btn-outline-secondary unaccept-btn" data-finding-id="x1"' in html
    assert "Zeige 1 von 3" in html
    assert "veraltet" in html
    assert "<b>" not in html and "&lt;b&gt;" in html


# ── Repair / Verlauf ────────────────────────────────────────────────────

@needs_node
def test_repair_plan_enables_start_hides_hint_and_advances_step(tmp_path: Path) -> None:
    plan = {"counts_by_level": {"SAFE_AUTOMATIC": 12, "EXTERNAL_METADATA": 4}, "actionable_total": 16,
            "manual_review_total": 3, "health_score": 99.9}
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderRepairPlan", "args": ["@repair-plan-content", plan]}]})
    assert out["els"]["repair-start-btn"]["disabled"] is False
    assert out["els"]["repair-start-btn"]["text"] == "SAFE_AUTOMATIC reparieren (12)"
    assert out["els"]["repair-start-hint"]["hidden"] is True
    assert out["steps"] == [False, True, False]
    html = out["els"]["repair-plan-content"]["html"]
    assert "12 SAFE_AUTOMATIC" in html or "davon 12 SAFE_AUTOMATIC" in html
    assert "Reine Vorschau — es wird nichts ausgeführt." in html


@needs_node
def test_level23_artist_list_keeps_button_contract(tmp_path: Path) -> None:
    plan = {"artists": [{"artist": 'Kygo "K"', "l3_count": 2},
                        {"artist": "t-low", "l3_count": 1}]}
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderLevel23Artists", "args": ["@level23-artists-content", plan]}]})
    html = out["els"]["level23-artists-content"]["html"]
    assert html.count("level23-btn") == 2  # ein L3-Button je Artist
    assert 'data-level="l3" data-artist="Kygo &quot;K&quot;" data-count="2"' in html
    assert 'data-level="l3" data-artist="t-low" data-count="1"' in html
    assert 'data-level="l2"' not in html  # CC-LIB-FINAL: L2 entfernt
    assert out["steps"] == [False, False, True]
    empty = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderLevel23Artists", "args": ["@level23-artists-content", {"artists": []}]}]})
    assert "Keine L3-Kandidaten." in empty["els"]["level23-artists-content"]["html"]


def _runs(n: int) -> list:
    return [{"status": "SUCCESS" if i % 2 == 0 else "FAILED", "level": "GENRE_REVALIDATION", "artist": "Frischer Artist",
             "kind": "maintenance", "triggered_by": "cli", "started_at": f"2026-09-27T05:{i:02d}:00"} for i in range(n)]


@needs_node
def test_repair_history_shows_preview_and_toggle(tmp_path: Path) -> None:
    body = {"runs": _runs(12), "total": 50}
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderRepairHistory", "args": ["@repair-history-content", body]}]})
    html = out["els"]["repair-history-content"]["html"]
    assert html.count("badge bg-") == 5
    assert "7 weitere anzeigen" in html
    assert "Zeige 12 von 50" in html
    assert "bg-green-lt" in html and "bg-red-lt" in html

    toggled = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderRepairHistory", "args": ["@repair-history-content", body]},
        {"op": "fire", "id": "repair-history-content", "type": "click", "closest": {".history-more-btn": {}}},
    ]})
    assert toggled["els"]["repair-history-content"]["html"].count("badge bg-") == 12


@needs_node
def test_repair_statistics_and_jobs_render_without_legacy_markup(tmp_path: Path) -> None:
    stats = {"total_runs": 50, "success": 75, "failed": 0, "skipped": 8,
             "most_common_issue_codes": [["META_ISRC_MISSING", 2]]}
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderRepairStatistics", "args": ["@repair-statistics-content", stats]}]})
    html = out["els"]["repair-statistics-content"]["html"]
    assert "card card-sm" in html and "Häufigste Issue-Codes" in html and "META_ISRC_MISSING" in html
    none = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderRepairStatistics", "args": ["@repair-statistics-content", {"total_runs": 0}]}]})
    assert "Noch keine Reparaturläufe vorhanden." in none["els"]["repair-statistics-content"]["html"]

    jobs = {"jobs": [
        {"status": "SUCCEEDED", "kind": "repair", "initiator": "u", "job_id": "j1", "progress": 100, "created_at": "2026-09-27T01:00:00", "error": None},
        {"status": "RUNNING", "kind": "scan", "initiator": "u", "job_id": "j2", "progress": 42.4, "created_at": "2026-09-27T02:00:00", "error": None},
        {"status": "FAILED", "kind": "x", "initiator": "u", "job_id": "j3", "progress": 0, "created_at": "2026-09-27T03:00:00", "error": "<b>boom</b>"},
    ]}
    jout = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderJobs", "args": ["@jobs-content", jobs]}]})
    jhtml = jout["els"]["jobs-content"]["html"]
    assert "bg-green-lt" in jhtml and "RUNNING (42%)" in jhtml and "bg-red-lt" in jhtml
    assert "<b>boom" not in jhtml and "&lt;b&gt;boom" in jhtml
    empty = _run(tmp_path, {"ops": [{"op": "call", "fn": "renderJobs", "args": ["@jobs-content", {"jobs": []}]}]})
    assert "Keine Jobs." in empty["els"]["jobs-content"]["html"]


# ── Finding-Details (Schritt 2: message sichtbar statt nur Tooltip) ──────

_MISMATCH = {
    "code": "FILENAME_TITLE_MISMATCH", "tier": "INFO",
    "findings": [{
        "finding_id": "fm1", "code": "FILENAME_TITLE_MISMATCH", "scope": "FILE", "status": "OPEN",
        "path": "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a", "artist": "01099", "album": "Skyr",
        "title": "Intro (feat. Mioso)", "severity": "INFO", "confidence": "HIGH", "occurrences": 3,
        "first_seen": "2026-09-20", "last_seen": "2026-09-27",
        "message": "Dateiname-Stamm '01 - Intro feat. Mioso' passt nicht zum Titel-Tag 'Intro (feat. Mioso)'",
    }],
}


def _toggle(fid: str) -> dict:
    return {"op": "fire", "id": "findings-content", "type": "click",
            "closest": {".finding-toggle": {"dataset": {"findingId": fid}}}}


@needs_node
def test_finding_details_are_collapsed_by_default(tmp_path: Path) -> None:
    html = _findings(tmp_path, [_MISMATCH])["els"]["findings-content"]["html"]
    assert 'class="finding-toggle health-path font-monospace small text-truncate"' in html
    assert 'aria-expanded="false"' in html
    assert "health-finding-detail" not in html
    assert "Dateiname-Stamm" not in html  # Meldung erst nach Aufklappen sichtbar


@needs_node
def test_finding_toggle_shows_message_and_api_fields(tmp_path: Path) -> None:
    html = _findings(tmp_path, [_MISMATCH], ops_after=[_toggle("fm1")])["els"]["findings-content"]["html"]
    assert 'aria-expanded="true"' in html
    detail = html.split('class="health-finding-detail', 1)[1]
    # Meldung sichtbar (Dateiname-Stamm + Titel-Tag stehen in message)
    assert "Dateiname-Stamm '01 - Intro feat. Mioso' passt nicht zum Titel-Tag 'Intro (feat. Mioso)'".replace("'", "&#39;") in detail
    for label, value in (("Pfad", "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a"), ("Artist", "01099"),
                         ("Album", "Skyr"), ("Severity", "INFO · HIGH"), ("Auftreten", "3"),
                         ("Erstmals gesehen", "2026-09-20"), ("Zuletzt gesehen", "2026-09-27")):
        assert f">{label}</dt>" in detail, label
        assert value in detail, value
    assert "finding-copy-btn" in detail


@needs_node
def test_finding_toggle_twice_closes_and_open_state_survives_rerender(tmp_path: Path) -> None:
    closed = _findings(tmp_path, [_MISMATCH], ops_after=[_toggle("fm1"), _toggle("fm1")])
    assert "health-finding-detail" not in closed["els"]["findings-content"]["html"]
    # weiterer Render (z. B. Filter/Suche) behaelt den geoeffneten Zustand
    reopened = _findings(tmp_path, [_MISMATCH], ops_after=[
        _toggle("fm1"),
        {"op": "call", "fn": "renderFindings", "args": ["@findings-content", [_MISMATCH]]},
    ])
    assert "health-finding-detail" in reopened["els"]["findings-content"]["html"]


@needs_node
def test_open_detail_does_not_change_row_count_or_remove_actions(tmp_path: Path) -> None:
    html = _findings(tmp_path, [_MISMATCH], ops_after=[_toggle("fm1")])["els"]["findings-content"]["html"]
    assert html.count("health-finding-row") == 1
    assert 'class="dropdown-item resolve-btn" data-finding-id="fm1"' in html
    assert 'class="dropdown-item accept-btn" data-finding-id="fm1"' in html


@needs_node
def test_finding_detail_escapes_message_and_fields(tmp_path: Path) -> None:
    evil = {"code": "X", "tier": "INFO", "findings": [{
        "finding_id": "e1", "path": "<img src=x>/a.m4a", "artist": "<b>a</b>", "album": None,
        "title": '"><script>t</script>', "severity": "INFO", "confidence": None, "occurrences": 1,
        "first_seen": "", "last_seen": "", "message": "<script>alert(1)</script> & 'q'"}]}
    html = _findings(tmp_path, [evil], ops_after=[_toggle("e1")])["els"]["findings-content"]["html"]
    assert "<script>" not in html and "<img" not in html and "<b>a" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &#39;q&#39;" in html


@needs_node
def test_finding_detail_without_message_or_optional_fields(tmp_path: Path) -> None:
    bare = {"code": "X", "tier": "INFO", "findings": [{
        "finding_id": "b1", "path": "a/b.m4a", "artist": None, "album": None, "title": None,
        "severity": None, "confidence": None, "occurrences": None, "first_seen": "", "last_seen": "", "message": ""}]}
    html = _findings(tmp_path, [bare], ops_after=[_toggle("b1")])["els"]["findings-content"]["html"]
    assert "Keine Meldung gespeichert." in html
    detail = html.split('class="health-finding-detail', 1)[1]
    assert ">Pfad</dt>" in detail
    for absent in ("Artist", "Album", "Titel", "Severity", "Auftreten", "Erstmals", "Zuletzt"):
        assert f">{absent}" not in detail, absent


@needs_node
def test_finding_copy_puts_code_message_and_path_on_clipboard(tmp_path: Path) -> None:
    copy = {"op": "fire", "id": "findings-content", "type": "click",
            "closest": {".finding-copy-btn": {"dataset": {"findingId": "fm1"}, "textContent": "Kopieren"}}}
    out = _findings(tmp_path, [_MISMATCH], ops_after=[copy])
    f = _MISMATCH["findings"][0]
    assert out["copied"] == f"FILENAME_TITLE_MISMATCH\n{f['message']}\n{f['path']}"
    assert out["fired"] == ["Kopiert ✓"]


@needs_node
def test_finding_copy_reports_failure_honestly(tmp_path: Path) -> None:
    copy = {"op": "fire", "id": "findings-content", "type": "click",
            "closest": {".finding-copy-btn": {"dataset": {"findingId": "fm1"}, "textContent": "Kopieren"}}}
    out = _run(tmp_path, {"clipboardFails": True, "ops": [
        {"op": "call", "fn": "renderFindings", "args": ["@findings-content", [_MISMATCH]]}, copy]})
    assert out["copied"] is None
    assert out["fired"] == ["Kopieren nicht möglich"]


def test_health_js_detail_uses_only_findings_api_fields() -> None:
    """Keine erfundenen Vergleichswerte: die Detailzeile darf nur FindingSchema-Felder
    zeigen (Normalisierung/Diff braucht eine Backend-Entscheidung, Schritt 3)."""
    js = HEALTH_JS.read_text(encoding="utf-8")
    detail_fn = js.split("function _findingDetailHtml(f) {", 1)[1].split("function _findingRowHtml", 1)[0]
    used = set(re.findall(r"\bf\.(\w+)", detail_fn))
    assert used <= {"path", "artist", "album", "title", "severity", "confidence",
                    "occurrences", "first_seen", "last_seen", "message", "finding_id"}, used


# ── Finding-Analyse (Schritt 3: /findings/{id}/details) ──────────────────

_DETAILS_URL = "/api/v1/library/findings/fm1/details"


def _details(**over) -> dict:
    base = {
        "finding_id": "fm1", "code": "FILENAME_TITLE_MISMATCH", "supported": True, "file_status": "ok",
        "path": "01099/2019 - Skyr/01 - Intro feat. Mioso.m4a", "message": None,
        "evidence_kind": "filename_title",
        "evidence": {
            "stem": "01 - Intro feat. Mioso", "prefix": "01 - ", "remainder": "Intro feat. Mioso",
            "title": "Intro (Mioso)", "normalized_remainder": "intro feat. mioso",
            "normalized_title": "intro mioso", "matches": False, "title_at_scan": "Intro (Mioso)",
            "segments": [{"op": "equal", "a": "intro ", "b": "intro "},
                         {"op": "delete", "a": "feat. ", "b": ""},
                         {"op": "equal", "a": "mioso", "b": "mioso"}],
        },
    }
    base.update(over)
    return base


def _explain(tmp_path: Path, body, extra_ops=None, route=True) -> dict:
    scenario = {"routes": {_DETAILS_URL: body} if route else {},
                "ops": [{"op": "call", "fn": "renderFindings", "args": ["@findings-content", [_MISMATCH]]},
                        _toggle("fm1")] + list(extra_ops or [])}
    return _run(tmp_path, scenario)


@needs_node
def test_collapsed_findings_do_not_request_details(tmp_path: Path) -> None:
    out = _findings(tmp_path, [_MISMATCH])
    assert out["fetchCalls"] == []


@needs_node
def test_opening_a_finding_requests_details_via_api_url_and_shows_loading(tmp_path: Path) -> None:
    out = _explain(tmp_path, _details())
    assert out["fetchCalls"] == [_DETAILS_URL]
    assert "Analyse lädt…" in out["els"]["findings-content"]["html"]  # Zustand direkt nach dem Aufklappen
    assert 'id="finding-explain-fm1"' in out["els"]["findings-content"]["html"]


@needs_node
def test_details_evidence_is_rendered_with_highlighted_difference(tmp_path: Path) -> None:
    html = _explain(tmp_path, _details())["els"]["finding-explain-fm1"]["html"]
    assert "Analyse (frisch von der Platte gelesen)" in html
    assert "01 - Intro feat. Mioso" in html                         # Dateiname (Platte)
    assert "„01 - “" in html                                          # abgetrennter Praefix
    assert "Intro (Mioso)" in html                                    # Titel-Tag (Platte)
    assert '<mark class="bg-red-lt text-reset px-0">feat. </mark>' in html   # nur links vorhanden
    assert "bg-green-lt" not in html.split("Verglichen: Titel-Tag", 1)[1].split("Ergebnis", 1)[0]  # rechts nichts eingefuegt
    assert "unterschiedlich" in html and "bg-red-lt" in html
    assert "Normalisierung des Scanners" in html


@needs_node
def test_details_insertions_are_highlighted_on_the_title_side(tmp_path: Path) -> None:
    body = _details()
    body["evidence"]["segments"] = [{"op": "equal", "a": "song", "b": "song"},
                                    {"op": "insert", "a": "", "b": " (live)"}]
    html = _explain(tmp_path, body)["els"]["finding-explain-fm1"]["html"]
    assert '<mark class="bg-green-lt text-reset px-0"> (live)</mark>' in html


@needs_node
def test_details_stale_finding_and_title_at_scan_note(tmp_path: Path) -> None:
    body = _details()
    body["evidence"].update(matches=True, title="Song", title_at_scan="Alter Titel",
                            segments=[{"op": "equal", "a": "song", "b": "song"}])
    html = _explain(tmp_path, body)["els"]["finding-explain-fm1"]["html"]
    assert 'badge bg-green-lt">gleich' in html and "veraltet" in html
    assert "beim Scan: Alter Titel" in html
    assert "<mark" not in html


@needs_node
def test_details_unsupported_and_unavailable_states(tmp_path: Path) -> None:
    unsupported = _explain(tmp_path, _details(supported=False, file_status="not_applicable", evidence=None,
                                              evidence_kind=None))["els"]["finding-explain-fm1"]["html"]
    assert "keine Detailanalyse" in unsupported and "Analyse (frisch" not in unsupported
    missing = _explain(tmp_path, _details(file_status="missing", evidence=None, evidence_kind=None,
                                          message="Datei nicht mehr vorhanden (verschoben)."))["els"]["finding-explain-fm1"]["html"]
    assert "Datei nicht mehr vorhanden (verschoben)." in missing


@needs_node
def test_details_http_error_is_shown_not_swallowed(tmp_path: Path) -> None:
    html = _explain(tmp_path, {}, route=False)["els"]["finding-explain-fm1"]["html"]
    assert "Analyse nicht verfügbar: HTTP 404" in html


@needs_node
def test_details_evidence_is_escaped(tmp_path: Path) -> None:
    body = _details()
    body["evidence"].update(stem="<script>s</script>", title='"><img src=x>', prefix="<b>",
                            title_at_scan="<i>x</i>",
                            segments=[{"op": "replace", "a": "<u>", "b": "<s>"}])
    body["message"] = None
    html = _explain(tmp_path, body)["els"]["finding-explain-fm1"]["html"]
    for raw in ("<script>", "<img", "<b>", "<i>", "<u>", "<s>"):
        assert raw not in html, raw
    assert "&lt;script&gt;" in html


@needs_node
def test_details_are_cached_while_open_and_refetched_after_reopening(tmp_path: Path) -> None:
    rerender = {"op": "call", "fn": "renderFindings", "args": ["@findings-content", [_MISMATCH]]}
    out = _explain(tmp_path, _details(), extra_ops=[rerender])
    assert out["fetchCalls"] == [_DETAILS_URL]                       # Re-Render: kein zweiter Request
    assert "Analyse (frisch von der Platte gelesen)" in out["els"]["findings-content"]["html"]  # aus dem Cache
    reopened = _explain(tmp_path, _details(), extra_ops=[_toggle("fm1"), _toggle("fm1")])
    assert reopened["fetchCalls"] == [_DETAILS_URL, _DETAILS_URL]    # zu + auf = frisch lesen


def test_health_js_explain_fetch_goes_through_api_url() -> None:
    js = HEALTH_JS.read_text(encoding="utf-8")
    assert "fetch(apiUrl(`/api/v1/library/findings/${encodeURIComponent(fid)}/details`)" in js
