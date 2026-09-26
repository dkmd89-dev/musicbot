# -*- coding: utf-8 -*-
"""CC-LOGGER-L6.1/L6.2 — Controls in Panel 2 der /logger-Seite real
ausgefuehrt (node, Muster wie tests/test_control_center_subpath_ui.py).

Prueft das tatsaechliche Client-Verhalten von logger.js:
- gerenderte Level-Auswahl (genau die erlaubten Level, aktueller Wert
  vorausgewaehlt, ungueltiger persistierter Wert nicht auswaehlbar)
- gesendeter PATCH-Body (genau ein Feld)
- Zuruecksetzen des Controls bei Fehlschlag
"""
from __future__ import annotations

import json
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
global.document = {
  getElementById: (id) => (els[id] = els[id] || { innerHTML: "", addEventListener() {} }),
  querySelectorAll: () => [],
};
global.window = {};
global.apiUrl = (u) => u;
global._loadInto = async () => {};
global.checkAuth = () => Promise.resolve(null);
global.showOnly = () => {};
global._escapeHtml = (v) => (v == null ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;"));

const scenario = JSON.parse(process.argv[3]);
global.fetch = async (url, opts) => {
  calls.push({ url, method: opts && opts.method, body: opts && opts.body });
  return {
    status: scenario.status,
    ok: scenario.status === 200,
    json: async () => (scenario.status === 200
      ? { success: true }
      : { detail: { code: scenario.code || "X", message: "fail" } }),
  };
};

const src = fs.readFileSync(process.argv[2], "utf-8");
const api = new Function(src + "\nreturn { renderConfig, _loggerSetLevel, _loggerSetFileHandler };")();

function fakeControl(attrs, props) {
  return Object.assign({ getAttribute: (k) => (k in attrs ? attrs[k] : null) }, props);
}

(async () => {
  const out = {};
  const el = { innerHTML: "" };
  api.renderConfig(el, { modules: scenario.modules || {} });
  out.configHtml = el.innerHTML;

  if (scenario.action === "level") {
    const sel = fakeControl(
      { "data-module": "ModA", "data-current": scenario.previous },
      { value: scenario.wanted },
    );
    await api._loggerSetLevel(sel);
    out.valueAfter = sel.value;
  } else if (scenario.action === "file") {
    const cb = fakeControl({ "data-module": "ModA" }, { checked: scenario.wanted });
    await api._loggerSetFileHandler(cb);
    out.valueAfter = cb.checked;
  }
  out.calls = calls;
  out.status = (els["logger-config-status"] || {}).innerHTML || "";
  console.log(JSON.stringify(out));
})();
"""

pytestmark = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_MOD = {"enabled": True, "file_handler": True, "console_handler": True}


def _run(tmp_path: Path, scenario: dict) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(LOGGER_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _options(html: str) -> list:
    import re

    return re.findall(r'<option value="([^"]*)"', html)


def test_level_select_offers_exactly_allowed_levels_with_current_selected(tmp_path: Path) -> None:
    out = _run(tmp_path, {"status": 200, "modules": {"ModA": dict(_MOD, level="WARNING")}})
    html = out["configHtml"]
    assert _options(html) == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    assert '<option value="WARNING" selected>' in html
    assert html.count(" selected") == 1
    assert 'data-module="ModA"' in html
    assert 'data-current="WARNING"' in html


def test_level_select_shows_invalid_persisted_value_as_not_selectable(tmp_path: Path) -> None:
    out = _run(tmp_path, {"status": 200, "modules": {"ModA": dict(_MOD, level="TRACE")}})
    html = out["configHtml"]
    assert '<option value="" selected disabled>TRACE (ungueltig)</option>' in html
    # angeboten werden weiterhin nur die erlaubten Level
    assert [o for o in _options(html) if o] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_level_change_sends_patch_with_only_level(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "status": 200, "action": "level", "previous": "INFO", "wanted": "DEBUG",
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert len(out["calls"]) == 1
    call = out["calls"][0]
    assert call["url"] == "/api/v1/admin/logger/config"
    assert call["method"] == "PATCH"
    assert json.loads(call["body"]) == {"modules": {"ModA": {"level": "DEBUG"}}}
    assert out["valueAfter"] == "DEBUG"
    assert "Gespeichert — noch nicht aktiv" in out["status"]


def test_level_change_reverts_on_backend_rejection(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "status": 422, "code": "LOGGER_CONFIG_INVALID_LEVEL",
        "action": "level", "previous": "INFO", "wanted": "ERROR",
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert len(out["calls"]) == 1
    assert out["valueAfter"] == "INFO"
    assert "Ungueltiges Level" in out["status"]


def test_level_value_outside_whitelist_is_never_sent(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "status": 200, "action": "level", "previous": "INFO", "wanted": "TRACE",
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert out["calls"] == []
    assert out["valueAfter"] == "INFO"


def test_level_unchanged_value_sends_nothing(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "status": 200, "action": "level", "previous": "INFO", "wanted": "INFO",
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert out["calls"] == []


def test_file_toggle_still_sends_only_file_handler(tmp_path: Path) -> None:
    """L6.1-Regression nach dem Umbau auf den gemeinsamen PATCH-Pfad."""
    out = _run(tmp_path, {
        "status": 200, "action": "file", "wanted": False,
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert len(out["calls"]) == 1
    assert json.loads(out["calls"][0]["body"]) == {"modules": {"ModA": {"file_handler": False}}}
    assert out["valueAfter"] is False


def test_file_toggle_reverts_on_unknown_module(tmp_path: Path) -> None:
    out = _run(tmp_path, {
        "status": 422, "code": "LOGGER_CONFIG_UNKNOWN_MODULE", "action": "file", "wanted": False,
        "modules": {"ModA": dict(_MOD, level="INFO")},
    })
    assert out["valueAfter"] is True
    assert "Modul nicht in der persistierten Konfiguration" in out["status"]
