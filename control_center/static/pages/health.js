// control_center/static/pages/health.js
// JS für die konsolidierte Health-Seite (api_health.md) — vereint
// MusicBot Doctor (vormals health.html), Library Health Review (vormals
// findings.html), Repair MusicBot (vormals repairs.html) und die
// Job-Liste (vormals jobs.html) auf einer Seite. Reine Wiederverwendung
// bestehender Panel-Logik (unveraendert aus den vier Vorseiten
// uebernommen) plus drei neue Ergaenzungen: Score-History-Anzeige,
// Health-Scan als Job, Findings-Filter (Severity/Kategorie) und
// Repair-History/-Statistik. Layout A (Tabs): Kopf mit Score/Kennzahlen/
// Navidrome-Chip, darunter die Tabler-Tabs Findings | Repair | Verlauf.
// Es wurden nur Render-Funktionen umgestellt, die Job-/Polling-/API-Logik
// ist unveraendert. Nutzt die gemeinsamen Helfer aus
// common.js (apiUrl()/_loadInto()/_escapeHtml()/showOnly()/checkAuth()) —
// keine Duplikate.

// ── A) MusicBot Doctor ──────────────────────────────────────────────────

const _HEALTH_STATUS_COLOR = {
  EXCELLENT: "green", GOOD: "lime", FAIR: "yellow", POOR: "orange", CRITICAL: "red",
};

function _healthNumber(n) {
  return typeof n === "number" ? n.toLocaleString("de-DE") : _escapeHtml(String(n));
}

// Signatur (el, data) ist der _loadInto()-Vertrag (renderFn(el, body)). Bis zum
// Layout-A-Umbau hiess sie renderHealth(data): _loadInto uebergab das DOM-
// Element als `data`, die Kacheln zeigten immer "Keine Dateien in der Library
// gefunden." (Score "–") — auch bei gueltigem /health/cached-Report.
function renderHealth(el, data) {
  if (!data.library || !data.library.files) {
    el.innerHTML = '<div class="col-12"><p class="mb-0">Keine Dateien in der Library gefunden.</p></div>';
    return;
  }
  const hasScore = data.health.score != null;
  const score = hasScore ? data.health.score : "–";
  const status = data.health.status || "UNSCORED";
  const color = _HEALTH_STATUS_COLOR[status] || "secondary";
  const pct = hasScore ? Math.max(0, Math.min(100, Number(score))) : 0;
  el.innerHTML = `
    <div class="col-12 col-md-6">
      <div class="subheader">Health Score</div>
      <div class="d-flex align-items-baseline gap-2">
        <div class="h1 mb-0">${_escapeHtml(String(score))}</div>
        <span class="badge bg-${color}-lt">${_escapeHtml(status)}</span>
      </div>
      ${hasScore ? `<div class="progress progress-sm mt-2"><div class="progress-bar bg-${color}" style="width: ${pct}%" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div></div>` : ""}
    </div>
    <div class="col-4 col-md-2"><div class="subheader">Dateien</div><div class="h2 mb-0">${_healthNumber(data.library.files)}</div></div>
    <div class="col-4 col-md-2"><div class="subheader">Artists</div><div class="h2 mb-0">${_healthNumber(data.library.artists)}</div></div>
    <div class="col-4 col-md-2"><div class="subheader">Alben</div><div class="h2 mb-0">${_healthNumber(data.library.albums)}</div></div>
  `;
}
function loadHealth() {
  return _loadInto("health-tiles", "/api/v1/library/health/cached", renderHealth);
}

// Score-Verlauf als Sparkline (statt Textliste). Reihenfolge der API:
// aelteste zuerst. Gleichbleibende Scores werden als flache Linie gezeichnet.
function _sparklineSvg(entries) {
  const W = 240, H = 32, PAD = 4;
  const scored = entries.filter((e) => typeof e.score === "number");
  if (!scored.length) return "";
  const vals = scored.map((e) => e.score);
  const min = Math.min.apply(null, vals);
  const max = Math.max.apply(null, vals);
  const x = (i) => scored.length === 1 ? W / 2 : PAD + i * (W - 2 * PAD) / (scored.length - 1);
  const y = (v) => max === min ? H / 2 : PAD + (max - v) * (H - 2 * PAD) / (max - min);
  const pts = scored.map((e, i) => x(i).toFixed(1) + "," + y(e.score).toFixed(1)).join(" ");
  const last = scored[scored.length - 1];
  const dots = scored.map((e, i) => {
    const when = e.timestamp ? new Date(e.timestamp).toLocaleString() : "";
    return `<circle cx="${x(i).toFixed(1)}" cy="${y(e.score).toFixed(1)}" r="${e === last ? 3.5 : 2}" fill="currentColor"><title>${_escapeHtml(String(e.score))} · ${_escapeHtml(e.status || "UNSCORED")} · ${_escapeHtml(when)}</title></circle>`;
  }).join("");
  return `<svg class="text-primary" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="max-width:${W}px" role="img" aria-label="Score-Verlauf der letzten ${scored.length} Läufe">` +
    `<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>`;
}

function renderScoreHistory(el, body) {
  if (!body.entries.length) {
    el.innerHTML = '<span>Noch kein Score-Verlauf vorhanden — nach dem ersten Health-Scan sichtbar.</span>';
    return;
  }
  const last = body.entries[body.entries.length - 1];
  const facts = [];
  facts.push(`${body.entries.length} Lauf/Läufe`);
  if (last.timestamp) facts.push("zuletzt gescannt " + _escapeHtml(new Date(last.timestamp).toLocaleString()));
  if (last.total_issues != null) facts.push(_healthNumber(last.total_issues) + " offene Issues laut Scan");
  if (last.total_files != null) facts.push(_healthNumber(last.total_files) + " Dateien");
  el.innerHTML = `<div class="subheader mb-1">Score-Verlauf</div>${_sparklineSvg(body.entries)}<div class="mt-1">${facts.join(" · ")}</div>`;
}
function loadScoreHistory() {
  return _loadInto("score-history-content", "/api/v1/library/health/score-history?limit=20", renderScoreHistory);
}

