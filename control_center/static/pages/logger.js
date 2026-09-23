// control_center/static/pages/logger.js
// Logger-Seite: Runtime-Status, persistierte Konfiguration,
// Desired-vs-Actual-Vergleich und kontrollierter Bot-Neustart.
//
// L6.2: Runtime-Status + Config + Diff.
// L6.3: Apply (kommt noch).
//
// Nutzt die gemeinsamen Helfer aus common.js
// (apiUrl(), _loadInto(), _escapeHtml(), checkAuth()).

// =====================================================================
// State
// =====================================================================
const _loggerState = {
  runtime: null,
  config: null,
};

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

function _loggerHandlerKind(handlerName) {
  if (handlerName === "FileHandler") return "file";
  if (handlerName.indexOf("StreamHandler") !== -1) return "stream";
  return "other";
}

// =====================================================================
// Panel 1 — Runtime-Status
// =====================================================================
function renderRuntimeStatus(el, body) {
  _loggerState.runtime = body;
  const kpiEl = document.getElementById("logger-runtime-kpi");
  if (!kpiEl) return;

  if (body.status === "missing") {
    kpiEl.innerHTML = "";
    el.innerHTML = '<p class="empty-note">Noch kein Runtime-Snapshot vorhanden. Er wird beim naechsten erfolgreichen Bot-Start geschrieben.</p>';
    renderDiff();
    return;
  }
  if (body.status === "corrupt") {
    kpiEl.innerHTML = "";
    el.innerHTML = '<div class="alert alert-warning mb-0"><div><div class="alert-title">Snapshot unlesbar</div><div class="text-secondary">' + _escapeHtml(body.message || "Der Snapshot ist unvollstaendig oder korrupt.") + '</div></div></div>';
    renderDiff();
    return;
  }

  const s = body.snapshot || {};
  const levels = s.effective_levels || {};
  const handlers = s.handlers || {};
  const disabled = new Set(s.disabled || []);
  const moduleCount = Object.keys(levels).length;

  kpiEl.innerHTML =
    '<div class="kpi-card"><div class="kpi-label">Root-Level</div><div class="kpi-value">' + _escapeHtml(s.root_level || "–") + '</div></div>' +
    '<div class="kpi-card"><div class="kpi-label">Module</div><div class="kpi-value">' + moduleCount + '</div></div>' +
    '<div class="kpi-card"><div class="kpi-label">Letzter Startup</div><div class="kpi-value" style="font-size:1.1rem;" title="' + _escapeHtml(s.runtime_applied_at || "") + '">' + _escapeHtml(_loggerTimeAgo(s.runtime_applied_at)) + '</div></div>';

  const names = Object.keys(levels).sort();
  if (!names.length) {
    el.innerHTML = '<p class="empty-note">Snapshot enthaelt keine Module.</p>';
    renderDiff();
    return;
  }

  const rows = names.map(function(name) {
    const level = levels[name];
    const handlerList = handlers[name] || [];
    const isDisabled = disabled.has(name);
    const statusBadge = isDisabled
      ? '<span class="badge bg-danger-lt">disabled</span>'
      : '<span class="badge bg-success-lt">aktiv</span>';
    const handlerText = handlerList.length ? handlerList.join(", ") : "–";
    return '<tr>' +
      '<td>' + _escapeHtml(name) + '</td>' +
      '<td><code>' + _escapeHtml(level) + '</code></td>' +
      '<td class="text-secondary small">' + _escapeHtml(handlerText) + '</td>' +
      '<td>' + statusBadge + '</td>' +
      '</tr>';
  }).join("");

  const startupId = (s.startup_id || "?");
  const shortId = startupId.length > 12 ? startupId.slice(0, 12) + "…" : startupId;

  el.innerHTML =
    '<p class="text-secondary small mb-2">Zustand nach letztem erfolgreichen Bot-Start (' +
      _escapeHtml(s.runtime_applied_at || "?") + '), startup_id <code>' + _escapeHtml(shortId) + '</code></p>' +
    '<div class="table-responsive">' +
      '<table class="table table-sm table-vcenter">' +
        '<thead><tr><th>Modul</th><th>Level</th><th>Handler</th><th>Status</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
    '</div>';

  renderDiff();
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
// Panel 2 — Persistierte Konfiguration
// =====================================================================
function renderConfig(el, body) {
  _loggerState.config = body;
  const modules = body.modules || {};
  const names = Object.keys(modules).sort();

  if (!names.length) {
    el.innerHTML = '<p class="empty-note">Keine persistierte Konfiguration vorhanden. Der Bot muss mindestens einmal gestartet worden sein, damit die Default-Konfiguration generiert wird.</p>';
    renderDiff();
    return;
  }

  const rows = names.map(function(name) {
    const m = modules[name] || {};
    const enabled = m.enabled !== false;
    const fileH = m.file_handler ? "✓" : "—";
    const consoleH = m.console_handler ? "✓" : "—";
    const status = enabled
      ? '<span class="badge bg-success-lt">aktiv</span>'
      : '<span class="badge bg-secondary-lt">disabled</span>';
    return '<tr>' +
      '<td>' + _escapeHtml(name) + '</td>' +
      '<td><code>' + _escapeHtml(m.level || "INFO") + '</code></td>' +
      '<td class="text-center">' + fileH + '</td>' +
      '<td class="text-center">' + consoleH + '</td>' +
      '<td>' + status + '</td>' +
      '</tr>';
  }).join("");

  el.innerHTML =
    '<p class="text-secondary small mb-2">' + names.length + ' Module. Wirksam beim naechsten Bot-Start.</p>' +
    '<div class="table-responsive">' +
      '<table class="table table-sm table-vcenter">' +
        '<thead><tr><th>Modul</th><th>Level</th><th class="text-center">File</th><th class="text-center">Console</th><th>Status</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
    '</div>';

  renderDiff();
}

function loadConfig() {
  return _loadInto(
    "logger-config-content",
    "/api/v1/admin/logger/config",
    renderConfig,
    loadConfig,
  );
}

// =====================================================================
// Panel 3 — Desired vs. Actual (berechnet aus State, kein neuer Call)
// =====================================================================
function renderDiff() {
  const el = document.getElementById("logger-diff-content");
  if (!el) return;
  const rt = _loggerState.runtime;
  const cfg = _loggerState.config;

  if (!rt || !cfg) {
    el.innerHTML = '<p class="empty-note">Warte auf Runtime- und Config-Daten…</p>';
    return;
  }
  if (rt.status !== "available") {
    el.innerHTML = '<p class="empty-note">Kein Vergleich moeglich: Runtime-Snapshot ist <code>' + _escapeHtml(rt.status) + '</code>. Der Diff wird berechnet, sobald ein gueltiger Snapshot vorliegt.</p>';
    return;
  }

  const snap = rt.snapshot || {};
  const rtLevels = snap.effective_levels || {};
  const rtHandlers = snap.handlers || {};
  const rtDisabled = new Set(snap.disabled || []);
  const cfgModules = cfg.modules || {};

  const allNames = new Set(Object.keys(rtLevels).concat(Object.keys(cfgModules)));
  const sortedNames = Array.from(allNames).sort();
  const rows = [];

  sortedNames.forEach(function(name) {
    const inRt = Object.prototype.hasOwnProperty.call(rtLevels, name);
    const inCfg = Object.prototype.hasOwnProperty.call(cfgModules, name);

    if (inRt && !inCfg) {
      rows.push('<tr>' +
        '<td>' + _escapeHtml(name) + '</td>' +
        '<td class="text-secondary small">Keine persistierte Konfiguration (Code-Default aktiv)</td>' +
        '</tr>');
      return;
    }
    if (!inRt && inCfg) {
      rows.push('<tr>' +
        '<td>' + _escapeHtml(name) + '</td>' +
        '<td class="text-secondary small">Nicht im Runtime-Snapshot (Modul wird vom Bot nicht verwendet)</td>' +
        '</tr>');
      return;
    }

    const cfgM = cfgModules[name] || {};
    const rtLevel = rtLevels[name];
    const cfgLevel = cfgM.level || "INFO";
    const handlerList = rtHandlers[name] || [];
    const rtHasFile = handlerList.indexOf("FileHandler") !== -1;
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

    if (changes.length) {
      rows.push('<tr>' +
        '<td>' + _escapeHtml(name) + '</td>' +
        '<td>' + changes.join("<br>") + '</td>' +
        '</tr>');
    }
  });

  if (!rows.length) {
    el.innerHTML = '<p class="empty-note-ok">Persistierte Konfiguration und Runtime-Zustand sind identisch.</p>';
    return;
  }

  el.innerHTML =
    '<p class="text-secondary small mb-2">' + rows.length + ' Modul(e) mit Abweichungen. Bei Anwendung (naechster Bot-Neustart) wuerden folgende Aenderungen wirksam:</p>' +
    '<div class="table-responsive">' +
      '<table class="table table-sm table-vcenter">' +
        '<thead><tr><th>Modul</th><th>Aenderung (actual → desired)</th></tr></thead>' +
        '<tbody>' + rows.join("") + '</tbody>' +
      '</table>' +
    '</div>';
}

// =====================================================================
// Panel 4 — Apply (Controlled Restart)
// =====================================================================
//
// POST /api/v1/admin/logger/apply — ein einziger API-Call, der Preflight
// + Restart in einem Schritt macht. Die API-Antwort bestimmt die
// Darstellung:
//   - 200 + preflight.status="unverified" → gelb-gruener Hinweis mit
//                                          unverifizierbaren Kategorien
//   - 200 + preflight.status="clear"      → gruener Hinweis
//   - 409 + code="LOGGER_APPLY_BLOCKED"   → roter Hinweis, kein Restart
//   - 409 + code="LOGGER_CONFIG_MISSING"  → roter Hinweis
//   - 429                                  → oranger Hinweis mit Countdown
//   - 403                                  → CSRF/Auth-Hinweis
//   - sonst                                → generischer Fehler

const _loggerRateLimit = {
  timer: null,
};

function _loggerClearRateLimitTimer() {
  if (_loggerRateLimit.timer) {
    clearInterval(_loggerRateLimit.timer);
    _loggerRateLimit.timer = null;
  }
}

function _loggerRenderAlert(kind, title, body) {
  // kind: "success" | "warning" | "danger" | "info"
  const el = document.getElementById("logger-apply-status");
  if (!el) return;
  el.innerHTML =
    '<div class="alert alert-' + kind + ' mb-0"><div>' +
      '<div class="alert-title">' + _escapeHtml(title) + '</div>' +
      '<div class="text-secondary">' + body + '</div>' +
    '</div></div>';
}

function _loggerPreflightBody(preflight) {
  const parts = [];
  if (preflight.message) parts.push(_escapeHtml(preflight.message));
  if (preflight.unverified && preflight.unverified.length) {
    parts.push(
      '<div class="mt-2"><strong>Nicht pruefbare Aktivitaeten:</strong> ' +
      preflight.unverified.map(function(u) { return '<code>' + _escapeHtml(u) + '</code>'; }).join(', ') +
      '</div>'
    );
  }
  return parts.join('');
}

async function _loggerApply() {
  const btn = document.getElementById("logger-apply-btn");
  if (!btn || btn.disabled) return;

  const confirmed = window.confirm(
    "Administrativer Vorgang:\n\n" +
    "Der Bot wird neu gestartet. Die persistierte Logger-Konfiguration " +
    "wird beim Neustart angewendet.\n\n" +
    "Ein laufender Repair-/Maintenance-Lauf wuerde den Restart blockieren. " +
    "Laufende Downloads oder Backups koennen nicht geprueft werden und " +
    "wuerden unterbrochen.\n\n" +
    "Fortfahren?"
  );
  if (!confirmed) return;

  _loggerClearRateLimitTimer();
  btn.disabled = true;
  _loggerRenderAlert("info", "Anwendung laeuft…", "Konfiguration wird validiert und Preflight geprueft.");

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
      if (preflight.status === "unverified") {
        _loggerRenderAlert(
          "warning",
          "Restart wurde geplant — mit Vorbehalt",
          _escapeHtml(message) + _loggerPreflightBody(preflight) +
            '<div class="mt-2 small">Die Seite kann in wenigen Sekunden aktualisiert werden, um den neuen Runtime-Zustand zu sehen.</div>'
        );
      } else {
        _loggerRenderAlert(
          "success",
          "Restart wurde geplant",
          _escapeHtml(message) +
            '<div class="mt-2 small">Die Seite kann in wenigen Sekunden aktualisiert werden, um den neuen Runtime-Zustand zu sehen.</div>'
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
          "Kein Restart ausgeloest — kritischer Lauf aktiv",
          _loggerPreflightBody(preflight)
        );
      } else if (code === "LOGGER_CONFIG_MISSING") {
        _loggerRenderAlert(
          "danger",
          "Kein Restart ausgeloest — Konfiguration fehlt",
          _escapeHtml(detail.message || "Keine persistierte Logger-Konfiguration vorhanden.")
        );
      } else {
        _loggerRenderAlert(
          "danger",
          "Kein Restart ausgeloest",
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
        "Rate-Limit aktiv",
        _escapeHtml(detail.message || "Ein weiterer Apply-Versuch ist zu schnell aufeinander.") +
          '<div class="mt-2">Naechster Versuch erlaubt in <strong id="logger-rate-limit-countdown">' + seconds + '</strong> s.</div>'
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
        "CSRF- oder Auth-Pruefung fehlgeschlagen. Bitte Seite neu laden."
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
