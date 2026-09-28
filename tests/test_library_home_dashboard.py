# -*- coding: utf-8 -*-
"""Library-Home-Dashboard (Phase E, CC-LIB-FINAL) — echtes JS-Verhalten.

Deckt die in dieser Phase geänderten/neuen Funktionen ab, mit dem echten
`library.html`-Inline-Skript + dem echten `common.js` zusammen unter Node
ausgeführt (`_loadInto()`-Vertrag, identisches Muster wie
tests/test_health_page_layout_a.py — DOM/fetch minimal gestubbt):

  - `_renderLibraryHealthSnapshot()` — Score/Status/Progress-Bar nutzen
    jetzt denselben `_HEALTH_STATUS_COLOR`-Vertrag wie health.js (seit
    dieser Phase in common.js, zusammen mit `_sparklineSvg()`), und lösen
    zusätzlich `loadLibraryHealthSparkline()` aus (eigener, isolierter
    Request gegen GET .../health/score-history).
  - `_renderLibraryAttention()` — verschlankt auf eine Warnings-Kennzahl;
    ein vorhandener Errors-Wert wird NIE verschwiegen (P0, CLAUDE.md
    Abschnitt 23), nur der haeufige 0-Errors-Fall zeigt keine eigene
    Zeile mehr. Top-Warnungen von 5 auf 2 verkuerzt.
  - Artists-Tabelle: progressive Anzeige (`_ARTISTS_PAGE_SIZE`,
    "Weitere laden") statt einer einzigen langen Liste; Health-Spalte
    zeigt einen Punkt (`.dot-ok/.dot-warn/.dot-error`, dieselbe Konvention
    wie die Repair-History) statt Pille+Symbol.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CC = Path(__file__).resolve().parent.parent / "control_center"
COMMON_JS = CC / "static" / "common.js"
# CC-UI L1: Inline-Skript byte-identisch nach static/pages/ verschoben (U1).
LIBRARY_JS = CC / "static" / "pages" / "library.js"
_NODE = shutil.which("node")

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
    // Minimaler Stub: library.html's _renderArtistsOverviewList() ruft
    // el.querySelector("table") -> ?.querySelector("tbody") auf, um
    // Klick-/Tastatur-Listener an die Zeilen zu haengen. Fuer diese Tests
    // (Fokus: Pagination-/Health-/Attention-Logik) genuegt ein generisches
    // Kettenglied, das nicht abstuerzt - die reale Zeilen-Klick-Navigation
    // ist unveraendert und nicht Teil dieser Aenderung.
    querySelector: () => mkEl("_sub"), querySelectorAll: () => [], setAttribute() {},
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

const scenario = JSON.parse(process.argv[3]);
global.fetch = async (url) => {
  if (url.indexOf("/auth/whoami") === -1) fetchCalls.push(url);
  const key = Object.keys(scenario.routes || {}).find((k) => url.indexOf(k) !== -1);
  if (!key) return { status: 404, ok: false, json: async () => ({}) };
  return { status: 200, ok: true, json: async () => scenario.routes[key] };
};

const src = fs.readFileSync(process.argv[2], "utf-8");
const api = new Function(src + "\nreturn { renderArtistsOverview, _renderLibraryHealthSnapshot, " +
  "_renderLibraryAttention, loadLibraryHealthSparkline, loadLibraryKpis };")();

(async () => {
  for (const op of scenario.ops || []) {
    if (op.op === "call") {
      const args = (op.args || []).map((a) => (typeof a === "string" && a[0] === "@" ? document.getElementById(a.slice(1)) : a));
      await api[op.fn].apply(null, args);
    } else if (op.op === "set") {
      document.getElementById(op.id)[op.prop] = op.value;
    } else if (op.op === "fire") {
      document.getElementById(op.id).listeners[op.type]({ target: { closest: () => null } });
      await new Promise((r) => setImmediate(r));
    }
  }
  const out = { fetchCalls, els: {} };
  Object.keys(els).forEach((id) => {
    out.els[id] = { html: els[id].innerHTML, text: els[id].textContent, hidden: els[id].hidden };
  });
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ crash: String(e && e.stack || e) }) + "\n", () => process.exit(1));
});
"""


