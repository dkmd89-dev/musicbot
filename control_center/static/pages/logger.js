// control_center/static/pages/logger.js
// Logger-Seite: Runtime-Uebersicht, Modulliste, Modul-Detailkarte
// (persistierte Konfiguration bearbeiten, Desired-vs-Actual) und
// kontrollierter Bot-Neustart.
//
// L6 (CC-LOGGER-L6): Runtime-Status + Config + Diff + Apply.
// L6.1/L6.2: Level und eigene Log-Datei (`file_handler`) pro Modul ueber das
//       bestehende PATCH /api/v1/admin/logger/config. Wirksam erst nach
//       "Konfiguration anwenden" (Bot-Neustart) — kein Live-Control (L3).
// L6.1 Dashboard: Module auswaehlen -> Detailkarte -> Aenderungen als Entwurf
//       (Draft) sammeln -> "Aenderungen speichern" (ein PATCH pro Modul mit
//       genau den geaenderten Feldern) -> "Zuruecksetzen" verwirft den Entwurf
//       lokal (kein Request) -> "Konfiguration anwenden".
//
// Nutzt die gemeinsamen Helfer aus common.js
// (apiUrl(), _loadInto(), _escapeHtml(), checkAuth()).

// =====================================================================
// State
// =====================================================================
const _loggerState = {
  runtime: null,   // Antwort von GET /runtime-status (Snapshot, kein Live-Zustand)
  config: null,    // Antwort von GET /config (zuletzt vom Server geladen)
  selected: null,  // Name des ausgewaehlten Moduls
  drafts: {},      // { modul: { level?, file_handler? } } — nur ungespeicherte Abweichungen
  saving: false,
  filter: "",
};

// Exakt services/logger_admin.py::ALLOWED_LOG_LEVELS, in der Reihenfolge
// von EnhancedLoggerMenuHandler.log_levels (aufsteigende Schwere).
// GET /config liefert die Liste nicht mit; der Gleichlauf wird durch
// tests/test_control_center_ui.py gepinnt.
const LOGGER_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

// =====================================================================
// Helper
// =====================================================================
function _loggerTimeAgo(isoString) {
  if (!isoString) return "–";
  try {
    const dt = new Date(isoString);
    if (isNaN(dt.getTime())) return isoString;
    const seconds = Math.floor((Date.now() - dt.getTime()) / 1000);
    if (seconds < 0) return isoString;
    if (seconds < 60) return "vor " + seconds + "s";
    if (seconds < 3600) return "vor " + Math.floor(seconds / 60) + "min";
    if (seconds < 86400) return "vor " + Math.floor(seconds / 3600) + "h";
    return "vor " + Math.floor(seconds / 86400) + "d";
  } catch (e) {
    return isoString;
  }
}

function _loggerPad2(n) {
  return (n < 10 ? "0" : "") + n;
}

// "27.09.2026 02:18:56 UTC" — der Snapshot-Zeitstempel ist UTC.
function _loggerFormatUtc(isoString) {
  if (!isoString) return "–";
  const dt = new Date(isoString);
  if (isNaN(dt.getTime())) return String(isoString);
  return _loggerPad2(dt.getUTCDate()) + "." + _loggerPad2(dt.getUTCMonth() + 1) + "." +
    dt.getUTCFullYear() + " " + _loggerPad2(dt.getUTCHours()) + ":" +
    _loggerPad2(dt.getUTCMinutes()) + ":" + _loggerPad2(dt.getUTCSeconds()) + " UTC";
}

function _loggerHandlerKind(handlerName) {
  // Der Snapshot enthaelt nur type(h).__name__, keine Klassenhierarchie.
  // Alle logging.FileHandler-Unterklassen enden per Konvention auf
  // "FileHandler" (RotatingFileHandler, TimedRotatingFileHandler,
  // WatchedFileHandler, logger.py::EnhancedRotatingFileHandler) —
  // identisch zur isinstance(h, logging.FileHandler)-Pruefung in
  // ModuleLoggerManager._apply_module_config(). Muss vor dem
  // StreamHandler-Zweig stehen (FileHandler erbt von StreamHandler).
  if (/FileHandler$/.test(handlerName)) return "file";
  if (handlerName.indexOf("StreamHandler") !== -1) return "stream";
  return "other";
}

