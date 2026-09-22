// control_center/static/pages/admin.js
// Administration-Seite: Nutzer/Rollen + System Status + Bot-Operationen.
// Nutzt die gemeinsamen Helfer aus common.js (apiUrl(), _loadInto(),
// _escapeHtml(), checkAuth()) und die Admin-APIs unter /api/v1/admin.
//

function renderSystemStatus(el, data) {
  const cpuEl = document.getElementById("admin-system-cpu");
  const memoryEl = document.getElementById("admin-system-memory");
  const diskEl = document.getElementById("admin-system-disk");
  const botEl = document.getElementById("admin-system-bot");
  const errorEl = document.getElementById("admin-system-status-error");

  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  if (cpuEl) {
    cpuEl.textContent = `${Number(data.cpu_percent).toFixed(1)} %`;
  }

  if (memoryEl) {
    memoryEl.textContent =
      `${Number(data.memory_percent).toFixed(1)} % · ` +
      `${Number(data.memory_used_mb).toFixed(0)} / ` +
      `${Number(data.memory_total_mb).toFixed(0)} MB`;
  }

  if (diskEl) {
    diskEl.textContent =
      `${Number(data.disk_percent).toFixed(1)} % · ` +
      `${Number(data.disk_used_gb).toFixed(1)} / ` +
      `${Number(data.disk_total_gb).toFixed(1)} GB`;
  }

  if (botEl) {
    const active = data.bot_service_active;

    if (active === true) {
      botEl.className = "status status-success";
      botEl.textContent = `${_escapeHtml(data.bot_service_name)} · Aktiv`;
    } else if (active === false) {
      botEl.className = "status status-danger";
      botEl.textContent = `${_escapeHtml(data.bot_service_name)} · Inaktiv`;
    } else {
      botEl.className = "status status-warning";
      botEl.textContent = `${_escapeHtml(data.bot_service_name)} · Unbekannt`;
    }
  }
}

async function loadSystemStatus() {
  const errorEl = document.getElementById("admin-system-status-error");

  try {
    const res = await fetch(
      apiUrl("/api/v1/admin/system/status"),
      { credentials: "same-origin" },
    );

    if (res.status === 401) {
      showOnly("login-view");
      return;
    }

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
        data?.detail ||
        `Fehler: ${res.status}`,
      );
    }

    renderSystemStatus(null, data);

    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
  } catch (err) {
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = `Systemstatus konnte nicht geladen werden: ${err.message}`;
    }
  }
}