def _run(tmp_path: Path, scenario: dict) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    combined = tmp_path / "common_plus_library.js"
    combined.write_text(
        COMMON_JS.read_text(encoding="utf-8") + "\n" + LIBRARY_JS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [_NODE, str(script), str(combined), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crash" not in out, out.get("crash")
    return out


def _artists(n: int, *, health_score=100) -> list:
    return [
        {"artist": f"Artist{i:02d}", "file_count": i + 1, "album_count": 1, "health_score": health_score}
        for i in range(n)
    ]


# ─────────────────────────────────────────────────────────────────────────
# Artists-Tabelle: progressive Anzeige ("Weitere laden")
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_artists_overview_paginates_and_load_more_reveals_rest(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content",
                                                                {"artists": _artists(20), "stale": False}]},
    ]})
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 15  # _ARTISTS_PAGE_SIZE
    assert "15 von 20 Artists" in html
    assert 'id="artists-load-more-btn"' in html

    out2 = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content",
                                                                {"artists": _artists(20), "stale": False}]},
        {"op": "fire", "id": "artists-load-more-btn", "type": "click"},
    ]})
    html2 = out2["els"]["artists-overview-content"]["html"]
    assert html2.count('class="artist-row"') == 20
    assert 'id="artists-load-more-btn"' not in html2  # alle geladen -> kein Button mehr


@needs_node
def test_artists_overview_under_page_size_shows_no_load_more_button(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content",
                                                                {"artists": _artists(5), "stale": False}]},
    ]})
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 5
    assert 'id="artists-load-more-btn"' not in html


@needs_node
def test_artists_overview_health_column_uses_dot_not_pill(tmp_path: Path) -> None:
    """Phase E Dashboard-Optimierung: Punkt (.dot-ok/.dot-warn/.dot-error,
    dieselbe Konvention wie die Repair-History) statt Pille+Symbol."""
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content",
                                                                {"artists": [
                                                                    {"artist": "Good", "file_count": 1, "album_count": 0, "health_score": 100},
                                                                    {"artist": "Mid", "file_count": 1, "album_count": 0, "health_score": 80},
                                                                    {"artist": "Bad", "file_count": 1, "album_count": 0, "health_score": 40},
                                                                ], "stale": False}]},
    ]})
    html = out["els"]["artists-overview-content"]["html"]
    assert 'class="dot dot-ok"' in html
    assert 'class="dot dot-warn"' in html
    assert 'class="dot dot-error"' in html
    assert "bg-green-lt" not in html  # alte Pillen-Klasse ist weg


# ─────────────────────────────────────────────────────────────────────────
# Library-Health-Karte: Status-Farbe, Progress-Bar, Sparkline-Trigger
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_health_snapshot_uses_shared_status_color_and_progress_bar(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": []}},
        "ops": [{"op": "call", "fn": "_renderLibraryHealthSnapshot", "args": [{
            "health": {"score": 99.9, "status": "EXCELLENT"},
            "statistics": {"total_files": 501, "total_artists": 42, "total_albums": 59},
            "scan": {"completed_at": "2026-09-27T05:47:00"},
        }]}],
    })
    html = out["els"]["library-health-content"]["html"]
    assert "99.9" in html
    assert 'bg-green-lt">EXCELLENT' in html  # _HEALTH_STATUS_COLOR.EXCELLENT == "green"
    assert 'class="progress-bar bg-green" style="width: 99.9%"' in html
    assert "501 Tracks · 42 Artists · 59 Alben" in html
    # CC-LIB-FINAL Library-Home: der "Stand"-Zeitstempel lebt seit dieser
    # Phase prominent unter dem Seitentitel (library-last-scan, befuellt
    # von loadLibraryKpis() - siehe test_last_scan_shown_under_page_title
    # unten) statt hier klein im Panel - hier deshalb bewusst NICHT mehr
    # geprueft.
    assert 'class="btn btn-outline-primary w-100' in html
    # Sparkline wird als eigener, isolierter Request geladen (nicht Teil
    # derselben /health/cached-Antwort).
    assert any("score-history" in u for u in out["fetchCalls"])


@needs_node
def test_health_snapshot_poor_status_uses_orange(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": []}},
        "ops": [{"op": "call", "fn": "_renderLibraryHealthSnapshot", "args": [{
            "health": {"score": 55, "status": "POOR"}, "statistics": {}, "scan": {},
        }]}],
    })
    html = out["els"]["library-health-content"]["html"]
    assert 'bg-orange-lt">POOR' in html  # _HEALTH_STATUS_COLOR.POOR == "orange"


