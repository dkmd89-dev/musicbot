# tests/test_control_center_statistics_page.py
# -*- coding: utf-8 -*-
"""
CC-UI Statistics — Seite nach docs/CONTROL_CENTER_UI_STANDARD.md:
Sprite-Icons statt Emojis, Zustände über ccState, Laden über ccApi,
Music DNA als Blickfang (Nutzerentscheidung 2026-09-28).

Entscheidungen 2026-09-28:
1. Kennzahl "Genres" zeigte die Länge von top_genres_pct - die ist auf
   top_n (Default 5) gekappt, also nie die Genre-Anzahl. Jetzt: "Top-Genre"
   (Name des meistgehörten Genres), keine API-Änderung.
2. Genres ohne Symbol (die Emoji-Zuordnung _getGenreEmoji entfällt).
3. Music DNA: Profil-Highlights, Tageszeit als 4 Kacheln mit Balken,
   Genres + Heavy Rotation nebeneinander.

Die echte static/pages/statistics.js läuft zusammen mit der echten
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
STATS_JS = CC_DIR / "static" / "pages" / "statistics.js"
STATS_HTML = CC_DIR / "templates" / "statistics.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    transport = httpx.ASGITransport(app=create_app())
    c = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

def test_statistics_has_no_emoji_inline_svg_or_old_placeholders():
    js = STATS_JS.read_text(encoding="utf-8")
    html = STATS_HTML.read_text(encoding="utf-8")
    assert not _EMOJI.search(js) and not _EMOJI.search(html)
    assert "_getGenreEmoji" not in js
    assert "<path" not in html, "Inline-SVG statt Sprite"
    assert "empty-note" not in js and "empty-note" not in html
    assert "Lädt…" not in js and "Lädt…" not in html
    for old in ("kpi-icon", "metrics-grid", "card-accent", "card-compact", "page-header-icon"):
        assert old not in html, old


@pytest.mark.asyncio
async def test_statistics_header_kpis_and_dna_hero(client):
    html = (await client.get("/statistics")).text
    assert '<div class="page-pretitle">Music</div>' in html
    assert '<use href="#i-chart"/></svg>Statistics</h2>' in html
    assert 'id="statistics-period"' in html
    # Kennzahlen mit sichtbarem Bezug
    assert 'id="kpi-plays-scope"' in html
    assert "Top-Genre" in html and 'id="kpi-genres-sub"' in html
    assert html.count("All-Time") >= 3
    # Music DNA ist Blickfang: Hero-Karte vor den Rankings
    assert 'class="card mb-3 cc-dna-hero"' in html
    assert html.index('id="music-dna-content"') < html.index('id="monthly-artists"')
    for icon in ("dna", "microphone", "repeat", "clock", "tag", "history"):
        assert f'<use href="#i-{icon}"/>' in html, icon


# ---------------------------------------------------------------------------
# statistics.js im node-Harness
# ---------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("fs");
const [commonPath, jsPath, scenarioJson] = process.argv.slice(2);
const sc = JSON.parse(scenarioJson);
const els = {};
const mkEl = (id) => {
  const listeners = {};
  return { id, hidden: false, textContent: "", innerHTML: "", className: "", style: {},
    disabled: false, value: id === "statistics-period" ? (sc.period || "month") : "", dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    setAttribute() {}, getAttribute() { return null; }, querySelector: () => null,
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    fire: (t) => (listeners[t] || []).forEach((f) => f()),
    appendChild() {}, remove() {} };
};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  createElement: () => mkEl("created"), addEventListener() {},
  documentElement: { getAttribute: () => "dark", setAttribute() {} },
  body: { appendChild() {}, classList: { toggle() {}, remove() {}, contains: () => false } },
};
global.window = {};
global.console = { ...console, error() {} };
const calls = [];
const responses = sc.responses || {};
global.fetch = async (url) => {
  calls.push(url);
  const key = url.split("?")[0];
  const r = key.endsWith("/auth/whoami")
    ? { status: 200, body: { user_id: 1, access_level: "OWNER" } }
    : (responses[key] || { status: 200, body: { has_data: false } });
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => JSON.stringify(r.body), json: async () => r.body };
};
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(jsPath, "utf-8");
new Function(src)();
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  await tick();
  if (sc.changePeriod) {
    const sel = document.getElementById("statistics-period");
    sel.value = sc.changePeriod; sel.fire("change"); await tick();
  }
  const g = (id) => document.getElementById(id);
  const out = { calls };
  for (const id of ["kpi-plays", "kpi-plays-scope", "kpi-songs", "kpi-repeat", "kpi-genres", "kpi-genres-sub",
                    "monthly-artists", "monthly-artists-period", "all-time-genres", "music-dna-content", "music-timeline"]) {
    out[id] = String(g(id).innerHTML || g(id).textContent);
  }
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})();
"""

_ME = "/api/v1/statistics/me"


def _run(tmp_path: Path, responses: dict, **extra) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(harness), str(COMMON_JS), str(STATS_JS), json.dumps({"responses": responses, **extra})],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _ok(body):
    return {"status": 200, "body": body}


