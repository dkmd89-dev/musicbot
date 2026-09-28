// control_center/static/pages/downloads.js
// Downloads-Seite nach docs/CONTROL_CENTER_UI_STANDARD.md (CC-UI Downloads).
// Endpunkte, Polling (Job 1 s, Verlauf 30 s) und Rehydrate unverändert.

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

// Die fuenf dreiwertigen Tier-Flags des Verlaufs (True/False/None, None =
// "keine Aussage moeglich", siehe services/downloader/download_history.py).
const _DL_TIERS = [
  { key: "genre_ok", label: "Genre", abbr: "Ge" },
  { key: "lyrics_ok", label: "Lyrics", abbr: "Ly" },
  { key: "cover_ok", label: "Cover", abbr: "Co" },
  { key: "mb_ok", label: "MusicBrainz", abbr: "MB" },
  { key: "loudness_ok", label: "Loudness", abbr: "Lo" },
];

// Anzeige-Texte für Verlauf-Status (Standard Abschnitt 2).
const _DL_STATUS_LABEL = { success: "Fertig", failed: "Fehler", cancelled: "Abgebrochen", duplicate: "Duplikat" };

function _tierBadgeHtml(label, abbr, value) {
  const cls = value === true ? "bg-green-lt" : value === false ? "bg-red-lt" : "bg-secondary-lt";
  const state = value === true ? "ok" : value === false ? "fehlt" : "keine Aussage";
  return `<span class="badge ${cls}" title="${_escapeHtml(label)}: ${state}">${_escapeHtml(abbr)}</span>`;
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

function _absoluteTimeText(timestamp) {
  const d = new Date(timestamp);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

// ── Aktueller Download ───────────────────────────────────────────────────

function _renderDownloadIdle() {
  ccState.empty(document.getElementById("download-status-content"), "Kein aktiver Download",
    "Starte oben einen Download per URL.");
  _renderJobEvents(null);
}

function _formatResultMessage(message) {
  return _escapeHtml(message || "").replace(/`([^`]+)`/g, "<code>$1</code>");
}

// Verlinkung Duplikat-Ergebnis -> Artist-Detailseite (P2) - der Artist-Name
// kommt bereits strukturiert aus dem Job-Result (jobs.py haengt ihn neben
// der vorformatierten Nachricht an), keine Text-Extraktion noetig.
function _duplicateArtistLinkHtml(job) {
  const artist = job.result && job.result.artist;
  if (!artist) return "";
  const href = apiUrl(`/library/${encodeURIComponent(artist)}`);
  return `<div class="mt-2"><a href="${href}">Zum Artist „${_escapeHtml(artist)}"</a></div>`;
}

// Schritt-Verlauf (D.12b) - job.events kommt aus JobRegistry (aelteste
// zuerst). Uhrzeit lokal formatiert, Meldung immer escaped. Anzeige im
// Seitenpanel #download-events-offcanvas (Standard Abschnitt 9).
function _formatEventTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function _jobEventsListHtml(job) {
  const events = job && Array.isArray(job.events) ? job.events : [];
  if (!events.length) return "";
  const running = job.status === "PENDING" || job.status === "RUNNING";
  const rows = events.map((e, i) => {
    const current = running && i === events.length - 1;
    const icon = current ? ccIcon("refresh") : ccIcon("check");
    return '<li class="timeline-event">'
      + `<div class="timeline-event-icon ${current ? "bg-teal-lt" : "bg-green-lt"}">${icon}</div>`
      + '<div class="card timeline-event-card"><div class="card-body py-2">'
      + `<div class="text-secondary float-end small font-monospace">${_escapeHtml(_formatEventTime(e.at))}</div>`
      + `<div>${_escapeHtml(e.message)}</div></div></div></li>`;
  }).join("");
  return `<ul class="timeline timeline-simple download-job-events">${rows}</ul>`;
}
function _renderJobEvents(job) {
  const el = document.getElementById("download-events-content");
  if (!el) return;
  const list = _jobEventsListHtml(job);
  el.innerHTML = list || '<div class="text-secondary">Noch keine Schritte.</div>';
}
function _jobEventsButtonHtml(job) {
  const count = job && Array.isArray(job.events) ? job.events.length : 0;
  if (!count) return "";
  return `<button type="button" class="btn btn-sm btn-ghost-secondary" data-bs-toggle="offcanvas" data-bs-target="#download-events-offcanvas">${ccIcon("history", "me-1")}Verlauf (${count})</button>`;
}

// Phasen des Web-Download-Jobs, abgeleitet aus den Job-Meldungen von
// control_center/routers/jobs.py::_run_download_job() (dort festgeschrieben,
// siehe tests/test_control_center_downloads_page.py). Unbekannte Meldung ->
// keine Phase hervorgehoben.
const _DL_PHASES = ["Prüfung", "Download", "Metadaten", "Abschluss"];
function _downloadPhaseIndex(message) {
  const m = message || "";
  if (m.startsWith("Duplikat-Prüfung")) return 0;
  if (m.startsWith("Download läuft")) return 1;
  if (m.startsWith("Metadaten")) return 2;
  if (m.startsWith("Zusammenfassung")) return 3;
  return -1;
}
function _downloadPhasesHtml(job) {
  const idx = job.status === "PENDING" ? -1 : _downloadPhaseIndex(job.message);
  if (idx < 0) return "";
  const items = _DL_PHASES.map((p, i) =>
    `<li class="step-item${i === idx ? " active" : ""}">${_escapeHtml(p)}</li>`).join("");
  return `<ul class="steps steps-counter steps-teal my-3 d-none d-md-flex">${items}</ul>`
    + `<div class="d-md-none small text-secondary my-2">Phase ${idx + 1} von ${_DL_PHASES.length} · ${_escapeHtml(_DL_PHASES[idx])}</div>`;
}

function _renderDownloadResult(job) {
  const el = document.getElementById("download-status-content");
  _renderJobEvents(job);
  const events = _jobEventsButtonHtml(job);
  const footer = events ? `<div class="mt-2">${events}</div>` : "";
  if (job.status === "SUCCEEDED") {
    const outcome = job.result && job.result.outcome;
    const dup = outcome === "duplicate";
    const msg = _formatResultMessage(job.result && job.result.message);
    const artistLink = dup ? _duplicateArtistLinkHtml(job) : "";
    el.innerHTML = `<div class="alert ${dup ? "alert-info" : "alert-success"} mb-0">`
      + `<div class="d-flex gap-2">${ccIcon(dup ? "copy" : "check", "alert-icon")}`
      + `<div class="cc-pre-wrap">${msg}${artistLink}</div></div></div>${footer}`;
    return;
  }
  if (job.status === "CANCELLED") {
    el.innerHTML = `<div class="alert alert-secondary mb-0"><div class="d-flex gap-2">${ccIcon("x", "alert-icon")}`
      + `<div>Download abgebrochen.</div></div></div>${footer}`;
    return;
  }
  el.innerHTML = `<div class="alert alert-danger mb-0"><div class="d-flex gap-2">${ccIcon("alert", "alert-icon")}`
    + `<div>${_escapeHtml(job.error || "Unbekannter Fehler.")}</div></div></div>${footer}`;
}

// Prozent-Text + Laufzeit (P1) - started_at liefert das Backend bereits.
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

// Download-Typ-Badge (P2) - job.context wird bei Job-Erstellung gesetzt.
function _downloadTypeBadgeHtml(job) {
  const type = job.context && job.context.download_type;
  if (!type) return "";
  const label = type === "playlist" ? "Playlist" : "Einzeltitel";
  return `<span class="badge bg-secondary-lt me-1">${_escapeHtml(label)}</span>`;
}

function _renderDownloadJob(job) {
  if (job.status === "PENDING" || job.status === "RUNNING") {
    const pct = Math.round(job.progress || 0);
    const elapsed = _elapsedText(job);
    const statusLabel = job.status === "PENDING" ? "Wartet" : "Läuft";
    const idShort = job.job_id ? String(job.job_id).slice(0, 8) : "";
    _renderJobEvents(job);
    document.getElementById("download-status-content").innerHTML = `
      <div class="d-flex align-items-start gap-2 mb-1">
        <div class="flex-fill min-w-0">
          <div class="fw-medium text-truncate">${_escapeHtml(job.message || "Download")}</div>
          <div class="text-secondary small">${_downloadTypeBadgeHtml(job)}${idShort ? "Job " + _escapeHtml(idShort) : ""}${elapsed ? " · " + _escapeHtml(elapsed) : ""}</div>
        </div>
        ${ccStatusBadge(ccStatusKind(job.status), statusLabel)}
      </div>
      ${_downloadPhasesHtml(job)}
      <div class="d-flex justify-content-between small text-secondary mb-1 mt-2"><span>Fortschritt</span><span>${pct} %</span></div>
      <div class="progress progress-sm">
        <div class="progress-bar bg-teal" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
      </div>
      <div class="d-flex mt-3">
        ${_jobEventsButtonHtml(job)}
        <button type="button" id="download-cancel-btn" class="btn btn-sm btn-ghost-danger ms-auto">${ccIcon("x", "me-1")}Abbrechen</button>
      </div>
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
  let job;
  try {
    job = await ccApi("GET", `/api/v1/jobs/download/${encodeURIComponent(jobId)}`);
  } catch (err) {
    if (err.status === 401) { _stopDownloadPolling(); return; }
    if (err.status === 404) {
      // Rehydrate-Fall: Job existiert nicht (mehr) - JobRegistry ist rein
      // prozessspeicher-basiert und ueberlebt keinen Neustart. Kein Fehler,
      // sondern "kein aktiver Download (mehr)".
      _stopDownloadPolling();
      _setDownloadFormBusy(false);
      _persistCurrentDownloadJobId(null);
      _renderDownloadIdle();
    }
    return; // sonstige Fehler: nächster Poll versucht es erneut
  }
  _renderDownloadJob(job);
}

async function startDownload(url) {
  _setDownloadFormBusy(true);
  const statusEl = document.getElementById("download-status-content");
  ccState.loading(statusEl);
  let job;
  try {
    job = await ccApi("POST", "/api/v1/jobs/download", { url });
  } catch (err) {
    if (err.status === 401) return;
    statusEl.innerHTML = `<div class="alert alert-danger mb-0"><div class="d-flex gap-2">${ccIcon("alert", "alert-icon")}`
      + `<div>Download konnte nicht gestartet werden: ${_escapeHtml(err.message)}</div></div></div>`;
    _setDownloadFormBusy(false);
    return;
  }
  _currentDownloadJobId = job.job_id;
  _persistCurrentDownloadJobId(_currentDownloadJobId);
  ccToast("ok", "Download gestartet", job.job_id ? `Job ${String(job.job_id).slice(0, 8)}` : "");
  _renderDownloadJob(job);
  _stopDownloadPolling();
  _downloadJobPollTimer = setInterval(() => _pollDownloadJob(_currentDownloadJobId), 1000);
}

async function cancelDownload() {
  if (!_currentDownloadJobId) return;
  const confirmed = await ccConfirm({
    title: "Download abbrechen?",
    text: "Bereits fertige Titel bleiben erhalten.",
    confirmLabel: "Abbrechen",
    danger: true,
  });
  if (!confirmed || !_currentDownloadJobId) return;
  const btn = document.getElementById("download-cancel-btn");
  if (btn) btn.disabled = true;
  try {
    await ccApi("POST", `/api/v1/jobs/download/${encodeURIComponent(_currentDownloadJobId)}/cancel`);
  } catch (err) {
    if (err.status !== 401) ccToast("error", "Abbrechen fehlgeschlagen", err.message);
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
  ccState.loading(document.getElementById("download-status-content"));
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
  const label = _DL_STATUS_LABEL[e.status] || e.status || "–";
  return "<tr>"
    + `<td class="w-1">${ccStatusBadge(ccStatusKind(e.status), label)}</td>`
    + `<td class="cc-cell-truncate"><div class="text-truncate">${_escapeHtml(e.title)}</div>`
    + `<div class="text-secondary small text-truncate">${_escapeHtml(e.artist)}</div></td>`
    + `<td class="d-none d-md-table-cell text-nowrap">${_DL_TIERS.map((t) => _tierBadgeHtml(t.label, t.abbr, e[t.key])).join(" ")}</td>`
    + `<td class="text-secondary small text-nowrap" title="${_escapeHtml(_absoluteTimeText(e.timestamp))}">${_escapeHtml(_relativeTimeText(e.timestamp))}</td>`
    + `<td class="w-1"><button type="button" class="btn btn-sm btn-icon btn-ghost-secondary download-retry-btn" data-url="${_escapeHtml(e.url)}" title="Erneut versuchen" aria-label="Erneut versuchen">${ccIcon("refresh")}</button></td>`
    + "</tr>";
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

// Schwellen unverändert (90/70), Farben nach Standard Abschnitt 2.
function _pctBarClass(pct) {
  if (pct === null) return "bg-secondary";
  if (pct >= 90) return "bg-green";
  if (pct >= 70) return "bg-yellow";
  return "bg-red";
}

function _kpiCardHtml(icon, color, label, value, tooltip) {
  return `
    <div class="col-6 col-lg-3">
      <div class="card card-sm h-100" title="${_escapeHtml(tooltip)}"><div class="card-body"><div class="row align-items-center g-3">
        <div class="col-auto d-none d-sm-block"><span class="avatar bg-${color}-lt">${ccIcon(icon)}</span></div>
        <div class="col min-w-0">
          <div class="subheader text-truncate">${_escapeHtml(label)}</div>
          <div class="h2 mb-0">${_escapeHtml(value)}</div>
        </div>
      </div></div></div>
    </div>
  `;
}

// KPI-Leiste - reine Client-Aggregation ueber die geladenen Eintraege
// (bis zu 200, siehe loadDownloads()). Bewusst NICHT als "Gesamt"/"All-Time"
// beschriftet, da hoechstens die geladene Ansicht ausgewertet wird.
// Reihenfolge: Menge -> Erfolg -> Probleme -> Metadatenqualitaet.
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
    _kpiCardHtml("download", "teal", "Downloads", String(entries.length),
      "Anzahl der geladenen Verlaufseinträge.") +
    _kpiCardHtml("check", "green", "Erfolgsquote", `${rate} %`,
      "Anteil erfolgreicher Downloads an den geladenen Verlaufseinträgen.") +
    _kpiCardHtml("alert", "red", "Fehlgeschlagen", String(failed),
      "Anzahl fehlgeschlagener Downloads in den geladenen Verlaufseinträgen.") +
    _kpiCardHtml("chart", "purple", "Metadaten", _formatPct(pipeline.pct),
      "Durchschnitt aller bekannten Metadaten-Prüfungen der geladenen Verlaufseinträge.");
}

// Historische Aggregation - ausdruecklich NICHT der aktuell laufende Job.
function _renderDownloadsPipeline(entries) {
  const el = document.getElementById("downloads-pipeline-content");
  if (!el) return;
  const stats = _downloadsPipelineStats(entries);
  if (!stats.known) {
    ccState.empty(el, "Noch keine Metadaten-Prüfungen", "Erscheint nach den ersten Downloads.");
    return;
  }
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
    el.innerHTML = '<div class="card-body"><div class="d-flex align-items-center gap-3">'
      + `<span class="avatar bg-green-lt">${ccIcon("check")}</span>`
      + '<div><div class="fw-medium">Keine auffälligen Downloads</div>'
      + '<div class="text-secondary small">Keine Fehler, keine fehlenden Metadaten</div></div></div></div>';
    return;
  }

  let html = "";
  if (failedEntries.length) {
    const last = failedEntries[0];
    html += `
      <div class="card-body">
        <div class="d-flex align-items-center gap-2 mb-2">
          ${ccStatusBadge("error", `${failedEntries.length} fehlgeschlagen`)}
        </div>
        <div class="text-secondary small">Letzter Fehler</div>
        <div class="text-truncate">${_escapeHtml(last.artist)} – ${_escapeHtml(last.title)}</div>
        <div class="text-secondary small mb-2" title="${_escapeHtml(_absoluteTimeText(last.timestamp))}">${_escapeHtml(_relativeTimeText(last.timestamp))}</div>
        <button type="button" id="downloads-attention-open-btn" class="btn btn-sm">${ccIcon("history", "me-1")}Fehler im Verlauf zeigen</button>
      </div>
    `;
  }
  if (missing.length) {
    html += '<div class="list-group list-group-flush">' + missing.map((t) => `
      <div class="list-group-item d-flex justify-content-between align-items-center">
        <span>ohne ${_escapeHtml(t.label)}</span>
        <span class="badge bg-yellow-lt">${t.count}</span>
      </div>
    `).join("") + "</div>";
  }
  el.innerHTML = html;
}

function _checklistRowHtml(label, value, unknownText) {
  const icon = value === true
    ? `<span class="text-green">${ccIcon("check")}</span>`
    : value === false
      ? `<span class="text-red">${ccIcon("x")}</span>`
      : `<span class="text-secondary">${ccIcon("minus")}</span>`;
  const hint = value === null || value === undefined ? ` <span class="text-secondary small">(${_escapeHtml(unknownText)})</span>` : "";
  return `<div class="d-flex align-items-center gap-2 py-1">${icon}<span>${_escapeHtml(label)}${hint}</span></div>`;
}

function _renderDownloadsLast(entries) {
  const el = document.getElementById("downloads-last-content");
  if (!el) return;
  if (!entries.length) {
    ccState.empty(el, "Noch kein Download im Verlauf");
    return;
  }
  const e = entries[0];
  const downloadOk = e.status === "success" ? true : e.status === "failed" ? false : null;
  el.innerHTML = `
    <div class="d-flex justify-content-between align-items-baseline gap-2 mb-2">
      <div class="fw-medium text-truncate">${_escapeHtml(e.artist)} – ${_escapeHtml(e.title)}</div>
      <div class="text-secondary small text-nowrap" title="${_escapeHtml(_absoluteTimeText(e.timestamp))}">${_escapeHtml(_relativeTimeText(e.timestamp))}</div>
    </div>
    ${_checklistRowHtml("Download", downloadOk, e.status)}
    ${_DL_TIERS.map((t) => _checklistRowHtml(t.label, e[t.key], "keine Aussage")).join("")}
  `;
}

function _renderDownloadsSummaryUnavailable() {
  if (_lastDownloadHistory) return;
  const pipeline = document.getElementById("downloads-pipeline-content");
  if (pipeline) ccState.empty(pipeline, "Keine Daten verfügbar");
  const attention = document.getElementById("downloads-attention-content");
  if (attention) { attention.innerHTML = '<div class="card-body"></div>'; ccState.empty(attention.firstElementChild, "Keine Daten verfügbar"); }
  const last = document.getElementById("downloads-last-content");
  if (last) ccState.empty(last, "Keine Daten verfügbar");
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
    if (q || _downloadStatusFilter !== "all") ccState.empty(el, "Keine Treffer", "Suche oder Filter anpassen.");
    else ccState.empty(el, "Noch keine Downloads", "Starte oben einen Download per URL.");
    return;
  }
  const shown = _downloadHistoryExpanded ? filtered : filtered.slice(0, _DOWNLOAD_HISTORY_PREVIEW_ROWS);
  const rest = filtered.length - shown.length;
  let more = "";
  if (rest > 0) {
    more = `<div class="card-footer"><button type="button" class="btn btn-sm downloads-history-more-btn">${rest} weitere anzeigen</button></div>`;
  } else if (_downloadHistoryExpanded && filtered.length > _DOWNLOAD_HISTORY_PREVIEW_ROWS) {
    more = '<div class="card-footer"><button type="button" class="btn btn-sm downloads-history-more-btn">Weniger anzeigen</button></div>';
  }
  el.innerHTML = '<div class="table-responsive"><table class="table card-table table-vcenter mb-0">'
    + '<thead><tr><th>Status</th><th>Track</th><th class="d-none d-md-table-cell">Metadaten</th><th>Zeit</th><th></th></tr></thead>'
    + "<tbody>" + shown.map(_downloadHistoryRowHtml).join("") + "</tbody></table></div>" + more;
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
  return _loadInto("downloads-content", "/api/v1/downloads/history?limit=200", renderDownloads, loadDownloads)
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
