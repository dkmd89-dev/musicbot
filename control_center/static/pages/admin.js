// control_center/static/pages/admin.js
// Administration-Seite nach docs/CONTROL_CENTER_UI_STANDARD.md (CC-UI
// Administration): System-Status, Bot, Wartungsmodus, Backups, Duplikat-
// Cache, Fehlerstatistik (read-only), Nutzer/Rollen. Nutzt die gemeinsamen
// Helfer aus common.js und ausschließlich die Admin-APIs unter /api/v1/admin.

// ── System-Status ────────────────────────────────────────────────────────

function renderSystemStatus(el, data) {
  const cpuEl = document.getElementById("admin-system-cpu");
  const memoryEl = document.getElementById("admin-system-memory");
  const diskEl = document.getElementById("admin-system-disk");
  const botEl = document.getElementById("admin-system-bot");
  const errorEl = document.getElementById("admin-system-status-error");

  if (errorEl) { errorEl.hidden = true; errorEl.textContent = ""; }
  if (cpuEl) cpuEl.textContent = `${Number(data.cpu_percent).toFixed(1)} %`;
  if (memoryEl) {
    memoryEl.textContent = `${Number(data.memory_percent).toFixed(1)} % · `
      + `${Number(data.memory_used_mb).toFixed(0)} / ${Number(data.memory_total_mb).toFixed(0)} MB`;
  }
  if (diskEl) {
    diskEl.textContent = `${Number(data.disk_percent).toFixed(1)} % · `
      + `${Number(data.disk_used_gb).toFixed(1)} / ${Number(data.disk_total_gb).toFixed(1)} GB`;
  }
  if (botEl) {
    // Vorher: textContent = _escapeHtml(...) -> doppelt escaped ("&amp;").
    const active = data.bot_service_active;
    const kind = active === true ? "ok" : active === false ? "error" : "warn";
    const label = active === true ? "Aktiv" : active === false ? "Inaktiv" : "Unbekannt";
    botEl.innerHTML = ccStatusBadge(kind, label)
      + (data.bot_service_name ? `<div class="text-secondary small text-truncate mt-1">${_escapeHtml(data.bot_service_name)}</div>` : "");
  }
}

async function loadSystemStatus() {
  const errorEl = document.getElementById("admin-system-status-error");
  try {
    renderSystemStatus(null, await ccApi("GET", "/api/v1/admin/system/status"));
  } catch (err) {
    if (err.status === 401) return;
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = `Systemstatus konnte nicht geladen werden: ${err.message}`;
    }
  }
}

// ── Bot ──────────────────────────────────────────────────────────────────

async function loadBotOperationStatus() {
  const statusEl = document.getElementById("admin-bot-operation-status");
  if (!statusEl) return;
  try {
    const data = await ccApi("GET", "/api/v1/admin/system/status");
    if (data.bot_service_active === true) statusEl.innerHTML = ccStatusBadge("ok", "Bot-Service aktiv");
    else if (data.bot_service_active === false) statusEl.innerHTML = ccStatusBadge("error", "Bot-Service inaktiv");
    else statusEl.innerHTML = ccStatusBadge("warn", "Status unbekannt");
  } catch (err) {
    if (err.status === 401) return;
    ccState.error(statusEl, `Status konnte nicht geladen werden: ${err.message}`, loadBotOperationStatus);
  }
}

