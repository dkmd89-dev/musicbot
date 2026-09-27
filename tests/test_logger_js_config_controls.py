# -*- coding: utf-8 -*-
"""CC-LOGGER-L6.1 Dashboard — Modulliste, Modul-Detailkarte, Entwurf/
Speichern/Zuruecksetzen, Runtime-Uebersicht und Apply-Darstellung der
/logger-Seite, real mit node ausgefuehrt (Muster wie
tests/test_control_center_subpath_ui.py).

Prueft das tatsaechliche Client-Verhalten von logger.js:
- Modulliste aus GET /config, Auswahl oeffnet die Detailkarte
- Level als Radio-Liste (genau die erlaubten Level, KEIN Dropdown)
- Eigene Log-Datei (`file_handler`) als Schalter, Entwurf ohne Request
- Speichern: genau ein PATCH mit genau den geaenderten Feldern
- Zuruecksetzen: persistierter Serverstand, kein Request
- Runtime-Snapshot available/missing/corrupt, startup_id/-Zeitstempel
- Desired-vs-Actual je Modul, kein Fake-Diff ohne Snapshot
- Apply: clear / blocked / unverified / Retry-After
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

LOGGER_JS = (
    Path(__file__).resolve().parent.parent
    / "control_center" / "static" / "pages" / "logger.js"
)

_NODE = shutil.which("node")

_HARNESS = r"""
const fs = require("fs");
const els = {};
const calls = [];
function mkEl() {
  return {
    innerHTML: "", className: "", textContent: "", disabled: false, value: "",
    addEventListener() {}, querySelectorAll: () => [], setAttribute() {},
    getAttribute: () => null, classList: { toggle() {}, contains: () => false },
  };
}
global.document = {
  getElementById: (id) => (els[id] = els[id] || mkEl()),
  querySelectorAll: () => [],
};
global.window = { confirm: () => true };
global.apiUrl = (u) => u;
global._loadInto = async () => {};
global.checkAuth = () => Promise.resolve(null);
global.showOnly = () => {};
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;"));
global.setInterval = () => 0;
global.clearInterval = () => {};

const scenario = JSON.parse(process.argv[3]);
const fx = scenario.fetch || { status: 200 };
global.fetch = async (url, opts) => {
  calls.push({ url, method: opts && opts.method, body: opts && opts.body,
               headers: opts && opts.headers, credentials: opts && opts.credentials });
  return {
    status: fx.status,
    ok: fx.status === 200,
    headers: { get: (k) => ((fx.headers || {})[k.toLowerCase()] || null) },
    json: async () => (fx.body !== undefined ? fx.body : { success: true }),
  };
};

const src = fs.readFileSync(process.argv[2], "utf-8");
const api = new Function(src + "\nreturn { _loggerState, renderConfig, renderRuntimeStatus, " +
  "_loggerSelectModule, _loggerOnDraftChange, _loggerSaveModule, _loggerResetModule, " +
  "_loggerRenderDetail, _loggerApply, _loggerComputeModuleDiff, _loggerHandlerKind };")();

