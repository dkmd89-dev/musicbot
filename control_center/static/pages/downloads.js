// control_center/static/pages/downloads.js

let _currentDownloadJobId = null;
let _downloadJobPollTimer = null;

function _setDownloadFormBusy(busy) {
  document.getElementById("download-start-btn").disabled = busy;
  document.getElementById("download-url-input").disabled = busy;
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

function _renderDownloadJob(job) {
  if (job.status === "PENDING" || job.status === "RUNNING") {
    const pct = Math.round(job.progress || 0);
    document.getElementById("download-status-content").innerHTML = `
      <div class="mb-2">
        <div class="progress mb-1">
          <div class="progress-bar" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
        <div class="text-secondary small">${_escapeHtml(job.message || "")}</div>
      </div>
      <button type="button" id="download-cancel-btn" class="btn btn-sm btn-outline-danger">Abbrechen</button>
    `;
    document.getElementById("download-cancel-btn").addEventListener("click", cancelDownload);
    return;
  }
  _stopDownloadPolling();
  _setDownloadFormBusy(false);
  _renderDownloadResult(job);
}

async function _pollDownloadJob(jobId) {
  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/download/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); _stopDownloadPolling(); return; }
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

// ── Verlauf ──────────────────────────────────────────────────────────────

function renderDownloads(el, body) {
  if (!body.entries.length) { el.innerHTML = '<p class="empty-note">Kein Download-Verlauf.</p>'; return; }
  el.innerHTML = '<div class="row-list">' + body.entries.map((e) => `
    <div class="row-item">
      <div class="row-main">
        <span class="badge badge-status-${_escapeHtml(e.status)}">${_escapeHtml(e.status)}</span>
        ${_escapeHtml(e.title)} — ${_escapeHtml(e.artist)}
        ${_tierBadgeHtml("Genre", "Ge", e.genre_ok)}
        ${_tierBadgeHtml("Lyrics", "Ly", e.lyrics_ok)}
        ${_tierBadgeHtml("Cover", "Co", e.cover_ok)}
        ${_tierBadgeHtml("MusicBrainz", "MB", e.mb_ok)}
        ${_tierBadgeHtml("Loudness", "Lo", e.loudness_ok)}
        <button type="button" class="btn btn-sm btn-outline-secondary download-retry-btn" data-url="${_escapeHtml(e.url)}" title="Erneut versuchen">🔁</button>
      </div>
      <div class="row-count">${new Date(e.timestamp).toLocaleString()}</div>
    </div>
  `).join("") + "</div>";
}

function loadDownloads() {
  return _loadInto("downloads-content", "/api/v1/downloads/history?limit=10", renderDownloads);
}

// ── Init ─────────────────────────────────────────────────────────────────

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
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
    const btn = ev.target.closest(".download-retry-btn");
    if (btn) startDownload(btn.dataset.url);
  });
}

initPage();