async function restartBot() {
  const statusEl = document.getElementById("admin-bot-operation-status");
  const buttonEl = document.getElementById("admin-bot-restart-btn");
  if (!buttonEl) return;
  const confirmed = await ccConfirm({
    title: "Bot neu starten?",
    text: "Der Bot ist während des Neustarts kurz nicht erreichbar.",
    confirmLabel: "Neu starten",
    danger: true,
  });
  if (!confirmed) return;

  buttonEl.disabled = true;
  if (statusEl) statusEl.textContent = "Bot-Neustart wird angefordert …";
  try {
    const data = await ccApi("POST", "/api/v1/admin/system/restart");
    const msg = (data && data.message) || "Neustart wird in Kürze ausgeführt.";
    if (statusEl) statusEl.innerHTML = ccStatusBadge("running", "Neustart angefordert")
      + `<div class="text-secondary small mt-1">${_escapeHtml(msg)}</div>`;
    ccToast("ok", "Bot-Neustart angefordert", msg);
    buttonEl.disabled = true;
  } catch (err) {
    if (err.status === 401) return;
    if (statusEl) ccState.error(statusEl, err.message);
    ccToast("error", "Neustart fehlgeschlagen", err.message);
    buttonEl.disabled = false;
  }
}

// ── Wartungsmodus ────────────────────────────────────────────────────────

let _maintenanceActive = null;

async function loadMaintenanceStatus() {
  const statusEl = document.getElementById("admin-maintenance-status");
  const labelEl = document.getElementById("admin-maintenance-label");
  const buttonEl = document.getElementById("admin-maintenance-toggle-btn");
  try {
    const data = await ccApi("GET", "/api/v1/admin/maintenance");
    const active = data.active === true;
    _maintenanceActive = active;
    if (statusEl) statusEl.innerHTML = ccStatusBadge(active ? "warn" : "ok", active ? "Aktiv" : "Inaktiv");
    if (labelEl) labelEl.textContent = active ? "Wartungsmodus ist aktiv" : "Wartungsmodus ist deaktiviert";
    if (buttonEl) {
      buttonEl.textContent = active ? "Wartungsmodus deaktivieren" : "Wartungsmodus aktivieren";
      buttonEl.className = active ? "btn btn-outline-success" : "btn btn-outline-warning";
    }
  } catch (err) {
    if (err.status === 401) return;
    if (labelEl) labelEl.textContent = "Wartungsstatus konnte nicht geladen werden.";
    ccToast("error", "Wartungsstatus nicht abrufbar", err.message);
  }
}

async function toggleMaintenance() {
  const buttonEl = document.getElementById("admin-maintenance-toggle-btn");
  if (!buttonEl) return;
  // Zustand aus dem letzten Laden; Rückfall wie bisher über den Button-Text.
  const currentlyActive = _maintenanceActive !== null
    ? _maintenanceActive : buttonEl.textContent.includes("deaktivieren");

  if (!currentlyActive) {
    // Nutzerentscheidung 2026-09-28: nur das Aktivieren wird bestätigt.
    const confirmed = await ccConfirm({
      title: "Wartungsmodus aktivieren?",
      text: "Im Telegram-Bot werden dann alle Nutzer außer Admins und Owner blockiert.",
      confirmLabel: "Aktivieren",
      danger: true,
    });
    if (!confirmed) return;
  }

  buttonEl.disabled = true;
  try {
    await ccApi("POST", "/api/v1/admin/maintenance", { active: !currentlyActive });
    ccToast("ok", currentlyActive ? "Wartungsmodus deaktiviert" : "Wartungsmodus aktiviert");
    await loadMaintenanceStatus();
  } catch (err) {
    if (err.status !== 401) ccToast("error", "Wartungsmodus nicht geändert", err.message);
  } finally {
    buttonEl.disabled = false;
  }
}

// ── Backups ──────────────────────────────────────────────────────────────