let _healthScanJobPollTimer = null;
let _currentHealthScanJobId = null;

function _stopHealthScanJobPolling() {
  if (_healthScanJobPollTimer) { clearInterval(_healthScanJobPollTimer); _healthScanJobPollTimer = null; }
}

function _renderHealthScanJobStatus(job) {
  const el = document.getElementById("health-scan-job-content");
  const startBtn = document.getElementById("health-scan-btn");

  if (job.status === "PENDING" || job.status === "RUNNING") {
    startBtn.disabled = true;
    el.innerHTML = `<p class="empty-note">${_escapeHtml(job.status)} (${job.progress.toFixed(0)}%) — ${_escapeHtml(job.message || "")}</p>`;
    return;
  }

  startBtn.disabled = false;
  _stopHealthScanJobPolling();

  if (job.status === "SUCCEEDED") {
    el.innerHTML = `<p><span class="dot dot-ok"></span>Health-Scan abgeschlossen.</p>`;
    loadHealth();
    loadScoreHistory();
    loadFindings();
  } else if (job.status === "CANCELLED") {
    el.innerHTML = `<p class="empty-note">Abgebrochen.</p>`;
  } else {
    el.innerHTML = `<p><span class="dot dot-error"></span>Fehlgeschlagen: ${_escapeHtml(job.error || "Unbekannter Fehler")}</p>`;
  }
}

async function _pollHealthScanJob(jobId) {
  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); _stopHealthScanJobPolling(); return; }
    if (!res.ok) return;
    _renderHealthScanJobStatus(await res.json());
  } catch (err) {}
}

