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

function _tierBadgeHtml(label, abbr, value) {
  const cls = value === true ? "bg-success" : value === false ? "bg-danger" : "bg-secondary";
  return `<span class="badge ${cls}" title="${_escapeHtml(label)}">${_escapeHtml(abbr)}</span>`;
}

function _formatResultMessage(message) {
  return _escapeHtml(message || "").replace(/`([^`]+)`/g, "<code>$1</code>");
}

function _renderDownloadResult(job) {
  const el = document.getElementById("download-status-content");
  if (job.status === "SUCCEEDED") {
    const outcome = job.result && job.result.outcome;
    const alertClass = outcome === "duplicate" ? "alert-info" : "alert-success";
    const msg = _formatResultMessage(job.result && job.result.message);
    el.innerHTML = `<div class="alert ${alertClass} mb-0" style="white-space: pre-wrap;">${msg}</div>`;
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

function _renderDownloadJob(job) {
  if (job.status === "PENDING" || job.status === "RUNNING") {
    const pct = Math.round(job.progress || 0);
    const elapsed = _elapsedText(job);
    document.getElementById("download-status-content").innerHTML = `
      <div class="mb-2">
        <div class="d-flex justify-content-between align-items-baseline gap-2 mb-1">
          <div class="text-secondary small text-truncate">${_escapeHtml(job.message || "")}</div>
          <div class="text-secondary small text-nowrap">${pct}%${elapsed ? " · " + _escapeHtml(elapsed) : ""}</div>
        </div>
        <div class="progress mb-1">
          <div class="progress-bar" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
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
      document.getElementById("download-status-content").innerHTML = "";
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
          <span class="text-truncate">${_escapeHtml(e.title)} — ${_escapeHtml(e.artist)}</span>
        </div>
        <div class="d-flex align-items-center gap-1 mt-1">
          ${_tierBadgeHtml("Genre", "Ge", e.genre_ok)}
          ${_tierBadgeHtml("Lyrics", "Ly", e.lyrics_ok)}
          ${_tierBadgeHtml("Cover", "Co", e.cover_ok)}
          ${_tierBadgeHtml("MusicBrainz", "MB", e.mb_ok)}
          ${_tierBadgeHtml("Loudness", "Lo", e.loudness_ok)}
          <button type="button" class="btn btn-sm btn-outline-secondary download-retry-btn" data-url="${_escapeHtml(e.url)}" title="Erneut versuchen">🔁</button>
        </div>
      </div>
      <div class="row-count">${new Date(e.timestamp).toLocaleString()}</div>
    </div>
  `;
}

// KPI-Leiste (P1) - reine Client-Aggregation ueber die geladenen Eintraege
// (bis zu 200, siehe loadDownloads()). Bewusst NICHT als "Gesamt"/"All-Time"
// beschriftet, da hoechstens die geladene Ansicht ausgewertet wird, keine
// serverseitige Statistik (kein neuer Endpunkt) - identisches Prinzip wie
// health.html's "keine vorgetaeuschten Health-Werte".
function _renderDownloadsKpi(entries) {
  const kpiEl = document.getElementById("downloads-kpi");
  if (!kpiEl) return;
  if (!entries.length) { kpiEl.hidden = true; kpiEl.innerHTML = ""; return; }
  const success = entries.filter((e) => e.status === "success").length;
  const failed = entries.filter((e) => e.status === "failed").length;
  const rate = entries.length ? Math.round((success / entries.length) * 100) : 0;
  const lastFailed = entries.find((e) => e.status === "failed");
  kpiEl.hidden = false;
  kpiEl.innerHTML = `
    <div class="card card-sm">
      <div class="card-body py-3">
        <div class="text-secondary small">Geladene Einträge</div>
        <div class="h2 mb-0">${entries.length}</div>
      </div>
    </div>
    <div class="card card-sm">
      <div class="card-body py-3">
        <div class="text-secondary small">Erfolgsquote (geladen)</div>
        <div class="h2 mb-0">${rate}%</div>
      </div>
    </div>
    <div class="card card-sm">
      <div class="card-body py-3">
        <div class="text-secondary small">Fehlgeschlagen (geladen)</div>
        <div class="h2 mb-0">${failed}</div>
      </div>
    </div>
    <div class="card card-sm">
      <div class="card-body py-3">
        <div class="text-secondary small">Zuletzt fehlgeschlagen</div>
        <div class="h4 mb-0 text-truncate">${lastFailed ? _escapeHtml(new Date(lastFailed.timestamp).toLocaleString()) : "—"}</div>
      </div>
    </div>
  `;
}

function _rerenderDownloads() {
  const el = document.getElementById("downloads-content");
  if (!el || !_lastDownloadHistory) return;
  const q = _downloadsSearchQuery();
  const entries = _lastDownloadHistory.entries;
  const filtered = q ? entries.filter((e) => _downloadEntryMatchesQuery(e, q)) : entries;
  if (!filtered.length) {
    el.innerHTML = q
      ? '<p class="empty-note">Keine Treffer für die Suche.</p>'
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
  _rerenderDownloads();
}

function loadDownloads() {
  return _loadInto("downloads-content", "/api/v1/downloads/history?limit=200", renderDownloads);
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
}

initPage();
