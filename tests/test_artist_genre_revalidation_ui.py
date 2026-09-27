# -*- coding: utf-8 -*-
"""Artist-Detailseite: Genre revalidieren (Job-Anbindung).

Markup/Verdrahtung ueber die echte create_app(); die Render-/Zustandsfunktionen
des Inline-Skripts werden aus dem Template extrahiert und real mit node ausgefuehrt.
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
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")


@pytest_asyncio.fixture
async def client():
    from control_center.app import create_app

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_panel_explains_what_revalidation_does_and_does_not_do(client):
    html = (await client.get("/library/Bausa")).text
    panel = html.split('id="genre-revalidation-panel"', 1)[1].split("<!-- L2 / L3 -->", 1)[0]
    assert "keine" in panel and "Audio-Dateien" in panel           # verändert keine Audio-Dateien
    assert "auto_learned_genre.json" in panel and "Bot-Neustart" in panel
    assert "manuellem Mapping" in panel                              # blockiert bei manuellem Mapping
    assert "Mapping-Editor" in panel


@pytest.mark.asyncio
async def test_script_uses_api_url_confirms_before_apply_and_polls_every_second(client):
    html = (await client.get("/library/Bausa")).text
    block = html.split("// -- Genre revalidieren", 1)[1].split('document.getElementById("genre-manage-preview-btn")', 1)[0]
    assert re.findall(r"fetch\((?!apiUrl)", block) == []
    start = block.split("async function startGenreRevalidation(mode) {", 1)[1].split("_genreRevalSetBusy(true);", 1)[0]
    assert 'if (mode === "apply")' in start and "window.confirm(" in start and "if (!confirmed) return;" in start
    assert "setInterval(() => _pollGenreRevalidationJob(_genreRevalJobId), 1000)" in block
    assert "Netzwerkfehler" not in block                             # Wording-Pin der Seite (nur der L2/L3-Job-Start)


_FUNCS = ["_genreLine", "genreRevalidationResultHtml", "_genreRevalSetBusy", "_stopGenreRevalPolling",
          "_renderGenreRevalidationJob"]

_HARNESS = r"""
const els = {};
const mk = (id) => (els[id] = els[id] || { id, innerHTML: "", disabled: false });
global.document = { getElementById: (id) => mk(id) };
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"));
global.clearInterval = () => {};
%CONSTS%
let _genreRevalTimer = null;
%FUNCS%
const scenario = JSON.parse(process.argv[2]);
const out = {};
mk("genre-revalidation-apply-btn").disabled = true;
if (scenario.result) out.html = genreRevalidationResultHtml(scenario.result);
for (const job of scenario.jobs || []) _renderGenreRevalidationJob(job);
out.els = Object.fromEntries(Object.entries(els).map(([k, v]) => [k, { html: v.innerHTML, disabled: v.disabled }]));
console.log(JSON.stringify(out));
"""


def _extract(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


def _run(tmp_path: Path, scenario: dict) -> dict:
    src = TEMPLATE.read_text(encoding="utf-8")
    consts = re.search(r"  const _GENRE_REVAL_OUTCOMES = \{.*?\n  \};", src, re.S).group(0)
    script = tmp_path / "h.js"
    script.write_text(_HARNESS.replace("%CONSTS%", consts).replace("%FUNCS%", "\n".join(_extract(src, n) for n in _FUNCS)),
                      encoding="utf-8")
    r = subprocess.run([_NODE, str(script), json.dumps(scenario)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _res(**over):
    base = {"artist": "A", "outcome": "OVERTURN_ALLOWED", "reason": "Neuer Kandidat erfüllt die Overturn-Regel.",
            "manual_mapping_protected": False, "current_primary": "Pop", "current_secondary": ["Rock"],
            "candidate_primary": "Hip Hop", "candidate_secondary": ["Deutschrap"], "candidate_source": "lastfm",
            "learning_status": "LEARNED", "locked_primary": "Hip Hop", "observation_count": 3, "mutated": False,
            "error_message": None, "mode": "preview", "exit_code": 0}
    base.update(over)
    return base


def _job(status="SUCCEEDED", result=None, **kw):
    j = {"status": status, "progress": 100.0, "message": "", "result": result, "error": None}
    j.update(kw)
    return j


@needs_node
@pytest.mark.parametrize("outcome,kind,label", [
    ("BLOCKED_MANUAL", "warning", "Blockiert — manuelles Mapping vorhanden"),
    ("NO_CANDIDATE", "warning", "Kein Kandidat"),
    ("SAME_GENRE", "success", "keine Änderung nötig"),
    ("OVERTURN_REJECTED", "warning", "Overturn-Regel nicht erfüllt"),
    ("OVERTURN_ALLOWED", "info", "Änderung zulässig"),
])
def test_each_outcome_is_rendered_with_its_own_label_and_alert_kind(tmp_path, outcome, kind, label):
    html = _run(tmp_path, {"result": _res(outcome=outcome)})["html"]
    assert f'alert alert-{kind} py-2 mb-2' in html and label in html


@needs_node
def test_result_shows_current_candidate_status_and_reason(tmp_path):
    html = _run(tmp_path, {"result": _res()})["html"]
    assert "Aktuell" in html and "Pop; Rock" in html
    assert "Kandidat (Last.fm)" in html and "Hip Hop; Deutschrap" in html
    assert "Lernstatus" in html and "LEARNED" in html and "Gelocktes Primary" in html
    assert "Beobachtungen" in html and ">3<" in html
    assert "Neuer Kandidat erfüllt die Overturn-Regel." in html


@needs_node
def test_result_without_current_or_candidate_genre(tmp_path):
    html = _run(tmp_path, {"result": _res(current_primary=None, current_secondary=[], candidate_primary=None,
                                          candidate_secondary=[], learning_status=None, locked_primary=None)})["html"]
    assert "(kein Genre)" in html and "—" in html
    assert "Lernstatus" not in html and "Gelocktes Primary" not in html


@needs_node
def test_preview_says_nothing_was_written_apply_reports_the_real_outcome(tmp_path):
    preview = _run(tmp_path, {"result": _res(mode="preview")})["html"]
    assert "Vorschau — es wurde nichts geschrieben." in preview
    wrote = _run(tmp_path, {"result": _res(mode="apply", mutated=True)})["html"]
    assert "Gelerntes Genre aktualisiert" in wrote and "Bot-Neustart" in wrote and "Audio-Dateien wurden nicht verändert" in wrote
    skipped = _run(tmp_path, {"result": _res(mode="apply", mutated=False)})["html"]
    assert "Keine Änderung geschrieben." in skipped and "Gelerntes Genre aktualisiert" not in skipped


@needs_node
def test_lastfm_error_is_shown(tmp_path):
    html = _run(tmp_path, {"result": _res(outcome="NO_CANDIDATE", error_message="lastfm down")})["html"]
    assert "Last.fm-Fehler: lastfm down" in html and "alert-danger" in html


@needs_node
def test_result_escapes_all_server_values(tmp_path):
    html = _run(tmp_path, {"result": _res(current_primary="<b>x</b>", candidate_primary="<i>y</i>", reason="<u>z</u>",
                                          learning_status="<s>l</s>", error_message="<em>e</em>",
                                          candidate_secondary=["<script>s</script>"])})["html"]
    for raw in ("<b>", "<i>", "<u>", "<s>", "<em>", "<script>"):
        assert raw not in html, raw


@needs_node
def test_apply_button_is_enabled_only_after_a_preview_that_allows_the_change(tmp_path):
    def apply_disabled(result, status="SUCCEEDED"):
        out = _run(tmp_path, {"jobs": [_job(status, result)]})
        return out["els"]["genre-revalidation-apply-btn"]["disabled"]

    assert apply_disabled(_res(mode="preview", outcome="OVERTURN_ALLOWED")) is False
    for outcome in ("BLOCKED_MANUAL", "NO_CANDIDATE", "SAME_GENRE", "OVERTURN_REJECTED"):
        assert apply_disabled(_res(mode="preview", outcome=outcome)) is True, outcome
    assert apply_disabled(_res(mode="preview", error_message="lastfm down")) is True      # Fehler -> nicht anwenden
    assert apply_disabled(_res(mode="apply", outcome="OVERTURN_ALLOWED", mutated=True)) is True   # nach Apply neu pruefen
    assert apply_disabled(None, status="FAILED") is True


@needs_node
def test_running_job_shows_progress_and_keeps_apply_disabled(tmp_path):
    out = _run(tmp_path, {"jobs": [_job("RUNNING", None, progress=10.0, message="Last.fm wird für A abgefragt…")]})
    assert "RUNNING (10%)" in out["els"]["genre-revalidation-content"]["html"]
    assert out["els"]["genre-revalidation-apply-btn"]["disabled"] is True


@needs_node
def test_failed_job_shows_the_error_and_reenables_the_preview_button(tmp_path):
    out = _run(tmp_path, {"jobs": [_job("FAILED", None, error="Es läuft bereits eine Reparatur <b>")]})
    html = out["els"]["genre-revalidation-content"]["html"]
    assert "Fehlgeschlagen: Es läuft bereits eine Reparatur" in html and "<b>" not in html
    assert out["els"]["genre-revalidation-preview-btn"]["disabled"] is False