(async () => {
  const out = { errors: [] };
  const listEl = document.getElementById("logger-config-content");
  if (scenario.modules) api.renderConfig(listEl, { modules: scenario.modules, total: 0 });
  if (scenario.runtime) {
    api.renderRuntimeStatus(document.getElementById("logger-runtime-content"), scenario.runtime);
  }
  for (const step of scenario.steps || []) {
    if (step.op === "select") api._loggerSelectModule(step.name);
    else if (step.op === "draft") api._loggerOnDraftChange(step.name, step.field, step.value);
    else if (step.op === "force_draft") api._loggerState.drafts[step.name] = step.fields;
    else if (step.op === "save") await api._loggerSaveModule();
    else if (step.op === "reset") api._loggerResetModule();
    else if (step.op === "apply") await api._loggerApply();
  }
  const g = (id) => document.getElementById(id);
  out.list = listEl.innerHTML;
  out.detail = g("logger-module-detail").innerHTML;
  out.configStatus = g("logger-config-status").innerHTML;
  out.applyStatus = g("logger-apply-status").innerHTML;
  out.kpi = g("logger-runtime-kpi").innerHTML;
  out.runtimeContent = g("logger-runtime-content").innerHTML;
  out.startup = g("logger-startup-content").innerHTML;
  out.saveDisabled = g("logger-save-btn").disabled;
  out.resetDisabled = g("logger-reset-btn").disabled;
  out.drafts = api._loggerState.drafts;
  out.persisted = api._loggerState.config && api._loggerState.config.modules;
  out.calls = calls;
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""

pytestmark = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_MOD = {"enabled": True, "file_handler": True, "console_handler": True}
_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_STARTUP_ID = "131f7d2e7b57a1c94e0d8b6a5c3f2e10"
_APPLIED_AT = "2026-09-27T02:18:56.524395+00:00"


def _run(tmp_path: Path, scenario: dict) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(LOGGER_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crash" not in out, out.get("crash")
    return out


def _mods(**overrides) -> dict:
    mods = {
        "ModA": dict(_MOD, level="INFO"),
        "ModB": dict(_MOD, level="DEBUG", file_handler=False),
    }
    mods.update(overrides)
    return mods


def _runtime(levels=None, handlers=None, disabled=None) -> dict:
    return {
        "status": "available",
        "snapshot": {
            "schema_version": 1,
            "startup_id": _STARTUP_ID,
            "runtime_applied_at": _APPLIED_AT,
            "root_level": "INFO",
            "effective_levels": levels if levels is not None else {"ModA": "INFO", "ModB": "DEBUG"},
            "handlers": handlers if handlers is not None else {
                "ModA": ["EnhancedRotatingFileHandler", "StreamHandler"],
                "ModB": ["StreamHandler"],
            },
            "disabled": disabled or [],
        },
    }


def _radio_values(html: str) -> list:
    return re.findall(r'<input type="radio"[^>]*value="([^"]*)"', html)


# ---------------------------------------------------------------------
# Modulliste + Auswahl
# ---------------------------------------------------------------------

def test_module_list_shows_all_configured_modules_with_level_and_file_state(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods()})
    assert out["list"].count("logger-module-item") == 2
    assert 'data-module="ModA"' in out["list"]
    assert 'data-module="ModB"' in out["list"]
    assert ">INFO<" in out["list"] and ">DEBUG<" in out["list"]
    assert "Datei" in out["list"] and "keine Datei" in out["list"]


def test_module_list_marks_disabled_module(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(ModC=dict(_MOD, level="INFO", enabled=False))})
    assert "disabled" in out["list"]


def test_empty_config_shows_empty_state_and_no_detail(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": {}})
    assert "Keine persistierte Konfiguration vorhanden" in out["list"]
    assert "logger-level-radio" not in out["detail"]


def test_no_selection_shows_prompt_not_detail_card(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods()})
    assert "Modul in der Liste auswählen" in out["detail"]
    assert "logger-level-radio" not in out["detail"]
    assert out["saveDisabled"] is True and out["resetDisabled"] is True


def test_selecting_module_opens_detail_card(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "ModA"}]})
    assert "Logger-Modul" in out["detail"]
    assert ">ModA<" in out["detail"]
    assert "Persistiert" in out["detail"]


def test_selecting_unknown_module_is_ignored(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "Nope"}]})
    assert "Modul in der Liste auswählen" in out["detail"]


# ---------------------------------------------------------------------
# Level: Radio-Liste, kein Dropdown
# ---------------------------------------------------------------------

def test_level_is_radio_list_with_exactly_allowed_levels_and_no_dropdown(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "modules": {"ModA": dict(_MOD, level="WARNING")},
        "steps": [{"op": "select", "name": "ModA"}],
    })
    html = out["detail"]
    assert _radio_values(html) == _LEVELS
    assert "<select" not in html and "<option" not in html
    # aktueller (persistierter) Wert vorausgewaehlt, genau einer
    assert len(re.findall(r'<input type="radio"[^>]*\schecked', html)) == 1
    assert re.search(r'value="WARNING"[^>]*\schecked', html)


def test_invalid_persisted_level_is_shown_honestly_and_not_preselected(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "modules": {"ModA": dict(_MOD, level="TRACE")},
        "steps": [{"op": "select", "name": "ModA"}],
    })
    html = out["detail"]
    assert "Persistiertes Level ungültig" in html
    assert "TRACE" in html
    assert _radio_values(html) == _LEVELS  # keine erfundenen Werte
    assert not re.search(r'<input type="radio"[^>]*\schecked', html)
    # Ungueltiger Wert ist kein Entwurf -> nichts zu speichern
    assert out["saveDisabled"] is True