async function startHealthScanJob() {
  const startBtn = document.getElementById("health-scan-btn");
  startBtn.disabled = true;
  document.getElementById("health-scan-job-content").innerHTML = '<p class="empty-note">Wird gestartet…</p>';

  try {
    const res = await fetch(apiUrl("/api/v1/jobs/health-scan"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      startBtn.disabled = false;
      return;
    }
    const job = await res.json();
    _currentHealthScanJobId = job.job_id;
    _renderHealthScanJobStatus(job);
    _stopHealthScanJobPolling();
    _healthScanJobPollTimer = setInterval(() => _pollHealthScanJob(_currentHealthScanJobId), 1000);
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    startBtn.disabled = false;
  }
}
document.getElementById("health-scan-btn").addEventListener("click", startHealthScanJob);

function _setNavidromeChip(color, html) {
  const el = document.getElementById("navidrome-status");
  el.className = "badge bg-" + color + "-lt";
  el.innerHTML = html;
}
async function loadNavidromeStatus() {
  try {
    const res = await fetch(apiUrl("/api/v1/navidrome/status"), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) { _setNavidromeChip("secondary", "Navidrome: Status nicht abrufbar."); return; }
    const status = await res.json();
    const dot = status.connected ? "dot-ok" : "dot-error";
    const label = status.connected ? "Verbunden" : "Nicht erreichbar";
    const count = status.connected && status.artist_count != null
      ? ` (${status.artist_count} Artists)` : "";
    _setNavidromeChip(status.connected ? "green" : "red", `<span class="dot ${dot}"></span>Navidrome: ${label}${count}`);
  } catch (err) {
    _setNavidromeChip("secondary", "Navidrome: Netzwerkfehler.");
  }
}

// ── B) Library Health Review (Findings) ─────────────────────────────────

let _lastFindingGroups = [];

// Reihenfolge der Gruppen: schwerste Severity zuerst, dann groesste Gruppe.
const _FINDING_TIER_ORDER = ["CRITICAL", "ERROR", "WARNING", "SUSPECTED", "INFO"];
const _FINDING_TIER_COLOR = {
  CRITICAL: "red", ERROR: "orange", WARNING: "yellow", SUSPECTED: "purple", INFO: "secondary",
};
const _FINDING_PREVIEW_ROWS = 5;
// UI-Zustand ueber Re-Renders hinweg (Filter/Suche/Reload nach Aktion).
const _findingsOpenCodes = new Set();
const _findingsExpandedCodes = new Set();
let _findingsOpenInitialized = false;

function _findingLabel(f) {
  return f.path || [f.artist, f.album, f.title].filter(Boolean).join(" — ") || f.finding_id;
}

function _findingsSearchQuery() {
  const input = document.getElementById("findings-search");
  return input ? (input.value || "").trim().toLowerCase() : "";
}

function _findingMatchesQuery(f, q) {
  return [_findingLabel(f), f.artist, f.album, f.title].filter(Boolean).join(" ").toLowerCase().indexOf(q) !== -1;
}

function _applyFindingsFilter(groups) {
  const severity = document.getElementById("findings-severity-filter").value;
  const category = document.getElementById("findings-category-filter").value;
  const q = _findingsSearchQuery();
  return groups
    .filter((g) => !category || g.code === category)
    .map((g) => {
      let findings = severity ? g.findings.filter((f) => f.severity === severity) : g.findings;
      if (q && String(g.code).toLowerCase().indexOf(q) === -1) {
        findings = findings.filter((f) => _findingMatchesQuery(f, q));
      }
      return { ...g, findings };
    })
    .filter((g) => g.findings.length > 0);
}

function _sortFindingGroups(groups) {
  const rank = (g) => {
    const i = _FINDING_TIER_ORDER.indexOf(g.tier);
    return i === -1 ? _FINDING_TIER_ORDER.length : i;
  };
  return groups.slice().sort((a, b) =>
    rank(a) - rank(b) || b.findings.length - a.findings.length || String(a.code).localeCompare(String(b.code)));
}

function _populateCategoryFilterOptions(groups) {
  const select = document.getElementById("findings-category-filter");
  const previous = select.value;
  const codes = [...new Set(groups.map((g) => g.code))].sort();
  select.innerHTML = '<option value="">Kategorie: alle</option>' +
    codes.map((c) => `<option value="${_escapeHtml(c)}">${_escapeHtml(c)}</option>`).join("");
  if (codes.includes(previous)) select.value = previous;
}

// Aufgeklappte Detailzeilen (finding_id) ueber Re-Renders hinweg.
const _findingsOpenDetails = new Set();

// ── Finding-Analyse (GET /findings/{id}/details, read-only) ─────────────
// Belege werden beim Aufklappen frisch geladen (Tags von der Platte). Cache nur,
// solange die Zeile offen ist; Zuklappen verwirft ihn (naechstes Oeffnen = frisch).
const _findingExplainCache = new Map();
const _findingExplainErrors = new Map();
const _findingExplainPending = new Set();

function _diffLineHtml(segments, side) {
  const key = side === "a" ? "a" : "b";
  const cls = side === "a" ? "bg-red-lt" : "bg-green-lt";
  return segments.map((seg) => {
    const text = _escapeHtml(seg[key]);
    if (!text) return "";
    return seg.op === "equal" ? text : `<mark class="${cls} text-reset px-0">${text}</mark>`;
  }).join("");
}

function _renderFindingExplain(b) {
  if (!b.supported) {
    return '<span class="text-secondary">Für diesen Finding-Code gibt es keine Detailanalyse.</span>';
  }
  if (b.file_status !== "ok" || !b.evidence) {
    return `<span class="text-secondary">${_escapeHtml(b.message || "Analyse nicht möglich.")}</span>`;
  }
  const ev = b.evidence;
  const scanNote = ev.title_at_scan && ev.title_at_scan !== ev.title
    ? ` <span class="text-secondary">(beim Scan: ${_escapeHtml(ev.title_at_scan)})</span>` : "";
  const result = ev.matches
    ? '<span class="badge bg-green-lt">gleich</span> <span class="text-secondary">Datei wurde seit dem Scan angepasst — das Finding ist veraltet.</span>'
    : '<span class="badge bg-red-lt">unterschiedlich</span>';
  return `
    <div class="subheader mb-1">Analyse (frisch von der Platte gelesen)</div>
    <dl class="row gx-2 mb-1">
      ${_findingDetailRow("Dateiname", `<span class="font-monospace">${_escapeHtml(ev.stem)}</span>`)}
      ${ev.prefix ? _findingDetailRow("Abgetrennt", `<span class="font-monospace">„${_escapeHtml(ev.prefix)}“</span> <span class="text-secondary">(Nummer/Artist-Präfix)</span>`) : ""}
      ${_findingDetailRow("Titel-Tag", `<span class="font-monospace">${_escapeHtml(ev.title)}</span>${scanNote}`)}
      ${_findingDetailRow("Verglichen: Dateiname", `<span class="font-monospace">${_diffLineHtml(ev.segments, "a")}</span>`)}
      ${_findingDetailRow("Verglichen: Titel-Tag", `<span class="font-monospace">${_diffLineHtml(ev.segments, "b")}</span>`)}
      ${_findingDetailRow("Ergebnis", result)}
    </dl>
    <div class="text-secondary">„Verglichen“ = nach der Normalisierung des Scanners (Groß/Klein, Leerzeichen, ungültige Dateinamenzeichen, feat.-Klammern, Klammern ohne Zusatz wie Remix/Live).</div>`;
}

function _findingExplainInnerHtml(fid) {
  if (_findingExplainCache.has(fid)) return _renderFindingExplain(_findingExplainCache.get(fid));
  if (_findingExplainErrors.has(fid)) {
    return `<span class="text-danger">Analyse nicht verfügbar: ${_escapeHtml(_findingExplainErrors.get(fid))}</span>`;
  }
  return '<span class="text-secondary">Analyse lädt…</span>';
}

async function _loadFindingExplain(fid) {
  if (_findingExplainCache.has(fid) || _findingExplainPending.has(fid)) return;
  _findingExplainPending.add(fid);
  try {
    const res = await fetch(apiUrl(`/api/v1/library/findings/${encodeURIComponent(fid)}/details`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const detail = body && (body.error || body.detail);
      _findingExplainErrors.set(fid, (detail && detail.message) || ("HTTP " + res.status));
    } else {
      _findingExplainCache.set(fid, await res.json());
    }
  } catch (err) {
    _findingExplainErrors.set(fid, "Netzwerkfehler: " + err.message);
  } finally {
    _findingExplainPending.delete(fid);
  }
  // Nur noch anzeigen, wenn die Zeile inzwischen nicht wieder zugeklappt wurde.
  const target = document.getElementById("finding-explain-" + fid);
  if (target && _findingsOpenDetails.has(fid)) target.innerHTML = _findingExplainInnerHtml(fid);
}

function _findingDetailRow(label, valueHtml) {
  return `<dt class="col-4 col-md-3">${_escapeHtml(label)}</dt><dd class="col-8 col-md-9 mb-1 text-break">${valueHtml}</dd>`;
}

// Nur Felder, die die Findings-API tatsaechlich liefert (FindingSchema) —
// keine abgeleiteten/erfundenen Vergleichswerte.
function _findingDetailHtml(f) {
  const rows = [];
  if (f.path) rows.push(_findingDetailRow("Pfad", `<span class="font-monospace">${_escapeHtml(f.path)}</span>`));
  if (f.artist) rows.push(_findingDetailRow("Artist", _escapeHtml(f.artist)));
  if (f.album) rows.push(_findingDetailRow("Album", _escapeHtml(f.album)));
  if (f.title) rows.push(_findingDetailRow("Titel", _escapeHtml(f.title)));
  const sev = [f.severity, f.confidence].filter(Boolean).join(" · ");
  if (sev) rows.push(_findingDetailRow("Severity", _escapeHtml(sev)));
  if (f.occurrences != null) rows.push(_findingDetailRow("Auftreten", _escapeHtml(String(f.occurrences))));
  if (f.first_seen) rows.push(_findingDetailRow("Erstmals gesehen", _escapeHtml(f.first_seen)));
  if (f.last_seen) rows.push(_findingDetailRow("Zuletzt gesehen", _escapeHtml(f.last_seen)));
  return `
      <div class="health-finding-detail small mt-1 mb-2">
        <div class="text-break mb-2">${f.message ? _escapeHtml(f.message) : '<span class="text-secondary">Keine Meldung gespeichert.</span>'}</div>
        <dl class="row gx-2 mb-2 text-secondary">${rows.join("")}</dl>
        <div class="mb-2" id="finding-explain-${_escapeHtml(f.finding_id)}">${_findingExplainInnerHtml(f.finding_id)}</div>
        <button type="button" class="btn btn-sm btn-outline-secondary finding-copy-btn" data-finding-id="${_escapeHtml(f.finding_id)}">Kopieren</button>
      </div>`;
}

function _findingRowHtml(f) {
  const id = _escapeHtml(f.finding_id);
  const open = _findingsOpenDetails.has(f.finding_id);
  return `
    <div class="list-group-item py-1 health-finding-row" data-finding-id="${id}">
      <div class="d-flex align-items-center gap-2">
        <button type="button" class="finding-toggle health-path font-monospace small text-truncate" data-finding-id="${id}" aria-expanded="${open}" title="Details ${open ? "ausblenden" : "anzeigen"}">${_escapeHtml(_findingLabel(f))}</button>
        <div class="dropdown">
          <button type="button" class="btn btn-sm btn-ghost-secondary" data-bs-toggle="dropdown" aria-expanded="false" aria-label="Aktionen für dieses Finding">⋮</button>
          <div class="dropdown-menu dropdown-menu-end">
            <button type="button" class="dropdown-item resolve-btn" data-finding-id="${id}">Als repariert markieren</button>
            <button type="button" class="dropdown-item accept-btn" data-finding-id="${id}">Akzeptieren …</button>
          </div>
        </div>
      </div>${open ? _findingDetailHtml(f) : ""}
    </div>`;
}

// Text fuer "Kopieren": Code, Meldung, Pfad — genau das, was im Detail steht.
function _findingCopyText(finding, code) {
  return [code, finding.message, finding.path].filter(Boolean).join("\n");
}

async function _copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    // Fallback (kein Secure Context / Berechtigung verweigert).
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (err2) {
      return false;
    }
  }
}