@needs_node
def test_health_sparkline_renders_into_own_placeholder(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": [
            {"score": 90.0, "status": "GOOD", "timestamp": "2026-09-20T10:00:00"},
            {"score": 99.9, "status": "EXCELLENT", "timestamp": "2026-09-27T05:47:00"},
        ]}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    html = out["els"]["library-health-sparkline"]["html"]
    assert "<svg" in html
    assert "<polyline" in html
    assert "Score-Verlauf" in html


@needs_node
def test_health_sparkline_empty_history_renders_nothing(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": []}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    assert out["els"]["library-health-sparkline"]["html"] == ""


# ─────────────────────────────────────────────────────────────────────────
# CC-LIB-FINAL Library-Home: "Zuletzt gescannt" prominent + Health-Trend
# (Nutzer-Ergaenzung — score-history liefert die Reihe bereits, kein
# neuer Endpunkt: Differenz erster vs. letzter gewerteter Score im
# selben score-history-Fenster wie die Sparkline oben).
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_last_scan_shown_under_page_title(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {
            "health/cached": {
                "library": {"files": 501, "artists": 42, "albums": 59},
                "health": {"score": 99.9, "status": "EXCELLENT"},
                "statistics": {"total_files": 501, "total_artists": 42, "total_albums": 59},
                "scan": {"completed_at": "2026-09-27T05:47:00"},
            },
            "score-history": {"entries": []},
        },
        "ops": [{"op": "call", "fn": "loadLibraryKpis"}],
    })
    assert out["els"]["library-last-scan"]["text"] == "Zuletzt gescannt: 27.09.2026 05:47"


@needs_node
def test_health_trend_shows_positive_delta_since_first_visible_scan(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": [
            {"score": 91.2, "status": "GOOD", "timestamp": "2026-09-20T10:00:00"},
            {"score": 91.5, "status": "GOOD", "timestamp": "2026-09-27T05:47:00"},
        ]}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    assert out["els"]["library-health-trend"]["text"] == "+0.3 seit letztem Scan"


@needs_node
def test_health_trend_shows_negative_delta(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": [
            {"score": 95.0, "status": "EXCELLENT", "timestamp": "2026-09-20T10:00:00"},
            {"score": 92.0, "status": "GOOD", "timestamp": "2026-09-27T05:47:00"},
        ]}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    assert out["els"]["library-health-trend"]["text"] == "-3 seit letztem Scan"


@needs_node
def test_health_trend_unchanged_shows_plusminus_zero(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": [
            {"score": 90.0, "status": "GOOD", "timestamp": "2026-09-20T10:00:00"},
            {"score": 90.0, "status": "GOOD", "timestamp": "2026-09-27T05:47:00"},
        ]}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    assert out["els"]["library-health-trend"]["text"] == "±0 seit letztem Scan"


@needs_node
def test_health_trend_hidden_with_fewer_than_two_scored_entries(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"score-history": {"entries": [
            {"score": 90.0, "status": "GOOD", "timestamp": "2026-09-27T05:47:00"},
        ]}},
        "ops": [{"op": "call", "fn": "loadLibraryHealthSparkline"}],
    })
    assert out["els"]["library-health-trend"]["text"] == ""


# ─────────────────────────────────────────────────────────────────────────
# Aufmerksamkeit-Karte: Warnings-Kennzahl, Errors nie verschwiegen
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_attention_shows_top_issues_as_labeled_rows(tmp_path: Path) -> None:
    """CC-LIB-FINAL Library-Home (Nutzer-Freigabe): Zeilenliste statt
    Code-Badges - Icon + Anzahl + Klartext-Label aus dem gemeinsamen
    _ISSUE_LABELS (common.js), sortiert nach Severity-Tier dann Anzahl,
    Top 3 (nicht mehr nur WARNING-Codes und nicht mehr auf 2 verkuerzt)."""
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "_renderLibraryAttention", "args": [{
        "statistics": {
            "issues_by_severity": {"ERROR": 0, "WARNING": 21, "INFO": 1223},
            "issues_by_code": {"AUDIO_LOW_BITRATE": 13, "ALBUM_TRACK_GAP": 7, "GENRE_EMPTY": 1},
        },
    }]}]})
    html = out["els"]["library-attention-content"]["html"]
    assert "Errors" not in html  # 0 Errors -> keine eigene Zeile
    assert ">13<" in html and "Bitrate niedrig" in html
    assert ">7<" in html and "Lücke in der Tracknummerierung" in html
    assert ">1<" in html and "Genre-Tag leer" in html  # Top 3 statt Top 2
    assert "Top 3 nach Severity · 1244 offen insgesamt" in html
    assert 'class="btn btn-outline-primary w-100' in html