function _formatBackupSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value)) return "–";
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function renderBackupList(el, data) {
  const backups = Array.isArray(data.backups) ? data.backups : [];
  if (!backups.length) {
    ccState.empty(el, "Keine Backups vorhanden", "Erstelle oben ein neues Backup.");
    return;
  }
  el.innerHTML = '<div class="table-responsive"><table class="table card-table table-vcenter mb-0">'
    + '<thead><tr><th>Backup</th><th>Größe</th><th class="d-none d-md-table-cell">Erstellt</th><th class="w-1"></th></tr></thead><tbody>'
    + backups.map((backup) => "<tr>"
      + `<td class="cc-cell-truncate"><div class="text-truncate font-monospace small">${_escapeHtml(backup.name)}</div></td>`
      + `<td class="text-secondary text-nowrap">${_escapeHtml(_formatBackupSize(backup.size))}</td>`
      + `<td class="text-secondary text-nowrap d-none d-md-table-cell">${_escapeHtml(backup.created_at ? new Date(backup.created_at).toLocaleString() : "–")}</td>`
      + '<td><button type="button" class="btn btn-sm btn-icon btn-ghost-danger admin-backup-delete"'
      + ` data-backup-name="${_escapeHtml(backup.name)}" title="Backup löschen" aria-label="Backup löschen">${ccIcon("trash")}</button></td>`
      + "</tr>").join("")
    + "</tbody></table></div>";
}

function loadBackups(backupType = "bot") {
  return _loadInto(
    "admin-backup-status",
    `/api/v1/admin/backups?backup_type=${encodeURIComponent(backupType)}`,
    renderBackupList,
    () => loadBackups(backupType),
  );
}

function _backupProgressHtml(text, pct) {
  const width = Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : 0;
  return '<div class="card-body">'
    + `<div class="d-flex justify-content-between small text-secondary mb-1"><span>${_escapeHtml(text)}</span><span>${width ? width.toFixed(0) + " %" : ""}</span></div>`
    + `<div class="progress progress-sm"><div class="progress-bar ${width ? "bg-teal" : "progress-bar-indeterminate"}" style="width: ${width}%"></div></div></div>`;
}

async function deleteBackup(backupName, backupType) {
  if (!backupName) return;
  const confirmed = await ccConfirm({
    title: "Backup löschen?",
    text: `„${backupName}“ wird endgültig gelöscht.`,
    confirmLabel: "Löschen",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await ccApi("DELETE", `/api/v1/admin/backups/${encodeURIComponent(backupName)}`);
    ccToast("ok", "Backup gelöscht", backupName);
    await loadBackups(backupType);
  } catch (err) {
    if (err.status !== 401) ccToast("error", "Backup nicht gelöscht", err.message);
  }
}

async function createBackup(backupType = "bot") {
  const btn = document.getElementById("admin-backup-create-btn");
  const statusEl = document.getElementById("admin-backup-status");
  if (!btn || !statusEl) return;

  btn.disabled = true;
  statusEl.innerHTML = _backupProgressHtml("Backup wird erstellt …", NaN);
  try {
    const body = await ccApi("POST", "/api/v1/admin/backups", { backup_type: backupType });
    if (!body || !body.job_id) throw new Error("Kein Job für das Backup erhalten.");
    statusEl.innerHTML = _backupProgressHtml("Backup-Job gestartet …", NaN);
    await pollBackupJob(body.job_id, backupType);
  } catch (err) {
    if (err.status === 401) return;
    statusEl.innerHTML = '<div class="card-body"></div>';
    ccState.error(statusEl.firstElementChild || statusEl, err.message, () => loadBackups(backupType));
    ccToast("error", "Backup fehlgeschlagen", err.message);
  } finally {
    btn.disabled = false;
  }
}

async function pollBackupJob(jobId, backupType) {
  const statusEl = document.getElementById("admin-backup-status");
  if (!statusEl) return;
  const maxAttempts = 60;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const job = await ccApi("GET", `/api/v1/jobs/${encodeURIComponent(jobId)}`);

    // Regression 2026-09-28: die API liefert JobStatus.value in Großbuchstaben
    // (services/jobs/models.py). Der frühere Vergleich mit "succeeded"/
    // "failed"/"cancelled" griff nie -> jedes Backup endete mit Zeitüberschreitung.
    if (job.status === "SUCCEEDED") {
      ccToast("ok", "Backup erstellt", backupType === "library" ? "Library-Backup" : "Bot-Backup");
      await loadBackups(backupType);
      return;
    }
    if (job.status === "FAILED") throw new Error(job.error || "Backup fehlgeschlagen.");
    if (job.status === "CANCELLED") throw new Error("Backup wurde abgebrochen.");

    const progress = Number(job.progress);
    statusEl.innerHTML = _backupProgressHtml("Backup läuft …", progress);
  }
  throw new Error("Zeitüberschreitung beim Warten auf das Backup.");
}