function _findFindingById(findingId) {
  for (const g of _lastFindingGroups) {
    for (const f of g.findings) {
      if (f.finding_id === findingId) return { finding: f, code: g.code };
    }
  }
  return null;
}

async function _copyFinding(btn) {
  const hit = _findFindingById(btn.dataset.findingId);
  if (!hit) return;
  const ok = await _copyToClipboard(_findingCopyText(hit.finding, hit.code));
  btn.textContent = ok ? "Kopiert ✓" : "Kopieren nicht möglich";
  setTimeout(() => { btn.textContent = "Kopieren"; }, 1500);
}

function _findingGroupHtml(g, searching) {
  const code = _escapeHtml(g.code);
  const open = searching || _findingsOpenCodes.has(g.code);
  const expanded = _findingsExpandedCodes.has(g.code);
  const shown = expanded ? g.findings : g.findings.slice(0, _FINDING_PREVIEW_ROWS);
  const rest = g.findings.length - shown.length;
  let more = "";
  if (rest > 0) {
    more = `<button type="button" class="list-group-item list-group-item-action text-secondary health-more-btn" data-code="${code}">${rest} weitere anzeigen</button>`;
  } else if (expanded && g.findings.length > _FINDING_PREVIEW_ROWS) {
    more = `<button type="button" class="list-group-item list-group-item-action text-secondary health-more-btn" data-code="${code}">Weniger anzeigen</button>`;
  }
  const color = _FINDING_TIER_COLOR[g.tier] || "secondary";
  return `
    <details class="card health-group" data-code="${code}"${open ? " open" : ""}>
      <summary class="card-header d-flex align-items-center gap-2">
        <span class="badge bg-${color}-lt">${_escapeHtml(g.tier)}</span>
        <span class="font-monospace fw-semibold flex-fill text-truncate">${code}</span>
        <span class="text-secondary">${g.findings.length}</span>
      </summary>
      <div class="list-group list-group-flush">${shown.map(_findingRowHtml).join("")}${more}</div>
    </details>`;
}

function renderFindings(el, groups) {
  _lastFindingGroups = groups;
  _populateCategoryFilterOptions(groups);
  const countEl = document.getElementById("health-findings-count");
  if (countEl) {
    const total = groups.reduce((n, g) => n + g.findings.length, 0);
    countEl.textContent = total ? total.toLocaleString("de-DE") : "";
  }
  const filtered = _sortFindingGroups(_applyFindingsFilter(groups));
  if (!filtered.length) { el.innerHTML = '<p class="mb-0">Keine offenen Findings (für die aktuelle Filterauswahl).</p>'; return; }
  if (!_findingsOpenInitialized) {
    _findingsOpenInitialized = true;
    _findingsOpenCodes.add(filtered[0].code);
  }
  const searching = _findingsSearchQuery() !== "";
  el.innerHTML = '<div class="d-flex flex-column gap-2">' +
    filtered.map((g) => _findingGroupHtml(g, searching)).join("") + "</div>";
}
function loadFindings() {
  return _loadInto("findings-content", "/api/v1/library/findings", renderFindings);
}
function _rerenderFindings() {
  renderFindings(document.getElementById("findings-content"), _lastFindingGroups);
}
document.getElementById("findings-severity-filter").addEventListener("change", _rerenderFindings);
document.getElementById("findings-category-filter").addEventListener("change", _rerenderFindings);
document.getElementById("findings-search").addEventListener("input", _rerenderFindings);

async function acceptFinding(findingId, buttonEl) {
  const reason = window.prompt("Grund für die Akzeptanz (Pflichtfeld):", "");
  if (reason === null) return;
  if (!reason.trim()) { window.alert("Ein Grund ist erforderlich."); return; }
  if (!window.confirm(`Finding wirklich als akzeptiert markieren?\n\n${reason}`)) return;

  buttonEl.disabled = true;
  try {
    const res = await fetch(apiUrl(`/api/v1/library/findings/${encodeURIComponent(findingId)}/accept`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ reason }),
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      buttonEl.disabled = false;
      return;
    }
    await loadFindings();
    if (!document.getElementById("accepted-findings-content").hidden) {
      await loadAcceptedFindings();
    }
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    buttonEl.disabled = false;
  }
}

