// control_center/static/pages/downloads.js

let _currentDownloadJobId = null;
let _downloadJobPollTimer = null;
let _downloadFormBusy = false;

// Persistenz des aktiven Job-IDs im Browser (Downloads-UI-Verbesserung,
// P0 "Aktiver Download verschwindet nach Reload") - rein clientseitiger
// Komfort, kein Ersatz fuer serverseitige Autorisierung: jede Anfrage
// gegen /api/v1/jobs/download/{id} bleibt ueber _get_own_download_job_or_404()
// auf den eigenen initiator beschraenkt (siehe control_center/routers/jobs.py),
// eine veraltete/fremde ID im Storage liefert daher hoechstens 404, nie
// fremde Daten.
const _DOWNLOAD_JOB_STORAGE_KEY = "musicbot_cc_active_download_job_id";

function _persistCurrentDownloadJobId(jobId) {
  try {
    if (jobId) localStorage.setItem(_DOWNLOAD_JOB_STORAGE_KEY, jobId);
    else localStorage.removeItem(_DOWNLOAD_JOB_STORAGE_KEY);
  } catch (err) {
    // Private-Mode/blockierter Storage - reine Komfortfunktion, kein Fehlerfall.
  }
}

function _applyRetryButtonsBusyState() {
  document.querySelectorAll(".download-retry-btn").forEach((btn) => { btn.disabled = _downloadFormBusy; });
}

function _setDownloadFormBusy(busy) {
  _downloadFormBusy = busy;
  document.getElementById("download-start-btn").disabled = busy;
  document.getElementById("download-url-input").disabled = busy;
  // Waehrend ein Download laeuft, wuerde ein Klick auf "Erneut versuchen"
  // den einzigen client-lokalen Job-Zustand (_currentDownloadJobId/
  // _downloadJobPollTimer) unbemerkt ueberschreiben - der urspruengliche
  // Job liefe serverseitig unsichtbar weiter (P0-Fund).
  _applyRetryButtonsBusyState();
}

function _stopDownloadPolling() {
  if (_downloadJobPollTimer) { clearInterval(_downloadJobPollTimer); _downloadJobPollTimer = null; }
}

// Tabler-Icons als Inline-SVG (Konvention aus library.html, kein Icon-Font
// vendored). Nur statische Pfad-Strings, nie Nutzerdaten.
const _DL_ICON_PATHS = {
  download: '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2" /><path d="M7 11l5 5l5 -5" /><path d="M12 4l0 12" />',
  "circle-check": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" /><path d="M9 12l2 2l4 -4" />',
  "circle-x": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" /><path d="M10 10l4 4m0 -4l-4 4" />',
  "chart-bar": '<path d="M3 13a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" /><path d="M15 9a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v10a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" /><path d="M9 5a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v14a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" />',
  check: '<path d="M5 12l5 5l10 -10" />',
  x: '<path d="M18 6l-12 12" /><path d="M6 6l12 12" />',
  minus: '<path d="M5 12l14 0" />',
  refresh: '<path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4" /><path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" />',
};

function _dlIcon(name, size = 18, extraClass = "") {
  return `<svg xmlns="http://www.w3.org/2000/svg" class="icon ${extraClass}" width="${size}" height="${size}" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path stroke="none" d="M0 0h24v24H0z" fill="none"/>${_DL_ICON_PATHS[name] || ""}</svg>`;
}

// Die fuenf dreiwertigen Tier-Flags des Verlaufs (True/False/None, None =
// "keine Aussage moeglich", siehe services/downloader/download_history.py).
const _DL_TIERS = [
  { key: "genre_ok", label: "Genre", abbr: "Ge" },
  { key: "lyrics_ok", label: "Lyrics", abbr: "Ly" },
  { key: "cover_ok", label: "Cover", abbr: "Co" },
  { key: "mb_ok", label: "MusicBrainz", abbr: "MB" },
  { key: "loudness_ok", label: "Loudness", abbr: "Lo" },
];

function _tierBadgeHtml(label, abbr, value) {
  const cls = value === true ? "bg-success" : value === false ? "bg-danger" : "bg-secondary";
  return `<span class="badge ${cls}" title="${_escapeHtml(label)}">${_escapeHtml(abbr)}</span>`;
}