# ---------------------------------------------------------------------
# Eigene Log-Datei (file_handler)
# ---------------------------------------------------------------------

def test_file_switch_reflects_persisted_state(tmp_path: Path) -> None:
    on = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    off = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "ModB"}]})["detail"]
    assert re.search(r'logger-file-toggle"[^>]*\schecked', on)
    assert "Aktiv</strong>" in on
    assert not re.search(r'logger-file-toggle"[^>]*\schecked', off)
    assert "Deaktiviert</strong>" in off


def test_file_switch_states_that_restart_is_required(tmp_path: Path) -> None:
    html = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "erst nach „Konfiguration anwenden“" in html
    assert "Bot-Neustart" in html


def test_console_is_shown_read_only(tmp_path: Path) -> None:
    html = _run(tmp_path, {"modules": _mods(), "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "Console" in html
    assert "hier nicht änderbar" in html


# ---------------------------------------------------------------------
# Entwurf / Speichern / Zuruecksetzen
# ---------------------------------------------------------------------

def test_draft_change_sends_no_request_and_enables_save_reset(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "DEBUG"},
    ]})
    assert out["calls"] == []
    assert out["drafts"] == {"ModA": {"level": "DEBUG"}}
    assert out["saveDisabled"] is False and out["resetDisabled"] is False


def test_draft_back_to_persisted_value_is_not_dirty(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "DEBUG"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "INFO"},
    ]})
    assert out["drafts"] == {}
    assert out["saveDisabled"] is True


def test_save_level_sends_single_patch_with_only_level(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "DEBUG"},
        {"op": "save"},
    ]})
    assert len(out["calls"]) == 1
    call = out["calls"][0]
    assert call["url"] == "/api/v1/admin/logger/config"
    assert call["method"] == "PATCH"
    assert json.loads(call["body"]) == {"modules": {"ModA": {"level": "DEBUG"}}}
    # Auth/CSRF-Verhalten unveraendert
    assert call["credentials"] == "same-origin"
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert call["headers"]["Content-Type"] == "application/json"


def test_save_file_handler_sends_single_patch_with_only_file_handler(tmp_path: Path) -> None:
    for wanted in (False, True):
        mod = "ModA" if wanted is False else "ModB"
        out = _run(tmp_path, {"modules": _mods(), "steps": [
            {"op": "select", "name": mod},
            {"op": "draft", "name": mod, "field": "file_handler", "value": wanted},
            {"op": "save"},
        ]})
        assert len(out["calls"]) == 1
        assert out["calls"][0]["method"] == "PATCH"
        assert json.loads(out["calls"][0]["body"]) == {"modules": {mod: {"file_handler": wanted}}}


def test_save_both_fields_is_one_patch_with_both_changed_fields(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
        {"op": "draft", "name": "ModA", "field": "file_handler", "value": False},
        {"op": "save"},
    ]})
    assert len(out["calls"]) == 1
    assert json.loads(out["calls"][0]["body"]) == {
        "modules": {"ModA": {"level": "ERROR", "file_handler": False}}
    }


def test_save_never_sends_enabled_or_console_handler(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
        {"op": "draft", "name": "ModA", "field": "file_handler", "value": False},
        {"op": "save"},
    ]})
    sent = json.loads(out["calls"][0]["body"])["modules"]["ModA"]
    assert set(sent) <= {"level", "file_handler"}


def test_save_success_says_saved_but_not_active_and_clears_draft(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "DEBUG"},
        {"op": "save"},
    ]})
    assert "Änderungen gespeichert. Noch nicht aktiv." in out["configStatus"]
    assert "Der laufende Bot wurde nicht verändert" in out["configStatus"]
    assert out["drafts"] == {}
    assert out["persisted"]["ModA"]["level"] == "DEBUG"
    assert out["saveDisabled"] is True
    # Speichern loest keinen Restart aus: kein Apply-Aufruf
    assert all("/apply" not in c["url"] for c in out["calls"])


def test_save_rejection_keeps_draft_and_shows_no_success(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "modules": _mods(),
        "fetch": {"status": 422, "body": {"detail": {"code": "LOGGER_CONFIG_INVALID_LEVEL", "message": "fail"}}},
        "steps": [
            {"op": "select", "name": "ModA"},
            {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
            {"op": "save"},
        ],
    })
    assert "Ungültiges Level" in out["configStatus"]
    assert "gespeichert" not in out["configStatus"].lower().replace("nicht gespeichert", "")
    assert out["drafts"] == {"ModA": {"level": "ERROR"}}
    assert out["persisted"]["ModA"]["level"] == "INFO"