async function resolveFinding(findingId, buttonEl) {
  const note = window.prompt("Notiz zur Behebung (optional):", "");
  if (note === null) return;
  if (!window.confirm("Finding wirklich als repariert markieren?")) return;

  buttonEl.disabled = true;
  try {
    const res = await fetch(apiUrl(`/api/v1/library/findings/${encodeURIComponent(findingId)}/review`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ status: "RESOLVED", note: note || null }),
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      buttonEl.disabled = false;
      return;
    }
    await loadFindings();
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    buttonEl.disabled = false;
  }
}

document.getElementById("findings-content").addEventListener("click", (event) => {
  const moreBtn = event.target.closest(".health-more-btn");
  if (moreBtn) {
    const code = moreBtn.dataset.code;
    if (_findingsExpandedCodes.has(code)) _findingsExpandedCodes.delete(code); else _findingsExpandedCodes.add(code);
    _rerenderFindings();
    return;
  }
  const toggleBtn = event.target.closest(".finding-toggle");
  if (toggleBtn) {
    const fid = toggleBtn.dataset.findingId;
    if (_findingsOpenDetails.has(fid)) {
      _findingsOpenDetails.delete(fid);
      _findingExplainCache.delete(fid);  // naechstes Oeffnen liest wieder frisch
      _findingExplainErrors.delete(fid);
      _rerenderFindings();
    } else {
      _findingsOpenDetails.add(fid);
      _findingExplainErrors.delete(fid);
      _rerenderFindings();
      _loadFindingExplain(fid);
    }
    return;
  }
  const copyBtn = event.target.closest(".finding-copy-btn");
  if (copyBtn) { _copyFinding(copyBtn); return; }
  const acceptBtn = event.target.closest(".accept-btn");
  if (acceptBtn) { acceptFinding(acceptBtn.dataset.findingId, acceptBtn); return; }
  const resolveBtn = event.target.closest(".resolve-btn");
  if (resolveBtn) { resolveFinding(resolveBtn.dataset.findingId, resolveBtn); return; }
});
// Auf-/Zuklappen merken (toggle bubbelt nicht -> Capture). Waehrend einer
// Suche sind alle Gruppen automatisch offen: das ist kein Nutzer-Wunsch.
document.getElementById("findings-content").addEventListener("toggle", (event) => {
  const d = event.target;
  if (!d || !d.classList || !d.classList.contains("health-group") || _findingsSearchQuery() !== "") return;
  if (d.open) _findingsOpenCodes.add(d.dataset.code); else _findingsOpenCodes.delete(d.dataset.code);
}, true);

function renderAcceptedFindings(el, body) {
  if (!body.findings.length) {
    el.innerHTML = '<p class="mb-0">Keine akzeptierten Findings.</p>';
    return;
  }
  const truncNote = body.total > body.findings.length
    ? `<p class="small mb-2">Zeige ${body.findings.length} von ${body.total} — ältere/weitere nicht geladen (kein Auto-Rendern großer Listen).</p>`
    : "";
  el.innerHTML = truncNote + '<div class="list-group list-group-flush border rounded">' + body.findings.map((f) => `
    <div class="list-group-item d-flex align-items-center gap-2" data-finding-id="${_escapeHtml(f.finding_id)}">
      <div class="health-path" title="${_escapeHtml(f.message)}">
        <span class="badge bg-secondary-lt me-1">${_escapeHtml(f.code)}</span>
        <span class="font-monospace small">${_escapeHtml(_findingLabel(f))}</span>
        ${f.present_in_latest_scan === false ? '<span class="text-secondary small">(veraltet — nicht mehr erkannt)</span>' : ""}
        <div class="text-secondary small">${_escapeHtml(f.review_note || "")}</div>
      </div>
      <button type="button" class="btn btn-sm btn-outline-secondary unaccept-btn" data-finding-id="${_escapeHtml(f.finding_id)}">Reaktivieren</button>
    </div>
  `).join("") + "</div>";
}
function loadAcceptedFindings() {
  return _loadInto(
    "accepted-findings-content", "/api/v1/library/findings/accepted", renderAcceptedFindings
  );
}