function _relativeTimeText(timestamp) {
  const t = new Date(timestamp).getTime();
  if (Number.isNaN(t)) return "";
  const minutes = Math.floor((Date.now() - t) / 60000);
  if (minutes < 1) return "gerade eben";
  if (minutes < 60) return `vor ${minutes} Min.`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `vor ${hours} Std.`;
  const days = Math.floor(hours / 24);
  if (days < 7) return days === 1 ? "vor 1 Tag" : `vor ${days} Tagen`;
  return new Date(t).toLocaleDateString();
}

function _renderDownloadIdle() {
  document.getElementById("download-status-content").innerHTML =
    '<p class="empty-note mb-0">Kein aktiver Download.</p>';
}

function _formatResultMessage(message) {
  return _escapeHtml(message || "").replace(/`([^`]+)`/g, "<code>$1</code>");
}

// Verlinkung Duplikat-Ergebnis -> Artist-Detailseite (P2) - der Artist-Name
// kommt bereits strukturiert aus dem Job-Result (jobs.py haengt ihn seit
// dieser Ergaenzung neben der vorformatierten Nachricht an), keine eigene
// Text-Extraktion aus der Nachricht noetig.
function _duplicateArtistLinkHtml(job) {
  const artist = job.result && job.result.artist;
  if (!artist) return "";
  const href = apiUrl(`/library/${encodeURIComponent(artist)}`);
  return `<div class="mt-2"><a href="${href}">Zum Artist „${_escapeHtml(artist)}" →</a></div>`;
}

function _renderDownloadResult(job) {
  const el = document.getElementById("download-status-content");
  if (job.status === "SUCCEEDED") {
    const outcome = job.result && job.result.outcome;
    const alertClass = outcome === "duplicate" ? "alert-info" : "alert-success";
    const msg = _formatResultMessage(job.result && job.result.message);
    const artistLink = outcome === "duplicate" ? _duplicateArtistLinkHtml(job) : "";
    el.innerHTML = `<div class="alert ${alertClass} mb-0" style="white-space: pre-wrap;">${msg}${artistLink}</div>`;
    return;
  }
  if (job.status === "CANCELLED") {
    el.innerHTML = '<div class="alert alert-secondary mb-0">Download abgebrochen.</div>';
    return;
  }
  el.innerHTML = `<div class="alert alert-danger mb-0">${_escapeHtml(job.error || "Unbekannter Fehler.")}</div>`;
}

// Prozent-Text + Laufzeit (P1) - started_at liefert das Backend bereits
// (JobSchema), bisher ungenutzt. Reine Anzeige, keine neue Fachlogik.
function _formatElapsedSeconds(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return m > 0 ? `${m}:${String(rem).padStart(2, "0")}` : `${rem}s`;
}
function _elapsedText(job) {
  if (!job.started_at) return "";
  const started = new Date(job.started_at).getTime();
  if (Number.isNaN(started)) return "";
  return _formatElapsedSeconds((Date.now() - started) / 1000);
}

// Download-Typ-Badge (P2) - job.context wird bereits bei Job-Erstellung
// gesetzt (jobs.py::start_download_job()) und bleibt waehrend PENDING/
// RUNNING/terminal unveraendert sichtbar (im Gegensatz zu job.result, das
// erst am Ende existiert).
function _downloadTypeBadgeHtml(job) {
  const type = job.context && job.context.download_type;
  if (!type) return "";
  const label = type === "playlist" ? "Playlist" : "Single";
  return `<span class="badge bg-secondary-lt me-1">${_escapeHtml(label)}</span>`;
}

function _renderDownloadJob(job) {
  if (job.status === "PENDING" || job.status === "RUNNING") {
    const pct = Math.round(job.progress || 0);
    const elapsed = _elapsedText(job);
    const stateText = job.status === "PENDING" ? "Wartet" : "Download läuft";
    document.getElementById("download-status-content").innerHTML = `
      <div class="mb-3">
        <div class="fw-medium text-truncate mb-2">${_downloadTypeBadgeHtml(job)}${_escapeHtml(job.message || "")}</div>
        <div class="d-flex align-items-center gap-2 mb-1">
          <div class="progress flex-fill">
            <div class="progress-bar" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
          </div>
          <div class="small text-nowrap">${pct} %</div>
        </div>
        <div class="text-secondary small">${stateText}${elapsed ? " · " + _escapeHtml(elapsed) : ""}</div>
      </div>
      <button type="button" id="download-cancel-btn" class="btn btn-sm btn-outline-danger">Abbrechen</button>
    `;
    document.getElementById("download-cancel-btn").addEventListener("click", cancelDownload);
    return;
  }
  _stopDownloadPolling();
  _setDownloadFormBusy(false);
  _persistCurrentDownloadJobId(null);
  _renderDownloadResult(job);
  // Verlauf sofort nachladen statt bis zu 30s auf das Intervall zu warten,
  // damit KPI/Pipeline/"Letzter Download" den gerade beendeten Job zeigen.
  loadDownloads();
}