function renderBackupList(el, data) {
  const backups = Array.isArray(data.backups) ? data.backups : [];

  if (!backups.length) {
    el.innerHTML = '<p class="empty-note mb-0">Keine Backups vorhanden.</p>';
    return;
  }

  const formatSize = (bytes) => {
    const value = Number(bytes);
    if (!Number.isFinite(value)) return "–";
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
    if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
    return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  el.innerHTML = `
    <div class="table-responsive">
      <table class="table table-vcenter table-sm mb-0">
        <thead>
          <tr>
            <th>Backup</th>
            <th>Größe</th>
            <th>Erstellt</th>
            <th class="w-1"></th>
          </tr>
        </thead>
        <tbody>
          ${backups.map((backup) => `
            <tr>
              <td class="text-truncate" style="max-width: 280px;">
                ${_escapeHtml(backup.name)}
              </td>
              <td class="text-secondary">${formatSize(backup.size)}</td>
              <td class="text-secondary">
                ${backup.created_at
                  ? new Date(backup.created_at).toLocaleString()
                  : "–"}
              </td>
              <td class="text-end">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-danger admin-backup-delete"
                  data-backup-name="${_escapeHtml(backup.name)}"
                  title="Backup löschen"
                  aria-label="Backup löschen"
                >
                  <svg xmlns="http://www.w3.org/2000/svg"
                       width="16" height="16"
                       viewBox="0 0 24 24"
                       fill="none"
                       stroke="currentColor"
                       stroke-width="2"
                       stroke-linecap="round"
                       stroke-linejoin="round">
                    <path d="M4 7h16"/>
                    <path d="M10 11v6"/>
                    <path d="M14 11v6"/>
                    <path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12"/>
                    <path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/>
                  </svg>
                </button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function deleteBackup(backupName, backupType) {
  const statusEl = document.getElementById("admin-backup-status");
  if (!statusEl || !backupName) return;

  if (!window.confirm(`Backup "${backupName}" wirklich löschen?`)) {
    return;
  }

  statusEl.innerHTML =
    '<span class="text-secondary">Backup wird gelöscht…</span>';

  try {
    const res = await fetch(
      apiUrl(`/api/v1/admin/backups/${encodeURIComponent(backupName)}`),
      {
        method: "DELETE",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      },
    );

    const body = await res.json().catch(() => null);

    if (!res.ok) {
      const message =
        body?.error?.message ||
        body?.detail ||
        `Fehler: ${res.status}`;
      throw new Error(message);
    }

    statusEl.innerHTML =
      '<span class="status status-success">Backup gelöscht.</span>';

    await loadBackups(backupType);
  } catch (err) {
    statusEl.innerHTML =
      `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
  }
}

function loadBackups(backupType = "bot") {
  return _loadInto(
    "admin-backup-status",
    `/api/v1/admin/backups?backup_type=${encodeURIComponent(backupType)}`,
    renderBackupList,
  );
}

async function createBackup(backupType = "bot") {
  const btn = document.getElementById("admin-backup-create-btn");
  const statusEl = document.getElementById("admin-backup-status");

  if (!btn || !statusEl) return;

  btn.disabled = true;
  statusEl.innerHTML = '<span class="text-secondary">Backup wird erstellt…</span>';

  try {
    const res = await fetch(apiUrl("/api/v1/admin/backups"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ backup_type: backupType }),
    });

    const body = await res.json().catch(() => null);

    if (!res.ok) {
      const message = body?.error?.message || body?.detail || `Fehler: ${res.status}`;
      throw new Error(message);
    }

    if (!body?.job_id) {
      throw new Error("Kein Job für das Backup erhalten.");
    }

    statusEl.innerHTML =
      '<span class="status status-info">Backup-Job gestartet…</span>';

    await pollBackupJob(body.job_id, backupType);
  } catch (err) {
    statusEl.innerHTML =
      `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
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

    const res = await fetch(apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}`), {
      credentials: "same-origin",
    });

    const job = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        job?.error?.message || job?.detail || `Job-Fehler: ${res.status}`,
      );
    }

    if (job.status === "succeeded") {
      statusEl.innerHTML =
        '<span class="status status-success">Backup erfolgreich erstellt.</span>';
      await loadBackups(backupType);
      return;
    }

    if (job.status === "failed") {
      throw new Error(job.error || "Backup fehlgeschlagen.");
    }

    if (job.status === "cancelled") {
      throw new Error("Backup wurde abgebrochen.");
    }

    const progress = Number(job.progress);
    statusEl.innerHTML =
      Number.isFinite(progress) && progress > 0
        ? `<span class="status status-info">Backup läuft… ${progress.toFixed(0)} %</span>`
        : '<span class="status status-info">Backup läuft…</span>';
  }

  throw new Error("Zeitüberschreitung beim Warten auf das Backup.");
}

async function loadMaintenanceStatus() {
  const statusEl = document.getElementById("admin-maintenance-status");
  const labelEl = document.getElementById("admin-maintenance-label");
  const buttonEl = document.getElementById("admin-maintenance-toggle-btn");
  const messageEl = document.getElementById("admin-maintenance-message");

  try {
    const res = await fetch(
      apiUrl("/api/v1/admin/maintenance"),
      { credentials: "same-origin" },
    );

    if (res.status === 401) {
      showOnly("login-view");
      return;
    }

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
        data?.detail ||
        `Fehler: ${res.status}`,
      );
    }

    const active = data.active === true;

    if (statusEl) {
      statusEl.className = active
        ? "status status-warning"
        : "status status-success";
      statusEl.textContent = active ? "Aktiv" : "Inaktiv";
    }

    if (labelEl) {
      labelEl.textContent = active
        ? "Wartungsmodus ist aktiv"
        : "Wartungsmodus ist deaktiviert";
    }

    if (buttonEl) {
      buttonEl.textContent = active
        ? "Wartungsmodus deaktivieren"
        : "Wartungsmodus aktivieren";
      buttonEl.className = active
        ? "btn btn-outline-success"
        : "btn btn-outline-warning";
    }

    if (messageEl) {
      messageEl.textContent = "";
    }
  } catch (err) {
    if (labelEl) {
      labelEl.textContent = "Wartungsstatus konnte nicht geladen werden.";
    }

    if (messageEl) {
      messageEl.innerHTML =
        `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
    }
  }
}

async function toggleMaintenance() {
  const buttonEl = document.getElementById("admin-maintenance-toggle-btn");
  const messageEl = document.getElementById("admin-maintenance-message");

  if (!buttonEl) return;

  const currentlyActive =
    buttonEl.textContent.includes("deaktivieren");

  buttonEl.disabled = true;

  if (messageEl) {
    messageEl.textContent = "Wartungsmodus wird geändert…";
  }

  try {
    const res = await fetch(apiUrl("/api/v1/admin/maintenance"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ active: !currentlyActive }),
    });

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
        data?.detail ||
        `Fehler: ${res.status}`,
      );
    }

    await loadMaintenanceStatus();
  } catch (err) {
    if (messageEl) {
      messageEl.innerHTML =
        `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
    }
  } finally {
    buttonEl.disabled = false;
  }
}

async function loadBotOperationStatus() {
  const statusEl = document.getElementById("admin-bot-operation-status");

  if (!statusEl) return;

  try {
    const res = await fetch(
      apiUrl("/api/v1/admin/system/status"),
      { credentials: "same-origin" },
    );

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
        data?.detail ||
        `Fehler: ${res.status}`,
      );
    }

    if (data.bot_service_active === true) {
      statusEl.innerHTML =
        '<span class="status status-success">Bot-Service aktiv</span>';
    } else if (data.bot_service_active === false) {
      statusEl.innerHTML =
        '<span class="status status-danger">Bot-Service inaktiv</span>';
    } else {
      statusEl.innerHTML =
        '<span class="status status-warning">Bot-Service-Status unbekannt</span>';
    }
  } catch (err) {
    statusEl.innerHTML =
      `<span class="text-danger">Status konnte nicht geladen werden: ${_escapeHtml(err.message)}</span>`;
  }
}

async function restartBot() {
  const statusEl = document.getElementById("admin-bot-operation-status");
  const buttonEl = document.getElementById("admin-bot-restart-btn");

  if (!buttonEl) return;

  if (!window.confirm(
    "Den Bot jetzt neu starten? Der Bot ist während des Neustarts kurz nicht erreichbar.",
  )) {
    return;
  }

  buttonEl.disabled = true;

  if (statusEl) {
    statusEl.textContent = "Bot-Neustart wird angefordert…";
  }

  try {
    const res = await fetch(apiUrl("/api/v1/admin/system/restart"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
        data?.detail ||
        `Fehler: ${res.status}`,
      );
    }

    if (statusEl) {
      statusEl.textContent =
        data?.message || "Neustart wird in Kürze ausgeführt.";
    }

    buttonEl.disabled = true;
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML =
        `<span class="text-danger">${_escapeHtml(err.message)}</span>`;
    }

    buttonEl.disabled = false;
  }
}

function renderAdminUsers(el, body) {
    if (!body.users.length) { el.innerHTML = '<p class="empty-note">Keine registrierten Nutzer.</p>'; return; }
    const roleBadge = { owner: "CRITICAL", admin: "ERROR", moderator: "WARNING", user: "INFO" };
    el.innerHTML = '<div class="row-list">' + body.users.map((u) => `
      <div class="row-item">
        <div class="row-main">
          <span class="badge badge-${roleBadge[u.role] || "INFO"}">${_escapeHtml(u.role)}</span>
          #${u.telegram_id}${u.navidrome_user ? " — 🎵 " + _escapeHtml(u.navidrome_user) : ""}
        </div>
        ${u.navidrome_user ? `<button class="small view-stats-btn" data-navidrome-user="${_escapeHtml(u.navidrome_user)}">Statistik</button>` : ""}
        <div class="row-count">${u.created_at ? new Date(u.created_at).toLocaleDateString() : "–"}</div>
      </div>
    `).join("") + "</div>";
  }
  function loadAdminUsers() {
    return _loadInto("admin-users-content", "/api/v1/admin/users", renderAdminUsers);
  }

  function renderStatistics(el, stats) {
    if (!stats.has_data) {
      el.innerHTML = `<p class="empty-note">Noch keine Wiedergabedaten für ${_escapeHtml(stats.navidrome_username)}.</p>`;
      return;
    }
    const artists = stats.top_artists.slice(0, 5).map((a) => `
      <div class="row-item"><div class="row-main">${_escapeHtml(a.label)}</div><div class="row-count">${a.count}</div></div>
    `).join("");
    el.innerHTML = `
      <p class="empty-note">${stats.total_plays} Wiedergaben (${_escapeHtml(stats.navidrome_username)})</p>
      <div class="row-list">${artists}</div>
    `;
  }

  async function loadUserStatsForAdmin(navidromeUser) {
    const el = document.getElementById("admin-user-stats-content");
    el.hidden = false;
    el.innerHTML = '<span class="empty-note">Lädt…</span>';
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

  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
      loadSystemStatus();
      loadBotOperationStatus();
      loadMaintenanceStatus();
      loadAdminUsers();

      document
        .getElementById("admin-maintenance-toggle-btn")
        ?.addEventListener("click", toggleMaintenance);

      document
        .getElementById("admin-bot-restart-btn")
        ?.addEventListener("click", restartBot);

      const backupTypeEl = document.getElementById("admin-backup-type");
    const getBackupType = () => backupTypeEl?.value || "bot";

    document
      .getElementById("admin-backup-status")
      ?.addEventListener("click", (event) => {
        const button = event.target.closest(".admin-backup-delete");
        if (!button) return;

        const backupName = button.dataset.backupName;
        deleteBackup(backupName, getBackupType());
      });

    loadBackups(getBackupType());

    document.getElementById("admin-backup-create-btn")?.addEventListener(
      "click",
      () => createBackup(getBackupType()),
    );

    document.getElementById("admin-backup-manage-btn")?.addEventListener(
      "click",
      () => loadBackups(getBackupType()),
    );

    backupTypeEl?.addEventListener(
      "change",
      () => loadBackups(getBackupType()),
    );
    });
  }
  initPage();