async function unacceptFinding(findingId, buttonEl) {
  if (!window.confirm("Diese Akzeptanz wirklich zurücknehmen? Das Finding wird wieder als offen geführt.")) return;

  buttonEl.disabled = true;
  try {
    const res = await fetch(apiUrl(`/api/v1/library/findings/${encodeURIComponent(findingId)}/unaccept`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({}),
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      buttonEl.disabled = false;
      return;
    }
    await loadAcceptedFindings();
    await loadFindings();
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    buttonEl.disabled = false;
  }
}

document.getElementById("accepted-findings-content").addEventListener("click", (event) => {
  const btn = event.target.closest(".unaccept-btn");
  if (!btn) return;
  unacceptFinding(btn.dataset.findingId, btn);
});

document.getElementById("accepted-findings-toggle").addEventListener("click", async () => {
  const content = document.getElementById("accepted-findings-content");
  const toggleBtn = document.getElementById("accepted-findings-toggle");
  const willShow = content.hidden;
  content.hidden = !willShow;
  toggleBtn.textContent = willShow ? "Akzeptierte Findings verbergen" : "Akzeptierte Findings anzeigen";
  if (willShow) {
    content.textContent = "Lädt…";
    await loadAcceptedFindings();
  }
});

// ── C) Repair MusicBot ───────────────────────────────────────────────────

let _lastSafeAutomaticCount = null;

// Schrittanzeige (reine Orientierung, kein Zustandsautomat): 1 Plan, 2 SAFE_AUTOMATIC,
// 3 L2/L3. Markiert den zuletzt begonnenen Schritt.
function _setRepairStep(n) {
  const list = document.getElementById("repair-steps");
  if (!list) return;
  Array.prototype.forEach.call(list.children, (li, i) => {
    li.classList.toggle("active", i === n - 1);
  });
}

function renderRepairPlan(el, plan) {
  const counts = Object.entries(plan.counts_by_level)
    .map(([lvl, n]) => `<div class="col-6 col-sm-4"><div class="subheader">${_escapeHtml(lvl)}</div><div class="h3 mb-0">${n}</div></div>`).join("");
  el.innerHTML = `
    <div class="row g-3 mb-3">${counts || '<div class="col-12">keine Kandidaten</div>'}</div>
    <p class="small mb-0">${plan.actionable_total} automatisch reparierbar (alle Level zusammen), davon ${plan.counts_by_level.SAFE_AUTOMATIC || 0} SAFE_AUTOMATIC (per Button unten ausführbar) — der Rest (Cover/L2/L3 usw.) erfordert bewusste manuelle Auswahl. ${plan.manual_review_total} zur manuellen Prüfung (Health Score ${plan.health_score ?? "–"}). Reine Vorschau — es wird nichts ausgeführt.</p>
  `;
  _lastSafeAutomaticCount = plan.counts_by_level.SAFE_AUTOMATIC || 0;
  const startBtn = document.getElementById("repair-start-btn");
  startBtn.disabled = false;
  startBtn.textContent = `SAFE_AUTOMATIC reparieren (${_lastSafeAutomaticCount})`;
  const hint = document.getElementById("repair-start-hint");
  if (hint) hint.hidden = true;
  _setRepairStep(2);
}
function loadRepairPlan() {
  document.getElementById("repair-plan-content").innerHTML =
    '<span class="empty-note">Scan läuft, kann eine Weile dauern…</span>';
  return _loadInto("repair-plan-content", "/api/v1/library/repair-plan", renderRepairPlan);
}

let _repairJobPollTimer = null;
let _currentRepairJobId = null;

function _stopRepairJobPolling() {
  if (_repairJobPollTimer) { clearInterval(_repairJobPollTimer); _repairJobPollTimer = null; }
}

function _renderRepairJobStatus(job) {
  const el = document.getElementById("repair-job-content");
  const cancelBtn = document.getElementById("repair-cancel-btn");
  const startBtn = document.getElementById("repair-start-btn");

  if (job.status === "PENDING" || job.status === "RUNNING") {
    cancelBtn.hidden = false;
    startBtn.disabled = true;
    el.innerHTML = `<p class="empty-note">${_escapeHtml(job.status)} (${job.progress.toFixed(0)}%) — ${_escapeHtml(job.message || "")}</p>`;
    return;
  }

  cancelBtn.hidden = true;
  startBtn.disabled = false;
  _stopRepairJobPolling();

  if (job.status === "SUCCEEDED") {
    const tail = (job.result && job.result.stdout_tail) || "";
    el.innerHTML = `<p><span class="dot dot-ok"></span>Reparatur abgeschlossen.</p>` +
      (tail ? `<pre style="white-space:pre-wrap;font-size:0.75rem;">${_escapeHtml(tail.slice(-1200))}</pre>` : "");
    loadRepairHistory();
    loadRepairStatistics();
    loadJobs();
  } else if (job.status === "CANCELLED") {
    el.innerHTML = `<p class="empty-note">Abgebrochen.</p>`;
  } else {
    const tail = (job.result && job.result.stdout_tail) || (job.result && job.result.stderr_tail) || "";
    el.innerHTML = `<p><span class="dot dot-error"></span>Fehlgeschlagen: ${_escapeHtml(job.error || "Unbekannter Fehler")}</p>` +
      (tail ? `<pre style="white-space:pre-wrap;font-size:0.75rem;">${_escapeHtml(tail.slice(-1200))}</pre>` : "");
  }
}

async function _pollRepairJob(jobId) {
  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); _stopRepairJobPolling(); return; }
    if (!res.ok) return;
    _renderRepairJobStatus(await res.json());
  } catch (err) {}
}