// ── Duplikat-Cache (Web-Paritäts-Backlog 4b) ─────────────────────────────
// Reiner Client um /api/v1/admin/duplicates/*, Fachlogik in services/duplicate/admin.py.

function _formatDuplicateDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : d.toLocaleDateString("de-DE");
}

async function loadDuplicateCacheStats() {
  const el = document.getElementById("admin-duplicates-stats");
  if (!el) return;
  try {
    const data = await ccApi("GET", "/api/v1/admin/duplicates/stats");
    el.innerHTML = '<div class="datagrid">'
      + `<div class="datagrid-item"><div class="datagrid-title">URL-Einträge</div><div class="datagrid-content">${_escapeHtml(String(data.url_entries))}</div></div>`
      + `<div class="datagrid-item"><div class="datagrid-title">Content-Einträge</div><div class="datagrid-content">${_escapeHtml(String(data.content_entries))}</div></div>`
      + `<div class="datagrid-item"><div class="datagrid-title">Zeitraum</div><div class="datagrid-content">${data.oldest_entry || data.newest_entry ? `${_escapeHtml(_formatDuplicateDate(data.oldest_entry))} – ${_escapeHtml(_formatDuplicateDate(data.newest_entry))}` : "–"}</div></div>`
      + "</div>";
  } catch (err) {
    if (err.status === 401) return;
    ccState.error(el, err.message, loadDuplicateCacheStats);
  }
}

async function clearDuplicateCache() {
  const buttonEl = document.getElementById("admin-duplicates-clear-btn");
  const messageEl = document.getElementById("admin-duplicates-message");
  if (!buttonEl) return;
  const confirmed = await ccConfirm({
    title: "Duplikat-Cache leeren?",
    text: "Gesamter Cache (URLs und Content). Das kann nicht rückgängig gemacht werden.",
    confirmLabel: "Leeren",
    danger: true,
  });
  if (!confirmed) return;

  buttonEl.disabled = true;
  if (messageEl) messageEl.textContent = "Cache wird geleert …";
  try {
    const data = await ccApi("POST", "/api/v1/admin/duplicates/clear", { confirm: true });
    const text = `${data.url_entries_removed} URL- / ${data.content_entries_removed} Content-Einträge entfernt.`;
    if (messageEl) messageEl.textContent = text;
    ccToast("ok", "Duplikat-Cache geleert", text);
    await loadDuplicateCacheStats();
  } catch (err) {
    if (messageEl) messageEl.textContent = "";
    if (err.status !== 401) ccToast("error", "Cache nicht geleert", err.message);
  } finally {
    buttonEl.disabled = false;
  }
}

// ── Bot-Runtime-Snapshot (E1) ────────────────────────────────────────────
// Read-only Fehlerstatistik + Duplikat-Sitzungszähler aus
// /api/v1/admin/runtime-snapshot. Kein Reset im Web.

function _formatAge(seconds) {
  if (seconds == null) return "";
  const s = Math.round(seconds);
  if (s < 60) return `vor ${s} s`;
  if (s < 3600) return `vor ${Math.round(s / 60)} min`;
  return `vor ${Math.round(s / 3600)} h`;
}

function _topEntriesHtml(map, limit = 5) {
  const entries = Object.entries(map || {}).sort((a, b) => b[1] - a[1]).slice(0, limit);
  if (!entries.length) return '<span class="text-secondary">–</span>';
  return entries
    .map(([k, v]) => `<span class="badge bg-secondary-lt me-1 mb-1">${_escapeHtml(k)}: ${_escapeHtml(String(v))}</span>`)
    .join("");
}

