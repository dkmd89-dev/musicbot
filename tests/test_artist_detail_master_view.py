# -*- coding: utf-8 -*-
"""Artist-Detail — Master-Detail (Phase E, CC-LIB-FINAL, Freigabe-Layout
"Final — Hybrid") — echtes JS-Verhalten.

Das reine String-Matching in test_control_center_ui.py prüft, dass die
richtigen IDs/Funktionsnamen im HTML vorkommen, aber NICHT, dass die neue
Album-Auswahl zur Laufzeit tatsächlich funktioniert (genau die Lücke, vor
der der Health-Dashboard-Vorfall e066b58 warnt: ein scheinbar korrektes
JS kann wegen eines falschen Render-/Event-Vertrags funktional kaputt
sein). Führt deshalb das echte Inline-Skript aus `library_artist_detail.html`
zusammen mit dem echten `common.js` unter Node aus (`_loadInto()`-Vertrag,
identisches Muster wie tests/test_health_page_layout_a.py) und prüft:

  - `renderArtistDetail()`: KPI-Kacheln (inkl. neuer "Offene Findings"-
    Kachel, Summe der bereits geladenen Track-issue_codes), Album-Liste
    (echte Alben aus body.albums + "Ohne Album"-Sammelgruppe für
    Singles), erstes Album automatisch ausgewählt.
  - Album-Wechsel per Klick (data-album-key, echte Event-Delegation auf
    #artist-content über event.target.closest() - reines Re-Rendering
    aus dem bereits geladenen Cache, kein neuer Request).
  - Titel-Quick-Edit-Button pro Track (befüllt title-edit-track-select/
    title-edit-new-title exakt wie der bestehende Track-Drawer-Pfad).
  - "Album bearbeiten"-Button im Album-Header (befüllt
    album-edit-album-select mit dem gewählten Album - verifiziert das
    reale <select>-Options-Verhalten nach einer innerHTML-Zuweisung,
    nicht nur, dass die Funktion aufgerufen wurde).
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
ARTIST_HTML = CC / "templates" / "library_artist_detail.html"
_NODE = shutil.which("node")

needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")


def _extract_script(html_path: Path) -> str:
    html = html_path.read_text(encoding="utf-8")
    m = re.search(r"\{% block scripts %\}\s*<script>(.*)</script>\s*\{% endblock %\}", html, re.S)
    assert m, "kein <script>-Block in {% block scripts %} gefunden"
    return m.group(1)


_HARNESS = r"""
const fs = require("fs");
const els = {};
const fetchCalls = [];

function mkEl(id) {
  const el = {
    id, className: "", textContent: "", value: "", hidden: false,
    disabled: false, dataset: {}, children: [], listeners: {}, options: [],
    _innerHTML: "",
    addEventListener(type, fn) { this.listeners[type] = fn; },
    classList: { toggle() {}, contains: () => false, add() {}, remove() {} },
    // Minimaler <option value="...">-Parser: genuegt, damit
    // [...select.options].some(...) (siehe _quickEditAlbumField() in
    // library_artist_detail.html) nach einer innerHTML-Zuweisung
    // (_populateAlbumSelect()/_populateTrackSelect()) realistisch reagiert
    // - ohne eine vollstaendige DOM-Implementierung zu brauchen.
    querySelector: () => mkEl("_sub"), querySelectorAll: () => [], setAttribute() {},
    scrollIntoView() {}, focus() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return this._innerHTML; },
    set(html) {
      this._innerHTML = html;
      const re = /<option value="([^"]*)"/g;
      const opts = [];
      let m;
      while ((m = re.exec(html))) opts.push({ value: m[1].replace(/&amp;/g, "&").replace(/&quot;/g, '"') });
      this.options = opts;
    },
  });
  return el;
}
global.document = {
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
};
global.window = { alert() {}, confirm: () => true, prompt: () => "", location: { pathname: "/library/Bausa" } };

const scenario = JSON.parse(process.argv[3]);
global.fetch = async (url) => {
  if (url.indexOf("/auth/whoami") === -1) fetchCalls.push(url);
  const key = Object.keys(scenario.routes || {}).find((k) => url.indexOf(k) !== -1);
  if (!key) return { status: 404, ok: false, json: async () => ({}) };
  return { status: 200, ok: true, json: async () => scenario.routes[key] };
};

const src = fs.readFileSync(process.argv[2], "utf-8");
const api = new Function(src + "\nreturn { renderArtistDetail, renderMetadataEditPreview };")();

