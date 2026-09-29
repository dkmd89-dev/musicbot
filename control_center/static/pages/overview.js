// control_center/static/pages/overview.js
// Overview beantwortet die Leitfrage:
// "Wie geht es meinem MusicBot gerade und was braucht Aufmerksamkeit?"
// Darstellung nach docs/CONTROL_CENTER_UI_STANDARD.md (CC-UI Overview).
//
// Hinweis: Es gibt KEINEN leichtgewichtigen Repair-Summary-Endpunkt.
// GET /api/v1/library/repair-plan loest einen vollen Library-Scan aus
// (~37s auf Produktion) und darf deshalb NICHT im Auto-Load laufen.
// Die Attention-Karte beschraenkt sich daher bewusst auf Findings
// (GET /api/v1/library/findings/summary ist guenstig und persistent).
//
// Health-Kachel: GET /api/v1/library/health/cached (nicht /health!) —
// /health loest denselben ~37s-Scan aus und darf ebenfalls nicht im
// Auto-Load laufen. /health/cached liest ausschliesslich den bereits
// vorhandenen persistenten Report (siehe control_center/routers/health.py).

// Aggregierter Zustand der Seite
const _overviewState = {
  health: null,     // { status, score, library: { files, artists, albums } }
  navidrome: null,  // { connected, artist_count }
  findings: 0,
};

// Schwellen der Kennzahlen (unverändert): ab 70 % Warnung, ab 90 % kritisch.
function _metricColorClass(percent) {
  if (percent == null) return "";
  if (percent >= 90) return "text-danger";
  if (percent >= 70) return "text-warning";
  return "";
}

// Schwellen der Aufmerksamkeits-Karte (unverändert): 0 ok, 1-24 Warnung,
// ab 25 kritisch.
function _attentionKind(openFindings) {
  if (openFindings === 0) return "ok";
  return openFindings >= 25 ? "error" : "warn";
}

const _ATTENTION_COLOR = { ok: "green", warn: "yellow", error: "red" };

// Anzeige-Texte für Download-Verlauf-Status (Standard Abschnitt 2).
const _HISTORY_STATUS_LABEL = {
  success: "Fertig", failed: "Fehler", cancelled: "Abgebrochen", duplicate: "Duplikat",
};