function renderRuntimeErrors(el, body) {
  const errors = body.errors;
  if (!errors) {
    ccState.empty(el, "Keine Fehlerdaten im Snapshot");
    return;
  }
  const recent = (errors.recent || []).slice(0, 10).map((e) => `
    <tr>
      <td class="text-nowrap small text-secondary">${_escapeHtml((e.timestamp || "").replace("T", " ").slice(0, 19))}</td>
      <td>${ccStatusBadge(ccStatusKind(e.severity), e.severity || "–")}</td>
      <td class="d-none d-md-table-cell">${_escapeHtml(e.type || "")}</td>
      <td class="d-none d-md-table-cell">${_escapeHtml(e.module || "–")}</td>
      <td class="small">${_escapeHtml(e.message || "")}</td>
    </tr>`).join("");
  el.innerHTML = `
    <div class="datagrid mb-3">
      <div class="datagrid-item"><div class="datagrid-title">Fehler gesamt</div><div class="datagrid-content h3 mb-0">${_escapeHtml(String(errors.total_exceptions))}</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Ø Bearbeitungszeit</div><div class="datagrid-content h3 mb-0">${_escapeHtml(errors.avg_processing_time.toFixed(3))} s</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Recovery-Quote</div><div class="datagrid-content h3 mb-0">${_escapeHtml((errors.recovery_success_rate * 100).toFixed(1))} %</div></div>
    </div>
    <div class="mb-1"><span class="text-secondary small me-2">Kategorien</span>${_topEntriesHtml(errors.by_category)}</div>
    <div class="mb-1"><span class="text-secondary small me-2">Module</span>${_topEntriesHtml(errors.by_module)}</div>
    <div class="mb-3"><span class="text-secondary small me-2">Schwere</span>${_topEntriesHtml(errors.by_severity)}</div>
    ${recent ? `<div class="table-responsive"><table class="table table-sm table-vcenter mb-0">
      <thead><tr><th>Zeit</th><th>Schwere</th><th class="d-none d-md-table-cell">Typ</th><th class="d-none d-md-table-cell">Modul</th><th>Meldung</th></tr></thead>
      <tbody>${recent}</tbody></table></div>` : '<div class="text-secondary small">Keine Fehler seit Bot-Start.</div>'}`;
}

function renderDuplicateSession(el, body) {
  const d = body.duplicates;
  if (!d) {
    el.textContent = "Keine Sitzungszähler im Bot-Snapshot.";
    return;
  }
  el.innerHTML = '<div class="datagrid">'
    + `<div class="datagrid-item"><div class="datagrid-title">Prüfungen</div><div class="datagrid-content">${_escapeHtml(String(d.total_checks))}</div></div>`
    + `<div class="datagrid-item"><div class="datagrid-title">Übersprungen</div><div class="datagrid-content">${_escapeHtml(String(d.duplicates_skipped))}</div></div>`
    + `<div class="datagrid-item"><div class="datagrid-title">URL / Content</div><div class="datagrid-content">${_escapeHtml(String(d.url_duplicates_found))} / ${_escapeHtml(String(d.content_duplicates_found))}</div></div>`
    + `<div class="datagrid-item"><div class="datagrid-title">Duplikat-Rate</div><div class="datagrid-content">${_escapeHtml(d.duplicate_rate.toFixed(1))} %</div></div>`
    + "</div>";
}

