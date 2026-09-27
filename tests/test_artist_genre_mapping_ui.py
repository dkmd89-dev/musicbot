# -*- coding: utf-8 -*-
"""Artist-Detailseite: Genre-Mapping bearbeiten (Primary + Secondary).

  1. Markup/Verdrahtung (echte create_app()): Editor-IDs, bestehende
     genre-manage-* IDs bleiben, alle fetch() laufen ueber apiUrl().
  2. Die reinen Render-/Zustandsfunktionen des Inline-Skripts werden aus dem
     Template extrahiert und real mit node ausgefuehrt (Muster wie
     tests/test_repair_result_semantics.py).
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

TEMPLATE = Path(__file__).resolve().parent.parent / "control_center" / "templates" / "library_artist_detail.html"
_NODE = shutil.which("node")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


_IDS = ["genre-mapping-editor", "genre-mapping-status", "genre-mapping-form", "genre-mapping-primary",
        "genre-mapping-secondary", "genre-mapping-add-input", "genre-mapping-add-btn", "genre-mapping-datalist",
        "genre-mapping-preview-btn", "genre-mapping-reset-btn", "genre-mapping-preview-content",
        "genre-mapping-save-btn", "genre-mapping-result-content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dom_id", _IDS + ["genre-manage-preview-btn", "genre-manage-execute-btn",
                                            "genre-manage-content", "genre-manage-result-content"])
async def test_artist_page_has_editor_and_keeps_existing_genre_manage_ids(client, dom_id):
    html = (await client.get("/library/Bausa")).text
    assert f'id="{dom_id}"' in html


@pytest.mark.asyncio
async def test_editor_is_a_form_with_primary_input_secondary_chips_and_datalist(client):
    html = (await client.get("/library/Bausa")).text
    assert re.search(r'<input[^>]*id="genre-mapping-primary"[^>]*list="genre-mapping-datalist"', html)
    assert re.search(r'<input[^>]*id="genre-mapping-add-input"[^>]*list="genre-mapping-datalist"', html)
    assert '<datalist id="genre-mapping-datalist">' in html
    assert re.search(r'id="genre-mapping-save-btn"[^>]*disabled', html)          # erst nach "Änderung prüfen"
    assert 'id="genre-mapping-form" hidden' in html                              # erst nach dem Laden sichtbar


@pytest.mark.asyncio
async def test_editor_tells_the_user_that_new_downloads_need_a_bot_restart(client):
    html = (await client.get("/library/Bausa")).text
    editor = html.split('id="genre-mapping-editor"', 1)[1].split("Tags aus dem Mapping setzen", 1)[0]
    assert "Bot-Neustart" in editor
    assert "mapping/artist_genre.yaml" in editor


@pytest.mark.asyncio
async def test_page_script_uses_only_the_genre_mapping_endpoints_via_api_url(client):
    html = (await client.get("/library/Bausa")).text
    block = html.split("// -- Genre-Mapping bearbeiten", 1)[1].split("document.getElementById(\"genre-manage-preview-btn\")", 1)[0]
    assert "fetch(apiUrl(`/api/v1/library/artists/${encodeURIComponent(artist)}/genre-mapping/preview`)" in block
    assert "fetch(apiUrl(`/api/v1/library/artists/${encodeURIComponent(artist)}/genre-mapping`)" in block
    assert re.findall(r"fetch\((?!apiUrl)", block) == []
    assert 'method: "PUT"' in block and 'method: "POST"' in block


@pytest.mark.asyncio
async def test_save_requires_a_preview_and_a_confirmation_and_sends_the_etag(client):
    html = (await client.get("/library/Bausa")).text
    save_fn = html.split("async function saveGenreMapping() {", 1)[1].split("document.getElementById(\"genre-mapping-primary\")", 1)[0]
    assert "if (!pv) return;" in save_fn                       # ohne Vorschau kein Schreiben
    assert "window.confirm(" in save_fn and "Bot-Neustart" in save_fn
    assert "etag: pv.etag" in save_fn
    assert "res.status === 409" in save_fn                      # veralteter Stand wird behandelt


# ── node: reine Funktionen aus dem Template ───────────────────────────────

pytestmark_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")


def _extract_function(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    if src[max(0, start - 6):start] == "async ":
        start -= 6
    depth, i = 0, src.index("{", start)
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


_FUNCS = ["genreChipsHtml", "renderGenreMappingPreview", "_genreMappingSyncForm",
          "_genreMappingInvalidate", "applyGenreMapping", "_genreMappingAdd"]

_HARNESS = r"""
const els = {};
const mk = (id) => (els[id] = els[id] || { id, innerHTML: "", value: "", disabled: false, hidden: true });
global.document = { getElementById: (id) => mk(id) };
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"));
const _genreMap = { entry: null, etag: null, primary: "", secondary: [], previewed: null };
%FUNCS%
const scenario = JSON.parse(process.argv[2]);
const out = {};
for (const step of scenario.steps) {
  if (step.op === "apply") applyGenreMapping(mk("genre-mapping-status"), step.body);
  else if (step.op === "add") { mk("genre-mapping-add-input").value = step.value; _genreMappingAdd(); }
  else if (step.op === "setprimary") { _genreMap.primary = step.value; }
  else if (step.op === "preview") { out.previewHtml = renderGenreMappingPreview(step.body); }
  else if (step.op === "markpreviewed") { _genreMap.previewed = { primary: "x", secondary: [], etag: "e", change: "update" }; mk("genre-mapping-save-btn").disabled = false; }
}
out.state = _genreMap;
out.els = Object.fromEntries(Object.entries(els).map(([k, v]) => [k, { html: v.innerHTML, value: v.value, disabled: v.disabled, hidden: v.hidden }]));
console.log(JSON.stringify(out));
"""


def _run(tmp_path: Path, steps: list) -> dict:
    src = TEMPLATE.read_text(encoding="utf-8")
    funcs = "\n".join(_extract_function(src, n) for n in _FUNCS)
    script = tmp_path / "h.js"
    script.write_text(_HARNESS.replace("%FUNCS%", funcs), encoding="utf-8")
    r = subprocess.run([_NODE, str(script), json.dumps({"steps": steps})], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _entry(**kw):
    e = {"key": "apache 207", "primary": "Hip Hop", "secondary": ["Deutschrap", "Trap"], "description": "R"}
    e.update(kw)
    return e


def _get_body(entry, known=("Hip Hop", "Trap")):
    return {"artist": "apache 207", "exists": entry is not None, "entry": entry, "etag": "abc", "known_genres": list(known)}


def _preview(**over):
    b = {"artist": "a", "artist_key": "apache 207", "change": "update", "existing": _entry(), "primary": "Pop",
         "secondary": ["Deutschrap"], "primary_changed": True, "added": ["Pop"], "removed": ["Hip Hop", "Trap"],
         "warnings": [], "etag": "abc"}
    b.update(over)
    return b


@pytestmark_node
def test_apply_loads_state_fills_datalist_shows_form_and_resets_preview(tmp_path):
    out = _run(tmp_path, [{"op": "markpreviewed"}, {"op": "apply", "body": _get_body(_entry())}])
    assert out["state"]["primary"] == "Hip Hop" and out["state"]["secondary"] == ["Deutschrap", "Trap"]
    assert out["state"]["etag"] == "abc" and out["state"]["previewed"] is None
    els = out["els"]
    assert els["genre-mapping-form"]["hidden"] is False
    assert els["genre-mapping-primary"]["value"] == "Hip Hop"
    assert els["genre-mapping-save-btn"]["disabled"] is True            # nach dem Laden erst neu pruefen
    assert '<option value="Trap">' in els["genre-mapping-datalist"]["html"]
    assert "Mapping-Key" in els["genre-mapping-status"]["html"] and "apache 207" in els["genre-mapping-status"]["html"]
    assert els["genre-mapping-secondary"]["html"].count("genre-chip-remove") == 2


@pytest.mark.skipif(_NODE is None, reason="node")
def test_apply_for_an_artist_without_mapping_offers_creating_one(tmp_path):
    out = _run(tmp_path, [{"op": "apply", "body": _get_body(None)}])
    assert out["state"]["primary"] == "" and out["state"]["secondary"] == []
    assert "noch kein Mapping" in out["els"]["genre-mapping-status"]["html"]
    assert "Keine Secondary-Genres" in out["els"]["genre-mapping-secondary"]["html"]


@pytestmark_node
def test_add_secondary_trims_dedupes_case_insensitively_and_ignores_the_primary(tmp_path):
    out = _run(tmp_path, [
        {"op": "apply", "body": _get_body(_entry())},
        {"op": "add", "value": "  Pop   Rap "},
        {"op": "add", "value": "trap"},          # Duplikat (case-insensitive)
        {"op": "add", "value": "HIP HOP"},       # ist das Primary
        {"op": "add", "value": "   "},           # leer
    ])
    assert out["state"]["secondary"] == ["Deutschrap", "Trap", "Pop Rap"]
    assert out["els"]["genre-mapping-add-input"]["value"] == ""


@pytestmark_node
def test_any_edit_invalidates_a_previous_preview_and_disables_save(tmp_path):
    out = _run(tmp_path, [{"op": "apply", "body": _get_body(_entry())}, {"op": "markpreviewed"},
                          {"op": "add", "value": "Pop Rap"}])
    assert out["state"]["previewed"] is None
    assert out["els"]["genre-mapping-save-btn"]["disabled"] is True
    assert out["els"]["genre-mapping-preview-content"]["html"] == ""


@pytestmark_node
def test_chips_escape_genre_names(tmp_path):
    out = _run(tmp_path, [{"op": "apply", "body": _get_body(_entry(secondary=['<img src=x onerror=1>', 'A"B']))}])
    html = out["els"]["genre-mapping-secondary"]["html"]
    assert "<img" not in html and "&lt;img" in html and 'data-genre="A&quot;B"' in html


@pytestmark_node
def test_preview_update_shows_primary_change_removed_and_added(tmp_path):
    html = _run(tmp_path, [{"op": "preview", "body": _preview()}])["previewHtml"]
    assert "Bestehender Mapping-Eintrag wird aktualisiert." in html
    assert "Hip Hop → <strong>Pop</strong>" in html
    assert '<span class="badge bg-red-lt">− Hip Hop</span>' in html and '<span class="badge bg-red-lt">− Trap</span>' in html
    assert '<span class="badge bg-green-lt">+ Pop</span>' in html
    assert "Ergebnis im Mapping: Pop; Deutschrap" in html


@pytestmark_node
def test_preview_secondary_only_edit_marks_primary_unchanged(tmp_path):
    body = _preview(primary="Hip Hop", secondary=["Deutschrap", "Pop Rap"], primary_changed=False,
                    added=["Pop Rap"], removed=["Trap"])
    html = _run(tmp_path, [{"op": "preview", "body": body}])["previewHtml"]
    assert "(unverändert)" in html and "→" not in html.split("Entfernt")[0]
    assert "− Trap" in html and "+ Pop Rap" in html


@pytestmark_node
def test_preview_create_unchanged_reorder_and_warnings(tmp_path):
    create = _run(tmp_path, [{"op": "preview", "body": _preview(change="create", existing=None, removed=[])}])["previewHtml"]
    assert "Neuer Mapping-Eintrag wird angelegt." in create and "→" not in create
    unchanged = _run(tmp_path, [{"op": "preview", "body": _preview(change="unchanged", added=[], removed=[], primary_changed=False)}])["previewHtml"]
    assert "Keine Änderung" in unchanged and "Nur die Reihenfolge" not in unchanged
    reorder = _run(tmp_path, [{"op": "preview", "body": _preview(added=[], removed=[], primary_changed=False)}])["previewHtml"]
    assert "Nur die Reihenfolge ändert sich." in reorder
    warn = _run(tmp_path, [{"op": "preview", "body": _preview(warnings=["Genre 'Trapp' kommt sonst nirgends im Mapping vor — Tippfehler?"])}])["previewHtml"]
    assert "alert alert-warning" in warn and "Trapp" in warn


@pytestmark_node
def test_preview_escapes_all_server_values(tmp_path):
    body = _preview(primary="<b>x</b>", secondary=["<i>y</i>"], added=["<u>z</u>"], removed=["<s>w</s>"],
                    existing=_entry(primary="<script>a</script>"), warnings=["<em>!</em>"])
    html = _run(tmp_path, [{"op": "preview", "body": body}])["previewHtml"]
    for raw in ("<b>", "<i>", "<u>", "<s>", "<script>", "<em>"):
        assert raw not in html, raw