function _formatMb(mb) {
  if (mb == null) return "";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

function _formatGb(gb) {
  if (gb == null) return "";
  if (gb >= 1024) return `${(gb / 1024).toFixed(2)} TB`;
  return `${gb.toFixed(1)} GB`;
}

function _formatStartedAt(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const date = d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return `seit ${date} ${time}`;
}

function _setMetric(valueEl, percent) {
  if (!valueEl) return;
  valueEl.textContent = percent != null ? `${Number(percent).toFixed(1)} %` : "–";
  valueEl.className = ("h2 mb-0 " + _metricColorClass(percent)).trim();
}

// ══════════════════════════════════════════════════════════════════
// System-Metriken: GET /api/v1/admin/system/status
// Bot-Service-Uptime aus systemctl ActiveEnterTimestamp (NICHT
// psutil.boot_time, das wäre die Host-Bootzeit).
// ══════════════════════════════════════════════════════════════════
async function loadSystemMetrics() {
  const el = (id) => document.getElementById(id);
  const cpuSub = el("metric-cpu-sub");
  const ramSub = el("metric-ram-sub");
  const diskSub = el("metric-disk-sub");
  const botVal = el("metric-bot-value");
  const botSub = el("metric-bot-sub");
  const sysOs = el("system-platform-os");
  const sysPy = el("system-platform-python");
  const sysUp = el("system-uptime-value");
  const sysStart = el("system-uptime-started");
  const sysLoad = el("system-load-value");
  const sysSwap = el("system-swap-value");

  let data;
  try {
    data = await ccApi("GET", "/api/v1/admin/system/status");
  } catch (err) {
    if (err.status === 401) return;
    ["metric-cpu-value", "metric-ram-value", "metric-disk-value"].forEach((id) => _setMetric(el(id), null));
    if (cpuSub) cpuSub.textContent = "Nicht abrufbar";
    [ramSub, diskSub, botSub, sysStart].forEach((e) => { if (e) e.textContent = ""; });
    if (botVal) botVal.textContent = "–";
    [sysOs, sysPy, sysUp, sysLoad, sysSwap].forEach((e) => { if (e) e.textContent = "–"; });
    console.error("System-Metriken konnten nicht geladen werden:", err);
    return;
  }

  _setMetric(el("metric-cpu-value"), data.cpu_percent);
  if (cpuSub) cpuSub.textContent = data.cpu_count ? `${data.cpu_count} Kerne` : "";

  _setMetric(el("metric-ram-value"), data.memory_percent);
  if (ramSub) {
    ramSub.textContent = data.memory_used_mb != null && data.memory_total_mb != null
      ? `${_formatMb(data.memory_used_mb)} / ${_formatMb(data.memory_total_mb)}` : "";
  }

  _setMetric(el("metric-disk-value"), data.disk_percent);
  if (diskSub) {
    diskSub.textContent = data.disk_used_gb != null && data.disk_total_gb != null
      ? `${_formatGb(data.disk_used_gb)} / ${_formatGb(data.disk_total_gb)}` : "";
  }

  if (botVal) {
    if (data.bot_service_active === true) botVal.innerHTML = ccStatusBadge("ok", "Online");
    else if (data.bot_service_active === false) botVal.innerHTML = ccStatusBadge("error", "Offline");
    else botVal.textContent = "–";
  }
  if (botSub) botSub.textContent = data.bot_uptime_formatted ? `${data.bot_uptime_formatted} Laufzeit` : "";

  if (sysOs) {
    sysOs.textContent = data.platform_os
      ? `${data.platform_os} ${data.platform_release || ""}`.trim() : "–";
  }
  if (sysPy) {
    const parts = [];
    if (data.platform_python) parts.push(`Python ${data.platform_python}`);
    if (data.platform_arch) parts.push(data.platform_arch);
    sysPy.textContent = parts.length ? parts.join(" · ") : "–";
  }
  if (sysUp) sysUp.textContent = data.bot_uptime_formatted || "–";
  if (sysStart) sysStart.textContent = _formatStartedAt(data.bot_started_at);

  if (sysLoad) {
    sysLoad.textContent = data.load_avg_1 != null && data.load_avg_5 != null && data.load_avg_15 != null
      ? `${data.load_avg_1.toFixed(2)} · ${data.load_avg_5.toFixed(2)} · ${data.load_avg_15.toFixed(2)}`
      : "nicht verfügbar";
  }
  if (sysSwap) {
    if (data.swap_total_gb != null && data.swap_used_gb != null) {
      if (data.swap_total_gb === 0) {
        sysSwap.textContent = "kein Swap";
      } else {
        const pct = data.swap_percent != null ? ` (${data.swap_percent.toFixed(0)} %)` : "";
        sysSwap.textContent = `${data.swap_used_gb.toFixed(1)} / ${data.swap_total_gb.toFixed(1)} GB${pct}`;
      }
    } else {
      sysSwap.textContent = "nicht verfügbar";
    }
  }
}

// ══════════════════════════════════════════════════════════════════
// Library-Status: GET /api/v1/library/health/cached
// Nutzt ausschließlich den persistenten Report - KEIN Library-Scan.
// ══════════════════════════════════════════════════════════════════
function _renderLibraryHealthBar(health, stale) {
  const wrap = document.getElementById("status-library-health-bar");
  const fill = document.getElementById("status-library-health-fill");
  const label = document.getElementById("status-library-health-label");
  if (!wrap || !fill || !label) return;

  const score = (health && health.score != null) ? Number(health.score) : null;
  if (score == null) {
    wrap.hidden = true;
    return;
  }
  const pct = Math.max(0, Math.min(100, score));
  const status = (health && health.status) ? health.status : "";
  // Farbe nach Status (Standard Abschnitt 2), nicht mehr nach Score-Schwellen.
  const color = { ok: "green", warn: "yellow", error: "red" }[ccStatusKind(status)] || "secondary";
  fill.style.width = `${pct}%`;
  fill.className = `progress-bar bg-${color}`;
  fill.setAttribute("aria-valuenow", String(pct));
  fill.setAttribute("aria-valuemin", "0");
  fill.setAttribute("aria-valuemax", "100");
  label.textContent = `${status} · ${score.toFixed(0)}/100${stale ? " · Bericht veraltet" : ""}`;
  wrap.hidden = false;
}

async function loadLibraryStatus() {
  const valueEl = document.getElementById("status-library-value");
  const hintEl = document.getElementById("status-library-hint");

  let data;
  try {
    data = await ccApi("GET", "/api/v1/library/health/cached");
  } catch (err) {
    if (err.status === 401) return;
    if (err.status === 404) {
      if (valueEl) valueEl.textContent = "Nicht geprüft";
      if (hintEl) hintEl.textContent = "Noch kein Health-Report vorhanden.";
      return;
    }
    if (valueEl) valueEl.textContent = "–";
    if (hintEl) ccState.error(hintEl, "Library-Status nicht abrufbar.", loadLibraryStatus);
    console.error("Library-Status konnte nicht geladen werden:", err);
    return;
  }

  _overviewState.health = data;
  const library = data.library || {};
  const health = data.health || {};

  if (valueEl) valueEl.textContent = `${Number(library.files || 0).toLocaleString("de-DE")} Dateien`;
  if (hintEl) {
    const parts = [
      `${Number(library.artists || 0).toLocaleString("de-DE")} Artists`,
      `${Number(library.albums || 0).toLocaleString("de-DE")} Alben`,
    ];
    // Health-Status steht sonst im Balken-Label; ohne Score dort hier zeigen.
    if (health.status && health.score == null) parts.push(`Health: ${health.status}`);
    hintEl.innerHTML = _escapeHtml(parts.join(" · "))
      + (data.stale ? " " + ccStatusBadge("warn", "veraltet") : "");
  }
  _renderLibraryHealthBar(health, data.stale);
}

// ══════════════════════════════════════════════════════════════════
// Aufmerksamkeit: GET /api/v1/library/findings/summary
// ══════════════════════════════════════════════════════════════════
async function loadFindings() {
  const content = document.getElementById("attention-content");
  let summary;
  try {
    summary = await ccApi("GET", "/api/v1/library/findings/summary");
  } catch (err) {
    if (err.status === 401) return;
    // Vorher: stiller Rückfall, die Karte blieb dauerhaft auf "Lädt…".
    if (content) {
      content.classList.remove("placeholder-glow");
      ccState.error(content, "Findings nicht abrufbar.", loadFindings);
    }
    _setAttentionStatus("secondary");
    return;
  }
  _overviewState.findings = summary.open || 0;
  _renderAttention();
}

function _setAttentionStatus(color) {
  const bar = document.getElementById("attention-status");
  if (bar) bar.className = `card-status-start bg-${color}`;
}

function _renderAttention() {
  const panel = document.getElementById("attention-panel");
  const content = document.getElementById("attention-content");
  if (!panel || !content) return;

  const f = _overviewState.findings;
  const kind = _attentionKind(f);
  panel.hidden = false;
  content.classList.remove("placeholder-glow");
  _setAttentionStatus(_ATTENTION_COLOR[kind]);

  if (kind === "ok") {
    content.innerHTML = '<div class="d-flex align-items-center gap-3">'
      + `<span class="avatar bg-green-lt">${ccIcon("check")}</span>`
      + '<div><div class="fw-medium">Alles sauber</div>'
      + '<div class="text-secondary small">Keine offenen Findings</div></div></div>';
    return;
  }
  const noun = f === 1 ? "Finding erfordert" : "Findings erfordern";
  const color = _ATTENTION_COLOR[kind];
  content.innerHTML = '<div class="d-flex align-items-center gap-3">'
    + `<span class="avatar bg-${color}-lt text-${color} fw-bold">${_escapeHtml(String(f))}</span>`
    + `<div><div class="fw-medium">${noun} Aufmerksamkeit</div>`
    + '<div class="text-secondary small">Jetzt prüfen und priorisieren</div></div></div>';
}

// ══════════════════════════════════════════════════════════════════
// Zuletzt: GET /api/v1/downloads/history?limit=5
// ══════════════════════════════════════════════════════════════════
async function loadRecentActivity() {
  const el = document.getElementById("recent-activity-content");
  if (!el) return;
  let body;
  try {
    body = await ccApi("GET", "/api/v1/downloads/history?limit=5");
  } catch (err) {
    if (err.status === 401) return;
    el.classList.add("card-body");
    ccState.error(el, "Verlauf nicht abrufbar.", loadRecentActivity);
    return;
  }

  el.classList.remove("card-body");
  const entries = (body && body.entries) || [];
  if (!entries.length) {
    ccState.empty(el, "Noch keine Downloads", "Neue Downloads erscheinen hier.");
    return;
  }

  el.innerHTML = '<div class="table-responsive"><table class="table card-table table-vcenter mb-0"><tbody>'
    + entries.map((e) => {
      const ts = new Date(e.timestamp);
      const timeStr = isNaN(ts.getTime()) ? "" :
        ts.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) + " "
        + ts.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
      const label = _HISTORY_STATUS_LABEL[e.status] || e.status || "–";
      return "<tr>"
        + `<td class="w-1">${ccStatusBadge(ccStatusKind(e.status), label)}</td>`
        + `<td class="cc-cell-truncate"><div class="text-truncate">${_escapeHtml(e.title)}</div>`
        + `<div class="text-secondary small text-truncate">${_escapeHtml(e.artist)}</div></td>`
        + `<td class="text-secondary small text-nowrap text-end">${_escapeHtml(timeStr)}</td>`
        + "</tr>";
    }).join("")
    + "</tbody></table></div>";
}