_DNA = {
    "has_data": True, "navidrome_username": "robin", "total_plays": 1200, "unique_songs": 300,
    "repeat_rate_pct": 75.0,
    "top_genres_pct": [{"label": "Deutschrap", "pct": 40.0}, {"label": "Pop", "pct": 20.0}],
    "top_artists_pct": [{"label": "<Cro>", "pct": 12.5}, {"label": "Apache 207", "pct": 8.0}],
    "time_of_day_pct": {"morgens": 10.0, "nachmittags": 20.0, "abends": 50.0, "nachts": 20.0},
}
_MONTH = {"has_data": True, "navidrome_username": "robin", "period": "monat", "total_plays": 321,
          "top_artists": [{"label": "Cro", "count": 40}, {"label": "Nina Chuba", "count": 20}]}
_GENRES = {"has_data": True, "navidrome_username": "robin", "total_plays_with_genre": 900,
           "top_genres": [{"label": "Deutschrap", "count": 500}, {"label": "Pop", "count": 250}]}
_TIMELINE = {"has_data": True, "track_count": 12, "listening_seconds": 3900, "new_track_count": 2,
             "top_artist": {"label": "Cro", "count": 5}, "top_album": None,
             "top_genre": {"label": "Deutschrap", "count": 7},
             "most_replayed_track": {"label": "Easy", "count": 1}}

_FULL = {
    _ME: _ok(_MONTH), _ME + "/genres": _ok(_GENRES),
    _ME + "/music-dna": _ok(_DNA), _ME + "/timeline": _ok(_TIMELINE),
}


@needs_node
def test_kpis_show_top_genre_instead_of_capped_list_length(tmp_path):
    """Regression Entscheidung 1: vorher stand hier len(top_genres_pct) (= 2)."""
    out = _run(tmp_path, _FULL)
    assert out["kpi-plays"] == "321"
    assert out["kpi-plays-scope"] == "Monat"
    assert out["kpi-songs"] == "300"
    assert out["kpi-repeat"] == "75%"
    assert out["kpi-genres"] == "Deutschrap"
    assert out["kpi-genres-sub"] == "All-Time, 40% der Plays"


@needs_node
def test_period_change_reloads_with_period_and_updates_scope(tmp_path):
    out = _run(tmp_path, _FULL, changePeriod="week")
    assert any(c == _ME + "?period=month" for c in out["calls"])
    assert any(c == _ME + "?period=week" for c in out["calls"])
    assert out["kpi-plays-scope"] == "Woche"


@needs_node
def test_music_dna_hero_highlights_time_of_day_and_lists(tmp_path):
    html = _run(tmp_path, _FULL)["music-dna-content"]
    # Profil-Highlights
    assert "Dein Genre" in html and "Deutschrap" in html and "40% deiner Plays" in html
    assert "Heavy Rotation" in html and "&lt;Cro&gt;" in html and "<Cro>" not in html
    assert "Deine Zeit" in html and "Abends" in html and "50% deiner Plays" in html
    assert "300 Songs, 1200 Plays" in html
    # Tageszeit: 4 Kacheln, Spitze markiert, Icons statt Emojis
    assert html.count('class="cc-dna-tod') == 4
    assert html.count("cc-dna-tod-peak") == 1
    for icon in ("sunrise", "sun", "sunset", "moon"):
        assert f'href="#i-{icon}"' in html
    # Listen mit türkisen Balken, Genres ohne Symbol
    assert "bg-teal" in html
    assert "1.</span><span class=\"flex-fill text-truncate\">Deutschrap</span>" in html


@needs_node
def test_rankings_and_timeline_render(tmp_path):
    out = _run(tmp_path, _FULL)
    assert "Cro" in out["monthly-artists"] and "Nina Chuba" in out["monthly-artists"]
    assert out["monthly-artists-period"] == "Monat"
    assert "Deutschrap" in out["all-time-genres"] and "500" in out["all-time-genres"]
    tl = out["music-timeline"]
    assert "1h 5m" in tl
    assert 'href="#i-microphone"' in tl and 'href="#i-disc"' in tl and 'href="#i-heart"' in tl
    assert "1 Play<" in tl and "5 Plays" in tl


@needs_node
def test_empty_states_use_cc_state(tmp_path):
    out = _run(tmp_path, {})
    assert "Noch kein Hörprofil" in out["music-dna-content"]
    assert "Keine Wiedergaben" in out["monthly-artists"]
    assert "Keine Genre-Daten" in out["all-time-genres"]
    assert "Heute noch nichts gehört" in out["music-timeline"]
    assert 'class="empty' in out["music-dna-content"]
    assert out["kpi-genres"] == "–"


@needs_node
def test_missing_navidrome_user_is_empty_state_not_error(tmp_path):
    err = {"status": 404, "body": {"error": {"code": "NAVIDROME_USER_NOT_CONFIGURED",
                                             "message": "Für diesen Account ist kein Navidrome-Benutzer hinterlegt."}}}
    out = _run(tmp_path, {_ME: err, _ME + "/genres": err, _ME + "/music-dna": err, _ME + "/timeline": err})
    for key in ("monthly-artists", "all-time-genres", "music-dna-content", "music-timeline"):
        assert "Keine Statistik verfügbar" in out[key]
        assert "kein Navidrome-Benutzer hinterlegt" in out[key]


@needs_node
def test_server_error_shows_error_with_retry(tmp_path):
    out = _run(tmp_path, {**_FULL, _ME + "/music-dna": {"status": 500, "body": {"error": {"message": "kaputt"}}}})
    assert "text-danger" in out["music-dna-content"] and "kaputt" in out["music-dna-content"]
    assert "Erneut versuchen" in out["music-dna-content"]
    # andere Karten unberührt
    assert "Cro" in out["monthly-artists"]
