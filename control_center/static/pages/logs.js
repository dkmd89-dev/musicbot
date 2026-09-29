// control_center/static/pages/logs.js
// Logdateien-Ansicht (Master-Prompt Abschnitt 12 "LOGS & DIAGNOSTICS").
// Liest services/logs/reader.py::read_logs() über GET /api/v1/logs (siehe
// dortigen Docstring für die bewussten Einschränkungen: kein Zeitraum-/
// Job-/User-Filter, da die Datenquelle das nicht zuverlässig hergibt -
// Master-Prompt Regel 38). Inhalte sind serverseitig bereits redigiert
// (redact_secrets), hier zusätzlich durchgehend escaped.
// CC-UI Logs/Logger: aus dem Template ausgelagert (vorher Inline-Script),
// Darstellung im Terminal-Stil nach docs/CONTROL_CENTER_UI_STANDARD.md §10.

// Level -> Farbklasse im Terminal (Standard Abschnitt 10).
const _LOG_LEVEL_TERM_CLASS = {
  DEBUG: "cc-t-time", INFO: "cc-t-info", WARNING: "cc-t-warn", ERROR: "cc-t-err", CRITICAL: "cc-t-err",
};

function renderLogs(el, body) {
  // Quelle-Dropdown nur beim ersten Laden befüllen (sonst geht die
  // Nutzerauswahl bei jedem Refresh verloren).
  const sourceSelect = document.getElementById("logs-source-select");
  if (!sourceSelect.options.length) {
    sourceSelect.innerHTML = body.available_sources.map((s) =>
      `<option value="${_escapeHtml(s)}">${_escapeHtml(s)}</option>`
    ).join("");
    sourceSelect.value = body.source;
  }

  const countEl = document.getElementById("logs-count");
  if (!body.entries.length) {
    if (countEl) countEl.textContent = "";
    ccState.empty(el, "Keine passenden Log-Zeilen.", "Filter anpassen oder andere Log-Datei wählen.");
    return;
  }
  if (countEl) {
    countEl.textContent = body.total_matched > body.entries.length
      ? `${body.entries.length} von ${body.total_matched}` : `${body.entries.length} Zeilen`;
  }
  const trunc = body.total_matched > body.entries.length
    ? '<div class="alert alert-info m-3 mb-0">'
      + `${ccIcon("info", "me-1")}Zeige ${body.entries.length} von ${body.total_matched} — weitere nicht geladen (kein Auto-Rendern großer Listen). Filter eingrenzen, um ältere Zeilen zu sehen.</div>`
    : "";
  const errors = body.entries.filter((e) => e.level === "ERROR" || e.level === "CRITICAL").length;
  const warnings = body.entries.filter((e) => e.level === "WARNING").length;
  const summary = (errors || warnings)
    ? '<div class="d-flex gap-2 px-3 pt-3">'
      + (errors ? ccStatusBadge("error", `${errors} ERROR/CRITICAL`) : "")
      + (warnings ? ccStatusBadge("warn", `${warnings} WARNING`) : "")
      + "</div>"
    : "";
  const lines = body.entries.map((e) => {
    const cls = _LOG_LEVEL_TERM_CLASS[e.level] || "cc-t-info";
    const level = e.level ? `<span class="${cls}">${_escapeHtml(e.level.padEnd(8))}</span> ` : "";
    const component = e.component ? `[${_escapeHtml(e.component)}] ` : "";
    return `<div class="cc-log-line"><span class="cc-t-time">${_escapeHtml(e.time || "")}</span> ${level}${component}${_escapeHtml(e.message)}</div>`;
  }).join("");
  el.innerHTML = trunc + summary + `<div class="cc-terminal p-3 m-3 rounded">${lines}</div>`;
}

function loadLogs() {
  const params = new URLSearchParams();
  const source = document.getElementById("logs-source-select").value;
  const level = document.getElementById("logs-level-select").value;
  const component = document.getElementById("logs-component-input").value.trim();
  const search = document.getElementById("logs-search-input").value.trim();
  const job = document.getElementById("logs-job-input").value.trim();
  if (source) params.set("source", source);
  if (level) params.set("level", level);
  if (component) params.set("component", component);
  if (search) params.set("search", search);
  if (job) params.set("job", job);
  params.set("limit", "200");
  return _loadInto("logs-content", `/api/v1/logs?${params.toString()}`, renderLogs, loadLogs);
}

document.getElementById("logs-refresh-btn").addEventListener("click", loadLogs);
document.getElementById("logs-filter-btn").addEventListener("click", loadLogs);
document.getElementById("logs-source-select").addEventListener("change", loadLogs);

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadLogs();
  });
}
initPage();