async function startRepairJob() {
  const count = _lastSafeAutomaticCount ?? "unbekannt viele";
  const confirmed = window.confirm(
    `SAFE_AUTOMATIC-Reparatur wirklich starten?\n\n` +
    `Betrifft ${count} Kandidat(en) aus der zuletzt geladenen Vorschau. ` +
    `Verlustfrei/deterministisch, mit Backup + Rollback abgesichert — ` +
    `aber es werden tatsächlich Dateien in der Library verändert.`
  );
  if (!confirmed) return;

  const startBtn = document.getElementById("repair-start-btn");
  startBtn.disabled = true;
  document.getElementById("repair-job-content").innerHTML = '<p class="empty-note">Wird gestartet…</p>';

  try {
    const res = await fetch(apiUrl("/api/v1/jobs/repair-safe-automatic"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      startBtn.disabled = false;
      return;
    }
    const job = await res.json();
    _currentRepairJobId = job.job_id;
    _renderRepairJobStatus(job);
    _stopRepairJobPolling();
    _repairJobPollTimer = setInterval(() => _pollRepairJob(_currentRepairJobId), 1000);
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    startBtn.disabled = false;
  }
}

async function cancelRepairJob() {
  if (!_currentRepairJobId) return;
  const cancelBtn = document.getElementById("repair-cancel-btn");
  cancelBtn.disabled = true;
  try {
    await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(_currentRepairJobId)}/cancel`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    });
  } catch (err) {
    window.alert("Netzwerkfehler beim Abbrechen: " + err.message);
  } finally {
    cancelBtn.disabled = false;
  }
}

document.getElementById("repair-start-btn").addEventListener("click", startRepairJob);
document.getElementById("repair-cancel-btn").addEventListener("click", cancelRepairJob);
document.getElementById("repair-plan-btn").addEventListener("click", loadRepairPlan);

// ── L2/L3-Reparatur (Pro-Artist) ─────────────────────────────────────────
const _LEVEL23_LABELS = {
  l2: "L2 (Neuverarbeitung — volle Metadaten-Pipeline erneut)",
  l3: "L3 (MusicBrainz — Netzwerk, kann pro Datei fehlschlagen)",
};

let _level23JobPollTimer = null;
let _level23JobId = null;

function _stopLevel23JobPolling() {
  if (_level23JobPollTimer) { clearInterval(_level23JobPollTimer); _level23JobPollTimer = null; }
}

function _setLevel23ButtonsDisabled(disabled) {
  document.querySelectorAll(".level23-btn").forEach((btn) => { btn.disabled = disabled; });
}

// Findings #4/#6: gleiche Semantik wie Telegram (_result_headline()) -
// "geändert" nur aus changed_files, nie aus affected_files.
function _repairOutcomeText(r) {
  if (r.failed) return (r.success || r.unresolved) ? "teilweise abgeschlossen" : "fehlgeschlagen";
  if (r.status === "UNRESOLVED" || r.unresolved) return "abgeschlossen – Überprüfung nötig";
  if (r.success) return "abgeschlossen";
  if (r.skipped) return "nichts zu tun";
  return "leerer Lauf";
}
function _repairCountsText(r) {
  const exitNote = (r.exit_code != null && r.exit_code !== 0)
    ? ` Repair-Subprozess meldete Exit-Code ${_escapeHtml(String(r.exit_code))} (Verification-Regression oder Abbruch) – Ergebnis bitte prüfen.`
    : "";
  return `${r.success} erfolgreich, ${r.skipped} übersprungen, ` +
    (r.unresolved ? `${r.unresolved} zu überprüfen, ` : "") +
    `${r.failed} fehlgeschlagen, ${r.resolved_count} Finding(s) verifiziert behoben, ` +
    `${(r.changed_files || []).length} Datei(en) geändert.` + exitNote;
}

function _renderLevel23JobStatus(job) {
  const el = document.getElementById("level23-job-content");

  if (job.status === "PENDING" || job.status === "RUNNING") {
    el.innerHTML = `<p class="empty-note">${_escapeHtml(job.status)} (${job.progress.toFixed(0)}%) — ${_escapeHtml(job.message || "")}</p>`;
    return;
  }

  _stopLevel23JobPolling();
  _setLevel23ButtonsDisabled(false);
  const r = job.result || {};

  if (job.status === "SUCCEEDED") {
    if (r.total === 0) {
      el.innerHTML = `<p><span class="dot dot-ok"></span>${_escapeHtml(r.artist || "")}: keine offenen ${_escapeHtml(_LEVEL23_LABELS[r.level] || "")}-Befunde (mehr) vorhanden.</p>`;
    } else {
      el.innerHTML = `<p><span class="dot ${r.status === "SUCCESS" ? "dot-ok" : "dot-warn"}"></span>${_escapeHtml(r.artist || "")} — ${_escapeHtml(r.level || "")} ${_escapeHtml(_repairOutcomeText(r))}: ` +
        _repairCountsText(r) + "</p>";
    }
    loadRepairHistory();
    loadRepairStatistics();
    loadJobs();
  } else {
    el.innerHTML = `<p><span class="dot dot-error"></span>Fehlgeschlagen: ${_escapeHtml(job.error || "Unbekannter Fehler")}</p>`;
  }
}

async function _pollLevel23Job(jobId) {
  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); _stopLevel23JobPolling(); return; }
    if (!res.ok) return;
    _renderLevel23JobStatus(await res.json());
  } catch (err) {}
}

async function startLevel23Job(level, artist, count) {
  const confirmed = window.confirm(
    `${_LEVEL23_LABELS[level]} wirklich starten für "${artist}"?\n\n` +
    `Betrifft ${count} Kandidat(en) aus der zuletzt geladenen Vorschau. ` +
    `Mit Backup abgesichert — aber es werden tatsächlich Dateien in der Library verändert.` +
    (level === "l3" ? "\n\nL3 ruft MusicBrainz auf — einzelne Dateien können bei Netzwerk-/Rate-Limit-Fehlern fehlschlagen." : "")
  );
  if (!confirmed) return;

  _setLevel23ButtonsDisabled(true);
  document.getElementById("level23-job-content").innerHTML = '<p class="empty-note">Wird gestartet…</p>';

  try {
    const res = await fetch(apiUrl(`/api/v1/jobs/repair-level${level === "l2" ? "2" : "3"}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ artist }),
    });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert("Fehler: " + (body && body.error ? body.error.message : res.status));
      _setLevel23ButtonsDisabled(false);
      return;
    }
    const job = await res.json();
    _level23JobId = job.job_id;
    _renderLevel23JobStatus(job);
    _stopLevel23JobPolling();
    _level23JobPollTimer = setInterval(() => _pollLevel23Job(_level23JobId), 1000);
  } catch (err) {
    window.alert("Netzwerkfehler: " + err.message);
    _setLevel23ButtonsDisabled(false);
  }
}

function renderLevel23Artists(el, plan) {
  if (!plan.artists.length) {
    el.innerHTML = '<p class="mb-0">Keine L2/L3-Kandidaten.</p>';
    return;
  }
  _setRepairStep(3);
  el.innerHTML = '<div class="list-group list-group-flush border rounded">' + plan.artists.map((a) => `
    <div class="list-group-item d-flex align-items-center gap-2">
      <span class="health-path text-truncate">${_escapeHtml(a.artist)}</span>
      <div class="btn-list flex-nowrap">
        ${a.l2_count > 0 ? `<button type="button" class="btn btn-sm btn-outline-primary level23-btn" data-level="l2" data-artist="${_escapeHtml(a.artist)}" data-count="${a.l2_count}">L2 (${a.l2_count})</button>` : ""}
        ${a.l3_count > 0 ? `<button type="button" class="btn btn-sm btn-outline-primary level23-btn" data-level="l3" data-artist="${_escapeHtml(a.artist)}" data-count="${a.l3_count}">L3 (${a.l3_count})</button>` : ""}
      </div>
    </div>
  `).join("") + "</div>";
}
function loadLevel23Artists() {
  document.getElementById("level23-artists-content").innerHTML =
    '<span class="empty-note">Scan läuft, kann eine Weile dauern…</span>';
  return _loadInto("level23-artists-content", "/api/v1/library/repair-plan/by-artist", renderLevel23Artists);
}