(async () => {
  for (const op of scenario.ops || []) {
    if (op.op === "call") {
      const args = (op.args || []).map((a) => (typeof a === "string" && a[0] === "@" ? document.getElementById(a.slice(1)) : a));
      await api[op.fn].apply(null, args);
    } else if (op.op === "fire") {
      const closest = op.closest || {};
      document.getElementById(op.id).listeners[op.type]({
        preventDefault() {},
        target: { closest: (sel) => closest[sel] || null },
      });
      await new Promise((r) => setImmediate(r));
    }
  }
  const out = { fetchCalls, els: {} };
  Object.keys(els).forEach((id) => {
    out.els[id] = { html: els[id].innerHTML, value: els[id].value, disabled: els[id].disabled };
  });
  process.stdout.write(JSON.stringify(out) + "\n", () => process.exit(0));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ crash: String(e && e.stack || e) }) + "\n", () => process.exit(1));
});
"""


def _run(tmp_path: Path, scenario: dict) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    combined = tmp_path / "common_plus_artist.js"
    combined.write_text(
        COMMON_JS.read_text(encoding="utf-8") + "\n" + _extract_script(ARTIST_HTML),
        encoding="utf-8",
    )
    result = subprocess.run(
        [_NODE, str(script), str(combined), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crash" not in out, out.get("crash")
    return out


def _track(rel_path, *, album_directory, title=None, track_number=None, issue_codes=None):
    return {
        "relative_path": rel_path, "filename": rel_path.rsplit("/", 1)[-1],
        "artist": "Bausa", "title": title, "album": album_directory,
        "album_directory": album_directory, "album_artist": "Bausa", "genre": "Deutschrap",
        "year": 2020, "track_number": track_number, "disc_number": None,
        "mb_recording_id": None, "mb_release_id": None, "isrc": None,
        "extension": ".m4a", "issue_codes": issue_codes or [],
    }


def _body(**over):
    base = {
        "artist": "Bausa", "file_count": 3, "album_count": 1, "health_score": 92,
        "issue_codes": [], "generated_at": "2026-09-27T05:47:00", "stale": False,
        "albums": [{"artist": "Bausa", "album": "2020 - Powers", "file_count": 2,
                     "health_score": 96, "issue_codes": []}],
        "tracks": [
            _track("Bausa/2020 - Powers/01 - Powers.m4a", album_directory="2020 - Powers",
                   title="Powers", track_number=1, issue_codes=["META_TITLE_NOT_CLEAN"]),
            _track("Bausa/2020 - Powers/02 - Was Du Liebe nennst.m4a", album_directory="2020 - Powers",
                   title="Was Du Liebe nennst", track_number=2),
            _track("Bausa/Auf gute Freunde.m4a", album_directory=None, title="Auf gute Freunde"),
        ],
    }
    base.update(over)
    return base


# ─────────────────────────────────────────────────────────────────────────
# renderArtistDetail(): KPI-Kacheln, Album-Liste, Default-Auswahl
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_render_shows_kpi_tiles_including_open_findings(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
    ]})
    html = out["els"]["artist-content"]["html"]
    assert '<div class="tile-value status-EXCELLENT">92</div>' in html
    assert '<div class="tile-value">3</div>' in html  # Dateien
    assert '<div class="tile-value">1</div>' in html  # Alben
    # Offene Findings: 1 issue_code auf "Powers", 0 sonst -> Summe 1.
    assert "Offene Findings" in html
    m = re.search(r'Offene Findings</div>\s*<div class="tile-value">(\d+)</div>', html)
    assert m and m.group(1) == "1"


@needs_node
def test_render_lists_real_album_and_singles_group_first_album_selected(tmp_path: Path) -> None:
    """Erster Render schreibt Album-Liste/-Detail als Teil des
    #artist-content-innerHTML (nicht ueber ein separates getElementById()
    auf die verschachtelten IDs) - deshalb hier gegen das
    #artist-content-HTML gepruft, nicht gegen (auf dem ersten Render noch
    nicht einzeln registrierte) Sub-Element-IDs."""
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
    ]})
    html = out["els"]["artist-content"]["html"]
    assert "2020 - Powers" in html
    assert "Ohne Album" in html
    assert 'class="select-row active"' in html  # genau ein aktiver Eintrag
    assert html.count('data-album-key=') == 2
    assert "Was Du Liebe nennst" in html
    assert 'id="album-detail-edit-album-btn"' in html  # echtes Album -> Toolbar da
    assert "⚠ 1" in html  # issue_codes-Zaehler fuer "Powers"
    # "Auf gute Freunde" gehoert zur Singles-Gruppe, die NICHT das zuerst
    # ausgewaehlte (alphabetisch erste) Album ist.
    powers_and_after = html.split("2020 - Powers", 1)[1]
    assert "Auf gute Freunde" not in powers_and_after.split("segment-nav", 1)[0]


@needs_node
def test_singles_group_has_no_album_toolbar(tmp_path: Path) -> None:
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
        {"op": "fire", "id": "artist-content", "type": "click",
         "closest": {"[data-album-key]": {"dataset": {"albumKey": "__singles__"}}}},
    ]})
    detail_html = out["els"]["artist-album-detail"]["html"]
    assert "Auf gute Freunde" in detail_html
    assert "Powers" not in detail_html
    assert 'id="album-detail-edit-album-btn"' not in detail_html
    assert 'id="album-detail-edit-albumartist-btn"' not in detail_html


# ─────────────────────────────────────────────────────────────────────────
# Album-Wechsel per Klick (echte Event-Delegation)
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_clicking_another_album_switches_detail_pane_tracks(tmp_path: Path) -> None:
    body = _body(
        album_count=2,
        albums=[
            {"artist": "Bausa", "album": "2020 - Powers", "file_count": 2, "health_score": 96, "issue_codes": []},
            {"artist": "Bausa", "album": "2018 - Chants", "file_count": 1, "health_score": 100, "issue_codes": []},
        ],
        tracks=[
            _track("Bausa/2020 - Powers/01 - Powers.m4a", album_directory="2020 - Powers", title="Powers", track_number=1),
            _track("Bausa/2018 - Chants/01 - Endlich.m4a", album_directory="2018 - Chants", title="Endlich", track_number=1),
        ],
    )
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", body]},
        {"op": "fire", "id": "artist-content", "type": "click",
         "closest": {"[data-album-key]": {"dataset": {"albumKey": "2018 - Chants"}}}},
    ]})
    detail_html = out["els"]["artist-album-detail"]["html"]
    assert "Endlich" in detail_html
    assert "Powers" not in detail_html
    list_html = out["els"]["artist-album-list"]["html"]
    # Jetzt ist "2018 - Chants" aktiv, nicht mehr "2020 - Powers".
    assert re.search(r'data-album-key="2018 - Chants"[^>]*class="select-row active"|class="select-row active" data-album-key="2018 - Chants"', list_html) \
        or 'class="select-row active" data-album-key="2018 - Chants"' in list_html


# ─────────────────────────────────────────────────────────────────────────
# Titel-Quick-Edit (Stift direkt in der Track-Zeile)
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_quick_edit_title_button_prefills_title_form(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "routes": {"title-edit/preview": {"target_count": 0, "changed_count": 0, "outcomes": []}},
        "ops": [
            {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
            {"op": "fire", "id": "artist-content", "type": "click",
             "closest": {"[data-quick-edit-title]": {"dataset": {"quickEditTitle": "Bausa/2020 - Powers/01 - Powers.m4a"}}}},
        ],
    })
    assert out["els"]["title-edit-track-select"]["value"] == "Bausa/2020 - Powers/01 - Powers.m4a"
    assert out["els"]["title-edit-new-title"]["value"] == "Powers"
    assert out["els"]["title-edit-execute-btn"]["disabled"] is True
    assert any("title-edit/preview" in u for u in out["fetchCalls"])


# ─────────────────────────────────────────────────────────────────────────
# "Album bearbeiten"-Button im Album-Header
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_album_edit_button_preselects_the_viewed_album(tmp_path: Path) -> None:
    """Verifiziert das reale <select>-Verhalten nach _populateAlbumPickers()
    (innerHTML mit <option>-Tags) UND _quickEditAlbumField() zusammen -
    nicht nur, dass irgendeine Funktion aufgerufen wurde."""
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderArtistDetail", "args": ["@artist-content", _body()]},
        {"op": "fire", "id": "artist-content", "type": "click",
         "closest": {"#album-detail-edit-album-btn": {}}},
    ]})
    assert out["els"]["album-edit-album-select"]["value"] == "2020 - Powers"


# ─────────────────────────────────────────────────────────────────────────
# renderMetadataEditPreview(): keine widersprüchlichen Statusmeldungen
# (Freigabe fix.txt 2026-09-27) - eine Zeile pro Panel darf nur EINEN
# eindeutigen Zustand aussagen: "wird geändert" ODER "wird übersprungen,
# weil <Grund>", nie "keine Änderung nötig" zusammen mit einem Grund, der
# gerade KEINEN No-Op belegt (z. B. Artist-Rename ist tag-wert-getrieben,
# executor.py::apply_artist_rename() - "Artist-Tag entspricht nicht dem
# gewaehlten Ausgangswert" bedeutet Wert-Mismatch, nicht Wert-Gleichheit).
# ─────────────────────────────────────────────────────────────────────────


def _skip_outcome(file, reason, *, status="SKIPPED"):
    return {"file": file, "status": status, "before": {}, "after": {}, "reason": reason}


@needs_node
def test_artist_rename_mismatch_shows_skip_not_noop(tmp_path: Path) -> None:
    """Konkreter Fall aus dem Screenshot: Artist-Tag "Apache", Zielwert
    "Apache 207" - passt der tatsaechliche ©ART-Tag nicht zum gewaehlten
    Ausgangswert, wird die Datei uebersprungen. Die Kopfzeile darf dafuer
    NICHT "keine Änderung nötig" sagen (das behauptet Wert-Gleichheit,
    das Gegenteil des tatsaechlichen Grundes)."""
    body = {
        "target_count": 1, "changed_count": 0,
        "outcomes": [_skip_outcome(
            "Apache/Song.m4a", "Artist-Tag entspricht nicht dem gewaehlten Ausgangswert",
        )],
    }
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderMetadataEditPreview",
         "args": ["@artist-edit-content", body, "artist-edit-execute-btn"]},
    ]})
    html = out["els"]["artist-edit-content"]["html"]
    assert "keine Änderung nötig" not in html
    assert "wird übersprungen" in html
    assert "Artist-Tag entspricht nicht dem gewaehlten Ausgangswert" in html
    assert out["els"]["artist-edit-execute-btn"]["disabled"] is True


@needs_node
def test_title_edit_genuine_noop_keeps_keine_aenderung_noetig(tmp_path: Path) -> None:
    """Titel-Tag "Nur mich -", Zielwert "Nur mich": stimmt der tatsaechlich
    gelesene ©nam-Tag exakt mit dem Zielwert ueberein (executor.py::
    apply_title_edit()s einzige Skip-Begruendung "bereits korrekt"), bleibt
    "keine Änderung nötig" - hier IST das die zutreffende, eindeutige
    Aussage (kein Widerspruch, da nur dieser eine Grund vorliegt)."""
    body = {
        "target_count": 1, "changed_count": 0,
        "outcomes": [_skip_outcome("Nur mich -.m4a", "bereits korrekt")],
    }
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderMetadataEditPreview",
         "args": ["@title-edit-content", body, "title-edit-execute-btn"]},
    ]})
    html = out["els"]["title-edit-content"]["html"]
    assert "keine Änderung nötig" in html
    assert "wird übersprungen" not in html
    assert "bereits korrekt" in html
    assert out["els"]["title-edit-execute-btn"]["disabled"] is True


@needs_node
def test_title_edit_real_change_still_shows_wird_geaendert(tmp_path: Path) -> None:
    """Regressionsschutz: der eigentliche Aenderungsfall (DRY_RUN, echter
    Diff) darf durch die Skip-Text-Unterscheidung oben nicht beeinflusst
    werden - "Nur mich -" -> "Nur mich" muss weiterhin normal als
    aktivierbare Aenderung angezeigt werden, wenn der Tag tatsaechlich
    abweicht."""
    body = {
        "target_count": 1, "changed_count": 1,
        "outcomes": [{
            "file": "Nur mich -.m4a", "status": "DRY_RUN",
            "before": {"title": "Nur mich -"}, "after": {"title": "Nur mich"},
            "reason": None,
        }],
    }
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderMetadataEditPreview",
         "args": ["@title-edit-content", body, "title-edit-execute-btn"]},
    ]})
    html = out["els"]["title-edit-content"]["html"]
    assert "werden geändert" in html
    assert "Nur mich -" in html and "Nur mich" in html
    assert out["els"]["title-edit-execute-btn"]["disabled"] is False


@needs_node
def test_safety_skip_also_shown_as_wird_uebersprungen(tmp_path: Path) -> None:
    """Ein Safety-Skip (z. B. Symlink) ist ebenfalls kein No-Op - auch
    hier darf die Kopfzeile nicht "keine Änderung nötig" behaupten."""
    body = {
        "target_count": 1, "changed_count": 0,
        "outcomes": [_skip_outcome("Album/Song.m4a", "Safety: Symlink")],
    }
    out = _run(tmp_path, {"ops": [
        {"op": "call", "fn": "renderMetadataEditPreview",
         "args": ["@album-edit-content", body, "album-edit-execute-btn"]},
    ]})
    html = out["els"]["album-edit-content"]["html"]
    assert "keine Änderung nötig" not in html
    assert "wird übersprungen" in html
    assert "Safety: Symlink" in html
