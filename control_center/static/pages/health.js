// control_center/static/pages/health.js
// JS für die konsolidierte Health-Seite (api_health.md) — vereint
// MusicBot Doctor (vormals health.html), Library Health Review (vormals
// findings.html), Repair MusicBot (vormals repairs.html) und die
// Job-Liste (vormals jobs.html) auf einer Seite. Reine Wiederverwendung
// bestehender Panel-Logik (unveraendert aus den vier Vorseiten
// uebernommen) plus drei neue Ergaenzungen: Score-History-Anzeige,
// Health-Scan als Job, Findings-Filter (Severity/Kategorie) und
// Repair-History/-Statistik. Nutzt die gemeinsamen Helfer aus
// common.js (apiUrl()/_loadInto()/_escapeHtml()/showOnly()/checkAuth()) —
// keine Duplikate.

// ── A) MusicBot Doctor ──────────────────────────────────────────────────

function renderHealth(data) {
  const el = document.getElementById("health-tiles");
  const badge = document.getElementById("health-score-badge");
  if (!data.library || !data.library.files) {
    el.innerHTML = "<p>Keine Dateien in der Library gefunden.</p>";
    badge.textContent = "–";
    return;
  }
  const score = data.health.score != null ? data.health.score : "–";
  const status = data.health.status || "UNSCORED";
  el.innerHTML = `
    <div class="tile"><div class="tile-label">Health Score</div>
      <div class="tile-value status-${_escapeHtml(status)}">${_escapeHtml(String(score))}</div>
      <div class="hint">${_escapeHtml(status)}</div></div>
    <div class="tile"><div class="tile-label">Dateien</div>
      <div class="tile-value">${data.library.files}</div></div>
    <div class="tile"><div class="tile-label">Artists</div>
      <div class="tile-value">${data.library.artists}</div></div>
    <div class="tile"><div class="tile-label">Alben</div>
      <div class="tile-value">${data.library.albums}</div></div>
  `;
  badge.textContent = `${score} · ${status}`;
}
function loadHealth() {
  return _loadInto("health-tiles", "/api/v1/library/health/cached", renderHealth);
}

