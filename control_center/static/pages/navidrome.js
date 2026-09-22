// control_center/static/pages/navidrome.js
// Navidrome-Seite: Verbindungsstatus + manueller Library-Scan.
// Nutzt Tabler-Komponenten (card, status) und die Helfer aus common.js.

function renderNavidromeStatus(el, data) {
  // _loadInto() ruft renderFn(el, body) - zwei Argumente wie in health.js.
  // el = Container-Element, data = JSON-Antwort von /api/v1/navidrome/status.
  const connectedEl = document.getElementById("navidrome-status");
  const statusEl    = document.getElementById("navidrome-connected-status");
  const countEl     = document.getElementById("navidrome-artist-count");

  if (data.connected) {
    connectedEl.textContent = "Online";
    statusEl.className = "status status-success";
    statusEl.textContent = "Navidrome erreichbar";
  } else {
    connectedEl.textContent = "Offline";
    statusEl.className = "status status-danger";
    statusEl.textContent = "Nicht erreichbar";
  }

  countEl.textContent = data.artist_count != null
    ? _escapeHtml(String(data.artist_count))
    : "–";
}

function _navidromeEndpoints() {
  const el = document.getElementById("navidrome-status-row");
  return {
    status: el?.dataset.statusEndpoint || "/api/v1/navidrome/status",
    scan:   el?.dataset.scanEndpoint   || "/api/v1/navidrome/scan",
  };
}

function loadNavidromeStatus() {
  const { status } = _navidromeEndpoints();
  return _loadInto(
    "navidrome-status-row",
    status,
    renderNavidromeStatus,
    loadNavidromeStatus
  );
}

async function triggerNavidromeScan() {
  const btn = document.getElementById("navidrome-scan-btn");
  const out = document.getElementById("navidrome-scan-output");
  if (!btn || !out) return;

  btn.disabled = true;
  out.textContent = "Scan läuft…";

  try {
    const res = await fetch(apiUrl(_navidromeEndpoints().scan), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });

    if (res.status === 403) {
      out.textContent = "❌ Keine Berechtigung (Admin erforderlich).";
      return;
    }
    if (!res.ok) {
      out.textContent = `❌ HTTP ${res.status}`;
      return;
    }

    const data = await res.json();
    out.textContent = data.success
      ? `✅ Scan erfolgreich (rc=${data.returncode})\n${data.stdout || ""}`
      : `❌ Scan fehlgeschlagen (rc=${data.returncode})\n${data.stderr || ""}`;
    loadNavidromeStatus();
  } catch (err) {
    out.textContent = `❌ Fehler: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function initPage() {
  checkAuth().then((who) => {
    if (!who) return;
    loadNavidromeStatus();
    document
      .getElementById("navidrome-scan-btn")
      ?.addEventListener("click", triggerNavidromeScan);
  });
}
initPage();