// ══════════════════════════════════════════════════════════════════
// Navidrome-Status: GET /api/v1/navidrome/status
// ══════════════════════════════════════════════════════════════════
async function loadNavidromeStatus() {
  const valueEl = document.getElementById("status-navidrome-value");
  const hintEl = document.getElementById("status-navidrome-hint");

  let data;
  try {
    data = await ccApi("GET", "/api/v1/navidrome/status");
  } catch (err) {
    if (err.status === 401) return;
    if (valueEl) valueEl.innerHTML = ccStatusBadge("warn", "Unbekannt");
    if (hintEl) hintEl.textContent = "Status nicht abrufbar.";
    console.error("Navidrome-Status konnte nicht geladen werden:", err);
    return;
  }

  _overviewState.navidrome = data;
  if (data.connected) {
    if (valueEl) valueEl.innerHTML = ccStatusBadge("ok", "Online");
    if (hintEl) {
      hintEl.textContent = data.artist_count != null
        ? `${Number(data.artist_count).toLocaleString("de-DE")} Artists` : "Verbunden";
    }
  } else {
    if (valueEl) valueEl.innerHTML = ccStatusBadge("error", "Offline");
    if (hintEl) hintEl.textContent = "Nicht erreichbar";
  }
}

// ══════════════════════════════════════════════════════════════════
// Heute gehört: GET /api/v1/statistics/me/timeline (Nutzerwunsch
// 2026-09-29) - kleiner Block in der Library-Karte, bestehender Endpunkt.
// ══════════════════════════════════════════════════════════════════
function _formatListening(seconds) {
  const totalMinutes = Math.floor(Number(seconds || 0) / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

async function loadTodayListening() {
  const el = document.getElementById("status-today-content");
  if (!el) return;
  let t;
  try {
    t = await ccApi("GET", "/api/v1/statistics/me/timeline");
  } catch (err) {
    if (err.status === 401) return;
    el.classList.remove("placeholder-glow");
    // 404 = kein Navidrome-Benutzer hinterlegt - Hinweis statt Fehler.
    el.innerHTML = `<div class="text-secondary small">${_escapeHtml(err.status === 404
      ? "Kein Navidrome-Benutzer hinterlegt." : "Hörstatistik gerade nicht verfügbar.")}</div>`;
    return;
  }
  el.classList.remove("placeholder-glow");
  if (!t || !t.has_data || !t.track_count) {
    el.innerHTML = '<div class="text-secondary small">Heute noch nichts gehört.</div>';
    return;
  }
  const stat = (label, value) => `<div class="col-4"><div class="text-secondary small">${label}</div>`
    + `<div class="fw-semibold">${_escapeHtml(value)}</div></div>`;
  const top = (t.top_artist && t.top_artist.label)
    ? `<div class="text-secondary small mt-2 text-truncate">Top: <span class="text-reset fw-medium">${_escapeHtml(t.top_artist.label)}</span></div>`
    : "";
  el.innerHTML = '<div class="row g-2">'
    + stat("Plays", String(t.track_count))
    + stat("Hörzeit", _formatListening(t.listening_seconds))
    + stat("Neu", String(t.new_track_count ?? 0))
    + "</div>" + top
    + `<a href="${CC_BASE}/statistics" class="btn btn-link p-0 mt-2">Zur Statistik</a>`;
}

// ══════════════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════════════
function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadSystemMetrics();
    loadLibraryStatus();
    loadNavidromeStatus();
    loadFindings();
    loadRecentActivity();
    loadTodayListening();
  });
}
initPage();