async function _pollDownloadJob(jobId) {
  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/download/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); _stopDownloadPolling(); return; }
    if (res.status === 404) {
      // Rehydrate-Fall: Job existiert nicht (mehr) - z. B. JobRegistry ist
      // rein prozessspeicher-basiert und ueberlebt keinen Neustart. Kein
      // Fehler, sondern "kein aktiver Download (mehr)".
      _stopDownloadPolling();
      _setDownloadFormBusy(false);
      _persistCurrentDownloadJobId(null);
      _renderDownloadIdle();
      return;
    }
    if (!res.ok) return;
    _renderDownloadJob(await res.json());
  } catch (err) {}
}

async function startDownload(url) {
  _setDownloadFormBusy(true);
  document.getElementById("download-status-content").innerHTML = '<p class="empty-note">Wird gestartet…</p>';
  try {
    const res = await fetch(apiUrl("/api/v1/jobs/download"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ url }),
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      document.getElementById("download-status-content").innerHTML =
        `<div class="alert alert-danger mb-0">${_escapeHtml((body && body.error && body.error.message) || String(res.status))}</div>`;
      _setDownloadFormBusy(false);
      return;
    }
    const job = await res.json();
    _currentDownloadJobId = job.job_id;
    _persistCurrentDownloadJobId(_currentDownloadJobId);
    _renderDownloadJob(job);
    _stopDownloadPolling();
    _downloadJobPollTimer = setInterval(() => _pollDownloadJob(_currentDownloadJobId), 1000);
  } catch (err) {
    document.getElementById("download-status-content").innerHTML =
      `<div class="alert alert-danger mb-0">Download konnte nicht gestartet werden (${_escapeHtml(err.message)}).</div>`;
    _setDownloadFormBusy(false);
  }
}