document.getElementById("level23-artists-content").addEventListener("click", (event) => {
  const btn = event.target.closest(".level23-btn");
  if (!btn) return;
  startLevel23Job(btn.dataset.level, btn.dataset.artist, btn.dataset.count);
});
document.getElementById("level23-plan-btn").addEventListener("click", loadLevel23Artists);

// ── Repair-History / Repair-Statistik / Jobs ─────────────────────────────

function _statCard(label, value) {
  return `<div class="col-6 col-md-3"><div class="card card-sm"><div class="card-body"><div class="subheader">${_escapeHtml(label)}</div><div class="h2 mb-0">${_escapeHtml(String(value))}</div></div></div></div>`;
}
function renderRepairStatistics(el, stats) {
  if (!stats.total_runs) { el.innerHTML = '<p class="mb-0">Noch keine Reparaturläufe vorhanden.</p>'; return; }
  const topCodes = stats.most_common_issue_codes.slice(0, 5)
    .map(([code, n]) => `<span class="badge bg-secondary-lt">${_escapeHtml(code)} <strong>${_escapeHtml(String(n))}</strong></span>`).join("");
  el.innerHTML = `
    <div class="row g-3">
      ${_statCard("Läufe", stats.total_runs)}
      ${_statCard("Erfolgreich", stats.success)}
      ${_statCard("Fehlgeschlagen", stats.failed)}
      ${_statCard("Übersprungen", stats.skipped)}
    </div>
    ${topCodes ? `<div class="small mt-3 mb-1">Häufigste Issue-Codes</div><div class="d-flex flex-wrap gap-2">${topCodes}</div>` : ""}
  `;
}
function loadRepairStatistics() {
  return _loadInto("repair-statistics-content", "/api/v1/library/repairs/statistics", renderRepairStatistics);
}

const _HISTORY_PREVIEW_ROWS = 5;
let _lastRepairHistory = null;
let _repairHistoryExpanded = false;

function _repairStatusColor(status) {
  return status === "SUCCESS" ? "green" : (status === "FAILED" ? "red" : "yellow");
}

function renderRepairHistory(el, body) {
  _lastRepairHistory = body;
  if (!body.runs.length) { el.innerHTML = '<p class="mb-0">Noch keine Reparaturläufe vorhanden.</p>'; return; }
  const truncNote = body.total > body.runs.length
    ? `<p class="small mb-2">Zeige ${body.runs.length} von ${body.total} — ältere nicht geladen.</p>`
    : "";
  const shown = _repairHistoryExpanded ? body.runs : body.runs.slice(0, _HISTORY_PREVIEW_ROWS);
  const rest = body.runs.length - shown.length;
  const toggle = rest > 0
    ? `<button type="button" class="list-group-item list-group-item-action text-secondary history-more-btn">${rest} weitere anzeigen</button>`
    : (_repairHistoryExpanded && body.runs.length > _HISTORY_PREVIEW_ROWS
      ? '<button type="button" class="list-group-item list-group-item-action text-secondary history-more-btn">Weniger anzeigen</button>' : "");
  el.innerHTML = truncNote + '<div class="list-group list-group-flush border rounded">' + shown.map((r) => `
    <div class="list-group-item d-flex align-items-start gap-2">
      <span class="badge bg-${_repairStatusColor(r.status)}-lt">${_escapeHtml(r.status)}</span>
      <div class="health-path">
        <div>${_escapeHtml(r.level)}${r.artist ? " · " + _escapeHtml(r.artist) : ""}</div>
        <div class="text-secondary small">${_escapeHtml(r.kind)} · ${_escapeHtml(r.triggered_by)}</div>
      </div>
      <div class="text-secondary small text-nowrap">${_escapeHtml(new Date(r.started_at).toLocaleString())}</div>
    </div>
  `).join("") + toggle + "</div>";
}
function loadRepairHistory() {
  return _loadInto("repair-history-content", "/api/v1/library/repairs/history?limit=20", renderRepairHistory);
}
document.getElementById("repair-history-content").addEventListener("click", (event) => {
  if (!event.target.closest(".history-more-btn") || !_lastRepairHistory) return;
  _repairHistoryExpanded = !_repairHistoryExpanded;
  renderRepairHistory(document.getElementById("repair-history-content"), _lastRepairHistory);
});

const _JOB_STATUS_COLOR = {
  SUCCEEDED: "green", FAILED: "red", CANCELLED: "red",
};

function renderJobs(el, body) {
  if (!body.jobs.length) { el.innerHTML = '<p class="mb-0">Keine Jobs.</p>'; return; }
  el.innerHTML = '<div class="list-group list-group-flush border rounded">' + body.jobs.map((j) => {
    const color = _JOB_STATUS_COLOR[j.status];
    const statusHtml = color
      ? `<span class="badge bg-${color}-lt">${_escapeHtml(j.status)}</span>`
      : `<span class="badge bg-blue-lt">${_escapeHtml(j.status)} (${j.progress.toFixed(0)}%)</span>`;
    const errorHtml = j.error ? `<div class="text-danger small">${_escapeHtml(j.error)}</div>` : "";
    return `
      <div class="list-group-item d-flex align-items-start gap-2">
        ${statusHtml}
        <div class="health-path">
          <div>${_escapeHtml(j.kind)}</div>
          <div class="text-secondary small">Initiator: ${_escapeHtml(j.initiator)} · ${_escapeHtml(j.job_id)}</div>
          ${errorHtml}
        </div>
        <div class="text-secondary small text-nowrap">${_escapeHtml(new Date(j.created_at).toLocaleString())}</div>
      </div>
    `;
  }).join("") + "</div>";
}
function loadJobs() {
  return _loadInto("jobs-content", "/api/v1/jobs?limit=20", renderJobs);
}
document.getElementById("jobs-refresh-btn").addEventListener("click", loadJobs);

// ── Init ──────────────────────────────────────────────────────────────

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadHealth();
    loadScoreHistory();
    loadFindings();
    loadRepairStatistics();
    loadRepairHistory();
    loadJobs();
    loadNavidromeStatus();
  });
}
initPage();