function renderScoreHistory(el, body) {
  if (!body.entries.length) {
    el.innerHTML = '<p class="empty-note">Noch kein Score-Verlauf vorhanden — nach dem ersten Health-Scan sichtbar.</p>';
    return;
  }
  const recent = body.entries.slice(-10).reverse();
  el.innerHTML = '<div class="row-list">' + recent.map((e) => `
    <div class="row-item">
      <div class="row-main">${e.score != null ? _escapeHtml(String(e.score)) : "–"} · ${_escapeHtml(e.status || "UNSCORED")}
        <div class="hint">${e.total_issues != null ? e.total_issues + " offene Issues, " : ""}${e.total_files != null ? e.total_files + " Dateien" : ""}</div>
      </div>
      <div class="row-count">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ""}</div>
    </div>
  `).join("") + "</div>";
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

async function loadNavidromeStatus() {
  const el = document.getElementById("navidrome-status");
  try {
    const res = await fetch(apiUrl("/api/v1/navidrome/status"), { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (!res.ok) { el.textContent = "Navidrome: Status nicht abrufbar."; return; }
    const status = await res.json();
    const dot = status.connected ? "dot-ok" : "dot-error";
    const label = status.connected ? "Verbunden" : "Nicht erreichbar";
    const count = status.connected && status.artist_count != null
      ? ` (${status.artist_count} Artists)` : "";
    el.innerHTML = `<span class="dot ${dot}"></span>Navidrome: ${label}${count}`;
  } catch (err) {
    el.textContent = "Navidrome: Netzwerkfehler.";
  }
}

// ── B) Library Health Review (Findings) ─────────────────────────────────

let _lastFindingGroups = [];

function _findingLabel(f) {
  return f.path || [f.artist, f.album, f.title].filter(Boolean).join(" — ") || f.finding_id;
}

function _applyFindingsFilter(groups) {
  const severity = document.getElementById("findings-severity-filter").value;
  const category = document.getElementById("findings-category-filter").value;
  return groups
    .filter((g) => !category || g.code === category)
    .map((g) => ({
      ...g,
      findings: severity ? g.findings.filter((f) => f.severity === severity) : g.findings,
    }))
    .filter((g) => g.findings.length > 0);
}

function _populateCategoryFilterOptions(groups) {
  const select = document.getElementById("findings-category-filter");
  const previous = select.value;
  const codes = [...new Set(groups.map((g) => g.code))].sort();
  select.innerHTML = '<option value="">— alle —</option>' +
    codes.map((c) => `<option value="${_escapeHtml(c)}">${_escapeHtml(c)}</option>`).join("");
  if (codes.includes(previous)) select.value = previous;
}

function renderFindings(el, groups) {
  _lastFindingGroups = groups;
  _populateCategoryFilterOptions(groups);
  const filtered = _applyFindingsFilter(groups);
  if (!filtered.length) { el.innerHTML = '<p class="empty-note">Keine offenen Findings (für die aktuelle Filterauswahl).</p>'; return; }
  el.innerHTML = filtered.map((g) => `
    <div class="finding-group">
      <div class="row-item">
        <div class="row-main"><span class="badge badge-${_escapeHtml(g.tier)}">${_escapeHtml(g.tier)}</span>${_escapeHtml(g.code)}</div>
        <div class="row-count">${g.findings.length}</div>
      </div>
      <div class="row-list finding-sublist">
        ${g.findings.map((f) => `
          <div class="row-item" data-finding-id="${_escapeHtml(f.finding_id)}">
            <div class="row-main" title="${_escapeHtml(f.message)}">${_escapeHtml(_findingLabel(f))}</div>
            <div class="d-flex gap-2">
              <button class="small resolve-btn" data-finding-id="${_escapeHtml(f.finding_id)}">Repariert</button>
              <button class="small accept-btn" data-finding-id="${_escapeHtml(f.finding_id)}">Akzeptieren</button>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `).join("");
}
function loadFindings() {
  return _loadInto("findings-content", "/api/v1/library/findings", renderFindings);
}
document.getElementById("findings-severity-filter").addEventListener("change", () => {
  renderFindings(document.getElementById("findings-content"), _lastFindingGroups);
});
document.getElementById("findings-category-filter").addEventListener("change", () => {
  renderFindings(document.getElementById("findings-content"), _lastFindingGroups);
});

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
  const acceptBtn = event.target.closest(".accept-btn");
  if (acceptBtn) { acceptFinding(acceptBtn.dataset.findingId, acceptBtn); return; }
  const resolveBtn = event.target.closest(".resolve-btn");
  if (resolveBtn) { resolveFinding(resolveBtn.dataset.findingId, resolveBtn); return; }
});

function renderAcceptedFindings(el, body) {
  if (!body.findings.length) {
    el.innerHTML = '<p class="empty-note">Keine akzeptierten Findings.</p>';
    return;
  }
  const truncNote = body.total > body.findings.length
    ? `<p class="empty-note">Zeige ${body.findings.length} von ${body.total} — ältere/weitere nicht geladen (kein Auto-Rendern großer Listen).</p>`
    : "";
  el.innerHTML = truncNote + '<div class="row-list">' + body.findings.map((f) => `
    <div class="row-item" data-finding-id="${_escapeHtml(f.finding_id)}">
      <div class="row-main" title="${_escapeHtml(f.message)}">
        <span class="badge badge-INFO">${_escapeHtml(f.code)}</span>
        ${_escapeHtml(_findingLabel(f))}
        ${f.present_in_latest_scan === false ? '<span class="denied">(veraltet — nicht mehr erkannt)</span>' : ""}
        <div class="hint">${_escapeHtml(f.review_note || "")}</div>
      </div>
      <button class="small unaccept-btn" data-finding-id="${_escapeHtml(f.finding_id)}">Reaktivieren</button>
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

function renderRepairPlan(el, plan) {
  const counts = Object.entries(plan.counts_by_level)
    .map(([lvl, n]) => `<div><strong>${n}</strong><br>${lvl}</div>`).join("");
  el.innerHTML = `
    <div class="counts-grid">${counts || "<div>keine Kandidaten</div>"}</div>
    <p class="empty-note">${plan.actionable_total} automatisch reparierbar (alle Level zusammen), davon ${plan.counts_by_level.SAFE_AUTOMATIC || 0} SAFE_AUTOMATIC (per Button unten ausführbar) — der Rest (Cover/L2/L3 usw.) erfordert bewusste manuelle Auswahl. ${plan.manual_review_total} zur manuellen Prüfung (Health Score ${plan.health_score ?? "–"}). Reine Vorschau — es wird nichts ausgeführt.</p>
  `;
  _lastSafeAutomaticCount = plan.counts_by_level.SAFE_AUTOMATIC || 0;
  const startBtn = document.getElementById("repair-start-btn");
  startBtn.disabled = false;
  startBtn.textContent = `SAFE_AUTOMATIC reparieren (${_lastSafeAutomaticCount})`;
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
    if (r.status === "SKIPPED" || r.total === 0) {
      el.innerHTML = `<p><span class="dot dot-ok"></span>${_escapeHtml(r.artist || "")}: keine offenen ${_escapeHtml(_LEVEL23_LABELS[r.level] || "")}-Befunde (mehr) vorhanden.</p>`;
    } else {
      el.innerHTML = `<p><span class="dot dot-ok"></span>${_escapeHtml(r.artist || "")} — ${_escapeHtml(r.level || "")} abgeschlossen: ` +
        `${r.success} erfolgreich, ${r.skipped} übersprungen, ${r.failed} fehlgeschlagen, ` +
        `${r.resolved_count} Finding(s) verifiziert behoben, ${(r.affected_files || []).length} Datei(en) geändert.</p>`;
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
    el.innerHTML = '<p class="empty-note">Keine L2/L3-Kandidaten.</p>';
    return;
  }
  el.innerHTML = '<div class="row-list">' + plan.artists.map((a) => `
    <div class="row-item">
      <div class="row-main">${_escapeHtml(a.artist)}</div>
      <div class="row-count">
        ${a.l2_count > 0 ? `<button class="small level23-btn" data-level="l2" data-artist="${_escapeHtml(a.artist)}" data-count="${a.l2_count}">L2 (${a.l2_count})</button>` : ""}
        ${a.l3_count > 0 ? `<button class="small level23-btn" data-level="l3" data-artist="${_escapeHtml(a.artist)}" data-count="${a.l3_count}">L3 (${a.l3_count})</button>` : ""}
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

function renderRepairStatistics(el, stats) {
  if (!stats.total_runs) { el.innerHTML = '<p class="empty-note">Noch keine Reparaturläufe vorhanden.</p>'; return; }
  const topCodes = stats.most_common_issue_codes.slice(0, 5)
    .map(([code, n]) => `<div><strong>${n}</strong><br>${_escapeHtml(code)}</div>`).join("");
  el.innerHTML = `
    <div class="counts-grid">
      <div><strong>${stats.total_runs}</strong><br>Läufe</div>
      <div><strong>${stats.success}</strong><br>Erfolgreich</div>
      <div><strong>${stats.failed}</strong><br>Fehlgeschlagen</div>
      <div><strong>${stats.skipped}</strong><br>Übersprungen</div>
    </div>
    ${topCodes ? `<p class="hint mt-2">Häufigste Issue-Codes:</p><div class="counts-grid">${topCodes}</div>` : ""}
  `;
}
function loadRepairStatistics() {
  return _loadInto("repair-statistics-content", "/api/v1/library/repairs/statistics", renderRepairStatistics);
}

function renderRepairHistory(el, body) {
  if (!body.runs.length) { el.innerHTML = '<p class="empty-note">Noch keine Reparaturläufe vorhanden.</p>'; return; }
  const truncNote = body.total > body.runs.length
    ? `<p class="empty-note">Zeige ${body.runs.length} von ${body.total} — ältere nicht geladen.</p>`
    : "";
  el.innerHTML = truncNote + '<div class="row-list">' + body.runs.map((r) => `
    <div class="row-item">
      <div class="row-main">
        <span class="badge badge-${r.status === "SUCCESS" ? "status-success" : "status-failed"}">${_escapeHtml(r.status)}</span>
        ${_escapeHtml(r.level)}${r.artist ? " · " + _escapeHtml(r.artist) : ""}
        <div class="hint">${_escapeHtml(r.kind)} · ${_escapeHtml(r.triggered_by)}</div>
      </div>
      <div class="row-count">${new Date(r.started_at).toLocaleString()}</div>
    </div>
  `).join("") + "</div>";
}
function loadRepairHistory() {
  return _loadInto("repair-history-content", "/api/v1/library/repairs/history?limit=20", renderRepairHistory);
}

const _JOB_STATUS_BADGE = {
  SUCCEEDED: "status-success", FAILED: "status-failed", CANCELLED: "status-cancelled",
};

function renderJobs(el, body) {
  if (!body.jobs.length) { el.innerHTML = '<p class="empty-note">Keine Jobs.</p>'; return; }
  el.innerHTML = '<div class="row-list">' + body.jobs.map((j) => {
    const badgeClass = _JOB_STATUS_BADGE[j.status];
    const statusHtml = badgeClass
      ? `<span class="badge badge-${badgeClass}">${_escapeHtml(j.status)}</span>`
      : `${_escapeHtml(j.status)} (${j.progress.toFixed(0)}%)`;
    const errorHtml = j.error ? `<div class="hint">${_escapeHtml(j.error)}</div>` : "";
    return `
      <div class="row-item">
        <div class="row-main">
          ${statusHtml} ${_escapeHtml(j.kind)}
          <div class="hint">Initiator: ${_escapeHtml(j.initiator)} · ${_escapeHtml(j.job_id)}</div>
          ${errorHtml}
        </div>
        <div class="row-count">${new Date(j.created_at).toLocaleString()}</div>
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
