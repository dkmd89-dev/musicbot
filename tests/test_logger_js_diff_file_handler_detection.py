# -*- coding: utf-8 -*-
"""CC-LOGGER-L6 Diff-Fix (Befund aus CC-LOGGER-L6.1 §7).

`control_center/static/pages/logger.js` (Diff-Berechnung, seit dem
Dashboard-Umbau `_loggerComputeModuleDiff()`) erkannte eine
Runtime-Log-Datei nur am exakten Typnamen "FileHandler". Module mit
eigener Datei ueber `logger.py::setup_module_logging()` tragen im
Snapshot aber "EnhancedRotatingFileHandler" (Unterklasse von
logging.FileHandler) und galten in Panel 3 als "ohne Log-Datei":

- Config file_handler=true  -> falsche Abweichung "aus -> an"
- Config file_handler=false -> echte Abweichung verschluckt
  (real verifiziert: EnhancedMetadataProcessor, Snapshot 2026-09-26)

logger.js wird hier real mit node ausgefuehrt (Muster wie
tests/test_control_center_subpath_ui.py), DOM/common.js-Helfer sind
minimal gestubbt.
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
global.document = {
  getElementById: (id) => (els[id] = els[id] || { innerHTML: "", addEventListener() {} }),
  querySelectorAll: () => [],
};
global.window = {};
global.apiUrl = (u) => u;
global._loadInto = async () => {};
global.checkAuth = () => Promise.resolve(null);
global.showOnly = () => {};
global._escapeHtml = (v) => (v == null ? "" : String(v));

const src = fs.readFileSync(process.argv[2], "utf-8");
const cases = JSON.parse(process.argv[3]);
const api = new Function(src + "\nreturn { _loggerComputeModuleDiff, _loggerHandlerKind };")();

const out = { kinds: {}, diffs: [] };
for (const name of ["FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler",
                    "WatchedFileHandler", "EnhancedRotatingFileHandler",
                    "StreamHandler", "NullHandler"]) {
  out.kinds[name] = api._loggerHandlerKind(name);
}
for (const c of cases) {
  const runtime = {
    status: "available",
    snapshot: {
      effective_levels: { Mod: "INFO" },
      handlers: { Mod: c.handlers },
      disabled: [],
    },
  };
  const config = {
    modules: { Mod: { enabled: true, level: "INFO",
                      file_handler: c.file_handler, console_handler: c.console_handler } },
  };
  out.diffs.push(api._loggerComputeModuleDiff("Mod", runtime, config));
}
console.log(JSON.stringify(out));
"""


def _run(tmp_path: Path, cases: list) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(LOGGER_JS), json.dumps(cases)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")



def test_handler_kind_classifies_all_file_handler_subclasses(tmp_path: Path) -> None:
    kinds = _run(tmp_path, [])["kinds"]
    for name in ("FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler",
                 "WatchedFileHandler", "EnhancedRotatingFileHandler"):
        assert kinds[name] == "file", name
    assert kinds["StreamHandler"] == "stream"
    assert kinds["NullHandler"] == "other"


def test_rotating_file_handler_with_config_true_is_not_reported(tmp_path: Path) -> None:
    """Vorher False Positive 'file_handler: aus -> an'."""
    out = _run(tmp_path, [{
        "handlers": ["EnhancedRotatingFileHandler", "StreamHandler"],
        "file_handler": True, "console_handler": True,
    }])
    assert out["diffs"][0] == {"status": "identical", "changes": []}


def test_rotating_file_handler_with_config_false_is_reported(tmp_path: Path) -> None:
    """Realfall EnhancedMetadataProcessor: vorher verschluckt (False Negative)."""
    out = _run(tmp_path, [{
        "handlers": ["EnhancedRotatingFileHandler", "StreamHandler"],
        "file_handler": False, "console_handler": True,
    }])
    assert out["diffs"][0]["status"] == "differs"
    assert "file_handler: an → aus" in out["diffs"][0]["changes"]


def test_plain_file_handler_behaviour_unchanged(tmp_path: Path) -> None:
    out = _run(tmp_path, [
        {"handlers": ["FileHandler", "StreamHandler"], "file_handler": True, "console_handler": True},
        {"handlers": ["StreamHandler"], "file_handler": True, "console_handler": True},
        {"handlers": ["FileHandler", "StreamHandler"], "file_handler": False, "console_handler": True},
    ])
    assert out["diffs"][0]["status"] == "identical"
    assert "file_handler: aus → an" in out["diffs"][1]["changes"]
    assert "file_handler: an → aus" in out["diffs"][2]["changes"]


def test_rotating_file_handler_is_not_counted_as_console(tmp_path: Path) -> None:
    """Datei-Handler darf nicht als Console-Handler durchgehen."""
    out = _run(tmp_path, [{
        "handlers": ["EnhancedRotatingFileHandler"],
        "file_handler": True, "console_handler": True,
    }])
    assert out["diffs"][0]["changes"] == ["console_handler: aus → an"]