async function loadRuntimeSnapshot() {
  const errorsEl = document.getElementById("admin-errors-content");
  const dupEl = document.getElementById("admin-duplicates-session");
  const freshEl = document.getElementById("admin-runtime-freshness");
  let body;
  try {
    body = await ccApi("GET", "/api/v1/admin/runtime-snapshot");
  } catch (err) {
    if (err.status === 401) return;
    if (errorsEl) ccState.error(errorsEl, err.message, loadRuntimeSnapshot);
    return;
  }
  if (body.status === "missing" || body.status === "corrupt") {
    const msg = body.message || "Kein Bot-Snapshot verfügbar.";
    if (errorsEl) ccState.empty(errorsEl, "Kein Bot-Snapshot", msg);
    if (dupEl) dupEl.textContent = msg;
    if (freshEl) freshEl.innerHTML = ccStatusBadge("neutral", body.status === "corrupt" ? "Snapshot beschädigt" : "kein Snapshot");
    return;
  }
  if (freshEl) {
    const stale = body.status === "stale";
    freshEl.innerHTML = ccStatusBadge(stale ? "warn" : "ok", `Stand: ${_formatAge(body.age_seconds)}${stale ? " – veraltet" : ""}`)
      + (stale ? '<div class="text-warning small mt-1">Bot schreibt keinen Snapshot mehr</div>' : "");
  }
  if (errorsEl) renderRuntimeErrors(errorsEl, body);
  if (dupEl) renderDuplicateSession(dupEl, body);
}

// ── Nutzer & Rollen ──────────────────────────────────────────────────────

// Farben wie bisher (owner rot, admin orange, moderator gelb, user grau).
const _ROLE_BADGE = { owner: "red", admin: "orange", moderator: "yellow", user: "secondary" };

function renderAdminUsers(el, body) {
  if (!body.users.length) { ccState.empty(el, "Keine registrierten Nutzer"); return; }
  el.innerHTML = '<div class="table-responsive"><table class="table card-table table-vcenter mb-0">'
    + '<thead><tr><th>Rolle</th><th>Nutzer</th><th class="d-none d-md-table-cell">Navidrome</th><th class="d-none d-md-table-cell">Angelegt</th><th class="w-1"></th></tr></thead><tbody>'
    + body.users.map((u) => {
      const color = _ROLE_BADGE[u.role] || "secondary";
      const kind = u.telegram_id < 0
        ? '<span class="badge bg-azure-lt ms-1">Web</span>'
        : '<span class="badge bg-secondary-lt ms-1">Telegram</span>';
      return "<tr>"
        + `<td><span class="badge bg-${color}-lt">${_escapeHtml(u.role)}</span></td>`
        + `<td class="text-nowrap">#${_escapeHtml(String(u.telegram_id))}${kind}</td>`
        + `<td class="d-none d-md-table-cell">${u.navidrome_user ? _escapeHtml(u.navidrome_user) : '<span class="text-secondary">–</span>'}</td>`
        + `<td class="text-secondary d-none d-md-table-cell">${_escapeHtml(u.created_at ? new Date(u.created_at).toLocaleDateString() : "–")}</td>`
        + `<td>${u.navidrome_user ? `<button type="button" class="btn btn-sm view-stats-btn" data-navidrome-user="${_escapeHtml(u.navidrome_user)}">${ccIcon("chart", "me-1")}Statistik</button>` : ""}</td>`
        + "</tr>";
    }).join("")
    + "</tbody></table></div>";
}

function loadAdminUsers() {
  return _loadInto("admin-users-content", "/api/v1/admin/users", renderAdminUsers, loadAdminUsers);
}