function _loggerHas(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function _loggerPersistedModule(name) {
  const modules = (_loggerState.config && _loggerState.config.modules) || {};
  return _loggerHas(modules, name) ? (modules[name] || {}) : null;
}

// Persistierter Wert (Server) — mit den Backend-Defaults des Schemas.
function _loggerPersistedValues(name) {
  const m = _loggerPersistedModule(name) || {};
  return {
    level: m.level || "INFO",
    file_handler: !!m.file_handler,
  };
}

// Effektiver Anzeige-/Entwurfswert: Draft ueberlagert den persistierten Stand.
function _loggerEffectiveValues(name) {
  const base = _loggerPersistedValues(name);
  const d = _loggerState.drafts[name] || {};
  return {
    level: _loggerHas(d, "level") ? d.level : base.level,
    file_handler: _loggerHas(d, "file_handler") ? d.file_handler : base.file_handler,
  };
}

function _loggerIsDirty(name) {
  const d = _loggerState.drafts[name];
  return !!d && Object.keys(d).length > 0;
}

function _loggerAnyDirty() {
  return Object.keys(_loggerState.drafts).some(_loggerIsDirty);
}

// Entwurf pflegen: nur echte Abweichungen vom persistierten Stand behalten.
function _loggerSetDraftField(name, field, value) {
  const base = _loggerPersistedValues(name);
  const d = Object.assign({}, _loggerState.drafts[name] || {});
  if (value === base[field]) {
    delete d[field];
  } else {
    d[field] = value;
  }
  if (Object.keys(d).length) {
    _loggerState.drafts[name] = d;
  } else {
    delete _loggerState.drafts[name];
  }
}

function _loggerPruneDrafts() {
  Object.keys(_loggerState.drafts).forEach(function(name) {
    if (_loggerPersistedModule(name) === null) {
      delete _loggerState.drafts[name];
      return;
    }
    const base = _loggerPersistedValues(name);
    const d = Object.assign({}, _loggerState.drafts[name]);
    Object.keys(d).forEach(function(field) {
      if (d[field] === base[field]) delete d[field];
    });
    if (Object.keys(d).length) {
      _loggerState.drafts[name] = d;
    } else {
      delete _loggerState.drafts[name];
    }
  });
}

// =====================================================================
// Desired vs. Actual (pure Berechnung, kein Request)
// =====================================================================
//
// Desired  = persistierte Konfiguration (Server-Stand, NICHT der Entwurf).
// Actual   = Runtime-Snapshot nach dem letzten erfolgreichen Bot-Start.
//
// Rueckgabe.status:
//   "unknown"         — kein (gueltiger) Runtime-Snapshot: Runtime-Zustand
//                       unbekannt, KEIN Diff
//   "not_in_config"   — Modul nicht persistiert
//   "not_in_runtime"  — Modul steht in der Config, nicht im Snapshot
//   "identical"       — keine Abweichung
//   "differs"         — `changes` enthaelt die Abweichungen (actual -> desired)
function _loggerComputeModuleDiff(name, runtime, config) {
  const cfgModules = (config && config.modules) || {};
  if (!_loggerHas(cfgModules, name)) {
    return { status: "not_in_config", changes: [] };
  }
  if (!runtime || runtime.status !== "available") {
    return { status: "unknown", changes: [] };
  }
  const snap = runtime.snapshot || {};
  const rtLevels = snap.effective_levels || {};
  const rtHandlers = snap.handlers || {};
  const rtDisabled = new Set(snap.disabled || []);

  if (!_loggerHas(rtLevels, name)) {
    return { status: "not_in_runtime", changes: [] };
  }

  const cfgM = cfgModules[name] || {};
  const rtLevel = rtLevels[name];
  const cfgLevel = cfgM.level || "INFO";
  const handlerList = rtHandlers[name] || [];
  const rtHasFile = handlerList.some(function(h) { return _loggerHandlerKind(h) === "file"; });
  const rtHasConsole = handlerList.some(function(h) { return _loggerHandlerKind(h) === "stream"; });
  const wantFile = !!cfgM.file_handler;
  const wantConsole = !!cfgM.console_handler;
  const rtIsDisabled = rtDisabled.has(name);
  const wantDisabled = cfgM.enabled === false;

  const changes = [];
  if (rtLevel !== cfgLevel) {
    changes.push("level: <code>" + _escapeHtml(rtLevel) + "</code> → <code>" + _escapeHtml(cfgLevel) + "</code>");
  }
  if (rtHasFile !== wantFile) {
    changes.push("file_handler: " + (rtHasFile ? "an" : "aus") + " → " + (wantFile ? "an" : "aus"));
  }
  if (rtHasConsole !== wantConsole) {
    changes.push("console_handler: " + (rtHasConsole ? "an" : "aus") + " → " + (wantConsole ? "an" : "aus"));
  }
  if (rtIsDisabled !== wantDisabled) {
    changes.push("enabled: " + (!rtIsDisabled ? "an" : "aus") + " → " + (!wantDisabled ? "an" : "aus"));
  }
  return { status: changes.length ? "differs" : "identical", changes: changes };
}

// Runtime-Sicht eines Moduls fuer die Detailkarte (nur Snapshot-Daten).
function _loggerRuntimeModuleView(name) {
  const rt = _loggerState.runtime;
  if (!rt || rt.status !== "available") return null;
  const snap = rt.snapshot || {};
  const levels = snap.effective_levels || {};
  if (!_loggerHas(levels, name)) return { present: false };
  const handlers = (snap.handlers || {})[name] || [];
  return {
    present: true,
    level: levels[name],
    file: handlers.some(function(h) { return _loggerHandlerKind(h) === "file"; }),
    console: handlers.some(function(h) { return _loggerHandlerKind(h) === "stream"; }),
    disabled: new Set(snap.disabled || []).has(name),
  };
}

// =====================================================================
// Runtime-Uebersicht
// =====================================================================
function _loggerKpiCol(label, valueHtml, title) {
  return '<div class="col-sm-4"><div class="subheader">' + _escapeHtml(label) + '</div>' +
    '<div class="h1 mb-0"' + (title ? ' title="' + _escapeHtml(title) + '"' : '') + '>' +
    valueHtml + '</div></div>';
}

function renderRuntimeStatus(el, body) {
  _loggerState.runtime = body;
  const kpiEl = document.getElementById("logger-runtime-kpi");
  const startupEl = document.getElementById("logger-startup-content");
  if (!kpiEl) return;

  if (body.status === "missing") {
    kpiEl.innerHTML = "";
    el.innerHTML = '<div class="alert alert-secondary mb-0"><div><div class="alert-title">Kein Runtime-Snapshot vorhanden</div>' +
      '<div class="text-secondary">Er wird beim nächsten erfolgreichen Bot-Start geschrieben. ' +
      'Der Runtime-Zustand ist bis dahin unbekannt.</div></div></div>';
    if (startupEl) startupEl.innerHTML = '<p class="empty-note mb-0">Nicht verfügbar — noch kein Runtime-Snapshot vorhanden.</p>';
    _loggerRefreshModuleViews();
    return;
  }
  if (body.status !== "available") {
    // "corrupt" (und jeder unbekannte Status) — kein Fake-Wert.
    kpiEl.innerHTML = "";
    el.innerHTML = '<div class="alert alert-danger mb-0"><div><div class="alert-title">Snapshot unlesbar</div><div class="text-secondary">' +
      _escapeHtml(body.message || "Der Snapshot ist unvollständig oder korrupt.") + '</div></div></div>';
    if (startupEl) startupEl.innerHTML = '<p class="text-danger mb-0">Fehlerhaft — der Runtime-Snapshot ist nicht lesbar.</p>';
    _loggerRefreshModuleViews();
    return;
  }

  const s = body.snapshot || {};
  const levels = s.effective_levels || {};
  const moduleCount = Object.keys(levels).length;
  const startupId = s.startup_id || "";
  const shortId = startupId.length > 12 ? startupId.slice(0, 12) + "…" : (startupId || "?");

  kpiEl.innerHTML =
    _loggerKpiCol("Root-Level", _escapeHtml(s.root_level || "–")) +
    _loggerKpiCol("Module", String(moduleCount)) +
    _loggerKpiCol("Letzter Startup", _escapeHtml(_loggerTimeAgo(s.runtime_applied_at)), s.runtime_applied_at || "");

  // Snapshot-Module ohne persistierte Konfiguration (Code-Default aktiv):
  // nicht in der Modulliste (die zeigt die Config), daher hier als Hinweis.
  let notPersisted = 0;
  if (_loggerState.config) {
    const cfgModules = _loggerState.config.modules || {};
    notPersisted = Object.keys(levels).filter(function(n) { return !_loggerHas(cfgModules, n); }).length;
  }

  el.innerHTML =
    '<div class="text-secondary small">Zustand nach dem letzten erfolgreichen Bot-Start</div>' +
    '<div class="small"><code>' + _escapeHtml(s.runtime_applied_at || "?") + '</code></div>' +
    '<div class="text-secondary small mt-2">startup_id</div>' +
    '<div class="small"><code title="' + _escapeHtml(startupId) + '">' + _escapeHtml(shortId) + '</code></div>' +
    (notPersisted
      ? '<div class="text-secondary small mt-2">' + notPersisted +
        ' Snapshot-Modul(e) ohne persistierte Konfiguration (Code-Default aktiv).</div>'
      : '');

  if (startupEl) {
    startupEl.innerHTML =
      '<div class="h3 mb-3">' + _escapeHtml(_loggerFormatUtc(s.runtime_applied_at)) + '</div>' +
      '<div class="text-secondary small">startup_id</div>' +
      '<div class="mb-3"><code class="text-break">' + _escapeHtml(startupId || "?") + '</code></div>' +
      '<span class="badge bg-secondary-lt">Kein Live-Zustand</span>';
  }

  _loggerRefreshModuleViews();
}

function loadRuntimeStatus() {
  return _loadInto(
    "logger-runtime-content",
    "/api/v1/admin/logger/runtime-status",
    renderRuntimeStatus,
    loadRuntimeStatus,
  );
}

// =====================================================================
// Modulliste (Quelle: GET /config)
// =====================================================================
function _loggerModuleBadges(name) {
  const m = _loggerPersistedModule(name) || {};
  const level = m.level || "INFO";
  const levelOk = LOGGER_LEVELS.indexOf(level) !== -1;
  const parts = [
    '<span class="badge ' + (levelOk ? 'bg-blue-lt' : 'bg-danger-lt') + '">' + _escapeHtml(level) + '</span>',
    m.file_handler
      ? '<span class="badge bg-green-lt" title="Eigene Log-Datei konfiguriert">Datei</span>'
      : '<span class="badge bg-secondary-lt" title="Keine eigene Log-Datei konfiguriert">keine Datei</span>',
  ];
  if (m.enabled === false) parts.push('<span class="badge bg-danger-lt">disabled</span>');
  const diff = _loggerComputeModuleDiff(name, _loggerState.runtime, _loggerState.config);
  if (diff.status === "differs") {
    parts.push('<span class="badge bg-warning-lt" title="Weicht vom Runtime-Zustand ab">Abweichung</span>');
  }
  if (_loggerIsDirty(name)) {
    parts.push('<span class="badge bg-orange-lt" title="Ungespeicherte Änderungen">ungespeichert</span>');
  }
  return parts.join(" ");
}

function _loggerModuleItemHtml(name) {
  const selected = _loggerState.selected === name;
  return '<button type="button" class="list-group-item list-group-item-action logger-module-item' +
      (selected ? ' selected' : '') + '" data-module="' + _escapeHtml(name) + '"' +
      ' aria-pressed="' + (selected ? 'true' : 'false') + '">' +
    '<div class="fw-semibold text-break">' + _escapeHtml(name) + '</div>' +
    '<div class="d-flex flex-wrap gap-1 mt-1">' + _loggerModuleBadges(name) + '</div>' +
  '</button>';
}

function _loggerFilteredNames() {
  const modules = (_loggerState.config && _loggerState.config.modules) || {};
  const q = (_loggerState.filter || "").trim().toLowerCase();
  return Object.keys(modules).sort().filter(function(n) {
    return !q || n.toLowerCase().indexOf(q) !== -1;
  });
}

function _loggerRenderModuleList() {
  const el = document.getElementById("logger-config-content");
  if (!el) return;
  const modules = (_loggerState.config && _loggerState.config.modules) || {};
  const total = Object.keys(modules).length;
  const names = _loggerFilteredNames();
  const countEl = document.getElementById("logger-module-count");
  if (countEl) {
    countEl.textContent = total
      ? (names.length === total ? total + " Module" : names.length + " von " + total + " Modulen")
      : "";
  }
  if (!total) return;
  if (!names.length) {
    el.className = "logger-module-list empty-note p-3";
    el.innerHTML = "Kein Modul entspricht dem Filter.";
    return;
  }
  el.className = "logger-module-list list-group list-group-flush";
  el.innerHTML = names.map(_loggerModuleItemHtml).join("");
}

function _loggerRefreshListItem(name) {
  const container = document.getElementById("logger-config-content");
  if (!container || !container.querySelectorAll) return;
  container.querySelectorAll(".logger-module-item").forEach(function(btn) {
    if (btn.getAttribute("data-module") === name) btn.outerHTML = _loggerModuleItemHtml(name);
  });
}

function renderConfig(el, body) {
  _loggerState.config = body;
  const modules = body.modules || {};
  const names = Object.keys(modules);

  if (!names.length) {
    _loggerState.selected = null;
    _loggerState.drafts = {};
    const countEl = document.getElementById("logger-module-count");
    if (countEl) countEl.textContent = "";
    el.className = "logger-module-list empty-note p-3";
    el.innerHTML = 'Keine persistierte Konfiguration vorhanden. Der Bot muss mindestens einmal gestartet worden sein, damit die Default-Konfiguration generiert wird.';
    _loggerRenderDetail();
    _loggerRefreshRuntimeHints();
    return;
  }

  _loggerPruneDrafts();
  if (_loggerState.selected && !_loggerHas(modules, _loggerState.selected)) {
    _loggerState.selected = null;
  }
  _loggerRenderModuleList();
  _loggerRenderDetail();
  _loggerRefreshRuntimeHints();
}

function loadConfig() {
  return _loadInto(
    "logger-config-content",
    "/api/v1/admin/logger/config",
    renderConfig,
    loadConfig,
  );
}

// Liste + Detailkarte neu zeichnen, wenn sich Runtime-Daten geaendert haben
// (Abweichungs-Badges, Desired-vs-Actual).
function _loggerRefreshModuleViews() {
  if (_loggerState.config) {
    _loggerRenderModuleList();
    _loggerRenderDetail();
  }
}

// Die "Snapshot-Module ohne Config"-Zeile haengt von beiden Antworten ab.
function _loggerRefreshRuntimeHints() {
  if (_loggerState.runtime && _loggerState.runtime.status === "available") {
    const el = document.getElementById("logger-runtime-content");
    if (el) renderRuntimeStatus(el, _loggerState.runtime);
  }
}

// =====================================================================
// Modul auswaehlen + Detailkarte
// =====================================================================
function _loggerSelectModule(name) {
  if (!name || _loggerPersistedModule(name) === null) return;
  _loggerState.selected = name;
  const container = document.getElementById("logger-config-content");
  if (container && container.querySelectorAll) {
    container.querySelectorAll(".logger-module-item").forEach(function(btn) {
      const on = btn.getAttribute("data-module") === name;
      btn.classList.toggle("selected", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  _loggerClearStatus("logger-config-status");
  _loggerRenderDetail();
}

function _loggerLevelRadiosHtml(name, current, persisted) {
  const radios = LOGGER_LEVELS.map(function(level) {
    return '<label class="form-check mb-1">' +
      '<input type="radio" class="form-check-input logger-config-control logger-level-radio" ' +
        'name="logger-level" value="' + level + '" data-module="' + _escapeHtml(name) + '"' +
        (level === current ? ' checked' : '') + '>' +
      '<span class="form-check-label">' + level +
        (level === persisted ? ' <span class="text-secondary small">(persistiert)</span>' : '') +
      '</span>' +
    '</label>';
  });
  return radios.join("");
}

function _loggerFileSwitchHtml(name, checked) {
  return '<label class="form-check form-switch mb-1">' +
    '<input type="checkbox" class="form-check-input logger-config-control logger-file-toggle" ' +
      'data-module="' + _escapeHtml(name) + '"' + (checked ? ' checked' : '') + '>' +
    '<span class="form-check-label"><strong id="logger-file-state">' +
      (checked ? 'Aktiv' : 'Deaktiviert') + '</strong></span>' +
  '</label>';
}

function _loggerYesNo(v) {
  return v ? "aktiviert" : "deaktiviert";
}

function _loggerDiffHtml(name) {
  const diff = _loggerComputeModuleDiff(name, _loggerState.runtime, _loggerState.config);
  if (diff.status === "unknown") {
    return '<div class="alert alert-secondary mb-0"><div class="text-secondary">Runtime-Zustand unbekannt — ' +
      'kein Vergleich möglich, bis ein gültiger Runtime-Snapshot vorliegt.</div></div>';
  }
  if (diff.status === "not_in_runtime") {
    return '<div class="alert alert-secondary mb-0"><div class="text-secondary">' +
      'Nicht im letzten Runtime-Snapshot vorhanden.</div></div>';
  }
  if (diff.status === "identical") {
    return '<div class="alert alert-success mb-0"><div>Persistierte Konfiguration und Runtime-Zustand sind identisch.</div></div>';
  }
  if (diff.status === "differs") {
    return '<div class="alert alert-warning mb-0"><div>' +
      '<div class="alert-title">⚠ Abweichung</div>' +
      '<div class="text-secondary mb-1">Konfiguration wurde noch nicht angewendet. ' +
        'Beim nächsten Bot-Neustart würden wirksam (actual → desired):</div>' +
      '<ul class="mb-0">' + diff.changes.map(function(c) { return '<li>' + c + '</li>'; }).join("") + '</ul>' +
    '</div></div>';
  }
  return "";
}

function _loggerRuntimeBlockHtml(name) {
  const rt = _loggerState.runtime;
  if (!rt) {
    return '<div class="text-secondary">Runtime-Zustand: noch nicht geladen.</div>';
  }
  if (rt.status !== "available") {
    return '<div class="text-secondary">Runtime-Zustand unbekannt' +
      (rt.status === "corrupt" ? ' (Snapshot fehlerhaft)' : ' (kein Snapshot)') + '.</div>';
  }
  const v = _loggerRuntimeModuleView(name);
  if (!v || !v.present) {
    return '<div class="text-secondary">Nicht im letzten Runtime-Snapshot vorhanden.</div>';
  }
  return '<div>Level: <code>' + _escapeHtml(v.level) + '</code></div>' +
    '<div>FileHandler: ' + (v.file ? 'vorhanden' : 'nicht vorhanden') + '</div>' +
    '<div>Console: ' + (v.console ? 'vorhanden' : 'nicht vorhanden') + '</div>' +
    (v.disabled ? '<div><span class="badge bg-danger-lt">disabled</span></div>' : '');
}

function _loggerRenderDetail() {
  const el = document.getElementById("logger-module-detail");
  if (!el) return;
  const name = _loggerState.selected;
  const m = name ? _loggerPersistedModule(name) : null;

  if (!name || m === null) {
    el.innerHTML = '<p class="empty-note mb-0">' +
      (_loggerState.config && Object.keys(_loggerState.config.modules || {}).length
        ? 'Modul in der Liste auswählen, um Level und eigene Log-Datei zu bearbeiten.'
        : 'Keine Module verfügbar.') + '</p>';
    _loggerUpdateActions();
    return;
  }

  const persisted = _loggerPersistedValues(name);
  const eff = _loggerEffectiveValues(name);
  const persistedLevelValid = LOGGER_LEVELS.indexOf(persisted.level) !== -1;
  const enabled = m.enabled !== false;

  el.innerHTML =
    '<div class="d-flex align-items-start gap-2 mb-3">' +
      '<div class="flex-fill min-w-0">' +
        '<div class="subheader">Logger-Modul</div>' +
        '<div class="h2 mb-0 text-break">' + _escapeHtml(name) + '</div>' +
      '</div>' +
      '<div class="d-flex flex-wrap gap-1 justify-content-end">' +
        (enabled ? '<span class="badge bg-success-lt">aktiv</span>' : '<span class="badge bg-danger-lt">disabled</span>') +
        '<span id="logger-dirty-badge">' + (_loggerIsDirty(name) ? '<span class="badge bg-orange-lt">ungespeichert</span>' : '') + '</span>' +
      '</div>' +
    '</div>' +

    (persistedLevelValid ? '' :
      '<div class="alert alert-danger"><div><div class="alert-title">Persistiertes Level ungültig</div>' +
      '<div class="text-secondary">In der Konfiguration steht <code>' + _escapeHtml(persisted.level) +
      '</code>. Wählen Sie ein gültiges Level und speichern Sie, um es zu korrigieren.</div></div></div>') +

    '<div class="row g-4 mb-3">' +
      '<div class="col-md-6">' +
        '<div class="form-label">Log-Level</div>' +
        '<div id="logger-level-group" role="radiogroup" aria-label="Log-Level">' +
          _loggerLevelRadiosHtml(name, eff.level, persistedLevelValid ? persisted.level : null) +
        '</div>' +
      '</div>' +
      '<div class="col-md-6">' +
        '<div class="form-label">Eigene Log-Datei</div>' +
        _loggerFileSwitchHtml(name, eff.file_handler) +
        '<div class="text-secondary small mb-3">Wird erst nach „Konfiguration anwenden“ und dem dadurch ' +
          'ausgelösten Bot-Neustart aktiv. Das Speichern verändert den laufenden Bot nicht.</div>' +
        '<div class="form-label">Console</div>' +
        '<div>' + (m.console_handler
          ? '<span class="badge bg-green-lt">Aktiv</span>'
          : '<span class="badge bg-secondary-lt">Deaktiviert</span>') +
          ' <span class="text-secondary small">(persistiert, hier nicht änderbar)</span></div>' +
      '</div>' +
    '</div>' +

    '<hr class="my-3">' +
    '<div class="row g-3 mb-3">' +
      '<div class="col-md-6">' +
        '<div class="subheader mb-1">Persistiert</div>' +
        '<div>Level: <code>' + _escapeHtml(persisted.level) + '</code></div>' +
        '<div>File: ' + _loggerYesNo(persisted.file_handler) + '</div>' +
        '<div>Console: ' + _loggerYesNo(!!m.console_handler) + '</div>' +
        '<div class="text-secondary small mt-1">Wird beim nächsten Start angewendet.</div>' +
      '</div>' +
      '<div class="col-md-6">' +
        '<div class="subheader mb-1">Runtime nach letztem Startup</div>' +
        _loggerRuntimeBlockHtml(name) +
        '<div class="text-secondary small mt-1">Snapshot, kein Live-Zustand.</div>' +
      '</div>' +
    '</div>' +
    _loggerDiffHtml(name);

  _loggerUpdateActions();
}

// Save/Reset nur bei Entwurf; Apply braucht keinen Entwurf (persistierter
// Stand wird angewendet). Waehrend eines Writes sind alle gesperrt.
function _loggerUpdateActions() {
  const name = _loggerState.selected;
  const dirty = !!name && _loggerIsDirty(name);
  const saveBtn = document.getElementById("logger-save-btn");
  const resetBtn = document.getElementById("logger-reset-btn");
  if (saveBtn) saveBtn.disabled = _loggerState.saving || !dirty;
  if (resetBtn) resetBtn.disabled = _loggerState.saving || !dirty;
}

function _loggerSetConfigControlsDisabled(disabled) {
  document.querySelectorAll(".logger-config-control").forEach(function(el) {
    el.disabled = disabled;
  });
}

function _loggerClearStatus(elementId) {
  const el = document.getElementById(elementId);
  if (el) el.innerHTML = "";
}

// Entwurf aendern (kein Request): Level-Radio / File-Schalter.
function _loggerOnDraftChange(name, field, value) {
  if (!name) return;
  _loggerSetDraftField(name, field, value);
  const badge = document.getElementById("logger-dirty-badge");
  if (badge) {
    badge.innerHTML = _loggerIsDirty(name) ? '<span class="badge bg-orange-lt">ungespeichert</span>' : "";
  }
  if (field === "file_handler") {
    const st = document.getElementById("logger-file-state");
    if (st) st.textContent = value ? "Aktiv" : "Deaktiviert";
  }
  _loggerRefreshListItem(name);
  _loggerClearStatus("logger-config-status");
  _loggerUpdateActions();
}

// =====================================================================
// Speichern / Zuruecksetzen
// =====================================================================
//
// Speichern sendet genau die geaenderten Felder des ausgewaehlten Moduls
// (`level`, `file_handler`) in EINEM PATCH /api/v1/admin/logger/config.
// `enabled`/`console_handler` werden nie mitgesendet. Unbekannte Module
// lehnt die API mit LOGGER_CONFIG_UNKNOWN_MODULE ab (L4) — das Anlegen neuer
// Module (ensure_module_config_entry) bleibt Telegram-/In-Process-exklusiv
// (L7). Die Backend-Validierung bleibt autoritativ. Kein Bot-Restart.
async function _loggerSaveModule() {
  const name = _loggerState.selected;
  if (!name || _loggerState.saving || !_loggerIsDirty(name)) return;

  const fields = Object.assign({}, _loggerState.drafts[name]);
  // Nur Werte aus der Whitelist senden (Backend-Validierung bleibt trotzdem
  // autoritativ).
  if (_loggerHas(fields, "level") && LOGGER_LEVELS.indexOf(fields.level) === -1) {
    delete fields.level;
  }
  if (!Object.keys(fields).length) return;

  _loggerState.saving = true;
  _loggerSetConfigControlsDisabled(true);
  _loggerUpdateActions();
  _loggerRenderAlertInto("logger-config-status", "info", "Speichere…", _escapeHtml(name));

  const patch = {};
  patch[name] = fields;

  let reload = false;
  try {
    const res = await fetch(apiUrl("/api/v1/admin/logger/config"), {
      method: "PATCH",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ modules: patch }),
    });

    if (res.status === 200) {
      // Server hat akzeptiert: Entwurf wird persistierter Stand.
      const m = _loggerPersistedModule(name);
      if (m) Object.assign(m, fields);
      _loggerPruneDrafts();
      _loggerRenderAlertInto(
        "logger-config-status",
        "success",
        "Änderungen gespeichert. Noch nicht aktiv.",
        "Der laufende Bot wurde nicht verändert. Wirksam erst nach " +
          "„Konfiguration anwenden“ (Bot-Neustart)."
      );
      reload = true;
      return;
    }

    // Fehlschlag: Entwurf bleibt erhalten (Nutzer kann erneut speichern
    // oder zuruecksetzen); nichts wurde als gespeichert dargestellt.
    if (res.status === 401) {
      showOnly("login-view");
      return;
    }
    if (res.status === 403) {
      _loggerRenderAlertInto("logger-config-status", "danger", "Zugriff verweigert",
        "CSRF- oder Auth-Prüfung fehlgeschlagen. Bitte Seite neu laden.");
      return;
    }

    const body = await res.json().catch(function() { return null; });
    const detail = (body && (body.detail || body.error)) || {};
    const code = detail.code || "";
    let title = "Nicht gespeichert";
    if (code === "LOGGER_CONFIG_UNKNOWN_MODULE") {
      title = "Modul nicht in der persistierten Konfiguration";
    } else if (code === "LOGGER_CONFIG_MISSING") {
      title = "Keine persistierte Konfiguration vorhanden";
    } else if (code === "LOGGER_CONFIG_INVALID_LEVEL") {
      title = "Ungültiges Level";
    }
    _loggerRenderAlertInto("logger-config-status", "danger", title,
      _escapeHtml(detail.message || ("HTTP " + res.status)));
    reload = true;  // Liste mit dem echten Dateistand abgleichen
  } catch (err) {
    _loggerRenderAlertInto("logger-config-status", "danger", "Netzwerkfehler",
      _escapeHtml(err.message || String(err)));
  } finally {
    _loggerState.saving = false;
    _loggerSetConfigControlsDisabled(false);
    _loggerRenderModuleList();
    _loggerRenderDetail();
    // loadConfig() zieht den echten Dateistand nach (Liste, Detailkarte,
    // Desired-vs-Actual).
    if (reload) loadConfig();
  }
}

// Verwirft den Entwurf des ausgewaehlten Moduls und stellt den zuletzt vom
// Server geladenen persistierten Stand wieder her. Kein Request; weder
// Runtime-Zustand noch Defaults noch Browser-Speicher werden verwendet.
function _loggerResetModule() {
  const name = _loggerState.selected;
  if (!name || _loggerState.saving) return;
  delete _loggerState.drafts[name];
  _loggerClearStatus("logger-config-status");
  _loggerRefreshListItem(name);
  _loggerRenderDetail();
}

function _loggerInitConfigControls() {
  // Event-Delegation: Liste und Detailkarte werden dynamisch neu gerendert.
  const list = document.getElementById("logger-config-content");
  if (list) {
    list.addEventListener("click", function(ev) {
      const target = ev.target;
      const item = target && target.closest ? target.closest(".logger-module-item") : null;
      if (item) _loggerSelectModule(item.getAttribute("data-module"));
    });
  }

  const detail = document.getElementById("logger-module-detail");
  if (detail) {
    detail.addEventListener("change", function(ev) {
      const target = ev.target;
      if (!target || !target.classList) return;
      const name = target.getAttribute("data-module");
      if (target.classList.contains("logger-level-radio")) {
        if (target.checked && LOGGER_LEVELS.indexOf(target.value) !== -1) {
          _loggerOnDraftChange(name, "level", target.value);
        }
      } else if (target.classList.contains("logger-file-toggle")) {
        _loggerOnDraftChange(name, "file_handler", !!target.checked);
      }
    });
  }

  const filter = document.getElementById("logger-module-filter");
  if (filter) {
    filter.addEventListener("input", function() {
      _loggerState.filter = filter.value || "";
      _loggerRenderModuleList();
    });
  }

  const saveBtn = document.getElementById("logger-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _loggerSaveModule);
  const resetBtn = document.getElementById("logger-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", _loggerResetModule);
}

// =====================================================================
// Apply (Controlled Restart)
// =====================================================================
//
// POST /api/v1/admin/logger/apply — ein einziger API-Call, der Preflight
// + Restart in einem Schritt macht. Die API-Antwort bestimmt die
// Darstellung:
//   - 200 + preflight.status="unverified" → Warnhinweis mit den nicht
//                                          pruefbaren Aktivitaeten (NIE als
//                                          "clear" darstellen)
//   - 200 + preflight.status="clear"      → gruener Hinweis
//   - 409 + code="LOGGER_APPLY_BLOCKED"   → roter Hinweis, kein Restart
//   - 409 + code="LOGGER_CONFIG_MISSING"  → roter Hinweis
//   - 429                                  → oranger Hinweis mit Countdown
//   - 403                                  → CSRF/Auth-Hinweis
//   - sonst                                → generischer Fehler

const _loggerRateLimit = {
  timer: null,
};

// Klartext fuer die Kategorien aus preflight.unverified.
const _LOGGER_UNVERIFIED_LABELS = {
  downloads: "Downloads",
  backups: "Backups",
};

function _loggerClearRateLimitTimer() {
  if (_loggerRateLimit.timer) {
    clearInterval(_loggerRateLimit.timer);
    _loggerRateLimit.timer = null;
  }
}

function _loggerRenderAlert(kind, title, body) {
  _loggerRenderAlertInto("logger-apply-status", kind, title, body);
}

function _loggerRenderAlertInto(elementId, kind, title, body) {
  // kind: "success" | "warning" | "danger" | "info"
  const el = document.getElementById(elementId);
  if (!el) return;
  el.innerHTML =
    '<div class="alert alert-' + kind + ' mb-0"><div>' +
      '<div class="alert-title">' + _escapeHtml(title) + '</div>' +
      '<div class="text-secondary">' + body + '</div>' +
    '</div></div>';
}

function _loggerUnverifiedListHtml(preflight) {
  const items = (preflight && preflight.unverified) || [];
  if (!items.length) return "";
  return '<div class="mt-2">Folgende Aktivitäten können vom Control Center nicht zuverlässig live geprüft werden:</div>' +
    '<ul class="mb-0">' +
    items.map(function(u) {
      return '<li>' + _escapeHtml(_LOGGER_UNVERIFIED_LABELS[u] || u) + '</li>';
    }).join("") +
    '</ul>';
}

function _loggerBlockedBodyHtml(preflight) {
  const active = (preflight && preflight.active) || {};
  const parts = [];
  if (active.repair) {
    parts.push('<div>Ein laufender kritischer Repair-/Maintenance-Lauf wurde erkannt.</div>');
  }
  if (preflight && preflight.message) {
    parts.push('<div class="small mt-1">' + _escapeHtml(preflight.message) + '</div>');
  }
  parts.push('<div class="mt-2">Die Konfiguration wurde nicht angewendet. Der Bot wird nicht neu gestartet.</div>');
  return parts.join("");
}

async function _loggerApply() {
  const btn = document.getElementById("logger-apply-btn");
  if (!btn || btn.disabled) return;

  const confirmed = window.confirm(
    "Administrativer Vorgang:\n\n" +
    "Der Bot wird neu gestartet. Die persistierte Logger-Konfiguration " +
    "wird beim Neustart angewendet.\n\n" +
    (_loggerAnyDirty()
      ? "ACHTUNG: Es gibt ungespeicherte Änderungen — sie werden NICHT angewendet.\n\n"
      : "") +
    "Ein laufender Repair-/Maintenance-Lauf würde den Restart blockieren. " +
    "Laufende Downloads oder Backups können nicht geprüft werden und " +
    "würden unterbrochen.\n\n" +
    "Fortfahren?"
  );
  if (!confirmed) return;

  _loggerClearRateLimitTimer();
  btn.disabled = true;
  _loggerRenderAlert("info", "Anwendung läuft…", "Konfiguration wird validiert und Preflight geprüft.");

  try {
    const res = await fetch(apiUrl("/api/v1/admin/logger/apply"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });

    // --- 200: angewendet ---
    if (res.status === 200) {
      const body = await res.json().catch(function() { return null; });
      const preflight = (body && body.preflight) || { status: "clear" };
      const message = (body && body.message) || "Restart geplant.";
      const reloadHint =
        '<div class="mt-2 small">Die Seite kann in wenigen Sekunden aktualisiert werden, um den neuen Runtime-Zustand zu sehen.</div>';
      if (preflight.status === "unverified") {
        _loggerRenderAlert(
          "warning",
          "⚠ Konfiguration kann angewendet werden",
          '<div>Der Repair-Lock ist frei.</div>' +
            _loggerUnverifiedListHtml(preflight) +
            '<div class="mt-2">Der Bot wird kontrolliert neu gestartet.</div>' +
            '<div class="small mt-1">' + _escapeHtml(message) + '</div>' +
            reloadHint
        );
      } else {
        _loggerRenderAlert(
          "success",
          "✓ Keine bekannte kritische Aktivität erkannt",
          '<div>Konfiguration kann angewendet werden. Der Bot wird kontrolliert neu gestartet.</div>' +
            '<div class="small mt-1">' + _escapeHtml(message) + '</div>' +
            reloadHint
        );
      }
      return;
    }

    // --- 409: blocked oder config missing ---
    if (res.status === 409) {
      const body = await res.json().catch(function() { return null; });
      const detail = (body && (body.detail || body.error)) || {};
      const code = detail.code || "LOGGER_APPLY_BLOCKED";
      const preflight = detail.preflight || null;
      if (code === "LOGGER_APPLY_BLOCKED" && preflight) {
        _loggerRenderAlert(
          "danger",
          "⚠ Anwendung blockiert",
          _loggerBlockedBodyHtml(preflight)
        );
      } else if (code === "LOGGER_CONFIG_MISSING") {
        _loggerRenderAlert(
          "danger",
          "Kein Restart ausgelöst — Konfiguration fehlt",
          _escapeHtml(detail.message || "Keine persistierte Logger-Konfiguration vorhanden.")
        );
      } else {
        _loggerRenderAlert(
          "danger",
          "Kein Restart ausgelöst",
          _escapeHtml(detail.message || ("HTTP " + res.status))
        );
      }
      return;
    }

    // --- 429: rate-limited mit Retry-After-Countdown ---
    if (res.status === 429) {
      const body = await res.json().catch(function() { return null; });
      const detail = (body && (body.detail || body.error)) || {};
      const retryHeader = res.headers.get("retry-after");
      const retryFromBody = detail.retry_after_seconds;
      let seconds = 60;
      if (retryHeader) {
        const n = parseInt(retryHeader, 10);
        if (!isNaN(n)) seconds = n;
      } else if (retryFromBody && !isNaN(parseInt(retryFromBody, 10))) {
        seconds = parseInt(retryFromBody, 10);
      }
      _loggerRenderAlert(
        "warning",
        "⏳ Zu viele Anfragen",
        '<div>Bitte noch <strong id="logger-rate-limit-countdown">' + seconds + '</strong> Sekunden warten.</div>' +
          '<div class="small mt-1">' +
            _escapeHtml(detail.message || "Ein weiterer Apply-Versuch folgt zu schnell aufeinander.") +
          '</div>'
      );
      const countdownEl = document.getElementById("logger-rate-limit-countdown");
      let remaining = seconds;
      _loggerRateLimit.timer = setInterval(function() {
        remaining -= 1;
        if (countdownEl) {
          if (remaining > 0) {
            countdownEl.textContent = String(remaining);
          } else {
            countdownEl.textContent = "0";
          }
        }
        if (remaining <= 0) {
          _loggerClearRateLimitTimer();
        }
      }, 1000);
      return;
    }

    // --- 403: CSRF oder Auth ---
    if (res.status === 403) {
      _loggerRenderAlert(
        "danger",
        "Zugriff verweigert",
        "CSRF- oder Auth-Prüfung fehlgeschlagen. Bitte Seite neu laden."
      );
      return;
    }

    // --- 401: nicht eingeloggt ---
    if (res.status === 401) {
      showOnly("login-view");
      return;
    }

    // --- sonstiger Fehler ---
    const body = await res.json().catch(function() { return null; });
    const detail = (body && (body.detail || body.error)) || {};
    _loggerRenderAlert(
      "danger",
      "Fehler",
      _escapeHtml(detail.message || ("HTTP " + res.status))
    );
  } catch (err) {
    _loggerRenderAlert(
      "danger",
      "Netzwerkfehler",
      _escapeHtml(err.message || String(err))
    );
  } finally {
    btn.disabled = false;
  }
}

function _loggerInitApplyPanel() {
  // Button ist nur aktiv, wenn die Config geladen ist.
  // Der Diff-Status spielt keine Rolle (auch wenn identisch: Restart kann
  // gewuenscht sein, weil der Bot trotzdem den aktuellen Snapshot neu
  // schreiben soll).
  const btn = document.getElementById("logger-apply-btn");
  if (!btn) return;
  btn.addEventListener("click", _loggerApply);
}

// =====================================================================
// Init
// =====================================================================
function initPage() {
  checkAuth().then(function(who) {
    if (!who) return;

    loadRuntimeStatus();
    loadConfig();

    const refreshBtn = document.getElementById("logger-runtime-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function() {
        loadRuntimeStatus();
        loadConfig();
      });
    }

    _loggerInitApplyPanel();
    _loggerInitConfigControls();

    // Apply-Button erst aktivieren, wenn die Config geladen ist —
    // sonst waere ein Klick ein Blindflug ohne Diff-Kontext.
    const btn = document.getElementById("logger-apply-btn");
    if (btn) {
      const wait = setInterval(function() {
        if (_loggerState.config !== null) {
          btn.disabled = false;
          clearInterval(wait);
        }
      }, 200);
      // Sicherheitsnetz: nach 10s den Button freigeben, falls die Config
      // nicht geladen werden konnte (dann regelt die API-Antwort die
      // Fehleranzeige).
      setTimeout(function() {
        clearInterval(wait);
        if (btn.disabled) btn.disabled = false;
      }, 10000);
    }
  });
}
initPage();