async function cancelDownload() {
  if (!_currentDownloadJobId) return;
  const btn = document.getElementById("download-cancel-btn");
  if (btn) btn.disabled = true;
  try {
    await fetch(apiUrl(`/api/v1/jobs/download/${encodeURIComponent(_currentDownloadJobId)}/cancel`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    });
  } catch (err) {
    window.alert("Netzwerkfehler beim Abbrechen: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Beim Seitenaufbau: laeuft (aus einem frueheren Aufruf dieser Seite in
// diesem Browser) noch ein Download, dessen Job-ID im Storage liegt?
// Ohne dies wuerde ein Reload/Tab-Wechsel die Sichtbarkeit eines noch
// laufenden, serverseitig aktiven Downloads verlieren (P0-Fund).
function _rehydrateActiveDownloadJob() {
  let jobId = null;
  try { jobId = localStorage.getItem(_DOWNLOAD_JOB_STORAGE_KEY); } catch (err) { jobId = null; }
  if (!jobId) return;
  _currentDownloadJobId = jobId;
  _setDownloadFormBusy(true);
  document.getElementById("download-status-content").innerHTML = '<p class="empty-note">Prüfe laufenden Download…</p>';
  _stopDownloadPolling();
  _downloadJobPollTimer = setInterval(() => _pollDownloadJob(_currentDownloadJobId), 1000);
  _pollDownloadJob(jobId);
}

// ── Verlauf ──────────────────────────────────────────────────────────────

const _DOWNLOAD_HISTORY_PREVIEW_ROWS = 10;
let _lastDownloadHistory = null;
let _downloadHistoryExpanded = false;
let _downloadStatusFilter = "all";

function _downloadsSearchQuery() {
  const input = document.getElementById("downloads-search");
  return input ? (input.value || "").trim().toLowerCase() : "";
}

function _downloadEntryMatchesQuery(e, q) {
  return [e.title, e.artist].filter(Boolean).join(" ").toLowerCase().indexOf(q) !== -1;
}

function _downloadHistoryRowHtml(e) {
  return `
    <div class="row-item">
      <div class="row-main">
        <div class="d-flex align-items-center gap-2">
          <span class="badge badge-status-${_escapeHtml(e.status)}">${_escapeHtml(e.status)}</span>
          <span class="text-truncate">${_escapeHtml(e.artist)} – ${_escapeHtml(e.title)}</span>
        </div>
        <div class="d-flex align-items-center gap-1 mt-1">
          ${_DL_TIERS.map((t) => _tierBadgeHtml(t.label, t.abbr, e[t.key])).join("")}
          <button type="button" class="btn btn-sm btn-outline-secondary btn-icon download-retry-btn" data-url="${_escapeHtml(e.url)}" title="Erneut versuchen" aria-label="Erneut versuchen">${_dlIcon("refresh", 14)}</button>
        </div>
      </div>
      <div class="row-count" title="${_escapeHtml(new Date(e.timestamp).toLocaleString())}">${_escapeHtml(_relativeTimeText(e.timestamp))}</div>
    </div>
  `;
}

// Pipeline-Abdeckung: Anteil True an allen BEKANNTEN Tier-Werten (True/
// False) - None ("keine Aussage moeglich") geht nicht in den Nenner ein und
// wird ausdruecklich nicht als Fehler gewertet. Unabhaengig vom Download-
// Status: auch failed-Eintraege koennen bereits Tier-Informationen tragen.
function _downloadsPipelineStats(entries) {
  const tiers = _DL_TIERS.map((t) => {
    let ok = 0;
    let known = 0;
    entries.forEach((e) => {
      if (e[t.key] === true) { ok += 1; known += 1; }
      else if (e[t.key] === false) { known += 1; }
    });
    return { ...t, ok, known, pct: known ? (ok / known) * 100 : null };
  });
  const ok = tiers.reduce((sum, t) => sum + t.ok, 0);
  const known = tiers.reduce((sum, t) => sum + t.known, 0);
  return { tiers, ok, known, pct: known ? (ok / known) * 100 : null };
}

function _formatPct(pct) {
  return pct === null ? "—" : `${Math.round(pct)} %`;
}

function _pctBarClass(pct) {
  if (pct === null) return "bg-secondary";
  if (pct >= 90) return "bg-success";
  if (pct >= 70) return "bg-warning";
  return "bg-danger";
}

function _kpiCardHtml(icon, colorClass, label, value, tooltip) {
  return `
    <div class="card card-sm" title="${_escapeHtml(tooltip)}">
      <div class="card-body py-3">
        <div class="d-flex align-items-center gap-3">
          <span class="kpi-icon ${colorClass}" aria-hidden="true">${_dlIcon(icon, 24)}</span>
          <div class="min-w-0">
            <div class="text-secondary small">${_escapeHtml(label)}</div>
            <div class="h1 mb-0">${_escapeHtml(value)}</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

// KPI-Leiste - reine Client-Aggregation ueber die geladenen Eintraege
// (bis zu 200, siehe loadDownloads()). Bewusst NICHT als "Gesamt"/"All-Time"
// beschriftet, da hoechstens die geladene Ansicht ausgewertet wird, keine
// serverseitige Statistik (kein neuer Endpunkt) - identisches Prinzip wie
// health.html's "keine vorgetaeuschten Health-Werte". Reihenfolge:
// Menge -> Erfolg -> Probleme -> Metadatenqualitaet.
function _renderDownloadsKpi(entries) {
  const kpiEl = document.getElementById("downloads-kpi");
  if (!kpiEl) return;
  if (!entries.length) { kpiEl.hidden = true; kpiEl.innerHTML = ""; return; }
  const success = entries.filter((e) => e.status === "success").length;
  const failed = entries.filter((e) => e.status === "failed").length;
  const rate = Math.round((success / entries.length) * 100);
  const pipeline = _downloadsPipelineStats(entries);
  kpiEl.hidden = false;
  kpiEl.innerHTML =
    _kpiCardHtml("download", "kpi-blue", "Downloads", String(entries.length),
      "Anzahl der geladenen Verlaufseinträge.") +
    _kpiCardHtml("circle-check", "kpi-green", "Erfolgsquote", `${rate} %`,
      "Anteil erfolgreicher Downloads an den geladenen Verlaufseinträgen.") +
    _kpiCardHtml("circle-x", "kpi-orange", "Fehlgeschlagen", String(failed),
      "Anzahl fehlgeschlagener Downloads in den geladenen Verlaufseinträgen.") +
    _kpiCardHtml("chart-bar", "kpi-purple", "Pipeline", _formatPct(pipeline.pct),
      "Durchschnitt aller bekannten Metadaten-Prüfungen der geladenen Verlaufseinträge.");
}

// Historische Aggregation - ausdruecklich NICHT der aktuell laufende Job
// (der steht links in "Aktuell").
function _renderDownloadsPipeline(entries) {
  const el = document.getElementById("downloads-pipeline-content");
  if (!el) return;
  const stats = _downloadsPipelineStats(entries);
  if (!stats.known) {
    el.className = "empty-note";
    el.innerHTML = "Noch keine Metadaten-Prüfungen im Verlauf.";
    return;
  }
  el.className = "";
  const rows = stats.tiers.map((t) => {
    const width = t.pct === null ? 0 : Math.round(t.pct);
    return `
      <div class="mb-2" title="${t.ok} von ${t.known} bekannten Werten">
        <div class="d-flex justify-content-between small mb-1">
          <span>${_escapeHtml(t.label)}</span>
          <span class="text-secondary">${_formatPct(t.pct)}</span>
        </div>
        <div class="progress progress-sm">
          <div class="progress-bar ${_pctBarClass(t.pct)}" style="width: ${width}%" role="progressbar" aria-label="${_escapeHtml(t.label)}" aria-valuenow="${width}" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
      </div>
    `;
  }).join("");
  el.innerHTML = `
    <div class="d-flex justify-content-between align-items-baseline mb-3" title="${stats.ok} von ${stats.known} bekannten Werten">
      <span class="fw-medium">Gesamt</span>
      <span class="h2 mb-0">${_formatPct(stats.pct)}</span>
    </div>
    ${rows}
  `;
}

// "Zuletzt fehlgeschlagen" ist ein Ereignis, keine Kennzahl - daher hier
// statt in der KPI-Leiste. "Ohne X" zaehlt nur explizites False, nie None.
function _renderDownloadsAttention(entries) {
  const el = document.getElementById("downloads-attention-content");
  if (!el) return;
  const failedEntries = entries.filter((e) => e.status === "failed");
  const missing = _DL_TIERS
    .map((t) => ({ ...t, count: entries.filter((e) => e[t.key] === false).length }))
    .filter((t) => t.count > 0);

  if (!failedEntries.length && !missing.length) {
    el.className = "";
    el.innerHTML = `<div class="empty-note-ok d-flex align-items-center gap-2">${_dlIcon("circle-check")} Keine auffälligen Downloads</div>`;
    return;
  }

  el.className = "";
  let html = "";
  if (failedEntries.length) {
    const last = failedEntries[0];
    html += `
      <div class="d-flex align-items-center gap-2 mb-2">
        <span class="text-danger">${_dlIcon("circle-x")}</span>
        <span class="fw-medium">${failedEntries.length} fehlgeschlagen</span>
      </div>
      <div class="text-secondary small">Letzter Fehler</div>
      <div class="text-truncate">${_escapeHtml(last.artist)} – ${_escapeHtml(last.title)}</div>
      <div class="text-secondary small mb-2" title="${_escapeHtml(new Date(last.timestamp).toLocaleString())}">${_escapeHtml(_relativeTimeText(last.timestamp))}</div>
      <button type="button" id="downloads-attention-open-btn" class="btn btn-sm btn-outline-secondary mb-3">Verlauf öffnen</button>
    `;
  }
  if (missing.length) {
    html += '<div class="row-list">' + missing.map((t) => `
      <div class="row-item">
        <div class="row-main">ohne ${_escapeHtml(t.label)}</div>
        <div class="row-count">${t.count}</div>
      </div>
    `).join("") + "</div>";
  }
  el.innerHTML = html;
}

function _checklistRowHtml(label, value, unknownText) {
  const icon = value === true
    ? `<span class="text-success">${_dlIcon("check")}</span>`
    : value === false
      ? `<span class="text-danger">${_dlIcon("x")}</span>`
      : `<span class="text-secondary">${_dlIcon("minus")}</span>`;
  const hint = value === null || value === undefined ? ` <span class="text-secondary small">(${_escapeHtml(unknownText)})</span>` : "";
  return `<div class="d-flex align-items-center gap-2 py-1">${icon}<span>${_escapeHtml(label)}${hint}</span></div>`;
}

function _renderDownloadsLast(entries) {
  const el = document.getElementById("downloads-last-content");
  if (!el) return;
  if (!entries.length) {
    el.className = "empty-note";
    el.innerHTML = "Noch kein Download im Verlauf.";
    return;
  }
  const e = entries[0];
  const downloadOk = e.status === "success" ? true : e.status === "failed" ? false : null;
  el.className = "";
  el.innerHTML = `
    <div class="d-flex justify-content-between align-items-baseline gap-2 mb-2">
      <div class="fw-medium text-truncate">${_escapeHtml(e.artist)} – ${_escapeHtml(e.title)}</div>
      <div class="text-secondary small text-nowrap" title="${_escapeHtml(new Date(e.timestamp).toLocaleString())}">${_escapeHtml(_relativeTimeText(e.timestamp))}</div>
    </div>
    ${_checklistRowHtml("Download", downloadOk, e.status)}
    ${_DL_TIERS.map((t) => _checklistRowHtml(t.label, e[t.key], "keine Aussage")).join("")}
  `;
}

function _renderDownloadsSummaryUnavailable() {
  ["downloads-pipeline-content", "downloads-attention-content", "downloads-last-content"].forEach((id) => {
    const el = document.getElementById(id);
    if (el && !_lastDownloadHistory) { el.className = "empty-note"; el.innerHTML = "Keine Daten verfügbar."; }
  });
}

function _setDownloadStatusFilter(filter) {
  _downloadStatusFilter = filter;
  document.querySelectorAll("#downloads-status-filter [data-filter]").forEach((btn) => {
    const active = btn.dataset.filter === filter;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });
  _rerenderDownloads();
}

function _rerenderDownloads() {
  const el = document.getElementById("downloads-content");
  if (!el || !_lastDownloadHistory) return;
  const q = _downloadsSearchQuery();
  const entries = _lastDownloadHistory.entries;
  const filtered = entries.filter((e) =>
    (_downloadStatusFilter === "all" || e.status === _downloadStatusFilter) &&
    (!q || _downloadEntryMatchesQuery(e, q)));
  if (!filtered.length) {
    el.innerHTML = q || _downloadStatusFilter !== "all"
      ? '<p class="empty-note">Keine Treffer für Suche/Filter.</p>'
      : '<p class="empty-note">Kein Download-Verlauf.</p>';
    return;
  }
  const shown = _downloadHistoryExpanded ? filtered : filtered.slice(0, _DOWNLOAD_HISTORY_PREVIEW_ROWS);
  const rest = filtered.length - shown.length;
  let more = "";
  if (rest > 0) {
    more = `<button type="button" class="btn btn-sm btn-outline-secondary mt-2 downloads-history-more-btn">${rest} weitere anzeigen</button>`;
  } else if (_downloadHistoryExpanded && filtered.length > _DOWNLOAD_HISTORY_PREVIEW_ROWS) {
    more = '<button type="button" class="btn btn-sm btn-outline-secondary mt-2 downloads-history-more-btn">Weniger anzeigen</button>';
  }
  el.innerHTML = '<div class="row-list">' + shown.map(_downloadHistoryRowHtml).join("") + "</div>" + more;
  _applyRetryButtonsBusyState();
}

function renderDownloads(el, body) {
  _lastDownloadHistory = body;
  _renderDownloadsKpi(body.entries);
  _renderDownloadsPipeline(body.entries);
  _renderDownloadsAttention(body.entries);
  _renderDownloadsLast(body.entries);
  _rerenderDownloads();
}

function loadDownloads() {
  return _loadInto("downloads-content", "/api/v1/downloads/history?limit=200", renderDownloads)
    .then(_renderDownloadsSummaryUnavailable);
}

// ── Init ─────────────────────────────────────────────────────────────────

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    _rehydrateActiveDownloadJob();
    loadDownloads();
    setInterval(() => { if (!document.getElementById("dashboard-view").hidden) loadDownloads(); }, 30000);
  });

  document.getElementById("download-start-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = document.getElementById("download-url-input");
    const url = input.value.trim();
    if (url) startDownload(url);
  });

  document.getElementById("downloads-content").addEventListener("click", (ev) => {
    const retryBtn = ev.target.closest(".download-retry-btn");
    if (retryBtn) { startDownload(retryBtn.dataset.url); return; }
    const moreBtn = ev.target.closest(".downloads-history-more-btn");
    if (moreBtn) { _downloadHistoryExpanded = !_downloadHistoryExpanded; _rerenderDownloads(); }
  });

  document.getElementById("downloads-search").addEventListener("input", _rerenderDownloads);

  document.getElementById("downloads-status-filter").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-filter]");
    if (btn) _setDownloadStatusFilter(btn.dataset.filter);
  });

  document.getElementById("downloads-attention-content").addEventListener("click", (ev) => {
    if (!ev.target.closest("#downloads-attention-open-btn")) return;
    _setDownloadStatusFilter("failed");
    document.getElementById("downloads-history-card").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

initPage();
