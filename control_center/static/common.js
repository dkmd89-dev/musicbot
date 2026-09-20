// control_center/static/common.js
// Gemeinsame JS-Helfer fuer alle Control-Center-Seiten (ui_prompt.txt
// Phase 1 "UI STRUCTURE REDESIGN"). Aus dem vorherigen Einzel-Dashboard
// (dashboard.html) unveraendert extrahiert, um Duplikation ueber jetzt
// 12 Seiten hinweg zu vermeiden - weiterhin Vanilla JS, keine Bibliothek,
// kein Build-Schritt (Master-Prompt Abschnitt 7).
//
// Jede Seite definiert eine eigene Funktion `initPage()` (in ihrem
// eigenen {% block scripts %}), die checkAuth() aufruft und danach ihre
// seiteneigenen load*()-Funktionen startet. onTelegramAuth() (unten)
// ruft nach erfolgreichem Login dieselbe seiteneigene initPage() erneut
// auf.

const VIEWS = ["loading-view", "login-view", "dashboard-view", "error-view"];
function showOnly(id) {
  VIEWS.forEach((v) => {
    const el = document.getElementById(v);
    if (el) el.hidden = (v !== id);
  });
}
function showError(msg) {
  const el = document.getElementById("error-view");
  if (el) el.textContent = msg;
  showOnly("error-view");
}

// Sicherheitshinweis (galt schon im vorherigen Einzel-Dashboard): Titel/
// Artist/Pfad/Message-Felder stammen aus Library-/Download-Metadaten
// (z. B. YouTube-Videotiteln) - nicht vertrauenswuerdig genug, um sie
// ungefiltert per innerHTML einzubetten (XSS, falls ein Titel HTML/
// Script enthaelt). Alle render*()-Funktionen escapen freien Text
// konsequent damit.
function _escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Gemeinsamer Lade-/Fehlerbehandlungs-Pfad fuer read-only-Bereiche -
// einheitliches Status-Handling (401/403/404/Netzwerkfehler) auf allen
// Seiten.
async function _loadInto(elementId, url, renderFn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  try {
    const res = await fetch(url, { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return; }
    if (res.status === 403) {
      el.innerHTML = '<span class="denied">Keine Berechtigung (Rolle reicht nicht).</span>';
      return;
    }
    if (res.status === 404) {
      const body = await res.json().catch(() => null);
      el.innerHTML = `<span class="empty-note">${body && body.error ? body.error.message : "Nicht gefunden."}</span>`;
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      el.textContent = "Fehler: " + (body && body.error ? body.error.message : res.status);
      return;
    }
    renderFn(el, await res.json());
  } catch (err) {
    el.textContent = "Netzwerkfehler: " + err.message;
  }
}

// Prueft die Anmeldung (GET /api/v1/auth/whoami), zeigt Login-/Error-
// View bei Bedarf und schaltet sonst auf die Dashboard-View um. Liefert
// das whoami-Objekt zurueck (oder null, wenn bereits eine andere View
// angezeigt wurde) - jede Seite ruft danach ihre eigenen load*()-
// Funktionen auf.
async function checkAuth() {
  showOnly("loading-view");
  try {
    const res = await fetch("/api/v1/auth/whoami", { credentials: "same-origin" });
    if (res.status === 401) { showOnly("login-view"); return null; }
    if (!res.ok) { showError("Anmeldestatus konnte nicht geprüft werden."); return null; }
    const who = await res.json();
    const userEl = document.getElementById("current-user");
    if (userEl) userEl.textContent = `Angemeldet als #${who.user_id} (${who.access_level})`;
    showOnly("dashboard-view");
    return who;
  } catch (err) {
    showError("Netzwerkfehler: " + err.message);
    return null;
  }
}

function onTelegramAuth(user) {
  fetch("/api/v1/auth/telegram-callback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(user),
  })
    .then((res) => {
      if (res.ok) {
        if (typeof initPage === "function") initPage();
      } else {
        showError("Telegram-Login fehlgeschlagen.");
      }
    })
    .catch((err) => showError("Netzwerkfehler: " + err.message));
}

// Mobile Sidebar-Drawer (Master-Prompt Abschnitt 12 "RESPONSIVE
// NAVIGATION") - reines CSS-Klassen-Toggle, keine Bibliothek.
function _initSidebarToggle() {
  const toggleBtn = document.getElementById("sidebar-toggle");
  if (!toggleBtn) return;
  toggleBtn.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open");
  });
  document.getElementById("sidebar")?.addEventListener("click", (event) => {
    if (event.target.closest("a")) document.body.classList.remove("sidebar-open");
  });
}
document.addEventListener("DOMContentLoaded", _initSidebarToggle);