// Backlog 9: Web-Benutzer ohne Telegram anlegen (Freischaltung Navidrome-Login)
async function createWebUser(event) {
  event.preventDefault();
  const nameEl = document.getElementById("admin-web-user-name");
  const roleEl = document.getElementById("admin-web-user-role");
  const msgEl = document.getElementById("admin-web-user-message");
  const btn = document.getElementById("admin-web-user-btn");
  if (!nameEl || !roleEl) return;
  if (btn) btn.disabled = true;
  try {
    const data = await ccApi("POST", "/api/v1/admin/web-users", { navidrome_user: nameEl.value, role: roleEl.value });
    const text = `#${data.telegram_id} (${data.navidrome_user || ""})`;
    if (msgEl) msgEl.innerHTML = `<span class="text-success">Web-Benutzer ${_escapeHtml(text)} angelegt.</span>`;
    ccToast("ok", "Web-Benutzer angelegt", text);
    nameEl.value = "";
    loadAdminUsers();
  } catch (err) {
    if (err.status === 401) return;
    if (msgEl) msgEl.innerHTML = `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
    ccToast("error", "Web-Benutzer nicht angelegt", err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderStatistics(el, stats) {
  const title = document.getElementById("admin-user-stats-title");
  if (title) title.textContent = `Statistik: ${stats.navidrome_username}`;
  if (!stats.has_data) {
    ccState.empty(el, "Noch keine Wiedergabedaten", `Für ${stats.navidrome_username} liegen in diesem Monat keine Daten vor.`);
    return;
  }
  const artists = stats.top_artists.slice(0, 5).map((a) => `
    <div class="list-group-item d-flex justify-content-between align-items-center">
      <span class="text-truncate">${_escapeHtml(a.label)}</span>
      <span class="badge bg-teal-lt">${_escapeHtml(String(a.count))}</span>
    </div>`).join("");
  el.innerHTML = `
    <div class="datagrid mb-3">
      <div class="datagrid-item"><div class="datagrid-title">Wiedergaben (Monat)</div><div class="datagrid-content h3 mb-0">${_escapeHtml(String(stats.total_plays))}</div></div>
      <div class="datagrid-item"><div class="datagrid-title">Navidrome-Nutzer</div><div class="datagrid-content">${_escapeHtml(stats.navidrome_username)}</div></div>
    </div>
    <div class="subheader mb-2">Top-Artists</div>
    <div class="list-group">${artists}</div>
  `;
}

async function loadUserStatsForAdmin(navidromeUser) {
  const el = document.getElementById("admin-user-stats-content");
  const panel = document.getElementById("admin-user-stats-offcanvas");
  const title = document.getElementById("admin-user-stats-title");
  if (title) title.textContent = `Statistik: ${navidromeUser}`;
  ccState.loading(el);
  const Offcanvas = window.tabler && window.tabler.Offcanvas;
  if (Offcanvas && panel) Offcanvas.getOrCreateInstance(panel).show();
  await _loadInto(
    "admin-user-stats-content",
    `/api/v1/statistics/${encodeURIComponent(navidromeUser)}?period=month`,
    renderStatistics,
  );
}

document.getElementById("admin-users-content").addEventListener("click", (event) => {
  const btn = event.target.closest(".view-stats-btn");
  if (!btn) return;
  loadUserStatsForAdmin(btn.dataset.navidromeUser);
});

// ── Init ─────────────────────────────────────────────────────────────────

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadSystemStatus();
    loadBotOperationStatus();
    loadMaintenanceStatus();
    loadDuplicateCacheStats();
    loadRuntimeSnapshot();
    loadAdminUsers();

    document.getElementById("admin-duplicates-clear-btn")?.addEventListener("click", clearDuplicateCache);
    document.getElementById("admin-web-user-form")?.addEventListener("submit", createWebUser);
    document.getElementById("admin-maintenance-toggle-btn")?.addEventListener("click", toggleMaintenance);
    document.getElementById("admin-bot-restart-btn")?.addEventListener("click", restartBot);

    const backupTypeEl = document.getElementById("admin-backup-type");
    const getBackupType = () => backupTypeEl?.value || "bot";

    document.getElementById("admin-backup-status")?.addEventListener("click", (event) => {
      const button = event.target.closest(".admin-backup-delete");
      if (!button) return;
      deleteBackup(button.dataset.backupName, getBackupType());
    });

    loadBackups(getBackupType());
    document.getElementById("admin-backup-create-btn")?.addEventListener("click", () => createBackup(getBackupType()));
    document.getElementById("admin-backup-manage-btn")?.addEventListener("click", () => loadBackups(getBackupType()));
    backupTypeEl?.addEventListener("change", () => loadBackups(getBackupType()));
  });
}
initPage();