def test_save_unknown_module_is_reported(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "modules": _mods(),
        "fetch": {"status": 422, "body": {"detail": {"code": "LOGGER_CONFIG_UNKNOWN_MODULE", "message": "x"}}},
        "steps": [
            {"op": "select", "name": "ModA"},
            {"op": "draft", "name": "ModA", "field": "file_handler", "value": False},
            {"op": "save"},
        ],
    })
    assert "Modul nicht in der persistierten Konfiguration" in out["configStatus"]


def test_save_forbidden_shows_csrf_hint(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "modules": _mods(), "fetch": {"status": 403},
        "steps": [
            {"op": "select", "name": "ModA"},
            {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
            {"op": "save"},
        ],
    })
    assert "Zugriff verweigert" in out["configStatus"]
    assert out["drafts"] == {"ModA": {"level": "ERROR"}}


def test_level_outside_whitelist_is_never_sent(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "force_draft", "name": "ModA", "fields": {"level": "TRACE"}},
        {"op": "save"},
    ]})
    assert out["calls"] == []


def test_save_without_draft_sends_nothing(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"}, {"op": "save"},
    ]})
    assert out["calls"] == []


def test_reset_restores_persisted_state_without_request(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "CRITICAL"},
        {"op": "draft", "name": "ModA", "field": "file_handler", "value": False},
        {"op": "reset"},
    ]})
    assert out["calls"] == []
    assert out["drafts"] == {}
    html = out["detail"]
    assert re.search(r'value="INFO"[^>]*\schecked', html)
    assert re.search(r'logger-file-toggle"[^>]*\schecked', html)
    assert out["saveDisabled"] is True and out["resetDisabled"] is True