@needs_node
def test_attention_never_hides_nonzero_errors(tmp_path: Path) -> None:
    """P0-Prioritaet (CLAUDE.md Abschnitt 23): ein vorhandener Errors-Wert
    darf durch die Dashboard-Verschlankung nie verschwinden - auch wenn
    issues_by_code (Detail-Rangliste) leer ist."""
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "_renderLibraryAttention", "args": [{
        "statistics": {
            "issues_by_severity": {"ERROR": 3, "WARNING": 5, "INFO": 0},
            "issues_by_code": {},
        },
    }]}]})
    html = out["els"]["library-attention-content"]["html"]
    assert "3 Errors" in html
    assert "Top 0 nach Severity · 8 offen insgesamt" in html


@needs_node
def test_attention_error_tier_code_ranks_above_higher_count_warning(tmp_path: Path) -> None:
    """Neu seit CC-LIB-FINAL: ein ERROR-/CRITICAL-Code mit offenen Treffern
    landet automatisch oben in der Rangliste, auch bei niedrigerer Anzahl
    als ein WARNING-Code - nicht mehr nur als Summe im Errors-Badge sichtbar."""
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "_renderLibraryAttention", "args": [{
        "statistics": {
            "issues_by_severity": {"ERROR": 2, "WARNING": 13, "INFO": 0},
            "issues_by_code": {"AUDIO_LOW_BITRATE": 13, "AUDIO_CORRUPT": 2},
        },
    }]}]})
    html = out["els"]["library-attention-content"]["html"]
    first_row_pos = html.find("Audio-Datei beschädigt")  # AUDIO_CORRUPT (CRITICAL)
    second_row_pos = html.find("Bitrate niedrig")  # AUDIO_LOW_BITRATE (WARNING, hoehere Anzahl)
    assert first_row_pos != -1 and second_row_pos != -1
    assert first_row_pos < second_row_pos


@needs_node
def test_similarly_named_artist_rows_get_distinct_hrefs_and_tooltips(tmp_path: Path) -> None:
    """Freigabe fix.txt 2026-09-27: bei aehnlichen/nahezu gleichen Artist-
    Namen (hier: ein Name mit unsichtbarem Trailing-Space, der beim
    HTML-Rendering visuell verschwindet) muss jede Zeile trotzdem
    eindeutig einem Verzeichnis zuzuordnen sein. `a.artist` ist bereits
    der stabile, verzeichnisbasierte Schluessel (services/library_health/
    scoring.py, artist_directory) - jede Zeile bekommt deshalb zusaetzlich
    ein `title`-Attribut mit dem exakten Wert (Tooltip deckt Whitespace-
    /Aehnlichkeits-Unterschiede auf, die der sichtbare Zeilentext allein
    nicht zeigt)."""
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistsOverview", "args": ["@artists-overview-content",
                                                                {"artists": [
                                                                    {"artist": "Apache", "file_count": 3, "album_count": 1, "health_score": 90},
                                                                    {"artist": "Apache ", "file_count": 2, "album_count": 1, "health_score": 90},
                                                                ], "stale": False}]},
    ]})
    html = out["els"]["artists-overview-content"]["html"]
    assert html.count('class="artist-row"') == 2
    assert 'title="Apache"' in html
    assert 'title="Apache "' in html
    assert "/library/Apache" in html
    assert "/library/Apache%20" in html  # encodeURIComponent(a.artist) - Trailing-Space bleibt im href erhalten


@needs_node
def test_attention_empty_state_unchanged(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [{"op": "call", "fn": "_renderLibraryAttention", "args": [{
        "statistics": {"issues_by_severity": {}, "issues_by_code": {}},
    }]}]})
    html = out["els"]["library-attention-content"]["html"]
    assert "Keine kritischen Probleme" in html
    assert 'class="btn btn-outline-primary w-100' in html