def test_reset_uses_persisted_state_not_runtime_state(tmp_path: Path) -> None:
    """Runtime sagt DEBUG, persistiert ist INFO -> Reset zeigt INFO."""
    out = _run(tmp_path, {
        "modules": {"ModA": dict(_MOD, level="INFO")},
        "runtime": _runtime(levels={"ModA": "DEBUG"}, handlers={"ModA": ["StreamHandler"]}),
        "steps": [
            {"op": "select", "name": "ModA"},
            {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
            {"op": "reset"},
        ],
    })
    assert re.search(r'value="INFO"[^>]*\schecked', out["detail"])
    assert not re.search(r'value="DEBUG"[^>]*\schecked', out["detail"])


# ---------------------------------------------------------------------
# Runtime-Uebersicht / Snapshot
# ---------------------------------------------------------------------

def test_runtime_available_shows_root_level_module_count_and_startup(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": _runtime()})
    assert "Root-Level" in out["kpi"] and ">INFO<" in out["kpi"]
    assert "Module" in out["kpi"] and ">2<" in out["kpi"]
    assert "Letzter Startup" in out["kpi"]
    assert _APPLIED_AT in out["kpi"]  # title-Attribut mit exaktem Zeitstempel
    assert "Zustand nach dem letzten erfolgreichen Bot-Start" in out["runtimeContent"]
    assert _APPLIED_AT in out["runtimeContent"]
    assert 'title="' + _STARTUP_ID + '"' in out["runtimeContent"]


def test_startup_card_shows_formatted_utc_time_and_full_startup_id(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": _runtime()})
    assert "27.09.2026 02:18:56 UTC" in out["startup"]
    assert _STARTUP_ID in out["startup"]  # vollstaendig, nicht abgeschnitten
    assert "Kein Live-Zustand" in out["startup"]


def test_runtime_missing_shows_no_fake_values(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": {"status": "missing"}})
    assert out["kpi"] == ""
    assert "Kein Runtime-Snapshot vorhanden" in out["runtimeContent"]
    assert "Nicht verfügbar" in out["startup"]
    assert _STARTUP_ID not in out["startup"]


def test_runtime_corrupt_shows_error_state(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": {"status": "corrupt", "message": "kaputt <b>"}})
    assert out["kpi"] == ""
    assert "Snapshot unlesbar" in out["runtimeContent"]
    assert "alert-danger" in out["runtimeContent"]
    assert "kaputt &lt;b&gt;" in out["runtimeContent"]  # escaped
    assert "Fehlerhaft" in out["startup"]


def test_runtime_view_never_claims_live_state(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": _runtime(), "steps": [{"op": "select", "name": "ModA"}]})
    combined = out["kpi"] + out["runtimeContent"] + out["startup"] + out["detail"]
    assert "Kein Live-Zustand" in combined
    assert "Snapshot, kein Live-Zustand" in out["detail"]
    for phrase in ("live aktiv", "jetzt aktiv", "sofort aktiv"):
        assert phrase not in combined.lower()


def test_snapshot_modules_without_persisted_config_are_hinted(tmp_path: Path) -> None:
    rt = _runtime(levels={"ModA": "INFO", "ModB": "DEBUG", "Orphan": "INFO"})
    out = _run(tmp_path, {"modules": _mods(), "runtime": rt})
    assert "1 Snapshot-Modul(e) ohne persistierte Konfiguration" in out["runtimeContent"]


# ---------------------------------------------------------------------
# Desired vs. Actual (je Modul)
# ---------------------------------------------------------------------

def test_detail_without_snapshot_says_unknown_not_a_false_diff(tmp_path: Path) -> None:
    for runtime in (None, {"status": "missing"}, {"status": "corrupt", "message": "x"}):
        scenario = {"modules": _mods(), "steps": [{"op": "select", "name": "ModA"}]}
        if runtime:
            scenario["runtime"] = runtime
        html = _run(tmp_path, scenario)["detail"]
        assert "Runtime-Zustand" in html
        assert "Abweichung" not in html
        assert "identisch" not in html
    html = _run(tmp_path, {"modules": _mods(), "runtime": {"status": "missing"},
                           "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "Runtime-Zustand unbekannt" in html


def test_detail_identical_to_runtime(tmp_path: Path) -> None:
    html = _run(tmp_path, {"modules": _mods(), "runtime": _runtime(),
                           "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "identisch" in html
    assert "Abweichung" not in html
    assert "FileHandler: vorhanden" in html


def test_detail_file_handler_deviation_is_reported(tmp_path: Path) -> None:
    """Persistiert file_handler=true, Runtime noch ohne Datei-Handler."""
    rt = _runtime(handlers={"ModA": ["StreamHandler"], "ModB": ["StreamHandler"]})
    html = _run(tmp_path, {"modules": _mods(), "runtime": rt,
                           "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "⚠ Abweichung" in html
    assert "Konfiguration wurde noch nicht angewendet" in html
    assert "file_handler: aus → an" in html
    assert "FileHandler: nicht vorhanden" in html


def test_detail_module_missing_in_snapshot_is_not_an_error(tmp_path: Path) -> None:
    rt = _runtime(levels={"ModB": "DEBUG"}, handlers={"ModB": ["StreamHandler"]})
    html = _run(tmp_path, {"modules": _mods(), "runtime": rt,
                           "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "Nicht im letzten Runtime-Snapshot vorhanden" in html
    assert "alert-danger" not in html
    assert "Abweichung" not in html


def test_diff_compares_persisted_state_not_the_unsaved_draft(tmp_path: Path) -> None:
    out = _run(tmp_path, {"modules": _mods(), "runtime": _runtime(), "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "CRITICAL"},
    ]})
    # Der Entwurf aendert Desired-vs-Actual nicht — erst Speichern persistiert.
    assert "identisch" in out["detail"]
    assert "⚠ Abweichung" not in out["detail"]


def test_file_handler_subclasses_count_as_file_handler(tmp_path: Path) -> None:
    """Regression (Diff-Fix L6.1 §7): EnhancedRotatingFileHandler ist eine
    Datei — kein False Positive 'aus -> an'."""
    html = _run(tmp_path, {"modules": _mods(), "runtime": _runtime(),
                           "steps": [{"op": "select", "name": "ModA"}]})["detail"]
    assert "file_handler" not in html.split("Runtime nach letztem Startup")[1]
    assert "identisch" in html


# ---------------------------------------------------------------------
# Apply-Darstellung
# ---------------------------------------------------------------------

_PF_BASE = {"checked": {"repair_lock": True}, "message": "PF-Meldung"}


def _apply(tmp_path: Path, fetch: dict) -> dict:
    return _run(tmp_path, {"modules": _mods(), "fetch": fetch, "steps": [{"op": "apply"}]})


def test_apply_uses_existing_endpoint_with_csrf_header(tmp_path: Path) -> None:
    out = _apply(tmp_path, {"status": 200, "body": {
        "status": "applied", "message": "ok",
        "preflight": dict(_PF_BASE, status="clear", active={"repair": False}, unverified=[]),
    }})
    assert len(out["calls"]) == 1
    call = out["calls"][0]
    assert call["url"] == "/api/v1/admin/logger/apply"
    assert call["method"] == "POST"
    assert call["credentials"] == "same-origin"
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_apply_clear_does_not_claim_everything_was_checked(tmp_path: Path) -> None:
    html = _apply(tmp_path, {"status": 200, "body": {
        "status": "applied", "message": "ok",
        "preflight": dict(_PF_BASE, status="clear", active={"repair": False}, unverified=[]),
    }})["applyStatus"]
    assert "✓ Keine bekannte kritische Aktivität erkannt" in html
    assert "Konfiguration kann angewendet werden" in html
    assert "alert-success" in html
    assert "alle Aktivitäten" not in html.lower()
    assert "alle bot-aktivitäten" not in html.lower()


def test_apply_unverified_lists_activities_and_is_never_shown_as_clear(tmp_path: Path) -> None:
    html = _apply(tmp_path, {"status": 200, "body": {
        "status": "applied", "message": "ok",
        "preflight": dict(_PF_BASE, status="unverified", active={"repair": False},
                          unverified=["downloads", "backups"]),
    }})["applyStatus"]
    assert "⚠ Konfiguration kann angewendet werden" in html
    assert "Der Repair-Lock ist frei" in html
    assert "<li>Downloads</li>" in html and "<li>Backups</li>" in html
    assert "nicht zuverlässig live geprüft" in html
    assert "Der Bot wird kontrolliert neu gestartet" in html
    assert "alert-warning" in html
    assert "alert-success" not in html
    assert "Keine bekannte kritische Aktivität" not in html


def test_apply_blocked_409_is_error_state_without_success(tmp_path: Path) -> None:
    html = _apply(tmp_path, {"status": 409, "body": {"detail": {
        "code": "LOGGER_APPLY_BLOCKED", "message": "x",
        "preflight": dict(_PF_BASE, status="blocked", active={"repair": True}, unverified=[]),
    }}})["applyStatus"]
    assert "⚠ Anwendung blockiert" in html
    assert "alert-danger" in html
    assert "Repair-/Maintenance-Lauf wurde erkannt" in html
    assert "PF-Meldung" in html  # konkrete Aktivitaet/Meldung des Preflight
    assert "Der Bot wird nicht neu gestartet" in html
    assert "alert-success" not in html
    assert "geplant" not in html.lower()


def test_apply_rate_limit_shows_retry_after_seconds(tmp_path: Path) -> None:
    html = _apply(tmp_path, {"status": 429, "headers": {"retry-after": "12"},
                             "body": {"detail": {"code": "LOGGER_APPLY_RATE_LIMITED", "message": "zu schnell"}}})["applyStatus"]
    assert "⏳ Zu viele Anfragen" in html
    assert "Bitte noch <strong id=\"logger-rate-limit-countdown\">12</strong> Sekunden warten" in html


def test_apply_forbidden_shows_csrf_hint(tmp_path: Path) -> None:
    html = _apply(tmp_path, {"status": 403})["applyStatus"]
    assert "Zugriff verweigert" in html


def test_apply_confirm_warns_about_unsaved_changes(tmp_path: Path) -> None:
    """Apply wendet nur den PERSISTIERTEN Stand an — ungespeicherte Entwuerfe
    duerfen nicht still unter den Tisch fallen."""
    script = _HARNESS.replace(
        "global.window = { confirm: () => true };",
        "global.window = { confirm: (m) => { global.__confirm = m; return true; } };",
    ).replace("out.calls = calls;", "out.calls = calls; out.confirm = global.__confirm;")
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    scenario = {"modules": _mods(), "fetch": {"status": 403}, "steps": [
        {"op": "select", "name": "ModA"},
        {"op": "draft", "name": "ModA", "field": "level", "value": "ERROR"},
        {"op": "apply"},
    ]}
    result = subprocess.run(
        [_NODE, str(path), str(LOGGER_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "ungespeicherte Änderungen" in out["confirm"]
    assert "NICHT angewendet" in out["confirm"]
